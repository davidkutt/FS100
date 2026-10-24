# ADR-0017: Reranker

- **Status:** Proposed (draft, M3a.0; decided in M3a.3)
- **Date:** 2026-10-23
- **Plan reference:** D57, D50 ([plan-phase-3.md §3](../../plan-phase-3.md#3-decisions))

## Context

A cross-encoder over the fused hybrid candidates is the largest expected quality gain of Phase 3a. Budget
(D57, D50): p95 rerank ≤ 1.5 s on the M1, ≤ ~2.5 GB, 20–50 candidates; the corpus is German and English;
the repo is MIT, so the model licence matters.

## Spike notes (M3a.0)

MacBook Air M1 16 GB, one model per process, 1,000-character chunks of `data/sample-docs` (≈ 250 tokens),
batch 16, median of 3 after a warm-up. Sanity check: rank of the Kubernetes rollback chunk among 30 for a
German and an English question.

| Model | Licence | Runtime | Memory | 20 pairs | 50 pairs | Rank DE / EN |
|---|---|---|---|---|---|---|
| `Xenova/ms-marco-MiniLM-L-6-v2` | Apache-2.0 | fastembed, ONNX CPU | RSS +1.2 GB | 0.76 s | 2.1 s | 2 / 1 |
| `jinaai/jina-reranker-v2-base-multilingual` | **CC BY-NC 4.0** | fastembed, ONNX CPU | RSS +2.0 GB | 5.2 s | 16.4 s | 1 / 1 |
| `BAAI/bge-reranker-v2-m3` | Apache-2.0 | sentence-transformers 6.1, torch 2.14 MPS fp16 | RSS +0.5 GB, MPS 1.1 GB weights, 2.3 GB pool after 50 pairs | 2.5 s | 7.1 s | 1 / 1 |

- **No multilingual candidate meets 1.5 s at 20 pairs.** Both are right on the sanity check; MiniLM ranks
  the German question's chunk second (it is English-only).
- MPS memory is unified memory but does not show in RSS, so `pnpm mem` misses it; count it against D50 by
  hand.
- With transformers 5, fp16 needs `model_kwargs={"dtype": torch.float16}`; `torch_dtype` is ignored
  silently and loads fp32 (2.3 GB).
- fastembed's RSS growth is mostly the onnxruntime arena for batch 16; smaller batches shrink it.

## Options for M3a.3

1. Fewer candidates (10–15) and pairs truncated to 256–384 tokens.
2. jina or bge as int8 ONNX, or onnxruntime's CoreML execution provider.
3. Relax the budget to ~3 s p95 for `mode=rag` only, if the `dev` gain is large.
4. MiniLM for English questions only (the router knows the language) — weak for DE.

## Decision

Open: chosen in M3a.3 on `dev` nDCG, latency and memory; jina only with its non-commercial licence recorded
in the README and the system card.
