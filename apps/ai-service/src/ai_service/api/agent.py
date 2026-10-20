from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field, field_validator

from ai_service.agent import Agent, rag_turn
from ai_service.api.chat import UserContext, get_pipeline
from ai_service.knowledge_base import Domain
from ai_service.rag import ChatPipeline, ChatTurn

router = APIRouter(prefix="/v1", tags=["agent"])


def get_agent(request: Request) -> Agent:
    return request.app.state.agent


class TextPart(BaseModel):
    type: Literal["text"]
    text: str = Field(min_length=1)


class AgentMessage(BaseModel):
    role: Literal["user", "assistant"]
    parts: list[TextPart] = Field(min_length=1)

    def turn(self) -> ChatTurn:
        return ChatTurn(role=self.role, content="\n\n".join(part.text for part in self.parts))


class AgentRequest(BaseModel):
    conversation_id: UUID
    messages: list[AgentMessage] = Field(min_length=1)
    mode: Literal["agent", "rag"] = "agent"
    domains: list[Domain] | None = None
    user: UserContext

    @field_validator("messages")
    @classmethod
    def ends_with_user(cls, messages: list[AgentMessage]) -> list[AgentMessage]:
        if messages[-1].role != "user":
            raise ValueError("the last message must come from the user")
        for message in messages:
            message.turn()  # the joined parts must fit ChatTurn's length limit
        return messages


@router.post("/agent", response_class=EventSourceResponse)
async def agent(
    agent: Annotated[Agent, Depends(get_agent)],
    pipeline: Annotated[ChatPipeline, Depends(get_pipeline)],
    body: AgentRequest,
) -> AsyncGenerator[ServerSentEvent]:
    """Agent turn, SSE v2: `step`, `tool_call`, `tool_result`, `sources`, `token`…, `done`
    (plan-phase-2 §7.3). `mode=rag` runs the Phase 1 pipeline and ends with the same `done`."""
    turns = [message.turn() for message in body.messages]
    events = (
        rag_turn(pipeline, turns, body.domains, body.user.sub)
        if body.mode == "rag"
        else agent.stream(turns, body.domains, body.user.roles, body.user.sub, body.conversation_id)
    )
    async with aclosing(events) as stream:
        async for event in stream:
            yield event
