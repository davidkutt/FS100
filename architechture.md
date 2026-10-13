# Architecture & Design Decisions

> **Project:** `kb-agent` (working title) — an assistant for the "Dev of the future".
> **Status:** living document · last updated 2026-10-13 · Phase 1 details in `plan.md` · significant decisions also get an ADR in `docs/adr/`.
> **Phase** column = when a decision takes effect (1–6). `→` means introduced in one phase and extended in a later one.

---

## 1. System overview

```
 Browser — Angular (web)
   │ ① OIDC code + PKCE                         │ ② REST + SSE (Bearer JWT, aud=kb-api)
   ▼                                            ▼
 Keycloak ◄──────────── JWKS ──────────────  NestJS (api) ─────────────► Postgres db `app`
   │                                            │
   ▼                                            │ ③ REST + SSE relay (client-credentials JWT, aud=kb-ai, + user context)
 Postgres db `keycloak`                         ▼
                                     Python AI service (ai-service)
                                       ingest: parse → chunk → embed
                                       chat:   embed query → search → prompt → LLM stream
                                        │                 │                     │
                                        ▼                 ▼                     ▼
                                      Qdrant       LLM API (OpenAI-compatible)  Phoenix
                                                   OpenRouter | HF | fake       traces
```

| Component | Responsibility | Technology |
|---|---|---|
| web | UI: login, documents, chat, retrieval inspector | Angular 22, Bootstrap 5.3 + SCSS, served by nginx |
| api | Auth, RBAC, document metadata, stream relay; later conversations, audit, quotas | NestJS 12 on Node 24, Drizzle |
| ai-service | Parsing, chunking, embeddings, retrieval, prompting, LLM calls, evaluation, tracing; later agent loop, tools, MCP | FastAPI on Python 3.13, fastembed |
| keycloak | Identity, roles, tokens | Keycloak 26.7 |
| postgres | Databases `keycloak` and `app` | Postgres 17 |
| qdrant | Vector index | Qdrant 1.18 |
| phoenix | LLM traces | Arize Phoenix (OpenTelemetry) |
| LLM API | Text generation | OpenRouter (default), Hugging Face router, `fake` for tests |

---

## 2. Product & scope

| ID | Decision | Why | Phase |
|---|---|---|---|
| GOAL-1 | Build an assistant for the "Dev of the future" (DB, Dev, Cloud, DevOps, MLOps, AI integration, Security, Architecture, SRE); the Phase 1 corpus is platform/DevOps | A concrete use case is a stronger portfolio piece than a generic "chat with your docs" demo and gives corpus, tools and evals a clear direction | 1 |
| GOAL-2 | Domain taxonomy `db, dev, cloud, devops, mlops, ai, security, architecture, sre`, tagged on every document and eval question | Enables domain filters, routing and per-domain metrics; new domains need no re-modelling | 1 |
| GOAL-3 | Local-first: daily use runs locally, the Azure deployment is a demo | One user doesn't justify 24/7 cloud cost; local iteration is faster; the same images run in both | 1 |
| GOAL-4 | Six phases, each ending in a working, demonstrable state; Phase 1 is a full vertical slice | One working end-to-end slice beats many half-finished components; every phase is portfolio-ready | 1–6 |
| GOAL-5 | Every AI technique is introduced together with an evaluation that shows whether it helped | Before/after evidence is the portfolio artifact and prevents complexity without benefit | 1–6 |
| GOAL-6 | No agent/RAG framework (LangChain, LlamaIndex) through Phase 2 — raw SDKs only | Learning goal: understand what frameworks hide; a framework comparison can follow later | 1–2 |
| GOAL-7 | Retrieval and grounded chat first; agent, tools and MCP from Phase 2 | Agents depend on reliable retrieval; a measured baseline makes later gains visible | 1 |

## 3. Repository & tooling

