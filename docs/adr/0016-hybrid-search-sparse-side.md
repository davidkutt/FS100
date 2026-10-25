# ADR-0016: Hybrid search — BM25 computed in the AI service, weighted RRF

- **Status:** Accepted (M3a.2)
- **Date:** 2026-10-24
- **Plan reference:** D54, D56 ([plan-phase-3.md §3](../../plan-phase-3.md#3-decisions))

## Context

Dense retrieval misses exact terms: error codes, CLI flags, identifiers (`test` item `r-033`, *"HTTP 402"*,
is the one `p2-dense` miss in the top 5). Collection v2 gets a named sparse vector next to `dense`, fused in
one Qdrant query. D56 names two candidates: **(a) BM25** computed by Qdrant, with English stemming or
language-neutral, **(b) bge-m3's learned sparse weights**; RRF fusion, DBSF compared once.

## Decision

- **Sparse side: BM25 with English stemming** (`SPARSE_MODEL=bm25-english`), computed in the AI service
  with fastembed's `Qdrant/bm25` (stop-word lists and a Snowball stemmer, a few KB, no model in memory);
  passages get BM25 term weights, queries term presence, and the collection's sparse vector has the IDF
  modifier, so Qdrant supplies the IDF. Not Qdrant's server-side inference (D56's fallback instead, see
  below).
- **Fusion: RRF with Qdrant's k = 2, the sparse side at half weight** (`rrf:2:0.5`), over the dense
  top 50 and the sparse top 50 under the same filter.
- **`score` stays the dense cosine similarity** of each fused hit (one more Qdrant call re-scores the
  fused hits on `dense`), so `RETRIEVAL_SCORE_THRESHOLD`, the abstention metric of the gate, the agent's
  `top_score` and the gap signal keep their meaning. The threshold now gates the query: the best hit
  below it → no hits (abstain); otherwise every fused hit stays, so a hit that only BM25 finds is not cut
  for its lower similarity. Recalibrated on reranker scores in M3a.3 (ADR-0017).
- **Each collection records its sparse side** in its Qdrant metadata (`{"sparse": …}`, none before
  M3a.2). Ingest and search follow the collection, not the setting: a rollback to a dense-only
  collection keeps working, and the gate compares a hybrid build with a dense live one. A new
  `SPARSE_MODEL` takes effect with `pnpm kb:reindex`.
- **`explain`** on `/v1/search` adds each hit's rank among the dense and the sparse top 50; the
  inspector shows fused, dense and sparse rank.

## Evidence

`kb-eval retrieval`, bge-m3, chunks 1000/150, top 10, in-memory Qdrant; candidates chosen on `dev` (36
items, 30 answerable), `test` run once at the end (D51). Exact-term items (`exact_term` in
`retrieval_v1`): 3 in `dev`, 3 in `test`.

`dev`:

| Retrieval | hit@1 | hit@5 | MRR@10 | nDCG@10 | Exact-term nDCG@10 | p50 ms |
|---|---|---|---|---|---|---|
| dense (`p2-dense`) | 0.83 | 1.00 | 0.89 | 0.91 | 0.94 | 60 |
| + bge-m3 sparse, RRF k = 2 | 0.53 | 1.00 | 0.73 | 0.79 | 0.97 | 123 |
| + BM25 neutral, RRF k = 2 | 0.70 | 1.00 | 0.84 | 0.87 | 0.94 | 65 |
| + BM25 English, RRF k = 2 | 0.77 | 1.00 | 0.88 | 0.90 | 0.95 | 65 |
| + BM25 English, RRF k = 60 | 0.63 | 0.93 | 0.76 | 0.80 | 0.97 | 64 |
| + BM25 English, DBSF | 0.73 | 0.97 | 0.84 | 0.86 | 0.96 | 65 |
| + BM25 English, RRF k = 2, sparse weight 0.3 | 0.80 | 1.00 | 0.89 | 0.91 | 0.94 | — |
| + BM25 English, RRF k = 10, sparse weight 0.5 | 0.63 | 0.97 | 0.79 | 0.84 | 0.97 | — |
| **+ BM25 English, RRF k = 2, sparse weight 0.5** | **0.80** | **1.00** | **0.90** | **0.91** | 0.95 | 65 |

`test` (dense vs. the winner; baselines `evals/baselines/p2-dense/` and `m3a2-hybrid/`):

| Slice | n | Dense hit@1 / hit@5 / MRR@10 / nDCG@10 | Hybrid hit@1 / hit@5 / MRR@10 / nDCG@10 |
|---|---|---|---|
| **overall** | 20 | 0.65 / 0.95 / 0.77 / 0.78 | **0.70 / 0.95 / 0.79 / 0.81** |
| **exact terms** | 3 | 0.33 / 0.67 / 0.49 / 0.48 | **0.33 / 1.00 / 0.53 / 0.59** |
| direct lookup | 8 | 0.75 / 0.88 / 0.81 / 0.85 | 0.75 / 1.00 / 0.82 / 0.87 |
| cross-language | 4 | 0.75 / 1.00 / 0.88 / 0.75 | 0.75 / 1.00 / 0.83 / 0.79 |
| multi-chunk | 4 | 0.25 / 1.00 / 0.51 / 0.57 | 0.50 / 0.75 / 0.59 / 0.64 |
| paraphrase | 2 | 0.50 / 1.00 / 0.67 / 0.75 | 0.50 / 1.00 / 0.75 / 0.82 |
| PDF page label | 1 | 1.00 / 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 / 1.00 |
| whole document | 1 | 1.00 / 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 / 1.00 |
| lang `de` / `en` | 6 / 14 | nDCG@10 0.75 / 0.79 | nDCG@10 0.78 / 0.83 |

Abstention unchanged: suggested threshold 0.557, balanced accuracy 0.95 on both. Per item:
`r-033` (*HTTP 402*, exact term) rank 8 → 4, `r-037` 2 → 1, `r-008` 3 → 2; `r-002` 2 → 3, `r-028`
3 → 5 and `r-035` 5 → 7 — the one new top-5 miss, a multi-chunk item. The full set (the CI gate) goes
from nDCG@10 0.86 to 0.87 (hit@5 0.98 both, exact terms hit@5 0.83 → 1.00). p50 latency 60 → 67 ms.

Reading the numbers: on `dev`, hybrid at best matches dense — dense already finds every `dev` exact-term
item first, and a third of the items are cross-language (German question, English text), where BM25 can
only add noise. Equal-weight fusion lets BM25's top hit tie dense's (k = 2: both 0.5) and pushes the
right chunk from rank 1 to 2 on cross-language and lookup items; a flatter fusion (k = 60, k = 10, DBSF)
lets chunks that both sides rank mediocre overtake dense's rank 1, which is worse. Half weight keeps
dense's top hit unless BM25 agrees. Differences of one item (0.03 on `dev`) are noise.

## Why BM25 in the AI service, not in Qdrant

The M3a.0 spike showed server-side inference (`models.Document(model="qdrant/bm25")`) works on the
self-hosted 1.19.2 image. But tests, `kb-eval` and the CI gate run Qdrant in-process (`:memory:`), where
qdrant-client computes `Qdrant/bm25` with fastembed instead, and the two differ: on four sample texts the
vectors matched except for *"ERR_PNPM_IGNORED_BUILDS"* (the server splits on `_`, fastembed keeps one
token — exactly the exact-term case), and local mode rejects the language-neutral options. Every eval
would have measured something other than what runs. Computing the vectors in the AI service makes them
identical in both places, keeps tests offline (a fake replaces fastembed's BM25), and costs no memory.

## bge-m3 learned sparse (b)

Measured and dropped. The weights came from fastembed's own ONNX session (token embeddings + input ids,
ReLU(h · w + b) with the 3.5 KB `sparse_linear.pt` head read without torch, max per token id, special
tokens dropped), in a second pass over each batch for the benchmark. It is the worst candidate on every
metric (subword pieces of German and English words rarely meet; fused with equal weight they displace
dense's top hit), doubles ingest time in that form, and needed fastembed internals. Not kept in the code.

## Alternatives considered

- **Qdrant server-side BM25** — see above; revisit if evals ever run against a server.
- **BM25 language-neutral** (no stemming, no stop words) — worse on `dev` (0.87 nDCG@10); stays a
  `SPARSE_MODEL` value for when the German share grows (golden v2, M3a.10).
- **DBSF, RRF k = 60** — worse on `dev` (above).
- **Per-hit threshold on the fused list** — would cut the BM25-only hits hybrid search is for.
- **Fused score as `score`** — RRF scores (≤ 1.5 here) mean nothing to the calibrated threshold, the
  gap signal or the agent; the extra call costs ~1–4 ms.
- **SPLADE models** — English-centred, another model in memory.

## Consequences

- `kb_current` from M3a.1 has no sparse side: search stays dense-only (the service logs a warning) until
  `pnpm kb:reindex` builds a hybrid collection behind the gate.
- One more Qdrant call per search (the dense re-score) and one metadata read; the query's BM25 vector is
  free. p50 retrieval latency 60 → 65–67 ms in-process.
- The chat may now get up to `RETRIEVAL_TOP_K` sources below the threshold when the best one passes.
- fastembed downloads `Qdrant/bm25` (stop-word lists) into `EMBEDDING_CACHE_DIR` on first use.
- M3a.3 reranks the fused candidates; the threshold moves to reranker scores there.
