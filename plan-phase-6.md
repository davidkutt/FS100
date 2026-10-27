# plan-phase-6.md — Phase 6: MLOps, Local Models & Polish

> **Parked 2026-10-26** — see [plan-daily-use.md](plan-daily-use.md).

> **Project (working title):** `kb-agent` — an assistant for the **"Dev of the future"**.
> **Document scope:** Phase 6 of 6 · **Status:** Draft v1 · **Updated:** 2026-10-24 · builds on `plan.md` v2,
> `plan-phase-2.md` v1.1, `plan-phase-3.md` v1, `plan-phase-4.md` v1, `plan-phase-5.md` v1 and
> `roadmap-phases-3-6.md` v1.5
> **Estimated effort:** ~63 h core (range 52–82 h) + up to ~38 h options · ~7 weeks at 8–10 h/week + 1 buffer week
> (holidays)
> **Start:** after Phase 5 (expected late October 2027) → core ends ~end of December 2027 → options, if the gate
> passes, ~mid-February 2028
> **Decisions taken for this plan:** plan on the **M1 with 16 GB** (a new Mac becomes an add-on, not a dependency) ·
> fine-tune the **small CPU reranker on the M1**, distilled from `bge-reranker-v2-m3` · all four options are of interest
> and go through the options gate in a fixed order with preconditions

### Review outcome (changes vs. `roadmap-phases-3-6.md` §7)

| Change | Reason |
|---|---|
| **Kick-off M6.0 (2 h)**; polish split into **supply chain M6.4 (4 h)** and **web polish & BFF M6.8 (10 h)** | Like every phase, versions and the options gate need a start; the BFF pattern is larger than a polish item. Phase 6 grows from ~60 h to ~63 h |
| **Fine-tuning target = the CPU reranker**, by **distillation** from the MPS reranker | Your decision. It trains on the M1 without a GPU, and it improves exactly the model the k3d-lite profile and the cloud demo run |
| **Rollout by moving an MLflow model alias** instead of a Qdrant alias | A reranker doesn't change the vectors, so no re-index; the Qdrant alias swap is already shown in P3a and P5 |
| **Abstention threshold ships with the model** | Abstention is calibrated on reranker scores (D57); a new reranker changes the score distribution |
| **Local models sized for 16 GB** (≤ ~9B at 4-bit) and benchmarked on **frozen retrieval outputs** | The new Mac is not confirmed; frozen contexts compare generators fairly and don't need the stack running next to the model |
| **Ollama as default local runtime, mlx-lm as comparison** | Ollama 0.40 runs supported architectures on Apple's MLX by default; "Ollama vs. MLX" became "Ollama's MLX runner vs. plain mlx-lm" |
| **BFF cookie pattern per RFC 10017** | Published in August 2026 as BCP 212; it strongly recommends a BFF for business applications, so tokens leave the browser |
| **Supply chain with GitHub artifact attestations; scanner job isolated** | `actions/attest` covers provenance and SBOM for public repos at no cost; the March 2026 compromise of `trivy-action` tags shows why scanners run pinned and without credentials |
| **EU AI Act Art. 50 in the system card** (disclosure added to P5) | Transparency obligations for chatbots are enforceable since 2026-08-02 and were not deferred by the Digital Omnibus |
| **Signal Forms** in the polish | Production-ready since Angular 22 (June 2026) |
| **Options gated with preconditions** and a fixed order | You want all four; ~38 h would otherwise double the phase silently |

---

## 0. Roadmap context

| Phase | Theme | Core hours | Result |
|---|---|---|---|
| 1 | Foundation + RAG slice + eval + tracing | ~76 | Streamed, cited answers; retrieval metrics; Phoenix traces; CI green |
| 2 | Agent | ~99 | Agent with MCP tools, approvals, conversations, audit, agent eval; taxonomy + gap signals |
| 3a | Retrieval quality, sub-topics & skills | ~75 | Hybrid + rerank + contextual + code-aware RAG, gated alias swap, priorities, skills |
| 3b | Evaluation, safety, cost, KB curator | ~76 | Judge gate, guardrails, ACL, cascade + cache, memory, compaction, curator (L2) |
| 4 | Kubernetes | ~46 | Whole stack on k3d from Helm charts, Gateway API + TLS, operators, hardening, Argo CD, read-only K8s tool, refresh CronJob (L3) |
| 5 | Azure | ~55 | Lean demo on Container Apps + SWA (~30 USD/month), ephemeral AKS via Argo CD, OIDC + managed identity, Key Vault, GitHub App; workflow integration (option) |
| **6 (this doc)** | **MLOps, local models, polish** | **~63** | Distilled CPU reranker rolled out and back via an MLflow alias, local-vs-API benchmark on the M1, system card v1, supply-chain attestations, BFF, demo video, v1.0 |

After Phase 6: optional L4 go/no-go (`roadmap-phases-3-6.md` §12).

---

## 1. Goal and demo script

**Goal.** Phase 6 closes the MLOps loop on one model, proves local inference with numbers, and finishes the portfolio.
A small multilingual cross-encoder — the reranker that `k3d-lite` and the cloud demo run on CPU — is fine-tuned on the
M1 by distillation from `bge-reranker-v2-m3`, tracked in MLflow, promoted only through an eval gate, and rolled out and
back by moving its registry alias. Local models that fit 16 GB are compared with the API tiers on the project's own
suites. The system card, supply-chain attestations, a BFF that keeps tokens out of the browser, the web polish, a
3-minute demo video and a `v1.0.0` release complete the project.

**Acceptance demo**

1. `pnpm mlops:up` → the MLflow UI shows experiment `rerank-ft` with the baseline runs (base student, teacher) and the
   training runs; registry model `kb-rerank` with `champion` (base) and `challenger` (fine-tuned).
2. `pnpm mlops:gate kb-rerank` → gate report: nDCG@10 on golden `test` base → fine-tuned (≥ +0.02), per language, on
   unseen documents, abstention F1 after threshold recalibration, p95 CPU latency → pass → `champion` moves.
3. The `models-build` workflow builds the new model set; `k3d-lite` and the cloud demo deploy it; the retrieval
   inspector shows the reranker version and its threshold; the post-deploy eval smoke is green.
