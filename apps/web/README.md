# @fs100/web

Angular 22 frontend (standalone components, signals, Bootstrap 5.3 via SCSS). See the [root README](../../README.md)
and the [startup guide](../../docs/setup/startup.md).

| Command (from the repo root)         | What it does                                  |
| ------------------------------------ | --------------------------------------------- |
| `pnpm --filter @fs100/web start`     | dev server on http://localhost:4200           |
| `pnpm --filter @fs100/web test`      | unit tests (Vitest via the Angular CLI)       |
| `pnpm --filter @fs100/web lint`      | ESLint (angular-eslint, incl. template a11y)  |
| `pnpm --filter @fs100/web build`     | production build into `dist/`                 |

Runtime config comes from `/config.json` (dev values in `public/config.json`, plan.md D17), loaded before
bootstrap; an empty `phoenixUrl` hides the chat's trace links. Login is Keycloak Authorization Code + PKCE
via `keycloak-angular` (`login-required`); the bearer token is attached to requests to `apiBaseUrl/api/`
only. The chat streams with `fetch` instead (`core/sse.ts`) and adds the token itself.

Pages (`src/app/features/`): `home`, `chat` (SSE, citations → source panel, stop), `documents` (upload,
live status, delete), `inspector` (raw search hits vs. the score threshold). `roleGuard` checks the
route's `data.role`; the API enforces the same roles.

Generate code with the local CLI, e.g. `pnpm --filter @fs100/web ng generate component features/chat/chat`.
