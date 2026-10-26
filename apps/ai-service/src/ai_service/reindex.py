"""Re-index (D55, ADR-0015): build a collection from the stored originals, compare it with the live
one on the golden `dev` and `test` items, and move the alias only if no `test` metric drops."""

import asyncio
import hashlib
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from pypdf.errors import PyPdfError
from qdrant_client import QdrantClient

from ai_service.contextual import Contextualizer
from ai_service.evals.metrics import balanced_accuracy
from ai_service.evals.retrieval import GoldenItem, evaluate, load_dataset, regressions, summarize
from ai_service.ingest import parse_stored
from ai_service.knowledge_base import KnowledgeBase, first_chunks, live_collection, swap
from ai_service.storage import JobState, Store

GATE = ("hit@5", "mrr@10", "ndcg@10", "abstention")
TOLERANCE = 0.02


class Skipped(BaseModel):
    doc_id: UUID
    filename: str
    reason: str


class ReindexReport(BaseModel):
    reason: str
    force: bool
    requested_by: str
    collection: str
    previous: str
    documents: int
    chunks: int
    skipped: list[Skipped]
    metrics: dict[str, dict[str, dict[str, float]]]  # split → `live` | `candidate` → metric
    blockers: list[str]
    decision: Literal["swapped", "kept", "forced"]
    build_s: float
    context_cost_usd: dict[str, float] = {}  # per filename: contextual retrieval (D60)


async def reindex(
    kb: KnowledgeBase,
    contextualizer: Contextualizer,
    store: Store,
    golden: Path,
    threshold: float | None,
    *,
    reason: str,
    force: bool,
    requested_by: str,
    stage: Callable[[JobState], Awaitable[None]],
) -> ReindexReport:
    started = time.perf_counter()
    await stage("building")
    target = kb.at(await asyncio.to_thread(kb.create_collection))
    live = await asyncio.to_thread(first_chunks, kb.client, kb.alias)
    stored = await store.latest_versions()
    skipped: list[Skipped] = []
    costs: dict[str, float] = {}
    for doc_id, payload in live.items():
        data = await store.original(doc_id, stored[doc_id]) if doc_id in stored else None
        if data is None:
            why = "no stored original: `pnpm kb:backfill-originals`, or upload it again"
            skipped.append(Skipped(doc_id=doc_id, filename=payload["filename"], reason=why))
            continue
        try:
            filename, version, domains = payload["filename"], stored[doc_id], payload["domains"]
            sections = await parse_stored(store, doc_id, version, filename, data)
            split = await asyncio.to_thread(target.split, sections)
            split, costs[filename] = await contextualizer.contextualize(
                sections, split, doc_id=doc_id, version=version, domains=domains
            )
            await asyncio.to_thread(
                target.index,
                split,
                doc_id=doc_id,
                version=version,
                filename=filename,
                sha256=hashlib.sha256(data).hexdigest(),
                owner_id=payload["owner_id"],
                domains=domains,
                topics=payload.get("topics", []),
                title=payload["title"],
            )
        except (ValueError, PyPdfError) as error:
            skipped.append(Skipped(doc_id=doc_id, filename=payload["filename"], reason=str(error)))
    # Deletes and relabels reach every collection, but not a document upserted after them.
    stored = await store.latest_versions()
    live = await asyncio.to_thread(first_chunks, kb.client, kb.alias)
    await asyncio.to_thread(target.reconcile, {d: p for d, p in live.items() if d in stored})

    await stage("evaluating")
    previous = await asyncio.to_thread(kb.live_collection)
    comparable = kb.model_key in previous  # same model and dimension: the scores compare
    items = load_dataset(golden)
    metrics: dict[str, dict[str, dict[str, float]]] = {}
    for split in ("dev", "test"):
        part = [item for item in items if item.split == split]
        metrics[split] = {"candidate": await asyncio.to_thread(score, target, part, threshold)}
        if comparable:
            live_kb = kb.at(previous)
            metrics[split]["live"] = await asyncio.to_thread(score, live_kb, part, threshold)
    blockers = [f"{s.filename}: {s.reason}" for s in skipped]
    if comparable:
        test = metrics["test"]
        gate = {metric: value for metric, value in test["live"].items() if metric in GATE}
        blockers += [f"test {line}" for line in regressions(test["candidate"], gate, TOLERANCE)]
    else:
        blockers.append(f"{previous} was built with another embedding model: nothing to compare")

    documents = len(await asyncio.to_thread(first_chunks, target.client, target.alias))
    chunks = (await asyncio.to_thread(target.client.count, target.alias)).count
    decision = "forced" if blockers and force else "kept" if blockers else "swapped"
    if decision == "kept":
        await asyncio.to_thread(kb.client.delete_collection, target.alias)
    else:
        await asyncio.to_thread(kb.swap, target.alias)
    return ReindexReport(
        reason=reason,
        force=force,
        requested_by=requested_by,
        collection=target.alias,
        previous=previous,
        documents=documents,
        chunks=chunks,
        skipped=skipped,
        metrics=metrics,
        blockers=blockers,
        decision=decision,
        build_s=time.perf_counter() - started,
        context_cost_usd={name: cost for name, cost in costs.items() if cost},
    )


def score(kb: KnowledgeBase, items: list[GoldenItem], threshold: float | None) -> dict[str, float]:
    results = evaluate(kb, items)
    answerable = [r.top1_score for r in results if r.answerable]
    unanswerable = [r.top1_score for r in results if not r.answerable]
    if not answerable:
        return {}
    metrics = summarize([r for r in results if r.answerable])
    if threshold is not None and unanswerable:
        metrics["abstention"] = balanced_accuracy(answerable, unanswerable, threshold)
    return metrics


def rollback(client: QdrantClient, alias: str, reports: list[ReindexReport]) -> str:
    """Point the alias back at the collection the swap to the live one replaced (newest first)."""
    live = live_collection(client, alias)
    swapped = (r for r in reports if r.decision != "kept" and r.collection == live)
    previous = next((r.previous for r in swapped), None)
    if previous is None or not client.collection_exists(previous):
        raise LookupError(f"Nothing to roll back to: no kept collection was replaced by {live}")
    swap(client, alias, previous)
    return previous


def summary(report: ReindexReport) -> str:
    lines = [
        f"{report.decision}: {report.collection} ({report.documents} documents, "
        f"{report.chunks} chunks, {report.build_s:.0f} s, contexts "
        f"{sum(report.context_cost_usd.values()):.4f} USD); live was {report.previous}"
    ]
    for split, sides in report.metrics.items():
        candidate, live = sides["candidate"], sides.get("live", {})
        cells = [
            f"{m} {candidate[m]:.3f}" + (f" ({candidate[m] - live[m]:+.3f})" if m in live else "")
            for m in GATE
            if m in candidate
        ]
        lines.append(f"{split}: " + " · ".join(cells))
    return "\n".join(lines + [f"- {blocker}" for blocker in report.blockers])
