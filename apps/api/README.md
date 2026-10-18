# @fs100/api

NestJS 12 product API / BFF (ESM, Vitest, oxlint): auth, RBAC, document metadata and the SSE relay to the AI
service (plan.md D3). Only this service and the web app are browser-facing. See the [root README](../../README.md)
and the [startup guide](../../docs/setup/startup.md).

| Command (from the repo root)          | What it does                                             |
| ------------------------------------- | -------------------------------------------------------- |
| `pnpm --filter @fs100/api start:dev`  | watch mode on http://localhost:3000 (`API_PORT`)         |
| `pnpm --filter @fs100/api test`       | unit (`src/**/*.spec.ts`) + HTTP e2e (`test/`) with Vitest |
| `pnpm --filter @fs100/api lint`       | oxlint (type-aware)                                      |
| `pnpm --filter @fs100/api build`      | compile into `dist/`                                     |
| `pnpm --filter @fs100/api db:generate` | new Drizzle migration in `drizzle/` after editing `src/db/schema.ts` |

Endpoints (plan.md §7.2; OpenAPI in `packages/contracts/api.openapi.json`):

| Route | Role | Notes |
|---|---|---|
| `GET /healthz` · `GET /readyz` | public | readiness = Postgres reachable |
| `GET /api/me` | any | |
| `GET /api/documents` | viewer | all documents with status and domains |
| `POST /api/documents` | editor | multipart `file` + `domains`; 202, ingested in the background; 409 duplicate, 413 > `UPLOAD_MAX_MB`, 415 not PDF/MD/TXT |
| `DELETE /api/documents/:id` | editor (own) / admin | vectors first, then the row; 409 while ingesting |
| `POST /api/chat` | viewer | SSE relay of `/v1/chat`, events unchanged; `CHAT_THROTTLE_PER_MIN` per user |
| `POST /api/search` | viewer | relay of `/v1/search` |
| `GET /api/status` | admin | `api`, `db`, `aiService`, `qdrant` |

Every route needs a Keycloak access token with `aud=kb-api` unless marked `@Public()`; restrict with
`@Roles(...)` (`src/auth/auth.guard.ts`). Errors are `application/problem+json` (`src/common/problem.filter.ts`).
Request bodies are validated with Zod via `@Body({ schema })`; relayed bodies are validated by the AI service,
whose types come from `@fs100/contracts/ai-service`. Config is validated with Zod in `src/config.ts`.

The API applies Drizzle migrations from `drizzle/` on boot. Tests (and `pnpm contracts:generate`) run with
`API_DATABASE_URL=:memory:`, an in-process PGlite, so they need no Docker. Generate code with the local CLI,
e.g. `pnpm --filter @fs100/api exec nest generate module x`.
