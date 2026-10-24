from collections.abc import Iterator
from uuid import uuid4

import httpx2
import jwt
import pytest
from fastapi.testclient import TestClient

from ai_service import embeddings, mcp_server
from ai_service.core.settings import Settings
from ai_service.main import create_app
from ai_service.mcp_client import McpClient
from ai_service.tokens import Tokens
from support import (
    MARKDOWN,
    OFFLINE,
    SIGNING_KEY,
    FakeTextEmbedding,
    FixedRouter,
    exchange,
    fetch_jwks,
    ingest,
    token,
)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """The app with the fake LLM and one ingested runbook; the agent's MCP hop stays in-process.
    No routing (the fake embedder's word hashes would route at random) and no GitHub token."""
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", fetch_jwks)
    monkeypatch.delenv("GITHUB_PAT_READ", raising=False)
    monkeypatch.setattr(embeddings, "TextEmbedding", FakeTextEmbedding)
    monkeypatch.setattr(Tokens, "_fetch", exchange)
    settings = Settings(**OFFLINE, llm_provider="fake", approval_signing_key=SIGNING_KEY)
    app = create_app(settings)
    monkeypatch.setattr(McpClient, "transport", httpx2.ASGITransport(app=app))
    with TestClient(app, headers={"Authorization": f"Bearer {token()}"}) as client:
        app.state.agent.router = FixedRouter()
        ingest(client, "runbook.md", MARKDOWN, ["devops"])
        yield client


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> list[httpx2.Request]:
    """The API's internal ingest route (D36), recording each request; it accepts them all."""
    requests: list[httpx2.Request] = []

    def accept(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(202, json={"id": str(uuid4()), "status": "pending"})

    monkeypatch.setattr(mcp_server, "API_TRANSPORT", httpx2.MockTransport(accept))
    return requests
