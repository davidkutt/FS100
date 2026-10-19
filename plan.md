# plan.md — Phase 1: Foundation, RAG Vertical Slice, Eval & Tracing

> **Project (working title):** `kb-agent` — an assistant for the **"Dev of the future"**: an engineer fluent across
> DB · Dev · Cloud · DevOps · MLOps · AI integration · Security · Architecture · SRE.
> Phase 1 starts with a **platform/DevOps** corpus; the other domains follow as tools, skills and corpora in later phases.
> **Document scope:** Phase 1 of 6 · **Status:** Draft v2 · **Updated:** 2026-10-19
> **Estimated effort:** ~76 h (range 60–90 h) · ~9 weeks at 8–10 h/week

### Changelog v1 → v2

| Change | Reason |
|---|---|
| **LLM, retrieval and (later) agent layer live in Python**; NestJS is the product API and relays the stream | Decision A — evals, tracing and retrieval tuning sit next to the harness; Python-first AI tooling |
| Domain = "Dev of the future" assistant; **domain tags** on every document and eval question | Decision B — prepares routing, per-domain evals and domain tools |
| **LLM via OpenRouter** (OpenAI-compatible); Hugging Face router as alternative; **Ollama/local models moved to Phase 6** | Decision C — MacBook M1, upgrade pending; user-funded tokens |
| One `openai_compat` adapter + `fake`; native Anthropic adapter dropped | OpenRouter, HF, Ollama, vLLM and LM Studio all speak the OpenAI API |
| **Retrieval eval harness** and **LLM tracing (Phoenix)** pulled into Phase 1 | Highest-value AI skills; needed to debug RAG from day one |
| Drizzle instead of Prisma; `bge-m3` added to the embedding benchmark | ESM-native, no codegen; hybrid-search path for Phase 3 |
| Retrieval inspector promoted to core; dark mode, Signal Forms, Lighthouse, Trivy pushed to Phase 6 | Pay for the AI additions with polish |
| Azure readiness spike is **mandatory** and scheduled in week 2 | Quota requests can take days; de-risks Phase 5 |
| Multi-arch images (arm64 + amd64) | Apple Silicon locally, amd64 nodes on AKS |
| New §13 **AI technology map** and Phase 2 domain-tool preview | Decision D — check of the advanced-AI coverage |

---

## 0. Roadmap context

| Phase | Theme | Result |
|---|---|---|
| **1 (this doc)** | Foundation + RAG slice + **eval + tracing** | Login → upload → ask → streamed, cited answers; retrieval metrics per run; traces in Phoenix. Local via Compose, CI green. |
| 2 | Agent | Python agent loop from scratch, agentic RAG, MCP server **and** client, first domain tools (DevOps, Cloud/SRE read-only, Architecture), human-in-the-loop, conversations, **agent eval** basics, prompt versioning |
| 3 | Quality, safety, cost *(largest — may split 3a/3b)* | Hybrid search + reranking + query rewriting + contextual retrieval, **code-aware RAG**, skills, ACL-filtered retrieval, LLM-judge eval gate, **guardrails**, **model routing + semantic cache**, long-term memory |
| 4 | Kubernetes | Helm chart, k3d locally, GitOps-ready manifests |
| 5 | Azure | Terraform, ACR, AKS (ephemeral) / Container Apps, Key Vault, budgets, OIDC from GitHub |
| 6 | **MLOps & local models** + polish | Embedding/reranker fine-tuning with MLflow + alias-based rollout, Ollama/MLX on the new Mac + local-vs-API benchmark, optional experiments, system card, demo video |

---

## 1. Goal and demo script

**Goal.** By the end of Phase 1 a signed-in user can upload documents tagged by domain, ask questions about them and
receive **streamed answers with citations**. Every change to retrieval is **measured** by an eval run, and every
request is **traceable** (retrieval → prompt → model). Runs fully locally with one command; CI green; README good
enough for a portfolio. **No agent loop, tools or MCP yet** (Phase 2).

**Acceptance demo:**

1. `pnpm stack:up` → infra healthy (Postgres, Qdrant, Keycloak, Phoenix); `pnpm dev` → apps running.
2. Open `http://localhost:4200` → Keycloak login as `bob` (editor).
3. Upload `data/sample-docs/` with domain tags → status `pending → processing → ready`.
4. Ask a question → answer streams in via OpenRouter with `[1] [2]` citations → clicking a citation shows chunk, document, page.
5. Open the **retrieval inspector**: same query, raw hits with scores, domain filter.
6. Open **Phoenix** (`http://localhost:6006`): the request's trace shows embed → search → LLM spans with prompt, tokens and latency.
7. `pnpm eval:retrieval` → table with hit@k / MRR / nDCG overall and per domain; results saved under `evals/runs/`.
8. Log in as `carol` (viewer): chat works, no upload controls; `POST /api/documents` with her token → **403**.
9. Push to `main` → CI: lint, tests, contract check, retrieval eval (report only), multi-arch images, e2e smoke → green.
10. A stranger reaches steps 1–7 from the README alone (with their own OpenRouter key, or `LLM_PROVIDER=fake`).

---

## 2. Scope

**In scope**
- Monorepo: Angular (web), NestJS (api), FastAPI (ai-service) + local infra
- Keycloak realm with roles, clients and seed users; JWT validation in both backends; RBAC
- Ingestion: PDF / Markdown / TXT → parse → chunk → embed → Qdrant, with **domain tags**
- Retrieval endpoint and **grounded chat in the AI service** (SSE), relayed by NestJS
- LLM provider interface in Python: `openai_compat` (OpenRouter default, HF alternative) + `fake`
- **Retrieval eval harness** with a golden dataset, metrics, CLI and CI report
- **LLM tracing** with OpenTelemetry/OpenInference → Phoenix
- Angular UI: documents, chat with citations, **retrieval inspector** (Bootstrap 5 + SCSS)
- Dockerfiles (multi-arch), Compose (dev + full profile), GitHub Actions, README + ADRs
- **Azure readiness spike** (budget, quota, ACR)

**Out of scope (deferred, with target phase)**
- Agent loop, tools, MCP, skills, conversation persistence → **2 / 3**
- Hybrid search, reranking, query rewriting, contextual retrieval, code-aware RAG, Docling → **3**
- Generation/agent evals with LLM-as-judge, guardrails, routing, semantic cache → **2 / 3**
- Per-document ACL filtering (data model prepared now) → **3**
- Kubernetes, Helm, Terraform, deployment to Azure → **4 / 5**
- **Local models (Ollama/MLX)**, fine-tuning, dark mode, Signal Forms, Lighthouse, Trivy → **6**

