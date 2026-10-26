import asyncio
import logging
import re
from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Literal
from uuid import UUID

from fastapi.sse import ServerSentEvent
from opentelemetry import trace
from opentelemetry.trace import StatusCode
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ai_service import prompts
from ai_service.core.logging import request_id
from ai_service.knowledge_base import SPAN_KIND, Domain, Hit, KnowledgeBase
from ai_service.llm import LlmError, LlmProvider, Message, Token, ToolCall, Usage
from ai_service.tools import untrusted

AnswerStatus = Literal["answered", "abstained", "no_kb"]
HISTORY_TOKEN_BUDGET = 2000
PROMPT = prompts.load("rag-system")
_CITATION = re.compile(r"\[(\d+)\]")
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class EventModel(BaseModel):
    """SSE payloads (plan.md §7.3): camelCase, relayed unchanged to the browser."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        serialize_by_alias=True,
        json_schema_serialization_defaults_required=True,
    )


class Source(EventModel):
    n: int
    doc_id: UUID
    title: str
    page: int | None
    heading: str | None
    domains: list[Domain]
    text: str
    score: float


class SourcesEvent(EventModel):
    sources: list[Source]


class TokenEvent(EventModel):
    text: str


class UsageInfo(EventModel):
    input_tokens: int
    output_tokens: int
    cost_usd: float | None


class DoneEvent(EventModel):
    usage: UsageInfo | None
    model: str | None
    trace_id: str | None


class ErrorEvent(EventModel):
    type: str
    title: str
    detail: str


def build_messages(turns: list[ChatTurn], hits: list[Hit]) -> list[Message]:
    """System rules, the newest history within the budget, then sources + question."""
    *history, question = turns
    sources = "".join(render_source(n, hit) for n, hit in enumerate(hits, 1))
    return [
        {"role": "system", "content": PROMPT.text},
        *history_messages(history),
        {
            "role": "user",
            "content": f"<sources>\n{sources}</sources>\n\nQuestion: {question.content}",
        },
    ]


def history_messages(history: list[ChatTurn]) -> list[Message]:
    """The newest turns within the history budget."""
    # shortcut: ~4 chars/token, use a tokenizer if budgets get tight
    budget = HISTORY_TOKEN_BUDGET * 4
    kept: list[ChatTurn] = []
    for turn in reversed(history):
        budget -= len(turn.content)
        if budget < 0:
            break
        kept.insert(0, turn)
    if kept and kept[0].role == "assistant":
        kept.pop(0)  # some providers require the first turn to be the user's
    return [_message(turn) for turn in kept]


def render_source(n: int, hit: Hit) -> str:
    text = untrusted(f"Document: {hit.title} · {_location(hit)}\n{hit.text}")
    scope = f' canonical="{" ".join(hit.priority_topics)}"' if hit.priority == "canonical" else ""
    return f'<source n="{n}"{scope}>\n{text}\n</source>\n'


def invalid_citations(answer: str, source_count: int) -> list[int]:
    """Cited `[n]` without a matching source."""
    return [n for n in map(int, _CITATION.findall(answer)) if not 1 <= n <= source_count]


def answer_status(answer: str, source_count: int, searched: bool) -> AnswerStatus:
    """Gap signal (D49): derived from the turn, never reported by the model."""
    if not searched:
        return "no_kb"
    cited = len(_CITATION.findall(answer)) > len(invalid_citations(answer, source_count))
    return "answered" if cited else "abstained"


def _location(hit: Hit) -> str:
    return hit.heading or (f"page {hit.page}" if hit.page else "")


def _message(turn: ChatTurn) -> Message:
    if turn.role == "user":
        return {"role": "user", "content": turn.content}
    return {"role": "assistant", "content": turn.content}


def _error(type_: str, title: str, detail: str) -> ServerSentEvent:
    return ServerSentEvent(event="error", data=ErrorEvent(type=type_, title=title, detail=detail))


class ChatPipeline:
    """Embed question → search → grounded prompt → LLM stream, as SSE events (plan.md §5)."""

    def __init__(
        self, kb: KnowledgeBase, llm: LlmProvider, top_k: int, score_threshold: float | None
    ) -> None:
        self.kb = kb
        self.llm = llm
        self.top_k = top_k
        self.score_threshold = score_threshold

    async def stream(
        self,
        turns: list[ChatTurn],
        domains: list[Domain] | None,
        user_id: str,
        model_id: str | None = None,
    ) -> AsyncGenerator[ServerSentEvent]:
        question = turns[-1].content
        attributes = {SPAN_KIND: "CHAIN", "input.value": question, "user.id": user_id}
        with tracer.start_as_current_span("chat", attributes=attributes) as span:
            usage: Usage | None = None
            try:
                hits = await asyncio.to_thread(
                    self.kb.search, question, self.top_k, self.score_threshold, domains
                )
                sources = [
                    Source.model_validate({"n": n, **hit.model_dump()})
                    for n, hit in enumerate(hits, 1)
                ]
                yield ServerSentEvent(event="sources", data=SourcesEvent(sources=sources))
                # aclosing: a client disconnect closes the provider stream, cancelling the LLM call.
                messages = build_messages(turns, hits)
                async with aclosing(self.llm.stream_chat(messages, model=model_id)) as events:
                    async for event in events:
                        match event:
                            case Token(text=text):
                                yield ServerSentEvent(event="token", data=TokenEvent(text=text))
                            case Usage():
                                usage = event
                            case LlmError(detail=detail):
                                span.set_status(StatusCode.ERROR, detail)
                                yield _error("llm", "LLM request failed", detail)
                                return
                            case ToolCall():
                                pass  # no tools offered
            except Exception as error:
                logger.exception("chat failed")
                span.set_status(StatusCode.ERROR, str(error))
                yield _error(
                    "internal", "Chat failed", f"See the AI service log ({request_id.get()})"
                )
                return
            if usage:
                logger.info(
                    "chat model=%s input_tokens=%d output_tokens=%d cost_usd=%s",
                    usage.model,
                    usage.input_tokens,
                    usage.output_tokens,
                    usage.cost_usd,
                )
            context = span.get_span_context()
            done = DoneEvent(
                usage=UsageInfo(
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cost_usd=usage.cost_usd,
                )
                if usage
                else None,
                model=usage.model if usage else None,
                trace_id=format(context.trace_id, "032x") if context.is_valid else None,
            )
            yield ServerSentEvent(event="done", data=done)
