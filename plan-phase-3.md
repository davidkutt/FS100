# plan-phase-3.md — Phase 3: Retrieval Quality, Skills, Evaluation, Safety & Cost

> **Project (working title):** `kb-agent` — an assistant for the **"Dev of the future"**.
> **Document scope:** Phase 3 of 6 (3a + 3b) · **Status:** Draft v1.1 · **Updated:** 2026-10-23 · builds on `plan.md` v2,
> `plan-phase-2.md` v1.1 and `roadmap-phases-3-6.md` v1.2
> **Estimated effort:** ~151 h core (3a ~75 h · 3b ~76 h; range 125–180 h) + up to ~22 h options · ~17 weeks at
> 8–10 h/week + 2 buffer weeks
> **Start:** 2026-10-23 with M3a.0 (planned: mid-February 2027); the end dates move up accordingly
> **Decisions taken for this plan:** workflow integration (MCP prompts for skills, headless API, repo sync) stays out of
> Phase 3 and becomes a Phase 5 option · planned for a **16 GB** Mac · the 3b options are decided at the start of 3b

### Review outcome (changes vs. `roadmap-phases-3-6.md` §3–§4)

| Change | Reason |
|---|---|
| **Kick-off milestones** M3a.0 (4 h) and M3b.0 (2 h) added | Several facts below need a spike before anything is built on them; Phase 3 grows from ~145 h to ~151 h |
| **Originals are stored** in a new `ai` database owned by the AI service | Re-indexing needs the source documents; Phase 1 doesn't keep originals (D7) |
| **Versioned point IDs and `lifecycle` move into the 3a re-index** | The collection is rebuilt for sparse vectors anyway; one migration instead of a second one in 3b |
| **Sparse side defaults to BM25**; bge-m3 learned sparse only as a challenger | FastEmbed lists neither a dense nor a sparse bge-m3 model; Qdrant offers BM25 with an IDF modifier and language-neutral processing (1.19) |
| **Reranker chosen by benchmark, with a licence check** | The only multilingual reranker in FastEmbed (`jina-reranker-v2-base-multilingual`) is CC BY-NC 4.0; `bge-reranker-v2-m3` is Apache-2.0 but brings PyTorch and ~0.6 B parameters |
| **Golden set split into `dev` and `test`** | Phase 3 tunes many knobs; reported numbers must come from data that wasn't used for tuning |
| **Judge runs weekly and on demand, not nightly** | Nightly runs at up to 2 USD each would cost ~60 USD a month |
| **Curator discovery via sitemaps of allow-listed hosts**; OpenRouter web search optional | No extra account; OpenRouter's `openrouter:web_search` supports `allowed_domains` and bills to the same credits |
| **Workflow integration stays out** | Decision for this plan; moves to Phase 5 as an option, where the cloud endpoint exists |
| **Resource budget for 16 GB** (D50) | Decides reranker size, spaCy models and where Docling runs |

---

## 0. Roadmap context

| Phase | Theme | Core hours | Result |
|---|---|---|---|
| 1 | Foundation + RAG slice + eval + tracing | ~76 | Streamed, cited answers; retrieval metrics; Phoenix traces; CI green |
| 2 | Agent | ~99 | Agent with MCP tools, approvals, conversations, audit, agent eval; taxonomy + gap signals |
| **3a (this doc)** | **Retrieval quality, sub-topics & skills** | **~75** | Hybrid + rerank + contextual + parent-child + code-aware RAG, eval-gated alias swap, priorities, skills |
| **3b (this doc)** | **Evaluation, safety, cost, KB curator** | **~76** | Calibrated judge gate, guardrails + red-team suite, ACL, cascade + semantic cache, memory, compaction, KB curator (L2) |
| 4 | Kubernetes | ~40 | Helm chart on k3d, TLS, network policies, read-only K8s tool, KB refresh job (L3) |
| 5 | Azure | ~46 | Terraform, AKS (ephemeral) + Container Apps demo, OIDC, Key Vault; workflow integration (option) |
| 6 | MLOps, local models, polish | ~60 | Fine-tuning + MLflow + alias rollout, local-vs-API benchmark, system card |

Details for Phases 4–6: `roadmap-phases-3-6.md`.

---

## 1. Goal and demo script

**Goal.** Phase 3 turns the working agent into a good and trustworthy one. By the end of **3a**, every retrieval
technique has a before/after row on a held-out test set, the corpus can be re-indexed from stored originals behind an
eval gate, the repo's own code is searchable, documents carry sub-topics and priorities, and the agent loads skills on
demand. By the end of **3b**, answer quality is measured by a calibrated judge and gated in CI, guardrails and ACL
filtering protect the system, a cascade and a semantic cache lower the cost per answer, the assistant remembers what
users want it to remember, long conversations stay within budget, and the KB curator closes knowledge gaps in
human-approved batches. Still local-first on a 16 GB Mac; OpenRouter is the only external service the core needs.

**Acceptance demo — 3a exit**

1. `pnpm kb:reindex` → builds `kb__v2__…` from stored originals, runs the golden `test` set, swaps `kb_current`;
   `pnpm kb:reindex --rollback` points the alias back.
2. The retrieval inspector shows, per hit, dense, sparse and fused rank, reranker score, priority boost and the parent
   section.
3. `pnpm eval:retrieval --split test --report techniques` prints the comparison table (P1 dense → hybrid → + rerank →
   + query transformation → + Docling/parent-child → + contextual → + priorities) per domain and language.
4. Ask *"Where is the approval signature verified?"* → `kb.search_code` returns the function with a `path:L12-L48`
   citation.
5. Mark the CI runbook `canonical` for `devops/ci-cd` → CI questions cite it first; the golden items for that sub-topic
   improve (otherwise the boost is reverted).
6. Ask *"Our nightly build fails with exit code 137 — triage it"* → the trace shows `load_skill(ci-failure-triage)`,
   then only the tools the skill allows.
7. Upload a PDF → the documents page shows `queued → parsing → contextualizing → embedding → ready`; the inspector
   shows Docling headings and tables.

**Acceptance demo — 3b exit**

8. A PR that weakens the answer prompt, labelled `eval:full` → the judge-based gate fails with per-metric deltas; the
   deterministic gate ran on the PR for free.
9. `pnpm eval:redteam` with guardrails on vs. off → pass rates per OWASP category; an issue with a hidden instruction is
   withheld and flagged in the trace.
10. Log in as `carol` (viewer, not in group `security`): restricted documents never appear — not in search, answers,
    code search, cache hits or MCP results.
11. Ask the same KB question twice in different words → the second answer is a marked cache hit; retire the cited
    document → the cache entry is gone.
12. Cost report: cost and judged quality per answer for cheap-only, strong-only and the cascade, with escalation
    reasons.
13. *"My goal is to learn Kubernetes networking"* → memory proposal → confirm → a later conversation uses it; the
    memory page lets you edit or delete it.
14. A 60-turn conversation stays within the context budget; facts from early turns are still answerable.
15. `pnpm curator:run` → gap clusters → candidates from allow-listed hosts → staged batch → promotion report → approve
    → the gap questions are answered with citations to the new documents.

---

## 2. Scope

**In scope — 3a**
- Kick-off spikes; golden set split into `dev` / `test`
- Stored originals and parses (`ai` database), Procrastinate job queue, job states in the UI
- Collection v2 (dense + sparse, versioned IDs, lifecycle, new payload), eval-gated re-index, alias swap, rollback
- Hybrid search, reranking, query transformation, Docling parsing, parent-child chunking, contextual retrieval
- Chunk-level sub-topics, lifecycle (`active` / `retired`), priorities with boosts
- Code-aware RAG over this repo (`search_code`)
- Skills with progressive disclosure, in the Agent Skills format
- Golden set v2 (+ code items), technique comparison report, ADRs

**In scope — 3b**
- Generation eval with a calibrated judge; synthetic data with human review
- Eval gate (deterministic on every PR; judge-based weekly and on demand); feedback review queue
- ACL-filtered retrieval on every path
- Guardrails (secret/PII masking, injection classifier, groundedness check) and red-team suite v1
- Model routing and cascade, semantic cache, prompt-caching optimisation
- Long-term memory under user control; context compaction
- KB curator (L2) with staging, promotion eval and batch approval

**Out of scope (deferred, with target)**
- Workflow integration (skills as MCP prompts, `answer_from_kb`, headless runs API, GitHub workflows, repo sync on
  merge) → **5, option**
- KB refresh job (L3), Kubernetes read-only tool → **4**
- Fine-tuning, local models, local-vs-API benchmark → **6**; GraphRAG, multimodal ingestion, multi-agent → **6 options**;
  autonomous curation (L4) → optional after 6
- OCR / vision-model parsing of scanned PDFs → only if a real document needs it
- Decided at M3b.0 (D75): sandboxed code execution, text-to-SQL, per-user GitHub access

---

## 3. Decisions

Numbering continues from `plan-phase-2.md` (D49). Status: **N** = new · **C** = changes an earlier decision (named).

### 3a