4. Rollback drill: `pnpm mlops:rollback kb-rerank` → the previous version is back in both environments within 15 min,
   and the eval numbers revert.
5. `pnpm bench:local` on the M1 → local-vs-API table (judged quality, tool calls, TTFT, tokens/s, peak memory, cost)
   for 2–3 local models × 2 quantizations against the API tiers; published in the README and the system card.
6. Dev model picker → `local-qwen3.5-9b-q4` → a cited answer streams from the Mac; agent mode is offered only for local
   models above the tool-calling threshold.
7. Public demo login → no token in browser storage or in a script-readable cookie (DevTools); the session cookie is
   `__Host-Http-kb-session`, HttpOnly; a POST without the CSRF header → 403; signing out in Keycloak ends the app session
   (back-channel logout).
8. Dark mode follows the system setting and the toggle; Lighthouse CI is green on landing and chat; axe reports no
   serious violations; the forms run on Signal Forms.
9. `gh attestation verify oci://ghcr.io/<owner>/kb-agent-ai@sha256:…` → provenance and SBOM verified; a deploy with an
   unattested digest is refused; the scan job fails on a seeded vulnerable test image.
10. `docs/system-card.md` v1 with generated tables; the chat discloses AI at the first interaction; generated messages
    carry a machine-readable marker.
11. The 3-minute demo video is linked in the README; release `v1.0.0` with changelog and ADR index.

---

## 2. Scope

**In scope**
- MLflow tracking server and model registry (local), model metadata contract, alias-driven model-set builds
- Reranker distillation on the M1: training-data builder (synthetic queries, hard negatives, teacher scores, leakage
  guard), training runs, ONNX int8 export, model card
- Promotion gate with threshold recalibration; rollout and rollback through the alias to k3d and the cloud demo
- Local inference on the M1 (Ollama + mlx-lm), local entries in `models.yaml`, local-vs-API benchmark
- System card v1 incl. EU AI Act Art. 50 transparency measures
- Supply chain: SBOMs, provenance and SBOM attestations, vulnerability scanning, verify-before-deploy, model-set manifests
- Web: BFF cookie pattern, Signal Forms, dark mode, Lighthouse and accessibility budgets, Angular major upgrade
- Demo video, final README, `v1.0.0`

**Out of scope (deferred or not planned)**
- Fine-tuning bge-m3 or another embedding model → not planned (needs a GPU and a full re-index; the same pipeline would
  apply later)
- Local models above ~9B → **add-on** when a new Mac arrives (§8, ~3 h)
- Local models in the cloud demo → not planned (API models only, P5)
- Admission-time signature checks in AKS (policy controller) → not planned; verification happens in the deploy workflows
- L4 autonomous curation → after Phase 6, only after the go/no-go
- Options (GraphRAG, multimodal, multi-agent, framework comparison) → **gated** (D120)

---

## 3. Decisions

Numbering continues from `plan-phase-5.md` (D107). Status: **N** = new · **C** = changes an earlier decision (named).

