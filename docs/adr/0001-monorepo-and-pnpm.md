# ADR-0001: Monorepo with pnpm workspaces, uv for Python

- **Status:** Accepted
- **Date:** 2026-10-12
- **Plan reference:** D1, D2, D19, D20

## Context

FS100 consists of three apps in two languages — Angular (`apps/web`), NestJS (`apps/api`) and a FastAPI
AI service (`apps/ai-service`) — plus shared infrastructure, contracts, evals and docs. Changes often cut
across all of them (an SSE event field touches Pydantic, Nest and Angular), and one developer works on
everything.

## Decision

- **One repository** for all apps, infra, evals and docs.
- **pnpm workspaces** for the Node apps (`apps/web`, `apps/api`), version pinned through
  `package.json#packageManager` (`pnpm@12.11.2`, installed by Corepack).
- **Catalogs** in `pnpm-workspace.yaml` for versions shared across apps (`typescript`, `vitest`,
  `prettier`, `@types/node`).
- **Build scripts are an allow-list** (`allowBuilds` in `pnpm-workspace.yaml`; pnpm ≥ 11 replaced
  `onlyBuiltDependencies` with this map). Only `esbuild` runs its install script; `@parcel/watcher`,
  `lmdb` and `msgpackr-extract` are denied because they ship prebuilt binaries.
- **uv** manages the AI service: `pyproject.toml` + `uv.lock`, Python 3.13 from `.python-version`.
- **Root `package.json` scripts are the task entry points** for everything, including Python and Docker:
  `dev`, `lint`, `test`, `build`, `format`, `stack:*`, `eval:retrieval`, `contracts:generate`.
  Placeholders fail loudly until their milestone implements them.
- **Each app keeps its framework's default tooling:** angular-eslint + Vitest (web), oxlint + Vitest
  (api, Nest 12 scaffold defaults), ruff + pyright + pytest (ai-service). Prettier formats all
  TypeScript/HTML/SCSS/JSON/YAML from the root config; Markdown stays hand-formatted.
- No Nx/Turborepo: two Node apps do not justify a build orchestrator.

## Alternatives considered

- **npm workspaces** — works, but hoisting allows phantom dependencies between apps; slower installs.
- **Yarn PnP** — strictness without `node_modules`, but friction with Angular/Nest tooling.
- **Bun** — a runtime bet unrelated to the project's learning goals.
- **Nx / Turborepo** — task caching and graphs are overkill at this size; revisit if CI time hurts.
- **One linter for both Node apps** — oxlint lacks Angular template rules; ESLint for Nest would mean
  replacing the scaffold default without a gain.

## Consequences

- One `pnpm install` + one `uv sync` set up the whole repo; `pnpm --filter` targets single apps.
- Strict `node_modules` catch undeclared dependencies early.
- pnpm 12 holds back freshly published versions (minimum release age). Pinning a version that is only
  hours old makes pnpm add a `minimumReleaseAgeExclude` entry — prefer a slightly older version.
- `pnpm deploy` will produce slim per-app images in M1.6.
- Contributors need Node, Corepack, uv and Docker — documented in `docs/setup/installation.md`.

## Compatibility spikes (M1.0)

All spikes ran on 2026-10-13 in throwaway code against the Compose infra (Postgres 17.11,
Keycloak 26.7.5); only the outcome is recorded here. All passed, so no fallback is needed.

| Spike | Result |
|---|---|
| Angular default test runner | ✅ **Vitest** (5.x) is the default in Angular 22 (`@angular/build:unit-test`, jsdom). Adopted. |
| Nest 12 + Vitest | ✅ Nest 12 scaffolds Vitest + oxlint and ESM. DI/decorators work under Vitest 5 without SWC. Adopted. |
| TypeScript line | ✅ Angular 22 requires TypeScript `>=6.0 <6.1`; Nest 12 builds with it. Catalog pins `~6.0.3`. TS 7 (native) waits for Angular support. |
| Zod via Nest 12 Standard Schema | ✅ `zod@4.6` works with Nest's built-in Standard Schema support: `@Body({ schema: CreateX })` plus a global `new StandardSchemaValidationPipe()`. Transforms and defaults are applied (`transform: true` is the default), unknown keys are stripped (`z.object`), failures return 400 with `path: message` entries. Also works under Vitest + supertest. **No `class-validator` needed.** |
| Drizzle with Nest 12 ESM | ✅ `drizzle-orm@0.45` + `pg@8.23` (`drizzle-orm/node-postgres`) as a global Nest provider; `drizzle-kit@0.31` reads an ESM `drizzle.config.ts`, `generate` emits readable SQL (incl. `text[]` with default), `migrate` applies it. Works with `nest build` → `node dist/main` and under Vitest. Stay on 0.45 until Drizzle 1.0 leaves beta. |
| `keycloak-angular` with Angular 22 | ✅ `keycloak-angular@22.0` + `keycloak-js@26.2` in a zoneless Angular 22 app: `provideKeycloak({ config, initOptions: { onLoad: 'login-required', pkceMethod: 'S256' } })`, `inject(Keycloak)` and `includeBearerTokenInterceptor` with a URL condition. A headless Chromium login as `bob` / `carol` reached the app with the right roles, and API calls carried `Authorization: Bearer …` with `aud=kb-api`. |

Follow-ups noted by the spikes (for M1.1/M1.4):

- Nest's default validation error body is not RFC 9457 — map it with the pipe's `exceptionFactory` or the
  global problem+json filter (M1.4).
- Decide per schema whether unknown keys are stripped (`z.object`, default) or rejected (`z.strictObject`).
- `drizzle-kit@0.31` pulls old `esbuild` versions via the deprecated `@esbuild-kit` loaders (dev-only;
  `esbuild` is already in `allowBuilds`).
- Set `checkLoginIframe: false` in `keycloak-js` init options (third-party cookie restrictions).
