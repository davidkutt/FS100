import asyncio
import math
import re
from pathlib import Path
from typing import get_args
from uuid import uuid4

import pytest

from ai_service import embeddings
from ai_service.catalog import load_taxonomy
from ai_service.contextual import Contextualizer
from ai_service.core.settings import Settings
from ai_service.embeddings import Embedder, Reranker
from ai_service.evals.agent import load_tasks
from ai_service.evals.fixtures import GitHubFixture
from ai_service.evals.metrics import (
    calibrate_threshold,
    hit_at,
    ndcg,
    percentile,
    reciprocal_rank,
)
from ai_service.evals.retrieval import (
    TYPES,
    GoldenItem,
    Relevant,
    contextualizer_of,
    gains,
    index_corpus,
    load_dataset,
    load_manifest,
    load_priorities,
    regressions,
    run,
    strategy_of,
    to_markdown,
)
from ai_service.evals.routing import load_items
from ai_service.ingest import parse
from ai_service.knowledge_base import Domain, Hit
from ai_service.query import Passage, QueryTransformer
from support import USAGE, FakeTextEmbedding, Labeller, ScriptedLlm

REPO = Path(__file__).parents[3]
DATASETS = REPO / "evals/datasets"
DATASET = DATASETS / "retrieval_v1.jsonl"
FOLLOW_UPS = DATASETS / "followup_v1.jsonl"
PRIORITIES = DATASETS / "priorities_v1.json"
FIXTURES = REPO / "evals/fixtures"
CORPUS = REPO / "data/sample-docs"
KB_TOOLS = {
    f"kb.{tool}" for tool in ("search_knowledge_base", "get_document", "list_sources", "ingest_url")
}
NATIVE_TOOLS = {"github_sandbox.create_issue", "web.fetch"}


def test_metrics_match_hand_computed_values() -> None:
    ranked = [0, 1, 0, 1]  # relevant at ranks 2 and 4, two labels

    assert hit_at(ranked, 1) == 0.0
    assert hit_at(ranked, 5) == 1.0
    assert reciprocal_rank(ranked, 10) == 0.5
    expected = (1 / math.log2(3) + 1 / math.log2(5)) / (1 + 1 / math.log2(3))
    assert ndcg(ranked, 2, 10) == pytest.approx(expected)  # ≈ 0.651
    assert ndcg([1, 0], 3, 10) == pytest.approx(1 / (1 + 1 / math.log2(3) + 0.5))
    assert reciprocal_rank([0, 0, 1], 2) == 0.0


def test_percentile_is_nearest_rank() -> None:
    assert percentile([40, 10, 30, 20], 50) == 20
    assert percentile([40, 10, 30, 20], 95) == 40


def test_threshold_separates_answerable_from_unanswerable() -> None:
    # t=0.85 keeps 2/3 answerable and rejects 2/2 unanswerable: (0.667 + 1) / 2
    threshold, accuracy = calibrate_threshold([0.9, 0.8, 0.85], [0.7, 0.82])

    assert threshold == 0.85
    assert accuracy == pytest.approx(5 / 6)


def test_each_label_counts_once() -> None:
    item = GoldenItem(
        id="x",
        question="?",
        lang="en",
        domains=["sre"],
        answerable=True,
        relevant=[Relevant(doc="a.md", heading="Rollback"), Relevant(doc="b.pdf", page=2)],
    )

    def hit(filename: str, page: int | None = None, heading: str | None = None) -> Hit:
        return Hit(
            chunk_id="c",
            doc_id=uuid4(),
            title=filename,
            filename=filename,
            page=page,
            heading=heading,
            domains=["sre"],
            score=0.5,
            text="",
        )

    hits = [
        hit("a.md", heading="Runbook"),
        hit("a.md", heading="Runbook › Rollback"),  # noqa: RUF001
        hit("a.md", heading="Runbook › Rollback › Verify"),  # noqa: RUF001
        hit("b.pdf", page=2),
    ]

    assert gains(item, hits) == [0, 1, 0, 1]


def assert_labels_resolve(items: list[GoldenItem]) -> None:
    sections = {name: parse(name, (CORPUS / name).read_bytes()) for name in load_manifest(CORPUS)}
    for item in items:
        for label in item.relevant:
            assert any(
                label.matches(label.doc, s.page, s.heading) for s in sections.get(label.doc, [])
            ), f"{item.id}: {label} matches no section of the corpus"


