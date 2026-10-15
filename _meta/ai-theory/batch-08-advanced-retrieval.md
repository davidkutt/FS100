# Batch 8 — Advanced retrieval

> **Topics:** #21 Hybrid search · #22 Reranking · #23 Query transformation · #24 Contextual retrieval · #25 Code-aware RAG
> **Needed for:** Phase 3 (plan §0 and §13.1). Builds on Batch 1 (#1 #3 #4 #6 #7 #17), Batch 2 (#5 #8 #9 #11 #18), Batch 3 (#10 #12), Batch 4 (#19 #20), Batch 5 (#27 #28 #29) and Batch 7 (#38 #42).
> **Delivered:** 2026-10-14 · **Sketches:** `batch-08-sketches.zip` (9 modules, 75 pytest, 6 experiment scripts with outputs)
> **Verified against:** Qdrant **1.19.2** source (and 1.18.3 for comparison) plus **qdrant-edge-py 0.8.0**, which embeds Qdrant's own Rust engine from the same tree, so the RRF, DBSF, BM25 and IDF numbers below come from Qdrant code that actually ran. Also qdrant-client 1.19.1 (local mode), fastembed 0.9.0 (model catalogue and source), tree-sitter 0.25.2 / 0.26.0 with grammar wheels, tree-sitter-language-pack 1.22.1, onnxruntime 1.31.0, openinference-semantic-conventions 0.1.41, pydantic 2.14.1, Python 3.13.16. Docs: Anthropic's contextual retrieval post, the cAST paper, OpenRouter prompt caching, Qdrant's multivector tutorial.
> **Not run:** a Qdrant server binary or container (Docker Hub and GitHub release downloads were blocked; the embedded engine stands in), any embedding or reranker model (Hugging Face was blocked, so no model weights), any LLM. All latency numbers for models are **estimates** and are labelled as such.

Evidence tags used below: **[verified]** = ran it here · **[source]** = read the code at the pinned version · **[docs]** = vendor or paper claim · **[estimate]** = arithmetic with stated assumptions.

---

## 0. Why advanced retrieval, and in which order

### 0.1 Map each technique to the failure it fixes

Batch 1 (#1) split RAG failures into five stages and said: debug left to right, and measure retrieval on its own first. Every technique in this batch targets one stage. If the inspector or the eval does not show that failure, the technique has nothing to fix.

| What you see in the inspector or eval | Stage | Technique | § |
|---|---|---|---|
| An exact term (error code, CLI flag, identifier, version, port) isn't found; dense search returns "the same topic" | recall | **hybrid search**: add a lexical channel | 1 |
| The right chunk is at rank 8–20 but not in the top 5 | ranking | **reranking** | 2 |
| A follow-up ("und wie mache ich das rückgängig?") retrieves noise | query | **query rewriting** | 3 |
| The question uses other words than the docs, or asks two things at once | query | multi-query, decomposition, HyDE | 3 |
| The answer chunk says "it" or "this setting", and the referent sits in another chunk | representation | **contextual retrieval** | 4 |
| "Where is the throttle configured?", "what calls X?" | ingest + recall | **code-aware RAG** | 5 |

Phase 1 and 2 already contain cheap partial fixes. Keep them as the baselines you have to beat:

- the **heading path** in `embed_text` (#3) is a free form of contextual retrieval,
- the **domain filter** (#7) and the router (#29) narrow the corpus,
- the agentic **L2** loop (#28) lets the model write its own search queries, which is query rewriting at the cost of agent steps.

### 0.2 Recommended order

1. **Eval slices first** (§0.3). Without them, none of the later steps can be judged. Plan §13 says each technique arrives only with an eval that shows it helped.
2. **Hybrid search.** It is deterministic, needs no LLM, adds almost no query latency, and a DevOps corpus is full of exact tokens.
3. **Reranking.** The model is chosen by measured latency on your Mac (§2.4); on CPU this is the expensive step.
4. **Query rewriting for follow-ups**, only on the L0/L1 prefetch path (§3.3).
5. **Contextual retrieval.** It costs LLM tokens at ingest and changes the privacy picture (§4.6).
6. **Code-aware RAG.** This is a new corpus with its own collection, chunker and eval slice.

Add **one factor per step** (the #5 rule). Each step is compared with the one before it, on the same frozen items (§6.3). Anthropic's numbers show these techniques stack, but those are their datasets and models; your interactions may differ.

### 0.3 The eval comes first: `retrieval_v2`

`retrieval_v1` stays frozen (#17). Create `retrieval_v2.jsonl` as a **superset** with a `slice` field, and keep reporting the v1 subset separately for continuity.

| Slice | What an item looks like | Targets | Role |
|---|---|---|---|
| `exact_term` | "Was bedeutet ERR_CONNECTION_REFUSED auf Port 5432?", "what does `--dry-run=client` do?" | hybrid | target |
| `paraphrase` | the existing v1 paraphrase items (no keyword overlap) | — | **guard** for hybrid and rewriting |
| `cross_language` | German question, English source | — | **guard**: the lexical channel can't help here, and fusion must not hurt |
| `context_dependent` | the answer chunk never names the subject ("It is switched atomically" under "Qdrant alias") | contextual | target |
| `follow_up` | multi-turn; the item carries `messages` | rewriting | target |
| `ranking` | the relevant section is retrieved but low (rank 6–20) at baseline | reranking | target |
| `code` | "Wo wird das Chat-Throttle konfiguriert?", labelled by path + symbol | code RAG | target |
| unanswerable | off-topic plus near-miss items, including near-miss **tokens** (`ERR_CONNECTION_RESET` when only `REFUSED` exists) | gate | **guard**: false acceptance |

Schema additions: `slice`, optional `messages` (prior turns for follow-ups), and `relevant` entries that can be `{doc, heading}` **or** `{path, symbol}`. Labels stay at section or symbol level, so they survive re-chunking (#3, #17).

**Metrics.** Use hit@5, MRR@10 and nDCG@10 as before. Add **candidate recall@20/@50**, because a reranker can only promote what the first stage found. Add latency p50/p95 **per stage** and the false-abstention rate.

**Statistics.** Size each target slice at 12–16 items (Batch 7 power simulation: large effects are detectable, small ones are not). Compare configurations with paired per-item flips and an exact sign test, and write the decision rule before the run (`ablation.py`). Pure retrieval is deterministic, so repeats add nothing. The LLM steps (rewriting, HyDE, context generation) are not deterministic: cache their outputs per prompt bundle (#38) or repeat them 3×.

**Tune and test split.** The plan's risk table promised a separate tuning subset in Phase 3. Choose `k`, weights, `top_n` and thresholds on `tune` items only, then report on `test` items once. With about 100 items in total, a 30/70 split is a reasonable start.

### 0.4 A reality check on corpus size

Anthropic's post suggests that a knowledge base under **200,000 tokens** (about 500 pages) can go into the prompt whole, without retrieval [docs]. The Phase 1 corpus (repo docs, ADRs, your runbooks, licensed excerpts) is probably in that range. kb-agent still doesn't do that, for three reasons. Every request would send the whole corpus to the provider (#19). Each request would cost about 200k input tokens, even at cache-read prices of 0.1–0.25×. And retrieval is the skill this portfolio shows. It is still a useful **one-off upper-bound baseline** for the Phase 3 generation eval: does retrieval lose answers that long context would find? That costs real tokens, so run it once, deliberately.

---

## 1. #21 Hybrid search

### 1.1 Why

Dense retrieval matches meaning. It is weak exactly where operators are precise:

- identifiers and error codes: `ERR_CONNECTION_REFUSED`, `0x80070005`, `CrashLoopBackOff`, `kb_current`
- flags and subcommands: `--dry-run=client`, `rollout undo`
- numbers: port 5432, exit code 137, version 1.19.2
- rare or new names that the embedding model barely saw in training

Lexical retrieval (BM25) is the opposite: exact tokens, no paraphrase, and no cross-language matching. **Hybrid search runs both channels and fuses their rankings.** Expect a gain on `exact_term` and watch `paraphrase` and `cross_language` for losses.

### 1.2 How BM25 works as a sparse vector in Qdrant

A sparse vector is a list of `(index, value)` pairs. For BM25 [source, verified]:

- **index** = a hash of the token: murmur3 32-bit, read as a signed i32, then the absolute value. fastembed and Qdrant use the same rule.
- **document value** = the TF part of BM25: `tf·(k1+1) / (tf + k1·(1 − b + b·|d|/avg_len))`, with defaults `k1 = 1.2`, `b = 0.75`, `avg_len = 256`.
- **query value** = `1.0` for each unique token.
- **IDF** is computed by Qdrant at query time when the sparse vector is configured with `modifier: idf`: `idf = ln((N − df + 0.5)/(df + 0.5) + 1)` (`test_idf_formula` checks this against the engine).

The split is deliberate. TF and length are properties of one document and are known at ingest. IDF depends on the whole collection and changes as documents arrive, so the server computes it.

Two consequences:

- **`avg_len` is baked into every document weight.** The same 4-token document gets a TF weight of 1.99 for a word that appears three times at `avg_len = 256`, and 1.57 at `avg_len = 4` [verified, E1]. Measure the real average in the tokenizer's own tokens (`measure_avg_len`), store it in the profile, and **re-index if it changes much**. A 1000-character chunk has roughly 150 word tokens, so the default 256 is off for this corpus [estimate].
- **IDF scope.** IDF is collection-wide by default. Qdrant 1.19 adds `params.idf = {corpus: <filter>}`, which computes IDF over a subset, for example one language. That subset is independent of the retrieval filter [verified: scores changed, the result set didn't]. This is **not in the 1.18.3 source**. You probably don't need it, but it is one of several 1.19-only features (§1.8).

**Learned sparse models** (SPLADE, BM42, miniCOIL) learn term weights and expansions. Every one fastembed 0.9.0 offers is **English-only**: `prithivida/Splade_PP_en_v1`, `Qdrant/bm42-all-minilm-l6-v2-attentions`, and `Qdrant/minicoil-v1` (built on jina-embeddings-v2-small-en). bge-m3's multilingual sparse output still needs FlagEmbedding/PyTorch (Batch 1 finding). For German + English, **BM25 is the only option that works out of the box**, so start there.

### 1.3 Fusion: RRF, weights, DBSF

**Reciprocal Rank Fusion** looks only at ranks. Qdrant's formula is `1 / ((pos + 1)/w + k − 1)`, where `pos` is 0-based and `w` is the source weight [source: `reciprocal_rank_fusion.rs`]. **Qdrant's default `k` is 2, not the 60 from Cormack et al. (2009).** It is 2 in both the 1.18.3 and 1.19.2 sources and in qdrant-client's local mode. With `w = 1`, the top hit of a list gets 1/2.

The E2 experiment below ran on Qdrant's engine. Seven chunks, hand-made 4-dimensional dense vectors (so the dense order is controlled), and real BM25 (`lex-v1` profile). The query was `ERR_CONNECTION_REFUSED port 5432` [verified]:

| Ranking | Result (id, score) |
|---|---|
| dense | 1 (0.9988), 2 (0.9982), 3 (0.981), 4 (0.9377), 5 (0.8587) |
| lexical | 4 (10.71), 6 (5.24), 5 (1.39) — only chunks that share a token come back |
| RRF k = 2 | **4 (0.70)**, 1 (0.50), 5 (0.417), 2 (0.333), 6 (0.333), 3 (0.25) |
| RRF k = 60 | **4 (0.0325)**, 5 (0.0318), 1 (0.0167), 6 (0.0164), 2 (0.0164), 3 (0.0161) |
| RRF k = 2, weights 1 : 3 | 4 (0.95), 5 (0.667), 6 (0.60), 1 (0.50), 2 (0.333), 3 (0.25) |
| DBSF | 4 (1.127), 1 (0.624), 2 (0.622), 3 (0.574), 5 (0.573), 6 (0.481) |

Reading the table:

- **`k` decides who wins second place.** A small `k` rewards being first in *either* list: chunk 1 is dense #1 only and comes second. A large `k` rewards agreement: chunk 5 (dense #5, lexical #3) comes second. Neither is right in general; tune `k` on the `tune` split.
- **Weights** shift influence between channels. Qdrant's source comment describes 3 : 1 as roughly "three results from the first prefetch for every one from the second".
- **DBSF** (distribution-based score fusion) maps each list's scores from [mean − 3σ, mean + 3σ] (sample σ) onto [0, 1] and sums them. It uses scores, not ranks, so it depends on the shape and length of each list. A list with a single hit gives that hit 0.5.

**Fused scores are not similarities.** The maximum RRF score with two lists at `k = 2` is 1.0, and only a chunk that is #1 in both lists gets there. A `score_threshold = 0.8` on the fused query returned **nothing** [verified]. So P1's `RETRIEVAL_SCORE_THRESHOLD` must never be passed as the top-level threshold of a fusion query. It may go into the dense `Prefetch(score_threshold=…)`, but that changes its meaning; see §1.7.

**Qdrant doesn't break ties.** The source says "Does not break ties": scores go into a hash map, then through an unstable sort. With `k = 2`, ties are common, because rank *r* in list A alone scores exactly the same as rank *r* in list B alone. In E2, two chunks tied at 0.5 came back in either order across fresh processes: **11 of 20 one way, 9 of 20 the other** [verified]. The effects are flaky evals (hit@1 flips between identical runs) and citation numbers that change between identical requests. Break ties yourself (§1.6) or let a reranker reorder afterwards.

**Prefetch limits are candidate depth.** A chunk below a channel's `limit` gets nothing from that channel. The lexical channel only returns chunks that share at least one token with the query; in E2 that was 3 of 7.

### 1.4 A lexical profile for German + English DevOps text

E1 sent technical strings through Qdrant's own BM25 tokenizer (qdrant-edge-py 0.8.0) and decoded the hashed indices back to tokens [verified]:

| Input | Default config (English) | `language: german` | No stemmer, no stopwords (`lex-v1`) | `multilingual` tokenizer + German |
|---|---|---|---|---|
| `ERR_CONNECTION_REFUSED on port 5432` | err, connect, refus, port, 5432 | err, connection, refused, on, port, 5432 | err, connection, refused, on, port, 5432 | err, connection, refused, on, port — **5432 dropped** |
| `it is not ready` | **readi** (it, is, not removed) | it, is, not, ready | it, is, not, ready | it, is, not, ready |
| `OOMKilled exit code 137` | oomkil, exit, code, 137 | oomkilled, exit, **cod**, 137 | oomkilled, exit, code, 137 | oomkilled, exit, cod — **137 dropped** |
| `max_tokens exceeded` | max, token, exceed | max, **tok**, exceeded | max, tokens, exceeded | max, tok, exceeded |
| `Datenbankverbindung abgelehnt` | datenbankverbindung, abgelehnt | **datenbankverbind**, abgelehnt | datenbankverbindung, abgelehnt | datenbankverbind, abgelehnt |
| `Deployment zurückrollen` | deploy, zurückrollen | deployment, **zuruckroll** | deployment, zurückrollen | deployment, zuruckroll |

What follows from this:

- **The English default throws away "not"** (and "in", "it"). In SRE text, "pod not ready" and "pod ready" are different questions.
- Stemming is consistent between ingest and query, so it still matches. But an English stemmer applied to German, or a German one to English ("tokens" → "tok", "code" → "cod"), mostly adds collisions.
- The **`word` tokenizer splits on every non-alphanumeric character**, including `_`, `-` and `/`. An identifier becomes a short phrase, which still matches but loses exactness: any chunk that contains "connection" and "refused" scores partially.
- The **`multilingual` tokenizer dropped bare numbers** (5432, 137, 3) in this probe. For ports and exit codes that rules it out.
- **No tokenizer splits camelCase or German compounds.** A query for "Verbindung" doesn't match "Datenbankverbindung". Dense search covers compounds. For code identifiers, `lexical.py` appends the parts: `getUserById` adds "get User By Id".

**Recommendation: `lex-v1`.** Use the `word` tokenizer, lowercase, **no stemmer** (`{"type": "none"}`), **no stopwords**, `max_token_len` 64, a measured `avg_len`, and identifier expansion. The reasoning: the lexical channel is there for exact tokens, and meaning is the dense channel's job. Evaluate two alternatives on `exact_term` + `paraphrase`: (b) one stemmed profile per language (`lex_de` and `lex_en` sparse vectors, query both or route by language), and (c) the English default.

The explicit `{"type": "none"}` stemmer exists in the 1.19.2 source but **not in 1.18.3** [source]. On 1.18 the only way was the `language: "none"` hack, which 1.19 now logs as deprecated.

### 1.5 Where BM25 gets computed: three pipelines that disagree

| Pipeline | Tokenizer | Notes |
|---|---|---|
| **Qdrant server-side inference**: `models.Document(text=…, model="qdrant/bm25", options={…})` | Rust `word` tokenizer, splits `_` | Server ≥ 1.15.3. qdrant-client passes the `Document` through to remote servers unchanged [source]. No model files needed. |
| **fastembed** `SparseTextEmbedding("Qdrant/bm25")` | Python regex `\w`, **keeps `_`** | `ERR_CONNECTION_REFUSED` → `err_connection_refus` [verified]. Downloads stopword files from Hugging Face. |
| **qdrant-client local mode** (`:memory:` or a path) | **fastembed's**, not the server's | Embeds `Document(bm25)` in the client [source]. Here it tried the Hugging Face download, retried with sleeps for about 37 s, then failed [verified]. |

The hash function is the same in all three; the tokens are not. A chunk indexed by one pipeline and queried by another **silently misses every identifier with an underscore**. Rules:

- **Pick one pipeline.** Recommended: server-side inference for both ingest and query. There are no model files, and there is one implementation.
- **BM25 tests run on testcontainers Qdrant** (or qdrant-edge-py), **never on local mode**. That is the same rule Batch 1 set for filters.
- Store the lexical profile's **fingerprint** in the index manifest (#9), and query with the profile from the manifest.

### 1.6 Server-side or client-side fusion?

- **Server-side:** one `query_points(prefetch=[dense, lexical], query=RrfQuery(...))`. One round trip, but you only get the fused score back.
- **Client-side:** `query_batch_points([dense, lexical])` (still one round trip), then fuse in Python (`fusion.py`). It reproduces Qdrant's numbers exactly; `test_rrf_parity_with_qdrant` compares them with the engine at `k = 2` and `k = 60`.

**Recommendation for kb-agent: client-side.**

1. The inspector can show each channel's rank and score, which is the only way to see *why* a hit won.
2. The abstention gate needs the raw dense cosine (§1.7).
3. Ties are broken deterministically: best single rank, then dense first, then id.
4. Traces get one RETRIEVER span per channel.
5. Ablations become a config switch.

The cost is a little Python work on 2 × 20 hits, which is nothing at this corpus size. Move to server-side fusion only if latency ever demands it.

### 1.7 Abstention with hybrid search

The P1 gate is "top-1 dense cosine ≥ calibrated threshold" (#11). It does not translate to fused or BM25 scores. Fused scores are rank arithmetic. BM25 scores grow with IDF and query length, so they aren't comparable across queries.

`gate.py` does this:

1. **Keep the dense gate**, calibrated per model and stored in the manifest.
2. **Add a narrow rescue.** If the query contains exact tokens (identifiers with digits, underscores or camelCase; flags; quoted strings) and a top-3 lexical hit contains **all** of them, pass. Those are the questions where dense search is weakest and a literal match is strong evidence.
3. **Filter per hit.** Drop hits below a lower dense floor unless they were rescued. A lexical-only hit has no dense score, so it stays only if rescued.

Recalibrate with the new slices: false abstention must include `exact_term` items, and false acceptance must include near-miss *tokens*. Requiring **all** literal tokens is what stops `ERR_CONNECTION_RESET` from being rescued by a chunk about `REFUSED` (`test_gate_abstains_without_dense_or_exact_match`).

### 1.8 Plan mapping

- **Collection schema** (a new build behind the alias, #9): named dense vector `dense`, plus a named sparse vector `lex` with `modifier: idf`. Payload is unchanged apart from a `lex_profile` field.
- **Index manifest** (#9) adds: the lexical profile fingerprint and options, the measured `avg_len`, `fusion: {method, k, weights}`, and `gate: {dense_threshold, floor, rescue}`.
- **Qdrant pin.** The plan pins 1.18.x. Phase 3 hybrid wants **1.19.x**: the explicit no-stemmer and corpus-scoped IDF both exist only there [source], with qdrant-client 1.19.1. Decide this at the start of Phase 3.
- **D9 finding (bge-m3 sparse not available via fastembed):** resolved for Phase 3 as "server-side BM25 first, learned sparse only if the eval shows BM25 isn't enough."
- **`/v1/search`** gets `mode: dense | lexical | hybrid` and returns per-channel ranks and scores. The inspector shows two columns plus the fused order.
- **Eval:** `kb-eval retrieval --config hybrid-rrf-k2`, with the full config in the run record (#17).
- **Tracing:** RETRIEVER `dense` and RETRIEVER `lexical` spans, plus a CHAIN span `fusion` with `kb.fusion.method/k/weights`.

### 1.9 Pitfalls

- Passing the cosine threshold as `score_threshold` on a fusion query. It returns nothing, or with other values, nonsense.
- Assuming RRF `k = 60` because the paper says so. Qdrant's default is 2. Write the value down in the manifest.
- Testing BM25 in qdrant-client local mode. That is a different tokenizer, and it needs network access to Hugging Face.
- Keeping `avg_len = 256` and then "fixing" it later without re-indexing. Old and new documents end up with different length normalisation.
- Using English stopwords on SRE text: "not" disappears.
- The `multilingual` tokenizer on a corpus full of port numbers and exit codes.
- Expecting the lexical channel to help cross-language questions. It can't; watch that guard slice.
- Treating "hybrid helped overall" as success while `paraphrase` lost items. Per-slice reports and guard rules exist for this.
- Assuming results are deterministic with server-side RRF. Ties shuffle between processes.

### 1.10 Self-check

1. Why does Qdrant compute IDF at query time instead of storing it in the document's sparse vector?
2. What is Qdrant's default RRF `k`, and how does a small `k` change which chunks win compared with `k = 60`? Use the E2 table.
3. Why does `score_threshold = 0.8` on an RRF query return nothing, and where may the calibrated cosine threshold still go?
4. Name three things the default English BM25 config does to the text "it is not ready" or to German words that hurt a DE/EN SRE corpus.
5. You index with fastembed's `Bm25` and query with `models.Document(model="qdrant/bm25")` against a server. Which queries silently fail, and why?
6. Why does `avg_len` force a re-index when it changes?
7. Give two reasons kb-agent fuses client-side.
8. How does the hybrid gate decide on "Was bedeutet ERR_CONNECTION_RESET?" when the corpus only covers `ERR_CONNECTION_REFUSED`?

---
## 2. #22 Reranking

### 2.1 Why

A bi-encoder (#4) compresses the query and each chunk into vectors **separately**: they never see each other. A **cross-encoder** reads `(query, passage)` together, with full attention across both, and outputs one relevance score. That judges relevance much better, but it has to run once per pair at query time, so it only runs on a short candidate list.

Reranking fixes **ranking** failures, where the right chunk sits at rank 8–20. It also makes the "which k chunks go into the prompt" decision sharper: fewer, better chunks mean fewer tokens and better focus (#12). It **cannot fix recall**: if the first stage didn't retrieve a chunk, nothing promotes it. So measure **candidate recall@20/@50** before blaming or crediting the reranker.

### 2.2 Where it sits

```
query → hybrid retrieval (N candidates) → rerank → top k → (gate) → number sources → prompt
```

- **N** comes from the candidate-recall curve on the `tune` split. On a corpus this size, N = 20–30 is usually enough. Anthropic's large setup went from 150 to 20 [docs]. Every extra candidate costs latency (§2.4).
- **Number sources after reranking.** The #10 rule ("number after filtering, best first, never renumber") now applies to the reranked order.
- **The reranker changes what the gate sees.** See §2.5.

### 2.3 Options

| Option | Languages | Size (fastembed) | Licence | Query-time cost | Note |
|---|---|---|---|---|---|
| `Xenova/ms-marco-MiniLM-L-6-v2` / `-L-12-v2` | English | 0.08 / 0.12 GB | Apache-2.0 | low | hurts German items |
| `BAAI/bge-reranker-base` | English + Chinese | 1.04 GB | MIT | medium | not built for German |
| `BAAI/bge-reranker-v2-m3` | **multilingual** | 2.27 GB fp32 · **0.57 GB int8** | Apache-2.0 | **high** (XLM-R large) | the obvious DE/EN candidate |
| `jinaai/jina-reranker-v2-base-multilingual` | multilingual | 1.11 GB | **CC-BY-NC-4.0** | medium | non-commercial licence: avoid in a public MIT repo |
| `jinaai/jina-reranker-v1-tiny-en` / `-turbo-en` | English | 0.13 / 0.15 GB | Apache-2.0 | low | 8K context |
| **Late interaction** `lightonai/mLateOn` | **multilingual + code** | 1.25 GB | Apache-2.0 | **low** (query encoding only) | 128-dim vector per token; §2.6 |
| Hosted rerank API (Cohere, Voyage, Jina) | varies | — | — | network call | another third party sees your chunks (#19); cost per call |
| LLM as reranker (via OpenRouter) | any | — | — | an extra LLM call | tokens ∝ N × chunk size; nondeterministic. Better as an **eval-time oracle** than at runtime |

All sizes and licences come from fastembed 0.9.0's model catalogue [verified]. The corpus is German + English with cross-language questions, so **an English-only reranker will move German items down**. The `cross_language` guard slice catches that.

### 2.4 What it costs on a CPU

A transformer forward pass costs about **2 FLOPs per weight per token**. Embedding tables are lookups and nearly free, so count the non-embedding parameters [estimate]:

| Model | Non-embedding params | 10 × 150 tokens | 20 × 256 tokens | 30 × 400 tokens |
|---|---|---|---|---|
| ms-marco-MiniLM-L-6-v2 | 10.6 M | 0.03 TFLOP | 0.11 TFLOP | 0.25 TFLOP |
| bge-reranker-base (XLM-R base) | 85 M | 0.25 | 0.87 | 2.04 |
| bge-reranker-v2-m3 (XLM-R large) | 302 M | 0.91 | **3.09** | 7.25 |

The 2-vCPU sandbox reached **203–230 GFLOP/s** on large fp32 MatMuls in onnxruntime 1.31 [verified, `bench_matmul.py`]. A whole model runs below MatMul peak. Assuming ~130 GFLOP/s there, and a hopeful 4× that (~520 GFLOP/s) for an M1 [estimate, unmeasured]:

| Model, 20 candidates × 256 tokens | Sandbox (~130 GFLOP/s) | Optimistic M1 (~520 GFLOP/s) |
|---|---|---|
| MiniLM-L-6 | ~0.8 s | ~0.2 s |
| bge-reranker-base | ~6.7 s | ~1.7 s |
| bge-reranker-v2-m3 fp32 | **~24 s** | **~6 s** |

**Conclusion:** a multilingual cross-encoder over 20 full chunks is not interactive on a laptop CPU. int8 typically helps around 2×, but that is not measured here. You can rerank fewer candidates (N = 10), clip passages to ~600 characters (`clip_passage`), use **late interaction** (§2.6), or rerank only in offline evals until a GPU arrives (Phase 6 hardware or Azure).

**Measure it on the Mac with `experiments/bench_rerank.py`** before deciding, and write the latency budget into the decision rule. An example: adopt only if p95 rerank time is ≤ 800 ms and the `ranking` slice is better.

Two fastembed details that affect latency [source]:

- Truncation follows the tokenizer config, and some rerankers allow long inputs. So **clip passages yourself**.
- `rerank(..., batch_size=64)` pads each batch to its longest pair. One long chunk slows the whole batch down.

### 2.5 Scores and the gate after reranking

- fastembed's `TextCrossEncoder.rerank` yields **raw logits**: `output[:, 0]`, with no sigmoid applied [source]. Their range depends on the model. A sigmoid is fine for display, but it is **not a calibrated probability**.
- A cross-encoder judges answerability better than cosine similarity. #11 said similarity ≠ answerability, and that gap is what near-misses fall through. So an optional **`min_logit` gate** after reranking can catch near-misses the dense gate lets through. Calibrate it per reranker model on the unanswerable items, exactly like #11, and store it in the manifest. If reranking empties the list, take the abstain path (`test_rerank_gate_on_logits_can_empty_the_list`).
- **Ties keep first-stage order** (stable sort), so equal logits never shuffle citations.

### 2.6 Late interaction (ColBERT-style) in Qdrant

A late-interaction model stores **one vector per token** for each chunk. At query time it encodes only the query, then scores each candidate with **MaxSim**: for each query token, take its best match among the chunk's tokens, and sum those maxima. Qdrant supports this with a multivector:

- Vector config: `multivector_config: {comparator: max_sim}` plus `hnsw_config: {m: 0}`. Qdrant's tutorial turns HNSW off for a vector that is only used to rescore prefetched candidates, which saves RAM and speeds up uploads [docs].
- Query: `prefetch=[dense, lexical]` followed by a rescoring query on the multivector, `using="late"`.

Costs [estimate]: 128 dimensions × ~300 tokens per chunk × 4 bytes ≈ **150 KB per chunk** in fp32 (75 KB in float16). A single 1024-dimensional dense vector is 4 KB. For 2,000 chunks that is about **300 MB fp32 / 150 MB fp16**. At ingest, every chunk goes through one more model forward pass. At query time you encode one short query plus a cheap MaxSim over N candidates, which fits a CPU. Quality against a cross-encoder has to be measured on the `ranking` slice.

### 2.7 Tracing

OpenInference has a **RERANKER** span kind with `reranker.query`, `reranker.model_name`, `reranker.top_k`, `reranker.input_documents` and `reranker.output_documents`. Each document carries `document.id`, `document.content` and `document.score` [verified, semconv 0.1.41]. Add `kb.rerank.moved_into_top` (how many results came from below the cut) and the latency.

You control what goes on this manual span, so record ids and scores, and add content only if the trace retention and masking rules from #18/#19 allow it.

### 2.8 Plan mapping

- A new `rag/rerank.py` behind a `Reranker` protocol. The knobs are `RERANK_MODEL`, `RERANK_CANDIDATES`, `RERANK_TOP_K`, `RERANK_MAX_CHARS` and `RERANK_MIN_LOGIT`, and they live in the model profile and index manifest, not in loose env vars.
- **Docker image:** bake the reranker in alongside the embedding model (M1.6). That adds 0.6–2.3 GB to the image. `/readyz` checks that the reranker is loaded.
- **RAM** (A1, a 16 GB M1): Keycloak, Qdrant, Phoenix, e5 and a 2.3 GB fp32 reranker is tight. Prefer int8 or late interaction.
- **CI:** `FakeScorer` only, never a real model (D20).
- **Inspector:** show first-stage rank → reranked rank for each hit.
- **ADR-0011** (the Phase 3 retrieval pipeline) records the bench numbers and the decision.

### 2.9 Pitfalls

- Crediting the reranker for a recall problem, or blaming it for one. Check candidate recall first.
- Treating logits as probabilities, or reusing the cosine threshold on them.
- Trusting the tokenizer's truncation to keep latency bounded.
- An English-only reranker on a German/English corpus.
- A non-commercial licence (`jina-reranker-v2`, `jina-colbert-v2`) in a public MIT portfolio repo.
- Numbering sources before reranking, so the citation numbers no longer match the prompt order.
- Choosing a model from leaderboards without measuring p95 latency on the target machine.

### 2.10 Self-check

1. Why is a cross-encoder more accurate than a bi-encoder, and why can't it search the whole corpus?
2. Which metric tells you whether the reranker even has a chance on an item?
3. Estimate the FLOPs for reranking 20 × 256-token pairs with an XLM-R-large reranker. What does that mean on a laptop CPU?
4. What does fastembed's `rerank` return, and how should a gate on it be calibrated?
5. How does late interaction move cost from query time to ingest time, and what does it cost in storage?
6. Name two licence or language traps in the fastembed reranker list.

---

## 3. #23 Query transformation (rewriting, multi-query, HyDE)

### 3.1 Why

There are three gaps between what users type and what the docs say:

- **Follow-ups are incomplete.** "Und wie mache ich das rückgängig?" means nothing on its own. P1 retrieves with the last user message only (#12), so follow-ups retrieve badly. That was an open question in DONE.md.
- **Vocabulary mismatch.** The user's words aren't the document's words.
- **Multi-aspect questions.** "How do I rotate the Keycloak secret and redeploy the API?" mixes two sections.

### 3.2 Techniques

| Technique | What it does | Fixes | Cost | Main risk |
|---|---|---|---|---|
| **Rewrite / condense** | Turns history + last message into one standalone query | follow-ups | 1 small LLM call | drops a literal token, changes the meaning |
| **Multi-query** | 2–3 paraphrases, each searched, fused with RRF | vocabulary mismatch | 1 call + n searches | topic drift adds noise |
| **Decomposition** | Sub-questions for multi-hop or multi-aspect questions | two topics in one question | 1 call + n searches | over-splitting simple questions |
| **HyDE** | The LLM writes a hypothetical answer passage, which is embedded and searched | short or abstract questions | 1 call (longer output) | hallucinated specifics pull the wrong docs |
| Step-back | Asks a more general question first | very specific questions | 1 call | drifts too general |

### 3.3 Relationship to agentic RAG (#28): where rewriting actually belongs

In **L2** the agent writes `search_kb.query` itself, so rewriting, decomposition and multi-query come for free, paid for in agent steps. **L1's prefetch** and plain **L0** retrieve with the raw last message *before* the model runs, and that is where a rewrite helps. So in Phase 3:

- use `QueryPlan` for **L0/L1 prefetch only**, and
- don't stack it on L2, where you would rewrite twice and pay twice.

### 3.4 Design: one structured call (`query_plan.py`)

- **One call** returns a `QueryPlan`: `rationale`, `standalone_query`, `language`, `needs_retrieval`, `sub_queries` (≤ 3, nullable) and `hyde_passage` (nullable). It uses the strict-schema dialect from #27: every field required, optional means nullable, `extra="forbid"`.
- The model is the **router profile**: cheap, fast, low reasoning effort (#27 per-role profiles). The prompt is its own versioned bundle, `rewrite@v1` (#38).
- **Skip when there is nothing to transform.** With `mode="followups"`, the first turn never calls the LLM, so most turns add no time to first token.
- **Fall back to the raw question.** Invalid JSON, a validation error or a timeout returns the original question. Query transformation is an optimisation and must never be able to break retrieval. Give it a tight deadline, around 1.5 s.
- **Keep literal tokens.** Tokens the user typed literally (codes, flags, identifiers) get re-appended to the **lexical** query if the rewrite lost them (`test_literal_tokens_survive_a_bad_rewrite`).
- **The harness owns retrieval policy.** `top_k`, filters, ACL and alias are never plan fields; `extra="forbid"` rejects a plan that tries to set `top_k` (the #26/#28 rule).
- **History is data.** It is wrapped in tags, stripped of `[n]` markers and truncated. Injected text in the history can at worst change the search text. That is low impact, but it is logged.
- `needs_retrieval=false` is **ignored by default**. L0/L1 always retrieve, and "no retrieval" decisions belong to the router or the agent.

**Hide the latency: race raw and rewritten.** Start the raw-question search immediately and run the rewrite in parallel. Then search the rewritten query and fuse both lists with RRF. Retrieval time becomes `max(rewrite, raw search) + one more search`, and the raw results are always in the mix, which limits the damage of a bad rewrite.

### 3.5 Cost and latency

The rewrite input is history (≤ 3 pairs, ≤ 600 characters each) plus instructions, about 600–900 tokens, with about 80 tokens of output. That is a negligible cost. The latency is not negligible: time to first token grows by one small-model call, roughly 0.5–2 s depending on model and provider [estimate], and the `sources` event arrives later. Restrict rewriting to follow-ups and race it as above.

### 3.6 HyDE in detail

- The hypothetical passage is a fake **document**. Embed it with the **`passage: ` prefix** for E5-style asymmetric models. The HyDE paper encodes hypothetical documents with the document encoder (Gao et al., 2022). Keep the prefix in the model profile (#4).
- Use it for the **dense channel only**. Terms the LLM invents would pollute BM25, so the lexical channel keeps the user's real query.
- **Fuse, don't replace.** Combine HyDE results with raw-query results via RRF.
- Where it fails: your own runbooks and configs. The model has never seen them, so it writes generic or invented text, for example a wrong flag name. It can also drift language, answering in English to a German question. For kb-agent it is **low priority**; evaluate it on `paraphrase` only, behind `allow_hyde`.

### 3.7 Eval

- `follow_up` needs multi-turn items (`messages`) in `retrieval_v2`; the single-turn v1 set cannot measure it (#12 finding).
- **This answers the open question from DONE.md** ("previous + current user message as the query?"). Compare three arms on `follow_up`: raw last message, **concatenation of the previous and current user message** (no LLM, deterministic), and the LLM rewrite. Guard: single-turn slices must be unchanged, because the rewrite is skipped there.
- **Component checks** on the rewriter: are literal tokens preserved, are entities resolved, is the language kept? These are deterministic assertions on its output.
- Rewrites are nondeterministic. Cache them per (bundle, model, history hash) to keep retrieval evals reproducible, or repeat 3× (#42), and record the bundle in the run.

### 3.8 Plan mapping

- `rag/query_plan.py`, prompt `prompts/rewrite/v1.txt` (locked, #38), settings `QUERY_TRANSFORM_MODE=off|followups|always` and `QUERY_TRANSFORM_DEADLINE_MS`, model profile `router`.
- Trace: a CHAIN span `query_plan` with an LLM child, plus `kb.query.source = raw|llm|llm_failed` and `kb.query.n_variants`.
- SSE: no protocol change is needed. `sources` just arrives later.
- `retrieval_v2` schema change for multi-turn items.

### 3.9 Pitfalls

- Rewriting every turn: you pay latency where nothing needed fixing.
- Letting the rewrite drop `--dry-run=client` or an error code.
- A rewrite that can set filters or `top_k`, which turns injection in the history into a retrieval-policy change.
- HyDE through the lexical channel, or HyDE embedded with the query prefix.
- Stacking rewriting on top of the L2 agent.
- No fallback, so a JSON hiccup becomes a failed answer.

### 3.10 Self-check

1. Why does query rewriting help L1 but not L2?
2. What three things does `plan_queries` do when the LLM returns invalid JSON, an extra `top_k` field, or a rewrite that drops `ERR_CONNECTION_REFUSED`?
3. Which E5 prefix does a HyDE passage get, and why?
4. How can you hide most of the rewrite latency?
5. Describe the three-arm experiment that answers "previous + current user message as the query?".

---
## 4. #24 Contextual retrieval

### 4.1 Why

Chunking cuts referents away from the text that refers to them. Lines like "It is switched atomically.", "Set it to `false` before upgrading." or "Diese Einstellung gilt nur für …" lose their subject. Neither the embedding nor BM25 of such a chunk knows that "it" means the Qdrant alias `kb_current`. Contextual retrieval has an LLM **write the missing context** for each chunk, and that context is added to the **indexed** text.

### 4.2 What Anthropic reported (September 2024) [docs]

- The metric is **1 − recall@20**: the share of relevant chunks missing from the top 20, averaged over their datasets.
- Baseline 5.7% → contextual embeddings **3.7% (−35%)** → plus contextual BM25 **2.9% (−49%)** → plus reranking **1.9% (−67%)**. The reranking step took the top 150 candidates down to 20.
- The context is **50–100 tokens** per chunk.
- One-time cost: about **$1.02 per million document tokens** with prompt caching. Their assumptions were 800-token chunks, 8k-token documents, 50 tokens of instructions and 100 tokens of context per chunk.

These are their datasets, embedding models and reranker. They tell you the technique is worth testing, not what it will give you.

### 4.3 You already have the cheap version

P1 builds `embed_text` as heading path + chunk (#3). For Markdown runbooks with good headings, "Rollback › Qdrant alias" already supplies most referents. So **the baseline for contextual retrieval is the heading-path text, not the bare chunk**. Expect gains where headings are weak:

- PDFs, because pypdf gives no heading structure (#2)
- long sections
- prose full of pronouns
- tables

`contextualize(..., generate=None)` returns exactly that baseline, which makes the comparison a one-flag switch.

### 4.4 Design (`contextual.py`)

- **Prompt layout for caching:** instructions + document **first**, which is a stable prefix shared by all of the document's chunks, and the chunk **last**. Ask for 1–2 sentences, at most 60 words, in the document's language. OpenRouter caches prefixes automatically for OpenAI, DeepSeek, Gemini 2.5+, Grok and others; Anthropic and Alibaba need `cache_control`. Minimum prefix sizes vary (often 1,024 tokens), so short documents aren't cached, but they are cheap anyway [docs].
- **Window policy:** the whole document if it fits under `CONTEXT_WINDOW_CHARS`. Otherwise use the **outline** (all headings) plus the chunk's own section. This bounds cost and context size for long PDFs (§4.5).
- **Where the context goes:** a separate payload field (`context`, `context_key`, `context_generated: true`), then `embed_text = context + heading path + chunk` and the same for the lexical text. **The displayed `text` stays the author's words** (#3's split between display and index text).
- **Does the answer model see the context?** Not by default. It sees the full chunk with its heading path, and citations must point to the author's text, not to generated text. The inspector shows the context.
- **Cache key:** `sha256(doc_sha256, chunk_sha256, prompt bundle, model + pinned provider, window policy)`. Re-ingesting the same bytes makes **no** LLM call (idempotent, #8). A prompt, model or window change regenerates exactly the affected contexts (`test_cache_hit_on_reingest_and_miss_on_prompt_or_model_change`). Keep the cache in Postgres, so a re-index with a new embedding model (#9) reuses every context.
- **Nondeterminism:** without a cache, every rebuild generates different contexts, so different vectors, so retrieval evals shift with the same config. The cache plus the bundle id in the manifest keeps builds reproducible.
- **Failures don't block ingest.** The document goes `ready` with heading-path text. A background job adds contexts and re-upserts the same point ids, which is safe because UUIDv5 ids are stable (#8).

### 4.5 Cost [estimate]

Each chunk is one call, and each call sends the window plus the chunk. With the whole document as the window, the tokens sent grow with the **square** of document length (number of chunks × document length). Using `estimate_cost` with 250-token chunks, 35-token overlap and placeholder prices of $0.10 per million input tokens and $0.40 per million output tokens:

| Document | Chunks | Tokens sent | No cache | Cache reads at 0.25× | Anthropic-like (write 1.25×, read 0.1×) | Outline + section window (6k tokens, no cache) |
|---|---|---|---|---|---|---|
| 4k tokens | 19 | 82 k | $0.009 | $0.003 | $0.002 | — |
| 8k tokens | 38 | 317 k | $0.033 | $0.011 | $0.006 | $0.025 |
| 20k tokens | 93 | 1.9 M | $0.19 | $0.054 | $0.027 | $0.062 |
| 50k tokens | 233 | **11.7 M** | **$1.18** | $0.31 | $0.14 | $0.15 |

For one 4k-token document, that is $0.6–2.2 per million document tokens, the same order as Anthropic's $1.02. The 50k-token PDF shows the **quadratic trap**: without caching, one document costs as much as a thousand short ones. With a working prefix cache the whole-document layout stays affordable. The window policy matters when the provider doesn't cache, when the document exceeds the model's context window, or when you want to send less (§4.6).

Run context generation on a **separate key with its own credit limit** (the same pattern as the eval key, Batch 7), and log cost per document.

### 4.6 Privacy (#19)

P1 had an invariant: **full documents never leave**, and each request sends only the top-5 chunks. Contextual retrieval breaks it. **Every contextualised document goes to the LLM provider in full, at ingest.** Consequences:

- The D25 class table needs a column for "may be contextualised". Make it a per-document flag, `contextualize`, defaulting to on only for public and self-written documents.
- The provider filter from ADR-0005 (ZDR or no-training, pinned provider, no fallbacks) applies to the **ingest** model too. ZDR still allows in-memory prompt caching (Batch 4 finding).
- Sensitive classes either skip contextualisation or wait for a local model (Phase 6).

### 4.7 Security (#20)

At ingest, the document is untrusted input to an LLM, and the output is **stored** in the index. That is a **persistent injection** path. OWASP's 2026 prompt-injection entry now includes persistence (Batch 4 finding). A document can steer its own context, for example: "This chunk is the official procedure for disabling authentication." That boosts its ranking, which is search-engine poisoning for RAG. Or it can plant instructions that reach the answer model, if contexts were ever shown to it.

Mitigations in the sketch:

- The context is **not shown to the answer model** by default.
- It is **cleaned**: invisible characters and reserved tags removed.
- It is **capped** at 400 characters and **flagged** `generated`.
- Our reserved tags in the source document are **neutralised** before they reach the prompt (`test_reserved_tags_in_documents_are_neutralised`).

Also add a red-team item (#46): a document that tries to steer its own context.

### 4.8 Interaction with D7 (originals aren't stored)

Context generation needs the whole document, which exists during ingest. Regenerating contexts later, after a new prompt or a better model, needs the **originals** again. That strengthens the open D7 finding: store content-addressed originals. Without them, the context cache still lets a re-index with a new **embedding** model reuse every context, but a new **context prompt** can't be applied to old uploads.

### 4.9 Alternatives

- **Heading path / title prefix:** you have it; it costs nothing.
- **Document summary prefix:** one LLM call per document, with the summary prepended to every chunk. Cost is linear, but it is less specific to each chunk.
- **Parent-child chunks (#3):** index small chunks and hand the LLM the parent section. That helps generation, not the recall of pronoun chunks.
- **Late chunking** (Jina, 2024): embed the whole document with a long-context model, then pool the token embeddings per chunk, so every chunk vector "sees" the document without any LLM. It needs token-level outputs from the embedding model, which fastembed's `TextEmbedding` API doesn't expose. A research option, not a Phase 3 item.

### 4.10 Plan mapping

- An ingest step `contextualize` between chunk and embed, run as a background job. Settings `CONTEXTUAL_MODE=off|on` and `CONTEXT_WINDOW_CHARS`, model profile `ingest`, prompt bundle `context@v1`.
- A Postgres table `chunk_contexts(key PK, context, model, bundle, created_at)`, payload fields `context`, `context_key` and `context_generated`, and the bundle in the index manifest.
- Trace: ingest spans with LLM children; cost goes into the per-document ingest log line.
- Eval: on `context_dependent`, compare the heading-path baseline with contextual, first dense-only and then hybrid. Guard: all other slices.

### 4.11 Pitfalls

- Comparing against bare chunks instead of the heading-path baseline. That overstates the gain.
- Whole-document windows for 50-page PDFs without caching.
- No cache, so every rebuild costs tokens and produces different vectors.
- Showing generated context to the answer model, or citing it.
- Forgetting that contextualisation sends whole documents to the provider.
- Not flagging generated text in the payload.

### 4.12 Self-check

1. What baseline must contextual retrieval beat in kb-agent, and why?
2. Why does the prompt put the document before the chunk?
3. Which inputs belong in the cache key, and what happens on re-ingest of the same file?
4. Why does the cost grow quadratically with document length, and what two things bound it?
5. Which P1 privacy invariant breaks, and what changes in D25 and ADR-0005?
6. Describe a stored-injection attack through contextual retrieval and two mitigations.

---

## 5. #25 Code-aware RAG

### 5.1 Why

The assistant is for the "Dev of the future". It has to answer questions like these from the repo itself:

- "Where is the chat throttle configured?"
- "What happens when an upload is a duplicate?"
- "Which endpoint deletes vectors?"

Prose chunkers cut code mid-function. Embeddings trained mostly on prose underweight identifiers. Code answers need **file and line citations**. And code changes every day, so indexing must be **incremental**.

### 5.2 Parsing with tree-sitter: verified facts

- **Grammar packaging.** There are per-language wheels: `tree-sitter-python` 0.25.0, `-typescript` 0.23.2, `-yaml` 0.7.2, `-bash` 0.25.1, `-hcl` 1.2.0, `-dockerfile` 0.2.0, `-json` 0.24.8. They ship compiled grammars inside the wheel. `tree-sitter-language-pack` 1.22.1 instead **downloads grammars at runtime** from `github.com/xberg-io/tree-sitter-language-pack/releases` into `~/.cache/tree-sitter-language-pack/v1.22.1/libs` (40 MB for 10 languages here) [verified]. In a non-root container with a read-only filesystem or restricted egress, the first parse fails. **Use the wheels**, or prefetch at image build with `TREE_SITTER_LANGUAGE_PACK_CACHE_DIR`.
- **Pin `tree-sitter==0.25.2`.** py-tree-sitter **0.26.0 segfaulted in 5 of 5 runs** when reading `start_point`/`end_point` of a multi-line node 3,000 times and then compiling a regex; 0.25.2 crashed in 0 of 5 (Python 3.13.16, x86_64) [verified, `tree_sitter_crash_probe.py`]. The first symptom was a crash inside `re` in unrelated code: memory corruption, not an exception. `test_tree_sitter_point_access_does_not_crash` guards the pin.
- **Offsets are bytes.** After a comment containing "Prüft" and an emoji, slicing the Python string with `start_byte` cut "def " off the function (202 characters vs 207 bytes). Slice the UTF-8 bytes, then decode [verified].
- **Decorators and comments are siblings.** In a TypeScript class body, `@Delete(':id')`, `@Roles('editor')` and `// Löscht ein Dokument` are **siblings before** `method_definition`. The class decorator `@Controller('documents')` is a child of `export_statement`. Python's `decorated_definition` wraps decorators, but a leading comment is still a sibling [verified]. A chunker that takes "the method node" **drops the routing and RBAC lines**, which are exactly what the questions are about. Attach preceding comments and decorators.
- **Error recovery.** A file with a syntax error still produces a tree with `has_error = True`. Chunk it and flag it.
- **What tree-sitter doesn't do:** types, import resolution, cross-file references. "Find usages" from tree-sitter tag queries works on names only. Exact references need an LSP or SCIP indexer, which is a Phase 6 option.

### 5.3 Chunking: cAST-style split-then-merge

**cAST** (Zhang et al., 2025; EMNLP 2025 Findings) parses with tree-sitter and greedily **merges adjacent siblings** while they fit the budget, **recursing into nodes** that are too big. Size is counted in **non-whitespace characters**, so indentation style doesn't move boundaries. They report +4.3 points Recall@5 on RepoEval and +2.67 points Pass@1 on SWE-bench over line-based chunking [docs].

`code_chunker.py` adds:

- a small **signature chunk** (decorators + class line) when it splits a class,
- the **parent qualifier** (`DocumentsController.remove`) and a header `path › parent › symbols` for the embedded and lexical text,
- attached **leading comments and decorators**,
- a **line-split fallback** for huge leaves, such as a 400-line literal.

**Budget:** start at 1,000–1,500 non-whitespace characters and **measure tokens per chunk** with the method from #5. If e5 embeds code, keep header + chunk under **512 tokens**, because e5 truncates silently there (#4); code tokenises densely, at roughly 3–3.5 characters per token like YAML (#12) [estimate]. `jina-embeddings-v2-base-code` allows 8192.

Non-code files in the repo:

- **YAML / Kubernetes / Helm:** one chunk per YAML document, with the symbol `Kind/name` (`chunk_k8s_yaml`). Helm templates contain `{{ }}`: never pass a code chunk through a template engine (the #38 finding about `str.format` and Jinja).
- **Markdown and ADRs:** the existing heading-aware chunker.
- **Dockerfiles and small HCL files:** the whole file is one chunk.

### 5.4 Metadata

Payload fields:

- `path`, `language`, `kinds`, `symbols` (qualified names), `parent`
- `start_line`, `end_line`, `imports` (the first 15)
- `repo`, `commit`, `blob_sha`, `parse_errors`
- `domains`: `dev`, plus `devops` for `infra/` and `.github/`

`doc_id = hash(repo:path)`, so it is stable **per path**. Point ids stay `UUIDv5(doc_id:chunk_index)`, so a changed file overwrites its points and the tail-delete from #8 removes leftovers.

Create payload indexes on `path`, `symbols` (an array field, so any-match applies, #7), `language` and `repo`.

### 5.5 Three retrieval channels

1. **Symbol lookup:** an exact payload match (`MatchAny`) on `symbols` for identifiers found in the query. "Where is `getUserById` defined?" is deterministic and needs no ranking.
2. **Lexical with identifier expansion:** Qdrant's tokenizer keeps `getUserById` as one token, so `lexical_text` appends "get User By Id". Then "user by id" matches, and so does the exact identifier. Underscores are split anyway (§1.4).
3. **Dense:** a code embedding model for natural-language → code. The header (path › class › method) gives it natural-language anchors.

Fuse with RRF. When the query contains identifiers, weight the symbol and lexical channels up (weighted RRF, §1.3). The router (#29) decides between the prose corpus and the code corpus (domain `dev`), or queries both and fuses client-side (§1.6).

### 5.6 Embedding model for code

| Candidate | Facts (fastembed 0.9.0) | Fit |
|---|---|---|
| `jinaai/jina-embeddings-v2-base-code` | 768 dims, 8192 tokens, Apache-2.0, 0.64 GB, English + 30 programming languages, no prefixes | natural-language → code; German queries are weaker |
| `intfloat/multilingual-e5-*` (the P1 model) | 512-token truncation, prefixes | fine for docstring-heavy code; DE queries ok |
| `lightonai/mLateOn` (late interaction) | multilingual + code, 128-dim per token, 8192 tokens | as a reranker over code candidates |

Benchmark on the `code` slice with the #5 method before choosing. Use a **separate collection** `kb_code__{model}__{dim}__{build}` behind its own alias `kb_code_current`. It has a different model, possibly different dimensions, and a different update rhythm (per commit), which makes a separate collection simpler than mixing named vectors in `kb_current`.

### 5.7 Repository ingestion (`repo_index.py`)

- **Source:** a pinned commit, read with `git ls-files -s` (mode, blob SHA, path). That respects `.gitignore` and gives blob SHAs for free.
- **Exclude:**
  - `evals/**` and the study notes: the answer keys must never be retrievable (Batch 7 finding)
  - `.env*`, keys and certificates
  - lockfiles
  - generated contracts (`packages/contracts`): index their sources instead
  - `node_modules`, `dist`, binaries, files over 200 KB, symlinks and submodules
- The **secret scan** from Batch 4 runs on code too.
- **Incremental:** diff the manifest's `path → blob` map against the current commit [verified in tests]:
  - **add** → chunk and upsert
  - **change** → re-chunk, upsert, delete tail chunks (#8)
  - **delete** → delete the document's points
  - **rename with the same blob** → update the payload path only
- **Freshness:** index on merge to `main` (a CI job) or nightly. Answers can say "as of commit abc123". Citations use `…/blob/<commit>/<path>#L<start>-L<end>` permalinks, which never drift.
- **Licence:** your own MIT code is fine. Vendored third-party code is excluded anyway.

### 5.8 Eval: the `code` slice

Items like "Wo wird das Chat-Throttle konfiguriert?" carry `relevant: [{path, symbol}]`. Labels refer to code **at a commit**, so the dataset version records that commit, and re-labelling is part of bumping it. Metrics are the usual ones, plus "symbol hit" (the exact symbol in the top k). Guard: prose slices are unchanged when routing to code is on.

### 5.9 Plan mapping

- `ingest/code/` (chunker, repository selector), a new collection and alias, a `search_code` agent tool or a domain route, and MCP exposure later. The GitHub MCP read tools from Phase 2 complement it: the index answers "how does our code work", and GitHub answers "what is in the live repo or issue right now".
- Pins: `tree-sitter==0.25.2` plus grammar wheels. Contract: hits gain optional `path`, `start_line`, `end_line`, `symbols` and `commit`. The UI chip shows `path:lines` and the offcanvas shows numbered code with the permalink.

### 5.10 Pitfalls

- Slicing the decoded string with byte offsets.
- Taking the method node and losing its decorators and doc comment.
- Runtime grammar downloads in a locked-down container, or py-tree-sitter 0.26.0.
- Indexing `evals/`, `.env*`, lockfiles or generated contracts.
- Labelling code eval items by chunk id, or without a commit.
- Embedding 600-token code chunks with a model that truncates at 512.
- Mixing code and prose in one collection while their models or update rhythms differ.

### 5.11 Self-check

1. Why must a code chunker slice bytes, not characters? What went wrong in E6?
2. Where do TypeScript method decorators live in the tree, and why does it matter for kb-agent's questions?
3. Describe cAST's split-then-merge, and why it counts non-whitespace characters.
4. Which three retrieval channels does code search use, and which one answers "where is X defined?" without ranking?
5. What does incremental indexing by blob SHA do on add, change, delete and rename?
6. Why must `evals/` be excluded, and how would you test that exclusion?

---
## 6. Putting it together

### 6.1 The target Phase 3 retrieval pipeline

```
query ─┬─ (follow-up?) QueryPlan ── standalone / sub-queries [/ HyDE] ─┐   raced with the raw query (§3.4)
       │                                                                  ▼
       └────────────────────────────► channels: dense (e5) · lexical (server-side BM25, lex-v1) · [code collection]
                                                  │ one batched request
                                                  ▼
                                   client-side RRF (k, weights from the manifest; deterministic ties)
                                                  ▼
                                   hybrid gate (dense threshold + exact-token rescue) ── abstain → templated reply
                                                  ▼
                                   rerank N → k (cross-encoder or late interaction) [+ min_logit gate]
                                                  ▼
                                   number sources 1..k → grounded prompt (#10, #12)

ingest: parse → chunk (prose: heading-aware · code: cAST) → [contextualize, cached] → dense + lexical → upsert (UUIDv5)
```

### 6.2 Latency budget [estimate, unmeasured]

| Step | Order of magnitude on a laptop CPU | Runs when |
|---|---|---|
| Embed the query (e5-base, ONNX) | tens of ms | every turn |
| Dense + lexical search, small corpus, one batched request | ≤ tens of ms | every turn |
| Client-side fusion and gate | < 1 ms | every turn |
| QueryPlan (small model via OpenRouter) | ~0.5–2 s, partly hidden by racing | follow-ups only |
| Rerank | **0.2–24 s depending on model and N (§2.4)**, the dominant term | every turn, if adopted |
| LLM time to first token | ~0.5–2 s | every turn |

Measure each line on the Mac and record them as stage spans (#18). If reranking can't meet the budget, it goes offline-only until there is a GPU.

### 6.3 Ablation ladder and decision rules

Write these rules **before** running (`ablation.py` implements the comparison and an example rule):

| Step | Factor added | Target slice | Guard slices | Adopt if |
|---|---|---|---|---|
| 0 | dense (P1 config, ADR-0004) | — | — | baseline |
| 1 | + lexical (`lex-v1`), RRF k = 2 | `exact_term` | `paraphrase`, `cross_language`, false acceptance | target "better" (sign test), ≤ 1 net loss per guard |
| 2 | tune `k` ∈ {2, 10, 60} and weights {1 : 1, 1 : 2} | — (on `tune` only) | — | pick on `tune`, confirm on `test` |
| 3 | + reranker (from the bench) | `ranking`, overall MRR@10 | `cross_language` | target "better", p95 added latency ≤ budget |
| 4 | + rewrite (follow-ups) | `follow_up` | all single-turn slices unchanged | target "better" vs **concat** baseline |
| 5 | + contextual (dense + lexical) | `context_dependent` | all | target "better"; cost per million doc tokens recorded |
| 6 | + code collection and route | `code` | prose slices unchanged | target "better" |

"Inconclusive" means **keep the cheaper configuration** (Batch 2 rule). Each run record carries the full config, the index manifest, the prompt bundles and the commit (#17, #38, #42).

### 6.4 Trace tree

```
CHAIN chat
├─ CHAIN query_plan            kb.query.source=raw|llm|llm_failed
│  └─ LLM (router profile)
├─ EMBEDDING query
├─ RETRIEVER dense             top-N ids + cosine
├─ RETRIEVER lexical           top-N ids + BM25 score, kb.lex.profile=lex-…
├─ CHAIN fusion                kb.fusion.method=rrf, kb.fusion.k=2, kb.gate.decision=pass_dense|pass_exact_token|abstain
├─ RERANKER                    reranker.model_name, reranker.top_k, kb.rerank.moved_into_top
└─ LLM (answer profile)
```

In Phase 2's agent loop, the same subtree sits under the `TOOL search_kb` span.

### 6.5 Index manifest additions (#9)

```yaml
collection: kb__e5-base__768__c1000__b20261101
dense: {model: intfloat/multilingual-e5-base, revision: <sha>, prefix_profile: e5, threshold: 0.81}
lexical: {vector: lex, modifier: idf, profile: lex-3f2a…, options: {tokenizer: word, stemmer: {type: none},
          stopwords: {custom: []}, lowercase: true, max_token_len: 64, avg_len: 148.6, k: 1.2, b: 0.75}}
fusion: {method: rrf, k: 2, weights: {dense: 1.0, lex: 1.0}, tie_break: best_rank>dense>id}
gate: {dense_threshold: 0.81, dense_floor: 0.76, exact_token_rescue: true}
rerank: {model: BAAI/bge-reranker-v2-m3-int8, candidates: 20, top_k: 5, max_chars: 1200, min_logit: null}
context: {mode: off, bundle: null}
qdrant: {server: 1.19.2, client: 1.19.1}
```

The numbers above are placeholders. Every value comes from a measured run and an ADR.

---

## 7. Plan change list (for the Phase 3 plan)

1. **Qdrant 1.18.x → 1.19.x** (server) and **qdrant-client 1.19.1** at the start of Phase 3: the explicit no-stemmer for BM25 and corpus-scoped IDF exist only in 1.19 [source]. Re-run the Batch 2 alias checks on the new version.
2. **`retrieval_v2`** with slices (`exact_term`, `paraphrase`, `cross_language`, `context_dependent`, `follow_up`, `ranking`, `code`, unanswerable incl. near-miss tokens), multi-turn `messages`, `{path, symbol}` labels, a commit for code items, and a **tune/test split**. v1 is still reported.
3. **Eval harness:** candidate recall@20/@50, per-stage latency, the per-slice paired comparison and decision rule (`ablation.py`), `--config` for retrieval pipelines, and run records with the manifest.
4. **Collection schema v3:** sparse vector `lex` (`modifier: idf`) with server-side BM25 (`Document(model="qdrant/bm25")`), the `lex-v1` profile, measured `avg_len`, and the profile fingerprint in the manifest. Build it behind the alias (#9).
5. **No BM25 in qdrant-client local mode:** extend D20's testcontainers rule to sparse tests, or use qdrant-edge-py for parity tests.
6. **Client-side fusion** (`fusion.py`) with deterministic ties; `/v1/search` gets `mode` and per-channel ranks and scores; the inspector shows dense / lexical / fused / reranked columns.
7. **Gate v2:** dense threshold + exact-token rescue + dense floor; recalibrate with the new slices. **Never** pass `RETRIEVAL_SCORE_THRESHOLD` as a fusion `score_threshold`.
8. **Reranker:** benchmark on the Mac (`bench_rerank.py`), decide in **ADR-0011** with a latency budget, bake it into the image, check it in `/readyz`, `FakeScorer` in CI, RERANKER spans, and number sources after reranking.
9. **QueryPlan** for L0/L1 prefetch on follow-ups only: race raw and rewritten queries, keep literal tokens, fall back to the raw query, `rewrite@v1` bundle, router profile, deadline. Answer the "previous + current message" question with the three-arm experiment.
10. **Contextual retrieval:** per-document `contextualize` flag (D25 class table), provider filter for the ingest model (ADR-0005), Postgres `chunk_contexts` cache keyed by content + bundle + model + window, background job, separate OpenRouter key with a limit, context kept out of the answer prompt, and a red-team item for self-steering documents.
11. **D7 decision becomes more urgent:** without stored originals, contexts can't be regenerated with a new prompt.
12. **Code corpus:** `ingest/code/` (cAST chunker, K8s YAML chunker, repository selector with exclusions, blob-SHA diff), its own collection and alias `kb_code_current`, payload indexes (`path`, `symbols`, `language`, `repo`), `search_code` or a domain route, permalink citations, indexing on merge to `main`.
13. **Pins:** `tree-sitter==0.25.2` plus grammar wheels (not the runtime-downloading language pack); keep the crash regression test.
14. **Exclusions** (`evals/**`, study notes, `.env*`, lockfiles, generated contracts) apply to **both** the doc corpus (D22) and the code corpus, with a test.
15. **New settings** (Appendix A of the plan), most of them living in the model profile or index manifest: `RETRIEVAL_MODE`, `FUSION_K`, `FUSION_WEIGHTS`, `LEX_PROFILE`, `RERANK_*`, `QUERY_TRANSFORM_MODE`, `QUERY_TRANSFORM_DEADLINE_MS`, `CONTEXTUAL_MODE`, `CONTEXT_WINDOW_CHARS`, `CODE_INDEX_*`.
16. **RAM budget (A1):** reranker int8 or late interaction. Re-check memory with everything running.

---

## Appendix A. Verification log

| # | What | How | Result |
|---|---|---|---|
| V1 | RRF default `k`, formula, weights, no tie-breaking | Qdrant source 1.19.2 and 1.18.3 (`reciprocal_rank_fusion.rs`), qdrant-client 1.19.1 `hybrid/fusion.py` | k = 2 in all three; `1/((pos+1)/w + k − 1)`; "Does not break ties" |
| V2 | Fusion numbers, thresholds on fused scores, corpus IDF | `exp_fusion.py` on qdrant-edge-py 0.8.0 | table in §1.3; `score_threshold=0.8` → []; corpus IDF changes scores, not results |
| V3 | Tie order across processes | the same query in 20 fresh processes | 11 : 9 split |
| V4 | DBSF | `score_fusion.rs` (sample variance, ±3σ, single hit → 0.5) | the sketch matches the engine within 1e-3 |
| V5 | BM25 tokenisation per config | `exp_bm25_tokens.py` (hash decode) | table in §1.4; `test_python_word_tokens_match_qdrant_tokenizer` (4 strings) |
| V6 | IDF formula | `query_context.rs`, `test_idf_formula` | `ln((N − df + 0.5)/(df + 0.5) + 1)` |
| V7 | Server BM25 options and defaults | `schema.rs`, `bm25_inference.rs` | k 1.2, b 0.75, avg_len 256, English default, `{"type":"none"}` stemmer only in 1.19 |
| V8 | Corpus-scoped IDF availability | grep 1.18.3 vs 1.19.2 | 1.19 only |
| V9 | Three BM25 pipelines | fastembed source, qdrant-client `model_embedder.py`, a local-mode run | fastembed keeps `_`; local mode uses fastembed (HF download attempted, about 37 s of retries, failed) |
| V10 | fastembed catalogue | `list_supported_models()` | §2.3 and §5.6 tables (sizes, licences, languages) |
| V11 | Reranker output | fastembed `onnx_text_model.py` | raw logits `output[:, 0]`; truncation from the tokenizer config; padding per batch |
| V12 | CPU MatMul throughput | `bench_matmul.py`, onnxruntime 1.31, 2 vCPU | 203–230 GFLOP/s fp32 |
| V13 | RERANKER semconv | openinference-semantic-conventions 0.1.41 | `reranker.{query,model_name,top_k,input_documents,output_documents}` |
| V14 | tree-sitter facts | `exp_treesitter.py` | bytes vs characters, decorator/comment siblings, error recovery |
| V15 | tree-sitter crash | `tree_sitter_crash_probe.py` ×5 per version | 0.26.0: 5/5 segfaults; 0.25.2: 0/5 |
| V16 | Language pack runtime download | `get_parser`, cache listing, binary strings | downloads from `github.com/xberg-io/…/releases`; env `TREE_SITTER_LANGUAGE_PACK_CACHE_DIR` |
| V17 | Anthropic contextual retrieval numbers | the post (19 Sep 2024) | §4.2 |
| V18 | cAST algorithm and results | arXiv 2506.15655 v2 (HTML), ACL Anthology listing | §5.3 |
| V19 | OpenRouter prompt caching per provider | the OpenRouter docs page | §4.4 |
| V20 | Qdrant multivector rescoring with `m = 0` | the Qdrant tutorial | §2.6 |

## Appendix B. Sketches (`batch-08-sketches.zip`)

| File | Tests |
|---|---|
| `kb_p3/fusion.py`, `kb_p3/gate.py` | `test_fusion_gate.py` (13): Qdrant k = 2 / 60 / weights / DBSF numbers, deterministic ties, evidence kept, fused-threshold trap, gate pass/rescue/abstain, floor |
| `kb_p3/lexical.py` | `test_lexical.py` (9): identifier parts, expansion, word tokens = Qdrant splitting, fingerprint, options shape, `avg_len`, exact tokens |
| `kb_p3/rerank.py`, `kb_p3/query_plan.py` | `test_rerank_query.py` (18): reorder and trace, logit gate, stable ties, clipping, cost model; QueryPlan skip/rewrite/fallback/forbid/literal tokens/cleaning/caps/HyDE/needs_retrieval/prompt/multi-query |
| `kb_p3/contextual.py` | `test_contextual.py` (9): baseline, display vs index text, cache hits/misses, layout, tag neutralisation, cleaning, window policy, key, cost |
| `kb_p3/code_chunker.py`, `kb_p3/repo_index.py` | `test_code.py` (12): bytes, attachments, merge, TS decorators and class context, order and budget, syntax errors, line split, K8s YAML, exclusions, size, diff, permalinks |
| `kb_p3/ablation.py` | `test_ablation.py` (6): sign test, adopt, guard regression, inconclusive, latency, same-items check |
| — | `test_engine_parity.py` (8): tokenizer parity ×4, default config drops "not", RRF parity with the engine, IDF formula, tree-sitter crash regression |

Total **75 passed** (pytest 9.1.1, Python 3.13.16). `experiments/` holds the scripts and raw outputs behind V2, V3, V5, V12, V14 and V15, plus `bench_rerank.py` to run on the Mac.

## Appendix C. Self-check answer key

**§1 Hybrid**
1. IDF depends on the whole collection (N and document frequencies), which changes as documents are added. TF and length are per-document facts known at ingest. With `modifier: idf`, Qdrant computes `ln((N − df + 0.5)/(df + 0.5) + 1)` at query time.
2. k = 2. A small k rewards being first in *one* list (E2: chunk 1, dense #1 only, is second). k = 60 rewards appearing in both (chunk 5, dense #5 and lexical #3, is second).
3. The maximum fused score is n × 1/k = 1.0 for two lists, reached only by a chunk that is #1 in both. 0.8 cuts everything else. The cosine threshold belongs on the dense channel (a prefetch threshold or the gate), never on fused scores.
4. English stopwords remove "not", "in", "it" ("it is not ready" → `readi`); the English stemmer is applied to German words; German compounds are never split. Also: `word` splits identifiers on `_`, and the `multilingual` tokenizer drops numbers.
5. Any query with an underscore identifier. fastembed keeps `err_connection_refus` as one token, while the server splits `err`, `connection`, `refused`. The hashes differ, so there is no match and no error.
6. `avg_len` is inside every document's stored TF weight. Changing it without re-indexing mixes two length normalisations in one collection.
7. Any two of: per-channel ranks and scores for the inspector; the raw dense cosine for the gate; deterministic ties; per-channel trace spans; config-switch ablations.
8. Dense is unsure (below threshold), so it tries the rescue. The literal token `ERR_CONNECTION_RESET` doesn't appear in any lexical hit, so the gate abstains. Partial matches never rescue.

**§2 Reranking**
1. It attends across query and passage jointly. It needs one forward pass per pair at query time, so it can't be precomputed for the corpus.
2. Candidate recall@N: is a relevant chunk among the N reranker inputs?
3. ≈ 2 × 302 M × 20 × 256 ≈ 3.1 TFLOP, which is tens of seconds in the sandbox and several seconds even on an optimistic M1. Not interactive without int8, fewer or shorter candidates, or late interaction.
4. Raw logits. Calibrate a `min_logit` per model on the unanswerable items, as in #11, and store it in the manifest. A sigmoid is for display only.
5. Document token vectors are computed at ingest, so a query only needs its own short encoding plus MaxSim. Storage is about 128 × tokens × 4 B per chunk (~150 KB vs 4 KB for one dense vector).
6. `jina-reranker-v2-base-multilingual` and `jina-colbert-v2` are CC-BY-NC-4.0. The MiniLM, jina-v1 and bge-reranker-base models aren't built for German.

**§3 Query transformation**
1. L2's model already writes standalone search queries in its tool calls. L1's prefetch runs on the raw last message before the model is involved.
2. It returns the raw question (`source="llm_failed"`) on invalid JSON, and also on an extra field (`extra="forbid"`). If the rewrite drops a literal token, it re-appends that token to the lexical query.
3. `passage: `. It is a hypothetical document and should live in the document side of the embedding space; the HyDE paper encodes it with the document encoder.
4. Race it: start the raw search immediately, rewrite in parallel, then search the rewrite and fuse both with RRF. Also skip first turns and set a tight deadline.
5. On the `follow_up` slice: (a) the raw last message, (b) the previous + current user message concatenated, (c) the LLM rewrite. Paired comparison against (b), with single-turn slices as guards.

**§4 Contextual retrieval**
1. The heading-path `embed_text` from #3. It already supplies referents for well-structured Markdown, so comparing with bare chunks would overstate the gain.
2. The document is the same for every chunk of that document, so as a prefix it can be cached. The chunk varies, so it goes last.
3. Document hash, chunk hash, prompt bundle, model and provider, window policy. Re-ingesting the same file hits the cache and makes no LLM call.
4. Each of the document's L/step chunks sends about L tokens. Bounded by prefix caching (reads at 0.1–0.25×) and by the outline + section window.
5. "Full documents never leave." D25 gains a per-class `contextualize` permission, and ADR-0005's provider filter (ZDR or no-training, pinned) applies to the ingest model as well.
6. A document instructs the context writer to describe it as authoritative or relevant to unrelated queries (ranking manipulation), or to plant instructions. Mitigations: keep the context out of the answer prompt, clean and cap it, flag it as generated, neutralise reserved tags, add a red-team item.

**§5 Code-aware RAG**
1. tree-sitter offsets count UTF-8 bytes. In E6, an umlaut and an emoji in a comment shifted character positions by 5, so `str[start_byte:]` cut "def " off.
2. As siblings before `method_definition` in the class body (and the class decorator under `export_statement`). Routes and `@Roles` are exactly what "who may delete documents?" needs.
3. Greedily merge adjacent sibling nodes while under budget, and recurse into nodes that are too big. Non-whitespace characters make the size independent of indentation and formatting style.
4. Symbol lookup, lexical with identifier expansion, and dense. Symbol lookup (an exact payload match) answers "where is X defined?".
5. Add → chunk and upsert; change → re-chunk, upsert, delete tail chunks; delete → delete the points; rename with the same blob → update the payload path only.
6. The eval datasets contain the expected sources and answers, so retrieving them lets the agent read the answer key. Test: run the selector on a fixture listing that contains `evals/…` and assert it is skipped (`test_select_excludes_answer_keys_secrets_lockfiles`), plus an index-level check that no point has a path under `evals/`.

---

## Sources

- Qdrant source, tags v1.19.2 and v1.18.3: `lib/segment/src/common/reciprocal_rank_fusion.rs`, `score_fusion.rs`, `lib/bm25/src/lib.rs`, `src/common/inference/bm25_inference.rs`, `lib/api/src/rest/schema.rs`, `lib/segment/src/types.rs`, `lib/segment/src/data_types/query_context.rs` — [github.com/qdrant/qdrant](https://github.com/qdrant/qdrant)
- qdrant-edge-py 0.8.0 (PyPI) and its examples in `lib/edge/python/examples/` of the same repository
- Anthropic, "Introducing Contextual Retrieval", 19 Sep 2024 — [anthropic.com/news/contextual-retrieval](https://www.anthropic.com/news/contextual-retrieval)
- Zhang et al., "cAST: Enhancing Code Retrieval-Augmented Generation with Structural Chunking via Abstract Syntax Tree" — [arXiv 2506.15655](https://arxiv.org/abs/2506.15655v2), [ACL Anthology (Findings of EMNLP 2025)](https://preview.aclanthology.org/dashboard/2025.findings-emnlp.430)
- OpenRouter, Prompt Caching — [openrouter.ai/docs/prompt-caching](https://openrouter.ai/docs/prompt-caching)
- Qdrant, "Multivector Representations for Reranking" — [qdrant.tech tutorial](https://qdrant.tech/documentation/tutorials-search-engineering/using-multivector-representations/)
- Cormack, Clarke, Büttcher, "Reciprocal Rank Fusion outperforms Condorcet and individual rank learning methods", SIGIR 2009 (cited in Qdrant's RRF source)
- Gao, Ma, Lin, Callan, "Precise Zero-Shot Dense Retrieval without Relevance Labels" (HyDE), arXiv 2212.10496
- fastembed 0.9.0, qdrant-client 1.19.1, tree-sitter 0.25.2/0.26.0, tree-sitter-language-pack 1.22.1, openinference-semantic-conventions 0.1.41 (PyPI packages, source read locally)