| # | St. | Topic | Decision | Why / alternatives |
|---|---|---|---|---|
| D108 | N | Hardware | Plan on the **M1 with 16 GB**. Training and benchmarking run with the Docker stack stopped (Mode A services only when a step needs them). Local LLMs ≤ ~9B at 4-bit; 8-bit only up to ~4B. A new Mac triggers a ~3 h add-on (larger models, same suites), never blocks the phase. (ADR-0052) | The new Mac isn't confirmed; every number in this phase must be reproducible on the machine that exists. |
| D109 | N | MLflow | **MLflow 3.17.x** server in the Mode A Compose profile `mlops`; backend store = `mlflow` database in the local Postgres, artifacts on a local volume (`.mlflow/`); no cloud instance. Experiments `rerank-ft` and `local-llm-bench`; registry model `kb-rerank` with aliases `champion` and `challenger`. MLflow is never on the request path: `models-build` resolves the alias at build time. Phoenix stays the trace store. (ADR-0049) | Registry + aliases are the MLOps skills the roadmap asks for; local-only keeps the cloud budget untouched. |
| D110 | C (D57, D82) | Fine-tuning target | The **CPU reranker** of `k3d-lite` and the cloud (as chosen in P3a/P4; expected `mmarco-mMiniLMv2-L12-H384-v1`, Apache-2.0, multilingual, ~0.1 B parameters) is fine-tuned on the M1 by **distillation** from `bge-reranker-v2-m3` (Apache-2.0, the local MPS champion of D57) plus hard negatives. Target: close ≥ 50 % of the student–teacher gap in nDCG@10 on golden `test` at unchanged CPU latency. (ADR-0050) | Your decision; improves the model the public demo actually runs, without GPU cost or re-indexing. |
| D111 | C (D65) | Training data | ~4k synthetic queries from the P3b generator over `active` chunks, DE/EN balanced, **not hand-reviewed** but filtered: dedupe, length and language checks, and the source chunk must be in the teacher's top 10. Positive = source child chunk; **7 hard negatives** per query from hybrid retrieval ranks 3–30, excluding siblings of the same parent, and dropping negatives the teacher scores above the positive (likely false negatives). Teacher scores for every pair. **Leakage guard:** no golden question or near-duplicate (cosine > 0.9) in training; ~20 % of documents held out entirely, so `test` is reported for seen and unseen documents. Dataset hashed and logged to MLflow; generation cost recorded (expected < 1 USD). (ADR-0050) | Reviewed items stay reserved for evaluation; the unseen-document split shows whether gains survive corpus growth. |
| D112 | N | Training recipe | **sentence-transformers 6.x** `CrossEncoderTrainer` on MPS (fp32), max length 384, batch 16, 1–2 epochs. Two variants: (a) `MarginMSELoss` on teacher margins (distillation), (b) binary cross-entropy on positives + hard negatives (labels only); ≤ 6 runs incl. a small learning-rate sweep. Selection on golden `dev`; `test` is evaluated once for the selected run. Export to ONNX with dynamic int8 for CPU; latency measured in the `k3d-lite` container and on Container Apps. Model card with data, teacher, licences, metrics and limits. (ADR-0050) | Distillation vs. labels-only is the interesting comparison; the run cap keeps the M1 time bounded. |
| D113 | N | Promotion gate & rollout | `challenger` → `champion` only if: nDCG@10 on `test` ≥ base + 0.02; per-language drop ≤ 0.01 (DE, EN); unseen-document split not below base; abstention F1 on the unanswerable items not below base **after recalibrating the threshold**; p95 CPU rerank latency ≤ base + 10 %; licence recorded. The threshold and score activation ship in `kb_model.json` (§7.1). Rollout: alias move → `models-build` resolves it → `models-rerank:<version>` image (k3d) and `models/rerank/<version>` on Azure Files (cloud) → config points to the version → deploy → post-deploy eval smoke. Rollback = alias back to `previous`, same pipeline; the old version is kept. (ADR-0051) | One mechanism for promotion and rollback, and the model can't ship without its matching threshold. |
| D114 | C (D40) | Local inference | **Ollama 0.40.x** (MLX runner for supported architectures on Apple Silicon, llama.cpp otherwise) as the default `local` provider through its OpenAI-compatible API; **mlx-lm 0.32.x** server as the comparison runtime. Candidates ≤ ~9B with Apache-2.0 licences first: Gemma 4 E4B, Qwen3.5 4B and 9B (re-checked at M6.0). 4-bit vs. 8-bit (8-bit only ≤ ~4B); 8k context. Models join `models.yaml` as dev-only `local-*` entries; agent mode only for models with ≥ 90 % well-formed tool calls on the suite. (ADR-0052) | Keeps the original brief's API ↔ local switch, with evidence on what a 16 GB laptop can do. |
| D115 | N | Benchmark design | **Frozen retrieval:** the answer suite runs on stored retrieval outputs for golden `test` (DE/EN), so generators are compared on identical contexts. Plus a tool-calling suite (tool choice + argument accuracy from the `agent_v2` tool-selection tasks, fixture MCP servers), an agent subset (~20 tasks, Mode A), and a red-team subset (injection in retrieved content). Metrics: judged faithfulness, relevance and citation accuracy (the calibrated P3b judge, API), refusal correctness, tool-call validity, task success, TTFT, tokens/s, peak memory, cost per answer (local marginal cost = 0, energy noted). Comparators: the API cheap and strong tiers (D70). Results logged to MLflow; table + chart in README and system card; a decision note "where local is good enough". (ADR-0052) | Separates generator quality from retrieval; reproducible on 16 GB. |
| D116 | C (P2 system-card stub) | System card & transparency | `docs/system-card.md` v1 (§7.8), with tables generated from eval results, `models.yaml`, licences, corpus statistics and curation levels (`pnpm docs:system-card`). EU AI Act Art. 50 checklist: AI disclosure at the first interaction (since P5), machine-readable marker on generated messages (`generatedBy: "ai"` + model id in the message API, `X-AI-Generated: true` on answer responses), how to report a bad source. Stated as a good-faith reading, not legal advice. | The obligations apply to chatbots since 2026-08-02; the card is where reviewers check limits and data flows. |
| D117 | C (D104) | Supply chain | Per image on `main`: SBOM (SPDX JSON, Syft via `anchore/sbom-action`), build-provenance and SBOM attestations with **`actions/attest@v4`** (`push-to-registry: true`), vulnerability scan with Trivy pinned by digest in a job with `contents: read` only (no `id-token`, no secrets), failing on fixable CRITICAL/HIGH, ignores only with an expiry date. `deploy-demo` and `e2e-aks` run `gh attestation verify` on every digest before deploying. Model sets get a SHA-256 manifest (model, version, licence, source, teacher) attested the same way. (ADR-0053) | Provenance you can verify; the scanner can't leak anything even if compromised again. |
| D118 | C (P1 SPA auth) | BFF cookie pattern | Following **RFC 10017 (BCP 212)**: NestJS becomes the web app's BFF. Confidential client `kb-web` (authorization code + PKCE); tokens kept server-side in `app.web_sessions` (encrypted); cookie `__Host-Http-kb-session` (`Secure`, `HttpOnly`, `SameSite=Strict`, `Path=/`, no `Domain`); CSRF defence by a required custom header; idle and absolute timeouts; Keycloak back-channel logout; refresh handled by the BFF. The SPA holds no tokens. The cloud setup works because SWA (`kb.example.dev`) and api (`api.kb.example.dev`) are the same site; `fetch` with `credentials: "include"` and exact-origin CORS. Bearer auth stays for MCP clients and headless runs. The public SPA client is removed from the realm. (ADR-0054) | The RFC's recommended pattern; removes token theft via XSS from the threat model. Token-mediating backend is the documented fallback. |
| D119 | C (P1 web decisions) | Web polish | Upgrade to the current Angular major at M6.0; **Signal Forms** for settings, documents, admin and curator forms; dark mode via Material 3 theme tokens (`color-scheme`, system default + toggle); Lighthouse CI budgets on landing and chat (Performance ≥ 90 mobile on landing, Accessibility ≥ 95, Best Practices ≥ 95); axe checks in Playwright; a failing budget blocks merges to `apps/web`. | Measurable polish instead of open-ended styling work. |
| D120 | N | Options gate & order | At M6.0: options only if Phase 5 finished within +10 % of its hours and the token budget holds; they run after the core exit demo, in this order, each with a precondition checked first: **O1 Multimodal** (≥ 15 corpus documents whose key content is in diagrams) → **O2 Multi-agent** (always eligible) → **O3 Framework comparison** (always eligible) → **O4 GraphRAG** (≥ 30 % failures on the multi-hop items of `test`). An option whose precondition fails is recorded as "not needed", with the numbers. Each option has an adopt-or-document rule (§8). | You want all four; the order puts the cheaper, data-backed ones first and the largest, conditional one last. |

---

## 4. Assumptions and open items

