"""`kb-eval retrieval`: ingest the corpus into an in-memory Qdrant, run the golden set, report.

Run from `apps/ai-service` (as `pnpm eval:retrieval` does); default paths are relative to it.
"""

import argparse
import asyncio
import copy
import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from itertools import product
from pathlib import Path
from statistics import mean
from typing import Any, Literal, get_args
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, TypeAdapter
from qdrant_client import QdrantClient, models

from ai_service.catalog import load_taxonomy
from ai_service.contextual import Contextualizer, Split
from ai_service.core.settings import Settings
from ai_service.embeddings import Embedder, Reranker, Sparse, load_reranker
from ai_service.evals.metrics import (
    balanced_accuracy,
    calibrate_threshold,
    hit_at,
    ndcg,
    percentile,
    reciprocal_rank,
)
from ai_service.ingest import HEADING_SEPARATOR, Section, parse
from ai_service.knowledge_base import FUSION, Domain, Hit, KnowledgeBase, Priority
from ai_service.llm import create_provider
from ai_service.query import Query, QueryTransformer, Strategy
from ai_service.rag import ChatTurn

TOP_K = 10
MANIFEST = "domains.json"
# Item types as `notes` begins (evals/README.md); unanswerable items are their own.
TYPES = (
    *("direct lookup", "paraphrase", "cross-language", "multi-chunk", "PDF", "whole document"),
    "follow-up",
)
_manifest = TypeAdapter(dict[str, list[Domain]])
# A document's sections and chunks → its labelled chunks and their cost (D60).
type Contextualize = Callable[[list[Section], Split, UUID, list[Domain]], tuple[Split, float]]


class Relevant(BaseModel):
    """Label by document + heading (any path level) and/or page, so it survives re-chunking."""

    doc: str
    heading: str | None = None
    page: int | None = None

    def matches(self, filename: str, page: int | None, heading: str | None) -> bool:
        return (
            filename == self.doc
            and (self.page is None or page == self.page)
            and (self.heading is None or self.heading in (heading or "").split(HEADING_SEPARATOR))
        )


class GoldenItem(BaseModel):
    id: str
    question: str
    lang: Literal["de", "en"]
    domains: list[Domain]
    answerable: bool
    relevant: list[Relevant] = []
    notes: str = ""
    split: Literal["dev", "test"] | None = None
    exact_term: bool = False  # names an error code, flag, command or identifier (D56)
    history: list[ChatTurn] = []  # the conversation before a follow-up `question`

    @property
    def type(self) -> str:
        if not self.answerable:
            return "unanswerable"
        return next((t for t in TYPES if self.notes.startswith(t)), "other")


class Pin(BaseModel):
    """A document's priority in `--priorities` (D61)."""

    priority: Priority
    priority_topics: list[str]


_pins = TypeAdapter(dict[str, Pin])


class ItemResult(BaseModel):
    id: str
    question: str
    lang: str
    domains: list[Domain]
    type: str
    exact_term: bool
    answerable: bool
    relevant_count: int
    gains: list[int]
    top1_score: float
    context_chars: int  # of the top 5 hits: what the chat puts into the prompt (RETRIEVAL_TOP_K)
    latency_ms: float  # with the query transformation
    cost_usd: float  # of the query transformation
    top_hits: list[str]
    topics: list[str] = []  # the question's nearest sub-topics, which boosts match (D61)


class RunReport(BaseModel):
    dataset: str
    model: str
    dim: int
    chunk_size: int
    chunk_overlap: int
    parent_size: int = 0
    sparse: Sparse
    fusion: str
    rerank: str  # `none` or `<model>:<candidates>`
    strategy: Strategy = "plain"
    contextual: list[Domain] = []
    context_cost_usd: dict[str, float] = {}  # per document, one-off at ingest
    priorities: str = "none"  # the `--priorities` file (D61)
    documents: int
    chunks: int
    ingest_s: float
    created_at: str
    overall: dict[str, float]
    by_domain: dict[str, dict[str, float]]
    by_lang: dict[str, dict[str, float]]
    by_type: dict[str, dict[str, float]]
    exact_terms: dict[str, float]  # empty: no such item in the run
    by_topic: dict[str, dict[str, float]] = {}  # per pinned sub-topic: the questions routed to it
    threshold: float | None
    threshold_balanced_accuracy: float | None
    checked_threshold: float | None  # RETRIEVAL_SCORE_THRESHOLD, e.g. calibrated on `dev`
    checked_balanced_accuracy: float | None
    items: list[ItemResult]


