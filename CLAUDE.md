# CLAUDE.md

Guidance for Claude Code sessions in this repo. Humans: start with [README.md](README.md).

## Project

FS100 — a RAG/agent assistant for the "Dev of the future". **[plan.md](plan.md) is the source of truth**
(decisions D1–D26, contracts §7, milestones §8); [docs/architecture.md](docs/architecture.md) is the living
decision log across all phases; ADRs in [docs/adr/](docs/adr/README.md) record decisions and spike results.
Work milestone by milestone, keep scope to the current one, and update the plan's checkboxes or an ADR when a
decision changes.

- `apps/web` — Angular 22 (standalone, signals, zoneless), Bootstrap 5.3 via SCSS, Vitest, angular-eslint
- `apps/api` — NestJS 12, **ESM** (relative imports need a `.js` suffix), Vitest + supertest, oxlint
- `apps/ai-service` — FastAPI, Python 3.13, uv; ruff, pyright **strict**, pytest. All AI code lives here (ADR-0002)
- `infra/` — Compose (Postgres, Qdrant, Keycloak realm `kb`, Phoenix), `realm-kb.json`, `init.sql`

## Commands (repo root)

```bash
pnpm lint            # angular-eslint · oxlint · prettier --check · ruff · pyright
pnpm test            # Vitest (web, api unit + e2e) · pytest
pnpm build           # web + api
pnpm format          # prettier --write + ruff format/fix
pnpm dev [web|api|ai]   # native dev servers, loads .env
pnpm stack:up | stack:down | stack:reset   # Docker infra (needs a running Docker daemon)
```

Single targets: `pnpm --filter @fs100/api exec vitest run <file>`,
`pnpm --filter @fs100/web exec ng test --watch=false --include <file>`,
`uv run --directory apps/ai-service pytest <path>::<test>`.

## Environment

- Node **24** (`.nvmrc`) and pnpm **12.11.2** via Corepack. Angular 22 refuses Node < 22.22.3.
  In cloud sessions `.claude/hooks/session-start.sh` selects Node 24 via nvm and installs all deps.
- pnpm 12: dependency build scripts need an `allowBuilds` entry (`pnpm approve-builds`); versions
  published within the last day are held back — prefer a slightly older version over adding
  `minimumReleaseAgeExclude` entries. Shared versions go into the `catalog:` in `pnpm-workspace.yaml`.
- Python deps: `uv add [--dev] <pkg>` inside `apps/ai-service`; never `pip install`.
- Cloud containers: start Docker with `sudo dockerd &` if needed; `quay.io` may be blocked by the egress
  proxy — pull `keycloak/keycloak:<tag>` from Docker Hub and retag it as `quay.io/keycloak/keycloak:<tag>`.

## Conventions

- Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `ci:` …); trunk-based on `main`.
- Run `pnpm lint && pnpm test` before committing; CI (`.github/workflows/ci.yml`) runs the same.
- Validation: Zod via Nest's `@Body({ schema })` + `StandardSchemaValidationPipe` (api), Pydantic v2 (ai-service).
- Tests never call a paid LLM (`LLM_PROVIDER=fake`, D20). No secrets in git — `.env` is local,
  `.env.example` holds dev-only placeholders.
- Keep `infra/keycloak/realm-kb.json` and the port map (plan.md §5) stable: redirect URIs depend on them.
- Markdown is hand-formatted (excluded from prettier); match the style of the surrounding docs.
