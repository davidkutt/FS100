# ADR-0016: Hybrid search — the sparse side

- **Status:** Proposed (draft, M3a.0; decided in M3a.2 with `test` numbers)
- **Date:** 2026-10-23
- **Plan reference:** D54, D56 ([plan-phase-3.md §3](../../plan-phase-3.md#3-decisions))

## Context

Dense retrieval misses exact terms: error codes, CLI flags, identifiers. Collection v2 gets a named
sparse vector next to `dense`, fused with RRF in one Qdrant query. D56 names two candidates: **(a) BM25**
computed by Qdrant, **(b) bge-m3's learned sparse weights**, only if the Phase 1 runtime exposes them.

## Spike notes (M3a.0)

**(a) Server-side BM25 works on the self-hosted image (A16 holds).** Throwaway `qdrant/qdrant:v1.19.2`,
`qdrant-client` 1.19.1: a sparse vector `sparse` with `Modifier.IDF`, points upserted and queried with
`models.Document(text=…, model="qdrant/bm25", options=…)` — no client-side model, no memory in the AI
service. `options={"language": "none"}` (no stemming, no stop words) and the default English stemming
both work; on a 4-document toy set *"rolling back"* scores 3.99 against *"Roll back a Helm release"* with
stemming and 1.98 without (only "back" matches); German *"images löschen"* matches either way.

**(b) bge-m3 sparse is cheap to add.** The ONNX export that fastembed loads (ADR-0003) returns
`token_embeddings` `[batch, seq, 1024]` next to `sentence_embedding`. Sparse weights =
ReLU(token_embeddings · w + b) with the 1024 → 1 head `sparse_linear.pt` from the model repo (3.5 KB, a
torch pickle: convert once to NumPy), max per token id, special tokens dropped. Same forward pass, so no
extra memory and no extra latency. Output looks right — *"Pod killed with exit code 137 (OOMKilled)…"* →
`▁Pod` 0.27, `▁137` 0.26, `▁killed` 0.22, `OOM` 0.21, `▁exit` 0.19. Catches: fastembed's `embed()` returns
only the pooled vector, so (b) needs fastembed internals or our own onnxruntime session over the same
files (a second session would load the 2.3 GB model twice); dimensions are XLM-R subword ids
(250 k vocabulary), so German compounds split into pieces (`fehler`, `hafte`).

## Decision (proposed)

- Default **(a) BM25 server-side**; `language: none` vs. English stemming compared on `dev` (the corpus is
  mixed DE/EN).
- **(b) stays in the M3a.2 benchmark** as the challenger, built into its own collection by the re-index job.
- RRF fusion; DBSF compared once.

## Alternatives considered

- **FastEmbed `Qdrant/bm25` client-side** — the fallback if server inference were missing; not needed.
- **SPLADE models** — English-centred, another model in memory.

## Consequences

To be written in M3a.2.
