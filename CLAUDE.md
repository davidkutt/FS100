# CLAUDE.md

Guide for agents working in FS100. Read this first; follow the links only when the task needs them.

## ALWAYS rules

1. **ALWAYS record learnings.** Whenever the user is frustrated with the code you produced or criticizes
   it, you MUST add a new rule to [Applied Learnings](#applied-learnings) in the same turn — one line,
   phrased as an actionable rule, not a story. Follow every Applied Learning unless the user tells you to
   ignore it or ignoring it is absolutely necessary for the user's task.
2. **ALWAYS keep comments minimal.** Add a code comment only when absolutely necessary (a non-obvious
   *why*: a workaround, a constraint, a surprising choice). Never restate what the code does. Keep each
   comment as short and concise as possible.
3. **ALWAYS** follow the LAZY RULES section, except when it's crucial to the task or the user explicitly asks for it./ 
4. **ALWAYS** follow the Capturing lessons section.

## Capturing lessons: rule, skill, or nothing

When I correct you, or when you finish a task, decide where the lesson belongs:

- **Constraint or preference** ("always X", "never Y") → one-line rule in CLAUDE.md.
- **Reusable multi-step procedure** → a skill, but only if ALL of these hold:
  - it took several steps, commands or lookups that weren't obvious from the code
    (env setup, migrations, release steps, test fixtures, codegen, a debugging recipe for this stack)
  - it will realistically come up again, in this project or others
  - no existing skill covers it; if one is close, update that one instead
- **One-off** → nothing.

Don't interrupt the task for a skill. At the end, create it and tell me in one line what you added.

When creating or updating a skill:
- Path: `.claude/skills/<name>/SKILL.md` for this repo,
  `~/.claude/skills/<name>/SKILL.md` if it applies across projects.
- The `description` is all a future session sees before loading the skill, so it decides
  whether the skill ever gets used. Lead with what it does, then "Use when…" with the words
  I'd actually type and the files/tools involved. 1–3 sentences, clearly distinct from
  existing skill descriptions.
- Body: exact commands in order, the pitfalls hit this time, and how to verify success.
  Imperative, no narrative, most important steps first. Keep it short; put long reference
  material in separate files in the skill folder and link to them.
- Add `disable-model-invocation: true` if it has side effects (deploy, publish, send, delete),
  so it only runs when I type /name.
- Move any CLAUDE.md rules that only apply to this workflow into the skill, and delete them
  from CLAUDE.md.
- Don't reference the skill in CLAUDE.md; the description handles discovery.
## What this is

FS100 is a RAG/agent assistant: upload domain-tagged documents, ask questions, get streamed answers with
citations, with every retrieval change measured by evals and every request traced.

**Goal since 2026-10-26: a daily-use tool for one person on a 16 GB M1.** The corpus is the user's Markdown
notes, and it's used from Claude Code / VS Code (`/mcp`) and the web UI. There is no Kubernetes, Azure or
public demo. What's next is in [plan-daily-use.md](plan-daily-use.md) (Phase 3c, M3c.0–M3c.5). Phases 4–6 and
the rest of Phase 3 are parked.

**Phase 1 is done except M1.7**: M1.0 (repo, skeletons, local infra, CI), M1.1 (auth walking skeleton),
M1.2 (ingest/search/delete in the AI service, golden set, `pnpm eval:retrieval`), M1.3 (grounded chat
`POST /v1/chat` as SSE), M1.4 (documents + chat/search relays in NestJS, contracts), M1.5 (Angular UI:
documents, chat, inspector) and M1.6 (Dockerfiles, Compose `--profile full`, CI workflows, Playwright e2e)
are done. M1.7 (Azure spike) is postponed while the project runs locally, so Phase 2 has no Azure parts.
**Phase 2 (agent, MCP, approvals)** — M2.0 (pins, spikes, identities, ADR-0007…0010
drafts), M2.1 (agent harness: `agent.py`, `tools.py`, `POST /v1/agent` with SSE v2, task set
`agent_v0`), M2.2 (conversations + event tee in NestJS, model registry, taxonomy + document topics,
agent chat UI), M2.3 (signed approvals `approvals.py` + resume, NestJS approval state machine,
append-only `audit_log`, approval card and admin audit page) and M2.4 (own MCP server `mcp_server.py` at
`/mcp`, Keycloak token exchange on both hops, `kb.ingest_url` via `/internal/documents/from-url`) are done, and so are
M2.5 (external MCP servers from `config/mcp_servers.yaml` in `catalog.py`, pinned `github-mcp` container,
`github_sandbox.create_issue`, embedding/LLM router `routing.py`), M2.6 (fixture GitHub MCP server in `evals/fixtures/`, `kb-eval agent | redteam | routing`, blocking retrieval
gate in `eval.yml`, ADR-0011/0012 proposed) and M2.7 (prompt files `ai_service/prompts/*.md` with version + hash,
daily cost caps in `apps/api/src/usage/`, admin usage page, system card, e2e approval smoke; only the README GIF
is open); M2.8 (Claude Code / VS Code log in to `/mcp` via Keycloak CIMD, ADR-0014) is code-complete, the hand check
in Claude Code is open. **Phase 3a (retrieval quality)** — M3a.0
(golden set split into `dev`/`test` via a `split` field, baselines in `evals/baselines/p2-dense/`, `pnpm mem`,
spikes, ADR-0015…0018 drafts), M3a.1 (originals in Postgres `ai`, Procrastinate queue with in-process worker,
collection v2 with versioned IDs, `kb-admin reindex` behind the golden-set gate + rollback, admin re-index page) and
M3a.2 (hybrid search: BM25 from fastembed in the AI service, weighted RRF, `explain` ranks in the inspector,
ADR-0016), M3a.3 (cross-encoder reranking, opt-in via `RERANKER_MODEL`, off by default: it lost hit@5 on `test`,
ADR-0017) and M3a.4 (HyDE in `query.py` as `strategy` of `search_knowledge_base` and `/v1/search`, follow-up set
`followup_v1`; multi-query and the follow-up rewrite lost on `dev` and were removed) and M3a.5 (Docling for PDFs in a
child process with pypdf fallback, parse stored in `ai.source_documents`; 1000/150 chunks searched, their parent
sections ≤ `PARENT_SIZE` 2000 chars returned once each; `get_document` by section; ADR-0018) and M3a.6
(contextual retrieval in `contextual.py`: one call per chunk with the document cached in the system prompt,
`CONTEXTUAL_DOMAINS`, labels stored in `ai.chunk_contexts`, job state `contextualizing`, payload `context` +
`chunk_topics`, taxonomy v2; ADR-0019) and M3a.7 (`lifecycle` / `priority` / `priority_topics` set in NestJS and
relayed as labels; retired documents filtered from every search; boost by positions after reranking when the
question's nearest sub-topics meet the scope; canonical sources marked in the prompts; `kb-eval --priorities`) are
done. The reranker, priorities, HyDE, the LLM router and Docling are frozen: no further work until M3c.2
measures them on the notes. Phase 3 ADRs start at 0015, not 0014. Check the milestone in
[plan-daily-use.md §3](plan-daily-use.md#3-milestones) (and the earlier plans it builds on) before building
something: most of the old roadmap is parked.

The plan's working title `kb-agent` lives on in identifiers (realm `kb`, clients `kb-web`/`kb-api`/`kb-ai`,
Qdrant alias `kb_current`). Keep those names.

## Map

| Path | What | Stack |
|---|---|---|
| `apps/web` | Frontend, browser-facing | Angular 22 (standalone, signals, zoneless), Bootstrap 5.3 via SCSS, Vitest, angular-eslint |
| `apps/api` | Product API / BFF: auth, RBAC, document metadata, SSE relay. Browser-facing | NestJS 12 (ESM), Vitest + supertest, oxlint |
| `apps/ai-service` | **All AI code**: parse, chunk, embed, retrieve, prompt, LLM, evals, tracing. Internal only | FastAPI, Python 3.13 (uv), pydantic-settings, ruff, pyright strict, pytest |
| `packages/contracts` | **Generated**, committed: OpenAPI of both services (+ SSE event schemas) and TS types | openapi-typescript |
| `config/` | `models.yaml` (model registry, AI service), `taxonomy.yaml` (domains + sub-topics, API and AI service); copied into the images | YAML |
| `infra/` | Compose (Postgres 17, Qdrant 1.19, Keycloak 26.8 with experimental `cimd,resource-indicators`, Phoenix; `--profile full` adds the apps), realm export, DB init | Docker Compose |
| `e2e/` | Playwright smoke (login → upload → ask → citation), runs against :4200 | Playwright |
| `data/sample-docs/` | Demo + eval corpus; `domains.json` = file → domain tags; repo docs are frozen snapshots | — |
| `evals/` | Datasets (`datasets/*.jsonl`, frozen per version), fixture MCP server + scenarios (`fixtures/`); `runs/` git-ignored | — |
| `scripts/` | `dev.mjs` (runs apps), `stack.mjs` (compose wrapper), `mem.mjs` (memory budget) | Node |
| `docs/adr/` | Architecture Decision Records — copy `template.md`, next free number, add to the index | — |
| `docs/setup/` | `installation.md` (toolchain), `startup.md` (URLs, seed users, troubleshooting) | — |
| `plan.md` | Phase 1 source of truth: decisions D1–D26, contracts §7, milestones §8, target layout §6 | — |
| `plan-phase-2.md` | Phase 2 source of truth: decisions D27–D49, contracts §7, milestones M2.0–M2.8 | — |
| `plan-phase-3.md` | Phase 3 source of truth: decisions D50–D75, contracts §7, milestones M3a.0–M3a.7 (the rest re-planned) | — |
| `plan-daily-use.md` | **What's next.** Phase 3c "Daily use": decisions D121–D126, milestones M3c.0–M3c.5, parked list | — |
| `plan-phase-4/5/6.md`, `roadmap-phases-3-6.md` | Parked (Kubernetes, Azure, MLOps). Don't build from them | — |
| `architechture.md` | Cross-phase decisions by ID (REPO-*, DEV-* …). Filename is misspelled; keep it | — |
| `_meta/ai-theory/` | Study notes, not product docs. Ignore unless asked | — |

Request path: browser → NestJS `:3000` (JWT `aud=kb-api`) → AI service `:8000` (the user's token exchanged
for `aud=kb-ai`; client credentials for system calls) → own MCP server `/mcp` (exchanged again by `kb-ai`,
`aud=http://localhost:8000/mcp`, ADR-0009). Never expose the AI service to the browser; never put AI logic in
NestJS (ADR-0002).

## Commands

Run everything from the repo root. Root `package.json` scripts are the entry points, Python included.

```bash
pnpm install && uv sync --directory apps/ai-service   # setup
pnpm stack:up                                         # infra, waits until healthy
pnpm stack:up:full                                    # infra + apps as containers (Mode B; stop pnpm dev first)
pnpm dev [web|api|ai …]                               # apps with hot reload; loads .env
pnpm lint            # angular-eslint · oxlint · prettier --check · ruff · pyright
pnpm test            # all tests
pnpm build           # web + api
pnpm format          # prettier + ruff fix
pnpm contracts:generate                   # after changing any route or SSE model; commit packages/contracts (CI checks drift)
pnpm kb:backfill-originals                # store originals of pre-M3a.1 documents (data/sample-docs/, by SHA-256)
pnpm kb:reindex [--force --reason "…"]    # rebuild kb_current from originals behind the eval gate; --rollback; needs `pnpm dev ai`
pnpm e2e                                  # Playwright smoke; needs a running stack, LLM_PROVIDER=fake
pnpm stack:backup                         # pg_dumpall into backups/ (git-ignored); run before anything destructive
pnpm --filter @fs100/api db:generate      # Drizzle migration after editing apps/api/src/db/schema.ts
```

Fast feedback — run only what you touched:

```bash
pnpm --filter @fs100/api exec vitest run src/app.controller.spec.ts
pnpm --filter @fs100/api test:e2e                      # test/*.e2e-spec.ts
pnpm --filter @fs100/web test --include src/app/app.spec.ts
uv run --directory apps/ai-service pytest tests/test_health.py::test_healthz_reports_ok
pnpm --filter @fs100/api lint   |   pnpm --filter @fs100/web lint   |   pnpm lint:ai
```

Generators: `pnpm --filter @fs100/web ng generate component features/x/x`,
`pnpm --filter @fs100/api exec nest generate module x`. Python deps: `uv add [--dev] <pkg>` in
`apps/ai-service`. Never install CLIs globally.

**Done means:** `pnpm lint && pnpm test` pass (that is what CI runs; also `pnpm build` for web/api changes).

## Conventions and gotchas

- **NestJS is ESM:** relative imports need the `.js` suffix (`./app.service.js`). Routes get the `/api`
  prefix via `app.setup.ts`; probes (`/healthz`) are excluded. Use `configureApp()` in e2e tests.
- **Angular:** new-style file names without suffixes (`home.ts`, `home.html`, not `home.component.ts`);
  selector prefix `app-`; features under `src/app/features/<name>/`; lazy routes via `loadComponent`;
  template a11y rules are lint errors. In specs, flush every `httpResource` request (also reloads after a
  run) — an open one makes `fixture.whenStable()` time out without a message.
- **Python:** pyright runs in **strict** mode — fully type everything. App factory `create_app(settings)` in
  `main.py`; tests build their own app with `TestClient(create_app(Settings()))`. Config only through
  `core/settings.py` (`Settings` fields map to env vars case-insensitively).
- **Style:** Prettier (100 cols, single quotes, trailing commas) for TS/HTML/SCSS/JSON/YAML; ruff (100 cols)
  for Python. Markdown is hand-formatted and not touched by Prettier.
- **Shared versions** (`typescript`, `vitest`, `prettier`, `@types/node`) live in the `catalog:` of
  `pnpm-workspace.yaml`. Dependency build scripts are blocked unless listed under `allowBuilds` (plan.md
  still says `onlyBuiltDependencies` — the code is right).
- **pnpm 12 holds back fresh releases.** Prefer a slightly older version over adding a
  `minimumReleaseAgeExclude` entry.
- **Env:** single root `.env` (from `.env.example`). Only `pnpm dev` and `pnpm stack:*` load it — a single
  app started on its own does not. New variables go into `.env.example` (dev-only placeholder) and plan.md
  Appendix A, and into the app's `environment:` list in `infra/compose/docker-compose.yml` (Mode B passes
  only listed variables).
- **Images:** all three Dockerfiles build with the repo root as context; `.dockerignore` is an allow-list,
  so a new top-level folder an image needs must be added there. The AI service runs on `python:*-slim` without
  system libraries: Python dependencies must bundle theirs (`psycopg[binary]`, `opencv-python-headless`).
- **Infra state:** realm JSON and `init.sql` only apply to empty volumes. For a realm change, recreate only the
  `keycloak` database (`docs/setup/startup.md` §7). The seed users' `id`s are pinned in `realm-kb.json`, so the
  data keeps its owners; keep them pinned. `init.sql` needs `pnpm stack:reset && pnpm stack:up`, which wipes all
  local data; ask first. Use `localhost`, not `127.0.0.1`, for anything Keycloak-related.
- **API DB:** Drizzle; migrations in `apps/api/drizzle/` run on API boot. API tests use `API_DATABASE_URL=:memory:`
  (in-process PGlite) and need no Docker; `test/support.ts` builds the app with test JWT keys.
- **Contracts:** Nest's OpenAPI comes from Zod schemas (`@Body({ schema })`, `@ApiOkResponse({ standardSchema })`;
  `.meta({ id })` names a component). Relayed bodies (`/api/chat`, `/api/search`) are validated only by the AI
  service; their types live in `@fs100/contracts/ai-service`. `contracts:generate` boots the API from the repo
  root with logging off, so a cwd-relative file path in API config makes it exit 1 without a message.
