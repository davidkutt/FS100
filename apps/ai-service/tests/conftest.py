from collections.abc import Iterator
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient

from ai_service import embeddings
from ai_service.core.settings import Settings
from ai_service.main import create_app
from support import MARKDOWN, FakeTextEmbedding, fetch_jwks, token


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """The app with the fake LLM and one ingested runbook."""
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", fetch_jwks)
    monkeypatch.setattr(embeddings, "TextEmbedding", FakeTextEmbedding)
    app = create_app(Settings(qdrant_url=":memory:", llm_provider="fake"))
    with TestClient(app, headers={"Authorization": f"Bearer {token()}"}) as client:
        client.post(
            "/v1/ingest",
            files={"file": ("runbook.md", MARKDOWN)},
            data={"doc_id": str(uuid4()), "owner_id": "bob", "domains": ["devops"]},
        )
        yield client
