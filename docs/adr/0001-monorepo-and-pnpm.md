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

| Spike | Result |
|---|---|
| Angular default test runner | **Vitest** (5.x) is the default in Angular 22 (`@angular/build:unit-test`, jsdom). Adopted. |
| Nest 12 + Vitest | Nest 12 scaffolds Vitest + oxlint and ESM. DI/decorators work under Vitest 5 without SWC. Adopted. |
| TypeScript line | Angular 22 requires TypeScript `>=6.0 <6.1`; Nest 12 builds with it. Catalog pins `~6.0.3`. TS 7 (native) waits for Angular support. |
| `keycloak-angular` with Angular 22 | `keycloak-angular@22` + `keycloak-js@26` work with Angular 22 (zoneless): `provideKeycloak`, `customBearerTokenInterceptor`. Adopted in M1.1. |
| Zod via Nest 12 Standard Schema | **Open** — M1.1 uses Zod for config only (no request bodies yet); spike with the first validated endpoint in M1.4 (fallback `class-validator`). |
| Drizzle with Nest 12 ESM | **Open** — spike with the `documents` schema in M1.1/M1.4. |
