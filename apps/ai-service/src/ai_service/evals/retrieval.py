"""`kb-eval retrieval`: ingest the corpus into an in-memory Qdrant, run the golden set, report.

Run from `apps/ai-service` (as `pnpm eval:retrieval` does); default paths are relative to it.
"""

import argparse
import time
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from statistics import mean
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, TypeAdapter
from qdrant_client import QdrantClient

from ai_service.core.settings import Settings
from ai_service.embeddings import Embedder
from ai_service.evals.metrics import (
    calibrate_threshold,
    hit_at,
    ndcg,
    percentile,
    reciprocal_rank,
)
from ai_service.ingest import HEADING_SEPARATOR
from ai_service.knowledge_base import Domain, Hit, KnowledgeBase

TOP_K = 10
MANIFEST = "domains.json"
_manifest = TypeAdapter(dict[str, list[Domain]])


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


class ItemResult(BaseModel):
    id: str
    question: str
    lang: str
    domains: list[Domain]
    answerable: bool
    relevant_count: int
    gains: list[int]
    top1_score: float
    latency_ms: float
    top_hits: list[str]


class RunReport(BaseModel):
    dataset: str
    model: str
    dim: int
    chunk_size: int
    chunk_overlap: int
    documents: int
    chunks: int
    ingest_s: float
    created_at: str
    overall: dict[str, float]
    by_domain: dict[str, dict[str, float]]
    by_lang: dict[str, dict[str, float]]
    threshold: float | None
    threshold_balanced_accuracy: float | None
    items: list[ItemResult]


def load_dataset(path: Path) -> list[GoldenItem]:
    return [GoldenItem.model_validate_json(line) for line in path.read_text().splitlines() if line]


def load_manifest(corpus: Path) -> dict[str, list[Domain]]:
    return _manifest.validate_json((corpus / MANIFEST).read_bytes())


def doc_id(filename: str) -> UUID:
    """Stable per file, so a report can name a cited document."""
    return uuid5(NAMESPACE_URL, filename)


def ingest_corpus(kb: KnowledgeBase, corpus: Path) -> int:
    """Every file of the corpus manifest, with its domains; returns the chunk count."""
    return sum(
        kb.ingest(
            doc_id=doc_id(name),
            filename=name,
            data=(corpus / name).read_bytes(),
            owner_id="eval",
            domains=domains,
        ).chunk_count
        for name, domains in load_manifest(corpus).items()
    )


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


def run(
    embedder: Embedder,
    dataset: Path,
    corpus: Path,
    chunk_size: int,
    chunk_overlap: int,
    split: str | None = None,
) -> RunReport:
    kb = KnowledgeBase(QdrantClient(":memory:"), embedder, "eval", chunk_size, chunk_overlap)
    kb.ensure_collection()
    started = time.perf_counter()
    chunks = ingest_corpus(kb, corpus)
    ingest_s = time.perf_counter() - started

    results: list[ItemResult] = []
    for item in load_dataset(dataset):
        if split and item.split != split:
            continue
        started = time.perf_counter()
        hits = kb.search(item.question, TOP_K)
        latency_ms = (time.perf_counter() - started) * 1000
        results.append(
            ItemResult(
                id=item.id,
                question=item.question,
                lang=item.lang,
                domains=item.domains,
                answerable=item.answerable,
                relevant_count=len(item.relevant),
                gains=gains(item, hits),
                top1_score=hits[0].score if hits else 0.0,
                latency_ms=latency_ms,
                top_hits=[
                    f"{h.filename} § {h.heading or f'p{h.page}'} ({h.score:.3f})" for h in hits[:3]
                ],
            )
        )

    answerable = [r for r in results if r.answerable]
    unanswerable = [r.top1_score for r in results if not r.answerable]
    threshold, accuracy = (
        calibrate_threshold([r.top1_score for r in answerable], unanswerable)
        if answerable and unanswerable
        else (None, None)
    )
    latencies = [r.latency_ms for r in results]
    domains = sorted({d for r in answerable for d in r.domains})
    return RunReport(
        dataset=f"{dataset.stem}-{split}" if split else dataset.stem,
        model=embedder.model_name,
        dim=embedder.dim,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        documents=len(load_manifest(corpus)),
        chunks=chunks,
        ingest_s=ingest_s,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        overall={
            **summarize(answerable),
            "p50_ms": percentile(latencies, 50),
            "p95_ms": percentile(latencies, 95),
        },
        by_domain={d: summarize([r for r in answerable if d in r.domains]) for d in domains},
        by_lang={
            lang: summarize([r for r in answerable if r.lang == lang])
            for lang in sorted({r.lang for r in answerable})
        },
        threshold=threshold,
        threshold_balanced_accuracy=accuracy,
        items=results,
    )