| ID | Decision | Why | Phase |
|---|---|---|---|
| REPO-1 | Monorepo for apps, infra, evals and docs | One PR can change a contract and all its consumers; one CI | 1 |
| REPO-2 | pnpm workspaces, pinned via `packageManager`; `onlyBuiltDependencies` allow-list; catalogs for shared versions | Strict `node_modules` prevents phantom dependencies between apps; `--filter` and `pnpm deploy` simplify CI and Docker; fast cached installs. npm is looser and slower, Yarn PnP causes tooling friction, Bun is a runtime bet unrelated to the goals. pnpm 10 blocks dependency install scripts by default, hence the allow-list | 1 |
| REPO-3 | uv for the Python service | Fast resolver, lockfile and Python version management in one tool | 1 |
| REPO-4 | No Nx / Turborepo | Two Node apps don't justify a build orchestrator | 1 |
| REPO-5 | Root `package.json` scripts as task entry points, no Makefile | Works the same on macOS, Linux and Windows/WSL2 | 1 |
| REPO-6 | Pinned versions: Node 24 LTS, Angular 22, NestJS 12, Python 3.13, Keycloak 26.7.x, Qdrant 1.18.x, Postgres 17, Bootstrap 5.3 | Current stable lines; Node 26 reconsidered once it enters LTS (28 Oct 2026); Dependabot keeps pins fresh | 1 |
| REPO-7 | Compatibility spikes with named fallbacks before building (Zod in Nest 12, Drizzle, keycloak-angular, Angular test runner) | Angular 22 and NestJS 12 are new majors; the ecosystem may lag | 1 |
| REPO-8 | Trunk-based development with short-lived branches and PRs (also solo), Conventional Commits | CI gates every change; readable history and changelog | 1 |
| REPO-9 | Architecture Decision Records in `docs/adr/` | Documents the reasoning, not only the result — valuable for reviewers | 1 |
| REPO-10 | Public repository, MIT licence | Portfolio visibility; permissive licence (drives the licence checks in RAG-1 and RAG-11) | 1 |

## 4. Service architecture

| ID | Decision | Why | Phase |
|---|---|---|---|
| SVC-1 | Three applications: Angular (web), NestJS (api), Python FastAPI (ai-service) | Matches the target stack and separates product concerns from AI concerns | 1 |
| SVC-2 | NestJS is the product API / BFF and the only browser-facing backend | One security boundary to the outside; the product domain stays in TypeScript | 1 |
| SVC-3 | The Python AI service owns all AI logic: parsing, chunking, embeddings, retrieval, prompting, LLM calls, evaluation, tracing; later the agent loop, tools and MCP client | AI code, evals and traces live in one language and process; retrieval tuning without network hops; most AI tooling is Python-first | 1→2 |
| SVC-4 | The AI service is internal only | Smaller attack surface; every request passes NestJS auth | 1 |
| SVC-5 | Chat is stateless in Phase 1 (client sends the last N messages); persisted conversations follow in NestJS | Keeps the first slice small; conversations belong to the product domain | 1→2 |
| SVC-6 | Ingestion: NestJS accepts the upload, returns `202 Accepted` and runs a background task that streams the file to the AI service; a real queue follows later | Smallest thing that works end-to-end; the async API shape already fits a queue | 1→3 |
| SVC-7 | Boot-time recovery marks jobs stuck in `pending`/`processing` as `failed` | In-process background tasks are lost on restart; the status must stay truthful | 1 |
| SVC-8 | Original files are not stored in Phase 1 (metadata and chunks only) | Avoids a blob-storage dependency until the cloud phase | 1 |

## 5. APIs, streaming & contracts

| ID | Decision | Why | Phase |
|---|---|---|---|
| API-1 | REST for request/response; Server-Sent Events for chat, consumed with `fetch` streaming | A one-way token stream doesn't need WebSockets; `EventSource` can't POST or send an `Authorization` header | 1 |
| API-2 | Fixed SSE events `sources`, `token`, `done`, `error`; extensible with `tool_call` / `tool_result` | Sources arrive first so citations render immediately; the agent phase adds events without a protocol change | 1→2 |
| API-3 | NestJS relays AI-service events unchanged | NestJS adds only auth and throttling; no AI logic duplicated in TypeScript | 1 |
| API-4 | Cancellation propagates browser → NestJS → AI service → LLM | Stops generation and token cost when the user stops or leaves | 1 |
| API-5 | OpenAPI-first contracts: generated TypeScript types (FastAPI → NestJS, NestJS → Angular) are committed; SSE event schemas are exported as JSON Schema from Pydantic; CI fails on drift | Breaking changes across three apps are caught at PR time; OpenAPI describes SSE poorly | 1 |
| API-6 | Errors as RFC 9457 `application/problem+json` | One standard error shape across services and clients | 1 |
| API-7 | Validation with Zod in NestJS (via Standard Schema; fallback class-validator) and Pydantic v2 in Python | One schema language per runtime, with inferred types | 1 |
| API-8 | `x-request-id` propagated across all hops; the `done` event carries the trace ID | Correlates logs, traces, UI messages and feedback | 1 |

