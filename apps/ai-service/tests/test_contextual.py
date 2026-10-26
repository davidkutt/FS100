import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest
from qdrant_client import QdrantClient

from ai_service import embeddings
from ai_service.catalog import load_taxonomy
from ai_service.contextual import Contextualizer, Split
from ai_service.core.settings import Settings
from ai_service.embeddings import Embedder
from ai_service.ingest import HEADING_SEPARATOR, Section, parents, parse
from ai_service.knowledge_base import Domain, KnowledgeBase
from support import USAGE, FakeTextEmbedding, Labeller

RUNBOOK = (
    b"# Runbook\n\n## Rollback\nUndo the release with kubectl rollout undo.\n\n"
    b"## Backups\nNightly pg_dump of the postgres database.\n"
)
TOPICS = load_taxonomy(Settings().taxonomy_config).topics()
SECTIONS = parse("runbook.md", RUNBOOK)
SPLIT = parents(SECTIONS, 1000, 150, 2000)
DOC = uuid4()


def contextualize(
    contextualizer: Contextualizer, domains: list[Domain], split: Split = SPLIT
) -> tuple[list[Section], float]:
    labelled, cost = asyncio.run(
        contextualizer.contextualize(SECTIONS, split, doc_id=DOC, version=3, domains=domains)
    )
    return [chunk for _, children in labelled for chunk in children], cost


def test_each_chunk_gets_a_context_and_its_documents_topics_with_the_document_first() -> None:
    llm = Labeller(["devops/deployment", "sre/slos", "devops/unknown"])
    contextualizer = Contextualizer(llm, "cheap/model", TOPICS, ["devops", "db"], 1.0)

    chunks, cost = contextualize(contextualizer, ["devops"])

    assert [(c.context, c.topics) for c in chunks] == [
        ("The runbook's Rollback section.", ("devops/deployment",)),  # sre/slos: not its domain
        ("The runbook's Backups section.", ("devops/deployment",)),
    ]
    assert cost == pytest.approx(2 * (USAGE.cost_usd or 0))
    system, chunk = (str(message.get("content")) for message in llm.calls[0][0])
    assert "devops/deployment" in system and "sre/slos" not in system
    rollback, backups = (
        f"[Runbook{HEADING_SEPARATOR}{h}]\n## {h}\n" for h in ("Rollback", "Backups")
    )
    assert f"<document>\n{rollback}Undo the release" in system
    assert system.endswith(f"{backups}Nightly pg_dump of the postgres database.\n</document>")
    assert "Backups" not in chunk
    assert {session for _, session in llm.calls} == {f"{DOC}:3"}


def test_no_context_outside_its_domains_after_a_failed_first_call_or_over_the_cap() -> None:
    off, failing, capped = Labeller([]), Labeller([], fail=True), Labeller([])
    plain = [chunk for _, children in SPLIT for chunk in children]

    assert contextualize(Contextualizer(off, None, TOPICS, ["db"], 1.0), ["devops"]) == (plain, 0)
    assert contextualize(Contextualizer(failing, None, TOPICS, ["devops"], 1.0), ["devops"]) == (
        plain,
        0,
    )
    first_only = Contextualizer(capped, None, TOPICS, ["devops"], USAGE.cost_usd or 0)
    chunks, cost = contextualize(first_only, ["devops"])

    assert (off.calls, len(failing.calls), len(capped.calls)) == ([], 1, 1)
    assert [chunk.context is not None for chunk in chunks] == [True, False]
    assert cost == USAGE.cost_usd


def test_the_context_is_indexed_not_cited_and_unlabelled_chunks_get_the_nearest_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(embeddings, "TextEmbedding", FakeTextEmbedding)
    kb = KnowledgeBase(
        QdrantClient(":memory:"),
        Embedder("fake"),
        "kb",
        1000,
        150,
        "bm25-english",
        2000,
        topics=TOPICS,
    )
    kb.ensure_collection()
    (parent, [rollback]), backups = kb.split(SECTIONS)
    context = replace(rollback, context="Helm zebra steps.", topics=("db/migrations",))
    kb.index(
        [(parent, [context]), backups],
        doc_id=DOC,
        version=1,
        filename="runbook.md",
        sha256="0" * 64,
        owner_id="bob",
        domains=["db"],
        topics=[],
        title=None,
    )

    hits = kb.search("zebra", 2)
    payloads = sorted(
        (p.payload or {} for p in kb.client.scroll("kb", with_payload=True)[0]),
        key=lambda payload: payload["chunk_index"],
    )

    assert (hits[0].heading or "").endswith("Rollback")
    assert "zebra" not in hits[0].text
    assert [(p["context"], p["chunk_topics"]) for p in payloads] == [
        ("Helm zebra steps.", ["db/migrations"]),
        (None, ["db/backup-restore"]),  # by embedding similarity to the descriptions
    ]