| # | St. | Topic | Decision | Why / alternatives |
|---|---|---|---|---|
| D50 | N | Resource budget (16 GB) | Target resident memory: AI service ≤ ~6 GB (bge-m3 ~2.3 GB, reranker ≤ ~2.5 GB, Prompt Guard ~0.35 GB, two spaCy `md` models); Docker VM ≤ ~4 GB (Postgres, Qdrant, Keycloak, Phoenix, GitHub MCP); NestJS + Angular dev ≤ ~1.5 GB. Docling runs only inside ingest jobs, one at a time. `pnpm mem` reports process memory and `docker stats`. A model that breaks the budget loses the benchmark even if it scores higher. | 16 GB is confirmed; every model choice in this phase is also a memory choice. Measured in M3a.0 (§8): the ingest peak, not the idle model, sets the limit. |
| D51 | C (D23) | Golden set discipline | `retrieval_v1` is split once into `dev` (~60 %, tuning) and `test` (~40 %, reported numbers only), stratified by domain, language and item type, fixed seed. New items (code, synthetic, gap, feedback) get their split when created. Tuning uses `dev`; each milestone ends with one `test` run whose numbers go into ADRs and the README. Sets are versioned (`golden_v2`, …). | Numbers measured on the tuning data overstate gains. |
| D52 | C (D3, D7) | Stored originals & `ai` database | New Postgres database `ai`, owned by the AI service: `source_documents` (doc id, version, sha256, original bytes ≤ 20 MB, mime, parsed DoclingDocument JSON, parser + version) and the job tables. Upload: NestJS streams the file to `POST /v1/documents` → stored → ingest job → `202 {jobId}`; NestJS polls the job and keeps the product status (D7 statuses + `queued`). NestJS still owns metadata, ACL fields, priorities and approvals. (ADR-0015) | Re-indexing and re-parsing need the originals; the AI service keeps the bytes it processes, NestJS keeps product data. Object storage (Azure Blob) can replace the `bytea` column in P5 behind the same interface. |
| D53 | N | Job queue | **Procrastinate 3.10.x** (Postgres-based, asyncio) in the AI service, jobs in the `ai` database. Locally the worker runs **inside** the API process and shares the loaded models (a second process would load bge-m3 twice); from P4 it becomes a separate Deployment of the same image. Queues: `ingest` (concurrency 1), `reindex`, `curator`, `eval`. Jobs are idempotent per doc id + version, retried with backoff, cancellable. (ADR-0015) | Python does the work and Postgres is already there. pg-boss in NestJS would split the pipeline across languages; Redis adds a service. |
| D54 | C (D10) | Collection v2 | `kb__v2__{model}__{dim}` with named vectors `dense` (bge-m3, cosine) and `sparse` (D56). Payload adds `version`, `lifecycle`, `priority`, `priority_topics`, chunk-level `topics`, `kind` (`doc` / `code`), `lang`, `parent_id`, `section_path`; for code `path`, `symbol`, `language`, `commit_sha`. Point ID = UUIDv5(`doc_id:version:chunk_index`), ready for staged versions in 3b. Payload indexes: `doc_id`, `domains`, `topics` (keyword with prefix matching), `lifecycle`, `visibility`, `allowed_groups`, `kind`, `path`. | Sparse vectors need a new collection anyway; versioned IDs now avoid a second migration. |
| D55 | N | Re-index & alias gate | `kb-reindex` job: build the new collection from stored originals (re-parse only if the parser version changed) → run `dev` + `test` retrieval eval → swap `kb_current` only if no `test` metric (hit@5, MRR@10, nDCG@10, abstention accuracy) drops by more than 0.02; otherwise keep the alias and attach the report. `--force` needs a reason, which goes to the audit log. Old collections stay 14 days; `--rollback` re-points the alias. (ADR-0015) | First real alias swap (study list #9), gated by evidence. |
| D56 | N | Hybrid search | Qdrant Query API: prefetch dense top-50 and sparse top-50 under the same filter (lifecycle, ACL, domain), fused with **RRF**; DBSF compared once. Sparse side by benchmark (ADR-0016): **(a) BM25** — Qdrant server-side inference (`qdrant/bm25` with IDF modifier), language-neutral processing vs. English stemming; FastEmbed `Qdrant/bm25` client-side if the self-hosted build lacks server inference; **(b) bge-m3 learned sparse**, only if the Phase 1 runtime exposes the sparse weights. Default (a). | Exact terms (error codes, CLI flags, identifiers) are where dense retrieval fails; BM25 adds no memory. |
| D57 | N | Reranking | Cross-encoder on the fused candidates → top-8. Candidates: `jina-reranker-v2-base-multilingual` (FastEmbed ONNX, ~1.1 GB, **CC BY-NC 4.0**), `bge-reranker-v2-m3` (Apache-2.0, ~0.6 B parameters, sentence-transformers + PyTorch, fp16 on the M1 GPU via MPS), `ms-marco-MiniLM-L-6-v2` (0.08 GB, English only) as the cheap baseline. Budget: p95 rerank ≤ 1.5 s on the M1, within D50; the number of reranked candidates (20–50) is tuned to fit. The abstention threshold is **recalibrated on reranker scores** with the unanswerable items. Licence recorded in the README and system card. (ADR-0017) | Largest expected quality gain per hour; licence and memory decide as much as nDCG. |
| D58 | N | Query transformation | Three strategies in the retrieval layer: standalone rewrite of follow-ups (`mode=rag` only — the agent already reformulates), multi-query (3 variants, merged by RRF) and HyDE. Cheap model, structured output, cached per question + history hash. Exposed to the agent as an optional `strategy` argument of `search_knowledge_base`. A strategy stays only if it gains ≥ 0.02 nDCG@10 on `test` at an acceptable cost per query. | Every variant costs an LLM call; evidence decides which survive. |
| D59 | C (D8) | Parsing & parent-child chunking | **Docling** (2.141.x, pinned in M3a.0) for PDF and HTML, without OCR/VLM extras; runs only in ingest jobs; the DoclingDocument JSON is cached in `ai.source_documents`. Child chunks of ~350–500 tokens are indexed; their parent section (≤ 2,000 tokens) goes to the LLM; children of the same parent are merged before prompting. Docling's HybridChunker vs. the own heading-aware chunker compared on `dev`. pypdf stays as fallback on errors and timeouts; PyMuPDF stays excluded (AGPL). (ADR-0018) | Headings, tables and reading order improve chunks and citations; children match precisely, parents give context. |
| D60 | N | Contextual retrieval & chunk labels | At ingest, one cheap-model call per chunk with the whole document as a cached prefix (document first, chunk last; `session_id = doc_id:version` for sticky routing) returns `{context (≤ 80 tokens), topics[]}`. The context is prepended for dense and sparse indexing, not shown in citations. `topics` are validated against `taxonomy.yaml`; fallback: embedding similarity to the sub-topic descriptions. Cost per document recorded and capped; switchable per domain. (ADR-0019) | Fixes chunks that lose their meaning out of context; the sub-topic labels come from the same call. |
| D61 | N | Lifecycle & priorities | `lifecycle`: `active` (default filter) / `retired`; `staged` follows in 3b. Priority `canonical` / `normal` / `low` with `priority_topics[]`, set by editors (own documents) or admins, audited. Boost applied **after** reranking, only when the route's topics overlap the scope and the chunk clears the threshold; weights tuned on `dev`. Canonical sources are marked in the prompt with a rule to prefer them on conflicts. | Roadmap §8.4; after reranking because the reranker would undo a boost applied inside Qdrant. |
| D62 | N | Code-aware RAG | Source: the local checkout of this repo (path in config, read-only, `.gitignore`-aware). tree-sitter grammars for Python, TypeScript and TSX; split-and-merge chunker in the cAST style (functions, classes, methods; ≤ ~1,500 non-whitespace characters; small siblings merged) with a header line (path, symbol, imports). Same dense model + BM25 for identifiers; payload `kind=code`. Incremental re-index by file hash (`pnpm kb:index-code`). New tool `search_code` on the own MCP server (the agent consumes KB tools through it, D34); citations as `path:Lstart-Lend`. Code eval set ~25 items. `astchunk` (MIT, v0.1.0) is a reference for the algorithm, not a dependency. A code-specific embedding model is an optional comparison. (ADR-0020) | Core capability for a developer assistant; own chunker because the libraries are young and the algorithm is small. |
| D63 | N | Skills | Agent Skills format: `SKILL.md` with only the portable fields `name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools`, in `skills/` at the repo root. Progressive disclosure: names + descriptions in the stable system prefix; tool `load_skill(name)` returns the body, `read_skill_file(name, path)` its references; while a skill is active its `allowed-tools` narrows the tool list (the permission policy still applies). Skill name + content hash on spans and messages, like prompts (D46). First skills: `ci-failure-triage`, `adr-writer`, `rag-debugging`; the D30 tool groups become their tool scopes. (ADR-0021) | Capabilities grow while the context stays small; the open format keeps the Phase 5 workflow option cheap. |

### 3b

| # | St. | Topic | Decision | Why / alternatives |
|---|---|---|---|---|
| D64 | N | Generation eval & judge | Per answer: faithfulness (claim-level support by the cited chunks), answer relevance, citation accuracy (deterministic validator + judge for support), refusal correctness (deterministic on unanswerable items). Judge = a different model family from the answer model, via OpenRouter, structured output (score per criterion + rationale), prompt versioned (D46), cost-capped. **Calibration:** ~50 hand-labelled answers per criterion, stratified; agreement and Cohen's kappa; a criterion may gate only at κ ≥ 0.6, otherwise rubric or judge change. (ADR-0022) | Judge scores mean something only once they agree with your own labels. |
| D65 | N | Synthetic data | A cheap model generates questions from chunks: direct, paraphrase without keyword overlap, cross-language, two-document multi-hop, near-miss unanswerable. Dedupe (cosine > 0.9 to existing items), answerability filter by the judge, then human review (accept / edit / reject) in a CLI. Stored with provenance (generator, prompt version, source chunk), reported separately from hand-written items. Exports query–passage pairs + hard negatives for P6. | Scales the eval set and prepares fine-tuning; review keeps generated noise out. |
| D66 | C (D43) | Eval gate | **Every PR, free, blocking:** retrieval `dev` + `test` (tolerance 0.02), citation validator, agent and skill smoke tests (fake LLM + fixtures), ACL matrix, guardrail unit tests. **Weekly and on demand (label `eval:full`), ≤ 2 USD per run:** judge-based generation eval, agent eval and red-team suite against a stored baseline with per-metric tolerances; summary in the job output. The baseline changes only through an explicit "accept baseline" commit. | Quality as part of the pipeline at a cost the token budget carries. |
| D67 | N | Feedback review | Thumbs-down and comments land in an admin review queue and get one label: `retrieval_miss`, `wrong_answer`, `knowledge_gap`, `tool_error` or `fine`. Misses and wrong answers become candidate eval items (`feedback_v1`, split on creation); gaps join the curator's gap pool. Metric: review turnaround. | Closes the loop between real use and the eval sets. |
| D68 | N | ACL-filtered retrieval | Keycloak groups → `groups` claim (group membership mapper) on the exchanged `kb-ai` and MCP tokens. One retrieval function enforces `visibility = org` or `allowed_groups ∩ groups ≠ ∅` as a mandatory Qdrant filter on every path: search and code tools, `mode=rag`, MCP, semantic-cache lookups, curator eval runs. Documents get `visibility` + `allowed_groups` at upload; editors can choose only their own groups. BM25 IDF across restricted documents is checked for score leakage; if visible, the IDF corpus is narrowed per query (Qdrant 1.19). Demo groups `platform`, `security`. (ADR-0027) | Restricted text never reaches the prompt, the cache or a log. |
| D69 | N | Guardrails | Order: **(1) user input** — secret and PII detection, masked before the LLM, user informed; **(2) tool and retrieval output** — secret/PII masking, then **Llama Prompt Guard 2 86M** per ≤ 512-token segment (trained on English and non-English attacks); suspected segments are replaced by a notice and flagged in the trace instead of blocking the turn; **(3) answer** — groundedness check of cited claims by a cheap model after the stream, sent as a `check` event (UI badge, cascade signal). Presidio 2.2.x with spaCy `en_core_web_md` + `de_core_news_md`, pattern recognisers (email, phone, IBAN, cards) and custom secret recognisers (API keys, tokens, private keys). Prompt Guard is a gated download under Meta's licence → optional, English-only 22M model as fallback; false positives measured on security documents that *describe* injection. (ADR-0023) | Defence in depth; masking and flagging instead of blocking keeps technical answers usable. |
| D70 | N | Model routing & cascade | `models.yaml` maps tasks to models (router, rewrite, contextual, judge, groundedness, answer-cheap, answer-strong). The router (D33) picks the answer tier up front for hard questions (multi-tool, low confidence). Cascade in `mode=rag`: cheap answer first, visible escalation ("retrying with a stronger model") when the citation validator or groundedness check fails. In agent mode escalation happens only before generation, so users never get two answers. Reasons recorded; compared with cheap-only and strong-only on `test` (cost + judged quality). (ADR-0024) | Strong models only where needed, with the trade-off measured. |
| D71 | N | Semantic cache | Qdrant collection `cache__{model}`. Only **KB-only** answers are stored (no GitHub, Azure, web or memory content); key = embedding of the standalone question; scope = hash(roles + groups, language, prompt version, answer tier); payload keeps the cited `doc_id:version`s. Hit threshold calibrated on synthetic paraphrase and near-miss pairs (start 0.95, wrong-hit rate ≤ 1 % on the calibration set). Any lifecycle or version change of a cited document deletes its entries; TTL 30 days. Hits are marked in the UI with a refresh action. (ADR-0025) | Saves cost and latency without leaking across permissions or serving stale answers. |
| D72 | N | Long-term memory | NestJS table `user_memory` (category `goal` / `skill` / `preference` / `progress`, ≤ 300 characters, source message). Writes only through agent proposals (`memory.propose`) that the user confirms in the UI; secret/PII filter before storing; ≤ 50 items per user. The profile is sent with every turn, placed right after the system prompt (stable, cacheable); above 20 items only the relevant ones (embedding similarity). Memory page: view, edit, delete, export. Answers that use memory are not cached. (ADR-0028) | Fits the mentor angle; the user stays in control of what is remembered. |
| D73 | N | Context compaction | When the transcript exceeds the history budget (D41), older turns are summarised by a cheap model into a structured `summary` part (facts, decisions, open questions, cited doc ids), stored in `messages` and shown as "earlier conversation summarised"; old tool results are replaced by their summaries. | Long conversations stay within budget and reproducible. |
| D74 | N | KB curator (L2) | As in roadmap §8: gap pool (D49 abstentions, thumbs-down, `knowledge_gap` labels; authenticated users only) → embedding clustering (min cluster size 3) → LLM label + sub-topic → coverage map. **Discovery:** sitemaps of allow-listed hosts, page titles and paths ranked by embedding similarity to the cluster label (no search account); optional OpenRouter `openrouter:web_search` with `allowed_domains` = the allow-list (billed to OpenRouter credits). Hosts and licences in `config/sources.yaml`; unknown host or licence → skip. Staged ingest via the queue (`lifecycle=staged`, provenance, `batch_id`); promotion eval (roadmap §8.3) → report → batch decision in NestJS (decision row + audit) → promote or reject; rollback by `batch_id`; per-host metrics. (ADR-0026) | Closes knowledge gaps with evidence and human approval, without a new paid account. |
| D75 | N | Options gate | At M3b.0, choose among sandboxed code execution (8 h), text-to-SQL (8 h) and per-user GitHub access (6 h). Options only if 3a finished within +10 % of its hours and the token budget holds; otherwise they move to the P6 options. | Keeps 3b from growing silently. |

---

## 4. Assumptions and open items

| # | Assumption | If wrong |
|---|---|---|
| A14 | **Held with open items:** Phase 2 code-complete; deviations and the hand-made leftovers in `plan-phase-2.md` §12 | Shift the schedule; don't start M3a.1 before the P2 agent eval is green |
| A15 | **Held:** Phase 1 runs bge-m3 as a fastembed custom model over the repo's ONNX export, which also returns token embeddings → D56 (b) is cheap (ADR-0016) | Settled in M3a.0; decides whether D56 candidate (b) is cheap or dropped |
| A16 | **Held:** the self-hosted Qdrant 1.19.2 image supports server-side BM25 inference (`qdrant/bm25`, ADR-0016) | FastEmbed `Qdrant/bm25` computes the same kind of sparse vectors client-side |
| A17 | 16 GB holds the D50 budget with one reranker loaded — **memory yes, latency no:** no multilingual candidate meets 1.5 s at 20 pairs (ADR-0017) | Smaller reranker (MiniLM, English only) and Prompt Guard 22M |
| A18 | ~25 USD/month OpenRouter budget during Phase 3 (one-off contextual retrieval, judge, synthetic data, curator) | Fewer judge runs, cheaper models, contextual retrieval for fewer domains |
| A19 | Prompt Guard 2 can be downloaded (licence accepted on Hugging Face) | 22M fallback, or classifier off with the gap documented |
| A20 | OpenRouter offers a judge model of a different family with structured outputs | Same family, different size; bias noted in ADR-0022 |

**Still open (decided inside the milestones):** sparse candidate (M3a.2), reranker (M3a.3), sub-topic list v2 and boost
weights (M3a.6–7), judge model (M3b.0–1), injection classifier variant (M3b.5), cache threshold (M3b.6), ACL demo
groups (M3b.4), curator host list and licences (M3b.9), 3b options (M3b.0).

---

## 5. Architecture (Phase 3)

```
 Browser — Angular 22 ──► NestJS API ─────────────────► Postgres `app`
   │                        │                             documents (+ version, lifecycle, visibility, allowed_groups,
   │                        │                             priority) · user_memory · feedback review · curator decisions
   │                        │ exchanged user JWT (+ groups claim)
   │                        ▼
   │                 AI service — FastAPI (API + in-process Procrastinate worker)
   │                   ├─ guardrails: secrets/PII (Presidio) · Prompt Guard 2 · groundedness check
   │                   ├─ router → semantic cache → agent loop / rag pipeline → cascade (cheap → strong)
   │                   ├─ skills loader: load_skill · read_skill_file            (skills/ in the repo)
   │                   ├─ retrieval: transform → hybrid (dense + BM25, RRF) → rerank → boost → threshold → parents
   │                   ├─ /mcp: search_knowledge_base · search_code · get_document · list_sources · ingest_url
   │                   └─ jobs: ingest · reindex · code-index · curator · eval
   │                        │                    │                         │
   │                 Postgres `ai`          Qdrant 1.19                OpenRouter: answers, rewrite, context,
   │                 originals, parses,     kb__v2__… (alias           judge, groundedness, curator labels,
   │                 jobs, curator data     kb_current), cache__…      optional web search
   └── Keycloak 26.8 (groups) · Phoenix (traces with prompt, skill and model versions)
```

| Service | Change in Phase 3 |
|---|---|
| ai-service | New endpoints (§7.1), in-process worker, guardrail models, reranker, Docling (ingest only), skills loader |
| postgres | New database `ai` (AI service owner) |
| qdrant | Collections `kb__v2__…` and `cache__…`; BM25 inference; old collections kept 14 days |
| keycloak | Groups `platform`, `security`; group membership mapper on the exchanged tokens |
| models on disk | Reranker, Docling layout models, Prompt Guard 2, spaCy `en_core_web_md` + `de_core_news_md` |

**Retrieval (one function for every path)**
1. Optional query transformation (D58).
2. Qdrant query: prefetch dense top-50 + sparse top-50 with the mandatory filter `lifecycle = active ∧ ACL ∧ domains`.
3. RRF fusion → rerank top-N → priority boost (D61) → threshold (recalibrated) → parent expansion (D59).
4. Guardrails on the returned text (D69): secret/PII masking, injection check per segment.

**Ingest**
1. NestJS → `POST /v1/documents` → original stored → job queued (`queued`).
2. Worker: parse with Docling, pypdf fallback (`parsing`) → child/parent or code chunks → context + sub-topics per
   chunk (`contextualizing`) → dense + sparse vectors (`embedding`) → upsert with versioned IDs (`ready`).
3. NestJS polls the job and updates the document row; failures keep the error and the job can be retried.

**Answer**
1. Guardrails on the user message → router (domains, tier) → semantic cache lookup for KB-only routes.
2. Miss → agent loop or rag pipeline (skills, tools, retrieval) → answer from the chosen tier.
3. Citation validator → groundedness check (`check` event) → in `mode=rag` possibly one visible escalation.
4. NestJS stores message, usage, gap signal; the AI service stores the cache entry if the turn was KB-only.

**Re-index:** build `kb__v2__…_{timestamp}` from `ai.source_documents` → eval on `dev` + `test` → gate (D55) →
alias swap or report → old collection kept 14 days.

**Curator:** see roadmap §8 and D74; staging uses the same ingest job with `lifecycle=staged`.

---

## 6. Repository layout (additions)

```
kb-agent/
├─ skills/                          # Agent Skills: ci-failure-triage/, adr-writer/, rag-debugging/ (SKILL.md + references)
├─ config/
│  ├─ models.yaml                   # + task → model map (D70)
│  ├─ guardrails.yaml               # recognisers, thresholds, actions (D69)
│  └─ sources.yaml                  # curator hosts, licences, sitemaps (D74); L3 flag added in P4
├─ apps/
│  ├─ web/src/app/features/
│  │  ├─ inspector/                 # + sparse / fused / rerank / boost columns, parent view
│  │  ├─ documents/                 # + job states, priority, lifecycle, visibility
│  │  ├─ memory/                    # memory page
│  │  └─ admin/                     # + re-index, feedback review, curator batches
│  ├─ api/src/                      # + memory/, feedback-review/, curator/, documents (ACL, priority, lifecycle)
│  └─ ai-service/src/ai_service/
│     ├─ jobs/                      # Procrastinate app; tasks: ingest, reindex, code_index, curator, eval
│     ├─ storage/                   # `ai` database: source_documents, code_files, curator data
│     ├─ retrieval/                 # transform, hybrid, rerank, boost, parents, acl — one entry point
│     ├─ ingest/                    # + docling parser, parent-child chunker, contextualizer, code chunker
│     ├─ skills/                    # loader, load_skill / read_skill_file
│     ├─ guardrails/                # pii, secrets, injection, groundedness
│     ├─ cache/                     # semantic cache
│     ├─ curator/                   # gaps, clustering, discovery, staging, promotion eval
│     └─ evals/                     # + generation (judge), calibration, synthetic, code, red-team v1, cache
└─ evals/
   ├─ datasets/
   │  ├─ golden_v2/{dev,test}.jsonl # D51
   │  ├─ code_v1.jsonl · judge_labels_v1.jsonl · synthetic_v1.jsonl · cache_pairs_v1.jsonl
   │  └─ redteam_v1.jsonl · feedback_v1.jsonl · gap_v1.jsonl · agent_v2.jsonl
   └─ baselines/                    # accepted baselines for the eval gate (D66)
```

---

## 7. Contracts (draft — generated OpenAPI / JSON Schema is authoritative)

### 7.1 AI service (internal; Bearer = exchanged user JWT `aud=kb-ai`, admin routes need `admin`)

| Method & path | Purpose | Request → Response |
|---|---|---|
| `POST /v1/documents` | store original, queue ingest | multipart `file`, `doc_id`, `title`, `domains[]`, `topics[]`, `visibility`, `allowed_groups[]` → `202 {jobId, version}` |
| `GET /v1/jobs/{id}` | job state | → `{state: queued\|parsing\|contextualizing\|embedding\|ready\|failed, progress, error?}` |
| `POST /v1/reindex` | admin: build, gate, swap | `{reason, force?: false}` → `202 {jobId}`; report: `GET /v1/reindex/{jobId}/report` |
| `POST /v1/reindex/rollback` | admin | → `200 {alias, collection}` |
| `POST /v1/code-index` | admin: index the local checkout | `{ref?}` → `202 {jobId}` |
| `PATCH /v1/documents/{doc_id}/labels` | P2 + `priority`, `priority_topics`, `lifecycle`, `visibility`, `allowed_groups` | payload update only → `204` |
| `POST /v1/search` | P1 + `strategy`, `kind`, `explain` | `explain: true` adds dense / sparse / fused / rerank ranks and the boost per hit |
| `GET /v1/skills` | skill catalogue | → `[{name, description, version, hash, allowedTools}]` |
| `POST /v1/curator/runs` | admin: gaps → candidates → staged batch | `{maxCandidates, hosts?}` → `202 {jobId}` |
| `GET /v1/curator/batches/{id}` | promotion report | §7.6 |
| `POST /v1/curator/batches/{id}/apply` | called by NestJS after a decision | `{decision: promote\|reject, decisionId}` → `200` |
| `/mcp` | + tool `search_code`; `search_knowledge_base` gains `strategy` | §7.5 |
| `POST /v1/ingest` (P1) | kept for system jobs; now queues a job | — |

### 7.2 NestJS API (browser-facing; Bearer JWT `aud=kb-api`)

| Method & path | Min. role | Notes |
|---|---|---|
| `POST /api/documents` | editor | + `visibility`, `allowedGroups[]` (own groups only), `topics[]`; status now starts at `queued` |
| `PATCH /api/documents/:id` | editor (own) / admin | + `priority`, `priorityTopics[]`, `lifecycle` (`retired` / `active`); audited |
| `POST /api/admin/reindex` · `POST /api/admin/reindex/rollback` · `GET /api/admin/reindex/:jobId` | admin | relays |
| `GET /api/admin/feedback?status=open` · `POST /api/admin/feedback/:id/review` | admin | `{label, note?, createEvalItem?}` |
| `GET /api/me/memory` · `PATCH /api/me/memory/:id` · `DELETE /api/me/memory/:id` · `GET /api/me/memory/export` | owner | |
| `POST /api/memory/proposals/:id` | owner | `{decision: confirm\|dismiss, text?}` |
| `GET /api/admin/curator/batches` · `GET /api/admin/curator/batches/:id` | admin | relay of the report |
| `POST /api/admin/curator/batches/:id/decision` | admin | `{decision, note?}` → decision row + audit → AI `apply` |
| `GET /api/skills` | viewer | relay |

New problem types: `reindex_gate_failed`, `group_not_allowed`, `memory_limit_reached`, `batch_state_conflict`.

### 7.3 SSE events (additions to v2)

```
event: skill_loaded     data: {"name":"ci-failure-triage","version":"1","hash":"…"}
event: cache_hit        data: {"similarity":0.97,"cachedAt":"…","citedDocs":["…:3"]}
event: guard            data: {"kind":"injection_suspected","source":"github.<tool>","segments":1}
event: escalation       data: {"from":"answer-cheap","to":"answer-strong","reason":"groundedness_failed"}
event: memory_proposed  data: {"proposalId":"…","category":"goal","text":"Learn Kubernetes networking"}
event: check            data: {"groundedness":"partial","unsupportedClaims":2,"model":"…"}
event: done             data: {…P2 fields…, "answerTier":"cheap","escalated":false,"cacheHit":false,"skills":["ci-failure-triage"]}
```

- `check` arrives after the last `token` and before `done`; `guard` events never contain the withheld text.
- `sources` hits gain `kind`, `path`, `lines` (code) and `sectionPath` (documents).

### 7.4 Data

Postgres `ai` (owned by the AI service):
```sql
source_documents   ( doc_id uuid, version int, sha256 char(64) not null, mime text not null, size_bytes int not null,
                     original bytea not null, parsed jsonb, parser text, parser_version text,
                     created_at timestamptz not null default now(), primary key (doc_id, version) )
code_files         ( path text primary key, sha256 char(64) not null, commit_sha text, language text,
                     indexed_at timestamptz not null )
curator_clusters   ( id uuid pk, label text, topics text[], question_refs jsonb, size int, created_at timestamptz )
curator_candidates ( id uuid pk, batch_id uuid not null, cluster_id uuid, url text not null, host text not null,
                     licence text not null, doc_id uuid, version int, report jsonb,
                     suggested text check (suggested in ('promote','reject','review')) )
-- + Procrastinate's own tables (managed by the library's migrations)
```

Postgres `app` (changes):
```sql
documents        ( …, version int not null default 1,
                   lifecycle text not null default 'active' check (lifecycle in ('staged','active','retired')),
                   visibility text not null default 'org' check (visibility in ('org','restricted')),
                   allowed_groups text[] not null default '{}',
                   priority text not null default 'normal' check (priority in ('canonical','normal','low')),
                   priority_topics text[] not null default '{}',
                   source_url text, added_by text not null default 'user', batch_id uuid, job_id text )
user_memory      ( id uuid pk, user_id text not null,
                   category text not null check (category in ('goal','skill','preference','progress')),
                   text varchar(300) not null, source_message_id uuid,
                   created_at timestamptz not null default now(), updated_at timestamptz not null default now() )
memory_proposals ( id uuid pk, user_id text not null, category text not null, text varchar(300) not null,
                   status text not null check (status in ('pending','confirmed','dismissed')), created_at timestamptz )
feedback         ( …, review_label text check (review_label in
                     ('retrieval_miss','wrong_answer','knowledge_gap','tool_error','fine')),
                   reviewed_by text, reviewed_at timestamptz, eval_item_id text )
curator_decisions( batch_id uuid primary key, decision text not null check (decision in ('promote','reject')),
                   decided_by text not null, note text, decided_at timestamptz not null default now() )
-- messages.parts gains the part type `summary` (D73)
```

### 7.5 Qdrant payload v2 and the `search_code` tool

```json
{
  "doc_id": "uuid", "version": 3, "chunk_index": 12, "kind": "doc", "lang": "de",
  "text": "…", "context": "…(D60, indexed only)…", "parent_id": "uuid:3:sec-4", "section_path": "Rollback › Helm",
  "title": "…", "page": 3, "domains": ["devops"], "topics": ["devops/ci-cd"],
  "lifecycle": "active", "priority": "canonical", "priority_topics": ["devops/ci-cd"],
  "visibility": "org", "allowed_groups": [], "owner_id": "sub", "embedding_model": "BAAI/bge-m3"
}
```
Code chunks add `path`, `symbol`, `language`, `start_line`, `end_line`, `commit_sha` and use `kind: "code"`.

| Tool | Arguments | Returns | Scope / role |
|---|---|---|---|
| `search_code` | `query`, `top_k ≤ 10`, `language?`, `path_prefix?` | `[{path, symbol, language, start_line, end_line, score, text}]` | `kb:read` · viewer |
| `search_knowledge_base` | P2 + `strategy?` (`plain` \| `multi_query` \| `hyde`, only survivors of M3a.4) | unchanged | unchanged |

### 7.6 Promotion report (curator batch)

```json
{"batchId":"…","cluster":{"label":"Helm rollback of failed releases","topics":["devops/release"],"questions":7},
 "documents":[{"url":"https://kubernetes.io/…","licence":"CC-BY-4.0","gapsClosed":5,"gapsTotal":7,
               "displacedGoldenItems":0,"abstentionIntact":true,"injectionFlags":0,"piiFlags":0,
               "nearDuplicateOf":null,"suggested":"promote"}],
 "golden":{"hit@5":{"before":0.84,"after":0.85},"ndcg@10":{"before":0.71,"after":0.72}},
 "costUsd":0.31}
```

### 7.7 Eval items

Code item (`code_v1.jsonl`):
```json
{"id":"c-007","split":"test","lang":"en","question":"Where is the HMAC of an approval action verified?",
 "relevant":[{"path":"apps/ai-service/src/ai_service/agent/approvals.py","symbol":"verify_signed_action"}]}
```

Judge label (`judge_labels_v1.jsonl`):
```json
{"id":"j-031","answerId":"…","criterion":"faithfulness","label":2,"scale":"0-2","labeller":"you",
 "notes":"claim about default TTL not in [2]"}
```

Cache pair (`cache_pairs_v1.jsonl`):
```json
{"id":"p-044","a":"How do I roll back a Helm release?","b":"Wie setze ich ein Helm-Release zurück?","same":true}
```

### 7.8 Skill file

```markdown
---
name: ci-failure-triage
description: Triage a failed CI run — find the failing step, match it to runbooks and known issues, propose next steps. Use when a user mentions a failing build, pipeline or workflow run.
license: MIT
compatibility: kb-agent 3a or later
allowed-tools: github.<runs-tool> github.<logs-tool> kb.search_knowledge_base kb.search_code
metadata:
  version: "1"
---
# CI failure triage
1. Identify the run and the first failing step …
```

### 7.9 Config excerpts (illustrative)

```yaml
# config/models.yaml — task map (D70)
tasks:
  router: cheap
  rewrite: cheap
  contextual: cheap
  groundedness: cheap
  judge: judge          # different family from the answer models (D64)
  answer: {default: cheap, escalate_to: strong}
```

```yaml
# config/sources.yaml — curator (D74)
hosts:
  kubernetes.io:      {licence: CC-BY-4.0, sitemap: https://kubernetes.io/sitemap.xml, domains: [devops, cloud]}
  www.keycloak.org:   {licence: Apache-2.0, sitemap: …, domains: [security]}
web_search: {enabled: false, engine: exa, max_results: 5}   # openrouter:web_search with allowed_domains = hosts
```
Licences are checked per host before the entry is added; the values above are placeholders until verified.

---

## 8. Milestones and tasks

Order 3a: M3a.0 → M3a.1 → M3a.2 → M3a.3 → M3a.4 → M3a.5 → M3a.6 → M3a.7 → M3a.8 → M3a.9 → M3a.10.
Order 3b: M3b.0 → M3b.1 → M3b.2 → M3b.3 → M3b.4 → M3b.5 → M3b.6 → M3b.7 → M3b.8 → M3b.9.
Hours are ideal single-person hours, ±30 %. Every retrieval milestone ends with a re-index through the gate (D55) and
one `test` run (D51).

### M3a.0 — Kick-off: deviations, split, spikes (~4 h)

- [x] Record Phase 2 deviations in `plan-phase-2.md`; measure the P2 stack with `pnpm mem` and fill in the D50 table
- [x] Split the golden set into `dev` / `test` (stratified, fixed seed); baseline run on both → `baselines/p2-dense`
- [x] **Spikes (≤ 45 min each):** server-side BM25 on the self-hosted Qdrant 1.19 image · does the Phase 1 bge-m3
  runtime expose sparse weights · Docling on a 30-page PDF (time, peak memory) · each reranker candidate: load,
  latency for 20 and 50 pairs, memory, licence
- [x] Pin Docling, Procrastinate, Presidio, tree-sitter grammar versions

**Acceptance:** baseline numbers for `dev` and `test`; spike notes in the ADR-0015 … 0018 drafts; D50 budget filled with
measured values.

**Done 2026-10-23.** Baselines (`evals/baselines/p2-dense/`, bge-m3, chunks 1000/150, top 10, no threshold):

| Split | Items (answerable) | hit@1 | hit@5 | MRR@10 | nDCG@10 | Threshold (balanced acc.) | Misses in top 5 |
|---|---|---|---|---|---|---|---|
| `dev` | 36 (30) | 0.83 | 1.00 | 0.89 | 0.91 | 0.610 (0.87) | — |
| `test` | 24 (20) | 0.65 | 0.95 | 0.77 | 0.78 | 0.557 (0.95) | `r-033` |

`test` happens to be the harder half; the weighted mean matches the full-set baseline (nDCG@10 0.86). The split is
stratified by first domain, language and item type (seed 42): every domain, both languages and all six item types
sit on both sides.

D50 measured (MacBook Air M1, 16 GB; `pnpm mem` with the P2 stack idle under `pnpm dev`, peaks with `/usr/bin/time -l`):

| Component | D50 estimate | Measured |
|---|---|---|
| AI service idle, bge-m3 loaded | bge-m3 ~2.3 GB | 1.83 GB |
| Embedding the corpus (eval run, 218 chunks, in-memory Qdrant) | — | **4.35–4.50 GB peak** |
| Reranker (ADR-0017) | ≤ ~2.5 GB | MiniLM +1.2 GB · jina +2.0 GB · bge fp16 +0.5 GB RSS + 1.1–2.3 GB MPS |
| Docling, 36-page PDF, own process (ADR-0018) | only in jobs | 1.96–2.02 GB peak |
| Prompt Guard 2, spaCy `md` ×2 | ~0.35 GB + two models | not measured (M3b.5) |
| Containers: Keycloak 0.69, Phoenix 0.44, Qdrant 0.06, Postgres 0.03, GitHub MCP 0.02 GB | VM ≤ ~4 GB | 1.25 GB (Docker Desktop's VM limit is 8.4 GB) |
| NestJS + Angular dev | ≤ ~1.5 GB | 0.51 + 0.57 GB |

The ingest peak, not the idle model, sets the AI service's limit: 4.5 GB plus a reranker breaks ≤ ~6 GB. Likely
cause: `KnowledgeBase.ingest` embeds all chunks of a document in one fastembed batch (default 256; ~55 chunks for
the largest document) — cap the batch in M3a.1 and measure again.

Spikes (ADR-0016 … 0018): server-side BM25 works on the self-hosted 1.19.2 image; bge-m3 sparse weights come from
the same ONNX pass (3.5 KB head); Docling 0.7 s/page warm, ~2 GB peak; no multilingual reranker meets 1.5 s at 20
pairs on the M1 (bge-reranker-v2-m3 MPS fp16 2.5 s, jina CPU 5.2 s; MiniLM 0.76 s, English only).

Pins (resolved together with the service's dependencies by `uv pip compile`, not installed — each enters
`pyproject.toml` in its milestone): `docling==2.141.0` (2.142 is days old), `procrastinate==3.10.0` (psycopg 3.3.6),
`presidio-analyzer==2.2.364` + `presidio-anonymizer==2.2.364`, `tree-sitter==0.26.0`, `tree-sitter-python==0.25.0`,
`tree-sitter-typescript==0.23.2` (ABI 15 / 14; both parse repo files without errors). Presidio caps numpy below 2.5
(the service has 2.5.4 → 2.4.6 in M3b.5). `docling-core` already depends on tree-sitter and the Python, JavaScript,
TypeScript and C grammars. If bge-reranker-v2-m3 wins: `sentence-transformers==6.1.0`; torch 2.14.1 comes with
Docling anyway.

Deviations: ADR-0014 went to M2.8, so every Phase 3 ADR number moved up by one (0015 … 0028). No `golden_v2` files
yet — the `retrieval_v1` items got a `split` field (questions and labels unchanged) and `kb-eval retrieval --split
dev|test` filters on it; `golden_v2` follows in M3a.10. ADR-0018 proposes Docling in a child process per job, so its
~2 GB returns to the OS. `pnpm mem` sums RSS over each app's process tree: shared pages count twice and MPS memory is
missing. Prompt Guard 2 is gated on Hugging Face (manual approval) and not downloaded, so A19 stays open until M3b.5.
The CI gate still runs the full set (hit@5 0.98, nDCG@10 0.86); the split gate is D66 (M3b.3). A14's "P2 agent eval
green" before M3a.1 was not re-run (paid LLM calls).

### M3a.1 — Stored originals, queue, collection v2, re-index (~12 h)

- [x] `ai` database + migrations; `source_documents`; backfill from `data/sample-docs/` (documents without a local
  source are listed for re-upload or re-fetch)
- [x] Procrastinate app with in-process worker, queues, job states, idempotency, retries, cancel
- [x] `POST /v1/documents`, `GET /v1/jobs/{id}`; NestJS upload path switched to it; job states in the documents UI
- [x] Collection v2 (D54): versioned IDs, new payload and indexes
- [x] `kb-reindex` with the eval gate (D55), report, `--rollback`, `--force` + reason → audit; admin endpoints and page
- [x] Tests: idempotent jobs, worker crash mid-job → resume, the gate refuses a deliberately worse build, rollback

**Acceptance:** demo steps 1 and 7; a re-index needs no re-upload; rollback takes under a minute.

**Done 2026-10-24.** Checked end to end on throwaway state (API :3001, AI :8001 with bge-m3, own databases and
alias): 17 documents uploaded through NestJS → queue in 177 s, none failed; `kb-admin reindex` built from the stored
originals in 188 s and swapped, reproducing the `p2-dense` baselines exactly (`test` nDCG@10 0.780, hit@5 0.95; `dev`
0.907); the same through `/api/admin/reindex` with both audit rows; rollback 0.04 s (API) and 1.0 s (CLI), two in a
row walk the chain back. Memory (D50): batch cap 16 — the eval run's ingest peak is 2.52 GB (3.84 GB at fastembed's
default 256, 3.02 GB at 32; same speed and metrics); the AI service with its in-process worker idles at 1.71 GB and
peaks at 2.13 GB while ingesting.

Deviations:
- `POST /v1/ingest` is removed, not kept: nothing calls it; the curator (M3b.9) defers the ingest job directly.
- `source_documents` has no `parsed` / `parser` / `parser_version` yet — they arrive with Docling (M3a.5). Labels are not
  stored with the originals: a re-index takes them from the live collection's payload.
- Job states add `building`, `evaluating`, `cancelled`; `contextualizing` comes in M3a.6. No `progress` field. Job ids
  are integers and bodies snake_case (`{job_id, version}`). The report comes with `GET /v1/jobs/{id}` and
  `GET /v1/reindex` (runs + reports), so there is no `/report` route; NestJS has `GET /api/admin/reindex` instead of
  `/:jobId`.
- Queues `ingest`, `reindex`, `maintenance` (stalled-job retry); `curator` and `eval` come with their milestones. No
  `JOBS_INGEST_CONCURRENCY` or `QDRANT_COLLECTION_PREFIX`: one job at a time and `kb__v2` are constants; ingest and
  re-index also share a lock.
- Payload v2 gets `version`, `kind`, `lifecycle`, `priority`, `priority_topics` now; `lang`, `parent_id`,
  `section_path`, chunk-level `topics` and the sparse vector come with M3a.2/5/6. NestJS `documents` gets only
  `version` and `job_id`; its status drops `processing` for the job states.
- NestJS syncs job states when documents are read (list, relabel, delete), not with a poller.
- Deletes and relabels reach every `kb__*` collection, so a rollback cannot resurrect a deleted document. A refused build
  is deleted; replaced collections are never deleted automatically (no 14-day cleanup yet).
- A different embedding model cannot pass the gate (nothing to compare): it needs `--force --reason`.
- CLI runs are not in `audit_log` (no user token); they record `cli:<user>` and the reason in the run report.

### M3a.2 — Hybrid search (~5 h)

- [ ] Sparse candidates per D56 built into separate collections by the re-index job; compared on `dev`; RRF vs. DBSF once
- [ ] `explain` mode in `/v1/search`; inspector columns for dense, sparse and fused ranks
- [ ] Winner through the gate; ADR-0016 with `test` numbers per item type

**Acceptance:** "hybrid" row on `test`; exact-term items (error codes, flags, identifiers) reported separately.

### M3a.3 — Reranking (~6 h)

- [ ] Candidates per D57; reranking of the fused candidates; top-N tuned to the latency budget
- [ ] Abstention threshold recalibrated on reranker scores (`dev`), checked on `test`
- [ ] Inspector rerank column; licence noted; ADR-0017

**Acceptance:** "+ rerank" row; p95 latency and memory within D50; abstention accuracy not below the baseline.

### M3a.4 — Query transformation (~5 h)

- [ ] Standalone rewrite (`mode=rag`), multi-query, HyDE; cheap model; cache per question + history hash
- [ ] `strategy` argument on `search_knowledge_base` (MCP schema change, contract check)
- [ ] Each measured on `dev`; survivors on `test`; cost per query

**Acceptance:** a row and a cost figure per strategy; only survivors stay enabled.

### M3a.5 — Docling parsing + parent-child chunking (~8 h)

- [ ] Docling parser without OCR/VLM extras; parse cached; pypdf fallback; timeouts
- [ ] Child/parent chunking; HybridChunker vs. own chunker on `dev`
- [ ] `get_document` and citations by section; inspector parent view; re-index; ADR-0018

**Acceptance:** "+ Docling / parent-child" row; tables survive parsing in 5 spot-checked PDFs; peak memory within D50.

### M3a.6 — Contextual retrieval + chunk sub-topics (~6 h)

- [ ] Contextualizer step (D60) with cached document prefix, cost cap, per-domain switch
- [ ] Chunk `topics` from the same call; fallback by embedding similarity; sub-topic list v2 in `taxonomy.yaml`
- [ ] Re-index; cost report per document; ADR-0019

**Acceptance:** "+ contextual" row with its one-off cost; ≥ 90 % of 50 spot-checked chunks carry a correct sub-topic.

### M3a.7 — Lifecycle & priorities (~5 h)

- [ ] Fields in NestJS and the payload; `PATCH` endpoints; documents UI (priority, scope, retire / activate); audit
- [ ] Boost after reranking; canonical marker and conflict rule in the prompt; weights tuned on `dev`
- [ ] Golden items per pinned topic; before/after on `test`

**Acceptance:** demo step 5; retired documents are never returned (test).

### M3a.8 — Code-aware RAG (~12 h)

- [ ] tree-sitter chunker (Python, TypeScript, TSX), split-and-merge, header lines, `.gitignore`-aware walker
- [ ] `code-index` job, incremental by file hash, `commit_sha` in the payload
- [ ] `search_code` MCP tool + agent tool group `code`; `path:Lstart-Lend` citations rendered in the UI
- [ ] `code_v1` (~25 items: definition lookup, usages, "how does X work", TypeScript ↔ Python contract questions)
- [ ] Line-window baseline vs. AST chunker; optional code embedding model; ADR-0020

**Acceptance:** demo step 4; code eval report for both chunkers.

### M3a.9 — Skills (~8 h)

- [ ] Loader for `skills/` with validation of the portable fields; `load_skill`, `read_skill_file`; tool narrowing; spans
- [ ] Skills `ci-failure-triage`, `adr-writer`, `rag-debugging`; D30 tool groups mapped
- [ ] `agent_v2`: + ~10 skill tasks (selection, success, "no skill needed"); ADR-0021

**Acceptance:** demo step 6; skill-selection accuracy reported; skill list inside the cached prefix (cached tokens
visible per step).

### M3a.10 — Golden set v2, technique report, docs (~4 h)

- [ ] `golden_v2`: + code items + items for documents added since P1, split on creation
- [ ] Final technique table on `test`; README section; ADR index
- [ ] 3a retrospective: hours vs. plan (input for D75)

**Acceptance:** demo steps 1–7 reachable from the README; the table is published.

### M3b.0 — Kick-off (~2 h)

- [ ] Record 3a deviations; options decision (D75); token budget check (A18)
- [ ] Judge shortlist: 2 models × 10 hand-labelled answers as a quick agreement check

**Acceptance:** options decision and judge shortlist recorded (ADR-0022 draft).

### M3b.1 — Generation eval + judge calibration (~10 h)

- [ ] Deterministic metrics (citation accuracy, refusal correctness); judge prompts (versioned), structured output,
  cost cap
- [ ] Labelling CLI; ~50 labels per criterion, stratified → `judge_labels_v1`
- [ ] Agreement and κ per criterion; iterate rubric or judge until κ ≥ 0.6, or document the gap
- [ ] Generation eval report on `test` (baseline = end of 3a); ADR-0022

**Acceptance:** κ per criterion reported; only criteria with κ ≥ 0.6 may gate.

### M3b.2 — Synthetic data (~5 h)

- [ ] Generator for the five item types; dedupe; answerability filter; review CLI
- [ ] ~100 accepted items with provenance and split; export of pairs + hard negatives for P6

**Acceptance:** acceptance rate of generated items reported; synthetic metrics shown separately from hand-written ones.

### M3b.3 — Eval gate + feedback review (~5 h)

- [ ] PR workflow (deterministic, blocking); weekly + `eval:full` workflow with budget input, baselines, tolerances
- [ ] "Accept baseline" command
- [ ] Feedback review queue (API + admin page), labels, eval-item creation, gap pool

**Acceptance:** demo step 8; a reviewed feedback item becomes an eval item.

### M3b.4 — ACL-filtered retrieval (~6 h)

- [ ] Group membership mapper on the exchanged tokens; demo groups and restricted documents
- [ ] Upload fields; mandatory filter in the single retrieval function
- [ ] ACL matrix: user × document × path (search, code, rag, MCP, cache, curator eval)
- [ ] IDF leakage check; per-query IDF corpus if needed; ADR-0027

**Acceptance:** demo step 10; matrix green.

### M3b.5 — Guardrails + red-team suite v1 (~12 h)

- [ ] Presidio with the `md` models, pattern and secret recognisers; masking of user input and tool/retrieval output;
  small PII/secret test set (precision, recall)
- [ ] Prompt Guard 2 86M (optional download), segmenting, withhold + flag, `guard` event; false-positive rate on
  security documents
- [ ] Groundedness check → `check` event → UI badge
- [ ] `redteam_v1` (~60 cases): OWASP LLM 2025, Agentic 2026 and MCP Top 10 categories, poisoned documents, secret
  exfiltration, memory poisoning; runs with guardrails on and off; ADR-0023

**Acceptance:** demo step 9; pass rate on vs. off; false-positive rate on benign security documents ≤ 5 % (target).

### M3b.6 — Cost: routing, cascade, semantic cache, prompt caching (~10 h)

- [ ] Task → model map; cascade with `escalation` events and reasons
- [ ] Semantic cache (D71): scope hash, invalidation, UI marker; calibration on `cache_pairs_v1`
- [ ] Prompt-caching audit: cached-token ratio per step; stable order of skills list, memory block and tools
- [ ] Cost report: cheap-only / strong-only / cascade × judged quality; cache hit and wrong-hit rates; ADR-0024, ADR-0025

**Acceptance:** demo steps 11–12; wrong-hit rate ≤ 1 % on the calibration set; cost per answer vs. the P2 baseline.

### M3b.7 — Long-term memory (~8 h)

- [ ] `user_memory` + `memory_proposals`; confirmation chip; memory page (view, edit, delete, export)
- [ ] `memory.propose` tool with secret/PII filter; profile block in the prompt; relevance selection above 20 items
- [ ] Memory tasks in `agent_v2` (recall, no invented memories, refuses to store secrets); ADR-0028

**Acceptance:** demo step 13; a deleted memory is absent from the next turn's context (test).

### M3b.8 — Context compaction (~4 h)

- [ ] `summary` part, budget trigger, summaries of old tool results, UI marker
- [ ] Long-conversation tasks (facts from early turns)

**Acceptance:** demo step 14.

### M3b.9 — KB curator (L2) (~14 h)

- [ ] Gap pool, clustering, labels, coverage map
- [ ] `sources.yaml`; sitemap discovery; optional OpenRouter web search with `allowed_domains`
- [ ] Candidate fetch with the SSRF guard from M2.4; staged ingest (`lifecycle=staged`, provenance, `batch_id`)
- [ ] Promotion eval (gaps closed, nothing pushed out, abstention intact, safety and hygiene) → report (§7.6)
- [ ] Batch decision in NestJS (decision row + audit) → apply; rollback by `batch_id`
- [ ] Retire suggestions (superseded ADRs, dead links); `gap_v1`; per-host metrics; ADR-0026

**Acceptance:** demo step 15; rolling back a batch restores the previous answers (test).

### Options (decided at M3b.0, D75)

| Option | Content | h |
|---|---|---|
| Sandboxed code execution | Local container sandbox: no network, CPU/memory/time limits, no secrets; tool `run_python` behind approval | 8 |
| Text-to-SQL | Sample Postgres DB; schema descriptions; SELECT-only parser check, read-only role, row limit, timeout, `EXPLAIN` | 8 |
| Per-user GitHub access | GitHub as brokered IdP + Keycloak Identity Brokering API v2 → GitHub read tools as the user | 6 |

---

## 9. Schedule (8–10 h/week, 9 h used)

| Week | Focus |
|---|---|
| 1–2 | M3a.0, M3a.1 (storage, queue, collection v2, re-index) |
| 3 | M3a.2 hybrid, M3a.3 rerank |
| 4–5 | M3a.4 query transformation, M3a.5 Docling + parent-child |
| 5–6 | M3a.6 contextual + sub-topics, M3a.7 priorities |
| 6–7 | M3a.8 code-aware RAG |
| 8 | M3a.9 skills, M3a.10 report |
| 9 | **Buffer** → 3a exit demo |
| 10–11 | M3b.0, M3b.1 judge + calibration, M3b.2 synthetic data |
| 12 | M3b.3 eval gate + feedback review |
| 13 | M3b.4 ACL |
| 14–15 | M3b.5 guardrails + red-team v1 |
| 15–16 | M3b.6 cost |
| 17 | M3b.7 memory, M3b.8 compaction |
| 18–19 | M3b.9 curator + **buffer** → 3b exit demo |

**Cut line 3a** (drop in this order): optional code embedding comparison → HyDE → multi-query → DBSF comparison →
HybridChunker comparison → `read_skill_file` (skill bodies only) → third skill → contextual retrieval for all domains
(keep two).
**Never cut 3a:** `dev`/`test` split, stored originals + gated re-index + rollback, hybrid, reranking (the largest model
that fits), threshold recalibration, AST code chunker + `search_code`, skills loader + two skills, lifecycle and
priorities, golden set v2, technique table.

**Cut line 3b** (drop in this order): options → curator web search (sitemaps only) → memory relevance selection (cap at
20 items) → post-hoc escalation (up-front routing only) → synthetic items 100 → 50 → red-team cases 60 → 40 →
groundedness check only in `mode=rag`.
**Never cut 3b:** judge calibration with κ, deterministic PR gate, ACL on every path, secret/PII masking, injection
flagging (if the model is available), red-team suite on/off, cache scope + invalidation rules (if the cache ships),
user control over memory (if memory ships), curator promotion eval + approval + rollback.

---

## 10. Definition of Done

**3a**
- [ ] Demo steps 1–7 pass on a fresh clone with the 16 GB budget (D50) met
- [ ] Re-index from stored originals, gated swap and rollback work and are tested
- [ ] Technique table on `test` published; every enabled technique beat its predecessor or is documented as neutral
- [ ] Abstention threshold recalibrated after reranking
- [ ] Code search returns line-precise citations; code eval reported
- [ ] Skills load on demand, narrow the tools and appear in traces
- [ ] ADR-0015 … 0021 written; licences of all models recorded

**3b**
- [ ] Demo steps 8–15 pass on a fresh clone
- [ ] Judge criteria calibrated (κ reported); only calibrated criteria gate; PR gate blocking and free
- [ ] ACL matrix green on every path, including cache and MCP
- [ ] Guardrails on/off comparison published; false-positive rate measured
- [ ] Cost per answer and judged quality reported for cheap-only, strong-only and cascade; cache wrong-hit rate ≤ 1 %
- [ ] Memory fully under user control; compaction keeps early facts answerable
- [ ] Curator batch promoted with a report, approval and a tested rollback
- [ ] ADR-0022 … 0028 written; system-card stub updated (models, licences, guardrail limits, red-team results)

---

## 11. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Reranker, Docling and guardrail models exceed 16 GB | Medium–High | D50 budget measured in M3a.0, smaller models, ingest concurrency 1, in-process worker |
| Overfitting to the golden set | Medium | `dev`/`test` split, `test` only at milestone ends, synthetic and feedback items |
| Judge disagrees with own labels | Medium | Calibration gate κ ≥ 0.6, rubric iterations, deterministic metrics first |
| Model licences (CC BY-NC reranker, Meta licence for Prompt Guard) | Medium | Licences in ADRs and the system card; Apache-2.0 alternative; optional download |
| Token cost of contextual retrieval, judge, synthetic data, curator | Medium | Caps per document and run, weekly instead of nightly, cheap models, budget check at M3b.0 |
| Cache serves wrong or leaked answers | Medium | KB-only, scope hash, invalidation by document version, calibrated threshold, wrong-hit metric |
| ACL bypass through a forgotten path | Medium | One retrieval function; matrix over every path |
| Injection classifier flags legitimate security documents | Medium–High | Withhold segments, not turns; false-positive measurement; per-domain threshold |
| Curator ingests poisoned or low-quality pages | Medium | Allow-list, staging, promotion eval with safety checks, human batch approval, rollback |
| New `ai` database, collection v2 and versioned IDs break Phase 2 features | Medium | Gated re-index, rollback, P2 agent eval in the PR gate |
| In-process worker slows the API during ingestion | Low–Medium | Ingest concurrency 1; separate worker Deployment from P4 |
| Phase 3 is the largest phase | High | 3a/3b exit demos, kick-offs, cut lines, options gate, two buffer weeks |

---

## 12. Hand-off to Phase 4 and later

- In-process worker → separate Deployment of the same image; `ai` database in the chart (P4)
- Curator staging + promotion eval → KB refresh CronJob (L3, M4.7)
- Reranker, Docling and guardrail models → resource requests/limits and a model-caching strategy for images (P4)
- Synthetic pairs + hard negatives → fine-tuning (P6); golden `test` set → local-vs-API benchmark (P6)
- Skills in Agent Skills format + `search_code` → workflow integration option (P5)
- Semantic cache collection → Qdrant hosting decision (P5)
- Model licences, guardrail limits, red-team results, curation levels → system card (P6)

---

## 13. Study-list coverage in Phase 3

| # | Topic | Where in Phase 3 |
|---|---|---|
| 2, 3 | Parsing, chunking | D59, M3a.5 (Docling, parent-child); D62 (code) |
| 6, 21 | Vector DB, hybrid search | D54, D56, M3a.2 |
| 7 | Metadata filtering | D61 (lifecycle, priorities), D68 (ACL) |
| 8, 9 | Idempotent ingestion, alias re-indexing | D52, D53, D55, M3a.1; staging in M3b.9 |
| 11 | Thresholds & abstention | D57 (recalibration after reranking) |
| 12 | Context engineering | D73 compaction |
| 17 | Retrieval evaluation | D51, M3a.10 (`test` table, golden v2) |
| 19, 20 | Privacy, prompt injection | D69 |
| 22 | Reranking | D57, M3a.3 |
| 23 | Query transformation | D58, M3a.4 |
| 24 | Contextual retrieval | D60, M3a.6 |
| 25 | Code-aware RAG | D62, M3a.8 |
| 29, 49 | Routing, model cascades | D70 |
| 35 | Safe web access | D74 (curator discovery) |
| 37 | Skills | D63, M3a.9 |
| 39 | Prompt caching | D60 (cached document prefix), M3b.6 audit |
| 40, 41 | Generation eval, judge calibration | D64, M3b.1 |
| 43 | Eval as CI gate | D66, M3b.3 |
| 44 | Synthetic data | D65, M3b.2 |
| 45 | Online feedback loop | D67 |
| 46, 48 | Red teaming, guardrails | D69, M3b.5 |
| 47 | ACL-filtered retrieval | D68, M3b.4 |
| 50 | Semantic caching | D71 |
| 51 | Long-term memory | D72 |
| 31, 34, 36 | Per-user GitHub, text-to-SQL, sandbox | Options (D75) |

---

## Appendix A — Environment variables (additions to `.env.example`)

```dotenv
# --- ai-service (FastAPI) ---
AI_DATABASE_URL=postgresql://postgres:dev-only-change-me@localhost:5432/ai
JOBS_INPROCESS_WORKER=true                 # false from P4 (separate worker Deployment)
GOLDEN_DATASET=../../evals/datasets/retrieval_v1.jsonl   # the re-index gate (M3a.1; golden_v2 in M3a.10)
SPARSE_MODE=bm25_server                    # bm25_server | bm25_client | bgem3 (ADR-0016)
BM25_LANGUAGE_NEUTRAL=true
RERANKER_MODEL=                            # ADR-0017
RERANK_CANDIDATES=30                       # tuned to the latency budget (20–50)
RERANK_KEEP=8
RETRIEVAL_SCORE_THRESHOLD=                 # recalibrated on reranker scores (M3a.3)
QUERY_STRATEGIES=plain                     # survivors of M3a.4
DOCLING_TIMEOUT_S=300
CHILD_CHUNK_TOKENS=450
PARENT_MAX_TOKENS=2000
CONTEXTUAL_DOMAINS=devops,cloud,security,architecture
CONTEXTUAL_MAX_COST_USD_PER_DOC=0.05
CODE_REPO_PATH=../..                       # local checkout, read-only
SKILLS_DIR=../../skills
GUARDRAILS_CONFIG=../../config/guardrails.yaml
SPACY_MODELS=en_core_web_md,de_core_news_md
PROMPT_GUARD_MODEL=meta-llama/Llama-Prompt-Guard-2-86M   # optional; 22M fallback
CACHE_ENABLED=true
CACHE_SIMILARITY_THRESHOLD=0.95
CACHE_TTL_DAYS=30
CURATOR_SOURCES_CONFIG=../../config/sources.yaml
CURATOR_WEB_SEARCH=false                   # true → openrouter:web_search with allowed_domains
EVAL_FULL_BUDGET_USD=2.00

# --- api (NestJS) ---
MEMORY_MAX_ITEMS=50
```

## Appendix B — Command cheat sheet (additions)

```bash
pnpm mem                                   # process memory + docker stats (D50)
pnpm kb:backfill-originals                 # store originals for documents ingested before Phase 3
pnpm kb:reindex [--force --reason "…"]     # build, gate, swap
pnpm kb:reindex --rollback
pnpm kb:index-code                         # incremental code index of the local checkout
pnpm eval:retrieval --split test --report techniques
pnpm eval:code
pnpm eval:generation [--judge]             # deterministic metrics; judge with --judge
pnpm eval:calibrate                        # judge vs. own labels (κ)
pnpm eval:synthetic --generate | --review
pnpm eval:redteam [--guardrails off]
pnpm eval:cache                            # wrong-hit rate on cache_pairs_v1
pnpm curator:run · pnpm curator:report <batchId>
```

## Sources checked (2026-10-22)

- FastEmbed supported models (no bge-m3) — https://qdrant.github.io/fastembed/examples/Supported_Models/ · open PR for bge-m3: https://github.com/qdrant/fastembed/pull/602
- FastEmbed rerankers (licences, sizes) — https://qdrant.tech/documentation/fastembed/fastembed-rerankers/
- bge-reranker-v2-m3 (Apache-2.0, ~0.6 B) — https://huggingface.co/BAAI/bge-reranker-v2-m3
- Qdrant BM25 inference and text processing — https://qdrant.tech/documentation/search/text-search/full-text-search/
- Qdrant 1.19 (per-tenant IDF, language-neutral BM25, removed legacy endpoints) — https://qdrant.tech/blog/qdrant-1.19.x/
- Qdrant score boosting — https://qdrant.tech/documentation/search/search-relevance/
- Docling 2.141 — https://pypi.org/project/docling/
- Procrastinate 3.10 — https://pypi.org/project/procrastinate/ · https://procrastinate.readthedocs.io
- Presidio analyzer 2.2.x — https://pypi.org/project/presidio-analyzer/
- Llama Prompt Guard 2 — https://dev.meta.ai/llama/docs/model-cards-and-prompt-formats/prompt-guard
- Prompt-injection detection tools overview — https://www.mintive.com/blog/prompt-injection-detection-tools
- astchunk (cAST reference) — https://github.com/yilinjz/astchunk
- Contextual Retrieval — https://anthropic.com/news/contextual-retrieval
- OpenRouter web search server tool (`allowed_domains`) — https://openrouter.ai/docs/guides/features/server-tools/web-search.md
- Agent Skills portable fields — https://code.claude.com/docs/en/skills.md
