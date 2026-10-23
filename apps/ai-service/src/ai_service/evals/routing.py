"""`kb-eval routing`: router accuracy on `routing_v1` (D33), embedding vs LLM (ADR-0012)."""

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from statistics import mean
from typing import Any, Literal

from pydantic import BaseModel

from ai_service.catalog import load_taxonomy
from ai_service.core.settings import Settings
from ai_service.embeddings import Embedder
from ai_service.evals.metrics import percentile
from ai_service.knowledge_base import Domain
from ai_service.llm import create_provider
from ai_service.routing import MIN_CONFIDENCE, PROMPT, EmbeddingRouter, LlmRouter, Route, Router


class RoutingItem(BaseModel):
    id: str
    question: str
    lang: Literal["de", "en"]
    domains: list[Domain]  # [] = no domain (small talk)
    needs_tools: bool
    notes: str = ""


class Routed(BaseModel):
    id: str
    domains: list[Domain]  # predicted
    needs_tools: bool
    confidence: float
    correct: bool
    latency_ms: float
    cost_usd: float


class RoutingReport(BaseModel):
    dataset: str
    router: str
    model: str | None
    prompt: str | None  # id@version hash of the classifier's prompt (D46)
    created_at: str
    overall: dict[str, float]
    by_domain: dict[str, dict[str, float]]
    items: list[Routed]


def load_items(path: Path) -> list[RoutingItem]:
    return [RoutingItem.model_validate_json(line) for line in path.read_text().splitlines() if line]


def correct(item: RoutingItem, route: Route) -> bool:
    """A labelled domain among the predicted ones; small talk wants none (or no tools)."""
    if not item.domains:
        return not route.domains or not route.needs_tools
    return bool(set(route.domains) & set(item.domains))


def summarize(items: list[RoutingItem], routed: list[Routed]) -> dict[str, float]:
    labelled = {item.id: item for item in items}
    sure = [r for r in routed if r.confidence >= MIN_CONFIDENCE]
    latencies = [r.latency_ms for r in routed]
    return {
        "n": len(routed),
        "accuracy": mean(r.correct for r in routed),
        "confident": len(sure) / len(routed),
        "accuracy_confident": mean(r.correct for r in sure) if sure else 0.0,
        # A confident wrong route filters the search and drops tools: the costly mistake.
        "confident_wrong": sum(not r.correct for r in sure) / len(routed),
        "needs_tools_accuracy": mean(r.needs_tools == labelled[r.id].needs_tools for r in routed),
        "cost_usd": sum(r.cost_usd for r in routed),
        "p50_ms": percentile(latencies, 50),
        "p95_ms": percentile(latencies, 95),
    }


async def run(router: Router, name: str, model: str | None, dataset: Path) -> RoutingReport:
    items = load_items(dataset)
    routed: list[Routed] = []
    for item in items:
        started = time.perf_counter()
        route = await router.route(item.question)
        routed.append(
            Routed(
                id=item.id,
                domains=route.domains,
                needs_tools=route.needs_tools,
                confidence=route.confidence,
                correct=correct(item, route),
                latency_ms=(time.perf_counter() - started) * 1000,
                cost_usd=(route.usage and route.usage.cost_usd) or 0.0,
            )
        )
    by_id = {r.id: r for r in routed}
    domains = sorted({d for item in items for d in item.domains})
    return RoutingReport(
        dataset=dataset.stem,
        router=name,
        model=model,
        prompt=f"{PROMPT.ref} {PROMPT.hash}" if name == "llm" else None,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        overall=summarize(items, routed),
        by_domain={
            domain: summarize(chunk, [by_id[item.id] for item in chunk])
            for domain in domains
            if (chunk := [item for item in items if domain in item.domains])
        },
        items=routed,
    )


def to_markdown(reports: list[RoutingReport]) -> str:
    def row(label: str, m: dict[str, float]) -> str:
        return (
            f"| {label} | {m['n']:.0f} | {m['accuracy']:.2f} | {m['confident']:.2f} "
            f"| {m['accuracy_confident']:.2f} | {m['confident_wrong']:.2f} "
            f"| {m['needs_tools_accuracy']:.2f} | {m['cost_usd']:.4f} | {m['p50_ms']:.0f} "
            f"| {m['p95_ms']:.0f} |"
        )

    header = [
        "| Slice | n | accuracy | confident | accuracy (confident) | confident & wrong "
        "| needs_tools | USD | p50 ms | p95 ms |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    lines = [f"## Routing eval · {reports[0].dataset}", "", *header]
    lines += [
        row(f"**{r.router}** `{r.model}`" + (f" · `{r.prompt}`" if r.prompt else ""), r.overall)
        for r in reports
    ]
    for report in reports:
        lines += ["", f"### {report.router}", "", *header]
        lines += [row(f"domain `{d}`", m) for d, m in report.by_domain.items()]
    return "\n".join(lines) + "\n"


def add_command(commands: Any, settings: Settings) -> None:
    cmd = commands.add_parser("routing", help="router accuracy: embedding vs LLM classifier")
    cmd.add_argument("--dataset", type=Path, default=Path("../../evals/datasets/routing_v1.jsonl"))
    cmd.add_argument("--out", type=Path, default=Path("../../evals/runs"))
    cmd.add_argument(
        "--router",
        action="append",
        choices=["embedding", "llm"],
        help="repeat to compare (default: ROUTER)",
    )
    cmd.add_argument("--model", help="classifier model for `llm` (default: ROUTER_MODEL)")
    cmd.set_defaults(run=partial(_main, settings=settings))


def _main(args: argparse.Namespace, settings: Settings) -> None:
    taxonomy = load_taxonomy(settings.taxonomy_config)
    reports: list[RoutingReport] = []
    for name in args.router or [settings.router]:
        router: Router
        if name == "llm":
            model = args.model or settings.router_model or settings.llm_model
            router = LlmRouter(create_provider(settings), taxonomy, model)
        else:
            model = settings.embedding_model
            embedder = Embedder(settings.embedding_model, settings.embedding_cache_dir)
            router = EmbeddingRouter(embedder, taxonomy)
        reports.append(asyncio.run(run(router, name, model, args.dataset)))
    args.out.mkdir(parents=True, exist_ok=True)
    stem = f"{args.out}/{datetime.now(UTC):%Y%m%dT%H%M%SZ}__{reports[0].dataset}"
    markdown = to_markdown(reports)
    Path(f"{stem}.json").write_text(
        json.dumps([r.model_dump(mode="json") for r in reports], indent=2)
    )
    Path(f"{stem}.md").write_text(markdown)
    print(markdown)
    print(f"→ {Path(stem).resolve()}.json", flush=True)
