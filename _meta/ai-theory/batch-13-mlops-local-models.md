# Batch 13 — MLOps & local models

> **Topics:** #55 Embedding & reranker fine-tuning · #56 MLOps: tracking, registry & rollout · #57 Local inference & quantization · #58 Local vs. API model benchmarking
> **Needed for:** Phase 6 (§0 roadmap, §13.4) · a few small pieces fit P1–P3 (§5)
> **Delivered:** 2026-10-15 · builds on #5, #9, #11, #12, #13, #17, #19, #38, #42–#44, #49
> **Verified with:** sentence-transformers 6.1.0 + transformers 5.19.0 + torch 2.14.1 (CPU) · MLflow 3.17.1 (SQLite store) · qdrant-client 1.19.1 local mode · fastembed 0.9.0 + onnxruntime 1.31.0 · llama.cpp master `529ac89` (14 Oct 2026, latest tag b11619) built from source, CPU, 2 vCPU · openai 3.31.0 · Pydantic 2.14.1 · Python 3.13.16
> **Read, not run:** Ollama master `f5be23f` (14 Oct 2026; release v0.40.4; build blocked — Go module proxy), mlx-lm 0.32.0 server source (Apple Silicon only), llama.cpp quantize/perplexity READMEs
> **Not available here:** real model weights (Hugging Face and the Ollama registry are blocked) → stand-ins: WordLlama static embeddings (weights in the wheel), a random-init tiny BERT, random-weight Llama checkpoints (4.4M and 415M parameters). Stand-ins show **mechanics and relative effects**, never production numbers.
> **Sketches:** `batch-13-sketches.zip` — 8 modules, 34 pytest (33 without the E4 model export) + 1 live test against llama-server, experiment scripts E1–E7 with their outputs.

---

## 0. Why this batch, and how the four topics connect

Phases 1–5 make kb-agent *measurable* (golden set, eval harness, traces, cost logs) and *swappable* (model profiles, `openai_compat`, Qdrant alias + manifest). Phase 6 uses both properties to change the models themselves:

```
 golden sets (frozen, P1/P3) ─────────────────────────────────────────────┐ (never trained on)
 synthetic pairs (#44) + feedback (#45) ─► split by section ─► fine-tune (#55) ─► export ONNX
                                                                    │
                                     gate: unseen items, paired, slices, parity, budgets
                                                                    │ promote
                       MLflow run + registered version + tags (#56) ▼
            build collection kb__…__r{version} ─► validate ─► flip kb_current (the switch)
                                                                    │ smoke ok
                                         MLflow alias `champion` (the record) ◄┘

 generation side:   OpenRouter models ◄── same openai_compat ──► local runtime (#57)
                                         └── benchmark per role (#58) decides which serves what
```

Two questions run through the whole batch:

1. **Did it really get better?** Fine-tuning and quantization both produce numbers that *look* like progress. Leakage, contamination, prompt caches and warm-up effects make those numbers lie. Every section below has one experiment showing how much.
2. **Can I prove what is running, and undo it?** A fine-tuned embedder, a quantized LLM and a benchmark result are only useful if the exact bytes, settings and data are recorded and the switch is reversible.

What P1–P5 already give you, so P6 doesn't rebuild it: the golden set labelled by **doc + heading** (#17), `kb-eval retrieval --collection` (#9), the index manifest + per-request embedder check (#9), model profiles (#13/#38), golden vectors for the embedder (#5), paired per-item statistics and decision rules written first (#5, #43, #49), and `openai_compat` with explicit sampling (#13/#38).

---

## 1. #55 Embedding & reranker fine-tuning

### 1.1 Why (first)

A general embedder doesn't know that "Rollout zurückdrehen" and `kubectl rollout undo` are the same request, or that "kb_current" is an alias name. Fine-tuning moves *your* vocabulary closer together. But it is the **last** retrieval lever, not the first:

