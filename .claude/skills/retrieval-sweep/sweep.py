"""Index the corpus once into an on-disk Qdrant under argv[1], then run the golden split argv[2]
for every value of a module constant. Edit SWEEP for the knob at hand."""

import sys
from pathlib import Path

from qdrant_client import QdrantClient

from ai_service import knowledge_base as kbm
from ai_service.catalog import load_taxonomy
from ai_service.core.settings import Settings
from ai_service.embeddings import Embedder
from ai_service.evals.metrics import reciprocal_rank
from ai_service.evals.retrieval import Indexed, ingest_corpus, run

state, split = Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "dev"
s = Settings()
topics = load_taxonomy(s.taxonomy_config).topics()
fresh = not (state / "qdrant").exists()
kb = kbm.KnowledgeBase(
    QdrantClient(path=str(state / "qdrant")),
    Embedder(s.embedding_model, s.embedding_cache_dir),
    "eval",
    s.chunk_size,
    s.chunk_overlap,
    s.sparse_model,
    s.parent_size,
    topics=topics,
)
kb.ensure_collection()
if fresh:  # ~3.5 min with bge-m3; later runs start in seconds
    ingest_corpus(kb, Path("../../data/sample-docs"))
indexed = Indexed(kb, 17, 0, 0, [], {})
dataset = Path("../../evals/datasets/retrieval_v1.jsonl")
extra: dict[str, Path] = {}  # e.g. {"priorities": Path("../../evals/datasets/priorities_v1.json")}

SWEEP = [("QUESTION_TOPICS", value) for value in (1, 2, 3)]  # (module constant, value)

base = run(indexed, dataset, split, checked_threshold=s.retrieval_score_threshold)
reports = [("baseline", base)]
for name, value in SWEEP:
    setattr(kbm, name, value)
    reports.append(
        (
            f"{name}={value}",
            run(indexed, dataset, split, checked_threshold=s.retrieval_score_threshold, **extra),
        )
    )
for label, r in reports:
    o = r.overall
    print(
        f"{label:24}",
        " ".join(f"{k} {o[k]:.3f}" for k in ("hit@1", "hit@5", "mrr@10", "ndcg@10")),
        f"abst {r.checked_balanced_accuracy:.2f}",
    )
    for a, b in zip(base.items, r.items, strict=True):
        if a.gains != b.gains:
            before, after = reciprocal_rank(a.gains, 10), reciprocal_rank(b.gains, 10)
            print(f"    {a.id} rr {before:.2f} → {after:.2f}  {b.top_hits[:1]}")