## 6. Identity & access

| ID | Decision | Why | Phase |
|---|---|---|---|
| IAM-1 | Keycloak as identity provider (realm `kb`) | Standard OIDC/OAuth with roles and groups; self-hostable; identical locally and in the cloud | 1 |
| IAM-2 | Angular uses Authorization Code + PKCE as a public client (`kb-web`) via `keycloak-js` | Standard flow for SPAs; no client secret in the browser | 1 |
| IAM-3 | NestJS validates JWTs itself with `jose` and cached JWKS (issuer, audience, expiry, signature) — no wrapper library | Small, explainable and testable; avoids lagging third-party integrations | 1 |
| IAM-4 | Separate audiences: browser tokens `aud=kb-api`, service tokens `aud=kb-ai` | A token is only accepted by the service it was issued for | 1 |
| IAM-5 | NestJS → AI service with a client-credentials token plus a user context object | Defense in depth for an internal service; prepares ACL filtering | 1 |
| IAM-6 | OAuth 2.0 Token Exchange (RFC 8693) so the AI layer and tools act on behalf of the user | Tools touching real systems need the user's rights, not a shared service account | 2–3 |
| IAM-7 | Realm roles `viewer` < `editor` < `admin` as composites | Simple, demonstrable permission matrix | 1 |
| IAM-8 | Authorization is enforced server-side; hiding UI controls is only convenience | The UI can be bypassed | 1 |
| IAM-9 | Documents are org-wide in Phase 1, but `owner_id`, `visibility` and `allowed_groups` exist from day one; ACL-filtered retrieval later | No data migration needed later; per-document permissions are a dedicated learning topic | 1→3 |
| IAM-10 | Access tokens live 5 minutes and are refreshed by `keycloak-js` | Limits the damage of a leaked token | 1 |
| IAM-11 | Realm exported as JSON in git; seed users `alice` / `bob` / `carol` for development only | Reproducible auth setup; no configuration drift | 1 |
| IAM-12 | BFF cookie pattern kept as optional hardening | Removes tokens from the browser entirely; not needed for the first slices | 6 (opt.) |

## 7. Data & storage

| ID | Decision | Why | Phase |
|---|---|---|---|
| DATA-1 | Postgres 17, one instance with databases `keycloak` and `app` | Mirrors the cheap cloud target (one managed server, two databases) | 1 |
| DATA-2 | Drizzle ORM with drizzle-kit migrations (instead of Prisma) | ESM-native for NestJS 12, schema in TypeScript, readable SQL migrations, no codegen step | 1 |
| DATA-3 | `documents` table with unique SHA-256, status lifecycle, domains, chunk/page counts and embedding model | Supports dedupe, status tracking, filtering and knowing which model indexed what | 1 |
| DATA-4 | Qdrant as vector database | Open source, fast filtered search, named dense + sparse vectors for later hybrid search, runs locally and in the cloud | 1 |
| DATA-5 | Collections named `kb__{model}__{dim}` behind the alias `kb_current` | Model or chunking changes are built in parallel and switched atomically, with instant rollback | 1 |
| DATA-6 | Named dense vector `dense` (cosine) | Leaves room for a sparse vector on the same points | 1→3 |
| DATA-7 | Deterministic point IDs: UUIDv5(`doc_id:chunk_index`) | Re-ingesting a document overwrites instead of duplicating | 1 |
| DATA-8 | Payload indexes on `doc_id`, `owner_id`, `domains` | Fast filtered search and deletes | 1 |

## 8. Retrieval pipeline

