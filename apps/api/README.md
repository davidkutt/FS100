# @grove/api

NestJS 12 product API / BFF (ESM, Vitest, oxlint): auth, RBAC, document metadata and the SSE relay to the AI
service (plan.md D3). Only this service and the web app are browser-facing. See the [root README](../../README.md)
and the [startup guide](../../docs/setup/startup.md).

| Command (from the repo root)          | What it does                                             |
| ------------------------------------- | -------------------------------------------------------- |
| `pnpm --filter @grove/api start:dev`  | watch mode on http://localhost:3000 (`API_PORT`)         |
| `pnpm --filter @grove/api test`       | unit (`src/**/*.spec.ts`) + HTTP e2e (`test/`) with Vitest |
| `pnpm --filter @grove/api lint`       | oxlint (type-aware)                                      |
| `pnpm --filter @grove/api build`      | compile into `dist/`                                     |
| `pnpm --filter @grove/api db:generate` | new Drizzle migration in `drizzle/` after editing `src/db/schema.ts` |

Endpoints (plan.md §7.2; OpenAPI in `packages/contracts/api.openapi.json`):

| Route | Role | Notes |
|---|---|---|
| `GET /healthz` · `GET /readyz` | public | readiness = Postgres reachable |
| `GET /api/me` | any | |
| `GET /api/documents` | viewer | all documents with status and domains; rows in work first take their job's state from the AI service (`GET /v1/jobs/{id}`) |
| `POST /api/documents` | editor | multipart `file` + `domains` + optional `topics` (`domain/topic` from `config/taxonomy.yaml`); 202, handed to the AI service's queue: status `pending → queued → parsing → embedding → ready \| failed`; 409 duplicate, 413 > `UPLOAD_MAX_MB`, 415 not PDF/MD/TXT |
| `PATCH /api/documents/:id` | editor (own) / admin | `{domains?, topics?}` → Qdrant payload update, no re-embedding; 409 until the ingest has ended |
| `DELETE /api/documents/:id` | editor (own) / admin | vectors and the stored original first (a `queued` job is cancelled), then the row; 409 while the job runs |
| `GET · POST /api/conversations` | viewer | own conversations, newest first · `{title?, modelId?}` |
| `GET · DELETE /api/conversations/:id` | owner (delete: also admin) | messages with `parts` (SSE v2 payloads by event name), gap signals and the caller's rating; others get 404 |
| `POST /api/conversations/:id/messages` | owner | `{text, modelId?, mode?, domains?}`; 429 `daily_cap_exceeded` once the caller's cost today reaches the cap → SSE v2 relay of `/v1/agent` with the last 20 messages as text; events are stored as the assistant message (a stop → `stopReason: cancelled`); `approval_required` is stored as a pending approval and relayed without `signedAction` |
| `GET /api/approvals?status=` | viewer | own approvals (admin: all), never with the signed action |
| `POST /api/approvals/:id` | requester | `{decision: approve\|reject, note?}` → SSE v2 continuation of the turn; 429 `daily_cap_exceeded` (checked first, the approval stays pending); role re-checked against `/v1/tools` (403 `tool_not_permitted`), 409 `approval_state_conflict` unless `pending`, 410 `approval_expired`; a stream that ends without the write's result → `unknown`, never retried (ADR-0008) |
| `GET /api/admin/audit` | admin | `?user&tool&outcome&from&to` (UTC days); newest 200 rows of the append-only `audit_log`: one per tool result, redacted args |
| `POST /api/messages/:id/feedback` | owner | `{rating: up\|down, comment?}`; a second rating replaces the first |
| `GET /api/me/usage` | any | `{capUsd, today, days}`: tokens, cost and turns per UTC day from the `usage` rows, last 30 days; the cap is the highest role's `DAILY_COST_CAP_USD_*` (D44) |
| `GET /api/admin/reindex` · `POST /api/admin/reindex` · `POST /api/admin/reindex/rollback` | admin | relays to the AI service's re-index (D55) with the user's token: alias target + latest runs with reports · `{reason, force}` → 202 `{jobId}` (force needs a reason) · alias back to the replaced collection; start and rollback are audited as `kb.reindex` / `kb.rollback` |
| `GET /api/admin/usage` | admin | `?user&from&to` (UTC days); cost and tokens per user and day, newest 200 rows |
| `GET /api/models` · `GET /api/tools` | viewer | relays of `/v1/models`, `/v1/tools`, cut to the caller's role |
| `GET /api/taxonomy` | viewer | `config/taxonomy.yaml` (`TAXONOMY_CONFIG`), validated at boot |
| `POST /api/chat` | viewer | SSE relay of `/v1/chat`, events unchanged; `CHAT_THROTTLE_PER_MIN` per user, shared with conversation messages; the `done` usage counts towards the daily cap (429 once reached) |
| `POST /api/search` | viewer | relay of `/v1/search` |
| `GET /api/status` | admin | `api`, `db`, `aiService`, `qdrant` |
| `POST /internal/documents/from-url` | service account with the `kb-api` client role `ingest-on-behalf` (= `kb-ai`) | `{url, domains, onBehalfOf:{sub, name}}` for `kb.ingest_url`: fetches the URL (hosts in `INGEST_URL_ALLOWED_HOSTS`, no IP literals or private addresses, ≤ 3 redirects on the list, ≤ `UPLOAD_MAX_MB`), then stores it as the user's upload → 202 `{id, status}`; audited as `documents.from_url` with the service identity (trusted subsystem, D36) |

Every route needs a Keycloak access token with `aud=kb-api` unless marked `@Public()`; restrict with
`@Roles(...)` (realm roles) or `@ServiceRole(...)` (client roles of `kb-api`, `src/auth/auth.guard.ts`). Calls to
the AI service carry the user's token exchanged for `aud=kb-ai` (`chat`, `search`, agent turns; cached until 150 s
before expiry, a resume exchanges afresh) or the API's service token (ingest, labels, delete, catalog, status),
see `src/ai-client/ai-client.service.ts` and ADR-0009. Errors are `application/problem+json` (`src/common/problem.filter.ts`).
Request bodies are validated with Zod via `@Body({ schema })`; relayed bodies are validated by the AI service,
whose types come from `@grove/contracts/ai-service`. Config is validated with Zod in `src/config.ts`.

The API applies Drizzle migrations from `drizzle/` on boot. Tests (and `pnpm contracts:generate`) run with
`API_DATABASE_URL=:memory:`, an in-process PGlite, so they need no Docker. Generate code with the local CLI,
e.g. `pnpm --filter @grove/api exec nest generate module x`.
