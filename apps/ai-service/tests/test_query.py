import asyncio
from uuid import uuid4

import pytest
from qdrant_client import QdrantClient

from ai_service import embeddings
from ai_service.embeddings import Embedder
from ai_service.knowledge_base import KnowledgeBase
from ai_service.query import Passage, Query, QueryTransformer
from support import USAGE, FakeTextEmbedding, ScriptedLlm


def test_hyde_adds_a_passage_once_per_question_and_a_failed_call_searches_the_question() -> None:
    llm = ScriptedLlm(Passage(passage="Run kubectl rollout undo."), RuntimeError("provider down"))
    transformer = QueryTransformer(llm, "cheap/model")

    async def expand() -> list[Query]:
        return [
            await transformer.expand("Roll back?", "hyde"),
            await transformer.expand("Roll back?", "hyde"),
            await transformer.expand("Restore?", "hyde"),
            await transformer.expand("Roll back?", "plain"),
        ]

    hyde, cached, failed, plain = asyncio.run(expand())

    assert hyde == Query("Roll back?", ["Run kubectl rollout undo."], USAGE)
    assert cached == Query("Roll back?", ["Run kubectl rollout undo."])  # no call, no cost
    assert failed == Query("Restore?")
    assert plain == Query("Roll back?")
    assert [(messages[1].get("content"), model) for messages, model in llm.calls] == [
        ("Roll back?", "cheap/model"),
        ("Restore?", "cheap/model"),
    ]


def test_passages_add_candidates_but_the_question_scores_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeTextEmbedding()

    def text_embedding(*_args: object, **_kwargs: object) -> FakeTextEmbedding:
        return fake

    monkeypatch.setattr(embeddings, "TextEmbedding", text_embedding)
    kb = KnowledgeBase(QdrantClient(":memory:"), Embedder("fake-e5"), "kb", 1000, 0)
    kb.ensure_collection()
    for name, text in (
        ("backup.md", b"# Backup\n\nNightly pg_dump at two."),
        ("rollback.md", b"# Rollback\n\nkubectl rollout undo"),
    ):
        kb.ingest(doc_id=uuid4(), filename=name, data=text, owner_id="t", domains=["devops"])
    passages = ["Nightly pg_dump at two.", "Backup: pg_dump nightly."]

    plain = kb.search("kubectl rollout undo", 2)
    hyde = kb.search("kubectl rollout undo", 2, passages=passages)

    assert [h.filename for h in plain] == ["rollback.md", "backup.md"]
    assert [h.filename for h in hyde] == ["backup.md", "rollback.md"]
    assert {h.filename: h.score for h in hyde} == {h.filename: h.score for h in plain}
    assert "passage: Nightly pg_dump at two." in fake.texts  # compared as a passage
