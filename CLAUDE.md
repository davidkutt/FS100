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
3. **ALWAYS** follow the LAZY RULES section.
## What this is

FS100 is a RAG/agent assistant: upload domain-tagged documents, ask questions, get streamed answers with
citations, with every retrieval change measured by evals and every request traced. Built in six phases;
**Phase 1 is in progress** — M1.0 (repo, skeletons, local infra, CI) is done. No auth flow, ingestion or chat
yet. Check the milestone in [plan.md §8](plan.md#8-milestones-and-tasks) before building something: many
features are deliberately scheduled for later milestones.

The plan's working title `kb-agent` lives on in identifiers (realm `kb`, clients `kb-web`/`kb-api`/`kb-ai`,
Qdrant alias `kb_current`). Keep those names.

## Map

| Path | What | Stack |
|---|---|---|
| `apps/web` | Frontend, browser-facing | Angular 22 (standalone, signals, zoneless), Bootstrap 5.3 via SCSS, Vitest, angular-eslint |
| `apps/api` | Product API / BFF: auth, RBAC, document metadata, SSE relay. Browser-facing | NestJS 12 (ESM), Vitest + supertest, oxlint |
| `apps/ai-service` | **All AI code**: parse, chunk, embed, retrieve, prompt, LLM, evals, tracing. Internal only | FastAPI, Python 3.13 (uv), pydantic-settings, ruff, pyright strict, pytest |
| `infra/` | Compose (Postgres 17, Qdrant 1.18, Keycloak 26.7, Phoenix), realm export, DB init | Docker Compose |
| `scripts/` | `dev.mjs` (runs apps), `stack.mjs` (compose wrapper), `not-yet.mjs` (placeholder that fails) | Node |
| `docs/adr/` | Architecture Decision Records — copy `template.md`, next free number, add to the index | — |
| `docs/setup/` | `installation.md` (toolchain), `startup.md` (URLs, seed users, troubleshooting) | — |
| `plan.md` | Phase 1 source of truth: decisions D1–D26, contracts §7, milestones §8, target layout §6 | — |
| `architechture.md` | Cross-phase decisions by ID (REPO-*, DEV-* …). Filename is misspelled; keep it | — |
| `_meta/ai-theory/` | Study notes, not product docs. Ignore unless asked | — |

Request path: browser → NestJS `:3000` (JWT `aud=kb-api`) → AI service `:8000` (client-credentials JWT
`aud=kb-ai` + `user` context). Never expose the AI service to the browser; never put AI logic in NestJS
(ADR-0002).

## Commands

Run everything from the repo root. Root `package.json` scripts are the entry points, Python included.

```bash
pnpm install && uv sync --directory apps/ai-service   # setup
pnpm stack:up                                         # infra, waits until healthy
pnpm dev [web|api|ai …]                               # apps with hot reload; loads .env
pnpm lint            # angular-eslint · oxlint · prettier --check · ruff · pyright
pnpm test            # all tests
pnpm build           # web + api
pnpm format          # prettier + ruff fix
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
  template a11y rules are lint errors.
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
  Appendix A.
- **Infra state:** realm JSON and `init.sql` only apply to empty volumes → `pnpm stack:reset && pnpm stack:up`
  (wipes all local data; ask first). Use `localhost`, not `127.0.0.1`, for anything Keycloak-related.
- **Placeholders:** `pnpm eval:retrieval` (M1.2) and `pnpm contracts:generate` (M1.4) fail on purpose.
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

<!-- none yet -->