| ID | Decision | Why | Phase |
|---|---|---|---|
| RAG-1 | PDF parsing with pypdf (page-aware); plain read for Markdown/TXT; not PyMuPDF | Lightweight and keeps page numbers for citations; PyMuPDF's AGPL licence conflicts with an MIT repo | 1 |
| RAG-2 | Layout-aware parsing (Docling) behind the same `Parser` interface | Handles tables and complex layouts once the baseline is measured | 3 |
| RAG-3 | Recursive chunking (~1000 characters, 150 overlap), heading-aware for Markdown, behind a `Chunker` interface | Sensible default; size and strategy are decided by the benchmark | 1 |
| RAG-4 | Embeddings computed in-process with fastembed (ONNX, CPU) | No token cost, identical locally and in the cloud, no external dependency for retrieval | 1 |
| RAG-5 | Multilingual embedding model; candidates `multilingual-e5-small/base/large` and `bge-m3`; `e5-base` as default until the benchmark decides | The corpus is German and English; bge-m3 also produces sparse vectors for hybrid search | 1 |
| RAG-6 | E5 `query:` / `passage:` prefixes enforced in code and tests | E5 models lose quality without them | 1 |
| RAG-7 | Dense-only retrieval first; hybrid search, reranking, query rewriting and contextual retrieval later | Measure a baseline before adding techniques | 1→3 |
| RAG-8 | Similarity threshold calibrated with unanswerable eval questions; "not in the knowledge base" instead of guessing | Abstaining is better than answering confidently from irrelevant context | 1 |
| RAG-9 | Grounded prompt: numbered sources delimited as untrusted data, answer only from sources, cite as `[n]`, reply in the user's language; citation validator | Traceable answers and a first defence against indirect prompt injection | 1 |
| RAG-10 | Conversation history trimmed to a token budget | Predictable cost and latency; keeps room for sources | 1 |
| RAG-11 | Sample corpus: this repo's docs and ADRs, self-written runbooks, licence-checked excerpts of upstream docs, 1–2 German documents, attribution file | Licence-safe in a public repo; an assistant explaining its own stack is a strong demo | 1 |
| RAG-12 | Code-aware RAG (syntax-tree chunking) for repository content | A developer assistant has to understand code | 3 |

## 9. LLM access & cost

| ID | Decision | Why | Phase |
|---|---|---|---|
| LLM-1 | `LlmProvider` protocol in Python with two implementations: `openai_compat` and `fake` | One adapter covers every OpenAI-compatible endpoint; `fake` makes tests deterministic and free | 1 |
| LLM-2 | OpenRouter as default endpoint, Hugging Face router as alternative | User-funded key with access to many models and per-key credit limits; switching is an env change | 1 |
| LLM-3 | No native vendor adapter for now | Added only if a needed feature isn't reachable through the OpenAI-compatible API | 1 |
| LLM-4 | Local models (Ollama / MLX) deferred | The 2021 M1 is limited and will be upgraded; Ollama speaks the same API, so nothing is rewritten | 6 |
| LLM-5 | The cloud deployment uses API models only (no GPU nodes) | GPU VMs would dominate the cost of a single-user demo | 5 |
| LLM-6 | Model IDs only in configuration, pinned; model and provider logged per request | Gateways and providers change models; drift must be traceable | 1 |
| LLM-7 | Cost guards: per-key credit limit, output cap (800 tokens), per-user throttle, cheap model for development, no paid LLM calls in CI | Tokens are paid personally; caps make mistakes cheap | 1 |
| LLM-8 | Only public or self-written documents in the corpus | Gateways forward prompts and retrieved chunks to third-party providers | 1 |

## 10. Evaluation & observability

| ID | Decision | Why | Phase |
|---|---|---|---|
| EVAL-1 | Retrieval evaluation is part of Phase 1 | Every later change needs a measured baseline | 1 |
| EVAL-2 | Golden set of 40–60 items (German + English, all domains, ≥8 unanswerable, paraphrase and cross-language items), written before any tuning and versioned | Realistic coverage; writing it before tuning prevents overfitting | 1 |
| EVAL-3 | Relevance labelled by document + heading/page, not chunk ID | Labels survive re-chunking and model changes | 1 |
| EVAL-4 | Metrics hit@1/5, MRR@10, nDCG@10 and latency p50/p95, overall and per domain and language | Standard retrieval metrics plus speed; breakdowns show where it fails | 1 |
| EVAL-5 | Eval runs in CI as a report on relevant PRs; becomes a blocking gate later | Collect a stable baseline before blocking merges | 1→3 |
| EVAL-6 | LLM tracing with OpenTelemetry + OpenInference, exported to Arize Phoenix | Shows retrieval, prompt, tokens and latency per request; single container, OTel-native. Self-hosted Langfuse v3 needs ClickHouse, Redis and object storage | 1 |
| EVAL-7 | Structured JSON logs; `/healthz` (liveness) and `/readyz` (readiness incl. dependencies and loaded model) | Operable from day one; required for Kubernetes probes later | 1 |
| EVAL-8 | Generation and agent evals with an LLM judge calibrated against own labels | Answer quality and tool behaviour need their own metrics | 2–3 |

