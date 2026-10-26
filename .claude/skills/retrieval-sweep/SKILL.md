---
name: retrieval-sweep
description: Sweeps a retrieval knob (a module constant in knowledge_base.py such as BOOST, QUESTION_TOPICS, PREFETCH, FUSION, or a `run()` option such as priorities) over the golden dev split on a corpus index built once into an on-disk Qdrant, so each setting takes seconds instead of a 3.5-minute `pnpm eval:retrieval` ingest, and lists the items each setting moves. Use when tuning retrieval "on dev", "sweep boost / fusion weight / top-n", "which items does X change", before the one `test` run a milestone reports (D51).
---

# Retrieval sweep on a cached index

1. Copy `sweep.py` into the scratchpad (`$S`) and set `SWEEP` (and `extra` for `run()` options such as
   `priorities`). Never edit constants in the repo for a sweep: the script overrides them in-process.
2. Run from `apps/ai-service` (relative paths resolve there), free — no `.env`, plain index:
   ```bash
   uv run python $S/sweep.py $S/state dev
   ```
   The first run ingests into `$S/state/qdrant` (~3.5 min, bge-m3); later runs reuse it. Delete
   `$S/state` after a change to chunking, parsing, the sparse side or the payload.
3. Read the per-item lines: an equal overall can hide one item up and one down.
4. Pick on `dev` only; then report one `test` run (D51). For the milestone row on a contextual index (the
   default since M3a.6), build with `contextualizer_of` + `index_corpus(..., contextual_domains,
   contextualize, topics)` under `uv run --env-file ../../.env` — paid, ~0.035 USD per ingest — and run
   both splits on that one index; write the reports with `to_markdown` / `model_dump_json` into
   `evals/baselines/<milestone>/{dev,test}.{md,json}`.

Pitfalls:
- `run()` sets `kb.threshold` from `checked_threshold`; pass `Settings().retrieval_score_threshold`, or
  threshold-gated logic (the D61 boost) behaves differently from the service.
- The local on-disk client holds a lock: one process per `$S/state` at a time.
- `QdrantClient.__del__` prints an `ImportError` at interpreter exit; harmless.
