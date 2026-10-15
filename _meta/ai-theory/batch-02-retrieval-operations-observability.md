# Batch 2 — Retrieval operations & observability

> **Topics:** #5 Embedding model selection & benchmarking · #11 Relevance thresholds & abstention ·
> #8 Idempotent ingestion pipeline · #9 Zero-downtime re-indexing with aliases · #18 LLM tracing & observability
> **Needed for:** P1 · M1.1 (tracing, weeks 1–2) · M1.2 (ingest, collection manager, benchmark, ADR-0004, weeks 3–4) · M1.4 (Nest ingest/delete)
> **Builds on:** Batch 1 (#1 #4 #6 #7 #2 #3 #17) — its takeaways are assumed, not repeated
> **Written:** 2026-10-13 · **Plan:** `plan.md` Draft v2

---

## 0. How to use this batch

Batch 1 explained how retrieval *works*. Batch 2 is about *running* it: choose by measurement (#5), know when not
to answer (#11), write safely (#8), change safely (#9) and see what happened (#18).

**Reading order.** The sections follow the roadmap order. You are in week 1, though, and M1.1 already needs a span
in Phoenix — if you start M1.1 before reading everything, read **#18 first**, then come back.

**The thread that ties the five topics together** — an index is a versioned artifact with a lifecycle:

```
 ┌──────────── #8 idempotent ingest ────────────┐
 │  doc → parse → chunk → embed → upsert (UUIDv5) │
 └───────────────────────┬────────────────────────┘
                         ▼
     collection kb__e5-base__768__c1000__20261020   ◄── metadata = "index manifest"
                         │                              (model, prefixes, chunker, threshold)
          #5 benchmark ──┤  eval by collection name, never by alias
          #11 calibrate ─┤  threshold belongs to this model + collection
                         ▼
          #9 promote: atomic alias flip  kb_current → new collection   (rollback = flip back)
                         │
          #18 trace every request: which collection, which chunks, which prompt, which model, how long
```

### What was verified today (2026-10-13)

Re-checked because this batch depends on library behaviour. Experiments ran against real servers, not mocks.

| Fact | How verified |
|---|---|
| Latest versions: Qdrant server **1.19.2**, `qdrant-client` **1.19.1**, `fastembed` **0.9.0**, `arize-phoenix` **20.21.2**, `arize-phoenix-otel` **0.17.2**, `openinference-instrumentation-openai` **0.1.65**, `openai` **3.29.0**, FastAPI **0.143.0** | PyPI / GitHub releases |
| Collections accept a **`metadata`** dict (create, merge-update, read back *through the alias*) on **1.18.0 and 1.19.2** | Both server binaries |
| `update_collection_aliases([Delete, Create])` in **one request**: 548 concurrent searches during 150 flips → **0 errors**. Same flips as **two requests**: **654 of 1,261** searches failed (404) | Stress test, 4 reader threads |
| `CreateAlias` on an existing alias name **silently re-points** it (1.18.0 and 1.19.2) | Both servers |
| Deleting a collection **removes its aliases** → searches on the alias return 404 | 1.19.2 |
| Writes through an alias land **only in the current target** collection | 1.19.2 |
| Re-ingesting a document with **fewer chunks leaves orphans** (5 → 3 chunks left 5 points); a range delete on `chunk_index` fixes it | 1.19.2 |
| `upsert(..., wait=True)` is the Python client default | Signature |
| `facet(key="doc_id", exact=True)` returns chunk counts per document (keyword index required) | 1.19.2 |
| Phoenix image `arizephoenix/phoenix` ships **amd64 + arm64**; UI + OTLP/HTTP on **6006**, OTLP/gRPC on **4317**; without `PHOENIX_SQL_DATABASE_URL` it uses **SQLite in a temporary folder** | Docker Hub tags, Phoenix docs |
| OpenInference span kinds: `CHAIN LLM RETRIEVER EMBEDDING RERANKER TOOL AGENT GUARDRAIL EVALUATOR PROMPT DECISION UNKNOWN` | `openinference-semantic-conventions` 0.1.41 |
| Streaming LLM spans get token counts **only if the provider sends a usage chunk**; a stream closed early ends the span with status `UNSET` and empty output | Fake OpenAI-compatible server + instrumentor |
| OpenRouter now returns usage (incl. `cost`) **in every response**, also in the last SSE chunk; its `usage.include` / `stream_options.include_usage` parameters are deprecated no-ops | OpenRouter docs |
| FastAPI 0.143 creates **its own OTel server spans** when a tracer provider is set | Experiment + FastAPI docs |
| The SQL in #8 behaves as described: 8 concurrent identical uploads → one 202, seven 409; second claim → 0 rows; delete of a `processing` row → 0 rows; recovery → `pending`, `pending`, `failed` | PostgreSQL 16 (plan: 17 — same semantics) |

---

## #5 Embedding model selection & benchmarking

### Why it matters

Public leaderboards (MTEB / MMTEB) average dozens of datasets that look nothing like yours. Your corpus is DE + EN
technical text full of CLI flags, YAML keys and product names; your questions are short, paraphrased and sometimes
cross-language. Rankings shift on domain data, and leaderboard gaps of one or two points are smaller than your
measurement noise (±12 points at n ≈ 45, Batch 1). Leaderboards also ignore what you pay for on an M1: CPU latency,
RAM, image size, cold start.

So the benchmark's job is **not** "find the best model". It is: **make one defensible decision, record it with
numbers, and make it cheap to revisit.** Use leaderboards only to build the shortlist — the plan's shortlist already
exists (D9).

### What the benchmark decides (the content of ADR-0004)

1. Embedding model (+ exact revision)
2. Chunk configuration (size, overlap)
3. Score threshold for abstention (→ #11)
4. The **baseline numbers** that every Phase 3 technique is compared against

### The candidates

| Model | Params | Dim | Max tokens | Prefixes | Pooling | fp32 weights ≈ | Licence | In fastembed 0.9.0 |
|---|---|---|---|---|---|---|---|---|
| `intfloat/multilingual-e5-small` | 118 M | 384 | 512 | `query: ` / `passage: ` | mean | 0.47 GB | MIT | custom |
| `intfloat/multilingual-e5-base` (default) | 278 M | 768 | 512 | `query: ` / `passage: ` | mean | 1.1 GB | MIT | custom |
| `intfloat/multilingual-e5-large` | 560 M | 1024 | 512 | `query: ` / `passage: ` | mean | 2.24 GB | MIT | **built in** |
| `BAAI/bge-m3` (dense only) | 568 M | 1024 | 8192 | none | **CLS** | 2.3 GB | MIT | custom |

Weight sizes are params × 4 bytes (fp32); the e5-large figure matches fastembed's own listing. Vector storage is
irrelevant at Phase 1 scale: 10,000 chunks × 1024 dims × 4 bytes ≈ 41 MB.

Two things in this table bite later:

- **Pooling differs.** E5 uses mean pooling, bge-m3's dense vector is the normalised CLS token. When you register
  the custom models with `TextEmbedding.add_custom_model(..., pooling=...)`, a wrong pooling choice still produces
  plausible vectors — just worse ones. The golden-vector test from the Batch 1 findings (cosine ≥ 0.999 against
  sentence-transformers) is what catches this.
- **e5-large and bge-m3 both have 1024 dimensions.** Swapping one for the other never raises a dimension error.
  Remember this for #9.

**Optional floor baseline:** BM25 (fastembed's `Qdrant/bm25`). It costs about an hour, tells you how much dense
retrieval actually adds on *your* data, and previews the Phase 3 hybrid path. Skip it if you are behind schedule.

### Experimental design

**Factors:** model (4) × chunk size (2: ~1000 and ~2000 characters) = **8 configurations**.

**Everything else is held fixed** and recorded: parser version, chunker algorithm, overlap *ratio* (keep it at 15 %
so 150 → 300 — decide once and write it down), `top_k = 10`, no domain filter, no threshold, the frozen golden set
version, the same machine.

**One collection per configuration**, addressed **by name**, never through `kb_current`. The eval CLI therefore
needs a `--collection` option (it will also be needed for #9).

**Per-model profile** — the single place where model-specific facts live (Batch 1 already put prefixes there):

```python
@dataclass(frozen=True)
class EmbeddingProfile:
    model_id: str            # "intfloat/multilingual-e5-base"
    revision: str            # HF commit or ONNX file hash — pin it
    dim: int
    max_tokens: int          # 512 for E5, 8192 for bge-m3
    pooling: str             # "mean" | "cls"
    query_prefix: str        # "query: " or ""
    passage_prefix: str      # "passage: " or ""
    score_threshold: float | None = None   # filled by #11 calibration
```

**What to measure**

| Group | Metric | Notes |
|---|---|---|
| Quality | hit@1, hit@5, MRR@10, nDCG@10 | Answerable items only — unanswerables belong to #11 |
| Quality slices | per language, per item type (direct, paraphrase, cross-language, multi-chunk), per domain | Print `n` next to every slice |
| Speed | query embedding latency p50 / p95 | Warm, batch size 1, embedding only (Qdrant timed separately) |
| Speed | ingest throughput (chunks/s), model load time | Load time = container cold start and CI cost |
| Resources | peak RSS, model size on disk | Matters on an M1 with Keycloak + Qdrant + Phoenix running |
| Correctness | **truncation rate**: share of chunks above `max_tokens` | See below |

**Measuring latency honestly**

- Warm up (e.g. 20 queries) before timing; report p95, not the mean.
- Fix the ONNX thread count (`TextEmbedding(..., threads=N)`) and record it — defaults differ between your Mac and a CI runner.
- Compare latencies only within one machine. CI numbers (plan: `e5-small` in CI) are not production numbers — label them.

**Truncation — the hidden confound**

E5 silently cuts everything after 512 tokens (Batch 1); the `passage: ` prefix and the heading path in `embed_text`
count too. If the ~2000-character chunks exceed 512 tokens, the E5 models embed only the first part of each chunk,
while bge-m3 sees all of it. bge-m3 might then "win" at 2000 characters *because of the chunk size, not because it is
a better model*. Count before you compare:

```python
from tokenizers import Tokenizer   # tokenizer.json from the model files fastembed downloaded
tok = Tokenizer.from_file(path_to_tokenizer_json)
lengths = [len(tok.encode(profile.passage_prefix + c.embed_text).ids) for c in chunks]
# report max, p95 and the share above profile.max_tokens — per chunk config
```

All four candidates are built on the XLM-RoBERTa SentencePiece vocabulary, so one count should serve all of them —
confirm by comparing the `tokenizer.json` hashes once. Rough expectation (a rule of thumb, *not measured*): 3–4
characters per token for English prose, fewer for code, CLI flags and German compounds — so 2000 characters lands
around 500–700 tokens, right at the limit. This answers the open question in DONE.md only once you measure it.

### Comparing configurations: paired, not side by side

Every configuration answers the *same* questions, so compare **per-item flips** rather than two averages with
overlapping confidence intervals. For hit@5, count the items where B succeeds and A fails (wins) and the reverse
(losses); items where both agree carry no information. The exact sign test on wins vs losses:

| Wins : losses | Two-sided p |
|---|---|
| 5 : 0 | 0.063 |
| 6 : 1 | 0.125 |
| 9 : 2 | 0.065 |
| 10 : 1 | 0.012 |
| 12 : 4 | 0.077 |

Read it as: "9 wins vs 2 losses" feels convincing but is still within what chance produces at this sample size.
When the evidence is this thin, **the tie-breaker is cost**: pick the cheaper model.

**Write the decision rule before you run the benchmark** (and paste it into ADR-0004 unchanged). For example:

> Choose the smallest model whose nDCG@10 is within 3 points of the best configuration, that has no worse
> cross-language slice by a sign test at p < 0.1, and whose warm query p95 on the M1 stays below 150 ms.
> On a tie, choose the smaller dimension.

The numbers are illustrative — the point is that they are fixed *before* you see results.

**Winner's curse.** Picking the best of 8 configurations on the same ~45 items overstates the winner's score. Say so
in the ADR. The Phase 3 tuning/held-out split fixes this properly; until then, the golden set stays frozen (v1) for
the whole benchmark.

### Benchmark loop (sketch)

```python
for profile in PROFILES:                     # 4 models
    for chunk_cfg in CHUNK_CONFIGS:          # 2 sizes
        name = collection_name(profile, chunk_cfg)            # see #9 for the naming scheme
        build_collection(name, profile, chunk_cfg, corpus)    # idempotent (#8), manifest in metadata (#9)
        run = run_retrieval_eval(collection=name, profile=profile,
                                 dataset="retrieval_v1", top_k=10, threshold=None)
        save_run(run)    # full config: model + revision, fastembed version, prefixes, chunk cfg, collection,
                         # dataset version + hash, git SHA, machine, threads, timestamp
report = compare(runs, baseline=("e5-base", "c1000"))         # flips + sign test per slice
```

### In kb-agent

- **M1.2:** `Embedder` with profiles, `add_custom_model` registrations + golden-vector tests, eval CLI with
  `--collection`, the benchmark itself → **ADR-0004** (results table, decision rule, decision, threshold, revisit triggers).
- **D9 / A1:** with 8 GB RAM, run bge-m3 once and unload it; bge-m3 is the second item on the §9 cut line.
- **Revisit triggers** to write into ADR-0004: golden set v2, corpus grows by a new language or domain, Phase 3
  hybrid or reranker, Phase 6 fine-tuning, hardware upgrade.

### Pitfalls

1. **Wrong prefix for the profile** (prefixes on bge-m3, none on E5) — silently worse, never an error. Test the exact input string per profile.
2. **Wrong pooling** in `add_custom_model` — same symptom; caught only by the golden-vector test.
3. **Comparing models on different chunkings or corpus snapshots.** Change one factor at a time.
4. **Truncation confound** between 512- and 8192-token models (above).
5. **Unanswerable items inside hit@k denominators** — they drag every model down equally and blur the comparison.
6. **Editing the golden set after seeing results.** That's tuning on the test set; bump to v2 instead.
7. **Cold or cross-machine latency numbers**, or default ONNX threads.
8. **One overall average** that hides a collapsing cross-language slice.
9. **Ignoring operational cost:** the two large models add ~2.2 GB to an image and to every cold start.

---

## #11 Relevance thresholds & abstention

### Why it matters

Dense search **always** returns `top_k` hits, even for "What is the capital of France?" against a DevOps knowledge
base. Without a gate, the LLM receives irrelevant context and either hallucinates around it or — best case — refuses
after you have paid for the call. "This isn't in the knowledge base" is the *correct* answer for an unanswerable
question; abstention is a feature you design and measure, not an error path.

### The key insight: similarity ≠ answerability

A cosine score measures **topical closeness**, not whether the passage contains the answer.

| Question type | Typical top-1 score | Can a score threshold catch it? |
|---|---|---|
| Answerable | high | — (must pass) |
| **Off-topic** unanswerable ("capital of France") | low | **Yes** |
| **Near-miss** unanswerable (runbook covers `kubectl rollout undo`, question asks about Helm rollbacks) | **as high as answerable** | **No** |

Near-miss items (Batch 1 asked you to write them on purpose) are invisible to a threshold. Catching them is the
LLM's job (grounded refusal, Batch 3 #10), and later a reranker's — a cross-encoder reads question and passage
together, so its scores track relevance much better (Phase 3).

So abstention has **two layers**: a cheap, coarse retrieval gate and an expensive, fine-grained refusal in
generation.

### The asymmetry that sets the threshold

- **False abstention** (an answerable question is refused by the gate) is **unrecoverable** — the LLM never sees the sources.
- **False acceptance** (an unanswerable question passes the gate) is **recoverable** — the LLM can still refuse.

Therefore set the gate **conservatively low**: its job is to stop clear off-topic questions, not to decide
answerability.

### Three uses of a score threshold

1. **Gate** — answer or abstain, decided on the top-1 score.
2. **Filter** — drop weak hits from the context (fewer distractors, fewer tokens).
3. **Display** — the threshold line in the retrieval inspector (M1.5).

Qdrant's `score_threshold` on `query_points` does (2) directly and (1) implicitly: if nothing survives, you abstain.
For cosine, hits with a score **≥** the threshold are kept (verified).

### Calibration procedure

Run on the configuration chosen in #5, with **no threshold and `top_k = 10`**:

1. For each golden item record the top-1 score (the gate sees only that — it can't know relevance at runtime).
2. Split items into answerable / off-topic unanswerable / near-miss unanswerable.
3. For each candidate threshold `t` on a grid, compute
   - **false-abstention rate** = answerables with top-1 < `t` / answerables,
   - **false-acceptance rate** = unanswerables with top-1 ≥ `t` / unanswerables (report off-topic and near-miss separately),
   - both **per language**.
4. Choose by a rule written in advance, e.g. *the highest `t` with false abstention ≤ 5 % in every language slice.*
5. Record `t`, the curves and `n` per group in ADR-0004, and store `t` in the **model profile / collection
   manifest** (#9) — not only in an env var.

```python
def calibrate(items, grid):
    ans = [i for i in items if i.answerable]
    off = [i for i in items if not i.answerable and i.kind == "off_topic"]
    near = [i for i in items if not i.answerable and i.kind == "near_miss"]
    for t in grid:
        yield {
            "t": t,
            "false_abstain": sum(i.top1 < t for i in ans) / len(ans),
            "accept_off_topic": sum(i.top1 >= t for i in off) / len(off),
            "accept_near_miss": sum(i.top1 >= t for i in near) / len(near),   # expect ~1.0 — that's the insight
        }
```

### How much do 8 unanswerable items tell you?

Very little. With the plan's minimum of 8 unanswerables, the 95 % Wilson intervals are:

| Observed false acceptances | 95 % interval |
|---|---|
| 0 / 8 | 0 – 32 % |
| 1 / 8 | 2 – 47 % |
| 0 / 15 | 0 – 20 % |
| 0 / 20 | 0 – 16 % |

Off-topic negatives are the cheapest items you'll ever write — ten more take minutes. Suggestion for golden set v1:
**about 8 near-miss + 10 off-topic** unanswerables. Treat the Phase 1 threshold as a coarse safety net and say so in
the ADR.

### The abstention path (design now, build in M1.3)

When no hit survives the threshold:

- **Skip the LLM call.** Deterministic, free, fast.
- Emit `sources` with an empty list, then the "not in the knowledge base" message as `token` events, then `done`.
- Pick the message language from the question (or the UI locale); keep DE and EN templates.
- Set `kb.abstained = true` on the chat span (#18) — abstention rate is a quality signal worth charting.
- If a **domain filter** was active, say so in the message ("nothing found in *devops* — try without the filter").
  A user-set convenience filter (Batch 1) is a common cause of abstention.

Whether `done` gets an explicit `abstained` field is a contract decision (D14) — note it for Batch 3.

### In kb-agent

- **M1.2:** calibration is part of the benchmark → ADR-0004; `RETRIEVAL_SCORE_THRESHOLD` becomes an *override* of
  the profile value, not the source of truth.
- **M1.3:** abstention path in the chat pipeline + a test with the `fake` provider asserting the LLM is never called.
- **M1.5:** the inspector shows **all** hits with the threshold drawn as a line — it must not apply the threshold itself.
- **#9:** every re-index or model swap **re-calibrates** before promotion.

### Pitfalls

1. **One global threshold across models.** E5 scores cluster around 0.7–1.0 (Batch 1); a threshold carried over to another model abstains on everything or nothing.
2. **Cross-language queries score lower.** A single `t` can quietly refuse many DE→EN questions — check false abstention per language.
3. **Ranking metrics computed with the threshold on.** Keep hit@k / MRR / nDCG threshold-free and report abstention metrics separately; otherwise a threshold change looks like a ranking change.
4. **Expecting the threshold to catch near-misses.** It can't; measure it anyway so the ADR says so with numbers.
5. **Domain filters shrink the candidate pool** and lower the top-1 score — more abstentions with filters on.
6. **Forgetting to recalibrate** after re-chunking or a model swap.
7. **Calling the LLM with zero sources** "so it can phrase the refusal" — you pay for a guess and lose determinism.
8. **Alternatives worth an experiment later, not now:** score margins (top-1 minus top-10), per-query normalisation, reranker scores (Phase 3).

---

## #8 Idempotent ingestion pipeline

### Why it matters

In practice ingestion runs **at least once**, not exactly once: a double click, a Nest retry after a timeout (while
the AI service actually finished), boot recovery re-running a stuck row, a deliberate re-ingest after a parser fix,
two replicas in Phase 4. If "run twice" doesn't equal "run once", you get:

- **Duplicates** — the same passage twice in the top-k: wasted context, skewed eval numbers.
- **Orphans** — chunks of deleted or shrunk documents keep answering questions, citing a document the UI no longer shows.
- **Zombie states** — rows stuck in `processing` forever.

**Definition.** An operation is idempotent if applying it n ≥ 1 times has the same effect as applying it once. For
ingestion that means: *after `ingest(doc_id, bytes, config)` succeeds, the points stored for `doc_id` are exactly
`chunks(bytes, config)` — no matter how many attempts, retries or crashes came before.*

### Three keys, three jobs

| Key | Value | Job | Where |
|---|---|---|---|
| Content key | SHA-256 of the uploaded bytes | Reject duplicate uploads (409) | Postgres `unique(sha256)` |
| Document identity | `doc_id` = row UUID | Identity of *one upload*; a re-upload after delete gets a new one | Postgres, Qdrant payload |
| Point identity | `UUIDv5(NAMESPACE, f"{doc_id}:{chunk_index}")` | Re-ingest **overwrites** instead of duplicating | Qdrant point ID |

```python
# ai_service/vectorstore/ids.py
POINT_NAMESPACE = uuid.UUID("…")  # generate once, commit, NEVER change — a new namespace re-IDs every point

def point_id(doc_id: str, chunk_index: int) -> str:
    return str(uuid.uuid5(POINT_NAMESPACE, f"{doc_id}:{chunk_index}"))
```

Add a snapshot test that pins `point_id("00000000-…", 0)` to a literal UUID — it fails loudly if someone "tidies up"
the namespace or the format string.

### The shrink problem (verified)

Deterministic IDs make *overwrites* safe, but not *shrinks*. A document that produced 5 chunks and now produces 3
(parser fix, new chunk size, edited content) leaves points 3 and 4 behind — the test above went 5 → 5 points instead
of 5 → 3. Three ways out:

| Strategy | How | Trade-off |
|---|---|---|
| Delete, then upsert | `delete(doc_id = X)` → upsert all | A window with **zero** points for the document; if the upsert fails, the document vanishes |
| **Upsert, then delete the tail** (recommended for P1) | upsert N chunks → `delete(doc_id = X AND chunk_index ≥ N)` | No empty window; relies on `chunk_index` being contiguous from 0 |
| Run ID | payload `ingest_run`; upsert → `delete(doc_id = X AND ingest_run ≠ current)` | Handles any shape change; one more payload field |

```python
def write_document(client, collection, doc_id, points):
    for batch in batched(points, 64):
        client.upsert(collection, batch, wait=True)          # wait=True is the default — keep it explicit
    client.delete(collection, models.FilterSelector(filter=models.Filter(must=[
        models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id)),
        models.FieldCondition(key="chunk_index", range=models.Range(gte=len(points))),
    ])), wait=True)
```

`wait=True` matters: Nest marks the row `ready` when this returns. Without it, a "ready" document might not be
searchable yet — exactly the kind of flake that breaks the Playwright smoke test.

**Embed everything before the first upsert.** For Phase 1 document sizes (≤ 20 MB) compute all vectors first, then
write. If writing fails half-way, delete by `doc_id` (best effort) and report `failed` — a half-indexed document must
not answer questions.

### The state machine — transitions as compare-and-set

```
pending ──claim──► processing ──finish──► ready
   ▲                    │
   └──recover (lease)───┤──fail──► failed
```

Each arrow is a **conditional `UPDATE`**; the `WHERE` clause is the lock. No `SELECT`-then-`UPDATE`.

```sql
-- upload (Nest): dedupe without a race; no row returned → 409
INSERT INTO documents (id, owner_id, owner_name, filename, mime, size_bytes, sha256, domains, status)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'pending')
ON CONFLICT (sha256) DO NOTHING
RETURNING id;

-- claim: 0 rows → somebody else owns it (or it was deleted) → stop
UPDATE documents SET status = 'processing', attempts = attempts + 1, updated_at = now()
WHERE id = $1 AND status = 'pending'
RETURNING id;

-- finish: 0 rows → the row changed under us → compensate (delete the vectors)
UPDATE documents SET status = 'ready', chunk_count = $2, page_count = $3, embedding_model = $4, updated_at = now()
WHERE id = $1 AND status = 'processing'
RETURNING id;
```

Two concurrent uploads of the same file both pass any "does it exist?" check; only the unique constraint is a real
guard. `ON CONFLICT DO NOTHING RETURNING` turns the race into a clean 409.

**Suggested schema addition:** `attempts integer not null default 0` (§7.4 doesn't have it yet).

### Recovery — and the catch in D7

The recovery rule is short *because* ingestion is idempotent: "it was interrupted → just run it again". At boot, a
single Nest process knows every `processing` row is stale; with several replicas (Phase 4) you need a lease
(`updated_at` older than, say, 15 minutes).

**But D7 says originals are not stored in Phase 1.** After a crash the uploaded bytes are gone (they lived in memory
or a temp file), so recovery can only mark the row `failed` and ask for a re-upload. The same decision blocks
re-chunking user documents in #9. Storing originals content-addressed (`uploads/{sha256}` on a volume now, Blob
Storage in Phase 5) costs one volume and one more delete step — it is logged as a finding in DONE.md for you to
decide.

```sql
-- boot recovery (with originals stored): retry up to 3 attempts, then give up
UPDATE documents
SET status = CASE WHEN attempts >= 3 THEN 'failed' ELSE 'pending' END,
    error  = CASE WHEN attempts >= 3 THEN 'ingest interrupted 3 times' ELSE error END,
    updated_at = now()
WHERE status = 'processing' AND updated_at < now() - interval '15 minutes';
-- then enqueue every 'pending' row
```

### Delete without zombies

The dangerous race: ingest is running → the user deletes the document → Nest deletes row and vectors → ingest
finishes and **upserts** → points without a row, answering questions forever.

The simplest Phase 1 rule closes it:

1. **Deleting a `processing` document returns 409** ("still processing, try again shortly").
2. Otherwise: delete the vectors first (idempotent — deleting missing points is fine), then
   `DELETE FROM documents WHERE id = $1 AND status <> 'processing'`.
3. The `finish` update above is conditional anyway, so a late result for a vanished row triggers a compensating delete.

Order matters: vectors-then-row means a failure leaves a *visible* row without vectors (fixable). Row-then-vectors
leaves *invisible* vectors that keep answering — the worse failure, and a privacy problem once documents are private.

### Reconciliation — the safety net for races you didn't think of

A small job (at boot and as a CLI command) compares the two stores. `facet` returns chunk counts per `doc_id` in one
call (verified; needs the keyword index on `doc_id` that D10 already creates):

```python
facets = client.facet(collection, key="doc_id", limit=100_000, exact=True)
in_qdrant = {hit.value: hit.count for hit in facets.hits}
in_db = {row.id: row.chunk_count for row in ready_rows}
orphans  = in_qdrant.keys() - in_db.keys()                                        # → delete by doc_id
mismatch = {d for d in in_db.keys() & in_qdrant.keys() if in_db[d] != in_qdrant[d]}  # → re-ingest or flag
missing  = in_db.keys() - in_qdrant.keys()                                        # 'ready' without vectors → flag
```

### Retries between Nest and the AI service

- **Don't blindly retry `POST /v1/ingest`** on a timeout: the first attempt may still be running. Idempotency makes
  the duplicate harmless, not free (it embeds everything twice). Retry only when the request provably never arrived
  (connection refused); leave everything else to recovery.
- Give the ingest call a timeout that fits the largest allowed document, separate from the chat timeouts.

### Cheap metadata edits

Changing a document's `domains` doesn't change its text, so it needs no re-embedding:
`set_payload(collection, {"domains": [...]}, points=Filter(doc_id = X))` plus the row update. Same idempotency, a
fraction of the cost (no endpoint for this in Phase 1 yet).

### In kb-agent

- **M1.2 (AI service):** `point_id()` + snapshot test; embed-then-write; tail delete; cleanup on failure; spans for every step (#18).
- **M1.4 (Nest):** `ON CONFLICT` upload; conditional claim/finish; 409 on deleting `processing`; vectors-then-row delete; boot recovery; reconciliation.
- **Acceptance tests** (M1.2/M1.4 already name the first two): ingest twice → same count · re-ingest a shrunk document → no orphans · two concurrent identical uploads → one 202, one 409 · delete during processing → 409 · crash mid-ingest → `failed` (or `pending` with originals) · reconciliation finds a planted orphan.
- **Phase 3:** the queue. With Postgres already there, the row *is* the job: `SELECT … FOR UPDATE SKIP LOCKED` (or a library such as pg-boss) before reaching for Redis.

### Pitfalls

1. **Check-then-insert dedupe** — races; use the unique constraint.
2. **Changing the UUIDv5 namespace or ID format** — every point duplicates on the next ingest.
3. **Non-deterministic chunking** (Batch 1) — same document, different chunks, different IDs.
4. **Forgetting the shrink case** — orphans that pass every "no duplicates" test.
5. **Marking `ready` before writes are applied** (`wait=False`).
6. **Leaving half-written documents** after a failure.
7. **Global SHA-256 uniqueness in Phase 3:** with ACLs, a 409 reveals that *someone* uploaded the file, and two teams can't own the same document. Plan `unique(tenant_or_owner, sha256)` when ACLs arrive.
8. **Same content, different bytes** (a PDF re-saved with new metadata) is not caught by SHA-256 — accept it, but know it.
9. **"Boot recovery" without stored originals** can only fail rows, not retry them.

---

## #9 Zero-downtime re-indexing with aliases

### Why it matters

You will re-index far more often than you expect: after the #5 benchmark, after a chunk-size change, a parser fix
(pypdf hyphenation), embedding the heading path differently, a new payload field (`lang`), HNSW or quantization
changes, Phase 3 sparse vectors, a Phase 6 fine-tuned model. Each change done **in place** means a window where the
index is half old, half new — and no way back. Building a **new collection beside the old one** and switching an
alias gives you a validated cut-over and a one-call rollback.

### The mechanics (verified)

- An alias is a name that points to one collection. Reads **and writes** through the alias go to the current target.
- `update_collection_aliases` applies a **list** of operations **atomically**:

```python
client.update_collection_aliases(change_aliases_operations=[
    models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name="kb_current")),
    models.CreateAliasOperation(create_alias=models.CreateAlias(
        collection_name="kb__e5-base__768__c1000__20261020", alias_name="kb_current")),
])
```

- Measured today: **0 failed searches out of 548** during 150 flips in one request each; **654 of 1,261 failed**
  when delete and create were sent as two requests — the gap between them is a real outage, even if it lasts
  milliseconds.
- `CreateAlias` on an existing alias re-points it silently (1.18.0 and 1.19.2). Use the explicit delete + create
  pair anyway: it says what you mean and doesn't rely on behaviour you only observed, not read in the docs.
- **Deleting a collection deletes its aliases.** Clean up the *wrong* collection and `kb_current` is gone: instant 404.

### The query-side coupling problem — the part most tutorials skip

The alias swaps the **documents**. The **queries** are embedded by the AI service with *its* loaded model. When the
model changes, query embedder and collection must change **in lockstep**:

| Situation after the flip | What happens |
|---|---|
| Different dimension (e5-base 768 → e5-large 1024) | Every search fails with a dimension error — loud |
| **Same dimension, different model** (e5-large ↔ bge-m3, both 1024) | Searches succeed and return **garbage** — silent |
| Same model, new chunking / parser / payload | Nothing to coordinate — the flip alone is zero-downtime |

The fix is to make the collection **describe itself** and the service **check**:

**1. An index manifest in collection metadata** (Qdrant collection `metadata`, verified on 1.18 and 1.19):

```json
{
  "schema_version": 1,
  "embedding_model": "intfloat/multilingual-e5-base",
  "model_revision": "<hf-commit-or-onnx-sha256>",
  "dim": 768, "pooling": "mean",
  "query_prefix": "query: ", "passage_prefix": "passage: ",
  "chunker": {"name": "recursive-md", "size": 1000, "overlap": 150, "version": "1"},
  "parsers": {"pypdf": "<version>", "markdown-it-py": "<version>"},
  "score_threshold": 0.81,
  "built_at": "2026-10-20T19:12:00Z", "git_sha": "abc1234",
  "eval_run": "2026-10-20T19-40_retrieval_v1"
}
```

(Values illustrative.) The manifest now carries everything #5 and #11 decided — prefixes, threshold — so they travel
with the vectors instead of living in a global env var.

**2. Resolve the alias, check the manifest, query the resolved name:**

```python
def resolve_index(client, alias: str, embedder) -> ResolvedIndex:
    target = next(a.collection_name for a in client.get_aliases().aliases if a.alias_name == alias)
    manifest = IndexManifest.model_validate(client.get_collection(target).config.metadata)
    if (manifest.embedding_model, manifest.dim) != (embedder.profile.model_id, embedder.profile.dim):
        raise IndexMismatch(target, manifest.embedding_model)   # /readyz fails, search → 503 problem+json
    return ResolvedIndex(collection=target, manifest=manifest)
```

Cache the result for a few seconds and query **the resolved name** for the whole request. That refines the Batch 1
rule "app code uses the alias only": *configuration* names only the alias; each request runs against one concrete,
checked collection, so model and vectors always match.

**Three levels of "zero downtime" for a model change:**

| Level | Behaviour during a model swap | Cost | When |
|---|---|---|---|
| 1 — detect | Mismatch → 503 for the seconds it takes to restart with the new `EMBEDDING_MODEL`. Zero *wrong* answers. | Nothing extra | **Phase 1 default** |
| 2 — follow | Service sees a new manifest, loads that profile, then switches; serves the old collection meanwhile | Two models in RAM briefly | P1 stretch / Phase 6 |
| 3 — split | Two collections live at once, traffic split (champion/challenger) | Two embedders resident | Phase 6 A/B with MLflow aliases |

For re-indexing *without* a model change, Level 1 is already genuinely zero-downtime.

### Blue/green procedure

1. **Precondition:** a source of truth to rebuild from — stored originals (finding from #8), or at least the
   sample corpus on disk.
2. **Build** `kb__{model}__{dim}__{chunk}__{build-id}` with the manifest; create the payload indexes immediately
   (Batch 1). Today's D10 name `kb__{model_slug}__{dim}` **collides** when only the chunking changes — hence the
   extra parts (logged as a finding).
3. **Freeze writes.** In Phase 1 (one user) the honest answer is a maintenance flag: `POST`/`DELETE
   /api/documents` return 503 with `Retry-After`. Without it, uploads during the backfill go only to the old
   collection (writes follow the alias — verified) and disappear at the flip. Dual-write and `updated_at`-based
   catch-up are the grown-up alternatives once rebuilds take hours.
4. **Backfill** every `ready` document into the new collection **by name**, idempotently (#8).
5. **Validate** before anyone sees it:
   - point count = sum of `chunk_count` (or `facet` per document);
   - collection status `green` (optimizer finished);
   - payload indexes present;
   - `kb-eval retrieval --collection <new>` — per-item flips against the current baseline (#5);
   - threshold **re-calibrated** (#11) and written into the manifest.
6. **Promote:** atomic alias flip (+ restart if the model changed, Level 1).
7. **Smoke-check** a few known questions through the real chat path; then lift the write freeze.
8. **Keep the old collection** for a rollback window. Rollback = flip back. Writes made *after* the flip exist only in
   the new collection — so keep the window short, or replay those documents.
9. **Garbage-collect** later, and never the alias target.

### Make it a tool, not a checklist

A small `kb-index` CLI in the AI service is the only thing allowed to change aliases; the service itself only reads
them.

| Command | Does |
|---|---|
| `kb-index list` | Collections, manifests, which one is live |
| `kb-index build --profile e5-base --chunk 1000` | Steps 2 + 4 |
| `kb-index eval <name>` | Wraps `kb-eval retrieval --collection <name>` |
| `kb-index promote <name>` | Refuses unless: manifest valid, indexes present, counts match, an eval run newer than the build exists, threshold set — then flips atomically and records the previous target |
| `kb-index rollback` | Flips back to the recorded previous target |
| `kb-index gc --keep 2` | Deletes old builds, never the alias target |

### In kb-agent

- **M1.2:** the collection manager creates `kb__…__{build-id}` collections with a manifest and creates the alias on
  first run; `/readyz` includes the manifest check; the benchmark (#5) builds its 8 collections with the same code.
- **D10:** the alias is already planned — add the manifest and the naming suffix.
- **Phase 6:** MLflow champion/challenger aliases map one-to-one onto Qdrant aliases (Level 3).

### Pitfalls

1. **Delete + create as two requests** — measured outage.
2. **Deleting the collection the alias points to.**
3. **Same-dimension model swap without a manifest check** — silent garbage.
4. **Evaluating through `kb_current`** instead of the candidate's name — you measured the old index.
5. **Forgetting payload indexes** on the new collection (slow filters, poor query planning).
6. **Uploads during the backfill** land only in the old collection.
7. **Threshold and prefixes not swapped with the model** — fixed by keeping them in the manifest.
8. **Rollback loses writes** made after the flip.
9. **RAM on the M1:** two large collections plus, at Level 2, two large models (~4.5 GB of weights for e5-large + bge-m3).
10. **Orphan collections pile up** on disk — `gc`.
11. **A hard-coded collection name** anywhere outside the index tool.

---

## #18 LLM tracing & observability

### Why it matters

A RAG answer is the product of about six steps. When an answer is wrong, a log line saying "200 OK in 2.3 s" can't
tell you whether retrieval missed (debug left to right — Batch 1 #1), the prompt builder trimmed the right chunk
away, or the model ignored it. A **trace** shows every step's input, output and timing as one tree. It also gives
you the latency breakdown (embedding vs search vs time to first token), tokens and cost per request, and later the
bridge from user feedback (Phase 3) to new eval items. That's why tracing is on the plan's "never cut" list.

### OpenTelemetry in two minutes

| Concept | Meaning | In kb-agent |
|---|---|---|
| **Trace** | One request end to end, identified by a 128-bit trace ID | One `/v1/chat` or `/v1/ingest` call |
| **Span** | One step: name, start/end, parent, attributes, events, status | `chat`, `search`, `ChatCompletion` … |
| **Context propagation** | In-process via `contextvars`; across processes via the W3C `traceparent` header | Python only in P1 (see correlation below) |
| **Resource** | Who emits the spans (`service.name`) | `OTEL_SERVICE_NAME=ai-service` |
| **Span processor** | `SimpleSpanProcessor` exports synchronously at span end; `BatchSpanProcessor` buffers and exports in the background | Simple in tests, Batch in the service |
| **Exporter** | Sends spans via OTLP: gRPC (:4317) or HTTP (`:6006/v1/traces` for Phoenix) | gRPC to Phoenix |
| **Sampling** | Which traces to keep | 100 % in Phase 1 |

### OpenInference — conventions on top of OTel

Plain OTel spans are just names and key/value pairs. **OpenInference** standardises the keys so an LLM backend like
Phoenix knows how to render them: a retriever span as a ranked document list, an LLM span as a chat transcript with
token counts.

- `openinference.span.kind`: `CHAIN`, `LLM`, `RETRIEVER`, `EMBEDDING`, `RERANKER`, `TOOL`, `AGENT`, `GUARDRAIL`,
  `EVALUATOR`, `PROMPT`, `DECISION`, `UNKNOWN`.
- Common: `input.value`, `output.value`, `metadata`, `tag.tags`, `session.id`, `user.id`.
- LLM: `llm.model_name`, `llm.provider`, `llm.input_messages`, `llm.output_messages`, `llm.invocation_parameters`,
  `llm.token_count.{prompt,completion,total}`, `llm.prompt_template.{template,version,variables}`.
- Retrieval: `retrieval.documents.{i}.document.{id,score,content,metadata}`.
- Embedding: `embedding.model_name`, `embedding.embeddings.{i}.embedding.{text,vector}`.

The `openai` SDK is instrumented automatically (`openinference-instrumentation-openai`); fastembed and Qdrant are
not, so `embed`, `search` and `prompt` are **manual spans** — exactly what D21 says.

### Target span trees

```
POST /v1/chat                        server span (FastAPI creates it — see trap 4)
└─ chat                    CHAIN     input = question · output = answer · kb.request_id · kb.collection
   │                                 kb.abstained · kb.cancelled · event "first_token"
   ├─ embed_query          EMBEDDING embedding.model_name · text (never the vector)
   ├─ search               RETRIEVER retrieval.documents.* · kb.top_k · kb.score_threshold · kb.filter.domains
   ├─ build_prompt         CHAIN     llm.prompt_template.version · kb.context_tokens · kb.sources_used
   └─ ChatCompletion       LLM       automatic: messages, model, token counts, invocation parameters

POST /v1/ingest
└─ ingest                  CHAIN     kb.doc_id · kb.chunk_count · kb.page_count
   ├─ parse · chunk
   ├─ embed_passages       EMBEDDING kb.batches · kb.max_tokens_seen · kb.truncated_chunks
   └─ upsert · delete_tail
```

Span **names stay low-cardinality** (`search`, never `search: how do I roll back…`); variable data goes into attributes.

### Setup

```python
# ai_service/core/tracing.py
from phoenix.otel import register
from openinference.instrumentation.openai import OpenAIInstrumentor

def setup_tracing(settings) -> TracerProvider:
    provider = register(project_name=settings.phoenix_project, batch=True, verbose=True)
    OpenAIInstrumentor().instrument(tracer_provider=provider)
    return provider

# FastAPI lifespan: provider = setup_tracing(settings); yield; provider.shutdown()   # flushes the batch queue
tracer = provider.get_tracer("ai_service")    # an OITracer: start_as_current_span(..., openinference_span_kind=...)
```

`register()` reads `PHOENIX_COLLECTOR_ENDPOINT` or `OTEL_EXPORTER_OTLP_ENDPOINT`; with nothing set it chose gRPC on
`localhost:4317` in today's test, which matches the plan's `.env`. With `verbose=True` it prints the resolved
"Collector Endpoint" and transport at startup — check that line once instead of guessing.

Manual retriever span (verified output: `retrieval.documents.0.document.{content,id,metadata,score}`):

```python
from openinference.instrumentation import get_retriever_attributes

with tracer.start_as_current_span("search", openinference_span_kind="retriever") as span:
    span.set_input(query)
    span.set_attributes({"kb.collection": idx.collection, "kb.top_k": top_k,
                         "kb.filter.domains": domains or []})
    if threshold is not None:                      # OTel attributes can't be None
        span.set_attribute("kb.score_threshold", threshold)
    hits = client.query_points(idx.collection, query=vector, using="dense", limit=top_k,
                               score_threshold=threshold, query_filter=flt).points
    span.set_attributes(get_retriever_attributes(documents=[
        {"id": str(h.id), "score": h.score, "content": h.payload["text"],
         "metadata": {"doc_id": h.payload["doc_id"], "page": h.payload.get("page"),
                      "heading": h.payload.get("heading")}} for h in hits]))
```

The chat span lives **inside the SSE generator** (trap 1), records time to first token as an event and marks
cancellation (trap 3):

```python
async def chat_events(req, deps):
    with tracer.start_as_current_span("chat", openinference_span_kind="chain") as span:
        span.set_input(req.messages[-1].content)
        span.set_attribute("kb.request_id", deps.request_id)
        trace_id = format(span.get_span_context().trace_id, "032x")   # → `done.traceId`
        chunks, answer = 0, []
        try:
            # … resolve index, embed, search, emit `sources`, abstain or build prompt …
            async for ev in deps.provider.stream_chat(messages, opts):
                if ev.type == "token":
                    if chunks == 0:
                        span.add_event("first_token")
                    chunks += 1
                    answer.append(ev.text)
                    yield sse("token", {"text": ev.text})
            span.set_output("".join(answer))
            yield sse("done", {"usage": usage, "model": model, "traceId": trace_id})
        except (asyncio.CancelledError, GeneratorExit):
            span.set_attribute("kb.cancelled", True)
            span.set_attribute("kb.chunks_streamed", chunks)
            raise
```

### Five traps — all reproduced today

**Trap 1 — the span ends before the stream starts.** A span opened in the endpoint around
`return StreamingResponse(gen())` closes when the function returns, before a single token is sent. Measured:
`chat_wrong` lasted **0.0 ms**; the same span opened inside the generator lasted **151.7 ms** with its child
correctly nested. Rule: *open request-scoped spans inside the generator.*

**Trap 2 — streaming spans without token counts.** The instrumentor can only record what the stream contains. Without
a final usage chunk, `llm.token_count.*` stayed empty; with it, the counts appeared. OpenRouter now sends usage
(including `cost`) in every response and treats `stream_options.include_usage` as a deprecated no-op; servers that
follow OpenAI's semantics (vLLM, Ollama — and probably the HF router, to be checked in M1.3) only send it when asked.
Portable rule for the `openai_compat` provider: **always send `stream_options={"include_usage": True}`** — harmless
on OpenRouter, required elsewhere.

**Trap 3 — cancelled requests look like successes.** When the consumer stops early and closes the stream, the LLM
span ended with status `UNSET` and an **empty output**; a manual span around a generator closed by `aclose()` or by
task cancellation also ended `UNSET` with no exception event. Without `kb.cancelled = true` you can't tell a user
pressing Stop from a normal answer — or measure how often it happens.

**Trap 4 — the framework already traces.** FastAPI 0.143 creates its own server span (`POST /v1/chat`) plus
`fastapi.endpoint` / `fastapi.dependencies` child spans once a tracer provider is set — observed in the experiment;
the server span correctly covered the whole stream (153 ms). So **don't add** `opentelemetry-instrumentation-fastapi`
on top (duplicate spans), exclude the probes with `FastAPI(telemetry={"exclude": lambda scope: scope["path"] in
("/healthz", "/readyz")})`, and leave `FASTAPI_OTEL_AUTO_CONFIGURE` unset (Phoenix's `register()` owns the exporter).

**Trap 5 — short-lived processes lose spans.** `BatchSpanProcessor` exports in the background. The `kb-eval` CLI
exits before the queue drains unless it calls `provider.force_flush()` (or `shutdown()`) at the end. Give CLI runs
their own project (`PHOENIX_PROJECT_NAME=kb-agent-eval`) so 400 benchmark queries don't bury your chat traces.

### Cost in traces

The OpenAI instrumentor records **token counts, not OpenRouter's `usage.cost`**. Phoenix computes cost itself from
`llm.model_name` + `llm.provider` + token counts against a built-in pricing table; under *Settings → Models* you can
add or override prices with a name regex. Whether OpenRouter-style IDs (`vendor/model`) match out of the box isn't
documented — check one trace in M1.3 and add a pattern if needed. The `costUsd` in the `done` event should come
straight from OpenRouter's usage object (Batch 3, #16).

### Privacy, retention, persistence

- **Traces are a second copy of your corpus plus every user question.** Phase 1 is safe by construction (public
  documents only, D25; Phoenix on localhost). For Phase 5, decide retention and access before deploying.
- **Masking:** `OPENINFERENCE_HIDE_INPUTS`, `…_OUTPUTS`, `…_INPUT_MESSAGES`, `…_OUTPUT_MESSAGES`,
  `…_RETRIEVAL_DOCUMENTS`, `…_EMBEDDING_VECTORS` (names verified) mask auto-instrumented content. Your manual spans
  must honour the same setting — read it in `tracing.py` and skip `set_input`/`content` accordingly.
- **Retention:** `PHOENIX_DEFAULT_RETENTION_POLICY_DAYS` (default `0` = keep forever).
- **Persistence:** without `PHOENIX_SQL_DATABASE_URL`, Phoenix keeps SQLite **in a temporary folder**. Mounting a
  volume is not enough — point `PHOENIX_WORKING_DIR` at it, or use the Postgres you already run:

```yaml
phoenix:
  image: arizephoenix/phoenix:version-20.21.2-nonroot   # amd64 + arm64; pin it, let Dependabot bump it
  ports: ["127.0.0.1:6006:6006", "127.0.0.1:4317:4317"]
  environment:
    PHOENIX_SQL_DATABASE_URL: postgresql://postgres:${POSTGRES_PASSWORD}@postgres:5432/phoenix   # + CREATE DATABASE phoenix in init.sql
    # or: PHOENIX_WORKING_DIR: /data   with a volume mounted at /data
  depends_on: { postgres: { condition: service_healthy } }
```

### Correlation: one ID everywhere

- **UI → trace:** the `done` event carries `traceId` (32 hex characters from the chat span); the dev-mode link opens it in Phoenix.
- **Logs → trace:** put `trace_id` and `span_id` into every JSON log line (a logging filter reading the current span), next to `request_id`.
- **Nest → AI service:** in Phase 1 only the AI service is traced, and `x-request-id` stitches the logs. Don't send
  a `traceparent` from Nest unless Nest also exports spans — otherwise Phoenix shows every AI-service trace with a
  missing parent. Full cross-service traces come with an OTel collector in Phase 4/5.

### Testing tracing

Make tracing a function that takes a provider (no module-level side effects). In pytest, use an
`InMemorySpanExporter` with a `SimpleSpanProcessor` and assert the **tree shape** and key attributes:
`chat` is the parent of `embed_query`, `search` and `ChatCompletion`; `search` has `retrieval.documents.*`;
the abstention test has `kb.abstained = true` and no LLM span; the cancellation test has `kb.cancelled = true`.
CI never needs a running Phoenix (`OTEL_SDK_DISABLED=true` or no exporter).

### Beyond traces: what to watch

| Signal | Source in Phase 1 |
|---|---|
| Latency: total, embedding, search, **time to first token** | Span durations + the `first_token` event |
| Tokens and cost per request / per user | LLM span + `done` usage, `user.id` on the chat span |
| Quality proxies: abstention rate, cancellation rate, citation-validator failures (Batch 3) | `kb.*` attributes |
| Errors | Span status + JSON logs |
| Throughput / error rate per endpoint | FastAPI's built-in metrics exist, but Phoenix doesn't ingest metrics — Prometheus/Azure Monitor in Phase 4/5 |

### In kb-agent

- **M1.1:** Phoenix in Compose (pinned tag, persistence), `tracing.py`, one test span, probes excluded.
- **M1.2:** ingest and search spans; `kb-eval` with its own project and a final flush.
- **M1.3:** chat span inside the generator, `first_token`, `kb.cancelled`, `kb.abstained`, `include_usage`, `traceId` in `done`, span-tree tests.
- **M1.5:** dev-mode trace link (third item on the cut line — the trace itself is not cuttable).

### Pitfalls

1. Span around `return StreamingResponse(...)` (trap 1).
2. No usage chunk → no token counts (trap 2).
3. Cancellations invisible (trap 3).
4. Double server spans from two instrumentations (trap 4).
5. Lost spans from short-lived processes (trap 5).
6. **Embedding vectors on spans** — kilobytes per span, useless to read; attach text only.
7. **High-cardinality span names.**
8. **Phoenix data in a temp folder** (persistence above).
9. **A `traceparent` without a parent exporter** (orphan display).
10. **Tracing as an import side effect** — makes tests flaky and CI dependent on a collector.
11. **Forgetting that traces contain data** — masking, retention and access are part of the design.

---

## Plan deltas found in this batch

These are proposals, not changes — the plan is yours. All are logged in DONE.md → *Findings*.

| # | Finding | Affects | Suggestion |
|---|---|---|---|
| 1 | Originals are not stored (D7), so boot recovery can only fail rows, and user documents can't be re-chunked | D7, #8, #9 | Store originals content-addressed (`uploads/{sha256}` volume → Blob in P5); decide in an ADR during M1.2/M1.4 |
| 2 | `kb__{model_slug}__{dim}` collides when only chunking changes | D10 | `kb__{model}__{dim}__{chunk}__{build-id}` + manifest in collection `metadata` (works on 1.18 and 1.19) |
| 3 | Threshold and prefixes are model-specific but configured globally | Appendix A, D9 | Keep them in the profile/manifest; `RETRIEVAL_SCORE_THRESHOLD` becomes an override |
| 4 | e5-large and bge-m3 share 1024 dims → silent garbage on a swap | D9, D10 | Manifest check in `/readyz` and per request |
| 5 | Phoenix stores SQLite in a temp folder by default; image tag format `version-X.Y.Z(-nonroot)`, arm64 available | M1.1 | `PHOENIX_SQL_DATABASE_URL` → `phoenix` DB in the existing Postgres, or `PHOENIX_WORKING_DIR` on a volume |
| 6 | FastAPI 0.143 traces requests natively | D21 | No `opentelemetry-instrumentation-fastapi`; exclude probes |
| 7 | Streaming token counts need a usage chunk; OpenRouter always sends one, others only on request | D11, D21 | Always send `stream_options.include_usage` |
| 8 | The instrumentor doesn't record OpenRouter's `cost`; Phoenix prices tokens from its own table | D21, D24 | `costUsd` from OpenRouter usage; custom price patterns in Phoenix if IDs don't match |
| 9 | 8 unanswerables give a 0–32 % interval at 0/8 | D23 | ~8 near-miss + ~10 off-topic in golden set v1 |
| 10 | Eval CLI must target a collection by name | M1.2 | `kb-eval retrieval --collection` |
| 11 | Small schema/behaviour gaps | §7.4, M1.4 | `attempts` column; 409 when deleting a `processing` document |

---

## Self-check

Answer without the notes first; the answers are folded underneath.

**#5 Benchmarking**

1. Give three reasons why the MTEB leaderboard is not enough to choose kb-agent's embedding model.
2. Which four things does ADR-0004 fix?
3. At 2000-character chunks bge-m3 beats every E5 model on multi-chunk items. Which confound do you rule out first, and how?
4. B beats A on 9 items and loses on 2 (hit@5); all other items agree. What do you conclude, and what decides between them?
5. Why must the decision rule be written down before the benchmark runs?
6. Which two silent registration mistakes does the golden-vector test catch?

**#11 Thresholds & abstention**

7. Why can't a similarity threshold catch near-miss unanswerables, and what catches them instead?
8. Explain the asymmetry between false abstention and false acceptance and what it means for choosing `t`.
9. You observe 0 of 8 false acceptances. What may you claim?
10. Why must hit@k, MRR and nDCG be computed without the threshold?
11. Where should the calibrated threshold live, and why not only in an env var?
12. What does the chat pipeline do when no hit survives the threshold, and why skip the LLM?

**#8 Idempotent ingestion**

13. Define idempotency for `ingest` precisely.
14. A document shrinks from 5 to 3 chunks and is re-ingested. What happens with UUIDv5 IDs alone, and what is the fix?
15. Why is `INSERT … ON CONFLICT DO NOTHING RETURNING` better than checking for the hash first?
16. Describe the delete-during-ingest race and the Phase 1 rule that closes it.
17. Why does D7 limit what boot recovery can do?
18. What does reconciliation compare, and which Qdrant API makes it a single call?
19. On delete, why vectors first and the row second?

**#9 Aliases & re-indexing**

20. Why must "delete alias" and "create alias" go in one request? What did the measurement show?
21. You swap e5-large for bge-m3 and flip the alias. What goes wrong, and how does the manifest prevent it?
22. List the validation steps before `promote`.
23. Why freeze uploads (or dual-write) during a backfill?
24. What does a rollback after the flip lose?

**#18 Tracing**

25. You wrap `return StreamingResponse(gen())` in a span inside the endpoint. What does Phoenix show, and why?
26. LLM spans have token counts with OpenRouter but not with vLLM. Why, and what is the portable fix?
27. A user presses Stop mid-answer. What does the trace look like by default, and what do you add?
28. After `docker compose down && up`, Phoenix has no traces. Why?
29. How do you get from a chat message in the UI to its trace, and from a log line to the same trace?
30. Give two reasons not to put embedding vectors on spans, and one privacy control for trace content.
31. Why does `kb-eval` need an explicit flush, and why its own Phoenix project?

<details>
<summary><strong>Answers</strong></summary>

1. Different data (general benchmarks vs DE + EN technical docs with flags and YAML); different queries (short, paraphrased, cross-language); leaderboard gaps smaller than your ±12-point noise; no CPU latency, RAM, image size or cold-start cost. Leaderboards build the shortlist only.
2. Model (+ revision), chunk configuration, score threshold, and the baseline numbers for Phase 3.
3. Truncation: E5 cuts at 512 tokens, bge-m3 reads up to 8192. Count tokens per chunk (`passage: ` + heading path included) and report the share above 512; if it's material, the comparison measures chunk visibility, not model quality.
4. Inconclusive (exact sign test p ≈ 0.065). With evidence this thin, cost decides: take the cheaper model, unless the pre-written rule says otherwise.
5. Otherwise you choose the rule that favours the result you saw (forking paths); with 8 configurations on ~45 items there's always some slice that "wins".
6. Wrong pooling (mean vs CLS) and missing normalisation in `add_custom_model` — both produce plausible vectors with worse quality. (Wrong *prefixes* are caught by the separate exact-input-string test.)
7. Cosine similarity measures topical closeness, not whether the passage contains the answer; near-misses are on-topic and score like answerables. The LLM's grounded refusal catches them now, a reranker or judge later.
8. False abstention is unrecoverable (the LLM never sees sources); false acceptance can still be refused by the LLM. So `t` is set low enough to keep false abstention near zero and only stop clear off-topic questions.
9. Little: the 95 % interval is 0–32 %. Add cheap off-topic items to tighten it.
10. Otherwise threshold changes masquerade as ranking changes; keep ranking quality and abstention behaviour as separate measurements.
11. In the model profile / collection manifest, because thresholds are model- and index-specific; a global env var survives a model swap and silently becomes wrong. The env var may remain as an override.
12. Emit empty `sources`, a templated "not in the knowledge base" message in the user's language (mentioning an active domain filter), then `done`; mark `kb.abstained`. Skipping the LLM is free, fast, deterministic and testable.
13. After a successful `ingest(doc_id, bytes, config)`, the points for `doc_id` are exactly `chunks(bytes, config)`, however many attempts or crashes preceded it.
14. Chunks 0–2 are overwritten, 3–4 stay as orphans. Fix: upsert, then delete `doc_id = X AND chunk_index ≥ N` (or use an ingest-run ID).
15. Two concurrent requests can both pass the check; the unique constraint is the only real guard, and `RETURNING` tells you who won without catching exceptions.
16. Ingest running → user deletes row and vectors → ingest finishes and upserts → orphan points that keep answering. Rule: deleting a `processing` row returns 409; claim/finish are conditional updates; a late finish for a vanished row deletes its vectors.
17. Without stored originals the bytes are gone after a crash, so recovery can only mark rows `failed`.
18. Chunk counts per `doc_id` in Qdrant vs `ready` rows and `chunk_count` in Postgres → orphans, mismatches, missing; `facet(key="doc_id", exact=True)`.
19. A failure then leaves a visible row without vectors (fixable) instead of invisible vectors that keep answering (and leak deleted content).
20. Between two requests the alias doesn't exist; searches 404. One request: 0 of 548 failed; two requests: 654 of 1,261 failed.
21. Same 1024 dims → no error, but bge-m3 vectors are compared with e5-large queries → garbage results. The service resolves the alias, reads the manifest, and refuses (503, `/readyz` fails) if the manifest's model differs from the loaded one.
22. Counts match, collection status green, payload indexes present, eval run by collection name with per-item flips vs baseline, threshold re-calibrated and in the manifest, then a smoke check after the flip.
23. Writes follow the alias, so uploads during the backfill go only to the old collection and vanish at the flip.
24. Writes made after the flip, which exist only in the new collection — keep the window short or replay them.
25. A near-zero-length `chat` span (measured 0.0 ms) without the streaming work; the span closes when the endpoint returns, before the generator runs. Open it inside the generator.
26. Token counts come from the final usage chunk. OpenRouter always sends it; OpenAI-style servers send it only with `stream_options={"include_usage": True}`. Always send that option.
27. Spans end with status `UNSET` and an empty LLM output — it looks like a normal request. Catch `CancelledError`/`GeneratorExit`, set `kb.cancelled = true` and the streamed chunk count, re-raise.
28. Without `PHOENIX_SQL_DATABASE_URL`, Phoenix keeps SQLite in a temporary folder. Use Postgres or set `PHOENIX_WORKING_DIR` to a mounted volume.
29. `done.traceId` (32-hex trace ID of the chat span) → dev-mode link; logs carry `trace_id`/`span_id` plus `request_id`.
30. They're large and unreadable; text is what you debug with. Privacy: `OPENINFERENCE_HIDE_*` masking (honoured by manual spans too), retention days, localhost-only/authenticated Phoenix.
31. `BatchSpanProcessor` exports asynchronously and the process exits first; a separate project keeps hundreds of eval queries from burying real chat traces.

</details>

---

## Sources

Verified today by running code against Qdrant 1.18.0 and 1.19.2 binaries and current PyPI packages (see the table
in §0). Documentation used:

- [FastAPI — OpenTelemetry](https://fastapi.tiangolo.com/advanced/opentelemetry/)
- [Phoenix — self-hosting configuration](https://www.arize.com/docs/phoenix/self-hosting/configuration.md)
- [Phoenix — cost tracking](https://www.arize.com/docs/phoenix/tracing/how-to-tracing/cost-tracking.md)
- [OpenRouter — usage accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting.md)
- [Docker Hub — arizephoenix/phoenix tags](https://hub.docker.com/r/arizephoenix/phoenix/tags)
