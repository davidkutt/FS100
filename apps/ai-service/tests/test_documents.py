"""Ingest → search → delete through the HTTP API, against an in-process Qdrant (`:memory:`)."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient

from ai_service import embeddings
from ai_service.core.settings import Settings
from ai_service.main import create_app
from support import FakeTextEmbedding, fetch_jwks, token

PDF = (Path(__file__).parent / "fixtures/two-pages.pdf").read_bytes()
MARKDOWN = b"# Runbook\n\n## Rollback\nUndo the release with kubectl rollout undo.\n"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", fetch_jwks)
    monkeypatch.setattr(embeddings, "TextEmbedding", FakeTextEmbedding)
    app = create_app(Settings(qdrant_url=":memory:"))
    with TestClient(app, headers={"Authorization": f"Bearer {token()}"}) as client:
        yield client


def ingest(
    client: TestClient, filename: str, data: bytes, domains: list[str], doc_id: str | None = None
) -> Any:
    return client.post(
        "/v1/ingest",
        files={"file": (filename, data)},
        data={"doc_id": doc_id or str(uuid4()), "owner_id": "bob", "domains": domains},
    )


def search(client: TestClient, query: str, **options: Any) -> list[dict[str, Any]]:
    response = client.post("/v1/search", json={"query": query, "top_k": 50, **options})
    assert response.status_code == 200
    return response.json()["hits"]


def test_ingest_then_search_returns_page_numbers(client: TestClient) -> None:
    doc_id = str(uuid4())

    ingested = ingest(client, "two-pages.pdf", PDF, ["db", "sre"], doc_id)
    hits = search(client, "nightly postgres backups pg_dump")

    assert ingested.status_code == 200
    assert ingested.json() == {
        "doc_id": doc_id,
        "chunk_count": 2,
        "page_count": 2,
        "embedding_model": Settings().embedding_model,
    }
    assert hits[0]["doc_id"] == doc_id
    assert hits[0]["page"] == 2
    assert hits[0]["domains"] == ["db", "sre"]
    assert hits[0]["filename"] == "two-pages.pdf"


def test_reingest_replaces_and_delete_removes_all_points(client: TestClient) -> None:
    doc_id = str(uuid4())

    ingest(client, "two-pages.pdf", PDF, ["sre"], doc_id)
    ingest(client, "two-pages.pdf", PDF, ["sre"], doc_id)
    after_reingest = search(client, "page")
    deleted = client.delete(f"/v1/documents/{doc_id}")

    assert len(after_reingest) == 2
    assert deleted.status_code == 204
    assert search(client, "page") == []


def test_search_filters_by_domain_and_threshold(client: TestClient) -> None:
    ingest(client, "two-pages.pdf", PDF, ["sre"])
    ingest(client, "runbook.md", MARKDOWN, ["devops"])

    devops = search(client, "rollout undo", domains=["devops"])
    strict = search(client, "rollout undo", score_threshold=0.999)

    assert [h["heading"] for h in devops] == ["Runbook › Rollback"]  # noqa: RUF001
    assert strict == []


@pytest.mark.parametrize(
    ("filename", "data", "domains", "status"),
    [
        ("slides.pptx", b"PK", ["dev"], 415),
        ("scan.pdf", b"not a pdf", ["dev"], 422),
        ("empty.md", b"# Title only\n", ["dev"], 422),
        ("notes.md", b"text", ["marketing"], 422),
    ],
    ids=["unsupported type", "broken pdf", "no text", "unknown domain"],
)
def test_ingest_rejects_bad_documents(
    client: TestClient, filename: str, data: bytes, domains: list[str], status: int
) -> None:
    assert ingest(client, filename, data, domains).status_code == status


def test_v1_routes_need_the_service_token(client: TestClient) -> None:
    response = client.post("/v1/search", json={"query": "x"}, headers={"Authorization": ""})

    assert response.status_code == 401


def test_readyz_reports_ready_once_model_and_qdrant_are_up(client: TestClient) -> None:
    assert client.get("/readyz").status_code == 200
    assert client.get("/v1/status").json() == {"status": "ok", "qdrant": "ok"}
