from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field, field_validator

from ai_service.knowledge_base import Domain
from ai_service.rag import ChatPipeline, ChatTurn

router = APIRouter(prefix="/v1", tags=["chat"])


def get_pipeline(request: Request) -> ChatPipeline:
    return request.app.state.chat


class UserContext(BaseModel):
    sub: str
    roles: list[str]


class ChatRequest(BaseModel):
    messages: list[ChatTurn] = Field(min_length=1)
    domains: list[Domain] | None = None
    user: UserContext

    @field_validator("messages")
    @classmethod
    def ends_with_user(cls, messages: list[ChatTurn]) -> list[ChatTurn]:
        if messages[-1].role != "user":
            raise ValueError("the last message must come from the user")
        return messages


@router.post("/chat", response_class=EventSourceResponse)
async def chat(
    pipeline: Annotated[ChatPipeline, Depends(get_pipeline)], body: ChatRequest
) -> AsyncGenerator[ServerSentEvent]:
    """Grounded chat: `sources`, `token`…, then `done` or `error` (plan.md §7.3)."""
    async with aclosing(pipeline.stream(body.messages, body.domains, body.user.sub)) as events:
        async for event in events:
            yield event
