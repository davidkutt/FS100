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

cp .env.example .env                      # dev-only defaults; then set LLM_API_KEY + LLM_MODEL, or LLM_PROVIDER=fake

pnpm stack:up                             # Postgres, Qdrant, Keycloak, Phoenix — waits until all are healthy
pnpm dev                                  # web + api + ai-service with hot reload
```

Open **http://localhost:4200** and log in as a seed user (below), e.g. `alice` / `alice` — the landing
page greets you with your roles, shows admins a status card and links to every running service. The
sidebar leads to **Chat**, **Documents** (upload needs `editor`) and the retrieval **Inspector**.

`pnpm stack:up` uses `docker compose up --detach --wait`, so it returns only when every container's
health check passes (≈ 1 minute; Keycloak is the slowest). `pnpm dev` runs in the foreground; stop it
with `Ctrl+C`.

On its **first** start the AI service downloads the embedding model (`EMBEDDING_MODEL`, ≈ 2.3 GB for the
default `BAAI/bge-m3`, [ADR-0004](../adr/0004-embedding-model-chunking-threshold.md)) into
`apps/ai-service/.cache/fastembed/`; it answers requests only after
that (`/readyz` turns 200). Later starts load the model from the cache in a few seconds.

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
| Web (Angular) | http://localhost:4200 | seed users below (Keycloak login, PKCE) |
| API (NestJS) | http://localhost:3000/healthz · `/readyz` · `/api/*` needs a user token (`/api/me`, `/api/documents`, `/api/chat`, `/api/search`, admin: `/api/status`) | — |
| AI service (FastAPI) | http://localhost:8000 · `/healthz`, `/readyz` · Swagger UI: http://localhost:8000/docs · `/v1/*` needs the API's service token | — |
| Keycloak admin console | http://localhost:8080/admin/ | `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD` from the first start (default `admin` / `dev-only-change-me`) |
| Keycloak account console (realm `kb`) | http://localhost:8080/realms/kb/account | seed users below |
| Qdrant dashboard | http://localhost:6333/dashboard | — |
| Phoenix (LLM traces) | http://localhost:6006 | — |
| Postgres | `postgresql://postgres:dev-only-change-me@localhost:5432/app` | also DB `keycloak` |

**Two separate logins.** The app (http://localhost:4200) signs you in with a user of realm **`kb`** — a seed
user below or one you registered. The `KEYCLOAK_ADMIN` account lives in realm **`master`** and only opens
the Keycloak admin console; it does not exist in realm `kb`, so the app login rejects it.

**Seed users in realm `kb`** (from `infra/keycloak/realm-kb.json`, plan.md §7.7). Password = username,
dev only:

| User | Password | Realm roles (effective) |
|---|---|---|
| `alice` | `alice` | admin → editor → viewer |
| `bob` | `bob` | editor → viewer |
| `carol` | `carol` | viewer |

**New users.** Click **Register** on the app's login page: the account gets the role `viewer`. To create
users or change roles as the Keycloak admin: http://localhost:8080/admin/ → realm selector **kb** →
**Users** → *Create new user* (then the **Credentials** tab → *Set password*, *Temporary* off) or open a user
→ **Role mapping** → *Assign role* → filter *Realm roles* → `editor` / `admin`. Role changes apply at the
next token refresh (≤ 5 min) or after logging out and in.

**Clients:** `kb-web` (public, PKCE S256, redirect `http://localhost:4200/*`, access tokens carry
`aud=kb-api`), `kb-api` (confidential, secret `dev-only-change-me`, service account with `aud=kb-ai`),
`kb-ai` (audience only, no flows).

## 4. Check that everything works

```bash
pnpm stack:ps                                   # all four containers "(healthy)"

curl -s localhost:3000/healthz                  # {"status":"ok"}
curl -s localhost:3000/readyz                   # {"status":"ok"} — Postgres reachable, migrations applied
curl -s localhost:3000/api/me                   # 401 — every /api route needs a user token
curl -s localhost:8000/                         # {"service":"ai-service","version":"0.1.0","docs":"/docs"}
curl -s localhost:8000/healthz                  # {"status":"ok"}
curl -s localhost:8000/readyz                   # {"status":"ok"} once the embedding model is loaded
curl -s localhost:6333/readyz                   # all shards are ready

# Keycloak: service token of the API (client credentials). Decode the JWT, e.g. on jwt.io —
# it must contain "iss": "http://localhost:8080/realms/kb" and "aud": "kb-ai".
curl -s -d grant_type=client_credentials -d client_id=kb-api -d client_secret=dev-only-change-me \
  http://localhost:8080/realms/kb/protocol/openid-connect/token

# AI service: /v1/* accepts only that service token (a user token for kb-api gets 401).
TOKEN=$(curl -s -d grant_type=client_credentials -d client_id=kb-api -d client_secret=dev-only-change-me \
  http://localhost:8080/realms/kb/protocol/openid-connect/token | sed -E 's/.*"access_token":"([^"]+)".*/\1/')
