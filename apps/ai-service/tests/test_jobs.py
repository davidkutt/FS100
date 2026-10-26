"""The ingest queue and the gated re-index (D52 to D55), on Procrastinate's in-memory connector."""

import copy
import json
import time
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from procrastinate import App
from procrastinate.testing import InMemoryConnector

from ai_service import embeddings
from ai_service import ingest as ingesting
from ai_service.admin import backfill
from ai_service.catalog import load_taxonomy
from ai_service.contextual import Contextualizer
from ai_service.core.settings import Settings
from ai_service.jobs import retry_stalled_jobs
from ai_service.knowledge_base import KnowledgeBase
from ai_service.main import create_app
from ai_service.storage import MemoryStore, Progress
from support import (
    OFFLINE,
    USAGE,
    FakeTextEmbedding,
    Labeller,
    docling_document,
    drain,
    fetch_jwks,
    ingest,
    submit,
    token,
)

RUNBOOK = (
    b"# Runbook\n\n## Rollback\nUndo the release with kubectl rollout undo.\n\n"
    b"## Backups\nNightly pg_dump of the postgres database.\n"
)
GUIDE = b"# Guide\n\n## Linting\nRun ruff and pyright before every commit.\n"
ADMIN = {"Authorization": f"Bearer {token(sub='alice', roles=('admin',))}"}


def item(id: str, split: str, question: str, heading: str) -> dict[str, Any]:
    relevant = [{"doc": "runbook.md", "heading": heading}]
    labels = {"lang": "en", "domains": ["devops"], "answerable": True, "relevant": relevant}
    return {"id": id, "split": split, "question": question, **labels}


GOLDEN = [
    item("g-1", "dev", "How do I undo a release with kubectl rollout?", "Rollback"),
    item("g-2", "test", "Undo the release: which kubectl rollout command?", "Rollback"),
    item("g-3", "test", "Where are the nightly pg_dump backups of postgres?", "Backups"),
]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", fetch_jwks)
    monkeypatch.setattr(embeddings, "TextEmbedding", FakeTextEmbedding)
    golden = tmp_path / "golden.jsonl"
    golden.write_text("\n".join(json.dumps(i) for i in GOLDEN))
    app = create_app(Settings(**OFFLINE, golden_dataset=str(golden)))
    with TestClient(app, headers={"Authorization": f"Bearer {token()}"}) as client:
        yield client


def kb_of(client: TestClient) -> KnowledgeBase:
    return cast(FastAPI, client.app).state.kb


def jobs_of(client: TestClient) -> App:
    return cast(FastAPI, client.app).state.jobs


def store_of(client: TestClient) -> MemoryStore:
    return cast(FastAPI, client.app).state.store


def call[T](client: TestClient, function: Callable[..., Awaitable[T]], *args: Any) -> T:
    """Awaits `function` on the app's event loop, where the queue lives."""
    assert client.portal is not None
    return client.portal.call(function, *args)


def points(client: TestClient) -> list[Any]:
    kb = kb_of(client)
    return kb.client.scroll(kb.alias, limit=100, with_payload=True)[0]


def contexts(client: TestClient) -> dict[tuple[str, int], str | None]:
    return {
        (p.payload["doc_id"], p.payload["chunk_index"]): p.payload["context"]
        for p in points(client)
    }


def job(client: TestClient, job_id: int) -> Any:
    return client.get(f"/v1/jobs/{job_id}").json()


def reindex(client: TestClient, **body: Any) -> Any:
    """Runs a re-index to its end; returns its run from `GET /v1/reindex`."""
    assert client.post("/v1/reindex", json=body, headers=ADMIN).status_code == 202
    drain(client)
    return client.get("/v1/reindex", headers=ADMIN).json()["runs"][0]


def test_an_upload_is_stored_queued_and_then_ready(client: TestClient) -> None:
    doc_id = str(uuid4())

    submitted = submit(client, "runbook.md", RUNBOOK, ["devops"], doc_id)
    queued = job(client, submitted.json()["job_id"])
    drain(client)
    ready = job(client, submitted.json()["job_id"])

    assert (submitted.status_code, submitted.json()["version"]) == (202, 1)
    assert queued["state"] == "queued"
    assert (ready["state"], ready["result"]["chunk_count"]) == ("ready", 2)
    assert store_of(client).originals == {(UUID(doc_id), 1): RUNBOOK}
    payload = points(client)[0].payload
    assert {k: payload[k] for k in ("version", "kind", "lifecycle", "priority")} == {
        "version": 1,
        "kind": "doc",
        "lifecycle": "active",
        "priority": "normal",
    }
    assert client.get("/v1/jobs/999").status_code == 404