@dataclass(frozen=True)
class Indexed:
    """The corpus in an in-memory collection; fusion and reranker vary per run on top of it."""

    kb: KnowledgeBase
    documents: int
    chunks: int
    ingest_s: float
    contextual: list[Domain]
    context_cost_usd: dict[str, float]


def load_dataset(path: Path) -> list[GoldenItem]:
    return [GoldenItem.model_validate_json(line) for line in path.read_text().splitlines() if line]


def load_priorities(path: Path) -> dict[str, Pin]:
    return _pins.validate_json(path.read_bytes())


def load_manifest(corpus: Path) -> dict[str, list[Domain]]:
    return _manifest.validate_json((corpus / MANIFEST).read_bytes())


def doc_id(filename: str) -> UUID:
    """Stable per file, so a report can name a cited document."""
    return uuid5(NAMESPACE_URL, filename)


def ingest_corpus(
    kb: KnowledgeBase, corpus: Path, contextualize: Contextualize | None = None
) -> tuple[int, dict[str, float]]:
    """Every file of the corpus manifest, with its domains; the chunk count and, per document
    contextualized, what it cost."""
    chunks, costs = 0, dict[str, float]()
    for name, domains in load_manifest(corpus).items():
        data = (corpus / name).read_bytes()
        sections = parse(name, data)
        split = kb.split(sections)
        if contextualize:
            split, costs[name] = contextualize(sections, split, doc_id(name), domains)
        chunks += kb.index(
            split,
            doc_id=doc_id(name),
            version=1,
            filename=name,
            sha256=hashlib.sha256(data).hexdigest(),
            owner_id="eval",
            domains=domains,
            topics=[],
            title=None,
        ).chunk_count
    return chunks, {name: cost for name, cost in costs.items() if cost}


def gains(item: GoldenItem, hits: list[Hit]) -> list[int]:
    found: set[int] = set()
    result: list[int] = []
    for hit in hits:
        label = next(
            (
                index
                for index, relevant in enumerate(item.relevant)
                if index not in found and relevant.matches(hit.filename, hit.page, hit.heading)
            ),
            None,
        )
        if label is not None:
            found.add(label)
        result.append(int(label is not None))
    return result


def summarize(results: list[ItemResult]) -> dict[str, float]:
    return {
        "n": len(results),
        "hit@1": mean(hit_at(r.gains, 1) for r in results),
        "hit@5": mean(hit_at(r.gains, 5) for r in results),
        "mrr@10": mean(reciprocal_rank(r.gains, 10) for r in results),
        "ndcg@10": mean(ndcg(r.gains, r.relevant_count, 10) for r in results),
    }


def evaluate(
    kb: KnowledgeBase,
    items: list[GoldenItem],
    transform: Callable[[GoldenItem], Query] | None = None,
) -> list[ItemResult]:
    results: list[ItemResult] = []
    for item in items:
        started = time.perf_counter()
        query = transform(item) if transform else Query(item.question)
        hits = kb.search(query.text, TOP_K, passages=query.passages)
        latency_ms = (time.perf_counter() - started) * 1000
        results.append(
            ItemResult(
                id=item.id,
                question=item.question,
                lang=item.lang,
                domains=item.domains,
                type=item.type,
                exact_term=item.exact_term,
                answerable=item.answerable,
                relevant_count=len(item.relevant),
                gains=gains(item, hits),
                # What the threshold decides on (`KnowledgeBase.search`): the best similarity.
                top1_score=max((h.score for h in hits), default=0.0),
                context_chars=sum(len(h.text) for h in hits[:5]),
                latency_ms=latency_ms,
                cost_usd=(query.usage and query.usage.cost_usd) or 0.0,
                top_hits=[
                    f"{h.filename} § {h.heading or f'p{h.page}'} ({h.score:.3f})" for h in hits[:3]
                ],
                topics=kb.question_topics(kb.embedder.embed_queries([query.text])[0]),
            )
        )
    return results