def test_golden_set_is_well_formed_and_every_label_resolves() -> None:
    items = load_dataset(DATASET)

    assert 40 <= len(items) <= 60
    assert len({i.id for i in items}) == len(items)
    assert sum(not i.answerable for i in items) >= 8
    assert {i.lang for i in items} == {"de", "en"}
    for item in items:
        assert item.answerable == bool(item.relevant), item.id
        assert item.split, item.id  # D51: every item is either tuning or held-out data
        assert item.type in (*TYPES, "unanswerable"), f"{item.id}: `notes` names no item type"
    assert_labels_resolve(items)


def test_follow_ups_carry_their_history_and_every_label_resolves() -> None:
    items = load_dataset(FOLLOW_UPS)

    assert len({i.id for i in items}) == len(items) >= 12
    assert {i.split for i in items} == {"dev", "test"}
    for item in items:
        assert item.answerable == bool(item.relevant), item.id
        assert item.history and item.history[-1].role == "assistant", item.id
        assert item.type == ("follow-up" if item.answerable else "unanswerable"), item.id
    assert_labels_resolve(items)


def test_runner_reports_on_the_corpus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embeddings, "TextEmbedding", FakeTextEmbedding)

    report = run(
        index_corpus(Embedder("fake-e5"), CORPUS, chunk_size=1000, chunk_overlap=150), DATASET
    )

    assert len(report.items) == len(load_dataset(DATASET))
    assert report.overall["n"] == sum(i.answerable for i in report.items)
    assert report.threshold is not None
    assert {"de", "en"} == set(report.by_lang)
    assert set(report.by_type) <= set(TYPES)
    assert report.exact_terms["n"] == sum(i.exact_term and i.answerable for i in report.items)
    assert "| **overall** |" in to_markdown(report)
    assert "| **exact terms** |" in to_markdown(report)


def test_runner_runs_the_split_on_one_index_with_each_reranker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(embeddings, "TextEmbedding", FakeTextEmbedding)
    indexed = index_corpus(Embedder("fake-e5"), CORPUS, 1000, 150, "bm25-english")

    fused = run(indexed, DATASET, "test", "dbsf")
    reranked = run(indexed, DATASET, "test", "dbsf", Reranker("fake", 20), checked_threshold=0.5)

    test_ids = {i.id for i in load_dataset(DATASET) if i.split == "test"}
    assert fused.dataset == "retrieval_v1-test"
    assert "dense + bm25-english, dbsf" in to_markdown(fused)
    assert {r.id for r in fused.items} == test_ids
    assert "dense + bm25-english, dbsf, rerank fake:20" in to_markdown(reranked)
    assert reranked.checked_balanced_accuracy is not None
    assert "At `RETRIEVAL_SCORE_THRESHOLD` 0.500" in to_markdown(reranked)
    assert fused.checked_balanced_accuracy is None


def test_runner_pins_the_priorities_per_run_and_reports_the_pinned_topics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(embeddings, "TextEmbedding", FakeTextEmbedding)
    taxonomy = load_taxonomy(Settings().taxonomy_config)
    indexed = index_corpus(Embedder("fake-e5"), CORPUS, 1000, 150, topics=taxonomy.topics())
    scopes = {t for pin in load_priorities(PRIORITIES).values() for t in pin.priority_topics}

    pinned = run(indexed, DATASET, "dev", checked_threshold=0.55, priorities=PRIORITIES)
    plain = run(indexed, DATASET, "dev")

    points, _ = indexed.kb.client.scroll(indexed.kb.alias, limit=1000)
    assert set(load_priorities(PRIORITIES)) <= set(load_manifest(CORPUS))
    assert taxonomy.unknown_topics(sorted(scopes)) == []
    assert pinned.by_topic and set(pinned.by_topic) <= scopes
    assert ", priorities priorities_v1" in to_markdown(pinned)
    assert (plain.priorities, {(p.payload or {})["priority"] for p in points}) == (
        "none",
        {"normal"},
    )


