# Roadmap outline — Phases 3–6

> **Purpose:** planning outline for the phases after `plan-phase-2.md`. Each phase gets its own `plan-phase-N.md`
> (same structure as `plan.md`) when the previous phase ends.
> **Status:** Draft v1.1 · 2026-10-19 · read with `plan.md`, `plan-phase-2.md`, `ai-study-list.md`
> **Assumptions:** 8–10 h/week (9 h used below), user-funded tokens, MacBook M1 until the upgrade, Azure budget ~30 USD/month
> **v1.1:** knowledge-base curation track added (§8): sub-topics and priorities (P3a), KB curator with promotion eval
> (P3b), refresh job (P4), optional autonomous curation L4 after Phase 6 (§12) — +27 h core, +14 h optional

---

## 1. Summary

| Phase | Theme | Core h | Optional h | Weeks @ 9 h | Window (if P2 ends mid-Feb 2027) | Exit demo |
|---|---|---|---|---|---|---|
| 1 | Foundation, RAG slice, eval, tracing | ~76 | — | — | ends ~mid-Nov 2026 | Cited streamed answers, retrieval metrics, traces |
| 2 | Agent | ~99 | (in cut line) | 11 + 2 buffer | mid-Nov 2026 → mid-Feb 2027 | Agent with MCP tools, approvals, audit, agent eval; taxonomy and gap signals recorded |
| **3a** | Retrieval quality, sub-topics & skills | ~71 | — | ~8 | → mid-Apr 2027 | Before/after table for every retrieval technique; a canonical runbook outranks upstream docs for its sub-topic; code questions with file citations; skills loaded on demand |
| **3b** | Evaluation, safety, cost, KB curator | ~74 | ~22 | ~8 | → mid-Jun 2027 | Calibrated judge as CI gate; guardrails blocking the red-team suite; cost per answer down with routing + cache; a curator batch closes gap questions and is promoted from its report |
| **4** | Kubernetes | ~40 | — | ~5 | → mid-Jul 2027 (+2 buffer weeks in summer) | Whole stack on k3d via Helm, TLS, network policies, read-only K8s tool, KB refresh CronJob |
| **5** | Azure | ~46 | — | ~5 | → early Sep 2027 | Ephemeral AKS from a workflow; always-on lean demo URL |
| **6** | MLOps, local models, polish | ~60 | ~38 | ~7 | → late Oct 2027 | Fine-tuned model rolled out via alias; local-vs-API table; system card; demo video |
| *opt.* | Autonomous open-web curation (L4) | — | ~14 | ~2 | after P6, only after a go/no-go (§12) | The curator discovers, vets and promotes sources without per-batch approval, within hard limits |
| | **Total (incl. P1)** | **~466** | **~74** | | | |

The original estimate of 250–300 h does not cover the decided scope. If the date matters more than completeness, cut
in this order: L4 (optional anyway) → P6 options → P3b options → KB refresh job (P4) → P3a code-aware RAG (keep for the
"developer assistant" story if at all possible) → P4 GitOps → P6 polish items.

---

## 2. Dependencies

```
P1 ──► P2 ──┬─► P3a ──────────────┬─► P3b ──► P4 ──► P5 ──► P6 ──► (L4, optional)
            │   sparse vectors     │   ACL ─► semantic cache
            │   → hybrid + first   │   synthetic data ─────────────► P6 fine-tuning
            │     alias swap       │   judge + guardrails ─► eval gate, promotion eval
            │   tool groups        │   red-team seed (P2) ─► suite + guardrails
            │   → skills           │
            │   topics, priorities,│
            │   lifecycle ─────────┴─► curator staging (P3b) ─► refresh job (P4) ─► L4
            │
            ├─ conversations (P2) ─► query rewriting (P3a), memory + compaction + feedback loop (P3b)
            └─ gap signals (P2) ───► gap clusters for the KB curator (P3b)
```

