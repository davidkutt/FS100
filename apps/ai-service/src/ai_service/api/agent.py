from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field, field_validator, model_validator

from ai_service.agent import Agent, Resume, Resumed, rag_turn
from ai_service.api.chat import get_pipeline
from ai_service.approvals import ApprovalError
from ai_service.catalog import ModelInfo
from ai_service.core.auth import Caller, get_caller
from ai_service.knowledge_base import Domain
from ai_service.rag import ChatPipeline, ChatTurn
from ai_service.tools import permitted

router = APIRouter(prefix="/v1", tags=["agent"])


def get_agent(request: Request) -> Agent:
    return request.app.state.agent


def get_models(request: Request) -> dict[str, ModelInfo]:
    return request.app.state.models


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
    model: str | None = None  # registry id (D40); None = LLM_MODEL
    domains: list[Domain] | None = None
    resume: Resume | None = None  # continues the turn that proposed the action

    @model_validator(mode="after")
    def resume_needs_agent(self) -> "AgentRequest":
        if self.resume and self.mode != "agent":
            raise ValueError("resume needs mode=agent")
        return self

    @field_validator("messages")
    @classmethod
    def ends_with_user(cls, messages: list[AgentMessage]) -> list[AgentMessage]:
        if messages[-1].role != "user":
            raise ValueError("the last message must come from the user")
        for message in messages:
            message.turn()  # the joined parts must fit ChatTurn's length limit
        return messages


def selected_model(
    body: AgentRequest,
    models: Annotated[dict[str, ModelInfo], Depends(get_models)],
    caller: Annotated[Caller, Depends(get_caller)],
) -> str | None:
    """A dependency, because errors raised inside the stream would follow a 200."""
    entry = models.get(body.model) if body.model else None
    if body.model and (
        entry is None
        or not permitted(entry.min_role, caller.roles)
        or (body.mode == "agent" and not entry.supports_tools)
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Model {body.model} is not available"
        )
    return body.model


def resumed(
    body: AgentRequest,
    agent: Annotated[Agent, Depends(get_agent)],
    caller: Annotated[Caller, Depends(get_caller)],
) -> Resumed | None:
    """Verified before the stream starts, like `selected_model`."""
    if body.resume is None:
        return None
    try:
        return agent.resume(body.resume, caller, body.conversation_id, body.domains)
    except ApprovalError as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Invalid approval: {error}"
        ) from error


@router.post("/agent", response_class=EventSourceResponse)
async def agent(
    agent: Annotated[Agent, Depends(get_agent)],
    pipeline: Annotated[ChatPipeline, Depends(get_pipeline)],
    caller: Annotated[Caller, Depends(get_caller)],
    body: AgentRequest,
    model: Annotated[str | None, Depends(selected_model)],
    resume: Annotated[Resumed | None, Depends(resumed)],
) -> AsyncGenerator[ServerSentEvent]:
    """Agent turn, SSE v2: `step`, `tool_call`, `tool_result`, `sources`, `token`…, `done`
    (plan-phase-2 §7.3); a write call ends it with `approval_required`, and `resume` continues
    it. `mode=rag` runs the Phase 1 pipeline and ends with the same `done`."""
    turns = [message.turn() for message in body.messages]
    events = (
        rag_turn(pipeline, turns, body.domains, caller.sub, model)
        if body.mode == "rag"
        else agent.stream(turns, body.domains, caller, body.conversation_id, model, resume)
    )
    async with aclosing(events) as stream:
        async for event in stream:
            yield event