def to_markdown(report: RunReport) -> str:
    def row(label: str, m: dict[str, float]) -> str:
        values = " | ".join(f"{m[key]:.2f}" for key in ("hit@1", "hit@5", "mrr@10", "ndcg@10"))
        return f"| {label} | {m['n']:.0f} | {values} |"

    o = report.overall
    lines = [
        f"## Retrieval eval · {report.dataset} · `{report.model}` · chunks "
        f"{report.chunk_size}/{report.chunk_overlap}",
        "",
        f"{report.chunks} chunks from {report.documents} documents, "
        f"ingest {report.ingest_s:.1f} s · "
        f"{len(report.items)} questions ({o['n']:.0f} answerable) · "
        f"latency p50 {o['p50_ms']:.0f} ms / p95 {o['p95_ms']:.0f} ms",
        "",
    ]
    if report.threshold is not None and report.threshold_balanced_accuracy is not None:
        lines += [
            f"Suggested `score_threshold`: **{report.threshold:.3f}** (balanced accuracy "
            f"{report.threshold_balanced_accuracy:.2f}, answerable vs. unanswerable top-1 scores)",
            "",
        ]
    lines += ["| Slice | n | hit@1 | hit@5 | MRR@10 | nDCG@10 |", "|---|---|---|---|---|---|"]
    lines.append(row("**overall**", o))
    lines += [row(f"domain `{d}`", m) for d, m in report.by_domain.items()]
    lines += [row(f"lang `{lang}`", m) for lang, m in report.by_lang.items()]
    misses = [r for r in report.items if r.answerable and not any(r.gains[:5])]
    if misses:
        lines += ["", "Misses (no relevant hit in the top 5):", ""]
        lines += [f"- `{r.id}` {r.question} → {'; '.join(r.top_hits[:1])}" for r in misses]
    return "\n".join(lines) + "\n"


def comparison(reports: list[RunReport]) -> str:
    lines = [
        "| Model | Chunks | Points | Ingest s | hit@1 | hit@5 | MRR@10 | nDCG@10 | p50 ms | p95 ms "
        "| Threshold |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in reports:
        o = r.overall
        lines.append(
            f"| `{r.model}` | {r.chunk_size}/{r.chunk_overlap} | {r.chunks} | {r.ingest_s:.0f} "
            f"| {o['hit@1']:.2f} | {o['hit@5']:.2f} | {o['mrr@10']:.2f} | {o['ndcg@10']:.2f} "
            f"| {o['p50_ms']:.0f} | {o['p95_ms']:.0f} | {r.threshold or 0:.3f} |"
        )
    return "\n".join(lines) + "\n"


def regressions(
    overall: dict[str, float], baseline: dict[str, float], tolerance: float
) -> list[str]:
    """The metrics more than `tolerance` below their baseline (D43: the CI gate)."""
    return [
        f"{metric} {overall[metric]:.3f} < baseline {value:.3f} - {tolerance}"
        for metric, value in baseline.items()
        if overall[metric] < value - tolerance
    ]


def _chunk_arg(value: str) -> tuple[int, int]:
    size, _, overlap = value.partition(":")
    return int(size), int(overlap or 0)


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
        metavar="SIZE:OVERLAP",
        help="repeat to benchmark (default: CHUNK_SIZE:CHUNK_OVERLAP)",
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
    for model in args.model or [settings.embedding_model]:
        embedder = Embedder(model, settings.embedding_cache_dir)
        for size, overlap in args.chunk or [(settings.chunk_size, settings.chunk_overlap)]:
            report = run(embedder, args.dataset, args.corpus, size, overlap, args.split)
            reports.append(report)
            stem = (
                f"{args.out}/{datetime.now(UTC):%Y%m%dT%H%M%SZ}__{report.dataset}__"
                f"{model.replace('/', '-')}__{size}-{overlap}"
            )
            markdown = to_markdown(report)
            Path(f"{stem}.json").write_text(report.model_dump_json(indent=2))
            Path(f"{stem}.md").write_text(markdown)
            print(markdown)
            print(f"→ {Path(stem).resolve()}.json\n", flush=True)
            failed += regressions(report.overall, dict(args.baseline), args.tolerance)
    if len(reports) > 1:
        print(comparison(reports))
    if failed:
        print("Retrieval regression:\n" + "\n".join(f"- {line}" for line in failed))
        raise SystemExit(1)