def test_the_same_bytes_keep_their_version_and_a_rerun_changes_nothing(
    client: TestClient,
) -> None:
    doc_id = str(uuid4())

    first = ingest(client, "runbook.md", RUNBOOK, ["devops"], doc_id=doc_id)
    before = sorted(p.id for p in points(client))
    second = submit(client, "runbook.md", RUNBOOK, ["devops"], doc_id)
    drain(client)
    after = sorted(p.id for p in points(client))
    newer = submit(client, "runbook.md", GUIDE, ["devops"], doc_id)
    drain(client)

    assert first["state"] == job(client, second.json()["job_id"])["state"] == "ready"
    assert second.json()["version"] == 1
    assert after == before
    assert newer.json()["version"] == 2
    assert {p.payload["version"] for p in points(client)} == {2}  # version 1 is gone


def test_an_unparsable_document_fails_at_once_and_a_transient_error_is_retried(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = submit(client, "scan.pdf", b"not a pdf", ["dev"]).json()["job_id"]
    drain(client)

    def unreachable(*_args: Any, **_kwargs: Any) -> None:
        raise ConnectionError("Qdrant is away")

    monkeypatch.setattr(kb_of(client), "index", unreachable)
    flaky = submit(client, "runbook.md", RUNBOOK, ["devops"]).json()["job_id"]
    drain(client)

    memory = cast(InMemoryConnector, jobs_of(client).connector)
    assert job(client, broken)["state"] == "failed"
    assert (memory.jobs[broken]["status"], memory.jobs[broken]["attempts"]) == ("failed", 1)
    assert job(client, flaky)["state"] == "queued"
    assert memory.jobs[flaky]["status"] == "todo"  # again in a few seconds


def test_delete_cancels_a_queued_ingest_and_drops_the_original(client: TestClient) -> None:
    doc_id = str(uuid4())
    job_id = submit(client, "runbook.md", RUNBOOK, ["devops"], doc_id).json()["job_id"]

    deleted = client.delete(f"/v1/documents/{doc_id}")
    drain(client)

    assert deleted.status_code == 204
    assert job(client, job_id)["state"] == "cancelled"
    assert store_of(client).originals == {}
    assert points(client) == []


def test_a_job_whose_worker_died_runs_again(client: TestClient) -> None:
    doc_id = str(uuid4())
    job_id = submit(client, "runbook.md", RUNBOOK, ["devops"], doc_id).json()["job_id"]
    jobs = jobs_of(client)
    memory = cast(InMemoryConnector, jobs.connector)
    memory.workers[99] = datetime.now(UTC) - timedelta(hours=1)  # last heartbeat
    call(client, jobs.job_manager.fetch_job, None, 99)
    call(client, store_of(client).set_progress, job_id, Progress("failed", "an earlier attempt"))
    retrying = job(client, job_id)["state"]
    call(client, store_of(client).set_progress, job_id, Progress("embedding"))
    # It had upserted its points when the process died.
    kb_of(client).ingest(
        doc_id=UUID(doc_id), filename="runbook.md", data=RUNBOOK, owner_id="bob", domains=["devops"]
    )

    running = job(client, job_id)["state"]
    refused = client.delete(f"/v1/documents/{doc_id}")
    call(client, retry_stalled_jobs, jobs)
    drain(client)

    assert (retrying, running, refused.status_code) == ("queued", "embedding", 409)
    assert job(client, job_id)["state"] == "ready"
    assert len(points(client)) == 2


def test_the_in_process_worker_runs_uploads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", fetch_jwks)
    monkeypatch.setattr(embeddings, "TextEmbedding", FakeTextEmbedding)
    app = create_app(Settings(**OFFLINE).model_copy(update={"jobs_inprocess_worker": True}))
    with TestClient(app, headers={"Authorization": f"Bearer {token()}"}) as client:
        job_id = submit(client, "runbook.md", RUNBOOK, ["devops"]).json()["job_id"]
        deadline = time.monotonic() + 5
        while job(client, job_id)["state"] != "ready" and time.monotonic() < deadline:
            time.sleep(0.05)

        assert job(client, job_id)["state"] == "ready"


def test_reindex_swaps_when_the_gate_holds_and_rolls_back(client: TestClient) -> None:
    ingest(client, "runbook.md", RUNBOOK, ["devops"])
    ingest(client, "guide.md", GUIDE, ["dev"])
    kb = kb_of(client)
    before = kb.live_collection()

    run = reindex(client)
    after = kb.live_collection()
    rolled_back = client.post("/v1/reindex/rollback", headers=ADMIN)
    again = client.post("/v1/reindex/rollback", headers=ADMIN)

    report = run["report"]
    assert (run["state"], run["requested_by"], report["decision"]) == ("ready", "alice", "swapped")
    assert (report["previous"], report["collection"]) == (before, after)
    assert after != before and report["blockers"] == []
    assert (report["documents"], report["chunks"]) == (2, 3)
    assert report["metrics"]["test"]["candidate"] == report["metrics"]["test"]["live"]
    assert rolled_back.json() == {"alias": "kb_current", "collection": before}
    assert kb.live_collection() == before
    assert again.status_code == 409


def test_contexts_cost_once_a_re_index_reuses_them_and_a_delete_drops_them(
    client: TestClient,
) -> None:
    state, store = cast(FastAPI, client.app).state, store_of(client)
    topics = load_taxonomy(Settings().taxonomy_config).topics()
    llm = Labeller(["devops/deployment"])
    contextualizer = Contextualizer(llm, "cheap/model", topics, ["devops"], 1, store)
    state.deps = replace(state.deps, contextualizer=contextualizer)

    uploaded = ingest(client, "runbook.md", RUNBOOK, ["devops"])
    guide = ingest(client, "guide.md", GUIDE, ["dev"])  # not switched on
    before = contexts(client)
    run = reindex(client)
    after = contexts(client)
    client.delete(f"/v1/documents/{uploaded['result']['doc_id']}")

    assert uploaded["result"]["context_cost_usd"] == pytest.approx(2 * (USAGE.cost_usd or 0))
    assert (len(llm.calls), run["report"]["context_cost_usd"]) == (2, {})  # from the store
    assert after == before
    assert sorted(p.payload["chunk_topics"][0] for p in points(client)) == [
        "dev/repository"  # the guide's, by the embedding fallback: "commit"
    ]
    assert guide["result"]["context_cost_usd"] == 0
    assert store.labels == {}


def test_a_pdf_is_parsed_once_until_docling_changes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    converted: list[bytes] = []

    def docling(data: bytes) -> dict[str, Any]:
        converted.append(data)
        return docling_document()

    monkeypatch.setattr(ingesting, "convert_pdf", docling)
    doc_id = str(uuid4())

    ingest(client, "handbook.pdf", b"%PDF handbook", ["sre"], doc_id=doc_id)
    reindexed = reindex(client)
    monkeypatch.setattr(ingesting, "PARSER", "docling 99.0")
    reindex(client)

    assert reindexed["report"]["skipped"] == []
    assert converted == [b"%PDF handbook"] * 2  # upload, then the new version; not the first build
    assert store_of(client).parses[UUID(doc_id), 1][0] == "docling 99.0"
    assert {(p.payload["page"], p.payload["heading"]) for p in points(client)} == {
        (1, "SLO handbook › Targets"),  # noqa: RUF001
        (2, "SLO handbook › Targets"),  # noqa: RUF001
        (2, "SLO handbook › Alerts › Burn rate"),  # noqa: RUF001
    }


def test_reindex_turns_a_dense_only_collection_hybrid(client: TestClient) -> None:
    kb = kb_of(client)
    dense_only = copy.copy(kb)
    dense_only.sparse = "none"
    kb.swap(dense_only.create_collection())  # as M3a.1 built it
    ingest(client, "runbook.md", RUNBOOK, ["devops"])
    before = kb.live_collection()

    run = reindex(client)
    hybrid = kb.sparse_of()
    client.post("/v1/reindex/rollback", headers=ADMIN)
    query = {"query": "kubectl rollout undo", "explain": True}
    hits = client.post("/v1/search", json=query).json()["hits"]

    assert run["report"]["decision"] == "swapped"
    assert run["report"]["metrics"]["test"]["live"]  # compared with the dense-only build
    assert hybrid == Settings().sparse_model != "none"
    assert (kb.live_collection(), kb.sparse_of()) == (before, "none")
    assert hits[0]["heading"] == "Runbook › Rollback"  # noqa: RUF001
    assert (hits[0]["dense_rank"], hits[0]["sparse_rank"]) == (1, None)


def test_the_gate_keeps_the_alias_on_a_worse_build_unless_forced(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    ingest(client, "runbook.md", RUNBOOK, ["devops"])
    ingest(client, "guide.md", GUIDE, ["dev"])
    kb = kb_of(client)
    before = kb.live_collection()
    real = kb.embedder.embed_passages

    def shuffled(texts: list[str]) -> list[list[float]]:
        return real(texts[::-1])  # each chunk of the new build gets another chunk's vector

    monkeypatch.setattr(kb.embedder, "embed_passages", shuffled)

    kept = reindex(client)
    after_kept = kb.live_collection()
    forced = reindex(client, reason="accept the worse build", force=True)

    assert kept["report"]["decision"] == "kept"
    assert any(b.startswith("test mrr@10") for b in kept["report"]["blockers"])
    assert after_kept == before
    assert kept["report"]["collection"] not in kb.collections()
    assert (forced["report"]["decision"], forced["reason"]) == ("forced", "accept the worse build")
    assert kb.live_collection() == forced["report"]["collection"]


def test_documents_without_an_original_block_the_swap_until_backfilled(
    client: TestClient, tmp_path: Path
) -> None:
    kb = kb_of(client)
    runbook, guide = uuid4(), uuid4()
    # Indexed before Phase 3: no originals stored.
    for doc_id, name, data in ((runbook, "runbook.md", RUNBOOK), (guide, "guide.md", GUIDE)):
        kb.ingest(doc_id=doc_id, filename=name, data=data, owner_id="bob", domains=["dev"])
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "renamed.md").write_bytes(RUNBOOK)

    blocked = reindex(client)
    missing = call(client, backfill, kb.client, kb.alias, store_of(client), corpus)
    still = reindex(client)

    assert blocked["report"]["decision"] == "kept"
    assert sorted(s["filename"] for s in blocked["report"]["skipped"]) == ["guide.md", "runbook.md"]
    assert missing == [f"guide.md ({guide})"]
    assert store_of(client).originals == {(runbook, 1): RUNBOOK}
    assert [s["filename"] for s in still["report"]["skipped"]] == ["guide.md"]


def test_deletes_and_relabels_survive_a_rollback(client: TestClient) -> None:
    runbook = ingest(client, "runbook.md", RUNBOOK, ["devops"])["result"]["doc_id"]
    guide = ingest(client, "guide.md", GUIDE, ["dev"])["result"]["doc_id"]
    reindex(client)

    client.delete(f"/v1/documents/{runbook}")
    client.patch(f"/v1/documents/{guide}/labels", json={"domains": ["sre"]})
    client.post("/v1/reindex/rollback", headers=ADMIN)
    hits = client.post("/v1/search", json={"query": "kubectl rollout ruff", "top_k": 10}).json()

    assert [(h["doc_id"], h["domains"]) for h in hits["hits"]] == [(guide, ["sre"])]


def test_a_document_deleted_during_the_build_is_not_swapped_in(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    ingest(client, "runbook.md", RUNBOOK, ["devops"])
    guide = UUID(ingest(client, "guide.md", GUIDE, ["dev"])["result"]["doc_id"])
    kb, store, real = kb_of(client), store_of(client), KnowledgeBase.index

    def deleted_meanwhile(self: KnowledgeBase, split: Any, **kwargs: Any) -> Any:
        if kwargs["doc_id"] == guide:  # the editor's delete reaches every collection…
            kb.delete(guide)
            del store.originals[guide, 1]
        return real(self, split, **kwargs)  # …but the build upserts afterwards

    monkeypatch.setattr(KnowledgeBase, "index", deleted_meanwhile)
    run = reindex(client)

    assert (run["report"]["decision"], run["report"]["documents"]) == ("swapped", 1)


def test_reindex_is_for_admins_and_force_needs_a_reason(client: TestClient) -> None:
    assert client.post("/v1/reindex", json={}).status_code == 403
    assert client.get("/v1/reindex").status_code == 403
    assert client.post("/v1/reindex", json={"force": True}, headers=ADMIN).status_code == 422
