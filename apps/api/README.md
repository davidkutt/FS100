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

Endpoints today: `GET /healthz` (public), `GET /api/me` (any role), `GET /api/status` (admin). Every route
needs a Keycloak access token with `aud=kb-api` unless marked `@Public()`; restrict with `@Roles(...)`
(`src/auth/auth.guard.ts`). Config is validated with Zod in `src/config.ts`. Generate code with the local CLI, e.g.
`pnpm --filter @fs100/api exec nest generate module documents`.
