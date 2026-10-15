# ADR-0004: Embedding model, chunking and score threshold

- **Status:** Accepted
- **Date:** 2026-10-15
- **Plan reference:** D8, D9, D10, D23

## Context

[ADR-0003](0003-embeddings-in-process.md) put embeddings in-process (fastembed, ONNX, CPU) and left the
model to a benchmark. Inputs to that benchmark:

- **Golden set** `evals/datasets/retrieval_v1.jsonl`, written before any tuning: 60 questions — 50
  answerable (15 DE, 35 EN; direct, paraphrase, cross-language, multi-label) and 10 unanswerable near
  misses.
- **Corpus** `data/sample-docs/`: 17 documents — repo docs and ADRs (snapshots), nine self-written
  runbooks (two in German), one 3-page PDF.
- **Runs:** `pnpm eval:retrieval --model … --chunk 1000:150 --chunk 500:75` — in-memory Qdrant, top 10,
  no filter, no threshold. MacBook M1, 16 GB, CPU only. Latency = query embedding + search, in-process.
  Run files: `evals/runs/20261015T12*` (git-ignored).

## Results

| Model | Chunks | Points | Ingest s | hit@1 | hit@5 | MRR@10 | nDCG@10 | p50 ms | p95 ms | Threshold |
|---|---|---|---|---|---|---|---|---|---|---|
| `intfloat/multilingual-e5-small` | 1000/150 | 218 | 16 | 0.56 | 0.86 | 0.69 | 0.72 | 7 | 10 | 0.843 |
| `intfloat/multilingual-e5-small` | 500/75 | 378 | 17 | 0.58 | 0.92 | 0.72 | 0.76 | 7 | 13 | 0.848 |
| `intfloat/multilingual-e5-base` | 1000/150 | 218 | 56 | 0.64 | 0.86 | 0.73 | 0.75 | 22 | 29 | 0.833 |
| `intfloat/multilingual-e5-base` | 500/75 | 378 | 63 | 0.68 | 0.88 | 0.75 | 0.78 | 23 | 30 | 0.830 |
| `intfloat/multilingual-e5-large` | 1000/150 | 218 | 178 | 0.68 | 0.94 | 0.80 | 0.83 | 71 | 88 | 0.845 |
| `intfloat/multilingual-e5-large` | 500/75 | 378 | 224 | 0.68 | 0.94 | 0.79 | 0.83 | 71 | 92 | 0.851 |
| **`BAAI/bge-m3`** | **1000/150** | 218 | 178 | **0.76** | **0.98** | **0.84** | **0.86** | 59 | 77 | **0.557** |
| `BAAI/bge-m3` | 500/75 | 378 | 210 | 0.76 | 0.98 | 0.84 | 0.85 | 60 | 79 | 0.603 |

Slices at 1000/150:

| Model | hit@1 DE / EN | hit@5 DE / EN | Weakest domain (hit@5) | Threshold balanced accuracy |
|---|---|---|---|---|
| e5-small | 0.47 / 0.60 | 0.87 / 0.86 | cloud 0.75, sre 0.77 | 0.78 |
| e5-base | 0.53 / 0.69 | 0.87 / 0.86 | sre 0.69, security 0.71 | 0.77 |
| e5-large | 0.47 / 0.77 | 0.93 / 0.94 | sre 0.77 | 0.73 |
| **bge-m3** | **0.80 / 0.74** | **1.00 / 0.97** | ai 0.89 | **0.87** |

E5 scores are squeezed into 0.77–0.90: unanswerable top-1 scores (0.77–0.86) overlap the answerable ones
almost completely, so no threshold separates them well. bge-m3 spreads them (unanswerable 0.43–0.61,
answerable median 0.63). The only bge-m3 miss in the top 5 is `r-033` (a status-code table row ranked
below a symptom list).

## Decision

- **`EMBEDDING_MODEL=BAAI/bge-m3`** (dense vector, CLS pooling, 1024 dimensions, no prefixes). It is best on
  every overall metric and both languages, and the only candidate whose scores support a usable
  threshold.
- **Chunking stays at `CHUNK_SIZE=1000`, `CHUNK_OVERLAP=150`.** 500/75 brings nothing for bge-m3 (nDCG
  0.85 vs. 0.86) and costs 73 % more points and ingest time; larger chunks also give the LLM more context
  per citation.
- **`RETRIEVAL_SCORE_THRESHOLD=0.55`** — the calibrated 0.557, rounded down in favour of recall. It applies
  to chat retrieval (M1.3) only; `/v1/search` (inspector) and the eval run without a threshold. The
  prompt's "not in the knowledge base" rule remains the main defence against unanswerable questions.
- Re-run the benchmark whenever the corpus, the dataset version or the chunker changes; thresholds are
  model-specific and are recalibrated with every model change.

## Alternatives considered

- **`multilingual-e5-large`** — second best (hit@5 0.94) at the same ingest cost as bge-m3, but weaker in
  German (hit@1 0.47) and with the worst threshold separation (0.73).
- **`multilingual-e5-base`** (previous default) — three times faster ingest, but hit@1 0.64 and hit@5 of
  0.69–0.71 in the sre and security slices.
- **`multilingual-e5-small`** — fastest (16 s ingest, 7 ms queries) and surprisingly close at 500/75
  (hit@5 0.92). Fallback for 8 GB machines (plan.md A1) and a candidate for a cheap CI smoke eval.

## Consequences

- First start downloads **≈ 2.3 GB** (instead of 1.1 GB); the AI service process holds **≈ 1.8 GB RSS**.
  Containers (M1.6) need the model baked in or a cached volume.
- Ingest is CPU-bound: 218 chunks took 178 s in the benchmark (≈ 1.2 chunks/s, long plan.md chunks); a
  live 8-chunk runbook took 3 s. Fine with background ingest and status polling (D7); batching or a
  queue comes in Phase 3. Query latency (p50 59 ms, p95 77 ms) is negligible next to the LLM call.
- The model id contains no `e5`, so the embedder adds no prefixes (covered by `tests/test_embeddings.py`).
- Switching an existing setup points `kb_current` at a new, empty collection `kb__baai-bge-m3__1024` —
  re-ingest (`runbook-embedding-model-swap.md`). Developers update `EMBEDDING_MODEL` and
  `RETRIEVAL_SCORE_THRESHOLD` in their local `.env`.
- bge-m3 can also produce sparse (lexical) weights — the hybrid-search path of D9. Getting them
  in-process is a Phase 3 spike.
- **Limits of the evidence:** 50 answerable and 10 unanswerable questions, written by the corpus author.
  Differences below ≈ 0.04 (two questions) are noise, and the threshold rests on ten items. The CI eval
  job (M1.6) must cache the model directory; if the download is too slow there, CI runs e5-small as a
  smoke check and bge-m3 numbers stay a local measurement.