def index_corpus(
    embedder: Embedder,
    corpus: Path,
    chunk_size: int,
    chunk_overlap: int,
    sparse: Sparse = "none",
    parent_size: int = 0,
    contextual: list[Domain] | None = None,
    contextualize: Contextualize | None = None,
    topics: dict[str, str] | None = None,
) -> Indexed:
    client = QdrantClient(":memory:")
    kb = KnowledgeBase(
        client, embedder, "eval", chunk_size, chunk_overlap, sparse, parent_size, topics=topics
    )
    kb.ensure_collection()
    started = time.perf_counter()
    chunks, costs = ingest_corpus(kb, corpus, contextualize)
    documents, took = len(load_manifest(corpus)), time.perf_counter() - started
    return Indexed(kb, documents, chunks, took, contextual or [], costs)


def contextualizer_of(
    contextualizer: Contextualizer, runner: asyncio.Runner
) -> Contextualize | None:
    """`contextualize` on `runner`'s event loop (the LLM client's); None if it is off."""
    if not contextualizer.domains:
        return None

    def contextualize(
        sections: list[Section], split: Split, document: UUID, domains: list[Domain]
    ) -> tuple[Split, float]:
        call = contextualizer.contextualize(
            sections, split, doc_id=document, version=1, domains=domains
        )
        return runner.run(call)

    return contextualize


def strategy_of(
    transformer: QueryTransformer, strategy: Strategy, runner: asyncio.Runner
) -> Callable[[GoldenItem], Query] | None:
    """The item's query under `strategy`; one event loop for every call (the LLM client's)."""
    if strategy == "plain":
        return None
    return lambda item: runner.run(transformer.expand(item.question, strategy))


def prioritize(kb: KnowledgeBase, pins: dict[str, Pin]) -> None:
    """Every document `normal`, then the pinned ones (by corpus filename) as `pins` says."""
    normal = Pin(priority="normal", priority_topics=[]).model_dump()
    kb.client.set_payload(kb.alias, normal, models.FilterSelector(filter=models.Filter()))
    for name, pin in pins.items():
        kb.update_labels(doc_id(name), pin.model_dump())


def run(
    indexed: Indexed,
    dataset: Path,
    split: str | None = None,
    fusion: str = FUSION,
    reranker: Reranker | None = None,
    checked_threshold: float | None = None,
    strategy: Strategy = "plain",
    transform: Callable[[GoldenItem], Query] | None = None,
    priorities: Path | None = None,
) -> RunReport:
    kb = copy.copy(indexed.kb)
    kb.fusion, kb.reranker, kb.threshold = fusion, reranker, checked_threshold
    pins = load_priorities(priorities) if priorities else {}
    prioritize(kb, pins)
    items = [i for i in load_dataset(dataset) if not split or i.split == split]
    results = evaluate(kb, items, transform)
    answerable = [r for r in results if r.answerable]
    unanswerable = [r.top1_score for r in results if not r.answerable]
    scores = [r.top1_score for r in answerable]
    threshold, accuracy = (
        calibrate_threshold(scores, unanswerable) if answerable and unanswerable else (None, None)
    )
    checked = (
        balanced_accuracy(scores, unanswerable, checked_threshold)
        if checked_threshold is not None and answerable and unanswerable
        else None
    )
    latencies = [r.latency_ms for r in results]
    domains = sorted({d for r in answerable for d in r.domains})
    return RunReport(
        dataset=f"{dataset.stem}-{split}" if split else dataset.stem,
        model=kb.embedder.model_name,
        dim=kb.embedder.dim,
        chunk_size=kb.chunk_size,
        chunk_overlap=kb.chunk_overlap,
        parent_size=kb.parent_size,
        sparse=kb.sparse,
        fusion=fusion,
        rerank=f"{reranker.model_name}:{reranker.candidates}" if reranker else "none",
        documents=indexed.documents,
        chunks=indexed.chunks,
        ingest_s=indexed.ingest_s,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        strategy=strategy,
        contextual=indexed.contextual,
        context_cost_usd=indexed.context_cost_usd,
        overall={
            **summarize(answerable),
            "p50_ms": percentile(latencies, 50),
            "p95_ms": percentile(latencies, 95),
            "usd_per_query": mean(r.cost_usd for r in results),
            "context_chars": mean(r.context_chars for r in results),
        },
        by_domain={d: summarize([r for r in answerable if d in r.domains]) for d in domains},
        by_lang={
            lang: summarize([r for r in answerable if r.lang == lang])
            for lang in sorted({r.lang for r in answerable})
        },
        by_type={
            t: summarize([r for r in answerable if r.type == t])
            for t in sorted({r.type for r in answerable})
        },
        exact_terms=summarize(exact) if (exact := [r for r in answerable if r.exact_term]) else {},
        priorities=priorities.stem if priorities else "none",
        by_topic={
            topic: summarize(routed)
            for topic in sorted({t for pin in pins.values() for t in pin.priority_topics})
            if (routed := [r for r in answerable if topic in r.topics])
        },
        threshold=threshold,
        threshold_balanced_accuracy=accuracy,
        checked_threshold=checked_threshold,
        checked_balanced_accuracy=checked,
        items=results,
    )


