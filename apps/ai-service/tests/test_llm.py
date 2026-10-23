"""`openai_compat` against a mocked OpenAI-compatible endpoint (no network)."""

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx2
import openai
import pytest
from openai.types.chat import ChatCompletionToolParam
from pydantic import BaseModel, Field, ValidationError

from ai_service.llm import (
    LlmError,
    LlmEvent,
    Message,
    OpenAICompatProvider,
    Token,
    ToolCall,
    Usage,
)

Handler = Callable[[httpx2.Request], httpx2.Response]
TOOL: ChatCompletionToolParam = {
    "type": "function",
    "function": {"name": "kb_search", "parameters": {"type": "object"}},
}


def stream(
    handler: Handler,
    tools: list[ChatCompletionToolParam] | None = None,
    session_id: str | None = None,
) -> list[LlmEvent]:
    client = openai.AsyncOpenAI(
        base_url="https://llm.test/v1",
        api_key="test",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    provider = OpenAICompatProvider(client, "test/model", 100)

    async def collect() -> list[LlmEvent]:
        messages: list[Message] = [{"role": "user", "content": "Hi"}]
        return [event async for event in provider.stream_chat(messages, tools, session_id)]

    return asyncio.run(collect())


def chunk(**fields: Any) -> str:
    base = {"id": "c", "object": "chat.completion.chunk", "created": 0, "model": "test/model"}
    return f"data: {json.dumps({**base, **fields})}\n\n"


def test_streams_tokens_then_usage_with_openrouter_cost() -> None:
    requests: list[Any] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(json.loads(request.content))
        body = (
            chunk(choices=[{"index": 0, "delta": {"content": "Hel"}}])
            + chunk(choices=[{"index": 0, "delta": {"content": "lo"}, "finish_reason": "stop"}])
            + chunk(choices=[], usage={"prompt_tokens": 12, "completion_tokens": 2, "cost": 1e-4})
            + "data: [DONE]\n\n"
        )
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, text=body)

    events = stream(handler)

    assert events == [Token("Hel"), Token("lo"), Usage(12, 2, 1e-4, "test/model")]
    assert requests[0]["max_tokens"] == 100
    assert requests[0]["stream_options"] == {"include_usage": True}
    assert not {"tools", "provider", "session_id"} & requests[0].keys()


def test_assembles_streamed_parallel_tool_calls_and_cached_tokens() -> None:
    requests: list[Any] = []

    def delta(index: int, **call: Any) -> str:
        return chunk(choices=[{"index": 0, "delta": {"tool_calls": [{"index": index, **call}]}}])

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(json.loads(request.content))
        body = (
            chunk(choices=[{"index": 0, "delta": {"content": "Let me check."}}])
            + delta(
                0, id="call_a", type="function", function={"name": "kb_search", "arguments": ""}
            )
            + delta(
                1, id="call_b", type="function", function={"name": "kb_search", "arguments": '{"qu'}
            )
            + delta(0, function={"arguments": '{"query": '})
            + delta(1, function={"arguments": 'ery": "b"}'})
            + delta(0, function={"arguments": '"a"}'})
            + chunk(choices=[{"index": 0, "delta": {}, "finish_reason": "tool_calls"}])
            + chunk(
                choices=[],
                usage={
                    "prompt_tokens": 900,
                    "completion_tokens": 30,
                    "prompt_tokens_details": {"cached_tokens": 512},
                },
            )
            + "data: [DONE]\n\n"
        )
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, text=body)

    events = stream(handler, [TOOL], session_id="conv-1")

    assert events == [
        Token("Let me check."),
        Usage(900, 30, None, "test/model", cached_tokens=512),
        ToolCall("call_a", "kb_search", '{"query": "a"}'),
        ToolCall("call_b", "kb_search", '{"query": "b"}'),
    ]
    assert requests[0]["tools"] == [TOOL]
    assert requests[0]["provider"] == {"require_parameters": True}
    assert requests[0]["session_id"] == "conv-1"
    assert "parallel_tool_calls" not in requests[0]


def test_api_errors_become_error_events() -> None:
    events = stream(lambda _: httpx2.Response(402, json={"error": {"message": "Out of credits"}}))

    assert len(events) == 1
    assert isinstance(events[0], LlmError)
    assert "Out of credits" in events[0].detail


class Verdict(BaseModel):
    domains: list[str]
    confidence: float = Field(ge=0, le=1)


def completion(content: str) -> dict[str, Any]:
    message = {"role": "assistant", "content": content}
    return {
        "id": "c",
        "object": "chat.completion",
        "created": 0,
        "model": "test/model",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25, "cost": 2e-5},
    }


def complete(*replies: str) -> tuple[Verdict, Usage, list[Any]]:
    requests: list[Any] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=completion(replies[len(requests) - 1]))

    client = openai.AsyncOpenAI(
        base_url="https://llm.test/v1",
        api_key="test",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    provider = OpenAICompatProvider(client, "test/model", 100)
    messages: list[Message] = [{"role": "user", "content": "Route this"}]
    verdict, usage = asyncio.run(provider.complete_json(messages, Verdict, "cheap/model"))
    return verdict, usage, requests


def test_structured_output_sends_the_schema_and_retries_an_invalid_reply_once() -> None:
    verdict, usage, requests = complete('{"domains": ["sre"], "confidence": 7}', VALID)

    assert verdict == Verdict(domains=["devops"], confidence=0.9)
    assert usage == Usage(20, 5, 2e-5, "test/model")
    first, retry = requests
    assert first["model"] == "cheap/model"
    assert first["response_format"]["type"] == "json_schema"
    assert first["response_format"]["json_schema"]["strict"] is True
    assert first["provider"] == {"require_parameters": True}
    assert "did not match the schema" in retry["messages"][-1]["content"]


def test_structured_output_gives_up_after_the_retry() -> None:
    with pytest.raises(ValidationError):
        complete("not json", "still not json")


VALID = '{"domains": ["devops"], "confidence": 0.9}'