## 11. Frontend

| ID | Decision | Why | Phase |
|---|---|---|---|
| WEB-1 | Angular 22 with standalone components, signals and feature folders | Current Angular idioms and a clear structure | 1 |
| WEB-2 | Bootstrap 5.3 via SCSS with variable overrides; no jQuery; ng-bootstrap only if a component needs it | Matches the target stack; theming via SCSS variables; fewer dependencies | 1 |
| WEB-3 | Runtime `config.json` loaded before bootstrap, rendered from env by nginx (`envsubst`) | One image for local, k3d and Azure | 1 |
| WEB-4 | Model output rendered as sanitized Markdown | Prevents XSS, including through injected content | 1 |
| WEB-5 | Retrieval inspector (raw hits, scores, threshold, filters) as a core page | Makes retrieval quality visible for debugging and demos | 1 |
| WEB-6 | Document status updated by polling while jobs are running | Simplest option for short-lived jobs | 1 |
| WEB-7 | Accessibility basics: labelled controls, focus management, `aria-live` for streamed text, keyboard-operable citations | Streaming UIs are otherwise hard to use with assistive technology | 1 |
| WEB-8 | Dark mode, Signal Forms and Lighthouse targets deferred | Time goes to AI features first | 6 |

## 12. Local development & testing

| ID | Decision | Why | Phase |
|---|---|---|---|
| DEV-1 | Mode A (daily): infra in Docker Compose, apps native with hot reload. Mode B: everything containerized via `--profile full` | Fast dev loop on limited RAM; Mode B tests the real images | 1 |
| DEV-2 | Fixed port map, identical in both modes | Keycloak redirect URIs and CORS never change | 1 |
| DEV-3 | No local LLM in Phase 1 | M1 hardware; API models via OpenRouter instead | 1 |
| DEV-4 | pytest (+ testcontainers for Qdrant), Vitest + supertest for NestJS, Angular CLI default runner, one Playwright smoke test with the fake LLM | Real dependencies where it matters, deterministic everywhere | 1 |

## 13. Containers & CI/CD

| ID | Decision | Why | Phase |
|---|---|---|---|
| CICD-1 | GitHub Actions with per-app jobs, path filters and caching | Free for public repos; fast feedback | 1 |
| CICD-2 | Images published to GHCR first, Azure Container Registry later | No cloud dependency until it's needed | 1→5 |
| CICD-3 | Multi-arch images (`linux/amd64` + `linux/arm64`) on `main`; amd64 only on PRs | arm64 for the Mac, amd64 for AKS nodes; faster PR builds | 1 |
| CICD-4 | Dockerfiles: multi-stage, non-root, pinned base images, healthcheck; embedding model baked in or cached | Small, secure, reproducible images; no model download on cold start | 1 |
| CICD-5 | SSE through proxies: buffering off, `Cache-Control: no-transform`, `X-Accel-Buffering: no` | Proxies otherwise buffer and break token streaming | 1 |
| CICD-6 | Dependabot for npm, Python, Docker and Actions; branch protection requires green CI | Keeps pinned versions current and safe | 1 |
| CICD-7 | Vulnerability scanning (Trivy) deferred | Lower priority than AI features | 6 |

## 14. Cloud & deployment

