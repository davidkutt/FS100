# Evals

Measurement before optimisation (plan.md D23): every change to chunking, embeddings or retrieval is
judged by an eval run, not by impression.

```bash
pnpm eval:retrieval                                    # model + chunking from .env defaults
pnpm eval:retrieval --model intfloat/multilingual-e5-small --model BAAI/bge-m3 \
                    --chunk 1000:150 --chunk 500:75     # benchmark: every model × every chunking
```

The runner (`kb-eval retrieval` in `apps/ai-service`) ingests the corpus listed in
[`data/sample-docs/domains.json`](../data/sample-docs/domains.json) into an **in-memory Qdrant** — no
running infra and no LLM needed — asks every golden question (top 10, no filter, no threshold) and
writes `runs/<timestamp>__<dataset>__<model>__<chunking>.{json,md}` (git-ignored). The Markdown is
printed too; with several runs, a comparison table follows.

## Metrics

Per answerable question; overall, per domain and per language:

- **hit@1 / hit@5** — a relevant chunk is in the top 1 / 5.
- **MRR@10** — 1 / rank of the first relevant chunk.
- **nDCG@10** — binary gain per *label* (a chunk only counts if it finds a label not found yet), so
  three chunks of the same section do not inflate the score.
- **latency p50 / p95** — query embedding + search, in-process.
- **suggested `score_threshold`** — the top-1 score that best separates answerable from unanswerable
  questions (balanced accuracy). Scores are model-specific: recalibrate for every model.

## Dataset `datasets/retrieval_v1.jsonl`

One JSON object per line (plan.md §7.6):

```json
{"id":"r-017","question":"…","lang":"de","domains":["devops"],"answerable":true,
 "relevant":[{"doc":"runbook-rollback.md","heading":"Rollback"}],"notes":"paraphrase"}
```

- `relevant` labels a **document + heading** (matches any level of the chunk's heading path) or
  **document + page** (PDF) or the whole document — never chunk ids, so labels survive re-chunking.
- Mix item types and say which in `notes`: direct lookup, paraphrase without keyword overlap,
  cross-language (DE ↔ EN), multi-chunk (several labels), unanswerable (`answerable: false`,
  `relevant: []`, ideally a near miss).
- `tests/test_evals.py` checks that every label resolves to a section of the corpus.

## Versioning

v1 was written **before any tuning** and is frozen. Never edit items to make a run look better: fix a
wrong label or add items only in a new version (`retrieval_v2.jsonl`), noting what changed and why, and
re-run the baseline on it. Phase 3 adds a separate tuning subset so the test items stay unseen.