| Your golden-set failure looks like … | Cheaper fix that comes first | Fine-tuning helps? |
|---|---|---|
| Right doc exists, chunk text is broken (tables, hyphenation) | parsing (#2), Docling (P3) | no |
| Answer is split across chunks / lost its context | chunking (#3), heading path, contextual retrieval (#24) | no |
| Exact token missed (`5432`, `--prune`, `ERR_…`) | hybrid BM25 (#21) | weakly |
| Right doc in top 20, wrong order | reranker (#22) | the reranker can be fine-tuned |
| Paraphrase / jargon / DE↔EN mismatch, right doc nowhere near the top | — | **yes — this is its job** |
| The document isn't in the corpus | corpus gap (#45 triage) | no |

So: fine-tune only when the P3 baseline (hybrid + rerank) is measured and the remaining failures are vocabulary mismatches. Write that diagnosis into ADR-0019 before you train.

### 1.2 How it works

**Bi-encoder fine-tuning (the embedder).** Training data are pairs *(query, relevant passage)*. The standard loss is **MultipleNegativesRankingLoss** (MNRL, InfoNCE): in a batch of B pairs, each query must score its own passage above the other B−1 passages, which act as free **in-batch negatives**. Scores are cosine × `scale` (20 by default = temperature 0.05). Consequences you must design for:

- **Batch size = number of negatives.** Bigger batches help; `CachedMultipleNegativesRankingLoss` (GradCache) gives a large effective batch on small memory.
- **Duplicates poison the batch.** If the same passage (or a near-copy) appears twice in a batch, one copy becomes a "negative" for the other's query. Use `batch_sampler=BatchSamplers.NO_DUPLICATES` (ST 6.1 also has `NO_DUPLICATES_HASHED`).
- **Hard negatives** (a third column) are passages that *look* relevant but aren't; they teach finer distinctions than random in-batch negatives — and they are where **false negatives** creep in (§1.4).
- **Prompts must match serving.** E5 needs `query: ` / `passage: `. In ST 6.1 you pass `prompts={"anchor": "query: ", "positive": "passage: "}` to the training arguments and set `model.prompts`, so `encode_query` / `encode_document` apply them (verified; stored in `config_sentence_transformers.json`). fastembed applies none (Batch 1 finding) — your `Embedder` adds them.

**Three ways to adapt, very different rollout costs:**

| Option | What changes | Re-index? | Rollout | When |
|---|---|---|---|---|
| **Full fine-tune** of the bi-encoder | query *and* document vectors | **yes** (whole corpus) | new collection + alias flip (#9) | largest gains, largest cost |
| **Query-only adapter** (frozen document tower + a small trainable layer on the query side; ST 6.1 `Router.for_query_document`) | query vectors only | **no** | swap the query encoder; manifest records both sides | quick wins, cheap rollback |
| **Reranker fine-tune** (cross-encoder, `CrossEncoderTrainer` in ST 6.1) | the second stage only | no | model profile switch | ranking problems in the top 20–50 |

In E1 (stand-in model) the query-only adapter matched the full fine-tune within noise on unseen topics (+6.0 vs +5.3 points) and **left all stored document vectors bit-identical** (verified). That doesn't transfer to e5-base automatically — but it makes the adapter the first thing to try, because it needs no re-index.

**Reranker fine-tuning** uses the same pairs plus hard negatives as labelled (query, passage, 0/1) examples, trained as a binary or listwise classifier. Its gate is "reranked hit@5/MRR on unseen items", and its rollout is a profile change — no Qdrant work at all.

### 1.3 The training data, and the leak you must prevent

Sources, in order of trust: **real questions** (from feedback triage, #45, rewritten and labelled by you), **synthetic questions** (#44: an LLM writes a question per chunk; the chunk is the positive), never the golden sets.

**The leakage unit is the section, not the question.** Two questions about the same section are near-copies *for a retriever*: once one is trained, the other is easy. E1 measured this with the stand-in model (corpus = your own DONE.md bullets + plan.md distractors; 51 topics, 153 queries; 10 seeds, ~45 test items per seed):

| Split | Arm | Test hit@5 | Gain over base (mean, min…max over seeds) |
|---|---|---|---|
| random 30 % of **queries** held out | full fine-tune | 0.615 | **+7.8** (+4.3…+10.9) |
| random 30 % of **queries** | query adapter | 0.604 | +6.7 (−2.2…+15.2) |
| 30 % of **topics** held out | full fine-tune | 0.616 | **+5.3** (0…+11.1) |
| 30 % of **topics** | query adapter | 0.622 | +6.0 (0…+8.9) |

The random split overstated the full fine-tune's gain by about half (+7.8 vs +5.3 points). And the seed-to-seed range (0 to 11 points) shows that **one training run tells you very little** at this data size — repeat with seeds or bootstrap.

**Contamination of the golden set.** Synthetic generation over the *whole* corpus also produces questions about the sections your golden set asks about. E1b kept the test items fixed (the natural-wording "explanation" query of 30 % of the topics, 15 items per seed, 10 seeds) and compared training **without** vs **with** the other two questions of those same topics:

| Arm | Clean gain over base | Extra "gain" from contaminated training | Seeds with inflation > 0 |
|---|---|---|---|
| full fine-tune | +7.3 | **+8.0** (sd 12.5) | 8 / 10 |
| query adapter | +12.0 | **+4.7** (sd 8.9) | 6 / 10 |

With contamination the full fine-tune's golden-set gain roughly **doubled** — the golden set stopped measuring generalisation. (15 items per seed is small; the direction is consistent, the size is uncertain.)

**Rules (in `splits.py`):**

1. Every training pair carries `doc` + `heading` of its positive → `group = doc#heading`.
2. **Golden firewall:** pairs whose group appears in any golden set (`retrieval_v1/v2`, `generation_v1`) are excluded from training. If that removes too much of a small corpus, the alternative is to train on them and **gate only on the unseen part** of the golden set (`seen_unseen()`), reporting the seen part separately — never one mixed number.
3. Split the rest **by group** (sha256 buckets — not `hash()`, which is salted per process, #42) into train / dev / test.
4. Drop near-duplicate questions across splits and against golden questions (4-gram Jaccard ≥ 0.7, as in #44).
5. Freeze the training file and log its sha256 with the run (§2).

### 1.4 Hard negatives without false negatives

A mined "hard negative" is the highest-scoring passage that isn't labelled positive. With **doc-level labels and one positive per query** — exactly what synthetic generation produces — the highest-scoring unlabelled passage is often *another relevant passage of the same section or document*. Training then pushes a correct answer away.

Two facts from E2:

- **sentence-transformers 6.1's miner already handles multiple labelled positives:** `mine_hard_negatives` groups rows by anchor text and excludes every labelled positive of that anchor ("Found an average of 5.02 positives per query"). False negatives therefore come only from **unlabelled** positives.
- With one positive per query (51 topics, 5 seeds, 108 training rows each), the share of mined negatives that were in fact from the query's own topic:

| Filter | False-negative share | Rows kept |
|---|---|---|
| none (top-1 mined) | **21.9 %** | 108 |
| skip the top 3 (`range_min=3`) | 6.5 % | 108 |
| `relative_margin=0.05` | 11.0 % | **26 of 108** (a weak base model scores many true negatives above the positive) |
| exclude the positive's own document (structural) | **0 %** (by construction) | 108 |

Test hit@5 on unseen topics moved within noise (0.596 pairs only → 0.604–0.613 with negatives; n = 45 × 5) — the stand-in model and corpus are too small to show the *damage* of false negatives, but the shares are what you'd be training on.

**Rule (in `negatives.py`):** structural filter first (exclude the positive's doc, or at least its section; your labels make this free), then optionally skip the top 1–3, then a **human audit** of 30 sampled triplets ("is this 'negative' actually an answer?") recorded with the run. Remaining blind spot: the *same fact* in another document — an ADR and the runbook that implements it, the DE and EN versions of one guide. Mark those relations in document metadata (`translation_of`, `implements`) and pass a `same_fact` predicate.

### 1.5 Train → export → serve

1. **Train** with `SentenceTransformerTrainer` (ST 6.1): MNRL (or Cached MNRL), `NO_DUPLICATES`, prompts, a seed, `report_to=["mlflow"]` (§2). On the Mac: MPS for e5-small/base is plausible — not verified here (CPU-only sandbox).
2. **Export to ONNX** — fastembed serves ONNX, not PyTorch. Verified route: `torch.onnx.export` of the underlying `BertModel` (a 6-line wrapper; transformers 5.19 needs it because `forward` clashes on positional `use_cache`), opset 17, dynamic batch/sequence axes, `onnx.checker`, optional `onnxruntime.quantization.quantize_dynamic` (int8).
   **Version trap (verified):** `sentence-transformers[onnx]==6.1.0` is **unresolvable** — its `optimum-onnx 0.1.0` pins `transformers < 4.58` while ST 6.1 needs `transformers ≥ 5`; an unpinned install silently resolves to ST 5.7 + transformers 4.57.6. Installing MLflow + optimum into the training venv also **downgraded transformers to 4.57.6** (caught by `uv pip check`). And a model saved by ST 6.1 does not load in ST 5.7 (`sentence_transformers.base.modules.normalize` doesn't exist there; `tokenizer_class: "TokenizersBackend"` is transformers-5 only). → export in the training environment with `torch.onnx`, pin everything, run `uv pip check` in CI.
3. **Serve** with `TextEmbedding.add_custom_model(model=…, pooling=MEAN, normalization=True, dim=…, model_file="onnx/model.onnx")` + `TextEmbedding(model_name=…, specific_model_path=<downloaded dir>)` — works fully offline (verified). This also closes the mechanism half of the 2026-10-13 finding about custom models (real e5 still unverified).
4. **Golden-vector parity** (E4, `profile.py`): embed fixed probe texts in the training framework, store the vectors with the model, re-embed through the exact serving path, require cos ≥ 0.999.

| Serving variant (E4, tiny fine-tuned BERT) | min cosine vs training vectors |
|---|---|
| fastembed, mean pooling, prefix added by our code | **1.0000** |
| fastembed, **CLS** pooling (wrong profile) | 0.764 |
| fastembed, **missing `query: ` prefix** | **0.989** |
| fastembed, int8 dynamic quantisation | 0.99998 (ONNX 2.71 MB → 0.76 MB) |

The missing prefix still scored **0.989** — a "≥ 0.98" check would pass a broken pipeline. Keep 0.999 for fp32. For int8, parity alone isn't the gate: store int8's own golden vectors and run the retrieval eval on the int8 build.

### 1.6 Gate: when is a candidate better?

`gates.py` encodes the rule; write the numbers into ADR-0019 **before** training:

- Evaluate on **unseen** items only (held-out groups + the unseen part of the golden sets), paired per item against the current champion (or the base model).
- Promote if gain ≥ `min_gain` (e.g. +3 points hit@5) **and** the exact sign test on discordant items is significant (9 : 2 → p = 0.065 is *not*, as in #5).
- Hard rejects regardless of the mean: contamination check failed, parity < 0.999, any slice (language, domain) with ≥ 8 items drops more than 5 points, p95 latency or model size over budget.
- Otherwise **inconclusive → keep the champion** (it's already built and indexed).

With ~45 unseen items, only large gains are detectable (#17: ±12 points interval). Grow the *unseen* evaluation set (reviewed synthetic items from held-out groups) rather than adding repeats.

### 1.7 Verified facts (this batch)

- ST 6.1 renamed module paths: `sentence_transformers.losses` / `.training_args` still import but emit `DeprecationWarning` → `sentence_transformers.sentence_transformer.losses` / `.training_args`. Tutorials older than 6.0 use the old paths.
- ST 6.1 trainers: `SentenceTransformerTrainer`, `CrossEncoderTrainer`, `SparseEncoderTrainer`, `MultiVectorEncoderTrainer`; losses include MNRL, Cached MNRL, GIST, Matryoshka, MarginMSE, distillation losses; `mine_hard_negatives(range_min, range_max, max_score, min_score, absolute_margin, relative_margin, sampling_strategy, …)`.
- `transformers` 5.19 `TrainingArguments.report_to` defaults to `"none"` (verified). In 4.x the default meant "all installed integrations" — so an old environment with MLflow installed logged silently (not re-run).
- E1–E4 numbers above; scripts and outputs in the zip.

### 1.8 Plan mapping

| Plan item | What this batch adds |
|---|---|
| §0 P6 "Embedding/reranker fine-tuning" | the go/no-go diagnosis (§1.1), adapter-first option, reranker as the no-re-index path |
| §13.3 synthetic data (P3) | generator must record `doc` + `heading` of the source chunk and `origin` → enables the firewall and group split later |
| D23 golden set | frozen golden sets are a **training firewall**; report seen/unseen separately if ever trained near them |
| D9 / ADR-0004 | base-model choice should note fine-tunability (licence allows derivatives — multilingual-e5 and bge-m3 are MIT; size trains on the Mac) |
| §6 layout | new `training/` (configs, frozen pair files, scripts) — excluded from ingestion like `evals/` |
| new ADR-0019 | fine-tuning go/no-go + decision rule (§1.6) |

### 1.9 Pitfalls

- Random row split → inflated gains (E1: about half of the measured gain).
- Synthetic questions about golden-set sections → the golden set measures memory, not generalisation (E1b: gain doubled).
- Hard negatives mined with one positive per query → ~1 in 5 "negatives" is relevant (E2).
- Duplicated texts in a batch → in-batch false negatives; use `NO_DUPLICATES`.
- Training prompts ≠ serving prefixes → plausible but worse vectors; parity at 0.98 doesn't catch it (E4: 0.989).
- Mixed library majors between training and export environments (ST 6.1 ↔ 5.7, transformers 5 ↔ 4).
- Judging one run: seed-to-seed spread was 0–11 points.
- Fine-tuning before hybrid + rerank are measured → you can't tell what the extra effort bought.
- Forgetting that a full fine-tune means **re-indexing everything** (time, a new collection, a recalibrated threshold — #11).

### 1.10 Self-check (#55)

1. Name three retrieval failure types that fine-tuning can't fix, and the cheaper fix for each.
2. Why is MNRL's batch size a quality knob, and what does `NO_DUPLICATES` prevent?
3. Your synthetic generator wrote 3 questions per chunk. Why does a random 80/20 split over the questions overstate the gain, and what do you split by instead?
4. What does "golden firewall" mean, and what is the fallback if it would remove most of the corpus?
5. sentence-transformers' miner already excludes labelled positives. Where do false negatives still come from in kb-agent's data, and which filter is free for you?
6. Full fine-tune vs query-only adapter vs reranker fine-tune: which ones need a re-index, and why?
7. Your parity check passes at cos 0.989. Is the pipeline fine?

---

## 2. #56 MLOps: experiment tracking, model registry & rollout

### 2.1 Why (first)

Three months after a fine-tune you need to answer: *which data, which base model revision, which loss and prefixes produced the vectors currently in `kb_current` — and how do I go back?* Without tracking you can't reproduce a result; without a registry you can't name what's running; without a rollout procedure you can't undo it. The cost of skipping it shows up exactly once — when something degrades and nobody knows what changed.

### 2.2 Concepts (MLflow 3 vocabulary)

| Concept | Meaning | kb-agent use |
|---|---|---|
| **Experiment** | a named group of runs | `kb-embedder-ft`, `kb-reranker-ft`, `local-vs-api` |
| **Run** | one training/eval execution: params, metrics, tags, artifacts | one fine-tune, one benchmark campaign |
| **Dataset digest** | sha256 of the frozen input file | `pairs_v1.jsonl`, `retrieval_v1.jsonl` — logged by you (the Trainer doesn't) |
| **Logged model** (MLflow 3) | model artifacts + metadata produced by a run | the ONNX directory + profile + golden vectors |
| **Registered model / version** | a name with immutable, numbered versions | `kb-embedder` v1, v2 … |
| **Alias** | a movable pointer to one version | `challenger`, `champion`, `previous_champion` |
| **Tags** | key/value on runs and versions | `gate=promote`, `profile_fingerprint`, dataset sha256s |

Stages (`Staging`/`Production`) are **deprecated** since 2.9 (verified: `FutureWarning`) — use aliases.

### 2.3 What MLflow 3.17 actually does (E3, verified)

- **Default store:** with no configuration MLflow 3 writes `sqlite:///<current directory>/mlflow.db` — a new database wherever you happen to run a script. Set `MLFLOW_TRACKING_URI` explicitly (e.g. `sqlite:////…/kb-agent/.mlflow/mlflow.db` or a local `mlflow server`).
- **Telemetry is on by default.** Disabled by `MLFLOW_DISABLE_TELEMETRY=true` or `DO_NOT_TRACK=true`, and automatically when `CI`, `GITHUB_ACTIONS`, `PYTEST_CURRENT_TEST` or one of about ten other CI markers is set. Same pattern as ragas/deepeval/promptfoo (Batches 9–10): set the opt-out in every tool environment.
- **Trainer callback** (`report_to=["mlflow"]`): logged **118 params** (every `TrainingArguments` field — mostly noise), 5 metrics (`train_loss`, `epoch`, throughput, `total_flos`), **no artifacts** (`HF_MLFLOW_LOG_ARTIFACTS` is off) and nothing about *which data*. → log dataset digests, base-model revision, prompts, split seed and the eval report yourself.
- **Aliases:** one alias → one version; setting `champion` on v2 removes it from v1 (verified). `latest` (any case) and `v<digits>` are **reserved**; `.` is rejected; `-` is allowed. A deleted alias raises on lookup. `models:/kb-embedder@champion` resolves to that version's files.
- **Pickled models:** `mlflow.pyfunc.log_model(python_model=<object>)` serialises with **CloudPickle** — MLflow itself warns that deserialising can execute code. The sketch logs the pyfunc **from code** (a file path; nothing pickled), and kb-agent never calls `pyfunc.load_model` on registry content: it downloads the *artifacts* by version, checks file hashes and golden vectors, and hands the directory to fastembed. `registry.download()` refuses entries containing `*.pkl`.
- **Server defaults** (`mlflow server --help`, 3.17): binds `127.0.0.1:5000`, `--allowed-hosts` defaults to localhost + private IPs (DNS-rebinding guard), CORS to localhost origins; `--app-name basic-auth` has **no default admin password** and refuses to start without one (`MLFLOW_AUTH_ADMIN_PASSWORD`). The `--disable-security-middleware` flag is labelled DANGEROUS.
- Minor: MLflow 3.17 prints a one-line hint when it detects a coding-agent environment variable (`CLAUDECODE`, `AI_AGENT`, …); `MLFLOW_DISABLE_AGENT_HINT=1` silences it. Irrelevant in your own terminal.

### 2.4 Two aliases — the switch and the record

kb-agent ends up with **two** alias systems, and mixing them up recreates the bug from #9 (same-dimension model swap → silent garbage):

| | Qdrant `kb_current` | MLflow `champion` |
|---|---|---|
| What it is | **the switch**: which collection answers users | **the record**: which model version is live |
| Who reads it | every search request | dashboards, the next index build, humans |
| Changes when | the rollout flips it (atomic, #9) | *after* the flip and smoke succeeded |

The query embedder must match the collection's vectors. So the service **resolves its embedder from the manifest of the collection that `kb_current` points to — by immutable version — never from `@champion`.** E3-f reproduced the failure mode: `champion` moved to v2 while `kb_current` still pointed at the v1 build; a service loading "the champion" would have embedded queries with v2 against v1 vectors. The manifest check (`check_serving`) refuses that combination.

Manifest (in collection `metadata`, extends the #9 design):

```json
{"embedder": {"registry": "kb-embedder", "version": "7", "fingerprint": "ep-3f…",
              "dim": 768, "query_prefix": "query: ", "passage_prefix": "passage: "},
 "chunking": {"size": 1000, "overlap": 150},
 "score_threshold": 0.78,
 "build_id": "b2026-11-03-1"}
```

For a **query-only adapter**, the manifest needs two entries — `document_embedder` (what built the vectors) and `query_embedder` (base + adapter version) — and the serving check compares both. In P1 (no registry yet) put the Hugging Face revision in `version` (`hf:<commit>`); the same code carries registry versions later.

Collection names include the version: `kb__{model}__{dim}__{chunk}__r{version}` (fixes the 2026-10-13 naming-collision finding).

### 2.5 Rollout and rollback

Extends the #9 procedure (`rollout.py`):

1. **Build** `kb__…__r{v}` from the downloaded artifacts (by version), with its manifest.
2. **Validate** by collection name: counts, indexes, `kb-eval retrieval --collection`, parity, **recalibrated threshold** (#11 — scores shift with the model).
3. Set MLflow `challenger = v` (only allowed when the version's `gate` tag is `promote`).
4. **Flip** `kb_current` with **compare-and-swap**: read the current target, abort if it isn't the one you validated against (another rollout happened), then delete + create in **one** `update_collection_aliases` call (atomic, #9). Also serialise rollouts (a CI concurrency group) — CAS is check-then-act.
5. **Smoke** through the live alias (a few golden queries, manifest check). On failure: flip back automatically; the registry is untouched.
6. **Record:** `champion = v`, `previous_champion = old`, drop `challenger`.
7. Keep the old collection for N days (rollback = flip back + record); then gc.

Optional later: **shadow evaluation** — for a sample of live queries, also search the challenger collection and log both result lists (no user impact) before flipping. Only worth it once real traffic exists.

### 2.6 Where MLflow runs in kb-agent

- **Locally on the Mac**, not in the Compose stack by default: `mlflow server --backend-store-uri sqlite:///…/.mlflow/mlflow.db --default-artifact-root …/.mlflow/artifacts` (or just the SQLite URI without a server). Add `mlflow.db`, `.mlflow/`, `mlruns/` to `.gitignore`; artifacts never go to git.
- **Phoenix stays the tracing system** (D21). MLflow 3 also has GenAI tracing — don't enable a second tracer in the AI service; MLflow is for training runs, the registry and benchmark campaigns.
- **CI** never trains (D20 spirit: deterministic, free). CI may run the parity + gate *checks* on artifacts already registered.
- P5: the registry backend could move to Postgres + Blob; not needed for a single-developer portfolio.

### 2.7 Plan mapping

| Plan item | What this batch adds |
|---|---|
| §0 / §13.4 "MLflow … rollout/rollback via Qdrant alias" | split into **switch** (Qdrant alias) and **record** (MLflow alias); manifest pins the version |
| D10 | collection name with `r{version}`; manifest `embedder.{registry,version,fingerprint}` (+ query/document sides for adapters) |
| D21 | MLflow for training/registry only; Phoenix for traces |
| D26 / repo hygiene | `.gitignore` for MLflow stores; telemetry off |
| Appendix A | `MLFLOW_TRACKING_URI`, `MLFLOW_DISABLE_TELEMETRY=true` |
| new ADR-0020 | registry, aliases, rollout/rollback, retention of old collections |

### 2.8 Pitfalls

- Loading the embedder via `@champion` instead of the collection's manifest (E3-f).
- Moving the registry alias *before* the Qdrant flip and smoke.
- Relying on the Trainer callback for provenance — it logs 118 arguments and no dataset.
- MLflow's default SQLite file in whatever directory you ran from → runs scattered over several databases.
- Loading pickled pyfunc models from a registry (code execution).
- Using stages (deprecated) or reserved alias names (`latest`, `v3`).
- Rolling out without recalibrating the threshold (#11).
- Two rollouts at once without CAS + a lock.
- Deleting the old collection immediately → no rollback.

### 2.9 Self-check (#56)

8. What exactly would you log for a fine-tuning run so that you could rebuild the same model in a year? Which of it does the Trainer callback log for you?
9. Why does kb-agent need both a Qdrant alias and an MLflow alias, and which one must the query embedder follow?
10. In which order do flip, smoke and `champion` happen, and what happens on a failed smoke?
11. Why is compare-and-swap on the alias needed even though the flip itself is atomic?
12. Why does the sketch log the pyfunc "from code" and refuse `*.pkl` on download?
13. What changes in the manifest when you ship a query-only adapter?

---

## 3. #57 Local inference & quantization

### 3.1 Why (first)

Running the LLM on your own Mac gives you: **no third party** in the data path (#19 — the strongest privacy control there is), zero marginal token cost, offline work, and a hands-on understanding of what the API hides (context windows, KV memory, sampling defaults). It costs you: RAM that the rest of the stack also needs (A1), slower generation, lower quality per GB, and operations work (versions, templates, settings). That's why the plan puts it in P6, after the hardware upgrade — and why the benchmark (#58) decides per role instead of "local everywhere".

Local ≠ private by itself (#19): traces, logs and caches still hold prompts. And one runtime ships a remote mode under a local-looking name (§3.5).

### 3.2 How inference spends memory and time

**Two phases.** *Prefill* reads the whole prompt at once (matrix–matrix work → compute-bound; measured here 169–411 tokens/s). *Decode* produces one token at a time and must stream **all weights** through the processor for every token (→ memory-bandwidth-bound; 21–78 tokens/s here). So:

- time to first token ≈ prompt tokens ÷ prefill speed (+ model load if cold),
- decode speed ≤ memory bandwidth ÷ weight bytes — an **upper bound**.

**Memory = weights + KV cache + compute buffers.**

- Weights: parameters × bits per weight ÷ 8. Llama-3.1-8B at Q4_K_M: 8.03 B × 4.89 ÷ 8 = **4.58 GiB** (matches the llama.cpp README row; `weights_gib()` test).
- KV cache: 2 (K and V) × layers × context × parallel slots × KV heads × head dim × bytes per element. Verified exactly against llama-server's own log: 16 layers × 8,192 × 4 × 128 → **256.00 MiB** at f16, **136.00 MiB** at q8_0 (`-ctk q8_0 -ctv q8_0`, needs flash attention). For the 8B example (32 layers, 8 KV heads, 128 dim): **1 GiB at 8k, 4 GiB at 32k** per slot — the context window you ask for is real memory.
- Compute buffers: a few hundred MB, model-dependent (estimate 0.8 GiB in the sketch; measure).

**Apple Silicon specifics.** CPU and GPU share one memory pool, but Metal only lets the GPU use its **`recommendedMaxWorkingSetSize`** — a value macOS sets below total RAM (commonly about two-thirds to three-quarters; read it in the llama.cpp/Ollama startup log, it is printed there). That number, minus what Keycloak + Postgres + Qdrant + Phoenix + the embedder + dev servers + the browser already use, is your real budget. Containers on macOS run in a Linux VM **without Metal**, so the model server runs natively and containers reach it via `host.docker.internal`.

### 3.3 Quantization

Quantization stores weights with fewer bits: blocks of 32–256 weights share a scale (and offset), each weight keeps 2–8 bits. Families in llama.cpp's GGUF:

- **Legacy** `Q4_0`, `Q8_0`: one scale per block of 32. Simple and fast.
- **K-quants** `Q2_K`…`Q6_K` with `_S/_M/_L` mixes: super-blocks with quantized scales; `_M` keeps sensitive tensors (attention V, FFN down) at higher precision.
- **I-quants** `IQ1`…`IQ4`: lattice codebooks for very low bits; really want an **importance matrix** (`llama-imatrix` on calibration text, then `llama-quantize --imatrix`).

Quality loss, from llama.cpp's own scoreboard (Llama 3 8B, Wikitext, CUDA, revision f364eb6f — their numbers, not re-run here). KLD = KL divergence of the next-token distribution vs FP16; "same top" = share of positions where both pick the same most-likely token:

| Type | Size (GiB) | KLD | KLD with imatrix | Same top token |
|---|---|---|---|---|
| f16 | 14.97 | — | — | — |
| Q8_0 | 7.96 | 0.0014 | — | 97.7 % |
| Q6_K | 6.14 | 0.0055 | — | 96.0 % |
| Q5_K_M | 5.33 | 0.0108 | — | — |
| **Q4_K_M** | **4.58** | **0.0313** | 0.0282 | **91.9 %** |
| IQ4_XS | 4.14 | — | 0.0363 | — |
| Q4_0 | 4.34 | 0.0719 | — | — |
| Q3_K_M | 3.74 | 0.1019 | 0.0844 | — |
| Q2_K | 2.96 | 0.4451 | 0.3314 | 71.1 % |

How to read it for kb-agent:

- **Q8_0 is near-lossless, Q4_K_M is the usual size/quality knee, below Q4 losses climb steeply.**
- At Q4_K_M about **1 position in 12** picks a different top token than FP16 → greedy answers diverge within the first lines. You can't compare outputs textually; only **task metrics** (citations valid, refusals right, JSON valid, tool chosen right) tell you whether it matters.
- The same README shows Llama 2 7B losing much less at Q4_K_M (KLD 0.0127) than Llama 3 8B (0.0313): models trained on more data **quantize worse**. Per-model measurement, not a rule of thumb.
- Perplexity is measured on English Wikitext. Your workload is German + English + YAML + citations → run your own eval (#58).

**Measured here** (E5: the random-weight 415M Llama, `llama-quantize` + `llama-bench -p 256 -n 64 -t 2 -r 3`, 2-vCPU Xeon — sizes are architecture facts, speeds are this CPU only):

| Type | MiB | Bits/weight | Prefill t/s | Decode t/s |
|---|---|---|---|---|
| f16 | 791.6 | 16.00 | 169 ± 17 | 20.6 ± 0.8 |
| Q8_0 | 420.6 | 8.50 | 411 ± 75 | 53.9 ± 2.4 |
| Q6_K | 324.8 | 6.57 | 267 ± 1 | 25.4 ± 1.1 |
| Q5_K_M | 280.2 | 5.66 | — | — |
| Q4_K_M | 238.2 | 4.82 | 393 ± 21 | 44.1 ± 1.4 |
| Q4_0 | 224.3 | 4.53 | 398 ± 56 | 78.2 ± 9.2 |
| IQ4_XS | 214.0 | 4.33 | — | — |
| Q3_K_M | 192.6 | 3.89 | — | — |
| Q2_K | 147.6 | 2.98 | 271 ± 4 | 48.5 ± 2.6 |

**Smaller isn't automatically faster:** Q2_K and Q6_K decoded *slower* than Q8_0, Q4_K_M slower than Q4_0. The effective weight-read rate ranged 7.5–24 GB/s by type — on this CPU, dequantisation work limits decode, not only bandwidth. Metal kernels differ → run `llama-bench` on the Mac before choosing a type.

### 3.4 Sizing for the Mac

Decode upper bounds from Apple's published memory bandwidth, for 8B-class Q4_K_M weights (4.9 GB): **M1** (68 GB/s) ≤ ~14 tokens/s · **M1 Pro** (200 GB/s) ≤ ~41 · **M1 Max** (400 GB/s) ≤ ~81. Real numbers are lower. (The 2021 MacBook Pros shipped with M1 Pro or M1 Max — check which chip you have; it changes the answer by 2×.)

Memory check (`fits()` in the sketch; budget = Metal working set, overhead 0.8 GiB estimated):

| 8B-class model | Context | Weights + KV + overhead | 16 GB Mac (~10–11 GiB working set, minus the stack) | 32 GB Mac (~20–24 GiB) |
|---|---|---|---|---|
| Q4_K_M | 8k | 4.58 + 1.0 + 0.8 ≈ **6.4 GiB** | tight next to the full stack | comfortable |
| Q4_K_M | 32k | 4.58 + 4.0 + 0.8 ≈ 9.4 GiB | no | ok |
| Q8_0 | 8k | 7.95 + 1.0 + 0.8 ≈ 9.8 GiB | no | ok |
| 14B-class Q4_K_M | 8k | ≈ 8.0 + KV + 0.8 | no | ok (KV depends on the architecture) |

The working-set fractions are typical values, not measured here — read yours from the log. Measure the stack's own footprint first (`docker stats` + Activity Monitor) — the plan's A1 risk becomes a number. Ollama's built-in recommendations (source) list `gemma4` at 12 GB and `qwen3.5` at 14 GB for local use: both beyond a 16 GB Mac's working set.

### 3.5 Runtimes and their quirks

All three expose an OpenAI-compatible endpoint, so `openai_compat` with a different `LLM_BASE_URL` reaches them (D11). They differ in defaults that silently change behaviour (`local_runtime.QUIRKS`):

| | **llama-server** (llama.cpp) | **Ollama `/v1`** | **mlx_lm.server** |
|---|---|---|---|
| Evidence | **run** (master 529ac89) | source (master f5be23f) | source (0.32.0) |
| Default bind | `127.0.0.1:`**`9931`** (not 8080 any more) | `127.0.0.1:11434` | `127.0.0.1:8080` |
| Auth / CORS default | none; **reflects any Origin with credentials** (startup warning); `--api-key`, `--cors-origins` | none; `OLLAMA_ORIGINS` + localhost/`app://`/`file://`/`vscode-webview://` | none; `--allowed-origins` default `*`; "not recommended for production" |
| Temperature if omitted | **0.8**, random seed → 3/3 different answers | **1.0** (and `top_p` 1.0 — overrides Modelfile defaults) | **0.0** |
| Streaming usage | only with `include_usage` (verified) | only with `include_usage` | only with `include_usage` |
| Prompt longer than context | **400** `exceed_context_size_error` with `n_prompt_tokens`, `n_ctx` | **silent**: oldest non-system messages dropped (debug log); an over-long last message is cut keeping 4 tokens + the tail (warn log) | no check found |
| Context size | `-c` at start (0 = model default) | default **4,096** unless GPU memory ≥ 23 GiB (32k) / ≥ 47 GiB (256k); on a Mac "GPU memory" = Metal working set; not settable per request via `/v1` | model default |
| `tool_choice` | strings work; the **named-object form is ignored** with a warning → default | **not in the request struct → ignored** | not handled |
| `response_format: json_schema` | grammar-constrained (5/5 valid from random weights) | mapped to native `format` (constrained) | not handled |
| Disconnect | **stops generating** (5 chunks read → 8 tokens total, slot idle) | not verified | not verified |
| Prompt cache | on: identical prompt → 1 new token processed of 633; `cached_tokens` in usage | yes (llama.cpp inside) | yes |
| Other | `timings` in every response; `/props` names the model file + build; `/metrics` | `keep_alive` 5 min → cold load after idle; **`:cloud` / `-cloud` models run on Ollama's servers** (`OLLAMA_NO_CLOUD=1` disables); bundles llama.cpp b11521 + an MLX runner | `--max-tokens` default 512 |

What this means for kb-agent:

- **Ollama's 4k default is the dangerous one.** On a 16 GB Mac — and, with typical working-set fractions, a 32 GB one too — the Metal working set stays below 23 GiB → 4,096 tokens. The P1 prompt (~1.3k tokens) fits; a P2 agent turn with tools and several tool results does not — and Ollama drops the oldest messages *without an error*. The #12 log of estimate/actual tokens catches it after the fact (`truncation_suspect()`); `context_check()` refuses before sending. Set `OLLAMA_CONTEXT_LENGTH` (server) or `PARAMETER num_ctx` in a Modelfile — the OpenAI endpoint can't set it per request.
- **`tool_choice: "none"` at the step limit (#26) is not honoured by Ollama** → the harness rule "never execute calls past the limit" is the real control, not the parameter.
- **Sampling defaults disagree three ways (0.8 / 1.0 / 0.0)** → the model profile always sends `temperature`, `top_p`, `seed`, `max_tokens` (#38 already says so; now it's proven necessary).
- **Grammar-constrained JSON is syntax, not sense.** The random-weight model produced `"confidence": 1.6766E6041001872001191` — valid JSON grammar; `json.loads` → `inf`; Pydantic 2.14 accepts `inf` for a plain `float` and rejects it with `Field(ge=0, le=1)`. Bounds in every schema (#27).
- **Lock the server down:** bind 127.0.0.1, set `--api-key` and `--cors-origins` (llama-server) — otherwise any web page you visit can call your model through the browser.
- **`OLLAMA_NO_CLOUD=1`** if you use Ollama: a `…:cloud` model name sends prompts to a third party, which turns the local arm of the benchmark and the D25 data class into something else.

**Recommendation:** llama-server as the **reference runtime** for the P6 benchmark (explicit 400s, `/props` for provenance, `timings`, known cancellation); Ollama only with `OLLAMA_CONTEXT_LENGTH`, `OLLAMA_NO_CLOUD=1`, explicit sampling and the context check; mlx-lm as an optional speed comparison on the Mac (MLX models can be faster on Apple Silicon — measure, it lacks tool/JSON handling in the server). LM Studio and vLLM weren't examined (vLLM is built for server GPUs).

**Chat templates matter.** A GGUF carries its chat template; tool calling and JSON grammars depend on the template being recognised. Building a custom GGUF here, a template/tokenizer mismatch made every `json_schema` request fail with "Failed to initialize samplers" until the tokenizer metadata was fixed. Use official GGUFs, note the template in the model profile, and include tool-call and JSON items in the benchmark.

### 3.6 Determinism (E6b)

- Unseeded requests at the server default: 3 of 3 answers different. Seeded (`seed=7`, temperature 0.8): 3 of 3 identical.
- Same seeded request alone vs next to 3 concurrent requests (`--parallel 4`): **20/20 identical** (tiny model) and **10/10** (415M model), at temperature 0 and seeded 0.8 — **on CPU**. That's better than the GPU-server result cited in Batch 7 (Thinking Machines: no batch invariance). Metal wasn't tested; check it on the Mac before relying on repeat-1 benchmarks.

### 3.7 Plan mapping

| Plan item | What this batch adds |
|---|---|
| D11 `openai_compat` | runtime profiles: `runtime`, `context_window`, explicit sampling, quirk flags; map 400 `exceed_context_size_error` → `Failure(kind="context_overflow", retryable=False)` |
| D18 / A1 | measure the stack's RSS + the Metal working set before picking a model size; native model server + `host.docker.internal` |
| D19/D25 | new data class `local` (no third party); Ollama `:cloud` names are third-party → `OLLAMA_NO_CLOUD=1` |
| §11 risks | silent context truncation (Ollama), template-dependent tool calling, open local port with permissive CORS |
| Appendix A | `LLM_CONTEXT_WINDOW`, `OLLAMA_CONTEXT_LENGTH`, `OLLAMA_NO_CLOUD=1`, `OLLAMA_KEEP_ALIVE`, `LLAMA_API_KEY` (llama-server) |
| new ADR-0021 | local runtime + model + quant type, sized from measured budget |

### 3.8 Pitfalls

- Choosing a model by total RAM instead of the Metal working set minus the stack.
- Asking for 32k context "just in case" — that's 4 GiB of KV for an 8B model.
- Trusting Ollama's default context (4k) with agent prompts; truncation is silent.
- Omitting sampling parameters — three runtimes, three defaults.
- Assuming a smaller quant is faster (E5: Q2_K slower than Q8_0 on CPU).
- Reading perplexity tables as kb-agent quality (English Wikitext, not German RAG with citations).
- Leaving llama-server open with reflected CORS and no API key.
- Running the model server in Docker on macOS (no Metal).
- Using a `…:cloud` Ollama model and calling it local.

### 3.9 Self-check (#57)

14. Why is decode memory-bandwidth-bound while prefill is compute-bound, and what does that predict for TTFT vs tokens/s?
15. Compute weights + KV for an 8B model (32 layers, 8 KV heads, head dim 128) at Q4_K_M with a 16k context.
16. What does "same top token 91.9 %" at Q4_K_M mean for comparing a local answer with the FP16/API answer?
17. Ollama on your 16 GB Mac: what is the default context, what happens to a 6k-token agent turn, and how do you notice?
18. Name three defaults that differ between llama-server, Ollama `/v1` and mlx-lm, and the one-line fix.
19. Why can constrained JSON decoding still produce an invalid `RouteDecision`?

---

## 4. #58 Local vs. API model benchmarking

### 4.1 Why (first)

"Is the local model as good?" has no answer. "**For which role** (answer, router, judge, agent), is local **non-inferior within a margin I wrote down first**, at what latency, cost and memory?" does. kb-agent already has the pieces — eval sets, graders, paired statistics, model profiles. The benchmark is mostly *discipline*: same inputs, explicit settings, honest timing, and a decision rule.

### 4.2 Design

**Arms** — four, so that the result separates *which model* from *how it's run*:

| Arm | Purpose |
|---|---|
| A — the current API model (ADR-0005) | the reference |
| B — the **same open-weights model** via an API provider | model gap vs A, with server-grade weights (providers may quantize too — #13: pin and record the provider) |
| C — that model locally at Q8_0 | runtime gap (B vs C) |
| D — locally at Q4_K_M (or what fits) | quantization gap (C vs D) |

**Suites** (all already exist or are planned): `generation_v1` (structural checks + calibrated judge, #40/#41), abstention and citation validity, a **German slice**, `routing_v1` / structured outputs (#27/#29), `agent_v1` tool selection (#42 — note the `tool_choice` quirks), the injection set (#46 susceptibility). Retrieval isn't affected — the embedder already runs locally.

**Metrics per arm:** quality (per suite, per slice), TTFT p50/p95, decode tokens/s, end-to-end p50/p95, failures (400s, `length`, invalid JSON, suspected truncation), cost per task (API: billed `usage.cost`; local: ≈ $0 marginal — report energy separately, e.g. `sudo powermetrics` on macOS), peak memory.

**Same code path:** every arm goes through the production `openai_compat` client with the model profile's explicit sampling and `include_usage` — the harness (`bench.py`) uses the `openai` SDK the same way, `max_retries=0` (a retry hides latency).

### 4.3 Measurement hygiene (what E7 showed)

E7 ran the harness against three llama-server arms (random-weight 415M model, 12 RAG-shaped prompts of ~276 tokens, 3 repeats, interleaved):

| Arm | TTFT p50 / p95 (s) | e2e p50 / p95 (s) | Decode t/s | Cached share of prompt tokens |
|---|---|---|---|---|
| Q8_0 | 0.04 / 1.00 | 1.10 / 2.21 | 47.4 | 75 % |
| Q4_K_M | 0.03 / 0.81 | 1.31 / 1.98 | 38.9 | 86 % |
| Q4_K_M, `cache_prompt: false` | 0.87 / 1.08 | 2.05 / 2.41 | 39.0 | 0 % |

- **Prompt cache:** first repeat TTFT 0.80 s (Q8_0) → later repeats **0.04 s**. A benchmark that repeats prompts measures the cache, not the model. For TTFT either disable it (`{"cache_prompt": false}` on llama-server), or count only first sightings, and always record `cached_tokens`.
- **Shared server = shared cache:** the Q4_K_M arm's *first* repeat averaged 0.40 s vs 0.86 s for the no-cache arm. Checked per item: in all 5 items where the no-cache arm (same server) ran first, the cached arm's first TTFT was **0.03–0.05 s**; where it ran first, 0.55–1.08 s. One server per arm, or the arms contaminate each other.
- **Warm-up:** report the first request per arm separately (cold load / first-run allocation; Ollama's `keep_alive` of 5 min makes it recur after idle) — and **warm up with a prompt that isn't a benchmark item**. My first harness version warmed up with item 1, which pre-cached it (0.03 s); `bench.run()` now refuses that.
- **Interleaving:** repeat-major, arm order shuffled per (repeat, item) with sha256 seeds → slow drift (thermal throttling on a laptop, background load, provider load) spreads over arms. Plugged in, Low Power Mode off, nothing else running; compare first vs last third of the campaign to detect drift.
- **Determinism:** explicit seed + temperature; on CPU the seeded output didn't depend on concurrency (E6b) — re-check on Metal and keep 3 repeats for API arms (OpenRouter `seed` is best-effort, #38).
- **Context:** set the same context window on every local arm and check that no request was truncated (llama-server would 400; Ollama would silently drop).
- **Templates:** log the chat template / model file (`/props` on llama-server); a different template is a different system.

### 4.4 Statistics and the decision rule

Reuse Batch 12's non-inferiority setup (`paired_noninferiority()`): per-item pass rates averaged over repeats, item-clustered bootstrap of the mean difference vs the reference, margin written first.

- **superior** if the CI's lower bound > 0, **non-inferior** if lower bound > −margin, **inferior** if upper bound < −margin, else **inconclusive**.
- Power is the hard part: at 45 items × 3, an *identical* system is confirmed non-inferior only ~34 % of the time (5-point margin, E3 of Batch 12); ~190 items × 3 are needed for 80 %. Expect **inconclusive** on small suites unless the gap is big — so the rule must say what inconclusive means (e.g. "keep the API model for answers; local allowed for roles where privacy outweighs").
- Decide **per role**: a local model can be non-inferior as a router (short JSON) and inferior as an answer writer (long German text with citations).

Template for ADR-0022:

```
Role: answer | router | judge | agent
Suites + slices: …            Margin: 5 pts (answer), 3 pts (router accuracy)
Latency budget: TTFT p95 ≤ … s, e2e p95 ≤ … s        Memory: fits budget from §3.4
Outcome map: superior/non-inferior + budgets ok → local allowed for this role
             inconclusive → keep API (or: local only for D25 class "private")
             inferior → API
```

### 4.5 Report

One table per role (the `report_md()` shape), a quality-vs-cost and quality-vs-latency scatter (Pareto front), the environment block (runtime build, model file, quant, template, context, sampling, chip, macOS version, power state), and the trial log (`e7_trials.jsonl` shape). The result is evidence for the system card (#59): "local model X is used for role Y; measured gap Z on suite S".

### 4.6 Plan mapping

| Plan item | What this batch adds |
|---|---|
| §0 P6 "local-vs-API benchmark" | four-arm design, per-role decisions, hygiene list |
| §13.4 | the benchmark reuses the eval sets and graders of P3 — no separate quality metric |
| D20 | benchmark campaigns are manual/scheduled (local machine + eval key), never CI |
| D24 | API arms run on the eval key with a cost stop (#42) |
| new ADR-0022 | decision rule per role |

### 4.7 Pitfalls

- Repeating prompts with the prompt cache on (TTFT 20× too good, E7).
- Two arms on one server (shared cache).
- Comparing a local Q4 of model X with API model Y and calling the gap "quantization".
- Different chat templates, context sizes or sampling defaults across arms.
- Judging locals with a judge calibrated on API answers only (re-check calibration on local outputs, #41).
- One run, no interleaving, laptop on battery.
- Treating "inconclusive" as "equal".

### 4.8 Self-check (#58)

20. Why four arms instead of "API vs local"?
21. Your local arm's TTFT is 0.04 s on repeats and 0.8 s on first sight. What happened, and what do you report?
22. How did two arms on one llama-server contaminate each other in E7?
23. With 45 items × 3 repeats, the local answer model comes out "inconclusive" at a 5-point margin. What does your decision rule do, and why is that likely?
24. Name four things you must record in the environment block so the result can be reproduced.

---

## 5. Pieces that fit earlier (P1–P3)

| When | Piece | Why now |
|---|---|---|
| P1 · M1.2 | Collection name `kb__{model}__{dim}__{chunk}__r{version}` and manifest `embedder.{registry,version,fingerprint}` with `version = "hf:<revision>"` | the same code carries registry versions in P6; closes the naming-collision finding |
| P1 · M1.3 | `openai_compat`: map 400 `exceed_context_size_error` → `context_overflow` (not retried); always send `temperature`, `top_p`, `seed`, `max_tokens`, `include_usage` | costs nothing; already required by #38; proven necessary by E6 |
| P1 · M1.0 | `.gitignore`: `mlflow.db`, `.mlflow/`, `mlruns/`, `*.gguf`, `models/` | keeps artifacts and weights out of git from day one |
| P3 · #44 | synthetic generator records the source chunk's `doc` + `heading` + `origin`, and skips golden-set groups | the training firewall and group split need it; retrofitting is painful |
| P3 · corpus | `translation_of` / `implements` relations in document metadata (DE/EN pairs, ADR ↔ runbook) | `same_fact` for hard-negative filtering; also useful for dedupe in answers |
| P3 · harness | rule "never execute calls past the step limit" stays the control (Ollama ignores `tool_choice`) | already in #26; now with a reason |

---

## 6. Plan change list (for plan v3 / the Phase 6 plan)

1. **§0 P6 + §13.4:** "MLflow model registry + alias-based rollout" → "MLflow records runs and versions; the **Qdrant alias is the switch**, the MLflow alias is the record; the service follows the collection manifest by version".
2. **D10:** collection name with `r{version}`/build id; manifest `embedder.{registry, version, fingerprint, dim, prefixes}` (+ `document_embedder`/`query_embedder` for adapters), `score_threshold` per build.
3. **D9 / ADR-0004:** note fine-tunability (licence permits derivatives; trainable on the Mac) as a criterion; record the base model's revision in the manifest.
4. **D11:** model profile gains `runtime`, `context_window`, explicit sampling (always sent), quirk flags; `context_overflow` failure kind; pre-send `context_check` for runtimes that truncate silently.
5. **D18 / A1:** replace "≥ 16 GB RAM" with a measured budget: Metal `recommendedMaxWorkingSetSize` − measured stack RSS; local model server runs natively (no Metal in Docker on macOS).
6. **D19 / D25:** data class `local` (no third party); `OLLAMA_NO_CLOUD=1`; local traces/logs still follow #19 retention rules.
7. **D20:** CI never trains or benchmarks; CI may run parity + gate checks on registered artifacts.
8. **D21:** MLflow for training/registry/benchmarks only; Phoenix remains the tracer (no MLflow tracing in the AI service).
9. **D23:** golden sets are a training firewall; any trained-near golden set is reported seen/unseen.
10. **D26:** MLflow telemetry off (`MLFLOW_DISABLE_TELEMETRY=true`) in every environment; registry entries without pickles (models from code).
11. **§6 layout:** `training/` (configs, frozen pair files, scripts, `pairs_v1.jsonl`) — excluded from ingestion like `evals/`; `bench/` campaign configs.
12. **Appendix A:** `MLFLOW_TRACKING_URI`, `MLFLOW_DISABLE_TELEMETRY=true`, `LLM_CONTEXT_WINDOW`, `OLLAMA_CONTEXT_LENGTH`, `OLLAMA_NO_CLOUD=1`, `OLLAMA_KEEP_ALIVE`, `LLAMA_API_KEY` / `LLAMA_ARG_CORS_ORIGINS` (llama-server), `EMBEDDER_REGISTRY_VERSION` (pin for index builds).
13. **§11 risks:** eval contamination by synthetic training data; registry/index mismatch; silent context truncation; benchmark artefacts (cache, warm-up, thermal, shared servers); open local model port.
14. **New ADRs:** ADR-0019 fine-tuning go/no-go + decision rule · ADR-0020 registry, aliases, rollout/rollback, retention · ADR-0021 local runtime + model + quant (sized from measurements) · ADR-0022 local-vs-API decision rule per role.

---

## Appendix A — Answer key

1. Parsing errors (→ better parser/Docling), split context (→ chunking, heading path, contextual retrieval), missing documents (→ corpus gap). Also exact tokens (→ BM25) and ordering (→ reranker).
2. Every other passage in the batch is a negative, so more batch = more and harder negatives. `NO_DUPLICATES` keeps identical texts out of one batch, where one copy would be a false negative for the other's query.
3. Questions about the same section land on both sides; the retriever learned that section from the sibling question. Split by section group (`doc#heading`), with sha256 buckets.
4. Pairs whose section appears in any golden set never enter training. Fallback: train on them, but gate only on the golden items whose sections are unseen, and report seen/unseen separately.
5. From unlabelled positives — another chunk of the same section/document, or the same fact in another document (DE/EN, ADR ↔ runbook). Free filter: exclude the positive's own document/section (labels are doc + heading); then skip-top and an audit sample; `same_fact` for cross-document duplicates.
6. Full fine-tune changes document vectors → re-index. Query-only adapter leaves document vectors untouched → no re-index (manifest records both sides). Reranker fine-tune touches only the second stage → no re-index.
7. No. E4: a missing `query: ` prefix still scored 0.989. Require ≥ 0.999 for fp32; for int8, own golden vectors + retrieval eval.
8. Dataset sha256s, base model + revision, prompts/prefixes, loss + hyperparameters, split seed + group rule, code commit, eval report (unseen + slices), export parity, profile fingerprint, environment lock. The callback logs only `TrainingArguments` and loss/throughput — no data, no prefixes, no eval report.
9. Qdrant's alias decides what users get (the switch); MLflow's alias records which version is live. The query embedder follows the manifest of the collection behind the Qdrant alias, by version.
10. Flip (CAS + atomic) → smoke through the live alias → record `champion`. Failed smoke → automatic flip back, registry unchanged.
11. Atomicity protects readers during one flip; CAS protects against two rollouts overwriting each other (one validated against a target that is no longer live). Plus a lock, since CAS is check-then-act.
12. A pickled pyfunc executes code when loaded; logging from a code file stores no pickle, and kb-agent only uses the artifacts. Refusing `*.pkl` keeps a tampered or legacy entry from slipping through.
13. Two entries: the document embedder (built the vectors, unchanged) and the query embedder (base + adapter version); `check_serving` compares both.
14. Decode streams all weights per token (little compute per byte), prefill does many tokens per weight read (compute). TTFT grows with prompt length and prefill speed; tokens/s is capped by bandwidth ÷ weight bytes.
15. Weights 8.03 B × 4.89 / 8 ≈ 4.58 GiB; KV = 2 × 32 × 16,384 × 8 × 128 × 2 B = 2 GiB; plus ~0.8 GiB buffers ≈ 7.4 GiB.
16. About 1 position in 12 picks a different top token → greedy answers diverge early; compare by task metrics (citations, refusals, JSON validity, judge), never by text identity.
17. 4,096 tokens (working set < 23 GiB). Oldest non-system messages are dropped silently (only a debug log). You notice via the estimate/actual token ratio (#12), or prevent it with `context_check` + `OLLAMA_CONTEXT_LENGTH`.
18. Temperature (0.8 / 1.0 / 0.0), seed (random unless set), max tokens (mlx-lm 512), context size, `tool_choice` handling. Fix: the model profile always sends sampling parameters explicitly (and sets the context server-side).
19. The grammar guarantees syntax and enum values, not ranges: an unbounded `number` produced `1.67E6041001872001191` → `inf`; Pydantic accepts `inf` for a plain `float`. Use `Field(ge=…, le=…)`.
20. To separate model choice (A vs B), runtime (B vs C) and quantization (C vs D) — otherwise every difference is called "local".
21. The prompt cache answered the repeats. Report first-sighting TTFT (or run with `cache_prompt: false`) and the cached-token share.
22. The no-cache arm processed the prompt first on the same server, which left it in the cache, so the cached arm's "first" request was already warm (0.40 s vs 0.86 s). One server per arm.
23. It applies the inconclusive branch (e.g. keep the API model for answers). Likely because 45 × 3 has ~34 % power to confirm even an identical system at a 5-point margin.
24. Any four of: runtime + build, model file (hash), quant type, chat template, context size, KV type, sampling parameters, chip + macOS version, power state, date, API provider + model id.

---

## Appendix B — Sketches and experiments

`batch-13-sketches.zip` — see its README. Modules: `splits`, `negatives`, `gates`, `profile`, `registry`, `rollout`, `local_runtime`, `bench`; tests: 34 pass (33 + 1 skipped without the E4 export) + 1 live (against llama-server); experiments E1–E7 with outputs.

## Appendix C — Sources

- llama.cpp (master `529ac89`, 14 Oct 2026): `tools/quantize/README.md` (sizes, speeds, imatrix), `tools/perplexity/README.md` (Llama 3 8B scoreboard, Llama 2 vs 3), `tools/server/README.md` (defaults, CORS, `--fit`, tools), `ggml/src/ggml-metal/ggml-metal-device.m` (`recommendedMaxWorkingSetSize`) — [github.com/ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp)
- Ollama (master `f5be23f`, 14 Oct 2026; release v0.40.4): `envconfig/config.go`, `server/routes.go`, `server/prompt.go`, `server/sched.go`, `llm/llama_server.go`, `openai/openai.go`, `server/model_recommendations.go`, `discover/` — [github.com/ollama/ollama](https://github.com/ollama/ollama)
- mlx-lm 0.32.0 `mlx_lm/server.py` (PyPI sdist) — [pypi.org/project/mlx-lm/0.32.0](https://pypi.org/project/mlx-lm/0.32.0/)
- MLflow 3.17.1 package source (`telemetry/`, `server/auth/basic_auth.ini`, `mlflow server --help`) — [pypi.org/project/mlflow/3.17.1](https://pypi.org/project/mlflow/3.17.1/)
- sentence-transformers 6.1.0 package source — [pypi.org/project/sentence-transformers/6.1.0](https://pypi.org/project/sentence-transformers/6.1.0/)
- Apple's published memory bandwidth for M1 / M1 Pro / M1 Max (68.25 / 200 / 400 GB/s)
- Earlier batches: #5 parity + sign test, #9 aliases + manifest, #12 token estimate, #38 explicit sampling, #42 clustered statistics, #44 synthetic data, Batch 12 E3 non-inferiority power