def to_markdown(report: RunReport) -> str:
    def row(label: str, m: dict[str, float]) -> str:
        values = " | ".join(f"{m[key]:.2f}" for key in ("hit@1", "hit@5", "mrr@10", "ndcg@10"))
        return f"| {label} | {m['n']:.0f} | {values} |"

    o = report.overall
    lines = [
        f"## Retrieval eval · {report.dataset} · `{report.model}` · chunks "
        f"{_chunks(report)} · {_retrieval(report)}",
        "",
        f"{report.chunks} chunks from {report.documents} documents, "
        f"ingest {report.ingest_s:.1f} s"
        + (
            f" (contexts {sum(report.context_cost_usd.values()):.4f} USD)"
            if report.contextual
            else ""
        )
        + " · "
        f"{len(report.items)} questions ({o['n']:.0f} answerable) · "
        f"latency p50 {o['p50_ms']:.0f} ms / p95 {o['p95_ms']:.0f} ms · "
        f"USD {o.get('usd_per_query', 0):.6f} per query · "
        f"{o.get('context_chars', 0):,.0f} characters in the top 5",
        "",
    ]
    if report.threshold is not None and report.threshold_balanced_accuracy is not None:
        lines += [
            f"Suggested `score_threshold`: **{report.threshold:.3f}** (balanced accuracy "
            f"{report.threshold_balanced_accuracy:.2f}, answerable vs. unanswerable top-1 scores)",
            "",
        ]
    if report.checked_threshold is not None and report.checked_balanced_accuracy is not None:
        lines += [
            f"At `RETRIEVAL_SCORE_THRESHOLD` {report.checked_threshold:.3f}: balanced accuracy "
            f"**{report.checked_balanced_accuracy:.2f}**",
            "",
        ]
    lines += ["| Slice | n | hit@1 | hit@5 | MRR@10 | nDCG@10 |", "|---|---|---|---|---|---|"]
    lines.append(row("**overall**", o))
    lines += [row(f"domain `{d}`", m) for d, m in report.by_domain.items()]
    lines += [row(f"lang `{lang}`", m) for lang, m in report.by_lang.items()]
    lines += [row(f"type {t}", m) for t, m in report.by_type.items()]
    if report.exact_terms:
        lines.append(row("**exact terms**", report.exact_terms))
    lines += [row(f"pinned `{t}`", m) for t, m in report.by_topic.items()]
    misses = [r for r in report.items if r.answerable and not any(r.gains[:5])]
    if misses:
        lines += ["", "Misses (no relevant hit in the top 5):", ""]
        lines += [f"- `{r.id}` {r.question} → {'; '.join(r.top_hits[:1])}" for r in misses]
    return "\n".join(lines) + "\n"


