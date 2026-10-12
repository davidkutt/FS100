# @fs100/web

Angular 22 frontend (standalone components, signals, Bootstrap 5.3 via SCSS). See the [root README](../../README.md)
and the [startup guide](../../docs/setup/startup.md).

| Command (from the repo root)         | What it does                                  |
| ------------------------------------ | --------------------------------------------- |
| `pnpm --filter @fs100/web start`     | dev server on http://localhost:4200           |
| `pnpm --filter @fs100/web test`      | unit tests (Vitest via the Angular CLI)       |
| `pnpm --filter @fs100/web lint`      | ESLint (angular-eslint, incl. template a11y)  |
| `pnpm --filter @fs100/web build`     | production build into `dist/`                 |

Generate code with the local CLI, e.g. `pnpm --filter @fs100/web ng generate component features/chat/chat`.