| # | Assumption | If wrong |
|---|---|---|
| A41 | Phase 5 is done; deviations recorded in `plan-phase-5.md` before M6.0 | Shift the schedule |
| A42 | Training a ~0.1 B cross-encoder with sentence-transformers 6.x on MPS (fp32) is stable and finishes a run in ≤ 2 h | CPU training overnight, or one free Kaggle/Colab GPU session (public data only) |
| A43 | The P3b generator yields ~4k usable queries for < 1 USD with the cheap model | 2k queries with more negatives per query |
| A44 | The teacher clearly beats the student on `test` (gap ≥ 0.04 nDCG@10) | Smaller target; labels-only fine-tuning; a negative result is reported honestly |
| A45 | ONNX int8 keeps quality within 0.005 nDCG@10 of fp32 | Ship fp32 ONNX |
| A46 | Ollama 0.40.x runs the chosen ≤ 9B models with tool calling through its OpenAI-compatible API on the M1 | mlx-lm or llama.cpp server as the default `local` provider |
| A47 | Apache-2.0 models with tool calling exist at ≤ 9B (Gemma 4 E4B, Qwen3.5 4B/9B) | Current alternatives chosen at M6.0, licence checked |
| A48 | The calibrated P3b judge model is still available on OpenRouter | Recalibrate a replacement on the 50 labels (κ ≥ 0.6) before benchmarking |
| A49 | Cookies set by `api.kb.example.dev` with `SameSite=Strict` work for the SPA on `kb.example.dev` (same site) and survive the wake-up flow | Token-mediating backend (RFC 10017), or web and api on one host |
| A50 | GitHub artifact attestations stay free for public repositories | Keyless cosign signatures in GHCR |
| A51 | Trivy releases after the March 2026 incident are trustworthy when pinned by digest | Grype (Anchore) as the scanner |

**Still open (decided inside the milestones):** the local model list (M6.0), the winning loss variant (M6.2),
Lighthouse thresholds per page (M6.8), the options order after precondition checks (M6.0), the GraphRAG approach (O4).

---

## 5. Architecture (Phase 6)

**Model lifecycle (reranker)**

```
 corpus (stored originals, active chunks) ──► P3b query generator ──► filters + leakage guard (golden test, held-out docs)
                                                                          │
 hybrid retrieval (hard negatives) ──────────────────────────────────────► training set ◄── teacher scores
                                                                          │                (bge-reranker-v2-m3, MPS)
                                                                          ▼
                                            CrossEncoderTrainer (MPS) ──► runs, metrics, dataset hash ──► MLflow
                                                                                       registry kb-rerank
                                                                     @challenger ──► promotion gate ──► @champion
                                                                                                         │
                         models-build (CI) ◄──────────── alias resolved at build time ─────────────────┘
                           ├─ k3d:   models-rerank:<version>  (image volume)     + kb_model.json (threshold)
                           └─ cloud: Azure Files models/rerank/<version>          + attested manifest
                         deploy → post-deploy eval smoke → rollback = alias back to the previous version
```

**Local-vs-API benchmark**

```
 golden test (DE/EN) ── frozen retrieval outputs ──► provider abstraction (D40)
                                                      ├─ OpenRouter: cheap / strong tiers (D70)
                                                      ├─ Ollama 0.40 (MLX runner)  :11434/v1
                                                      └─ mlx-lm server             :8080/v1
 tool-calling suite · agent subset · red-team subset ─┘
 answers ──► calibrated judge (API) ──► quality · tool calls · TTFT · tokens/s · peak memory · cost ──► MLflow + README
```

**BFF (web only; MCP and headless clients keep bearer tokens)**

```
 browser ── cookie __Host-Http-kb-session + CSRF header ──► NestJS BFF ── app.web_sessions (encrypted tokens)
                                                             ├─ Keycloak: code flow (kb-web, confidential), refresh,
                                                             │            back-channel logout
                                                             └─ ai-service: token exchange as before (D36)
```

| Component | Change in Phase 6 |
|---|---|
| ai-service | Loads the reranker version and threshold from `kb_model.json`; `local-*` providers; `generatedBy` marker |
| api | BFF: login/callback/logout, session store, CSRF, back-channel logout; bearer auth kept for non-browser clients |
| web | No tokens; Signal Forms; dark mode; Lighthouse and axe budgets; AI disclosure (from P5) |
| New (local) | MLflow (`mlops` profile), training and benchmark tooling under `mlops/` |
| CI | `models-build`, `supply-chain`; verify step in the deploy workflows |

---

## 6. Repository layout (additions)

```
kb-agent/
├─ mlops/
│  ├─ datasets/rerank/               # builder (queries, negatives, teacher scores); manifests with hashes
│  ├─ train/rerank_ft.py · configs/  # CrossEncoderTrainer recipe, run configs (≤ 6)
│  ├─ export/onnx_int8.py
│  ├─ gate/promote.py · rollback.py  # promotion gate, alias moves
│  └─ bench/local_vs_api/            # suites, runners, report generator
├─ infra/compose/mlflow.yml          # Mode A profile `mlops`
├─ scripts/models/build-set.sh       # resolve aliases → model image (k3d) / Files sync (cloud) + manifest
├─ config/models.yaml                # + local-* entries
├─ config/gates.yaml                 # + rerank promotion gate
├─ apps/api/src/bff/                 # session, cookie, CSRF, back-channel logout
├─ docs/system-card.md · docs/model-cards/kb-rerank.md · docs/demo/script.md
└─ .github/workflows/{models-build,supply-chain}.yml   # + verify step in deploy-demo and e2e-aks
```

Training data and model files stay out of git (`.gitignore`); their hashes and MLflow run ids are committed.

---

## 7. Contracts (draft — code, schemas and MLflow metadata are authoritative)

### 7.1 Model metadata (`kb_model.json`, shipped in every model set)

```json
{
  "name": "kb-rerank", "version": "7", "mlflow_uri": "models:/kb-rerank/7",
  "base": "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1", "teacher": "BAAI/bge-reranker-v2-m3",
  "format": "onnx-int8", "max_length": 384, "score_activation": "sigmoid",
  "abstention_threshold": 0.31,
  "dataset": "rerank-ds-2027-11@sha256:…",
  "metrics": {"test": {"ndcg@10": 0.0, "hit@5": 0.0}, "test_unseen_docs": {"ndcg@10": 0.0},
              "p95_cpu_ms_k3d_lite": 0},
  "licence": "Apache-2.0",
  "files": {"model.onnx": "sha256:…", "tokenizer.json": "sha256:…"}
}
```