def comparison(reports: list[RunReport]) -> str:
    lines = [
        "| Model | Chunks | Retrieval | Points | Ingest s | hit@1 | hit@5 | MRR@10 | nDCG@10 "
        "| Exact-term nDCG@10 | p50 ms | p95 ms | USD/query | Top-5 chars | Threshold |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in reports:
        o, exact = r.overall, r.exact_terms.get("ndcg@10")
        lines.append(
            f"| `{r.model}` | {_chunks(r)} | {_retrieval(r)} | {r.chunks} "
            f"| {r.ingest_s:.0f} | {o['hit@1']:.2f} | {o['hit@5']:.2f} | {o['mrr@10']:.2f} "
            f"| {o['ndcg@10']:.2f} | {'-' if exact is None else f'{exact:.2f}'} "
            f"| {o['p50_ms']:.0f} | {o['p95_ms']:.0f} | {o.get('usd_per_query', 0):.6f} "
            f"| {o.get('context_chars', 0):,.0f} | {r.threshold or 0:.3f} |"
        )
    return "\n".join(lines) + "\n"


def _chunks(report: RunReport) -> str:
    sizes = f"{report.chunk_size}/{report.chunk_overlap}"
    return f"{sizes} in {report.parent_size}" if report.parent_size else sizes


def _retrieval(report: RunReport) -> str:
    fused = "dense" if report.sparse == "none" else f"dense + {report.sparse}, {report.fusion}"
    if report.contextual:
        fused += f", contextual ({_contextual(report.contextual)})"
    reranked = fused if report.rerank == "none" else f"{fused}, rerank {report.rerank}"
    if report.priorities != "none":
        reranked += f", priorities {report.priorities}"
    return reranked if report.strategy == "plain" else f"{reranked}, {report.strategy}"


def regressions(
    overall: dict[str, float], baseline: dict[str, float], tolerance: float
) -> list[str]:
    """The metrics more than `tolerance` below their baseline (D43: the CI gate)."""
    return [
        f"{metric} {overall[metric]:.3f} < baseline {value:.3f} - {tolerance}"
        for metric, value in baseline.items()
        if overall[metric] < value - tolerance
    ]


def _chunk_arg(value: str) -> tuple[int, int, int]:
    size, overlap, parent, *_ = [*value.split(":"), "0", "0"]
    return int(size), int(overlap), int(parent)


def _contextual(domains: list[Domain]) -> str:
    return "all" if set(domains) == set(get_args(Domain)) else ",".join(domains)


def _contextual_arg(value: str) -> list[Domain]:
    if value == "all":
        return list(get_args(Domain))
    return TypeAdapter(list[Domain]).validate_python([] if value == "none" else value.split(","))


def _rerank_arg(value: str) -> tuple[str, int]:
    model, _, candidates = value.rpartition(":")
    return ("none", 0) if value == "none" else (model, int(candidates))


def _priorities_arg(value: str) -> Path | None:
    return None if value == "none" else Path(value)


def _metric_arg(value: str) -> tuple[str, float]:
    metric, _, number = value.partition("=")
    return metric, float(number)


def add_command(commands: Any, settings: Settings) -> None:
    cmd = commands.add_parser("retrieval", help="golden-set retrieval eval: hit@k, MRR, nDCG")
    cmd.add_argument(
        "--dataset", type=Path, default=Path("../../evals/datasets/retrieval_v1.jsonl")
    )
    cmd.add_argument(
        "--split", choices=["dev", "test"], help="only this part (D51); default: all items"
    )
    cmd.add_argument("--corpus", type=Path, default=Path("../../data/sample-docs"))
    cmd.add_argument("--out", type=Path, default=Path("../../evals/runs"))
    cmd.add_argument(
        "--model", action="append", help="repeat to benchmark (default: EMBEDDING_MODEL)"
    )
    cmd.add_argument(
        "--chunk",
        action="append",
        type=_chunk_arg,
        metavar="SIZE:OVERLAP[:PARENT]",
        help="repeat to benchmark (default: CHUNK_SIZE:CHUNK_OVERLAP:PARENT_SIZE)",
    )
    cmd.add_argument(
        "--sparse",
        action="append",
        choices=get_args(Sparse),
        help="repeat to benchmark (default: SPARSE_MODEL; `none` = dense only)",
    )
    cmd.add_argument(
        "--contextual",
        action="append",
        type=_contextual_arg,
        metavar="DOMAINS|all|none",
        help="repeat to benchmark (default: CONTEXTUAL_DOMAINS); calls CONTEXTUAL_MODEL at ingest",
    )
    cmd.add_argument(
        "--fusion",
        action="append",
        metavar="rrf:K:SPARSE_WEIGHT|dbsf",
        help=f"repeat to benchmark (default: {FUSION})",
    )
    cmd.add_argument(
        "--rerank",
        action="append",
        type=_rerank_arg,
        metavar="MODEL:CANDIDATES|none",
        help="repeat to benchmark (default: RERANKER_MODEL:RERANK_CANDIDATES)",
    )
    cmd.add_argument(
        "--strategy",
        action="append",
        choices=get_args(Strategy),
        help="repeat to benchmark (default: plain); hyde calls QUERY_MODEL, LLM from the env",
    )
    cmd.add_argument(
        "--priorities",
        action="append",
        type=_priorities_arg,
        metavar="PATH|none",
        help="repeat to benchmark (default: none): JSON of corpus file → priority and scope (D61)",
    )
    cmd.add_argument(
        "--baseline",
        action="append",
        type=_metric_arg,
        default=[],
        metavar="METRIC=VALUE",
        help="fail (exit 1) if an overall metric drops below VALUE - tolerance, e.g. hit@5=0.98",
    )
    cmd.add_argument("--tolerance", type=float, default=0.02)
    cmd.set_defaults(run=partial(_main, settings=settings))


def _main(args: argparse.Namespace, settings: Settings) -> None:
    args.out.mkdir(parents=True, exist_ok=True)
    reports: list[RunReport] = []
    failed: list[str] = []
    sparses: list[Sparse] = args.sparse or [settings.sparse_model]
    reranks = args.rerank or [(settings.reranker_model, settings.rerank_candidates)]
    strategies: list[Strategy] = args.strategy or ["plain"]
    contextuals: list[list[Domain]] = args.contextual or [settings.contextual_domains]
    paid = strategies != ["plain"] or any(contextuals)
    if paid and settings.llm_provider == "fake":
        raise SystemExit(
            "--strategy and --contextual need a real LLM: add `--env-file ../../.env` to `uv run`"
        )
    llm = create_provider(settings)
    transformer = QueryTransformer(llm, settings.query_model or None)
    topics = load_taxonomy(settings.taxonomy_config).topics()
    runner = asyncio.Runner()  # one event loop for every LLM call: the client's
    for model in args.model or [settings.embedding_model]:
        embedder = Embedder(model, settings.embedding_cache_dir)
        chunkings = args.chunk or [
            (settings.chunk_size, settings.chunk_overlap, settings.parent_size)
        ]
        for (size, overlap, parent), sparse, contextual in product(chunkings, sparses, contextuals):
            contextualizer = Contextualizer(
                llm,
                settings.contextual_model or settings.llm_model,
                topics,
                contextual,
                settings.contextual_max_cost_usd_per_doc,
            )
            contextualize = contextualizer_of(contextualizer, runner)
            indexed = index_corpus(
                embedder,
                args.corpus,
                size,
                overlap,
                sparse,
                parent,
                contextual,
                contextualize,
                topics,
            )
            for fusion, (name, candidates), strategy, priorities in product(
                args.fusion or [FUSION], reranks, strategies, args.priorities or [None]
            ):
                reranker = load_reranker(name, candidates, settings.embedding_cache_dir)
                threshold = settings.retrieval_score_threshold
                transform = strategy_of(transformer, strategy, runner)
                report = run(
                    indexed,
                    args.dataset,
                    args.split,
                    fusion,
                    reranker,
                    threshold,
                    strategy,
                    transform,
                    priorities,
                )
                reports.append(report)
                retrieval = f"{sparse}-{fusion}__rerank-{report.rerank}__{strategy}"
                if contextual:
                    retrieval += f"__ctx-{_contextual(contextual).replace(',', '-')}"
                if priorities:
                    retrieval += f"__prio-{priorities.stem}"
                slug = f"{model}__{size}-{overlap}-{parent}__{retrieval.replace(':', '-')}"
                stem = (
                    f"{args.out}/{datetime.now(UTC):%Y%m%dT%H%M%SZ}__{report.dataset}__"
                    f"{slug.replace('/', '-')}"
                )
                markdown = to_markdown(report)
                Path(f"{stem}.json").write_text(report.model_dump_json(indent=2))
                Path(f"{stem}.md").write_text(markdown)
                print(markdown)
                print(f"→ {Path(stem).resolve()}.json\n", flush=True)
                failed += regressions(report.overall, dict(args.baseline), args.tolerance)
    runner.close()
    if len(reports) > 1:
        print(comparison(reports))
    if failed:
        print("Retrieval regression:\n" + "\n".join(f"- {line}" for line in failed))
        raise SystemExit(1)
