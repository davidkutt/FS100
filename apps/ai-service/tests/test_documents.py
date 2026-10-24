"""Upload → job → search → delete through the HTTP API; Qdrant and the database in-process."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_service import embeddings
from ai_service.core.settings import Settings
from ai_service.knowledge_base import KnowledgeBase
from ai_service.main import create_app
from support import OFFLINE, FakeTextEmbedding, drain, fetch_jwks, submit, token

PDF = (Path(__file__).parent / "fixtures/two-pages.pdf").read_bytes()
MARKDOWN = b"# Runbook\n\n## Rollback\nUndo the release with kubectl rollout undo.\n"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", fetch_jwks)
    monkeypatch.setattr(embeddings, "TextEmbedding", FakeTextEmbedding)
    app = create_app(Settings(**OFFLINE))
    with TestClient(app, headers={"Authorization": f"Bearer {token()}"}) as client:
        yield client


def ingest(
    client: TestClient,
    filename: str,
    data: bytes,
    domains: list[str],
    doc_id: str | None = None,
    topics: list[str] | None = None,
) -> Any:
    """The job when it has ended, or the refused upload."""
    submitted = submit(client, filename, data, domains, doc_id, topics)
    if submitted.status_code != 202:
        return submitted
    drain(client)
    return client.get(f"/v1/jobs/{submitted.json()['job_id']}")


def kb_of(client: TestClient) -> KnowledgeBase:
    return cast(FastAPI, client.app).state.kb


def payloads(client: TestClient, doc_id: str) -> list[dict[str, Any]]:
    kb = kb_of(client)
    points, _ = kb.client.scroll(kb.alias, with_payload=True)
    return [p.payload or {} for p in points if (p.payload or {})["doc_id"] == doc_id]


def search(client: TestClient, query: str, **options: Any) -> list[dict[str, Any]]:
    response = client.post("/v1/search", json={"query": query, "top_k": 50, **options})
    assert response.status_code == 200
    return response.json()["hits"]


def test_ingest_then_search_returns_page_numbers(client: TestClient) -> None:
    doc_id = str(uuid4())

    ingested = ingest(client, "two-pages.pdf", PDF, ["db", "sre"], doc_id)
    hits = search(client, "nightly postgres backups pg_dump")

    assert ingested.json()["state"] == "ready"
    assert ingested.json()["result"] == {
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
        ("notes.md", b"text", ["marketing"], 422),
    ],
    ids=["unsupported type", "unknown domain"],
)
def test_upload_rejects_what_cannot_be_ingested(
    client: TestClient, filename: str, data: bytes, domains: list[str], status: int
) -> None:
    assert submit(client, filename, data, domains).status_code == status


@pytest.mark.parametrize(
    ("filename", "data", "error"),
    [("scan.pdf", b"not a pdf", "Stream has ended"), ("empty.md", b"# Title\n", "No ext")],
    ids=["broken pdf", "no text"],
)
def test_documents_without_text_fail_their_job(
    client: TestClient, filename: str, data: bytes, error: str
) -> None:
    job = ingest(client, filename, data, ["dev"]).json()

    assert job["state"] == "failed"
    assert error in job["error"]


def test_labels_change_without_re_embedding(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc_id = str(uuid4())
    ingest(client, "two-pages.pdf", PDF, ["sre"], doc_id, ["cloud/cost"])
    monkeypatch.setattr(kb_of(client).embedder, "embed_passages", pytest.fail)

    labels = {"domains": ["devops"], "topics": ["devops/deployment", "devops/ci-cd"]}
    response = client.patch(f"/v1/documents/{doc_id}/labels", json=labels)

    assert response.status_code == 204
    assert [(p["domains"], p["topics"]) for p in payloads(client, doc_id)] == [
        (labels["domains"], labels["topics"])
    ] * 2
    assert search(client, "page", domains=["sre"]) == []
    assert len(search(client, "page", domains=["devops"])) == 2


def test_only_taxonomy_topics_are_accepted(client: TestClient) -> None:
    doc_id = str(uuid4())

    ingested = ingest(client, "runbook.md", MARKDOWN, ["devops"], doc_id, ["devops/nope"])
    patched = client.patch(f"/v1/documents/{doc_id}/labels", json={"topics": ["sre/oncall"]})

    assert (ingested.status_code, patched.status_code) == (422, 422)  # before anything is stored
    assert "devops/nope" in ingested.json()["detail"]


def test_v1_routes_need_the_service_token(client: TestClient) -> None:
    response = client.post("/v1/search", json={"query": "x"}, headers={"Authorization": ""})

    assert response.status_code == 401


def test_readyz_reports_ready_once_model_and_qdrant_are_up(client: TestClient) -> None:
    assert client.get("/readyz").status_code == 200
    assert client.get("/v1/status").json() == {"status": "ok", "qdrant": "ok"}
