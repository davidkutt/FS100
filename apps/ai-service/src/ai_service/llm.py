import json
import re
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Protocol

import openai
from openai.types import CompletionUsage
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam
from openai.types.chat.parsed_chat_completion import ParsedChatCompletion
from pydantic import BaseModel, ValidationError

from ai_service.core.settings import Settings

Message = ChatCompletionMessageParam


@dataclass(frozen=True)
class Token:
    text: str


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON as the model wrote it, possibly invalid


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    model: str
    cached_tokens: int = 0


@dataclass(frozen=True)
class LlmError:
    detail: str


LlmEvent = Token | ToolCall | Usage | LlmError


class LlmProvider(Protocol):
    def stream_chat(
        self,
        messages: list[Message],
        tools: list[ChatCompletionToolParam] | None = None,
        session_id: str | None = None,
        model: str | None = None,  # None = LLM_MODEL
    ) -> AsyncGenerator[LlmEvent]: ...


class StructuredLlm(Protocol):
    async def complete_json[T: BaseModel](
        self, messages: list[Message], schema: type[T], model: str | None = None
    ) -> tuple[T, Usage]: ...


def _usage(usage: CompletionUsage, model: str) -> Usage:
    cost = (usage.model_extra or {}).get("cost")  # OpenRouter only
    details = usage.prompt_tokens_details
    return Usage(
        usage.prompt_tokens,
        usage.completion_tokens,
        None if cost is None else float(cost),
        model,
        (details.cached_tokens if details else None) or 0,
    )


class OpenAICompatProvider:
    """Any OpenAI-compatible endpoint: OpenRouter, HF router, later Ollama/vLLM (D11)."""

    def __init__(self, client: openai.AsyncOpenAI, model: str, max_output_tokens: int) -> None:
        self._client = client
        self._model = model
        self._max_output_tokens = max_output_tokens

    async def stream_chat(
        self,
        messages: list[Message],
        tools: list[ChatCompletionToolParam] | None = None,
        session_id: str | None = None,
        model: str | None = None,  # None = LLM_MODEL
    ) -> AsyncGenerator[LlmEvent]:
        extra: dict[str, object] = {}
        if tools:
            # No `parallel_tool_calls`: with require_parameters it filters out all (ADR-0007).
            extra["provider"] = {"require_parameters": True}
        if session_id:
            extra["session_id"] = session_id  # OpenRouter sticky routing → prompt-cache hits
        calls: dict[int, dict[str, str]] = {}
        try:
            stream = await self._client.chat.completions.create(
                model=model or self._model,
                messages=messages,
                max_tokens=self._max_output_tokens,
                stream=True,
                stream_options={"include_usage": True},
                tools=tools or openai.omit,
                extra_body=extra or None,
            )
            # Closing the stream drops the HTTP connection, which stops generation upstream.
            async with stream:
                async for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        yield Token(delta.content)
                    # A call's arguments arrive in many fragments; parallel calls differ by index.
                    for part in (delta and delta.tool_calls) or []:
                        call = calls.setdefault(part.index, {"id": "", "name": "", "arguments": ""})
                        call["id"] = call["id"] or part.id or ""
                        if part.function:
                            call["name"] = call["name"] or part.function.name or ""
                            call["arguments"] += part.function.arguments or ""
                    if chunk.usage:
                        yield _usage(chunk.usage, chunk.model)
        except openai.APIError as error:
            yield LlmError(str(error))
            return
        for index, call in sorted(calls.items()):
            yield ToolCall(call["id"] or f"call_{index}", call["name"], call["arguments"])

    async def complete_json[T: BaseModel](
        self, messages: list[Message], schema: type[T], model: str | None = None
    ) -> tuple[T, Usage]:
        """Structured output (D41): the JSON Schema goes with the request, Pydantic checks the
        reply, and an invalid reply gets one retry with the error."""
        try:
            completion = await self._parse(messages, schema, model)
        except ValidationError as error:
            correction = f"That reply did not match the schema: {error}\nReply with valid JSON."
            retry: list[Message] = [*messages, {"role": "user", "content": correction}]
            completion = await self._parse(retry, schema, model)
        message = completion.choices[0].message
        if message.parsed is None:
            raise ValueError(message.refusal or "no structured reply")
        if completion.usage is None:
            return message.parsed, Usage(0, 0, None, completion.model)
        return message.parsed, _usage(completion.usage, completion.model)

    async def _parse[T: BaseModel](
        self, messages: list[Message], schema: type[T], model: str | None
    ) -> ParsedChatCompletion[T]:
        return await self._client.chat.completions.parse(
            model=model or self._model,
            messages=messages,
            response_format=schema,
            max_tokens=self._max_output_tokens,
            extra_body={"provider": {"require_parameters": True}},
        )


class FakeProvider:
    """Deterministic and free (tests, CI, e2e): proposes `ingest_url` for "Add <url>", else
    searches once if it may, then cites every source."""

    async def stream_chat(
        self,
        messages: list[Message],
        tools: list[ChatCompletionToolParam] | None = None,
        session_id: str | None = None,
        model: str | None = None,  # None = LLM_MODEL
    ) -> AsyncGenerator[LlmEvent]:
        names = [t["function"]["name"] for t in tools or []]
        search = next((n for n in names if n.endswith("search_knowledge_base")), None)
        ingest = next((n for n in names if n.endswith("ingest_url")), None)
        question = str(messages[-1].get("content"))
        call = None
        if messages[-1]["role"] == "user":
            if ingest and (url := re.search(r"\badd (https?://\S+)", question, re.IGNORECASE)):
                call = ToolCall("fake-1", ingest, json.dumps({"url": url[1], "domains": ["dev"]}))
            elif search:
                call = ToolCall("fake-1", search, json.dumps({"query": question}))
        if call:
            yield call
            yield Usage(0, 0, None, "fake")
            return
        sources = re.findall(r'<source n="(\d+)">', question)
        answer = (
            f"Fake answer based on {' '.join(f'[{n}]' for n in sources)}."
            if sources
            else "Not in the knowledge base (fake provider)."
        )
        for word in answer.split(" "):
            yield Token(word + " ")
        yield Usage(0, 0, None, "fake")

    async def complete_json[T: BaseModel](
        self, messages: list[Message], schema: type[T], model: str | None = None
    ) -> tuple[T, Usage]:
        raise NotImplementedError("the fake provider has no structured output (ROUTER=embedding)")


def create_provider(settings: Settings) -> OpenAICompatProvider | FakeProvider:
    if settings.llm_provider == "fake":
        return FakeProvider()
    if not settings.llm_api_key or not settings.llm_model:
        raise ValueError("LLM_PROVIDER=openai_compat needs LLM_API_KEY and LLM_MODEL (or use fake)")
    # The SDK retries 408/409/429/5xx and connection errors with exponential backoff.
    client = openai.AsyncOpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout=settings.llm_timeout_s,
        max_retries=3,
    )
    return OpenAICompatProvider(client, settings.llm_model, settings.llm_max_output_tokens)