- **AI service tests** never download models or need Docker: they fake fastembed (`tests/support.py`; BM25 and the cross-encoder via an
  autouse fixture in `conftest.py`, which also sends PDFs to pypdf instead of Docling) and use `support.OFFLINE` (Qdrant and the `ai` database in-process, no worker); `drain(client)` runs the queued
  jobs, so an upload is `ingest(client, …)`, not a bare POST. The golden set's labels are checked against `data/sample-docs/` by
  `tests/test_evals.py`; `evals/datasets/retrieval_v1.jsonl` is frozen — changes go into a new version.
- **Sparse vectors are computed in the AI service** (fastembed BM25), never with Qdrant's `models.Document` inference:
  in-process Qdrant (tests, `kb-eval`, CI gate) tokenizes differently from the server (ADR-0016).
- **torch** comes from PyTorch's CPU index via `tool.uv.sources` in `apps/ai-service/pyproject.toml`; uv applies
  sources only to direct dependencies, so `torch`/`torchvision` stay listed there (PyPI's Linux wheels pull ~3 GB of CUDA).
- **Cloud sessions without the PyTorch index:** `uv sync --directory apps/ai-service --no-install-package torch
  --no-install-package torchvision`, then prefix `uv run` scripts with `UV_NO_SYNC=1` (tests never need torch). If
  `ng` rejects the Node version, check web changes in `apps/web` with `pnpm exec ngc -p tsconfig.app.json --noEmit`
  and `pnpm exec eslint src`; `ng test` then runs only in CI.
- **Prompt caching at OpenRouter** (`gpt-6-luna`, M3a.6): a long shared prefix was cached only inside the
  system message (91–98 %), never as a user message (0 %); check `Usage.cached_tokens` before relying on it.
- **LLM-written index content is stored and reused** (contexts in `ai.chunk_contexts`, keyed by model + messages):
  regenerated at re-index it moves the gate by noise alone (M3a.6: −0.04 nDCG@10 between two identical builds).
- **No paid LLM calls in tests or CI** — use `LLM_PROVIDER=fake`. No agent frameworks (LangChain etc.)
  through Phase 2 (D11). No AGPL deps (repo is MIT; e.g. no PyMuPDF).
- **Never commit secrets.** Only public or self-written documents go into the corpus (D25).
- **Git:** trunk-based, short-lived branches, Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`,
  `refactor:`, `test:`, `ci:`). Significant decisions get an ADR in the same PR.
- **Keep docs in sync:** when you change commands, ports, env vars or layout, update README.md and
  `docs/setup/*` in the same change.

## LAZY RULES
You are a lazy senior developer. The best code is the code never written. You solve the whole problem with the least new code. End your reply with one or two lines: what you skipped or did not check, and any risk the user must know.

## Before you write

Read the task and the code it touches. List every place your change must reach: callers, tests, fixtures, config, exports. Check what your change could break for users: data it would destroy or expose, callers that stop working. That is scope. Extra features are not.

## The smallest complete change

Take the first option that fully works:

1. Does it need to exist? Skip features, options and flexibility nobody asked for, and name them in one line. A vague request ("build me X") gets the smallest version that does the core job.
2. Already in this codebase (a helper, component, service, pattern)? Use it the way the surrounding code does.
3. Standard library or a platform feature? Use it, unless the project has its own. A house component beats a native widget.
4. An installed dependency? Use it. Never add a dependency for a few lines.
5. Can it be one line a reader gets at a glance? One line.
6. Otherwise: the minimum code that works.

- Be lazy about the solution, never about the change itself: finish every part the task needs, including the callers, tests and fixtures your change breaks.
- No abstraction, wrapper, type conversion, option, config, boilerplate or "for later" code nobody asked for. Keep values in the form the platform already gives you. Deletion beats addition. Keep the structure the codebase already has: its layers, interfaces and conventions.
- The shortest working diff wins, once you know everything it must touch. A one-liner that needs decoding is not short.
- Comment only the why the code cannot show, in one line.
- Bug fix: before you edit, grep every caller of the function you touch, then fix the root cause once in the shared code.
- Code you move or merge keeps its error handling and validation.
- Between options of equal size, take the one that is correct on edge cases.
- Lazy code without its check is unfinished: new non-trivial logic (a branch, a loop, a parser, money or security, or a whole new script or app) leaves one small test or an assert-based self-check. Trivial changes need none.
- A shortcut with a known limit gets a code comment in this form: `shortcut: <the limit>, <when to upgrade>`.

Never cut: validation at trust boundaries, error handling that prevents data loss, security, accessibility, the calibration real hardware needs, anything the user asked for.

## Applied Learnings

Rules learned from user feedback. Newest last. Format: `- <rule> — <why, one clause>`.

- Next to any setting that only applies on first start (Docker volumes, realm import), say so where it is edited and name the reset command — users edit `.env`, restart, and expect it to apply.
- Before telling the user a variable is missing from their `.env`, grep with `^\s*NAME=` — indented lines still load (uv and Node), so `^NAME=` reports false gaps.
- Call a milestone done only after its demo step ran on the user's running stack, not only in tests or on a throwaway stack — M2.8 was "done" while the live Keycloak lacked its features.
