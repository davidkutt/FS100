# Startup guide — run FS100 locally

Prerequisite: the toolchain from the **[installation guide](installation.md)** (Node 24, pnpm via Corepack,
uv, Docker).

FS100 uses two development modes (plan.md D18):

- **Mode A (daily, available now):** infrastructure in Docker Compose — Postgres, Qdrant, Keycloak,
  Phoenix — and the three apps running **natively** with hot reload.
- **Mode B (`--profile full`, from M1.6):** everything containerised, for demos, e2e and image tests.

---

## 1. First start (≈ 5 minutes, most of it image downloads)

```bash
git clone https://github.com/davidkutt/FS100.git && cd FS100

corepack enable pnpm                      # once per machine
pnpm install                              # web + api
uv sync --directory apps/ai-service       # ai-service (creates apps/ai-service/.venv)

cp .env.example .env                      # dev-only defaults; edit later (e.g. LLM_API_KEY in M1.3)

pnpm stack:up                             # Postgres, Qdrant, Keycloak, Phoenix — waits until all are healthy
pnpm dev                                  # web + api + ai-service with hot reload
```

Open **http://localhost:4200** — the landing page links to every running service.

`pnpm stack:up` uses `docker compose up --detach --wait`, so it returns only when every container's
health check passes (≈ 1 minute; Keycloak is the slowest). `pnpm dev` runs in the foreground; stop it
with `Ctrl+C`.

## 2. Daily routine

```bash
pnpm stack:up       # start infra (no-op if it is already running)
pnpm dev            # start the apps
# … work …
Ctrl+C              # stop the apps
pnpm stack:down     # stop infra; data is kept in Docker volumes
```

Start only some apps — useful when you debug one of them in your IDE:

```bash
pnpm dev api ai     # names: web, api, ai
```

Or each app on its own (from the repo root):

```bash
pnpm --filter @fs100/web start                                                   # http://localhost:4200
pnpm --filter @fs100/api start:dev                                               # http://localhost:3000
uv run --directory apps/ai-service uvicorn ai_service.main:app --reload --port 8000
```

> Running an app on its own does **not** load `.env` (only `pnpm dev` and `pnpm stack:*` do). Export the
> variables you need, or prefix with `node --env-file=.env …`.

## 3. What runs where

Ports are fixed and identical in Mode A and Mode B (plan.md §5). Everything binds to `localhost` only.

| Service | URL | Login (dev only) |
|---|---|---|
| Web (Angular) | http://localhost:4200 | — (Keycloak login arrives in M1.1) |
| API (NestJS) | http://localhost:3000/api/hello · http://localhost:3000/healthz | — |
| AI service (FastAPI) | http://localhost:8000 · Swagger UI: http://localhost:8000/docs | — |
| Keycloak admin console | http://localhost:8080/admin/ | `admin` / `dev-only-change-me` (`KEYCLOAK_ADMIN*`) |
| Keycloak account console (realm `kb`) | http://localhost:8080/realms/kb/account | seed users below |
| Qdrant dashboard | http://localhost:6333/dashboard | — |
| Phoenix (LLM traces) | http://localhost:6006 | — |
| Postgres | `postgresql://postgres:dev-only-change-me@localhost:5432/app` | also DB `keycloak` |

**Seed users in realm `kb`** (from `infra/keycloak/realm-kb.json`, plan.md §7.7). Password = username,
dev only:

| User | Password | Realm roles (effective) |
|---|---|---|
| `alice` | `alice` | admin → editor → viewer |
| `bob` | `bob` | editor → viewer |
| `carol` | `carol` | viewer |

**Clients:** `kb-web` (public, PKCE S256, redirect `http://localhost:4200/*`, access tokens carry
`aud=kb-api`), `kb-api` (confidential, secret `dev-only-change-me`, service account with `aud=kb-ai`),
`kb-ai` (audience only, no flows).

## 4. Check that everything works

```bash
pnpm stack:ps                                   # all four containers "(healthy)"

curl -s localhost:3000/api/hello                # {"message":"Hello from the FS100 API"}
curl -s localhost:3000/healthz                  # {"status":"ok"}
curl -s localhost:8000/                         # {"service":"ai-service","version":"0.1.0","docs":"/docs"}
curl -s localhost:8000/healthz                  # {"status":"ok"}
curl -s localhost:6333/readyz                   # all shards are ready
curl -si localhost:3000/api/hello | grep -i x-request-id   # every response carries a request id

# Keycloak: service token of the API (client credentials). Decode the JWT, e.g. on jwt.io —
# it must contain "iss": "http://localhost:8080/realms/kb" and "aud": "kb-ai".
curl -s -d grant_type=client_credentials -d client_id=kb-api -d client_secret=dev-only-change-me \
  http://localhost:8080/realms/kb/protocol/openid-connect/token

# Postgres: both databases exist
docker exec fs100-postgres-1 psql -U postgres -tAc "select datname from pg_database where datname in ('app','keycloak')"
```

In the browser: log in as `bob` / `bob` at http://localhost:8080/realms/kb/account to see the user side of
the realm.

## 5. Quality checks

Run them before every push — they are also what CI runs.

