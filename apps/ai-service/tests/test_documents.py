"""Upload → job → search → delete through the HTTP API; Qdrant and the database in-process."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_service import embeddings
from ai_service.core.settings import Settings
from ai_service.embeddings import Reranker
from ai_service.knowledge_base import KnowledgeBase
from ai_service.main import create_app
from ai_service.query import Passage, QueryTransformer
from support import OFFLINE, FakeTextEmbedding, ScriptedLlm, drain, fetch_jwks, submit, token

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
        "context_cost_usd": 0,
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


def test_search_finds_each_section_once_through_its_best_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", fetch_jwks)
    monkeypatch.setattr(embeddings, "TextEmbedding", FakeTextEmbedding)
    settings = Settings(**OFFLINE, chunk_size=60, chunk_overlap=0, parent_size=400)
    rollback = (
        "## Rollback\nUndo the release with kubectl rollout undo.\n"
        "Then watch the rollout status of the release."
    )
    runbook = f"# Runbook\n\n{rollback}\n\n## Backups\nNightly pg_dump.\n".encode()

    with TestClient(create_app(settings), headers={"Authorization": f"Bearer {token()}"}) as client:
        ingest(client, "runbook.md", runbook, ["devops"])
        hits = search(client, "rollout of the release", explain=True)
        chunks = payloads(client, hits[0]["doc_id"])

    assert [h["heading"] for h in hits] == ["Runbook › Rollback", "Runbook › Backups"]  # noqa: RUF001
    assert hits[0]["text"] == rollback
    assert hits[0]["chunk_text"] in rollback and hits[0]["chunk_text"] != rollback
    assert [c["parent_id"] for c in chunks].count(hits[0]["parent_id"]) == 2


def test_hyde_drafts_a_passage_and_only_the_survivors_are_strategies(client: TestClient) -> None:
    ingest(client, "runbook.md", MARKDOWN, ["devops"])
    llm = ScriptedLlm(Passage(passage="Undo the release."))
    cast(FastAPI, client.app).state.query = QueryTransformer(llm, None)

    hits = search(client, "rollout undo", strategy="hyde")
    lost = client.post("/v1/search", json={"query": "rollout undo", "strategy": "multi_query"})

    assert [h["heading"] for h in hits] == ["Runbook › Rollback"]  # noqa: RUF001
    assert [messages[1].get("content") for messages, _ in llm.calls] == ["rollout undo"]
    assert lost.status_code == 422


def test_the_reranker_orders_the_fused_candidates_and_its_score_gates(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    ingest(client, "two-pages.pdf", PDF, ["sre"])
    ingest(client, "runbook.md", MARKDOWN, ["devops"])
    kb_of(client).reranker = reranker = Reranker("fake", 20)  # RERANKER_MODEL=…, faked in conftest

    def reversed_order(_query: str, texts: list[str]) -> list[float]:
        return [i / 10 for i in range(len(texts))]  # the last fused candidate scores best

    monkeypatch.setattr(reranker, "scores", reversed_order)
    query = "Undo the release with kubectl rollout undo"

    response = client.post("/v1/search", json={"query": query, "top_k": 2, "explain": True})
    hits = response.json()["hits"]

    assert response.json()["reranker_model"] == "fake"
    assert [(h["fused_rank"], h["score"]) for h in hits] == [(3, 0.2), (2, 0.1)]
    assert len(search(client, query, score_threshold=0.2)) == 3
    assert search(client, query, score_threshold=0.21) == []


def test_hybrid_search_explains_its_ranks_and_keeps_cosine_scores(client: TestClient) -> None:
    ingest(client, "two-pages.pdf", PDF, ["sre"])
    ingest(client, "runbook.md", MARKDOWN, ["devops"])
    query = "Undo the release with kubectl rollout undo"

    hits = search(client, query, explain=True)
    best = hits[0]["score"]
    gated = search(client, query, score_threshold=best)
    kb = kb_of(client)
    dense = kb.embedder.embed_queries([query])[0]
    cosine = kb.client.query_points(kb.alias, query=dense, using="dense", limit=1).points[0]

    assert hits[0]["heading"] == "Runbook › Rollback"  # noqa: RUF001
    assert (hits[0]["fused_rank"], hits[0]["dense_rank"], hits[0]["sparse_rank"]) == (1, 1, 1)
    assert best == cosine.score  # the dense similarity, not the fused score
    # The threshold decides on the best hit and keeps the weaker ones (ADR-0016).
    assert len(gated) == len(hits) and gated[-1]["score"] < best
    assert search(client, query, score_threshold=best + 0.001) == []


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
    scoped = client.patch(f"/v1/documents/{doc_id}/labels", json={"priority_topics": ["sre/x"]})

    assert (ingested.status_code, patched.status_code, scoped.status_code) == (422, 422, 422)
    assert "devops/nope" in ingested.json()["detail"]


def test_retired_documents_are_never_returned(client: TestClient) -> None:
    runbook = ingest(client, "runbook.md", MARKDOWN, ["devops"]).json()["result"]["doc_id"]
    handbook = ingest(client, "two-pages.pdf", PDF, ["sre"]).json()["result"]["doc_id"]
    kb = kb_of(client)

    retired = client.patch(f"/v1/documents/{runbook}/labels", json={"lifecycle": "retired"})
    hits = search(client, "rollout undo")
    listed, found = kb.documents(), kb.document(UUID(runbook))
    client.patch(f"/v1/documents/{runbook}/labels", json={"lifecycle": "active"})

    assert retired.status_code == 204
    assert {h["doc_id"] for h in hits} == {handbook}
    assert ([str(d.doc_id) for d in listed], found) == ([handbook], None)
    assert search(client, "rollout undo")[0]["doc_id"] == runbook


GUIDE = b"# Guide\n\n## Releases\nRollouts and rollbacks of a release.\n"
RUNBOOK = b"# Runbook\n\n## Rollback\nRollouts and rollbacks of a release: kubectl rollout undo.\n"
CANONICAL = {"priority": "canonical", "priority_topics": ["devops/deployment"]}
UNMOVED = [("guide.md", 0), ("runbook.md", 0)]


@pytest.mark.parametrize(
    ("pinned", "labels", "threshold", "order"),
    [
        ("runbook.md", CANONICAL, 0.55, [("runbook.md", 3), ("guide.md", 0)]),
        ("guide.md", {**CANONICAL, "priority": "low"}, 0.55, [("runbook.md", 0), ("guide.md", -3)]),
        ("runbook.md", {**CANONICAL, "priority_topics": ["db/schema"]}, 0.55, UNMOVED),
        ("runbook.md", CANONICAL, 0.8, UNMOVED),
    ],
    ids=["canonical rises", "low sinks", "other sub-topic", "below the threshold"],
)
def test_a_priority_moves_hits_on_its_sub_topics_above_the_threshold(
    client: TestClient,
    pinned: str,
    labels: dict[str, Any],
    threshold: float,
    order: list[tuple[str, int]],
) -> None:
    files = {"guide.md": GUIDE, "runbook.md": RUNBOOK}
    ids = {
        name: ingest(client, name, data, ["devops"]).json()["result"]["doc_id"]
        for name, data in files.items()
    }
    kb_of(client).threshold = threshold
    question = "rollouts and rollbacks of a release"  # nearest: devops/deployment, devops/ci-cd

    client.patch(f"/v1/documents/{ids[pinned]}/labels", json=labels)
    hits = search(client, question, explain=True)

    assert [(h["filename"], h["boost"]) for h in hits] == order


def test_v1_routes_need_the_service_token(client: TestClient) -> None:
    response = client.post("/v1/search", json={"query": "x"}, headers={"Authorization": ""})

    assert response.status_code == 401


def test_readyz_reports_ready_once_model_and_qdrant_are_up(client: TestClient) -> None:
    assert client.get("/readyz").status_code == 200
    assert client.get("/v1/status").json() == {"status": "ok", "qdrant": "ok"}