---

## 3. Decisions

Status: **L** = locked · **C** = changed in v2 · **N** = new in v2. ADR numbers where an ADR is written.

| # | St. | Topic | Decision | Why / alternatives |
|---|---|---|---|---|
| D1 | L | Repo & tooling | **Monorepo.** **pnpm** workspaces for `apps/web` + `apps/api`, pinned via `packageManager`; `onlyBuiltDependencies` allow-list (pnpm 10 blocks dependency install scripts by default, e.g. `esbuild`); **catalogs** for shared versions. **uv** for the AI service. Root `package.json` scripts as task entry points. (ADR-0001) | pnpm: strict `node_modules` (no phantom deps between apps), `--filter`, `pnpm deploy` for slim Docker images, fast cached installs. npm works but is looser and slower; Yarn PnP adds tooling friction; Bun is a runtime bet unrelated to the learning goals. No Nx/Turbo for two Node apps. |
| D2 | L | Versions (pin exact at M1.0) | Node 24 LTS (revisit Node 26 after it enters LTS on 28 Oct 2026) · Angular 22 · NestJS 12 · Python 3.13 · Keycloak 26.7.x · Qdrant 1.18.x + `qdrant-client` 1.18 · Postgres 17 · Bootstrap 5.3 | Current stable lines. Angular 22 / Nest 12 are new → compatibility spikes in M1.0. Dependabot keeps pins fresh. |
| D3 | **C** | Service split | **NestJS = product API / BFF**: auth, RBAC, document metadata, (P2: conversations, audit, quotas), stream relay. **Python AI service = all AI**: parsing, chunking, embeddings, retrieval, prompting, LLM calls, eval, tracing; in P2 the agent loop, tools and MCP client. Only NestJS is browser-facing. (ADR-0002) | AI code, evals and traces in one language and process; retrieval tuning without a network hop. NestJS keeps a real job: the product domain and the security boundary — a common enterprise pattern. |
| D4 | L | AuthN | Angular: Authorization Code + **PKCE**, public client `kb-web` via `keycloak-js` (+ `keycloak-angular` if compatible). NestJS validates JWT via JWKS (`jose`): `iss`, `aud=kb-api`, `exp`, signature. | Standard; a small own guard is easier to explain and test than a wrapper library. BFF-cookie pattern is a possible Phase 6 hardening. |
| D5 | **C** | Service-to-service auth | Phase 1: NestJS → AI service with a **client-credentials** token (`kb-api`, audience `kb-ai`) plus a `user` context object (`sub`, `roles`, later `groups`). **Phase 2/3: Keycloak token exchange** so the AI layer and MCP tools act *on behalf of the user*. | Defense in depth now; on-behalf-of delegation is the right model once tools touch real systems. |
| D6 | L | RBAC | Realm roles `viewer` < `editor` < `admin` (composites). viewer: chat + search. editor: + upload, delete own docs. admin: + delete any, status page. Docs org-wide visible in P1. | Simple matrix; per-document ACL in P3 (fields exist from day one). |
| D7 | L | Ingestion flow | Nest: multipart (≤20 MB, allow-list PDF/MD/TXT, magic-byte check), SHA-256 dedupe (409), row `pending`, **202**. Background task streams file + metadata (incl. `domains`) to `POST /v1/ingest`; row → `ready`/`failed`. Originals not stored in P1. Boot-time recovery for stuck rows. | Smallest working thing; queue in P3. |
| D8 | L | Parsing & chunking | `pypdf` (page-aware), plain read for MD/TXT; recursive splitter ~1000 chars / 150 overlap, heading-aware for Markdown; behind `Parser` / `Chunker` interfaces. **Not PyMuPDF** (AGPL vs. MIT repo). | Lightweight; Docling and code-aware (tree-sitter) chunkers are P3 drop-ins. |
| D9 | **C** | Embeddings | In-process **fastembed** (ONNX, CPU). Benchmark candidates: `multilingual-e5-small`, `-base`, `-large`, **`bge-m3`** (dense + sparse from one model; large and slow on CPU). Default `e5-base` until the benchmark decides → **ADR-0004: `bge-m3`**, 1000/150, threshold 0.55. E5 `query: ` / `passage: ` prefixes enforced + tested. (ADR-0004) | No token cost; identical locally and in the cloud; DE + EN corpus. bge-m3 is the natural path to hybrid search. |
| D10 | L | Qdrant model | Collection `kb__{model_slug}__{dim}` + alias **`kb_current`**; named dense vector `dense`, cosine; payload indexes `doc_id`, `owner_id`, **`domains`**; point ID = UUIDv5(`doc_id:chunk_index`); payload carries `visibility`, `allowed_groups` (P3). | Alias = zero-downtime model swaps and later A/B rollout (P6 MLOps). |
| D11 | **C** | LLM access | In **Python**: `LlmProvider` protocol `stream_chat(messages, opts) → AsyncIterator[LlmEvent]`. Implementations: **`openai_compat`** (raw `openai` SDK with `base_url`; **OpenRouter** default, **HF router** alternative, Ollama/MLX/vLLM in P6) and **`fake`** (deterministic, CI). Model id only in env. No agent framework through Phase 2. (ADR-0005) | One adapter covers every target; writing against the raw SDK teaches what frameworks hide. A native vendor adapter is added only if a needed feature isn't reachable via OpenRouter. |
| D12 | **C** | Chat protocol | Browser `POST /api/chat` (Nest: auth, RBAC, throttle) → Nest calls `POST /v1/chat` on the AI service (SSE) → Nest **relays events unchanged** → browser (fetch streaming; EventSource can't POST or send headers). Events: `sources`, `token`, `done`, `error`. Stateless; client sends last N messages. **Abort propagates on both hops** (browser → Nest → AI service → LLM). | Retrieval + prompt + LLM stay together in Python; P2 adds `tool_call` / `tool_result` without a protocol change. |
| D13 | L | Validation | NestJS: **Zod** via Nest 12's Standard Schema support (fallback `class-validator`); Python: Pydantic v2. | One schema language per runtime. |
| D14 | **C** | Contracts | OpenAPI-first: FastAPI → types for Nest; Nest (`@nestjs/swagger`) → types for Angular. **SSE event schemas** are exported from the Pydantic models as JSON Schema into `packages/contracts` (OpenAPI describes SSE poorly). Generated files committed; CI fails on drift. | Breaking changes caught at PR time across three apps. |
| D15 | **C** | App DB | Postgres 17, databases `keycloak` + `app` in one instance; **Drizzle ORM** + drizzle-kit migrations. | ESM-native (Nest 12), schema in TS, readable SQL migrations, no codegen step. |
| D16 | **C** | Frontend | Angular 22, standalone components, signals, feature folders; Bootstrap 5.3 via SCSS with variable overrides, no jQuery. **Sanitized** Markdown rendering. Dark mode and Signal Forms → P6. | Matches the stack; polish later. |
| D17 | L | Runtime config | Angular loads `/config.json` before bootstrap; nginx renders it from env (`envsubst`). | One image for local, k3d and Azure. |
| D18 | **C** | Dev workflow | **Mode A (daily):** infra in Compose (Postgres, Qdrant, Keycloak, Phoenix), apps native with hot reload. **Mode B (`--profile full`):** all containerized for demos, e2e and image tests. **No local LLM in Phase 1.** Apple Silicon → arm64 images locally. | M1 RAM is limited; hot reload is fastest natively. |
| D19 | **C** | CI/CD | GitHub Actions: per-app jobs (path filters, caching), contract-drift check, **retrieval eval job (report only)**, buildx **multi-arch** images (`linux/amd64,linux/arm64` on `main`; amd64 only on PRs) → GHCR; e2e smoke; Dependabot. Trunk-based, Conventional Commits. | amd64 for AKS, arm64 for the Mac; ACR in Phase 5. |
| D20 | L | Testing | pytest (+ in-process Qdrant via `qdrant-client` `:memory:` — same client API, no Docker; testcontainers if server-only features are needed); Nest: Vitest + supertest; Angular: CLI default runner; one Playwright smoke (login → upload → ask) with `LLM_PROVIDER=fake`. **No paid LLM calls in CI.** | Deterministic and free. |
| D21 | **C** | Observability | JSON logs, `x-request-id` browser → Nest → AI service, `/healthz` + `/readyz`. **LLM tracing** in the AI service: OpenTelemetry + OpenInference instrumentation (`openai` SDK) + manual spans for embed/search/prompt → **Arize Phoenix** container. Usage (tokens, cost if returned) logged per request. | Single-container, OTel-native; self-hosted Langfuse v3 needs ClickHouse, Redis and object storage — optional later. |
| D22 | **C** | Domain & corpus | Taxonomy: `db`, `dev`, `cloud`, `devops`, `mlops`, `ai`, `security`, `architecture`, `sre`. Phase 1 corpus is platform/DevOps-heavy: **the repo's own docs + ADRs**, **runbooks you write yourself**, and open-licensed excerpts of upstream docs (Kubernetes, Keycloak, Qdrant, GitHub Actions …) plus 1–2 German docs. **Check every license**, keep `ATTRIBUTION.md`. | Meta-demo: the assistant explains its own stack. Self-written runbooks are licence-safe and authentic portfolio content. |
| D23 | **N** | Evaluation from day one | Golden set `evals/datasets/retrieval_v1.jsonl` (40–60 items: question, expected doc + heading/page, domain, language, `answerable`). Metrics: hit@1/5, MRR@10, nDCG@10, latency p50/p95 — overall + per domain + per language. Unanswerable items calibrate `score_threshold`. Results as JSON under `evals/runs/` (git-ignored) + summary in the CI job. Dataset versioned. | Measurement before optimization — the base for every Phase 3 technique. |
| D24 | **N** | Token cost guard | Dedicated OpenRouter key **with a per-key credit limit**; `LLM_MAX_OUTPUT_TOKENS` cap; per-user throttle in Nest; cheap model for development, stronger model only for demos; `fake` provider in CI. | You pay the tokens; caps make mistakes cheap. |
| D25 | **N** | Data & privacy | Only public or self-written documents in the corpus — OpenRouter forwards prompts (incl. retrieved chunks) to third-party providers. Check provider data policies before adding anything private. | Portfolio-safe by construction. |
| D26 | L | Repo hygiene | MIT, public repo, `.env.example` committed, dev-only secrets labelled, nothing real in git history. | — |

---

## 4. Assumptions and open items

| # | Assumption | If wrong |
|---|---|---|
| A1 | MacBook M1 (2021, Apple Silicon/arm64) with **≥16 GB RAM**; upgrade planned | With 8 GB: Mode A only, default to `e5-small`, run the bge-m3 benchmark once and unload it |
| A2 | LLM via **OpenRouter**, user-funded; HF router as fallback; local models after the hardware upgrade (Phase 6) | Any OpenAI-compatible endpoint works by changing `LLM_BASE_URL` |
| A3 | Corpus German + English | English-only → reconsider D9 candidates |
| A4 | 8–10 h/week is realistic (confirmed) | Use the cut line in §9 |
| A5 | Public GitHub repo + GitHub Actions | Port workflows (~2 h) |
| A6 | An Azure subscription can be created in week 2 (M1.7) | Move M1.7 later; Phase 5 risk increases |

**Still open (decide during M1.0):**
- **RAM size** of the Mac (affects A1).
- **Monthly token cap** for the OpenRouter key (suggestion: 10–20 USD while building Phase 1).
- **Project name** — `kb-agent` undersells the "Dev of the future" idea; pick a real name before the repo goes public.
- **Dev and demo model** on OpenRouter — pick by price/quality in M1.3, record in ADR-0005, re-check with the eval harness.

---

## 5. Architecture (Phase 1)

```
 Browser — Angular 22 (:4200)
   │ ① OIDC code + PKCE                         │ ② REST + SSE (Bearer JWT, aud=kb-api)
   ▼                                            ▼
 Keycloak (:8080) ◄──────── JWKS ─────────── NestJS API (:3000) ─────────► Postgres db `app` (documents)
   │                                            │
   ▼                                            │ ③ REST + SSE relay (client-credentials JWT, aud=kb-ai, + user context)
 Postgres db `keycloak`                         ▼
                                     AI service — FastAPI (:8000)
                                       ingest: parse → chunk → embed (fastembed)
                                       chat:   embed query → search → prompt → LLM stream
                                        │                 │                     │
                                        ▼                 ▼                     ▼
                                  Qdrant (:6333)   LLM API (OpenAI-compatible)  Phoenix (:6006)
                                  alias kb_current OpenRouter | HF | fake       OTLP traces
```

| Service | Port | Image / runtime | Browser-facing |
|---|---|---|---|
| web | 4200 (dev server, or nginx `:80` mapped to `4200` in full profile) | Angular 22 → nginx | yes |
| api | 3000 | NestJS 12 on Node 24 | yes |
| ai-service | 8000 | FastAPI on Python 3.13 | **no** |
| keycloak | 8080 | `quay.io/keycloak/keycloak:26.7.x` (`start-dev --import-realm`) | yes (login) |
| postgres | 5432 | `postgres:17` + init script | no |
| qdrant | 6333 / 6334 | `qdrant/qdrant:1.18.x` | no (dashboard on localhost) |
| phoenix | 6006 (UI) / 4317 (OTLP gRPC) | `arizephoenix/phoenix` (pin version) | no (localhost only) |

Ports are identical in Mode A and Mode B, so Keycloak redirect URIs never change. Every image must exist for arm64 (verify Phoenix in M1.1).

**Ingest flow**
1. Angular `POST /api/documents` (multipart + `domains[]`) → Nest guard (`editor`+), checks, SHA-256 dedupe → row `pending`, **202** `{id}`.
2. Background task: row → `processing`; stream file to `POST /v1/ingest` with `doc_id`, `owner_id`, `title`, `domains`.
3. AI service: parse → chunk → embed (`passage: `) → upsert (UUIDv5 ids) → `{chunk_count, page_count, embedding_model}`; spans traced.
4. Nest: row → `ready` / `failed`. Angular polls while any row is non-terminal.

**Chat flow**
1. Angular `POST /api/chat` `{messages, domains?}` → Nest guard (`viewer`+), throttle.
2. Nest → `POST /v1/chat` (SSE) with service token + `user` context.
3. AI service: embed query (`query: `) → search (`top_k`, `score_threshold`, optional domain filter) → emit `sources`.
4. Build grounded prompt (system rules, numbered sources clearly separated from instructions, trimmed history within a token budget) → `provider.stream_chat()` → emit `token` …
5. `done` with usage (tokens, cost if provided) or `error`. Trace: `chat` → `embed` → `search` → `llm`.
6. Nest pipes events to the browser; client disconnect aborts the upstream request; the AI service cancels the LLM stream.

---

## 6. Repository layout

```
kb-agent/
├─ apps/
│  ├─ web/                       # Angular 22 (Bootstrap 5.3 + SCSS)
│  │  └─ src/app/{core,features/{chat,documents,inspector},shared}/
│  ├─ api/                       # NestJS 12
│  │  └─ src/{auth,documents,chat,ai-client,db,health,common}/
│  └─ ai-service/                # FastAPI (uv)
│     ├─ src/ai_service/
│     │  ├─ api/                 # routers: ingest, search, chat, health
│     │  ├─ core/                # settings, auth, logging, tracing
│     │  ├─ ingest/              # parsers, chunkers
│     │  ├─ embeddings/          # fastembed wrapper, prefixes
│     │  ├─ vectorstore/         # Qdrant collections, alias, queries
│     │  ├─ llm/                 # LlmProvider, openai_compat, fake
│     │  ├─ rag/                 # prompt builder, citation validator, chat pipeline
│     │  └─ evals/               # metrics, runner, CLI (`kb-eval`)
│     └─ tests/
├─ packages/contracts/           # generated OpenAPI types + SSE JSON Schemas (committed, drift-checked)
├─ evals/
│  ├─ datasets/retrieval_v1.jsonl
│  ├─ runs/                      # results (git-ignored; CI uploads as artifact)
│  └─ README.md                  # how items are written, labelled and versioned
├─ infra/
│  ├─ compose/                   # docker-compose.yml (profiles: default = infra, full)
│  ├─ keycloak/realm-kb.json
│  └─ postgres/init.sql
├─ data/sample-docs/             # + ATTRIBUTION.md; runbooks/ written by you
├─ docs/{architecture.md, adr/}
├─ e2e/                          # Playwright smoke test
├─ .github/{workflows/, dependabot.yml}
├─ .env.example · .nvmrc · .python-version · .editorconfig
├─ package.json · pnpm-workspace.yaml
└─ plan.md
```

---

## 7. Contracts (draft — generated OpenAPI/JSON Schema is authoritative)

### 7.1 AI service (internal; Bearer JWT `aud=kb-ai`)

| Method & path | Purpose | Request → Response |
|---|---|---|
| `GET /healthz` · `GET /readyz` | liveness / readiness (Qdrant reachable, model loaded) | → `{status}` |
| `POST /v1/ingest` | parse, chunk, embed, upsert | multipart `file`, `doc_id`, `owner_id`, `title?`, `domains[]` → `{doc_id, chunk_count, page_count, embedding_model}` |
| `POST /v1/search` | dense retrieval (inspector, eval) | `{query, top_k=5, score_threshold?, domains?, doc_ids?}` → `{embedding_model, hits:[{chunk_id, doc_id, title, page, heading, domains, score, text}]}` |
| `POST /v1/chat` | grounded chat, **SSE** | `{messages:[{role, content}], domains?, user:{sub, roles}}` → events §7.3 |
| `DELETE /v1/documents/{doc_id}` | remove all points of a document | → `204` |

### 7.2 NestJS API (browser-facing; Bearer JWT `aud=kb-api`)

| Method & path | Min. role | Notes |
|---|---|---|
| `GET /api/me` | any | `{sub, name, roles}` |
| `GET /api/documents` | viewer | list with status and domains |
| `POST /api/documents` | editor | multipart + `domains[]`; **202**; 409 duplicate; 413/415 size/type |
| `DELETE /api/documents/:id` | editor (own) / admin (any) | deletes DB row + vectors |
| `POST /api/chat` | viewer | SSE relay of `/v1/chat` |
| `POST /api/search` | viewer | relay of `/v1/search` (retrieval inspector) |
| `GET /api/status` | admin | health of Nest, AI service, Qdrant, DB |
| `GET /healthz` · `GET /readyz` | — | probes |

Errors: **RFC 9457 `application/problem+json`**.

### 7.3 SSE events

```
event: sources   data: {"sources":[{"n":1,"docId":"…","title":"…","page":3,"heading":"…","domains":["devops"],"text":"…","score":0.82}]}
event: token     data: {"text":"…"}
event: done      data: {"usage":{"inputTokens":0,"outputTokens":0,"costUsd":null},"model":"…","traceId":"…"}
event: error     data: {"type":"…","title":"…","detail":"…"}
```

`traceId` lets the UI link a message to its Phoenix trace (dev mode only).

### 7.4 Postgres `app.documents` (Drizzle schema)

```sql
id              uuid primary key,
owner_id        text not null,           -- Keycloak `sub`
owner_name      text not null,
filename        text not null,
mime            text not null,
size_bytes      integer not null,
sha256          char(64) not null unique,
domains         text[] not null default '{}',
status          text not null check (status in ('pending','processing','ready','failed')),
error           text,
chunk_count     integer,
page_count      integer,
embedding_model text,
created_at      timestamptz not null default now(),
updated_at      timestamptz not null default now()
```

### 7.5 Qdrant point payload

```json
{
  "doc_id": "uuid", "chunk_index": 12, "text": "…",
  "title": "…", "filename": "…", "page": 3, "heading": "Section › Subsection",
  "domains": ["devops", "sre"],
  "owner_id": "sub", "visibility": "org", "allowed_groups": [],
  "sha256": "…", "embedding_model": "intfloat/multilingual-e5-base"
}
```

### 7.6 Golden-set item (`evals/datasets/retrieval_v1.jsonl`)

```json
{"id":"r-017","question":"Wie rolle ich ein fehlerhaftes Deployment zurück?","lang":"de",
 "domains":["devops"],"answerable":true,
 "relevant":[{"doc":"runbook-rollback.md","heading":"Rollback"}],"notes":"paraphrased, no keyword overlap"}
```

Relevance is labelled by **document + heading/page**, not chunk id, so labels survive re-chunking. Mix item types:
direct lookup, paraphrase without keyword overlap, cross-language (DE question → EN source), multi-chunk, unanswerable.

### 7.7 Keycloak realm `kb`

- **Realm roles:** `viewer`, `editor` (⊃ viewer), `admin` (⊃ editor) → token claim `realm_access.roles`.
- **Clients:** `kb-web` — public, Standard Flow, **PKCE S256 required**, redirect `http://localhost:4200/*`, web origin `http://localhost:4200`, audience mapper → `kb-api`.
  `kb-api` — confidential, service account enabled, audience mapper → `kb-ai`.
- **Seed users (dev only):** `alice` (admin), `bob` (editor), `carol` (viewer).
- **Self-registration** on; default role `default-roles-kb` ⊃ `viewer`, so new users can chat and search. Turn it
  off (or gate it) before any public deployment — viewers spend LLM tokens (D24).
- **Settings:** access-token lifetime 5 min, refresh via `keycloak-js`; realm committed as `infra/keycloak/realm-kb.json`.

---

## 8. Milestones and tasks

Order: M1.0 → M1.1 → M1.2 → M1.3 → M1.4 → M1.5 → M1.6; **M1.7 in week 2** (independent).
Hours are ideal single-person hours, ±30 %.

### M1.0 — Repo & tooling (~5 h)

- [ ] GitHub repo, MIT license, README stub, `.gitignore`, `.editorconfig`, `.nvmrc` (24), `.python-version` (3.13)
- [ ] pnpm workspace: `packageManager` pin, `onlyBuiltDependencies`, catalog for TypeScript and shared tooling
- [ ] Scaffold `apps/web` (`ng new --package-manager pnpm`, SCSS, routing), `apps/api` (Nest CLI 12), `apps/ai-service` (`uv init`, FastAPI, ruff, pytest, pyright)
- [ ] Root scripts: `dev`, `lint`, `test`, `build`, `stack:up`, `stack:down`, `eval:retrieval`, `contracts:generate`
- [ ] Conventional Commits (+ optional lefthook for lint-on-commit)
- [ ] ADR-0001 (monorepo & pnpm), ADR-0002 (AI layer in Python), ADR-0003 (embeddings in-process)
- [ ] **Compatibility spikes (≤1 h each, outcome into the ADRs):** Zod via Nest 12 Standard Schema · Drizzle with Nest 12 ESM · `keycloak-angular` with Angular 22 · Angular default test runner
- [ ] Resolve the open items from §4 (RAM, token cap, project name)

**Acceptance:** clean clone → `pnpm install && pnpm lint && pnpm test` green; each app serves a hello endpoint/page.

### M1.1 — Local infra + auth walking skeleton (~8 h)

- [ ] Compose: Postgres (init → `keycloak`, `app`), Qdrant (volume), Keycloak (`--import-realm`), **Phoenix** (volume), healthchecks, fixed port map, arm64 check for every image
- [ ] Keycloak realm per §7.7; export committed; README section "how to re-export the realm"
- [ ] NestJS: zod config, `JwtAuthGuard` (`jose`, cached JWKS), `RolesGuard` + `@Roles()`, `GET /api/me`, health, CORS allow-list, `helmet`, `nestjs-pino`, request-id
- [ ] AI service: JWT dependency (`aud=kb-ai`), health, JSON logging, **OTel tracer → Phoenix** (one test span visible)
- [ ] Nest → AI service client with client-credentials token caching and request-id propagation
- [ ] Angular: `config.json` loader, Keycloak (PKCE), interceptor, route guard, landing page `Hello {name} · {roles}`, admin status card
- [ ] Token test matrix: no token 401 · wrong `aud` 401 · expired 401 · viewer on editor route 403

**Acceptance:** all seed users log in with correct roles; matrix passes; a test span appears in Phoenix; infra healthy in < 3 min from a clean clone (images cached).

### M1.2 — AI service: ingestion, retrieval, evaluation (~18 h)

- [ ] Settings (`pydantic-settings`), Qdrant client factory, `/readyz` (Qdrant + model loaded)
- [ ] `Embedder` (fastembed) with cache dir and **prefix handling + tests**
- [ ] Parsers (PDF with page mapping, MD with heading paths, TXT) + fixtures; `Chunker` (recursive, heading-aware, configurable)
- [ ] Collection manager: collection + alias `kb_current`, payload indexes (`doc_id`, `owner_id`, `domains`)
- [ ] `POST /v1/ingest`, `POST /v1/search` (domain filter, threshold), `DELETE /v1/documents/{doc_id}`; spans for parse/chunk/embed/upsert/search
- [ ] Write your **runbooks** and assemble the sample corpus with domain tags + `ATTRIBUTION.md`
- [ ] **Golden set v1:** 40–60 items across domains, DE + EN, ≥8 unanswerable, mixed item types (§7.6) — written *before* any tuning
- [ ] **Eval harness:** metrics (hit@k, MRR, nDCG, latency), runner, `kb-eval retrieval` CLI, JSON results, Markdown summary, per-domain/per-language breakdown
- [ ] **Benchmark** `e5-small/base/large` + `bge-m3` and two chunk sizes → ADR-0004 (model, chunking, calibrated `score_threshold`)
- [ ] Tests: unit (chunker, parsers, prefixes, metrics against hand-computed examples) + integration (ingest → search with in-process Qdrant `:memory:`)

**Acceptance:** ingest → search round-trip with page numbers; re-ingest creates no duplicates; delete removes all points; `pnpm eval:retrieval` produces the report; ADR-0004 contains the numbers.

### M1.3 — AI service: grounded chat (~8 h)

- [ ] `LlmProvider` protocol + `LlmEvent` union (`token`, `usage`, `error`; extensible for tool calls)
- [ ] `openai_compat` provider (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_MAX_OUTPUT_TOKENS`, timeouts, retries with backoff for 429/5xx; OpenRouter attribution headers optional) + `fake` provider
- [ ] Prompt builder: system rules (answer only from sources, say "not in the knowledge base" otherwise, reply in the user's language, cite as `[n]`), sources delimited and marked as untrusted data, history trimming with a token budget
- [ ] Citation validator (every `[n]` exists in `sources`) — used in tests now, as an eval metric in P3
- [ ] `POST /v1/chat` SSE pipeline; cancel the LLM stream on client disconnect; usage + cost in `done`
- [ ] OpenInference instrumentation of the `openai` SDK; `chat` span wraps embed/search/llm
- [ ] Tests: prompt snapshot, citation validator, SSE stream with `fake`, cancellation
- [ ] **Manual quality pass:** 10 golden questions against the dev model; notes + model choice in ADR-0005

**Acceptance:** `curl -N` streams `sources → token… → done`; the Phoenix trace shows all spans with prompt and token counts; switching between OpenRouter and the HF router needs only env changes.

### M1.4 — NestJS API: documents + relays (~10 h)

- [ ] Drizzle schema + migration (`documents`, §7.4)
- [ ] `DocumentsModule`: multipart with limits, MIME allow-list + magic bytes, SHA-256 dedupe (409), `domains` validated against the taxonomy, RBAC (own vs any), background ingest, boot recovery, delete (DB + vectors)
- [ ] `AiServiceClient` on generated types; upstream errors → problem+json
- [ ] `ChatModule`: SSE relay with **abort propagation**, per-user throttle; `POST /api/search` relay
- [ ] Global exception filter (RFC 9457), `GET /api/status`, OpenAPI → `packages/contracts`
- [ ] Tests: guards, documents service (dedupe, RBAC, domains), relay (events pass through unchanged, abort reaches upstream)

**Acceptance:** upload → `ready` → `/api/chat` streams end to end; viewer upload → 403; duplicate → 409; client disconnect cancels the upstream LLM call (test).

### M1.5 — Angular UI (~13 h)

- [ ] App shell (navbar + responsive sidebar), SCSS tokens / Bootstrap variable overrides
- [ ] **Documents:** drag-and-drop upload with domain multi-select, live status, delete with confirm, role-based controls (server enforces)
- [ ] **Chat:** `fetch` + `ReadableStream` SSE parser, streaming render, stop button, `[n]` citation chips → offcanvas (chunk text, doc, page), optional domain filter, empty/loading/error states, dev-mode link to the Phoenix trace
- [ ] **Retrieval inspector:** query + domain filter + `top_k` → ranked hits with scores, threshold line, chunk text and metadata
- [ ] Sanitized Markdown rendering; accessibility (labels, focus, `aria-live="polite"`, keyboard-operable citations)
- [ ] Tests: SSE parser, chat component with fake stream, auth guard

**Acceptance:** demo-script steps 2–5 and 8 work in the browser; no console errors.

### M1.6 — Containers, CI, e2e, docs (~10 h)

- [x] Dockerfiles ×3: multi-stage, non-root, pinned bases, `HEALTHCHECK`, `.dockerignore`; Angular via nginx (SPA fallback, `config.json` via `envsubst`, `proxy_buffering off` if nginx proxies SSE); embedding model baked in or cached volume
- [x] Compose `--profile full`
- [x] Workflows: `ci.yml` (lint/test/build, contract drift), `eval.yml` (retrieval eval on PRs touching `apps/ai-service/` or `evals/`; summary in the job summary; artifact upload; non-blocking), `docker.yml` (multi-arch buildx → GHCR on `main`), `e2e.yml` (full profile + Playwright, `fake` LLM)
- [x] `dependabot.yml` (npm, uv/pip, docker, github-actions)
- [ ] Branch protection on `main` (GitHub setting, not code)
- [x] README: pitch ("Dev of the future" assistant), Mermaid architecture, quickstart (OpenRouter key or `fake`), eval table, ADR index, roadmap
- [ ] README screenshots/GIF incl. Phoenix trace
- [x] `docs/architecture.md` with both flows

**Acceptance:** CI green on a fresh PR with the eval summary visible; multi-arch images on GHCR; README alone gets a stranger to demo steps 1–7.

> **Status 2026-10-19:** code complete, verified locally: `pnpm lint && pnpm test && pnpm build`, no
> contract drift, `pnpm stack:up:full` + `pnpm e2e` green. Still open, none of it code: the unchecked items
> above, and the first CI run on a PR / images on GHCR (needs a push).

### M1.7 — Azure readiness spike (mandatory, ~4 h, week 2)

- [ ] Azure subscription; **budget + e-mail alerts** (e.g. 30 USD/month); tags `project=kb-agent`
- [ ] Check **B-series vCPU quota** in Germany West Central / West Europe; request an increase if needed; choose the region
- [ ] Resource group + **ACR Basic**; push one image manually; document the commands
- [ ] Teardown script (everything except the budget)

**Acceptance:** test budget alert fires; image pulled from ACR elsewhere; ADR-0006 (region & quota).

> **Postponed 2026-10-19:** the project runs locally for now (assumption A6 → "move M1.7 later"). The spike
> needs no code change; do it before Phase 5 and file the quota request early. ADR-0006 and the
> "ADR-0001 … 0006" item of §10 wait for it.

---

## 9. Schedule (8–10 h/week)

| Week | Focus |
|---|---|
| 1 | M1.0 + start M1.1 |
| 2 | Finish M1.1 · **M1.7** (file the quota request early) |
| 3–4 | M1.2 (ingestion, retrieval, golden set, eval harness, benchmark) |
| 5 | M1.3 (grounded chat + tracing) |
| 6 | M1.4 (documents + relays) |
| 7–8 | M1.5 (UI incl. inspector) |
| 9 | M1.6 (containers, CI, e2e, README) |

**Cut line** (drop in this order): Playwright e2e → bge-m3 in the benchmark → dev-mode trace link → inspector threshold line → multi-arch builds on PRs.
**Never cut:** auth + RBAC, eval harness + golden set, tracing, `fake` provider, contract check, token cost guard, README.

---

## 10. Definition of Done (Phase 1)

- [ ] Demo script (§1) passes on a fresh clone
- [ ] Roles enforced server-side and covered by tests
- [ ] Ingestion idempotent; delete removes row and vectors; domain tags stored and filterable
- [ ] Chat streams with valid citations; disconnect cancels the upstream LLM call
- [ ] Provider switch (OpenRouter ↔ HF ↔ `fake`) is env-only
- [ ] `pnpm eval:retrieval` reports overall, per-domain and per-language metrics; ADR-0004 contains the benchmark
- [ ] Every chat request produces a Phoenix trace with retrieval and LLM spans
- [ ] CI green: lint, tests, contract drift, eval report, multi-arch images, e2e
- [ ] ADR-0001 … 0006 written; README with diagram, quickstart, screenshots
- [ ] No secrets in git; `.env.example` complete; the OpenRouter key has a credit limit

---

## 11. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Angular 22 / NestJS 12 ecosystem lag | Medium | M1.0 spikes with named fallbacks |
| Keycloak redirect / audience / CORS misconfiguration | High | Realm JSON in git, token test matrix in M1.1, fixed port map |
| M1 RAM pressure (Keycloak + Qdrant + Phoenix + embeddings + dev servers) | Medium | Mode A, smaller embedding model, stop unused services, upgrade planned |
| arm64/amd64 image mismatch | Medium | Multi-arch builds; verify every third-party image for arm64 in M1.1 |
| Token cost overrun | Low–Medium | Per-key credit limit, output cap, throttle, cheap dev model, no LLM calls in CI |
| Model behaviour drifts (OpenRouter routes to different providers, models get updated) | Medium | Pin model ids, log model + provider per request, re-run the manual pass when switching |
| Golden set too small / overfitted | Medium | Write it before tuning; version it; add items only via a documented process; separate tuning subset in P3 |
| Embedding cold start slows CI and containers | Medium | Readiness gate, baked/cached model, `e5-small` in CI |
| PDF extraction quality | Medium | Visible in citations and inspector; Docling in P3 |
| Indirect prompt injection via documents | Medium | Sources delimited as untrusted data; sanitized rendering; red-team set + guardrails in P3 |
| SSE breaks through proxies (two hops now) | Medium | Test through nginx in the full profile; `Cache-Control: no-transform`, `X-Accel-Buffering: no`; relay test in M1.4 |
| Scope creep | High | Cut line §9; new ideas go to the §13 backlog |

---

## 12. Hand-off to Phase 2

- `LlmEvent` and the SSE protocol have room for `tool_call` / `tool_result`; the agent loop is written next to `rag/` in the AI service
- `/v1/search` becomes the first agent tool; the same function is exposed through the **MCP server**
- `domains` tags feed a **router** (which tool/corpus to use) and per-domain evals
- The eval harness extends from retrieval to **agent evals** (tool selection, trajectory, task success)
- Traces already show every LLM call — the agent loop adds tool spans
- The `user` context in AI-service requests is replaced by **Keycloak token exchange** once tools act on behalf of the user
- Runtime `config.json` + env-only configuration keep images deployable to k3d (P4) and Azure (P5) unchanged

---

## 13. AI technology map (learning roadmap)

Each technique is introduced **only together with an eval that shows whether it helped** — that before/after
evidence is the portfolio artifact. "New in v2" marks items that were missing from the v1 roadmap.

### 13.1 Retrieval & knowledge

| Technique | Phase | New in v2 | What you learn / show |
|---|---|---|---|
| Chunking strategies (recursive, heading-aware → parent-child, structure-aware) | 1 → 3 | | Chunk size vs. recall trade-offs, measured |
| Embedding selection & multilingual benchmarking | 1 | | Model choice backed by numbers (ADR-0004) |
| Metadata/domain filtering | 1 | ✓ | Payload indexes, filtered vector search |
| Hybrid search (dense + sparse, RRF fusion) | 3 | | Qdrant query API, bge-m3 sparse vectors |
| Reranking (cross-encoder, e.g. fastembed rerankers) | 3 | | Two-stage retrieval, latency vs. quality |
| Query rewriting, multi-query, HyDE | 3 | | LLM-assisted retrieval |
| Contextual retrieval (LLM-generated context per chunk) | 3 | | Ingestion-time LLM use, cost vs. gain |
| **Code-aware RAG** (tree-sitter/AST chunking, code embeddings, repo indexing) | 3 | ✓ | Core capability for a *developer* assistant |
| GraphRAG (entities/relations, e.g. a service dependency graph) | 6 (opt.) | ✓ | Only if evals show multi-hop failures |
| Multimodal ingestion (architecture diagrams, screenshots via vision models) | 6 (opt.) | ✓ | Vision-model captioning into the index |

### 13.2 Agents

| Technique | Phase | New in v2 | What you learn / show |
|---|---|---|---|
| Tool-calling loop from scratch (streaming, max steps, parallel calls, error handling) | 2 | | What frameworks hide |
| **Agentic RAG** (agent decides whether/where to retrieve, self-check, multi-hop) | 2 | ✓ | Retrieval as a tool, not a fixed step |
| MCP server (own tools) + MCP client (official GitHub, Azure and AKS MCP servers) | 2 | | The protocol in both directions |
| MCP/tool auth (OAuth with Keycloak, token exchange, least privilege) | 2–3 | | On-behalf-of delegation |
| Human-in-the-loop approvals for write actions | 2 | | Safe action design |
| Skills with progressive disclosure | 3 | | Context-efficient capability packaging |
| **Long-term memory** (user profile: skills, goals, learning progress) | 3 | ✓ | Fits the mentor angle of "Dev of the future" |
| Sandboxed code execution (e.g. Container Apps dynamic sessions) | 3 | | Running untrusted code safely |
| **Multi-agent experiment**: domain specialists vs. one agent + skills, decided by eval | 6 (opt.) | ✓ | Evidence instead of hype |

### 13.3 Evaluation & data

| Technique | Phase | New in v2 | What you learn / show |
|---|---|---|---|
| **Retrieval eval** (hit@k, MRR, nDCG, per domain/language) | 1 | ✓ | Measurement discipline |
| Generation eval (faithfulness, relevance, citation accuracy, refusal on unanswerable) with **LLM-as-judge calibrated against your own labels** | 3 | | Judge reliability, not just judge scores |
| **Agent eval** (tool-selection accuracy, trajectory, task success, cost/latency per task) | 2–3 | ✓ | Evaluating non-deterministic workflows |
| **Synthetic data generation** (questions from the corpus, human-reviewed) | 3 | ✓ | Scaling eval sets; training data for P6 |
| Eval as CI gate (blocking on regressions) | 3 | | Quality as part of the pipeline |
| **Online feedback loop** (thumbs up/down → candidate eval items) | 3 | ✓ | Closing the loop with real usage |

### 13.4 LLMOps / MLOps

| Technique | Phase | New in v2 | What you learn / show |
|---|---|---|---|
| **Tracing** (OpenTelemetry + OpenInference, Phoenix) | 1 | ✓ | Debugging LLM systems |
| **Prompt versioning** linked to eval runs | 2 | ✓ | Prompts as tested artifacts |
| Token/cost tracking per user and request | 1–2 | | LLM FinOps |
| **Model routing / cascades** (cheap model first, escalate on low confidence), evaluated on cost vs. quality | 3 | ✓ | OpenRouter makes this cheap to try |
| **Semantic cache** (embedding-similarity cache in Qdrant) | 3 | ✓ | Cost and latency optimization |
| **Embedding/reranker fine-tuning** on synthetic pairs + **MLflow** tracking + model registry + rollout/rollback via Qdrant alias | 6 | ✓ | The full MLOps loop on a small, affordable model |
| Local inference (Ollama/MLX on the new Mac), quantization trade-offs, **local vs. API benchmark** on the same eval set | 6 | | Deferred by hardware |

### 13.5 Security & governance

| Technique | Phase | New in v2 | What you learn / show |
|---|---|---|---|
| Prompt-injection defence (direct and indirect) + red-team test set (OWASP Top 10 for LLM apps) | 1 (basics) → 3 | | Threat modelling for LLM apps |
| ACL-filtered retrieval (Keycloak groups → Qdrant filters) | 3 | | Authorization inside RAG |
| **Guardrails**: PII redaction (e.g. Presidio), groundedness check on answers, injection classifier (e.g. Azure AI Content Safety Prompt Shields) | 3 | ✓ | Defence in depth around the model |
| Tool permission model + audit log of agent actions | 2–3 | | Accountability for autonomous actions |
| **System card** (data sources, limitations, evals, intended use) | 6 | ✓ | Responsible-AI documentation in an EU context |

### 13.6 Phase 2 preview — domain tools for the "Dev of the future"

Phase 2 starts with **DevOps, Cloud/SRE (read-only) and Architecture**; the other domains follow in Phases 3–6.
Read-only first; every write action sits behind human approval.

| Domain | Corpus | Tool / MCP | Skill idea |
|---|---|---|---|
| DevOps | CI/CD docs, runbooks | GitHub MCP server (issues, Actions runs) | CI-failure triage |
| Cloud | Azure docs excerpts | Azure MCP server / AKS MCP server | Cost estimate, resource review |
| SRE | Runbooks, postmortems | Kubernetes status (read-only), later Prometheus queries | Incident triage, postmortem writer |
| Architecture | The repo's ADRs | ADR search over this repo | ADR writer, C4/Mermaid diagram |
| Dev | Code of this repo | Code search (code-aware RAG, P3) | Code-review checklist |
| DB | Postgres docs excerpts | Read-only SQL + `EXPLAIN` on a sample DB | Query review |
| Security | OWASP material | Dependency/CVE lookup, scan results | STRIDE threat model |
| MLOps | MLflow docs | MLflow runs/registry (P6) | Model-card writer |
| AI integration | This project's evals and traces | Phoenix / eval-results lookup | RAG-debugging assistant |

---

## Appendix A — Environment variables (`.env.example`)

```dotenv
# --- infra ---
POSTGRES_USER=postgres
POSTGRES_PASSWORD=dev-only-change-me
KEYCLOAK_ADMIN=admin
KEYCLOAK_ADMIN_PASSWORD=dev-only-change-me

# --- api (NestJS) ---
API_PORT=3000
LOG_LEVEL=info                              # pino: fatal|error|warn|info|debug|trace|silent
API_DATABASE_URL=postgresql://postgres:dev-only-change-me@localhost:5432/app
KEYCLOAK_ISSUER=http://localhost:8080/realms/kb
# KEYCLOAK_REALM_URL=                       # how the API reaches the realm; unset = KEYCLOAK_ISSUER (Mode B: keycloak:8080)
KEYCLOAK_AUDIENCE=kb-api
KEYCLOAK_CLIENT_ID=kb-api
KEYCLOAK_CLIENT_SECRET=dev-only-change-me
AI_SERVICE_URL=http://localhost:8000
AI_SERVICE_AUDIENCE=kb-ai
CORS_ORIGINS=http://localhost:4200
UPLOAD_MAX_MB=20
CHAT_THROTTLE_PER_MIN=20

# --- ai-service (FastAPI) ---
AI_PORT=8000
AI_KEYCLOAK_ISSUER=http://localhost:8080/realms/kb
AI_KEYCLOAK_AUDIENCE=kb-ai
# AI_KEYCLOAK_REALM_URL=                    # same for the AI service's JWKS fetch
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=
QDRANT_ALIAS=kb_current
EMBEDDING_MODEL=BAAI/bge-m3                 # ADR-0004
EMBEDDING_CACHE_DIR=./.cache/fastembed
CHUNK_SIZE=1000
CHUNK_OVERLAP=150
RETRIEVAL_TOP_K=5
RETRIEVAL_SCORE_THRESHOLD=0.55              # ADR-0004 calibration, model-specific
LLM_PROVIDER=openai_compat                  # openai_compat | fake
LLM_BASE_URL=https://openrouter.ai/api/v1   # HF alternative: https://router.huggingface.co/v1
LLM_API_KEY=                                # OpenRouter key WITH a credit limit; required unless fake
LLM_MODEL=openai/gpt-6-luna                 # required unless fake; demo: deepseek/deepseek-v4.1-flash (ADR-0005)
LLM_MAX_OUTPUT_TOKENS=800
LLM_TIMEOUT_S=60
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
OTEL_SERVICE_NAME=ai-service

# --- web (rendered into config.json in the container) ---
WEB_KEYCLOAK_URL=http://localhost:8080
WEB_KEYCLOAK_REALM=kb
WEB_KEYCLOAK_CLIENT_ID=kb-web
WEB_API_BASE_URL=http://localhost:3000
WEB_PHOENIX_URL=http://localhost:6006       # dev-mode trace links; empty = hidden
```

## Appendix B — Command cheat sheet (target UX)

```bash
pnpm install                         # web + api
(cd apps/ai-service && uv sync)      # Python deps
pnpm stack:up                        # Postgres, Qdrant, Keycloak, Phoenix (Mode A)
pnpm dev                             # web + api + ai-service with hot reload
pnpm stack:up:full                   # everything containerized (Mode B)
pnpm lint && pnpm test               # all apps
pnpm contracts:generate              # OpenAPI types + SSE JSON Schemas
pnpm eval:retrieval                  # golden-set retrieval eval → evals/runs/
pnpm e2e                             # Playwright smoke (full profile, fake LLM)
```