```bash
pnpm lint           # angular-eslint (web) · oxlint (api) · prettier --check · ruff + pyright (ai-service)
pnpm test           # Vitest (web, api unit + HTTP) · pytest (ai-service)
pnpm build          # production builds of web and api
pnpm format         # auto-fix formatting (prettier + ruff)
```

Commits follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`,
`chore:`, `refactor:`, `test:`, `ci:` …), trunk-based on `main`.

## 6. Environment variables

- The single source is the repo-root **`.env`** (git-ignored), created from `.env.example`.
- `pnpm dev` starts `node --env-file-if-exists=.env scripts/dev.mjs`; all three apps inherit the
  variables. Variables already set in your shell **win** over `.env`.
- `pnpm stack:*` passes `.env` to Docker Compose (`--env-file`). Without a `.env`, the defaults in the
  compose file apply — they match `.env.example`.
- Every value in `.env.example` is a dev-only placeholder. Real secrets (the OpenRouter key from M1.3)
  go into your local `.env` only — never into git.
- The web app reads its browser-facing settings at runtime from `/config.json` — locally
  `apps/web/public/config.json` (Keycloak URL/realm/client, API base URL, Phoenix URL; an empty
  `phoenixUrl` hides Phoenix links). In containers nginx renders it from the `WEB_*` variables (M1.6).
- The API validates its environment at boot and refuses to start with a readable error if a value is
  invalid (e.g. a `CORS_ORIGINS` entry with a path).

### Logs and request ids

API and AI service write **one JSON object per line** to stdout; `LOG_LEVEL` (`info` by default) applies to
both. Each request gets an `x-request-id` — the caller's if it is safe, otherwise a new UUID — which is
echoed in the response and included in the request's log lines (`req.id` in the API, `request_id` in the
AI service). Authorization and cookie headers are redacted, and `/healthz` probes are not logged. To
follow one request, search the `pnpm dev` output for its id.

## 7. Managing the infrastructure

| Command | Effect |
|---|---|
| `pnpm stack:up` | Create/start all infra containers, wait until healthy |
| `pnpm stack:ps` | Container status and health |
| `pnpm stack:logs` / `pnpm stack:logs keycloak` | Follow logs (all services or one) |
| `pnpm stack:down` | Stop and remove containers; **keeps** data volumes |
| `pnpm stack:reset` | Stop and **delete all local data** (Postgres incl. Keycloak, Qdrant, Phoenix) |

`scripts/stack.mjs` forwards any extra arguments to `docker compose`, e.g.
`node scripts/stack.mjs restart keycloak`.

### Changing the Keycloak realm

Keycloak imports `infra/keycloak/realm-kb.json` **only if the realm does not exist yet**. After editing the
file, recreate the Keycloak state:

```bash
pnpm stack:reset && pnpm stack:up     # wipes ALL local data (also Qdrant and Phoenix)
```

### Re-exporting the realm after changes in the admin console

```bash
docker exec fs100-keycloak-1 /opt/keycloak/bin/kc.sh export \
  --realm kb --users same_file --file /tmp/realm-kb.json --http-management-port 9001
docker cp fs100-keycloak-1:/tmp/realm-kb.json infra/keycloak/realm-kb.json
git diff infra/keycloak/realm-kb.json
```

`--http-management-port 9001` avoids a clash with the running server's management port. The export is
much more verbose than the hand-written file (generated ids, defaults, **hashed seed-user passwords**) —
review the diff, keep it dev-only, and never export a realm that contains real users or secrets.

### Changing `infra/postgres/init.sql`

The script only runs on an **empty** Postgres volume: `pnpm stack:reset && pnpm stack:up`.

## 8. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `pnpm stack:up` fails: `port is already allocated` | Another process uses 5432/6333/6334/8080/6006/4317 (often a native Postgres). Find it: `lsof -nP -iTCP:5432 -sTCP:LISTEN`; stop it, or stop the other Compose project |
| `pnpm stack:up` times out on Keycloak | First start imports the realm and builds its Quarkus image: wait, then `pnpm stack:logs keycloak`. Low Docker memory is the usual root cause |
| Realm / users don't match the JSON | The realm already existed — see [Changing the Keycloak realm](#changing-the-keycloak-realm) |
| `pnpm dev`: `[ai] … uv: not found` | Install uv ([installation guide](installation.md#24-uv-and-python-313)), then `uv sync --directory apps/ai-service` |
| `pnpm dev`: port 4200/3000/8000 in use | An old dev server is still running: `lsof -nP -iTCP:4200 -sTCP:LISTEN` and kill it |
| Angular shows stale output | `rm -rf apps/web/.angular` and restart |
| Login page: "Cookie not found" | Use `http://localhost:…`, not `127.0.0.1` — cookies and redirect URIs are bound to `localhost` |
| Want a clean slate | `pnpm stack:reset`, `rm -rf node_modules apps/*/node_modules apps/ai-service/.venv`, then the steps in §1 |

## 9. What's next

The base setup covers milestone **M1.0** plus the local infra of M1.1. Next steps, in plan order: auth
walking skeleton (M1.1), ingestion + retrieval + eval harness (M1.2), grounded chat (M1.3), documents +
relays (M1.4), UI (M1.5), containers + CI + e2e (M1.6). `pnpm eval:retrieval` and
`pnpm contracts:generate` exist as placeholders and fail with a pointer to their milestone until then.
