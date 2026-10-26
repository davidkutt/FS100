"""Own MCP server (ADR-0010): auth, tools, confirmation; the hop-2 token cache (ADR-0009)."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, cast

import httpx2
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp import Client, types
from mcp.client.context import ClientRequestContext
from mcp.client.streamable_http import streamable_http_client

from ai_service import mcp_server
from ai_service.core.settings import Settings
from ai_service.mcp_client import PROTOCOL
from ai_service.query import Passage, QueryTransformer
from ai_service.tokens import Tokens
from ai_service.tools import SearchArgs
from support import ScriptedLlm, ingest, token

MCP = Settings().mcp_resource_url
METADATA = "http://localhost:8000/.well-known/oauth-protected-resource/mcp"
GUIDE = b"# Guide\n\n## One\nFirst part.\n\n## Two\nSecond part.\n\n## Three\nThird part.\n"
URL = "https://raw.githubusercontent.com/davidkutt/FS100/main/README.md"


def mcp_token(roles: tuple[str, ...] = ("viewer",), scope: str = "kb:read") -> str:
    return token(aud=MCP, roles=roles, scope=scope)


def with_mcp[T](
    client: TestClient,
    bearer: str,
    use: Callable[[Client], Awaitable[T]],
    asked: list[str] | None = None,
    accept: bool = True,
) -> T:
    """Runs `use` with an SDK client in the app's event loop, where its MCP session manager runs."""

    async def confirm(
        context: ClientRequestContext, params: types.ElicitRequestParams
    ) -> types.ElicitResult:
        if asked is not None:
            asked.append(params.message)
        if accept:
            return types.ElicitResult(action="accept", content={"confirm": True})
        return types.ElicitResult(action="decline")

    async def run() -> T:
        headers = {"authorization": f"Bearer {bearer}"}
        async with (
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=client.app), headers=headers
            ) as http,
            Client(
                streamable_http_client(MCP, http_client=http),
                mode=PROTOCOL,
                elicitation_callback=confirm,
            ) as mcp,
        ):
            return await use(mcp)

    assert client.portal is not None
    return client.portal.call(run)


def call(client: TestClient, bearer: str, tool: str, **args: Any) -> dict[str, Any]:
    result = with_mcp(client, bearer, lambda mcp: mcp.call_tool(tool, args))
    assert not result.is_error, result.content
    return result.structured_content or {}


def test_a_request_without_token_gets_the_resource_metadata_challenge(client: TestClient) -> None:
    del client.headers["Authorization"]

    response = client.post(MCP, json={})
    metadata = client.get(METADATA).json()

    assert response.status_code == 401
    assert f'resource_metadata="{METADATA}"' in response.headers["www-authenticate"]
    assert metadata["resource"] == MCP
    assert metadata["authorization_servers"] == [Settings().ai_keycloak_issuer]


@pytest.mark.parametrize(
    ("bearer", "status"),
    [
        (token(), 401),
        (token(aud="kb-api"), 401),
        (token(aud=MCP, scope="kb:read", expires_in=-60), 401),
        (token(aud=MCP, scope="profile"), 403),
    ],
    ids=["hop-1 token", "browser token", "expired", "without kb:read"],
)
def test_mcp_admits_only_tokens_for_its_audience_and_scope(
    client: TestClient, bearer: str, status: int
) -> None:
    response = client.post(MCP, json={}, headers={"Authorization": f"Bearer {bearer}"})

    assert response.status_code == status


def test_read_tools_and_the_document_resource(client: TestClient) -> None:
    ingest(client, "guide.md", GUIDE, ["dev"], doc_id="00000000-0000-0000-0000-00000000000a")
    bearer = mcp_token()

    hits = call(
        client,
        bearer,
        "search_knowledge_base",
        query="third part",
        doc_ids=["00000000-0000-0000-0000-00000000000a"],
    )["hits"]
    sources = call(client, bearer, "list_sources")["sources"]
    first = call(client, bearer, "get_document", doc_id=hits[0]["doc_id"], limit=2)
    rest = call(client, bearer, "get_document", doc_id=hits[0]["doc_id"], offset=2, limit=2)
    resource = with_mcp(
        client, bearer, lambda mcp: mcp.read_resource(f"kb://documents/{hits[0]['doc_id']}")
    )

    assert {hit["doc_id"] for hit in hits} == {"00000000-0000-0000-0000-00000000000a"}
    assert [(s["title"], s["domains"], s["chunk_count"]) for s in sources] == [
        ("guide.md", ["dev"], 3),
        ("runbook.md", ["devops"], 1),
    ]
    assert call(client, bearer, "list_sources", domains=["dev"])["sources"] == sources[:1]
    assert ([s["index"] for s in first["sections"]], first["section_count"]) == ([0, 1], 3)
    assert (first["next_offset"], rest["next_offset"]) == (2, None)
    assert [s["text"] for s in rest["sections"]] == ["## Three\nThird part."]
    [content] = resource.contents
    assert isinstance(content, types.TextResourceContents)
    outline = json.loads(content.text)
    assert [heading.split()[-1] for heading in outline["headings"]] == ["One", "Two", "Three"]