| ID | Decision | Why | Phase |
|---|---|---|---|
| CLOUD-1 | Microsoft Azure as cloud provider | Target stack of the portfolio | 5 |
| CLOUD-2 | AKS on the Free tier (no control-plane fee) | No SLA needed for a demo; real Kubernetes for the portfolio | 5 |
| CLOUD-3 | Ephemeral cluster by default, created and destroyed by a GitHub Actions workflow (Terraform + Helm); 24/7 only during application periods | 24/7 was estimated at ~100–125 USD/month versus a few dollars plus runtime hours; also demonstrates infrastructure as code | 5 |
| CLOUD-4 | Azure Container Apps (scale-to-zero) as fallback for a lean always-on demo | Cheaper always-on option if the ephemeral cluster isn't enough | 5 (opt.) |
| CLOUD-5 | Terraform for Azure resources, Helm chart for the apps, tested locally with k3d | The same chart locally and in the cloud; reproducible infrastructure | 4–5 |
| CLOUD-6 | GitHub → Azure authentication via OIDC federation; secrets in Key Vault | No long-lived cloud credentials in GitHub | 5 |
| CLOUD-7 | Managed Postgres (Flexible Server, burstable tier) hosting both databases | Cheapest managed option; mirrors the local layout | 5 |
| CLOUD-8 | Budget with e-mail alerts (e.g. 30 USD/month) and resource tags from day one | Cost protection for a personal subscription; FinOps practice | 1 |
| CLOUD-9 | Mandatory Azure readiness spike in week 2 (budget, vCPU quota, region, ACR) | Quota increases can take days; finds blockers long before the cloud phase | 1 |
| CLOUD-10 | Same images and env-only configuration across local, k3d and Azure | No environment-specific builds | 1 |

## 15. Agent layer (direction for Phases 2–6)

| ID | Decision | Why | Phase |
|---|---|---|---|
| AGT-1 | Agent loop written from scratch in the Python AI service | Learning goal; full control over streaming, step limits and errors | 2 |
| AGT-2 | Retrieval becomes a tool (agentic RAG); the same functions are exposed through an own MCP server | One implementation serves the in-app agent and external MCP clients | 2 |
| AGT-3 | MCP client consuming existing servers (official GitHub, Azure and AKS MCP servers) | Reuse instead of rebuilding integrations; shows MCP in both directions | 2 |
| AGT-4 | First domain tools: DevOps, Cloud/SRE (read-only), Architecture | Closest to the Phase 1 corpus; read-only keeps the risk low | 2 |
| AGT-5 | Read-only tools first; write actions only after human approval; every tool call in an audit log | Safe and accountable autonomy | 2–3 |
| AGT-6 | Skills as folders with `SKILL.md`, loaded by progressive disclosure | Capabilities grow without bloating the context | 3 |
| AGT-7 | Sandboxed code execution (e.g. Container Apps dynamic sessions) | Runs model-generated code without endangering the host | 3 |
| AGT-8 | Multi-agent setup only if evals show it beats one agent with skills | No complexity without evidence | 6 (opt.) |

## 16. Security

| ID | Decision | Why | Phase |
|---|---|---|---|
| SEC-1 | Layered prompt-injection defence: sources delimited as untrusted data, sanitized rendering, least-privilege tools; red-team set later | No single defence is sufficient | 1→3 |
| SEC-2 | Upload validation: ≤20 MB, allow-list PDF/MD/TXT, magic-byte check, SHA-256 dedupe | Blocks disguised files and duplicates | 1 |
| SEC-3 | `helmet`, CORS allow-list and per-user rate limiting in NestJS | Standard web hardening; limits abuse and token cost | 1 |
| SEC-4 | Secrets: `.env.example` committed, `.env` ignored, dev-only credentials labelled; cloud secrets regenerated and stored in Key Vault | A public repo must never contain real secrets | 1→5 |
| SEC-5 | Guardrails: PII redaction, prompt-injection classifier, groundedness checks | Defence in depth around the model | 3 |

---

## 17. Open decisions

| Topic | Decide in | Notes |
|---|---|---|
| RAM of the development Mac | M1.0 | 8 GB shifts defaults to `e5-small` and Mode A only |
| Monthly credit limit of the OpenRouter key | M1.0 | Suggested 10–20 USD during Phase 1 |
| Project name | Before the repo goes public | `kb-agent` is a placeholder |
| Development and demo LLM | M1.3 (ADR-0005) | Chosen by price/quality, re-checked with evals |
| Final embedding model, chunk size and threshold | M1.2 (ADR-0004) | From the benchmark |
| Azure region | M1.7 (ADR-0006) | Germany West Central or West Europe, depending on quota |
| Qdrant in the cloud: in-cluster or Qdrant Cloud free tier | Phase 5 | Decide when the deployment is designed |