### 7.2 Training row (`mlops/datasets/rerank/*.jsonl`)

```json
{"query": "Wie rolle ich ein Helm-Release zurück?", "lang": "de",
 "positive": {"chunk_id": "…", "text": "…"},
 "negatives": [{"chunk_id": "…", "text": "…", "rank": 4}],
 "teacher": {"positive": 7.12, "negatives": [2.31, 1.87, 0.95, 0.40, -0.12, -0.80, -1.33]},
 "doc_id": "…", "split": "train", "generator": "p3b-gen@v3", "source_chunk_in_teacher_top10": true}
```

### 7.3 Run config (`mlops/train/configs/margin-mse-lr2e-5.yaml`)

```yaml
student: cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
loss: margin_mse              # or: bce_hard_negatives
device: mps
max_length: 384
batch_size: 16
epochs: 2
learning_rate: 2.0e-5
warmup_ratio: 0.1
eval: {set: golden_dev, metric: ndcg@10, every_steps: 500}
mlflow: {experiment: rerank-ft, register_as: kb-rerank, alias_on_finish: null}   # alias only via the gate
```

### 7.4 Promotion gate (`config/gates.yaml`, excerpt)

```yaml
kb-rerank:
  compare: {challenger: "@challenger", baseline: "@champion"}
  require:
    test.ndcg@10:            {min_delta: 0.02}
    test.ndcg@10.per_lang:   {max_drop: 0.01, langs: [de, en]}
    test_unseen_docs.ndcg@10: {min_delta: 0.0}
    abstention.f1:           {min_delta: 0.0, recalibrate_threshold: true}
    latency.p95_cpu_ms:      {max_ratio: 1.10, profile: k3d-lite}
    licence:                 {required: true}
  on_pass: {move_alias: champion, keep_previous: true}
```

### 7.5 `models.yaml` local entries (dev only)

```yaml
  - id: local-qwen3.5-9b-q4
    label: "Qwen3.5 9B (local, 4-bit)"
    base_url: ${OLLAMA_BASE_URL}            # http://localhost:11434/v1
    model: qwen3.5:9b                       # exact tag pinned at M6.0
    supportsTools: false                    # true only after the tool-calling threshold (D114)
    price_tier: local
    environments: [dev]
    roles: [editor, admin]
```

### 7.6 Benchmark report (one row per model × runtime × quantization)

| Column | Meaning |
|---|---|
| `model`, `runtime`, `quant` | e.g. `qwen3.5-9b`, `ollama-mlx`, `4bit` |
| `faithfulness`, `relevance`, `citation_acc` | judged on frozen contexts, golden `test` |
| `refusal_correct` | unanswerable items declined, answerable ones answered |
| `tool_call_valid`, `tool_call_acc` | well-formed calls; correct tool + arguments |
| `agent_success` | agent subset, Mode A |
| `redteam_pass` | injection subset, forbidden tools never called |
| `ttft_p50_ms`, `tok_s_p50`, `peak_mem_gb` | measured on the M1, same prompt set |
| `usd_per_answer` | API price; local = 0 marginal (energy noted) |

### 7.7 BFF endpoints (NestJS)

| Route | Purpose |
|---|---|
| `GET /auth/login` | starts the code flow (PKCE, `state`, `nonce`); returns to `redirect` (allow-listed) |
| `GET /auth/callback` | exchanges the code, stores tokens in `app.web_sessions`, sets `__Host-Http-kb-session` |
| `POST /auth/logout` | ends the session, RP-initiated logout at Keycloak |
| `GET /auth/session` | user info and roles for the SPA (no tokens) |
| `POST /auth/backchannel-logout` | Keycloak logout token → session revoked |
| every other `/api/*` | cookie session + required header `X-KB-CSRF: 1`; or `Authorization: Bearer` for non-browser clients |

### 7.8 System card v1 (outline of `docs/system-card.md`)

1. Purpose, intended users, out-of-scope uses
2. System overview (diagram) and deployments (local, k3d, Container Apps, AKS e2e)
3. Models: API tiers, local models, embeddings, reranker (version, licence, model card link), guardrail models
4. Data: corpus sources and licences, curation levels in use (L0–L3), provenance, PII handling, what goes to OpenRouter,
   retention (incl. guest data)
5. Evaluation: retrieval, generation (judge, κ), agent, red-team results, local-vs-API, reranker gate history
6. Safety and limits: guardrails, ACL, tool permissions and approvals, demo limits and caps, egress difference ACA/AKS
7. Transparency: AI disclosure, machine-readable marker, how answers cite sources
8. Known limitations and failure modes; how to report a bad source or answer
9. Changelog

### 7.9 Environment changes

| Variable | Service | Value |
|---|---|---|
| `RERANK_MODEL_DIR` | ai-service | `/models/rerank/<version>` (contains `kb_model.json`) |
| `MLFLOW_TRACKING_URI` | mlops tooling (local only) | `http://localhost:5000` |
| `OLLAMA_BASE_URL`, `MLX_BASE_URL` | ai-service (dev) | `http://localhost:11434/v1`, `http://localhost:8080/v1` |
| `BFF_SESSION_KEY` (new, secret) | api | encryption key for stored tokens (Key Vault `bff-session-key` in the cloud) |
| `KEYCLOAK_WEB_CLIENT_ID`, `KEYCLOAK_WEB_CLIENT_SECRET` (new) | api | confidential client `kb-web` |
| `SESSION_IDLE_MIN`, `SESSION_MAX_H` (new) | api | `30`, `8` |
| SPA OIDC settings | web | **removed** (no tokens in the browser) |

---

## 8. Milestones and tasks

Order: M6.0 → M6.1 → … → M6.9; supply chain (M6.4) comes before the local-model work so the rollout already ships
attested model sets. Hours are ideal single-person hours, ±30 %.

### M6.0 — Kick-off (~2 h)