curl -s localhost:8000/v1/status -H "Authorization: Bearer $TOKEN"   # {"status":"ok"} + a "status" span in Phoenix

# AI service: ingest a document, search it, delete it (spans ingest/parse/chunk/embed/upsert/search in Phoenix)
DOC=$(uuidgen | tr A-Z a-z)
curl -s localhost:8000/v1/ingest -H "Authorization: Bearer $TOKEN" -F file=@data/sample-docs/slo-handbook.pdf \
  -F doc_id=$DOC -F owner_id=dev -F domains=sre        # {"doc_id":…,"chunk_count":3,"page_count":3,…}
curl -s localhost:8000/v1/search -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"query":"Was passiert, wenn das Fehlerbudget aufgebraucht ist?","top_k":3}'   # hits with page numbers
curl -N localhost:8000/v1/chat -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"messages":[{"role":"user","content":"Was passiert, wenn das Fehlerbudget aufgebraucht ist?"}],"user":{"sub":"dev","roles":["viewer"]}}'
  # streams event: sources → token … → done; Phoenix shows chat → search → embed and the LLM span (prompt, tokens)
curl -s -o /dev/null -w '%{http_code}\n' -X DELETE localhost:8000/v1/documents/$DOC -H "Authorization: Bearer $TOKEN"  # 204