def test_runner_searches_with_the_strategy_and_reports_its_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(embeddings, "TextEmbedding", FakeTextEmbedding)
    indexed = index_corpus(Embedder("fake-e5"), CORPUS, 1000, 150)
    dev = [i for i in load_dataset(FOLLOW_UPS) if i.split == "dev"]
    llm = ScriptedLlm(*[Passage(passage="Roll back with docker compose up.")] * len(dev))

    with asyncio.Runner() as runner:
        hyde = strategy_of(QueryTransformer(llm, None), "hyde", runner)
        report = run(indexed, FOLLOW_UPS, "dev", strategy="hyde", transform=hyde)

    assert [messages[1].get("content") for messages, _ in llm.calls] == [i.question for i in dev]
    assert report.overall["usd_per_query"] == pytest.approx(USAGE.cost_usd)
    assert ", hyde" in to_markdown(report)
    assert strategy_of(QueryTransformer(llm, None), "plain", runner) is None


def test_runner_contextualizes_the_switched_on_domains_and_reports_the_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(embeddings, "TextEmbedding", FakeTextEmbedding)
    llm = Labeller([])

    with asyncio.Runner() as runner:
        contextualize = contextualizer_of(Contextualizer(llm, None, {}, ["sre"], 1), runner)
        indexed = index_corpus(
            Embedder("fake-e5"), CORPUS, 1000, 150, "none", 0, ["sre"], contextualize
        )
        off = contextualizer_of(Contextualizer(llm, None, {}, [], 1), runner)
    report = run(indexed, DATASET, "test")

    sre = {name for name, domains in load_manifest(CORPUS).items() if "sre" in domains}
    assert set(report.context_cost_usd) == sre
    assert sum(report.context_cost_usd.values()) == pytest.approx(
        len(llm.calls) * (USAGE.cost_usd or 0)
    )
    assert "dense, contextual (sre)" in to_markdown(report)
    assert off is None


def test_regression_gate_allows_the_tolerance_and_flags_drops() -> None:
    baseline = {"hit@5": 0.98, "ndcg@10": 0.86}

    assert regressions({"hit@5": 0.96, "ndcg@10": 0.90}, baseline, 0.02) == []
    assert regressions({"hit@5": 0.95, "ndcg@10": 0.86}, baseline, 0.02) == [
        "hit@5 0.950 < baseline 0.980 - 0.02"
    ]


def test_agent_task_sets_are_well_formed_and_every_reference_resolves() -> None:
    sections = {name: parse(name, (CORPUS / name).read_bytes()) for name in load_manifest(CORPUS)}
    v0, v1 = load_tasks(DATASETS / "agent_v0.jsonl"), load_tasks(DATASETS / "agent_v1.jsonl")
    redteam = load_tasks(DATASETS / "redteam_v0.jsonl")
    tools = {*KB_TOOLS, *NATIVE_TOOLS, *(f"github.{t.name}" for t in GitHubFixture(FIXTURES).tools)}

    assert len(v0) == 22 and v1[: len(v0)] == v0  # v0 is frozen and part of v1
    assert len({t.id for t in v1}) == len(v1) >= 30
    assert {t.type for t in v1} >= {
        *("kb-lookup", "multi-hop", "cross-language", "abstain", "no-tool"),
        *("tool-selection", "multi-tool", "write-approval", "role-denied", "injection"),
    }
    assert len({t.id for t in redteam}) == len(redteam) >= 15
    for task in [*v1, *redteam]:
        expect = task.expect
        assert {*expect.tools_required, *expect.tools_forbidden} <= tools, task.id
        assert expect.approval_expected == (task.type == "write-approval"), task.id
        assert not task.scenario or (FIXTURES / f"scenarios/{task.scenario}.json").is_file()
        for pattern in [*expect.answer_regex, *expect.answer_not_regex]:
            re.compile(pattern)
        for label in expect.cites_any:
            assert any(
                label.matches(label.doc, s.page, s.heading) for s in sections.get(label.doc, [])
            ), f"{task.id}: {label} matches no section of the corpus"
    for task in v1:
        assert (task.expect.answer_status == "no_kb") >= (task.type == "no-tool"), task.id
    assert all(task.owasp and task.expect.tools_forbidden for task in redteam)


def test_routing_set_is_well_formed_and_covers_every_domain() -> None:
    items = load_items(DATASETS / "routing_v1.jsonl")

    assert len({i.id for i in items}) == len(items) >= 60
    assert {d for i in items for d in i.domains} == set(get_args(Domain))
    assert {i.lang for i in items} == {"de", "en"}
    assert all(i.needs_tools == bool(i.domains) for i in items)