- [ ] Record Phase 5 deviations; options gate (D120) incl. the precondition checks for O1 and O4
- [ ] Pin MLflow 3.17.x, sentence-transformers 6.x, ONNX Runtime/Optimum, Ollama 0.40.x, mlx-lm 0.32.x; current Angular
  major (`ng update` plan); re-check the local model list (licence, tool calling, size)
- [ ] Memory plan for the M1: what runs during training, teacher scoring and benchmarking (D108)
- [ ] **Spike (≤ 30 min):** BFF session cookie from `api.kb.example.dev` with SSE and the wake-up flow on the cloud
  hosts (A49)

**Acceptance:** versions pinned; options decision and order recorded; local model shortlist with licences.

### M6.1 — MLflow & model metadata (~5 h)

- [ ] Compose profile `mlops` (MLflow server, `mlflow` database, artifact volume); `pnpm mlops:up/down`
- [ ] Experiment layout; registry model `kb-rerank`; aliases `champion` (= current base student) and `challenger`
- [ ] Baseline runs: base student and teacher on golden `dev`/`test` (nDCG@10, hit@5, per language, abstention F1,
  CPU latency), logged with dataset and code versions
- [ ] `kb_model.json` contract (§7.1); AI service reads version and threshold from it; `models-build` skeleton resolves
  an alias
- [ ] ADR-0049

**Acceptance:** demo step 1 (with baselines only); the AI service starts from a model set built from `@champion`.

### M6.2 — Reranker distillation (~14 h)

- [ ] Training-data builder: ~4k synthetic queries (P3b generator), filters, leakage guard, held-out documents, hard
  negatives from hybrid retrieval, false-negative filter, teacher scores on MPS; dataset manifest + MLflow logging
- [ ] Training script (`CrossEncoderTrainer`, MPS); variants (a) MarginMSE and (b) BCE with hard negatives; ≤ 6 runs;
  selection on `dev`
- [ ] Selected run evaluated once on `test` (seen / unseen documents); ONNX int8 export; quality check vs. fp32; CPU
  latency in the `k3d-lite` container and on Container Apps
- [ ] Model card `docs/model-cards/kb-rerank.md`; registered as `@challenger`
- [ ] ADR-0050

**Acceptance:** results table (base student, teacher, variant a, variant b; test seen/unseen; latency); gap closed is
reported whatever the outcome.

### M6.3 — Promotion gate, rollout, rollback (~5 h)

- [ ] `mlops/gate/promote.py` with `config/gates.yaml`; threshold recalibration on the unanswerable items; gate report
  (Markdown + MLflow)
- [ ] `models-build` workflow: alias → model image (k3d registry) + Azure Files version directory + manifest; config
  update; deploy to `k3d-lite` and the cloud demo; post-deploy eval smoke
- [ ] Rollback script and drill (timed); old versions retained (last 3)
- [ ] ADR-0051

**Acceptance:** demo steps 2–4; a challenger that fails one criterion is blocked (test with a deliberately weak run).

### M6.4 — Supply chain (~4 h)

- [ ] `supply-chain` workflow: SBOM (Syft, SPDX JSON) + provenance and SBOM attestations (`actions/attest@v4`) per
  image; Trivy scan pinned by digest in an isolated job; expiring ignores
- [ ] `gh attestation verify` in `deploy-demo` and `e2e-aks` before any digest is deployed
- [ ] Model-set manifest attested in `models-build`; README section "Verify our images"
- [ ] ADR-0053

**Acceptance:** demo step 9.

### M6.5 — Local models on the M1 (~7 h)

- [ ] Ollama 0.40.x and mlx-lm 0.32.x installed and pinned; 2–3 models from the shortlist × 4-bit (+ 8-bit ≤ ~4B)
- [ ] Measurement harness: TTFT, tokens/s, peak memory (same prompts, stack stopped)
- [ ] `local-*` entries in `models.yaml`; tool-calling suite run → `supportsTools` per model; UI switch in dev
- [ ] ADR-0052 (part 1: runtimes and models)

**Acceptance:** demo step 6; memory and speed numbers for every candidate.

### M6.6 — Local-vs-API benchmark (~8 h)

- [ ] Frozen retrieval outputs for golden `test` exported; answer suite with the calibrated judge
- [ ] Tool-calling suite, agent subset (Mode A), red-team subset; cost per answer for the API tiers
- [ ] Report generator → table + chart in the README and the system card; decision note "where local is good enough"
- [ ] ADR-0052 (part 2: benchmark design and results)

**Acceptance:** demo step 5; every number reproducible with `pnpm bench:local --model …`.

### M6.7 — System card v1 & transparency (~4 h)

- [ ] `docs/system-card.md` (§7.8) with generated tables (`pnpm docs:system-card`)
- [ ] `generatedBy` marker in the message API and `X-AI-Generated` on answer responses; disclosure check in the UI
- [ ] Bad-source and bad-answer reporting path (feedback → review queue, P3b)

**Acceptance:** demo step 10; the card's tables regenerate from the current eval results without manual edits.

### M6.8 — Web polish & BFF (~10 h)

- [ ] **BFF (~5 h):** client `kb-web` (confidential), routes (§7.7), `app.web_sessions` with encrypted tokens, cookie
  attributes, CSRF header, timeouts, back-channel logout; SPA without tokens; SSE and the wake-up flow tested; old SPA
  client removed; ADR-0054
- [ ] **Angular (~2 h):** major upgrade; forms migrated to Signal Forms
- [ ] **Dark mode (~1 h):** Material 3 tokens, system default + toggle
- [ ] **Budgets (~2 h):** Lighthouse CI on landing and chat, axe in Playwright, merge-blocking for `apps/web`

**Acceptance:** demo steps 7–8.

### M6.9 — Demo video, README, v1.0 (~4 h)

- [ ] Demo script (`docs/demo/script.md`), 3-minute recording against the public URL (guest + reviewer flows, one
  trace, the eval tables)
- [ ] Final README: architecture, live demo, eval and benchmark tables, cost table, ADR index, how to run locally
- [ ] `v1.0.0` release with changelog; roadmap marked done; L4 go/no-go date set

**Acceptance:** demo step 11; a stranger can follow the README from clone to local demo.

