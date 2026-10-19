# ADR-0003: Embeddings computed in-process with fastembed

- **Status:** Accepted
- **Date:** 2026-10-12
- **Plan reference:** D9, D10, D18, D24

## Context

Ingestion embeds every chunk (`passage: …`), chat and evals embed every query (`query: …`). The corpus is
German and English. The developer machine is a MacBook M1 without a local LLM in Phase 1; the target
platform is AKS / Container Apps in Phase 5. Tokens are paid by the developer.

## Decision

- Compute embeddings **inside the AI service process** with **fastembed** (ONNX Runtime, CPU).
- Default model **`intfloat/multilingual-e5-base`** until the M1.2 benchmark (`e5-small/base/large`,
  `bge-m3`) decides; the result is recorded in ADR-0004.
- The model id is configuration (`EMBEDDING_MODEL`); the Qdrant collection name encodes model and
  dimension (`kb__{model_slug}__{dim}`) and is addressed through the alias `kb_current`, so a model swap
  is a re-index plus an alias flip.
- E5 prefixes (`query: ` / `passage: `) are applied in one place and covered by tests.
- Model files are cached in `EMBEDDING_CACHE_DIR` (git-ignored) and baked into or mounted into images
  in M1.6.

## Alternatives considered

- **Hosted embedding API (OpenAI, Voyage, Cohere, via OpenRouter …)** — per-token cost on every ingest
  and eval run, data leaves the machine, results depend on network; no local reproducibility.
- **Separate embedding server (Hugging Face TEI, Ollama)** — one more container and RAM on the M1;
  worth revisiting for GPU nodes or when models get large (Phase 6).
- **sentence-transformers (PyTorch)** — heavier install and memory footprint than ONNX for CPU inference.

## Consequences

- Zero token cost for embeddings; identical behaviour locally, in CI and in the cloud.
- Cold start (model download/load) affects container start and CI → readiness gate (`/readyz`), cached
  models, `e5-small` in CI.
- CPU-bound ingestion on large corpora; acceptable at Phase 1 scale, a queue arrives in Phase 3.
- `bge-m3` keeps the door open to dense + sparse hybrid search (Phase 3) from one model.