| Dependency | Why |
|---|---|
| P2 tool registry and tool groups → P3a skills | Skills package tool groups with instructions; designed into the registry now |
| P2 conversations → P3a query rewriting, P3b memory, compaction, feedback loop | All need persisted multi-turn history |
| P2 taxonomy + document topics → P3a chunk labels, prefix filters, priorities | Labels exist before they are used; the router already reads the descriptions |
| P2 gap signals → P3b KB curator | Gap clusters need a history of unanswered questions; it can't be backfilled |
| bge-m3 (ADR-0004) + Qdrant 1.19 → P3a hybrid | Sparse vectors from the same model; new collection = first real alias swap |
| P3a contextual-retrieval pass → P3a chunk labels | Sub-topic labels come out of the same LLM call; fallback: embedding similarity |
| P3a lifecycle + priorities → P3b staging | `staged` extends the lifecycle field; canonical boosts protect curated documents from displacement |
| P3b ACL filtering → P3b semantic cache | Cache keys must include the permission scope or answers leak across users |
| P3b judge + guardrails → P3b promotion eval | Faithfulness scoring and injection/PII scans gate every promotion |
| P3b synthetic data → P6 fine-tuning | Training pairs and hard negatives come from the P3b generator |
| P3b judge calibration → P3b CI gate | An uncalibrated judge must not block merges |
| P3b curator → P4 refresh job (L3) → optional L4 | Each level reuses the previous level's gates and needs less human review |
| P4 Helm chart → P5 AKS | P5 deploys the same chart; Container Apps uses the same images |
| P4 network policies → P5 | Egress allow-list (OpenRouter, GitHub, Azure) reused in the cloud |
| New Mac → P6 local models | Phase 6 order adapts if the hardware is late (see §7) |

---

## 3. Phase 3a — Retrieval quality, sub-topics & skills (~71 h)

**Goal.** Every retrieval technique ships with a before/after row on golden set v2; documents get sub-topics and
priorities; the agent gets skills.
**Exit demo.** Comparison table (P1 dense baseline → hybrid → + rerank → + contextual) per domain and language; a
canonical runbook outranks upstream docs for its sub-topic, with numbers; a question about this repo's code answered
with file/line citations; a skill loaded on demand, visible in the trace.

| Milestone | Content | h | Study list |
|---|---|---|---|
| M3a.1 | Async ingestion queue (ADR: Postgres `SKIP LOCKED` in NestJS vs. Redis-based worker); **re-index job** that builds a new collection, runs the golden set and swaps `kb_current` only if metrics ≥ baseline; rollback command | 10 | #8, #9 |
| M3a.2 | Hybrid search: bge-m3 dense + sparse, Qdrant Query API prefetch + RRF fusion | 5 | #21, #6 |
| M3a.3 | Reranking: cross-encoder on top-50 → top-5, latency budget, measured | 6 | #22 |
| M3a.4 | Query transformation: standalone rewrite of follow-ups (needed with conversations), multi-query, HyDE — each measured separately | 6 | #23 |
| M3a.5 | Docling parsing + parent-child chunking (small chunks indexed, parent section to the LLM) | 8 | #2, #3 |
| M3a.6 | Contextual retrieval: LLM context per chunk at ingest, document prefix cached | 6 | #24, #39 |
| M3a.7 | **Sub-topics & priorities** (§8.4, §8.5): chunk-level sub-topic labels from the contextual-retrieval pass (fallback: embedding similarity to the descriptions); prefix filters; `lifecycle` `active`/`retired`; per-document priority `canonical`/`normal`/`low` with topic scope, boost applied after reranking, canonical sources marked in the prompt; documents UI for priority and retire; before/after on golden questions per pinned topic | 6 | #7, #17 |
| M3a.8 | Code-aware RAG: tree-sitter chunking for this repo (TypeScript + Python), symbol/path metadata, code eval set | 12 | #25 |
| M3a.9 | Skills with progressive disclosure: `SKILL.md` loader in the harness; first skills = CI-failure triage, ADR writer, RAG debugging; tool groups move under skills | 8 | #37 |
| M3a.10 | Golden set v2 (+ code items), ADRs, README table | 4 | #17 |