### Add-on — when a new Mac arrives (~3 h, not in the totals)

- [ ] Re-run M6.5/M6.6 with larger models (20–30B at 4-bit, e.g. MoE variants), same suites; table extended; ADR-0052
  updated

### Options (gated by D120; run after the core exit demo, in this order)

| Option | Precondition | Content | Adopt-or-document rule | h |
|---|---|---|---|---|
| **O1 Multimodal ingestion** | ≥ 15 documents whose key content is in diagrams | Docling picture classification + picture description through an API vision model (`PictureDescriptionApiOptions`, remote services enabled only in ingest jobs), captions cached per image hash (like D60), indexed as `figure` chunks under their section, image linked in citations; Mermaid/PlantUML sources indexed as text; eval set `figure_v1` (~15 items) | Keep if `figure_v1` hit@5 +≥ 0.2 without golden `test` regression; else document | 8 |
| **O2 Multi-agent experiment** | — | Specialists (e.g. devops, security, curator) as sub-agents called by a supervisor through the existing tool registry, same permissions and approvals; vs. one agent + skills on `agent_v2` | Adopt only if task success +≥ 5 pp at ≤ 1.3× cost and latency; else a documented negative result | 10 |
| **O3 Framework comparison** | — | The agent loop re-implemented with one framework (default Pydantic AI 2.x: MIT, MCP, deferred tools for approvals; chosen at the gate) using the same MCP tools and prompts; `agent_v2` + red-team subset; compare success, cost, latency, code size, tracing, approval support | Report only; the own harness stays unless the framework wins on success and approvals | 8 |
| **O4 GraphRAG** | ≥ 30 % failures on the multi-hop items of `test` | Light graph in Postgres: deterministic edges first (imports from the code index, chart dependencies, ADR links), LLM-extracted relations for ADR prose (cached); tool `graph_neighbors` / `graph_path` for the agent; compared with LazyGraphRAG/LightRAG-style libraries on cost | Keep if multi-hop success +≥ 15 pp without golden `test` regression; else document | 12 |

Each option writes an ADR (ADR-0055 onward, numbered when done).

---

## 9. Schedule (8–10 h/week, 9 h used)

| Week | Focus |
|---|---|
| 1 | M6.0 kick-off, M6.1 MLflow + baselines, start M6.2 data builder |
| 2 | M6.2 data, teacher scores, first runs |
| 3 | M6.2 selection, export, model card; M6.3 gate + rollout |
| 4 | M6.3 rollback drill; M6.4 supply chain; start M6.5 |
| 5 | M6.5 local models; M6.6 benchmark |
| 6 | M6.6 report; M6.7 system card; start M6.8 BFF |
| 7 | M6.8 BFF + polish; M6.9 video, README, v1.0 → exit demo |
| — | **1 buffer week** (holidays) |
| 8–12 | Options O1 → O4, only if the gate passed (~38 h) |

**Cut line** (drop in this order): options (all) → mlx-lm comparison runtime (Ollama only) → 8-bit variants → third
local model → variant (b) of the loss comparison → Lighthouse budget on the chat page (landing only) → dark-mode
toggle (system setting only) → model-set attestation (images only) → back-channel logout (front-channel only) → video
length 3 → 1.5 min.
**Never cut:** leakage guard and the test-once rule, promotion gate with threshold recalibration, rollback drill, MLflow
registry with aliases, frozen-retrieval benchmark with the calibrated judge, system card v1 incl. AI disclosure and
marker, SBOM + attestations + verify-before-deploy, BFF without tokens in the browser, `v1.0.0`.

---

## 10. Definition of Done (Phase 6)

- [ ] Demo script (§1) passes on the M1 and against the public demo
- [ ] Distilled reranker evaluated on `test` (seen/unseen) and either promoted through the gate or documented as a
  negative result; rollback drill timed
- [ ] MLflow holds every run with dataset hash, code version and metrics; registry aliases drive the model sets
- [ ] Local-vs-API table published and reproducible; `local-*` models selectable in dev
- [ ] System card v1 with generated tables; AI disclosure and machine-readable marker in place
- [ ] Every deployed image and model set attested and verified before deploy; scan job isolated
- [ ] Web app holds no tokens; Signal Forms, dark mode, Lighthouse and axe budgets green
- [ ] Demo video, final README, `v1.0.0` release
- [ ] ADR-0049 … 0054 written; options ADRs for every option done or skipped by precondition

---

## 11. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Distillation gains are small (teacher–student gap too narrow, or synthetic queries unlike real ones) | Medium | Gap measured in M6.1 first; unseen-document split; real gap and thumbs-down questions (P3b) as an extra check; negative result is a valid outcome |
| Leakage inflates results | Medium | Golden questions and near-duplicates excluded, held-out documents, `test` evaluated once |
| MPS training slow or unstable on the M1 | Medium | Small model, ≤ 6 runs, fp32; CPU overnight or one free GPU notebook session |
| New threshold changes abstention behaviour in production | Medium | Recalibration is part of the gate; threshold travels in `kb_model.json`; post-deploy eval smoke |
| Local models too weak or too slow on 16 GB | High | Expected and reported as a result; frozen contexts keep the comparison fair; new-Mac add-on |
| Judge drift or judge model retired | Low–Medium | Same calibration labels; κ check before benchmarking |
| BFF breaks SSE, the wake-up flow or cross-origin cookies | Medium | A49 spike in M6.0; token-mediating backend as fallback; Playwright flow tests in the cloud |
| Angular major upgrade breaks forms or Material | Medium | Upgrade first in M6.8, behind the Playwright suite |
| Supply-chain tooling itself compromised | Low–Medium | Pinned by digest/SHA, isolated scan job, no secrets in workflows (P5) |
| Options eat the end of the project | Medium | Gate, preconditions, fixed order, each option can be cut alone |
| Video and README polish take longer than planned | Medium | Demo script written first; one take per section; 1.5-min fallback |

---

## 12. After Phase 6

- **L4 go/no-go** (roadmap §12) on the date set in M6.9
- **New-Mac add-on** (§8) whenever the hardware arrives
- **Maintenance rhythm:** monthly cost review and dependency updates (Dependabot), quarterly full eval and red-team run,
  AKS minor bumps, Angular majors twice a year, model-list review for the API tiers