# Postgres: both databases exist
docker exec fs100-postgres-1 psql -U postgres -tAc "select datname from pg_database where datname in ('app','keycloak')"
```

In the browser: log in at http://localhost:4200 as `alice` (admin: status card shows `api`, `db`,
`aiService` and `qdrant` = `ok`), then **Log out** and log in as `bob` / `carol` (no status card). The `status` span of
the card's AI-service call appears in Phoenix (http://localhost:6006, project `default`). Every response
carries an `x-request-id` header; the API and the AI service log it in their JSON log lines.

Then the demo path as `bob`: **Documents** → pick domains → drop files from `data/sample-docs/` → status
goes `pending → processing → ready`. **Chat** → ask a question → the answer streams with `[1]` citations;
select one to read the passage, **Trace in Phoenix** opens the request's trace. **Inspector** shows the
raw hits with scores and a dashed line at the score threshold. As `carol` (viewer) there are no upload
or delete controls. Chat calls the real LLM unless `LLM_PROVIDER=fake`.

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

### Changing credentials in `.env`

`POSTGRES_PASSWORD` and `KEYCLOAK_ADMIN*` are written into the Docker volumes on the **first** start and
ignored afterwards. `pnpm stack:down`, restarts and deleting images all keep the volumes — only
`pnpm stack:reset` (wipes all local data) makes the new values take effect:

```bash
pnpm stack:reset && pnpm stack:up
```

Keep `API_DATABASE_URL` in sync with `POSTGRES_*`. To keep your data instead, change the passwords where
they live: the Keycloak admin via the admin console (realm `master` → Users → `admin` → Credentials), and
Postgres with `docker exec fs100-postgres-1 psql -U postgres -c "ALTER USER postgres PASSWORD '<new>'"`
before the next `pnpm stack:up` (otherwise Keycloak can no longer connect to Postgres).

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
| App login says "Invalid username or password" for `admin` | `admin` is the Keycloak server admin (realm `master`). Log in to the app as `alice` / `bob` / `carol` or **Register** — see [§3](#3-what-runs-where) |
| New `KEYCLOAK_ADMIN_PASSWORD` / `POSTGRES_PASSWORD` not accepted | The volumes still hold the first-start values — see [Changing credentials in `.env`](#changing-credentials-in-env) |
| Keycloak unhealthy after changing `POSTGRES_PASSWORD` | Same cause: Postgres still has the old password. Revert `.env`, or reset / `ALTER USER` as described there |
| Everything is slow | Usually memory: Docker infra + embedding model + IDE + browser on 16 GB. Check `sysctl vm.swapusage`; use `EMBEDDING_MODEL=intfloat/multilingual-e5-small`, stop `phoenix` when not needed, give Docker less RAM. The first page load after `pnpm install` also pre-bundles dependencies once |
| Realm / users don't match the JSON | The realm already existed — see [Changing the Keycloak realm](#changing-the-keycloak-realm) |
| `pnpm dev`: `[ai] … uv: not found` | Install uv ([installation guide](installation.md#24-uv-and-python-313)), then `uv sync --directory apps/ai-service` |
| `pnpm dev`: port 4200/3000/8000 in use | An old dev server is still running: `lsof -nP -iTCP:4200 -sTCP:LISTEN` and kill it |
| `[api]` exits on startup: `password authentication failed for user "postgres"` | `API_DATABASE_URL` in `.env` must repeat `POSTGRES_USER` / `POSTGRES_PASSWORD` (the API migrates on boot, so it fails fast) |
| `POST /api/documents` → 409 for a file that failed | Dedupe is by content (SHA-256), failed rows included: delete the failed document, then upload again |
| `pnpm dev`: `[ai]` exits on startup with a Qdrant connection error | The AI service needs Qdrant at startup: `pnpm stack:up` first |
| `[ai]` exits: `LLM_PROVIDER=openai_compat needs LLM_API_KEY and LLM_MODEL` | Set both in `.env` (OpenRouter key with a credit limit, model from [ADR-0005](../adr/0005-llm-access-and-model.md)), or `LLM_PROVIDER=fake` |
| Chat ends with `event: error`, `LLM request failed` | `detail` carries the provider's answer: 401 wrong key, 402 credits used up, 429 rate limit after retries — see `data/sample-docs/runbook-llm-provider-outage.md` |
| `[ai]` takes minutes to start, `/readyz` returns 503 | First start downloads the embedding model; watch the `[ai]` progress output. Changing `EMBEDDING_MODEL` downloads another one and starts with an empty collection (re-ingest) |
| Angular shows stale output | `rm -rf apps/web/.angular` and restart |
| Login page: "Cookie not found" | Use `http://localhost:…`, not `127.0.0.1` — cookies and redirect URIs are bound to `localhost` |
| Want a clean slate | `pnpm stack:reset`, `rm -rf node_modules apps/*/node_modules apps/ai-service/.venv`, then the steps in §1 |

## 9. What's next

Milestones **M1.0** (base setup), **M1.1** (infra + auth walking skeleton), **M1.2** (ingestion,
retrieval, eval harness — `pnpm eval:retrieval`, see [evals/README.md](../../evals/README.md)) and
**M1.3** (grounded chat, `POST /v1/chat` in the AI service), **M1.4** (documents, chat and search
relays in the API, `pnpm contracts:generate`) and **M1.5** (Angular UI: documents, chat, inspector) are
done. Next step, in plan order: containers + CI + e2e (M1.6).