**Decisions to make:** queue technology · reranker model (CPU latency on M1) · Docling vs. pypdf per file type · skill
format and loading trigger · whether contextual retrieval stays on (cost vs. gain) · boost weights and scope rules ·
sub-topic list v2.
**Watch:** Docling and rerankers are heavy on the M1 — measure memory; keep `e5-small`/CPU fallbacks for CI.

---

## 4. Phase 3b — Evaluation, safety, cost, KB curator (~74 h core + ~22 h options)

**Goal.** Quality is gated in CI, the system defends itself, cost per answer goes down with evidence, and the corpus
grows where the assistant fails.
**Exit demo.** A PR that degrades answers is blocked by the judge gate; the red-team suite runs green with guardrails on
(and shows what fails with them off); cost and latency per answer before/after routing + cache; the assistant remembers a
user's goals across conversations, and the user can edit or delete them; a curator batch closes gap questions and is
promoted from its report.

| Milestone | Content | h | Study list |
|---|---|---|---|
| M3b.1 | Generation eval (faithfulness, relevance, citation accuracy, refusal) with an LLM judge **calibrated on ~50 own labels** (agreement, Cohen's kappa) | 10 | #40, #41 |
| M3b.2 | Synthetic data: questions from chunks incl. hard variants, dedupe, human review → golden set growth + training pairs for P6 | 5 | #44 |
| M3b.3 | Eval as CI gate (deterministic on every PR, judge runs nightly / on demand vs. baseline) + online feedback loop (thumbs → review queue → eval items) | 5 | #43, #45 |
| M3b.4 | ACL-filtered retrieval: Keycloak groups → `allowed_groups` filter, enforced before the LLM; per-tenant IDF check for sparse | 6 | #47, #7 |
| M3b.5 | Guardrails + red-team suite v1: PII redaction (Presidio) before the LLM, injection classifier, groundedness check on answers; suite covers OWASP LLM, Agentic and MCP Top 10, incl. poisoned documents | 12 | #46, #48, #20 |
| M3b.6 | Cost: model routing / cascade (cheap first, escalate on failed check), semantic cache (after ACL, permission-scoped keys, invalidation on document change), prompt-caching optimization | 10 | #49, #50, #39 |
| M3b.7 | Long-term memory: user profile (goals, skills, progress), explicit save + user-visible edit/delete, limits on what is stored | 8 | #51 |
| M3b.8 | Context compaction for long conversations | 4 | #12 |
| M3b.9 | **KB curator (L2, §8):** gap clusters from unanswered and thumbs-down questions (embedding clustering, LLM label, mapped to sub-topics → coverage map); search tool limited to allow-listed hosts with a per-host licence record; candidate list (URL, licence, gap, sub-topic); staged ingest with provenance; promotion eval run and report (§8.3); batch approval UI; retire suggestions (superseded ADRs, dead links); `gap_v1` set; curation metrics | 14 | #35, #8, #45, #20 |
| *Option* | Sandboxed code execution, **local** container sandbox (no network, CPU/memory/time limits); ACA dynamic sessions in P5 | 8 | #36 |
| *Option* | Text-to-SQL with guardrails on a sample Postgres DB (SELECT-only parser check, read-only role, row limit, timeout, `EXPLAIN`) | 8 | #34 |
| *Option* | Per-user GitHub access: GitHub as brokered IdP + Keycloak Identity Brokering API v2 → tool calls as the user | 6 | #31 |

**Decisions to make:** judge model and rubric · injection classifier (hosted vs. open model, cost) · cache store
(Qdrant collection vs. Postgres) · memory store and retention · search provider and clustering method for the curator ·
per-host licence records · whether the option items are worth their hours.
**Order:** M3b.9 needs M3b.1 (judge) and M3b.5 (guardrails) first.
**Possible split:** if P3b runs long, move M3b.7 memory and M3b.8 compaction to P6.

---

## 5. Phase 4 — Kubernetes (~40 h)

**Goal.** The full stack runs on a local k3d cluster from one Helm chart, production-shaped.
**Exit demo.** `make k3d-up && helm install` → HTTPS login via Keycloak in production mode; network policies block
unexpected egress; the agent answers "Which pods restarted in the last hour?" through a read-only K8s tool; the KB
refresh CronJob promotes a changed page from an L3 host and sends everything else to the review queue.

| Milestone | Content | h | Study list |
|---|---|---|---|
| M4.1 | Helm umbrella chart: web, api, ai-service (+ `/mcp`), github-mcp, keycloak (production mode), postgres (ADR: CloudNativePG vs. chart), qdrant (official chart), phoenix; values per environment | 12 | — |
| M4.2 | k3d cluster, ingress (Traefik), TLS (cert-manager + local CA), Keycloak `start` with hostname, realm import job | 8 | — |
| M4.3 | Hardening: probes, requests/limits, HPA for stateless apps, PodDisruptionBudgets, default-deny NetworkPolicies + egress allow-list, non-root, read-only root FS | 6 | — |
| M4.4 | Secrets and config: External-Secrets-ready layout, runtime `config.json` from values | 3 | — |
| M4.5 | GitOps-ready: Argo CD (or Flux) Application manifests, kustomize overlays — ADR | 3 | — |
| M4.6 | SRE read-only tool: own read-only K8s tool (pods, events, logs, rollout status) with a read-only ServiceAccount; agent eval tasks | 4 | #33, #30 |
| M4.7 | **KB refresh CronJob (L3, §8.1):** re-fetch approved sources (ETag / Last-Modified + content hash); a changed page becomes a new staged version → promotion eval → auto-promote only if every gate passes and the host has L3 status, otherwise review queue; weekly digest; kill switch in values | 4 | #8, #43 |

**Watch:** k3d + the whole stack is tight on an M1 with 16 GB — reduced resource profile, Phoenix optional in-cluster,
or wait for the new Mac.

---

## 6. Phase 5 — Azure (~46 h)

**Goal.** The project runs in the cloud: an always-on lean demo and an ephemeral AKS showcase, both from CI.
**Exit demo.** A GitHub Actions run creates AKS, deploys the chart, runs the smoke test and destroys the cluster; the
public demo URL stays up within the budget.

| Milestone | Content | h | Study list |
|---|---|---|---|
| M5.1 | Terraform: resource group, ACR, AKS (Free tier), Postgres Flexible (burstable), Key Vault, budgets; remote state | 12 | — |
| M5.2 | GitHub → Azure OIDC federation; workload identity for pods; Key Vault CSI or External Secrets; GitHub App replaces PATs | 6 | #31 |
| M5.3 | Ephemeral AKS workflow: create → deploy → smoke → destroy, with a TTL safeguard | 8 | — |
| M5.4 | Always-on lean demo on Container Apps (scale-to-zero where possible), incl. the M4.7 refresh job as a scheduled Container Apps job; Qdrant hosting decision (in-cluster vs. Qdrant Cloud free tier); cost check against 30 USD/month | 8 | #6 |
| M5.5 | DNS, TLS, Keycloak production config, self-registration policy for the public demo | 5 | — |
| M5.6 | Cloud observability: Phoenix in-cluster with a volume vs. Azure Monitor via OTLP — ADR | 3 | #18 |
| M5.7 | AKS-MCP as local stdio demo against the ephemeral cluster; Azure MCP via workload identity; ACA dynamic sessions if the P3b sandbox option was done | 4 | #30, #36 |

**Constraints:** API models only, no GPU nodes. Region and quota from ADR-0006.

---

## 7. Phase 6 — MLOps, local models, polish (~60 h core + ~38 h options)

**Goal.** Close the MLOps loop on a small model, prove local inference with numbers, and finish the portfolio.
**Exit demo.** A fine-tuned model beats the base model on the held-out set and is rolled out (and rolled back) by moving
the Qdrant alias; a published local-vs-API table; system card; 3-minute demo video.

| Milestone | Content | h | Study list |
|---|---|---|---|
| M6.1 | MLflow tracking server + model registry (aliases champion / challenger) | 6 | #56 |
| M6.2 | Fine-tune a **small** embedding model or a reranker on P3b synthetic pairs + hard negatives (bge-m3 is heavy to fine-tune on an M1; use MPS or a rented GPU notebook); held-out eval | 14 | #55 |
| M6.3 | Rollout via re-index + alias swap with eval gate; rollback drill | 4 | #9, #56 |
| M6.4 | Local models on the new Mac: Ollama and/or MLX, quantization levels vs. RAM; model joins the UI switch | 8 | #57 |
| M6.5 | Local-vs-API benchmark on answer, tool-calling and agent eval suites; published table | 8 | #58, #42 |
| M6.6 | System card v1 (from the P2 stub), incl. corpus sources, curation levels in use and how to report a bad source | 4 | #59 |
| M6.7 | Polish: dark mode, Signal Forms, Lighthouse targets, Trivy scanning, BFF cookie pattern | 12 | — |
| M6.8 | Demo video + final README | 4 | — |
| *Option* | GraphRAG over services, ADRs and dependencies — only if evals show multi-hop failures | 12 | #53 |
| *Option* | Multimodal ingestion of architecture diagrams (vision-model captions) | 8 | #54 |
| *Option* | Multi-agent experiment: domain specialists vs. one agent + skills (e.g. the curator as its own agent), decided by eval | 10 | #52 |
| *Option* | Framework comparison (one agent framework vs. the own harness on the same evals) | 8 | — |

**If the new Mac is late:** do M6.1–M6.3 and M6.6–M6.8 first; M6.4/M6.5 last.
Autonomous curation (L4) is not a Phase 6 option: it comes after Phase 6 and only after a go/no-go (§12).

---

## 8. Knowledge-base curation track (cross-phase)

**Goal.** The corpus grows where the assistant fails, and every change to it is measured, attributable and reversible.

### 8.1 Automation ladder

| Level | What happens | Phase | You decide |
|---|---|---|---|
| L0 | You upload documents | P1 | Everything |
| L1 | The agent proposes one URL via `kb.ingest_url`; approval card | P2 | Each document |
| L2 | KB curator: gap clusters → search on allow-listed hosts → staged ingest → promotion eval → report | P3b (M3b.9) | Each batch |
| L3 | Refresh of already-approved sources: a changed page is promoted automatically if every gate passes and its host has L3 status | P4 (M4.7), runs in P5 | Which hosts get L3; everything that fails a gate |
| L4 | Open-web discovery with automatic promotion | Optional, after P6 (§12) | Go/no-go, audit samples |

At every level you keep: adding a host and its licence record, priorities, taxonomy changes and retiring documents. The
system suggests; you decide.

**Trust is earned per host, from data:** acceptance rate of proposals, gaps closed per batch, displacement incidents,
cost per promoted document. Starting rule for L3: ≥ 20 reviewed proposals from the host, ≥ 90 % accepted, no
displacement or safety incident.

### 8.2 Data model (Postgres `documents` + Qdrant payload)

| Field | Values | From |
|---|---|---|
| `domains[]` | the nine domains (D22) | P1 |
| `topics[]` | `domain/subtopic` from `taxonomy.yaml` (D48); document level → chunk level | P2 → P3a |
| `lifecycle` | `active`, `retired` → + `staged` | P3a → P3b |
| `priority`, `priority_topics[]` | `canonical`, `normal`, `low` + topic scope | P3a |
| Provenance | `source_url`, `fetched_at`, `etag`, `content_sha256`, `licence`, `added_by` (`user` / `curator`), `approval_id`, `batch_id`, `version` | P3b |

- Normal search filters `lifecycle = active`. Content changes are payload updates (no re-embedding); embedding or
  chunking changes keep using a new collection + alias swap (M3a.1).
- From P3b, point IDs include the document version (`UUIDv5(doc_id:version:chunk_index)`, changing D10), so a staged
  version can sit next to the active one; promotion retires the previous version.
- A batch is rolled back by retiring its `batch_id`.

### 8.3 Promotion eval (one run per staged batch)

Baseline: `lifecycle = active`. Candidate: `active` + the staged batch.

| Check | Pass criterion (starting values) | Cost |
|---|---|---|
| Gaps closed | Real gap questions from the batch's clusters — never questions generated from the new documents. A staged chunk ranks in the top 5 above the threshold, and the agent answers with a citation to it instead of declining; judge faithfulness ≥ the M3b.1 threshold | Retrieval free; answers + judge within the eval cost cap |
| Nothing pushed out | Golden set hit@5 / nDCG@10 drop ≤ 0.02; per document, golden questions where its chunks push the expected document out of the top 5 = 0 | Free |
| Abstention intact | Questions labelled unanswerable stay unanswered; if a new document genuinely answers one, you relabel it | Answers only |
| Safety & hygiene | Injection classifier and PII scan on every chunk; near-duplicates (cosine > 0.95 to an active chunk) flagged; licence recorded; red-team probe tasks that retrieve the new chunks pass the forbidden-tool checks | Small |

Output: a promotion report with one row per document — gaps closed, golden questions pushed out, flags, licence and a
suggested decision (`promote`, `reject`, `review`). After promotion the gap questions join the versioned `gap_v1` set, so
later changes can't silently lose them.

### 8.4 Priorities

- Per document `canonical`, `normal` or `low` with a topic scope, plus `retired`; set in the documents UI (editor+),
  audited.
- **Ranking:** boost only when the question's route matches the scope and the chunk already clears the threshold;
  applied in the AI service **after reranking**, because the reranker would undo Qdrant's formula-based score boosting.
- **Prompt:** canonical sources are marked, with a rule to prefer them when sources conflict (your runbook beats upstream
  docs for "how do *we* …").
- **Measured** like any retrieval change: golden questions per pinned topic, before/after.

### 8.5 Taxonomy

- `config/taxonomy.yaml` (P2, D48): nine domains with descriptions + `domain/subtopic` ids, ~5–8 per domain, starting
  with devops, cloud, security, architecture; versioned.
- Document labels set by you (LLM suggestions from P3a); chunk labels automatic from the contextual-retrieval pass, with
  embedding similarity to the descriptions as fallback.
- Hard filters only at domain level; sub-topics drive boosts, reports and the **coverage map** (active chunks + open gap
  questions per sub-topic), which tells the curator where to search.
- Per-sub-topic eval breakdown once P3b synthetic data has grown the golden set.

---

## 9. Option E1 — early cloud preview after Phase 2

Move a thin Container Apps deployment (parts of M5.1, M5.4, M5.5, ~20 h) to directly after P2.

| | Decided order | With E1 |
|---|---|---|
| Live demo URL | ~late Aug 2027 | ~mid-Mar 2027 |
| Extra hours | — | ~+12 h net (Terraform reworked when AKS lands) |
| Running cost | from ~late Aug 2027 | from ~Mar 2027, within the 30 USD budget only with scale-to-zero and Qdrant Cloud free tier |
| Learning order | AI topics uninterrupted until P4 | Short infra detour between P2 and P3a |

Recommendation: decide at the end of P2, based on how much a live link matters for applications and on the token and
cloud budget at that point.

---

## 10. Study-list coverage (all 59 topics)

| # | Topic | Phase(s) |
|---|---|---|
| 1 | RAG | P1 |
| 2 | Document parsing | P1 (pypdf), P3a (Docling) |
| 3 | Chunking strategies | P1, P3a (parent-child, code) |
| 4 | Text embeddings | P1 |
| 5 | Embedding selection & benchmarking | P1 (ADR-0004), P6 (fine-tuned challenger) |
| 6 | Vector DB & ANN | P1, P3a (sparse), P5 (hosting) |
| 7 | Metadata filtering | P1, P2 (topics), P3a (prefix filters, priorities), P3b (ACL) |
| 8 | Idempotent ingestion | P1, P3a (queue), P3b (staging + provenance), P4 (refresh job) |
| 9 | Alias re-indexing | P3a (first swap), P6 (rollout); content changes use the payload lifecycle (§8.2) |
| 10 | Grounded generation & citations | P1, P2 |
| 11 | Thresholds & abstention | P1, P2 (incl. gap signals) |
| 12 | Context engineering & budgets | P1, P2, P3b (compaction) |
| 13 | Provider abstraction | P1, P2 (model registry), P6 (local) |
| 14 | Streaming & cancellation | P1, P2 (mid-run) |
| 15 | Fake LLM | P1, P2 (scripted tool calls) |
| 16 | Token & cost tracking | P1, P2 (per user, caps) |
| 17 | Retrieval evaluation | P1, P2 (blocking), P3a (golden set v2, priorities), P3b (promotion eval, `gap_v1`) |
| 18 | Tracing | P1, P2 (agent + MCP), P5 (cloud) |
| 19 | Data privacy | P1, P2 (tool outputs), P3b (PII redaction, curator PII gate), P6 (local) |
| 20 | Prompt injection | P1, P2 (untrusted tool output), P3b (guardrails, curator staging) |
| 21 | Hybrid search | P3a |
| 22 | Reranking | P3a |
| 23 | Query transformation | P3a |
| 24 | Contextual retrieval | P3a |
| 25 | Code-aware RAG | P3a |
| 26 | Tool calling & agent loop | P2 |
| 27 | Structured outputs | P2 |
| 28 | Agentic RAG | P2 |
| 29 | Query & domain routing | P2 (domain, taxonomy), P3b (model) |
| 30 | MCP | P2, P4 (K8s tool), P5 (AKS-MCP) |
| 31 | Tool / MCP auth, on-behalf-of | P2 (token exchange, MCP auth), P3b option (GitHub per user), P5 (workload identity) |
| 32 | Human-in-the-loop | P2, P3b (curator batch approval) |
| 33 | Permission model & audit | P2, P4 |
| 34 | Text-to-SQL | P3b option |
| 35 | Safe web access | P2 optional (fetch), P3b (curator search, allow-listed), L4 optional (open web) |
| 36 | Sandboxed code execution | P3b option (local), P5 (ACA sessions, only if the option was done) |
| 37 | Skills | P3a |
| 38 | Prompt versioning | P2 |
| 39 | Prompt caching | P2 (layout), P3a (contextual), P3b (optimization) |
| 40 | Generation evaluation | P3b |
| 41 | LLM-as-judge & calibration | P3b |
| 42 | Agent evaluation | P2, P6 (local models) |
| 43 | Eval as CI gate | P2 (retrieval), P3b (full gate, promotion gate), P4 (refresh gate) |
| 44 | Synthetic data | P3b |
| 45 | Online feedback loop | P2 (capture + gap signals), P3b (loop + curator) |
| 46 | Red teaming | P2 (seed), P3b (suite incl. poisoned documents) |
| 47 | ACL-filtered retrieval | P3b |
| 48 | Guardrails | P3b |
| 49 | Model routing & cascades | P3b |
| 50 | Semantic caching | P3b |
| 51 | Long-term memory | P3b |
| 52 | Multi-agent orchestration | P6 option |
| 53 | GraphRAG | P6 option |
| 54 | Multimodal ingestion | P6 option |
| 55 | Embedding & reranker fine-tuning | P6 |
| 56 | MLOps (tracking, registry, rollout) | P6 |
| 57 | Local inference & quantization | P2 optional (proof), P6 |
| 58 | Local vs. API benchmarking | P6 |
| 59 | System card | P2 (stub), P6 |

Topics that stay uncovered if all options are cut: #34, #36, #52, #53, #54.

---

## 11. Open questions for later phases

- **P3:** queue technology; reranker and judge models; whether P3b's options are worth their hours.
- **KB curation:** sub-topic list v2; boost weights; search provider for the curator; per-host licence records; which
  hosts qualify for L3; whether L4 is ever switched on.
- **P4:** Postgres in-cluster (CloudNativePG) vs. chart; GitOps tool (Argo CD vs. Flux); does the M1 carry k3d with the full stack?
- **P5:** Qdrant hosting (in-cluster vs. Qdrant Cloud free tier); where traces go in the cloud; Container Apps vs. AKS
  for the always-on demo; whether option E1 moves the first deploy forward.
- **P6:** when the new Mac arrives; fine-tuning target (small embedding model vs. reranker); Ollama vs. MLX.
- **All phases:** the monthly token cap and the total time budget (~466 h core) — revisit at each phase end.

---

## 12. Optional — L4 autonomous open-web curation (after Phase 6, ~14 h)

**Not planned by default.** It is listed so the decision is explicit, and it only starts after a go/no-go against the
criteria below.

**What it adds on top of L2/L3**
- Discovery beyond the allow-list: open-web search, with a domain reputation score
- Automatic licence detection from machine-readable metadata (Creative Commons markup, SPDX identifiers); pages without
  one are skipped
- `robots.txt` and site terms respected
- Automatic promotion through the §8.3 gates, plus a quarantine period (e.g. 7 days staged), a weekly rate limit, a
  random human audit sample (e.g. 10 % of promotions), a weekly digest and a kill switch
- Documents promoted by L4 are labelled as such in citations

**Risks**

| Risk | Why it matters here | Minimum mitigation before a go |
|---|---|---|
| Corpus poisoning / persistent injection (OWASP LLM04 Data and Model Poisoning, LLM08 Vector and Embedding Weaknesses) | One ingested page influences every later answer and tool call; unlike a chat turn, the effect persists | Injection classifier and red-team probes as gates, quarantine period, provenance and batch rollback; untrusted-content handling (D31) stays on |
| Attacker-steered gaps | On the public demo anyone can ask questions; crafted questions can steer the curator to search for and ingest an attacker's page | Gap signals only from authenticated editor+ users; minimum cluster size; viewer and anonymous questions ignored |
| Licences and copyright | Every document needs a checked licence (D22); automatic detection is unreliable, and answers quote the content | Only pages with machine-readable open licences; attribution recorded; unknown → skip |
| Misinformation and outdated content (OWASP LLM09) | Search ranks popularity, not correctness, and a wrong page gets cited with confidence; the judge checks faithfulness to the source, not truth | Domain reputation, canonical documents outrank new ones, human audit sample |
| Displacement of curated content | New pages push your runbooks and ADRs out of the top results | Displacement gate at zero, canonical boosts |
| Privacy (D25) | Pages may contain personal data, and every retrieved chunk goes to OpenRouter | PII scan as a hard gate; pages with hits are dropped |
| Cost (OWASP LLM10 Unbounded Consumption) | Search, fetch, contextual pass and eval per candidate, running unattended | Weekly budget, rate limit, cost per promoted document tracked |
| Self-reinforcing loops | Answers built on curator documents change future gap signals | Judge the curator on the golden and `gap_v1` sets, not only on live traffic |
| Credibility of the portfolio | The corpus and its citations are what reviewers see first | Off by default; L4 documents labelled in citations; corpus statistics and L4 limits in the system card |

**Go/no-go (all required)**
- L2 and L3 have run for at least 3 months with ≥ 90 % of proposals accepted and no safety or displacement incident
- The red-team suite includes poisoned pages and steered gaps, and passes with the guardrails on
- A rollback drill has been done: retire a batch and verify that answers revert
- The system card describes L4, its limits and how to report a bad source

**Scope if go:** enabled per domain in config, off by default, kill switch in values. Study list: #35, #20, #46, #48, #59.

---

## Sources checked (2026-10-18, 2026-10-19)

- Qdrant 1.19 (incl. keyword prefix matching) — https://qdrant.tech/blog/qdrant-1.19.x/
- Qdrant score boosting (formula queries, since 1.14) — https://qdrant.tech/documentation/search/search-relevance/ · https://qdrant.tech/blog/qdrant-1.14.x/
- Keycloak release notes (identity brokering API v2, token exchange delegation) — https://www.keycloak.org/docs/latest/release_notes/index.html
- AKS-MCP v0.0.20 (stdio-only) — https://github.com/Azure/aks-mcp/releases/tag/v0.0.20
- OWASP Top 10 for Agentic Applications 2026 — https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026
- OWASP Top 10 for LLM Applications 2025 (LLM04, LLM08, LLM09, LLM10) — https://www.indusface.com/learning/owasp-top-10-llm/