- **Possible next model:** fine-tune the embedding model with the same pipeline (GPU session + re-index + Qdrant alias
  swap behind the eval gate)

---

## 13. Study-list coverage in Phase 6

| # | Topic | Where in Phase 6 |
|---|---|---|
| 5 | Embedding / model selection & benchmarking | D114, D115 local model and runtime benchmark |
| 13 | Provider abstraction | D114 `local-*` providers behind the same interface |
| 17, 43 | Retrieval evaluation, eval as gate | D113 promotion gate on golden `test` incl. unseen documents |
| 22 | Reranking | D110–D112 distilled CPU reranker |
| 40, 41 | Generation eval, LLM-as-judge | D115 calibrated judge on frozen contexts |
| 42 | Agent evaluation | D115 agent and tool-calling suites for local models |
| 44 | Synthetic data | D111 synthetic queries + mined hard negatives as training data |
| 55 | Embedding & reranker fine-tuning | M6.2 |
| 56 | MLOps (tracking, registry, rollout) | D109, D113, M6.3 |
| 57 | Local inference & quantization | D114 Ollama (MLX) vs. mlx-lm, 4-bit vs. 8-bit |
| 58 | Local vs. API benchmarking | M6.6 |
| 59 | System card | D116 |
| 19 | Data privacy | D116 data flows; local inference keeps prompts on the device |
| 52, 53, 54 | Multi-agent, GraphRAG, multimodal | Options O2, O4, O1 |

---

## Appendix A — Environment (additions)

```dotenv
# --- mlops (local only) ---
MLFLOW_TRACKING_URI=http://localhost:5000
MLFLOW_BACKEND_STORE_URI=postgresql://mlflow:…@localhost:5432/mlflow
MLFLOW_ARTIFACTS_DIR=./.mlflow
PYTORCH_ENABLE_MPS_FALLBACK=1

# --- ai-service ---
RERANK_MODEL_DIR=/models/rerank/7
OLLAMA_BASE_URL=http://localhost:11434/v1
MLX_BASE_URL=http://localhost:8080/v1

# --- api (BFF) ---
KEYCLOAK_WEB_CLIENT_ID=kb-web
KEYCLOAK_WEB_CLIENT_SECRET=…
BFF_SESSION_KEY=…                          # 32 random bytes, base64
SESSION_IDLE_MIN=30
SESSION_MAX_H=8
```

## Appendix B — Command cheat sheet (additions)

```bash
pnpm mlops:up | mlops:down                   # MLflow (Compose profile mlops)
pnpm mlops:data -- --queries 4000            # build the distillation dataset (+ teacher scores on MPS)
pnpm mlops:train -- configs/margin-mse-lr2e-5.yaml
pnpm mlops:export -- --run <run-id>          # ONNX int8 + model card
pnpm mlops:gate kb-rerank                    # promotion gate → alias move on pass
pnpm mlops:rollback kb-rerank                # alias back to the previous version
gh workflow run models-build.yml -f model=kb-rerank
pnpm bench:local -- --model local-qwen3.5-9b-q4 --suite all
pnpm docs:system-card                        # regenerate the system card tables
gh attestation verify oci://ghcr.io/<owner>/kb-agent-ai@sha256:… -R <owner>/kb-agent
ollama ps                                    # RUNNER column shows mlx or llamacpp
```

## Sources checked (2026-10-24)

- MLflow on PyPI (3.17.2, 2026-10-21) — https://pypi.org/project/mlflow/ · model registry and aliases: https://mlflow.org/docs/latest/ml/model-registry/
- sentence-transformers on PyPI (6.2.0, 2026-10-21) — https://pypi.org/project/sentence-transformers/ · migration guide (v6): https://www.sbert.net/docs/migration_guide.html · cross-encoder distillation examples: https://sbert.net/examples/cross_encoder/training/distillation/
- `mmarco-mMiniLMv2-L12-H384-v1` (Apache-2.0, multilingual) — https://www.promptlayer.com/models/cross-encoder-mmarco-mminilmv2-l12-h384-v1
- Ollama releases (0.40.11) — https://github.com/ollama/ollama/releases · MLX in Ollama (preview, March 2026): https://registry.ollama.ai/blog/mlx · MLX by default in 0.40: https://jacar.es/?p=7672
- mlx-lm (0.32.2) — https://www.developersdigest.tech/local-models/runtimes/mlx-lm
- Gemma 4 (Apache-2.0, sizes) — https://en.wikipedia.org/wiki/Gemma_(language_model) · Qwen3.5 sizes and licence: https://www.verdent.ai/guides/model/qwen-3-5 · local tool-calling tests: https://www.promptquorum.com/power-local-llm/best-local-models-tool-calling-2026
- MacBook Pro M5 Pro / M5 Max memory options — https://www.macworld.com/article/2942089/macbook-pro-m5-pro-max-release-specs-price.html
- Free GPU options 2026 (Kaggle, Colab, Modal) — https://gpuperhour.com/blog/free-cloud-gpus-and-credits
- RFC 10017, OAuth 2.0 for Browser-Based Applications (BCP 212, August 2026) — https://www.rfc-editor.org/rfc/rfc10017.html
- EU AI Act Art. 50 transparency obligations — https://labs.cloudsecurityalliance.org/research/csa-research-note-eu-ai-act-article-50-transparency-20260729/
- GitHub artifact attestations (`actions/attest@v4`, SBOM, verification) — https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations
- Trivy compromise, March 2026 — https://www.wiz.io/de-de/blog/trivy-compromised-teampcp-supply-chain-attack
- Angular v22 (Signal Forms production-ready) — https://blog.angular.dev/announcing-angular-v22-c52bb83a4664
- Docling enrichments (picture description via API) — https://docling-project.github.io/docling/usage/enrichments/
- Pydantic AI (2.x, MCP, human-in-the-loop) — https://www.developersdigest.tech/agent-frameworks/pydantic-ai
- LazyGraphRAG — https://www.microsoft.com/en-us/research/blog/lazygraphrag/
