"""Manual LLM quality pass: 10 golden questions through ChatPipeline against real OpenRouter models.

Run from apps/ai-service:
    .venv/bin/python ../../.claude/skills/llm-quality-pass/quality_pass.py MODEL...
"""

import asyncio
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import openai
from qdrant_client import QdrantClient

from ai_service.core.settings import Settings
from ai_service.embeddings import Embedder
from ai_service.knowledge_base import KnowledgeBase
from ai_service.llm import OpenAICompatProvider
from ai_service.rag import ChatPipeline, ChatTurn, invalid_citations

IDS = ["r-002", "r-007", "r-011", "r-014", "r-016", "r-024", "r-028", "r-033", "u-003", "u-005"]
ROOT = Path("../..")

env = dict(
    line.split("=", 1)
    for line in (ROOT / ".env").read_text().splitlines()
    if "=" in line and not line.startswith("#")
)
key = env["LLM_API_KEY"].split("#")[0].strip()
settings = Settings()
items = {
    x["id"]: x
    for x in map(json.loads, (ROOT / "evals/datasets/retrieval_v1.jsonl").read_text().splitlines())
}
corpus = ROOT / "data/sample-docs"
kb = KnowledgeBase(
    QdrantClient(":memory:"),
    Embedder(settings.embedding_model, settings.embedding_cache_dir),
    "kb",
    settings.chunk_size,
    settings.chunk_overlap,
)
kb.ensure_collection()
for name, domains in json.loads((corpus / "domains.json").read_text()).items():
    data = (corpus / name).read_bytes()
    doc_id = uuid5(NAMESPACE_URL, name)
    kb.ingest(doc_id=doc_id, filename=name, data=data, owner_id="eval", domains=domains)


async def run(model: str) -> list[dict[str, Any]]:
    client = openai.AsyncOpenAI(base_url=settings.llm_base_url, api_key=key, max_retries=3)
    provider = OpenAICompatProvider(client, model, settings.llm_max_output_tokens)
    threshold = settings.retrieval_score_threshold
    pipeline = ChatPipeline(kb, provider, settings.retrieval_top_k, threshold)
    results: list[dict[str, Any]] = []
    for qid in IDS:
        started, ttft, answer, sources, done, error = time.perf_counter(), 0.0, "", [], None, None
        turns = [ChatTurn(role="user", content=items[qid]["question"])]
        async for event in pipeline.stream(turns, None, "quality-pass"):
            if event.event == "sources":
                sources = event.data.sources
            elif event.event == "token":
                ttft = ttft or time.perf_counter() - started
                answer += event.data.text
            elif event.event == "done":
                done = event.data
            elif event.event == "error":
                error = event.data.detail
        results.append(
            {
                "id": qid,
                "question": items[qid]["question"],
                "answerable": items[qid]["answerable"],
                "model": model,
                "sources": [f"{s.title} § {s.heading or s.page} ({s.score:.2f})" for s in sources],
                "answer": answer,
                "invalid_citations": invalid_citations(answer, len(sources)),
                "ttft_s": round(ttft, 2),
                "total_s": round(time.perf_counter() - started, 2),
                "usage": done.usage.model_dump() if done and done.usage else None,
                "error": error,
            }
        )
    return results


results = [r for model in sys.argv[1:] for r in asyncio.run(run(model))]
out = ROOT / f"evals/runs/quality-pass-{datetime.now(UTC):%Y%m%dT%H%M%S}.json"
out.write_text(json.dumps(results, indent=1, ensure_ascii=False))
for model in sys.argv[1:]:
    rows = [r for r in results if r["model"] == model]
    usages = [r["usage"] or {} for r in rows]
    print(
        f"{model}: cost {sum(u.get('costUsd') or 0 for u in usages) * 100:.3f} ct · "
        f"ttft p50 {statistics.median(r['ttft_s'] for r in rows):.2f}s · "
        f"output max {max(u.get('outputTokens', 0) for u in usages)} · "
        f"invalid citations {sum(len(r['invalid_citations']) for r in rows)} · "
        f"errors {sum(bool(r['error']) for r in rows)}"
    )
print(f"answers: {out}")
