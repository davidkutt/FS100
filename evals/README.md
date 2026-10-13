# Evals

Measurement before optimisation (plan.md D23): every change to retrieval is judged by an eval run against a
versioned golden set. Phase 1 covers **retrieval**; generation and agent evals follow in Phases 2–3.

```
evals/
  datasets/retrieval_v1.jsonl   # golden set, versioned, committed (written in M1.2)
  runs/                         # results as JSON, git-ignored; CI uploads them as artifacts
  README.md                     # this file
```

Run it with `pnpm eval:retrieval` (implemented in M1.2 as the `kb-eval retrieval` CLI of the AI service).

## Item format

One JSON object per line ([plan.md §7.6](../plan.md#76-golden-set-item-evalsdatasetsretrieval_v1jsonl)):

```json
{"id":"r-017","question":"Wie rolle ich ein fehlerhaftes Deployment zurück?","lang":"de",
 "domains":["devops"],"answerable":true,
 "relevant":[{"doc":"runbook-rollback.md","heading":"Rollback"}],"notes":"paraphrased, no keyword overlap"}
```

(Shown on two lines for readability; in the file every item is a single line.)

| Field | Rules |
|---|---|
| `id` | `r-NNN`, unique, never reused or renumbered — runs and notes refer to it |
| `question` | Phrased like a real user would ask it, not copied from the document |
| `lang` | `de` or `en` — the language of the question, not of the source |
| `domains` | One or more of `db`, `dev`, `cloud`, `devops`, `mlops`, `ai`, `security`, `architecture`, `sre` (D22) |
| `answerable` | `false` when the corpus does not contain the answer; then `relevant` is `[]` |
| `relevant` | Every passage that answers the question: `doc` = file name in `data/sample-docs/`, plus `heading` (Markdown heading path as stored in the chunk payload, e.g. `"Deploy › Rollback"`) **or** `page` (PDF, 1-based) |
| `notes` | Item type and anything a reviewer needs (e.g. "cross-language: DE question, EN source") |

Relevance is labelled by **document + heading/page, never by chunk id**, so labels survive re-chunking and
model changes. A retrieved chunk counts as relevant when its `doc` matches and its heading path starts
with the labelled `heading` (or its page equals `page`).

## Writing the golden set

Target for `retrieval_v1` (D23): **40–60 items**, German and English, spread across the domains of the
corpus, **at least 8 unanswerable**. Mix the item types:

| Type | What it tests |
|---|---|
| Direct lookup | The question reuses the document's wording |
| Paraphrase | Same meaning, little or no keyword overlap |
| Cross-language | German question, English source (and vice versa) |
| Multi-chunk | The answer spans several sections or documents (several `relevant` entries) |
| Unanswerable | Plausible, on-topic, but not in the corpus — calibrates `RETRIEVAL_SCORE_THRESHOLD` |

Rules:

1. **Write the items before any tuning** and without looking at retrieval results — otherwise the set
   rewards whatever the current configuration already does.
2. Base items only on documents that are in `data/sample-docs/` and licence-checked (`ATTRIBUTION.md`).
3. Prefer questions you would genuinely ask as a "Dev of the future"; avoid trivia.
4. Review each new item once more a day later: is the label complete, is the question unambiguous?

## Versioning

- A dataset file is **frozen** once a run against it is used for a decision (first: the ADR-0004 benchmark).
- Changes — new items, fixed labels, removed items — go into a **new file** (`retrieval_v2.jsonl`), with
  a line in the changelog below explaining what changed and why. Old files stay, so old runs remain
  reproducible.
- Every run records the dataset file name, embedding model, chunking settings and git commit.
- Phase 3 splits off a separate tuning subset, so that techniques are not tuned on the reported set.

## Metrics

Computed overall, **per domain** and **per language** (D23):

| Metric | Meaning |
|---|---|
| hit@1, hit@5 | Share of answerable items with at least one relevant chunk in the top 1 / top 5 |
| MRR@10 | Mean of 1/rank of the first relevant chunk (0 if none in the top 10) |
| nDCG@10 | Rank-discounted gain with binary relevance, normalised by the ideal ranking |
| Latency p50 / p95 | Embed + search time per query |

Unanswerable items are excluded from hit/MRR/nDCG and reported separately: the share whose best score
stays below `RETRIEVAL_SCORE_THRESHOLD` (correct abstention).

## Changelog

| Dataset | Date | Change |
|---|---|---|
| `retrieval_v1` | — | To be written in M1.2 |
