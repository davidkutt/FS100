import re
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Protocol

import openai
from openai.types.chat import ChatCompletionMessageParam

from ai_service.core.settings import Settings

Message = ChatCompletionMessageParam


@dataclass(frozen=True)
class Token:
    text: str


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    model: str


@dataclass(frozen=True)
class LlmError:
    detail: str


LlmEvent = Token | Usage | LlmError  # Phase 2 adds tool calls


class LlmProvider(Protocol):
    def stream_chat(self, messages: list[Message]) -> AsyncGenerator[LlmEvent]: ...


class OpenAICompatProvider:
    """Any OpenAI-compatible endpoint: OpenRouter, HF router, later Ollama/vLLM (D11)."""

    def __init__(self, client: openai.AsyncOpenAI, model: str, max_output_tokens: int) -> None:
        self._client = client
        self._model = model
        self._max_output_tokens = max_output_tokens

    async def stream_chat(self, messages: list[Message]) -> AsyncGenerator[LlmEvent]:
        try:
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=self._max_output_tokens,
                stream=True,
                stream_options={"include_usage": True},
            )
            # Closing the stream drops the HTTP connection, which stops generation upstream.
            async with stream:
                async for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield Token(chunk.choices[0].delta.content)
                    if chunk.usage:
                        cost = (chunk.usage.model_extra or {}).get("cost")  # OpenRouter only
                        yield Usage(
                            chunk.usage.prompt_tokens,
                            chunk.usage.completion_tokens,
                            None if cost is None else float(cost),
                            chunk.model,
                        )
        except openai.APIError as error:
            yield LlmError(str(error))


class FakeProvider:
    """Deterministic and free (tests, CI, e2e): cites every source in the prompt."""

    async def stream_chat(self, messages: list[Message]) -> AsyncGenerator[LlmEvent]:
        sources = re.findall(r'<source n="(\d+)">', str(messages[-1].get("content")))
        answer = (
            f"Fake answer based on {' '.join(f'[{n}]' for n in sources)}."
            if sources
            else "Not in the knowledge base (fake provider)."
        )
        for word in answer.split(" "):
            yield Token(word + " ")
        yield Usage(0, 0, None, "fake")


def create_provider(settings: Settings) -> LlmProvider:
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
