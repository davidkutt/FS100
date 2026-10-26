# ADR-0019: Contextual retrieval and chunk sub-topics

- **Status:** Accepted (M3a.6)
- **Date:** 2026-10-26
- **Plan reference:** D60, D48, D55, D51 ([plan-phase-3.md §3](../../plan-phase-3.md#3-decisions))

## Context

A chunk of 1000 characters often does not say what it belongs to: *"Restore last night's backup into a
scratch database"* names neither Postgres nor the runbook. Anthropic's contextual retrieval prepends a
short, model-written context to each chunk before indexing. Phase 2 labels documents with sub-topics
(D48); the curator (M3b.9) and priorities (M3a.7) need them per chunk. D60 takes both from one cheap
call per chunk, with the whole document as a cached prefix.

## Decision

- **One call per chunk** to `CONTEXTUAL_MODEL` (empty = `LLM_MODEL`, `openai/gpt-6-luna`), structured
  output `{context, topics}`, prompt `contextual@1`. The **system message holds the instructions, the
  document's sub-topics and the whole document** (each section under its heading path, since the parser
  drops heading-only blocks such as a title); the user message is the chunk. The first call runs alone,
  the rest with 8 in parallel, all with `session_id = doc_id:version` (OpenRouter sticky routing).
- **The context is indexed, never cited:** `context + "\n\n" + chunk` is embedded on the dense and the
  BM25 side; the payload keeps `context` and `text` apart, and hits, citations and parents carry the
  chunk's text only.
- **Chunk sub-topics in `chunk_topics`**, next to the document's own `topics` (set by users; a relabel
  or a re-index's reconcile overwrites those, not these). Only sub-topics of the document's domains are
  offered and kept. A chunk without one gets the sub-topic of the document's domains whose taxonomy
  description (`topic: description`) is most similar to its vector — the **fallback** for documents
  outside `CONTEXTUAL_DOMAINS`, failed calls and capped documents. Payload index with prefix matching,
  like `topics`.
- **Per-domain switch and cost cap:** `CONTEXTUAL_DOMAINS` (comma-separated; a document is
  contextualized if one of its domains is listed; empty = off) and `CONTEXTUAL_MAX_COST_USD_PER_DOC`
  (0.05; summed from OpenRouter's `usage.cost`; the chunks after it go without context, calls in flight
  finish). A failed first call skips the document (warning), a later failure only its chunk. The job
  state `contextualizing` shows while it runs; the job result (`context_cost_usd`) and the re-index
  report (per filename) record the cost.
- **On for all nine domains** (`.env.example`; the code default is off, so tests and CI make no calls),
  **`RETRIEVAL_SCORE_THRESHOLD` stays 0.55**. The gate (D55) refuses the first contextual build on
  abstention (evidence below), so it is swapped in with `pnpm kb:reindex --force --reason …`.
- **Contexts are stored** in `ai.chunk_contexts` (migration `0004_chunk_contexts`: `doc_id`, `key` =
  SHA-256 of model and messages, `label` jsonb), deleted with the document's originals. A re-index
  reuses every label whose call would be the same — same model, prompt, sub-topic list, document and
  chunk — so it is free and **deterministic**: two contextual builds without the store differed by
  0.04 nDCG@10 on `test` and the gate refused the second (evidence below). A new document version, a
  prompt, model or taxonomy change pays again. `kb-eval` keeps no store and pays per run.
- **Taxonomy v2:** sub-topics for all nine domains (v1 ids unchanged), plus `architecture/roadmap` and
  `dev/documentation` for plans and guides, which the first spot-check had no topic for.
- **Fix outside the milestone:** the chunker drops chunks without a word character (6 of 224 in the
  corpus were a bare `---` between sections).

## Evidence

`kb-eval retrieval`, bge-m3, BM25 English, `rrf:2:0.5`, chunks 1000/150 in parents ≤ 2000, no reranker,
top 10, in-memory Qdrant, MacBook Air M1 16 GB; contexts from `openai/gpt-6-luna`. Plain and contextual
from one index each, read on `dev`, `test` and the full set (`evals/baselines/m3a6-contextual`).

| Retrieval | hit@1 | hit@5 | MRR@10 | nDCG@10 | Exact terms (3) nDCG@10 | Abstention at 0.55 |
|---|---|---|---|---|---|---|
| `dev` plain | 0.83 | 1.00 | 0.92 | 0.924 | 0.96 | 0.82 |
| `dev` + contextual | 0.83 | 1.00 | 0.91 | 0.934 | 1.00 | 0.73 |
| `test` plain (`m3a5-parents`) | 0.70 | 0.95 | 0.78 | 0.809 | 0.57 | 0.95 |
| **`test` + contextual** | 0.70 | **1.00** | **0.83** | **0.851** | **0.69** | 0.93 |
| full set plain (the CI gate's set) | 0.78 | 0.98 | 0.86 | 0.878 | 0.77 | 0.87 |
| full set + contextual | 0.78 | 1.00 | 0.88 | 0.901 | 0.85 | 0.81 |

- **`test`:** `r-035` (multi-chunk), the top-5 miss since M3a.2, 8 → 3; the exact-term items `r-015`
  (*no space left on device*) and `r-033` (*HTTP 402*) 4 → 2 each; `r-002` (DE → EN) 3 → 1; `r-008` 2 → 1;
  `r-022` and `r-037` 1 → 2. German questions 0.76 → 0.89 nDCG@10, cross-language 0.79 → 0.92. `dev` sits
  near its ceiling: +0.010.
- **Run to run:** contexts differ per run. The first contextual run (before the chunk fix and the two
  sub-topics) gave `test` nDCG@10 0.857, MRR@10 0.829 — the same gain — but abstention 0.80: `u-008`
  (*LoRA on our runbooks*) 0.533 → 0.566 crossed the threshold; in the final run `r-035` fell to 0.546
  instead. `dev` gave 0.930 and 0.934.
- **Abstention at 0.55 drops on every split** (dev −0.08 in both runs, full set −0.06, test −0.03 / −0.15):
  a context names the document's subject, so off-topic questions about the same subject score higher. A
  dev-calibrated threshold of ~0.60 brings balanced accuracy to 0.90 on all three splits but keeps only
  80 % of the answerable questions (dev 0.97 → 0.80). The threshold stays 0.55, and the swap is forced
  with that reason: 4 (`test`) and 6 (`dev`) unanswerable items cannot resolve a 0.02 tolerance (one item
  is 0.125 / 0.083), and golden v2 (M3a.10) recalibrates with more of them.
- **Cost (one-off per ingest):** 0.034 USD for the 17 documents (218 chunks), 0.020 of it fs100-plan.md
  (92 chunks, 47 KB); the next ones are 0.002 (setup guides), runbooks ~0.001. 91–98 % of the input tokens
  are read from the prompt cache. Ingest 182 → 353 s (alone on the M1; the LLM calls), search latency
  unchanged (p50 59 ms).

**Through the real gate** (the `reindex-check` skill on throwaway state: server Qdrant, uploads without
contexts, then `kb-admin reindex` with all nine domains), three times: `test` nDCG@10 +0.058 … +0.062,
MRR@10 +0.070 … +0.099, hit@5 +0.05 twice and ±0 once, abstention 0.80 / 0.80 / 0.925 against 0.95 —
`kept` without force, `forced` with a reason. 0.043 USD and ~380 s per contextual build (~190 s
without), the AI process at 1.82 GB idle, 2.39 GB ingesting and 2.60 GB in the gate (D50). Before the
labels were stored, the admin page's second build of the same documents was kept against the first:
`test` nDCG@10 0.865 → 0.824, MRR@10 0.850 → 0.787. With the store it made no LLM call and swapped with
no blocker; rollbacks took 0.04 s (API) and 2.3 s (CLI).

**Sub-topics**, 50 random chunks each, graded by hand against the taxonomy (correct = the chunk is about
it). First sample (seed 6, taxonomy v2 without `roadmap`/`documentation`, before the chunk fix): 45/50
carry a correct sub-topic (43/50 as the first one); the misses were a bare `---` and plan or guide
sections without a fitting topic (schedule, *What's next*, documentation links). After the two topics
and the chunk fix, a **fresh sample** (seed 26): **47/50 carry a correct sub-topic** (94 %), 43/50 as the
first one; the three misses are plan milestones about the UI and the repo setup, whose `dev/*` topics
fs100-plan.md (architecture, ai, devops) is not offered. The embedding fallback on the same chunks:
32/50 and 31/50 — it pulls plan chunks to `ai/agents`.

## Alternatives considered

- **The document in a user message before the chunk** (D60's "document first") — `gpt-6-luna` at
  OpenRouter cached nothing that way, sequentially or in parallel, with or without `prompt_cache_key`
  (0 of 85,766 input tokens for setup-installation.md); in the system message 91–98 % are cached
  (fs100-plan.md: 0.157 → 0.026 USD).
- **One call per document for all its chunks** — far fewer input tokens, but one long structured reply
  per document and a weaker per-chunk focus; not measured.
- **Topics from every domain** — would let a chunk carry a topic its document's domains don't have;
  search filters are domain-level, so chunk topics stay inside them.
- **Embedding similarity only** — no cost, but 31 of 50 chunks right (below).

## Consequences

- **Data leaves the machine at ingest:** every document of `CONTEXTUAL_DOMAINS` goes to the LLM
  provider whole, once per chunk (system card). Before, only retrieved chunks did, at question time.
- The document sits in the system message: its text could instruct the model. The output is two short
  fields, the topics are checked against the taxonomy, and a context only changes how that document's
  own chunks are found.
- Ingest of the sample corpus takes ~+170 s (LLM calls) and ~0.035 USD, once per document version;
  re-indexes reuse the stored contexts.
- A relabel to other domains keeps the old domains' `chunk_topics` until the next re-index.
- The CI gate (`eval.yml`) runs without an LLM, so it measures retrieval without contexts.
- The agent eval (`kb-eval agent`) indexes its corpus without contexts.