def test_search_can_draft_a_passage_first(client: TestClient) -> None:
    llm = ScriptedLlm(Passage(passage="Undo the release."))
    cast(FastAPI, client.app).state.query = QueryTransformer(llm, None)

    result = call(client, mcp_token(), "search_knowledge_base", query="undo", strategy="hyde")

    assert [hit["filename"] for hit in result["hits"]] == ["runbook.md"]
    assert [messages[1].get("content") for messages, _ in llm.calls] == ["undo"]


def test_the_agents_search_arguments_match_the_tool_schema(client: TestClient) -> None:
    """The agent sends `SearchArgs` to `search_knowledge_base` (D34): same names, same enum."""
    tools = with_mcp(client, mcp_token(), lambda mcp: mcp.list_tools()).tools
    tool = next(t for t in tools if t.name == "search_knowledge_base")
    served: dict[str, Any] = tool.input_schema["properties"]
    sent: dict[str, Any] = SearchArgs.model_json_schema()["properties"]

    assert set(sent) <= set(served)
    assert served["strategy"]["enum"] == sent["strategy"]["enum"] == ["plain", "hyde"]


def test_read_tools_need_a_role(client: TestClient) -> None:
    result = with_mcp(client, mcp_token(roles=()), lambda mcp: mcp.call_tool("list_sources", {}))

    assert result.is_error
    assert "Not permitted for your role" in str(result.content)


def test_ingest_url_asks_first_then_adds_through_the_api(
    client: TestClient, api: list[httpx2.Request]
) -> None:
    asked: list[str] = []
    bearer = mcp_token(roles=("editor", "viewer"), scope="kb:read kb:write")

    result = with_mcp(
        client,
        bearer,
        lambda mcp: mcp.call_tool("ingest_url", {"url": URL, "domains": ["dev"]}),
        asked,
    )

    assert not result.is_error, result.content
    assert asked == [f"Add {URL} to the knowledge base (dev)?"]
    [request] = api
    assert str(request.url) == "http://localhost:3000/internal/documents/from-url"
    assert json.loads(request.content) == {
        "url": URL,
        "domains": ["dev"],
        "onBehalfOf": {"sub": "carol", "name": "carol"},
    }
    service = jwt.decode(
        request.headers["authorization"].split()[1], options={"verify_signature": False}
    )
    assert (service["sub"], service["aud"]) == ("service-account-kb-ai", "kb-api")
    assert (result.structured_content or {})["status"] == "pending"


@pytest.mark.parametrize(
    ("roles", "scope", "accept", "error", "asks"),
    [
        (("editor",), "kb:read kb:write", False, "elicitation was decline", True),
        (("editor",), "kb:read", True, "insufficient_scope: needs kb:write", False),
        (("viewer",), "kb:read kb:write", True, "Not permitted for your role", False),
    ],
    ids=["declined", "without kb:write", "viewer"],
)
def test_ingest_url_adds_nothing_unless_confirmed_and_permitted(
    client: TestClient,
    api: list[httpx2.Request],
    roles: tuple[str, ...],
    scope: str,
    accept: bool,
    error: str,
    asks: bool,
) -> None:
    asked: list[str] = []
    args = {"url": URL, "domains": ["dev"]}

    result = with_mcp(
        client,
        mcp_token(roles, scope),
        lambda mcp: mcp.call_tool("ingest_url", args),
        asked,
        accept,
    )

    assert result.is_error
    assert error in str(result.content)
    assert (bool(asked), api) == (asks, [])


def test_ingest_url_reports_the_apis_refusal(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    refusal = {"type": "about:blank", "status": 400, "detail": "Host example.com is not allowed"}
    transport = httpx2.MockTransport(lambda _: httpx2.Response(400, json=refusal))
    monkeypatch.setattr(mcp_server, "API_TRANSPORT", transport)
    bearer = mcp_token(roles=("editor",), scope="kb:read kb:write")

    result = with_mcp(
        client,
        bearer,
        lambda mcp: mcp.call_tool(
            "ingest_url", {"url": "https://example.com/a.md", "domains": ["dev"]}
        ),
    )

    assert result.is_error
    assert "Not added: Host example.com is not allowed" in str(result.content)


def test_exchanged_tokens_are_cached_until_30_s_before_they_expire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifetimes = [300, 300, 10, 300]  # the third is inside the renewal margin at once
    forms: list[dict[str, str]] = []

    async def fetch(_self: Tokens, form: dict[str, str]) -> tuple[str, int]:
        forms.append(form)
        return f"token-{len(forms)}", lifetimes[len(forms) - 1]

    monkeypatch.setattr(Tokens, "_fetch", fetch)
    tokens = Tokens(Settings())

    async def run() -> list[str]:
        return [
            await tokens.exchange("alice", "kb:read"),
            await tokens.exchange("alice", "kb:read"),
            await tokens.exchange("alice", "kb:read kb:write"),
            await tokens.exchange("bob", "kb:read"),
            await tokens.exchange("bob", "kb:read"),
        ]

    assert asyncio.run(run()) == ["token-1", "token-1", "token-2", "token-3", "token-4"]
    assert forms[0] == {
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "subject_token": "alice",
        "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "scope": "kb:read",
        "client_id": "kb-ai",
        "client_secret": "",
    }
