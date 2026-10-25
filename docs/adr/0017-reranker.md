# ADR-0017: Reranking — built and measured, off by default

- **Status:** Accepted (M3a.3)
- **Date:** 2026-10-25
- **Plan reference:** D57, D50, D51 ([plan-phase-3.md §3](../../plan-phase-3.md#3-decisions))

## Context

A cross-encoder over the fused hybrid candidates (ADR-0016) was the largest expected quality gain of
Phase 3a. Budget (D57, D50): p95 rerank ≤ 1.5 s on the M1, ≤ ~2.5 GB, 20–50 candidates; the corpus is
German and English; the repo is MIT, so the model licence matters. A model that breaks the budget loses
even if it scores higher (D50); candidates are chosen on `dev`, `test` is run once (D51), and a change
that drops a `test` metric by more than 0.02 would not pass the re-index gate (D55).

## Decision

- **No reranker by default** (`RERANKER_MODEL=none`). The only model within the latency budget that
  gains on `dev`, `jinaai/jina-reranker-v2-base-multilingual` int8 over 10 candidates, loses hit@5 on
  `test` (0.95 → 0.85) — both misses are exact-term items hybrid search had just rescued — sits on the
  latency limit (p95 1.48–1.54 s over four runs) and is CC BY-NC 4.0. On the full set (the CI gate) hit@5 drops 0.98 →
  0.94, below the gate.
- **The code path stays, opt-in:** with `RERANKER_MODEL` set, the AI service loads a fastembed
  cross-encoder (ONNX, CPU, no PyTorch) and scores the top `RERANK_CANDIDATES` (10; `top_k` if larger)
  fused hits against the query; the best `top_k` stay. `score` becomes the logit through a sigmoid (0–1),
  and `RETRIEVAL_SCORE_THRESHOLD` applies to it, so each reranker needs its own threshold, calibrated on
  `dev`: jina int8 **0.35**, `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1-int8` (Apache-2.0) **0.40**,
  `none` 0.55 (ADR-0004). It takes effect on restart; the collection does not change, so no re-index.
- Two int8 exports not in fastembed's list are registered as custom models, named like fastembed's
  own `BAAI/bge-reranker-v2-m3-int8`: `jinaai/jina-reranker-v2-base-multilingual-int8`
  (`onnx/model_int8.onnx`) and `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1-int8`
  (`onnx/model_qint8_arm64.onnx`).
- **`explain`** adds `fused_rank` (rank among the reranker's candidates; without a reranker the
  position), and `/v1/search` names the `reranker_model`; the inspector shows rerank, fused, dense and
  sparse rank.
- `kb-eval retrieval --rerank MODEL:CANDIDATES|none` (repeatable) benchmarks rerankers on one ingest
  of the corpus; each report also gives the balanced accuracy at `RETRIEVAL_SCORE_THRESHOLD`, for
  checking a `dev`-calibrated threshold on `test`.

## Evidence

`kb-eval retrieval`, bge-m3, chunks 1000/150, BM25 English, `rrf:2:0.5`, top 10, in-memory Qdrant,
MacBook Air M1 16 GB with nothing else running; latency is per query (embed, search, rerank).

`dev` (36 items, 30 answerable; abstention = balanced accuracy at the split's best threshold):

| Reranker : candidates | Licence | hit@1 | hit@5 | MRR@10 | nDCG@10 | DE / EN nDCG@10 | Abstention | p50 / p95 ms |
|---|---|---|---|---|---|---|---|---|
| none (hybrid, `m3a2-hybrid`) | — | 0.80 | 1.00 | 0.90 | 0.91 | 0.96 / 0.89 | 0.87 | 63 / 84 |
| `Xenova/ms-marco-MiniLM-L-6-v2` : 20 | Apache-2.0 | 0.63 | 0.90 | 0.75 | 0.79 | 0.60 / 0.87 | 0.87 | 872 / 1061 |
| `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1-int8` : 10 | Apache-2.0 | 0.80 | 1.00 | 0.89 | 0.91 | 0.94 / 0.90 | 0.90 | 485 / 596 |
| … : 20 | | 0.77 | 1.00 | 0.86 | 0.89 | 0.94 / 0.87 | 0.92 | 939 / 1135 |
| … : 30 | | 0.73 | 1.00 | 0.85 | 0.88 | 0.90 / 0.87 | 0.92 | 1430 / 1595 |
| **`jinaai/jina-reranker-v2-base-multilingual-int8` : 10** | CC BY-NC 4.0 | **0.87** | 1.00 | **0.93** | **0.94** | 0.96 / 0.93 | **0.97** | 1351 / **1475** |
| … : 20 | | 0.90 | 1.00 | 0.95 | 0.95 | 0.96 / 0.95 | 0.97 | 2716 / 2947 |
| `jinaai/jina-reranker-v2-base-multilingual` (fp32) : 20 | CC BY-NC 4.0 | 0.93 | 1.00 | 0.97 | 0.96 | 0.96 / 0.96 | 0.97 | 6360 / 6773 |
| `BAAI/bge-reranker-v2-m3-int8` : 20 | Apache-2.0 | 0.90 | 1.00 | 0.94 | 0.94 | 0.96 / 0.93 | 0.93 | 7455 / 8063 |

Only three rows fit 1.5 s: MiniLM (English only; German nDCG@10 0.96 → 0.60), mMiniLM at 10 (even with
hybrid: three items up a rank, four down) and jina int8 at 10. The two multilingual ones move the first
relevant hit only between ranks 1 and 3 on `dev`: the split is near its ceiling (hit@5 1.00 already),
and one item is 0.03.

`test` (20 answerable), once, jina int8 : 10 against hybrid (baselines `evals/baselines/m3a2-hybrid/`
and `m3a3-rerank/`):

| Slice | n | Hybrid hit@1 / hit@5 / MRR@10 / nDCG@10 | + rerank hit@1 / hit@5 / MRR@10 / nDCG@10 |
|---|---|---|---|
| **overall** | 20 | 0.70 / **0.95** / 0.79 / 0.81 | 0.70 / **0.85** / 0.78 / 0.81 |
| **exact terms** | 3 | 0.33 / **1.00** / 0.53 / 0.59 | 0.33 / **0.33** / 0.41 / 0.54 |
| direct lookup | 8 | 0.75 / 1.00 / 0.82 / 0.87 | 0.75 / 0.75 / 0.78 / 0.83 |
| cross-language | 4 | 0.75 / 1.00 / 0.83 / 0.79 | 0.75 / 1.00 / 0.81 / 0.82 |
| multi-chunk | 4 | 0.50 / 0.75 / 0.59 / 0.64 | 0.50 / 0.75 / 0.67 / 0.65 |
| paraphrase | 2 | 0.50 / 1.00 / 0.75 / 0.82 | 0.50 / 1.00 / 0.75 / 0.82 |
| lang `de` / `en` | 6 / 14 | nDCG@10 0.78 / 0.83 | nDCG@10 0.77 / 0.82 |

Per item: `r-015` (*'no space left on device'*, exact term, DE) rank 3 → 7 and `r-033` (*HTTP 402*,
exact term) 4 → 10 fall out of the top 5; `r-028` (multi-chunk) 5 → 2; `r-002` 3 → 4, `r-035` 7 → 6.
Abstention at the configured thresholds: 0.95 → 0.95 (hybrid at 0.55, rerank at the `dev`-calibrated
0.35; `test`'s own best would be 0.327, 0.97). Latency p50 / p95 67 / 79 → 1267 / 1481 ms. Full set (60
items, the CI gate): hit@1 0.76 → 0.80, hit@5 0.98 → 0.94, nDCG@10 0.87 → 0.89, abstention 0.87 → 0.96
(it contains `dev`, where the threshold was calibrated), p95 1533 ms.

Reading the numbers: the cross-encoder judges the passage's meaning and ignores that it carries the
literal error string — the failure dense retrieval had and BM25 fixed. `dev`'s three exact-term items
stay on top under every reranker, so `dev` could not show it, and tuning a fix on `test` would spend the
held-out split. The `dev` gain is two items at hit@1; it did not hold on `test`.

## Latency and memory (M3a.0 spike, M3a.3)

One model per process, 1,000-character chunks, German query, median of 3 after a warm-up; RSS growth
when loaded and run:

| Model | Runtime | 10 pairs | 20 pairs | 30 pairs | RSS |
|---|---|---|---|---|---|
| MiniLM-L6 | ONNX CPU fp32 | 0.43 s | 0.83 s | 1.21 s | +1.0 GB |
| mMiniLM-L12 | ONNX CPU fp32 / int8 | 0.88 / 0.51 s | 1.68 / 0.90 s | 2.37 / 1.32 s | +1.4 / +1.1 GB |
| jina-v2 base | ONNX CPU fp32 / int8 | 3.0 / 1.34 s | 6.2 / 2.5 s | 9.1 / 3.7 s | +2.4 / +2.0 GB |
| bge-reranker-v2-m3 | ONNX CPU int8 | 3.6 s | 6.7 s | 10.1 s | +2.1 GB |
| bge-reranker-v2-m3 (M3a.0) | torch 2.14 MPS fp16 | — | 2.5 s | — | +0.5 GB RSS + 1.1–2.3 GB MPS |

- Four onnxruntime threads (the M1's performance cores) instead of the default change nothing.
- onnxruntime's CoreML provider is no way out: mMiniLM 23 s for 10 pairs at +9.5 GB, jina fails.
- PyTorch on MPS (bge, M3a.0) would bring torch into the service process and only works natively on
  macOS — not in the Linux containers of Mode B, Phase 4 or Phase 5.
- With jina int8 loaded next to bge-m3, an eval run on `dev` peaks at 3.17 GB (2.50 GB
  without): within D50's ≤ ~6 GB for the AI service.

## Alternatives considered

- **jina int8 : 10 on by default** — `dev` +0.03 nDCG@10 and +0.10 abstention, but `test` hit@5 −0.10,
  exact terms back to dense's level, p95 on the budget line, +1.3 s per chat turn, non-commercial.
- **mMiniLM int8 : 10** (Apache-2.0, 0.6 s) — no ranking gain on `dev`; not worth 0.5 s per query.
- **More candidates or larger models** — better on `dev` (nDCG@10 0.95–0.96) at 2.9–8 s p95.
- **Relax the budget to ~3 s for `mode=rag`** (draft option 3) — jina int8 at 20 candidates (p95 2.9 s)
  gains 0.01 nDCG@10 on `dev` over 10; the exact-term loss is the same kind of error.
- **Protect exact terms** (keep BM25's top hit, or fuse the reranker's order with the hybrid ranks by
  RRF instead of replacing it) — plausible, but `dev` has no item to tune it on.

## Consequences

- Retrieval, latency, memory and the CI baseline stay as in ADR-0016; `fastembed` loads no reranker.
- Opting in changes `score` from the cosine to the reranker's: set `RETRIEVAL_SCORE_THRESHOLD` with
  `RERANKER_MODEL` (`.env.example`); the gate's abstention metric, the agent's `top_score` and the gap
  signal follow the reranker's scale. jina's CC BY-NC licence is recorded in the README and the system
  card.
- Revisit with golden v2 (M3a.10: more exact-term items on both splits) and after parent-child chunking
  (M3a.5), which changes what the reranker sees; the eval runner reproduces every row above.
- The priority boost (D61) is applied after reranking when one runs, otherwise after fusion.
