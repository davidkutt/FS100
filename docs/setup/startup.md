# Startup guide — run FS100 locally

Prerequisite: the toolchain from the **[installation guide](installation.md)** (Node 24, pnpm via Corepack,
uv, Docker).

FS100 uses two development modes (plan.md D18):

- **Mode A (daily):** infrastructure in Docker Compose — Postgres, Qdrant, Keycloak, Phoenix — and the
  three apps running **natively** with hot reload.
- **Mode B (`pnpm stack:up:full`):** everything containerised, for demos, e2e and image tests — see
  [Mode B](#mode-b-everything-in-containers).

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

### Mode B: everything in containers

Needs Docker and pnpm (Corepack) only — no `pnpm install`, no uv; the images build the apps:

```bash
cp .env.example .env        # set LLM_API_KEY + LLM_MODEL, or LLM_PROVIDER=fake
pnpm stack:up:full          # = node scripts/stack.mjs --profile full up --detach --wait --build
```

It builds the images from `apps/*/Dockerfile` and starts them next to the infra, on the same ports as
Mode A — so stop `pnpm dev` first. The containers read the same variables from `.env` (or your shell,
which wins); only the hostnames between them differ, and those are set in the Compose file.

- The **first** start downloads the embedding model into the Docker volume `fs100_fastembed-cache`
  (≈ 2.3 GB for `bge-m3`); `stack:up:full` waits until the AI service is ready. Later starts reuse it.
- After a code change, run `pnpm stack:up:full` again: it rebuilds what changed.
- `pnpm stack:down` stops everything (both modes); `pnpm stack:reset` also deletes the model volume.
- Without `.env`, `LLM_PROVIDER` falls back to `fake`.

## 3. What runs where

Ports are fixed and identical in Mode A and Mode B (plan.md §5). Everything binds to `localhost` only.

| Service | URL | Login (dev only) |
|---|---|---|
| Web (Angular) | http://localhost:4200 | seed users below (Keycloak login, PKCE) |
| API (NestJS) | http://localhost:3000/healthz · `/readyz` · `/api/*` needs a user token (`/api/me`, `/api/documents`, `/api/conversations`, `/api/approvals`, `/api/models`, `/api/taxonomy`, `/api/chat`, `/api/search`, `/api/me/usage`, admin: `/api/status`, `/api/admin/audit`, `/api/admin/usage`, `/api/admin/reindex`) | — |
| AI service (FastAPI) | http://localhost:8000 · `/healthz`, `/readyz` · Swagger UI: http://localhost:8000/docs · `/v1/*` needs a token with `aud=kb-ai` (a user's, exchanged by the API, or the API's service token) · MCP server: http://localhost:8000/mcp (token with `aud=http://localhost:8000/mcp`, scope `kb:read`), metadata at `/.well-known/oauth-protected-resource/mcp` | — |
| Keycloak admin console | http://localhost:8080/admin/ | `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD` from the first start (default `admin` / `dev-only-change-me`) |
| Keycloak account console (realm `kb`) | http://localhost:8080/realms/kb/account | seed users below |
| Qdrant dashboard | http://localhost:6333/dashboard | — |
| Phoenix (LLM traces) | http://localhost:6006 | — |
| Postgres | `postgresql://postgres:dev-only-change-me@localhost:5432/app` | also DBs `keycloak` and `ai` (the AI service's originals and job queue, created on its first start) |

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

**New users.** Self-registration is off (D44: tools spend tokens). To allow it for a demo: admin console →
realm **kb** → **Realm settings** → **Login** → *User registration* on; new accounts get the role `viewer`. To
create users or change roles as the Keycloak admin: http://localhost:8080/admin/ → realm selector **kb** →
**Users** → *Create new user* (then the **Credentials** tab → *Set password*, *Temporary* off) or open a user
→ **Role mapping** → *Assign role* → filter *Realm roles* → `editor` / `admin`. Role changes apply at the
next token refresh (≤ 5 min) or after logging out and in.

**Clients** (token flow: ADR-0009): `kb-web` (public, PKCE S256, redirect `http://localhost:4200/*`, access
tokens carry `aud=kb-api`), `kb-api` (confidential, secret `dev-only-change-me`; exchanges user tokens for
`aud=kb-ai` and has a service account with `aud=kb-ai` for system calls), `kb-ai` (confidential, secret
`dev-only-change-me`; exchanges those tokens for the MCP server via the optional client scopes `kb:read` /
`kb:write`, whose audience mapper adds `http://localhost:8000/mcp`; its service account holds the `kb-api` client
role `ingest-on-behalf` for `/internal/documents/from-url`). Claude Code and VS Code get a client of their own on
their first login, created from their Client ID Metadata Document ([§4](#use-the-knowledge-base-from-claude-code--vs-code)).
Every public client must use PKCE S256.

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

# AI service: /v1/* accepts only tokens for aud=kb-ai (a user token for kb-api gets 401).
TOKEN=$(curl -s -d grant_type=client_credentials -d client_id=kb-api -d client_secret=dev-only-change-me \
  http://localhost:8080/realms/kb/protocol/openid-connect/token | sed -E 's/.*"access_token":"([^"]+)".*/\1/')
curl -s localhost:8000/v1/status -H "Authorization: Bearer $TOKEN"   # {"status":"ok"} + a "status" span in Phoenix

# Chat and agent turns act as a user: log in as bob (scripted PKCE login), exchange like the API does (hop 1).
BOB=$(.claude/skills/user-token/login.sh bob)
X=urn:ietf:params:oauth:grant-type:token-exchange; AT=urn:ietf:params:oauth:token-type:access_token
USER_TOKEN=$(curl -s -d grant_type=$X -d client_id=kb-api -d client_secret=dev-only-change-me \
  -d subject_token=$BOB -d subject_token_type=$AT -d audience=kb-ai \
  http://localhost:8080/realms/kb/protocol/openid-connect/token | sed -E 's/.*"access_token":"([^"]+)".*/\1/')

# AI service: upload a document (stored + queued), wait for its job, search it (spans ingest/parse/chunk/embed/upsert/search)
DOC=$(uuidgen | tr A-Z a-z)
curl -s localhost:8000/v1/documents -H "Authorization: Bearer $TOKEN" -F file=@data/sample-docs/slo-handbook.pdf \
  -F doc_id=$DOC -F owner_id=dev -F domains=sre        # 202 {"job_id":1,"version":1}
curl -s localhost:8000/v1/jobs/1 -H "Authorization: Bearer $TOKEN"   # queued → parsing → embedding → ready {"result":{"chunk_count":3,…}}
curl -s localhost:8000/v1/search -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"query":"Was passiert, wenn das Fehlerbudget aufgebraucht ist?","top_k":3}'   # hits with page numbers
curl -N localhost:8000/v1/chat -H "Authorization: Bearer $USER_TOKEN" -H 'content-type: application/json' \
  -d '{"messages":[{"role":"user","content":"Was passiert, wenn das Fehlerbudget aufgebraucht ist?"}]}'
  # streams event: sources → token … → done; Phoenix shows chat → search → embed and the LLM span (prompt, tokens)
curl -N localhost:8000/v1/agent -H "Authorization: Bearer $USER_TOKEN" -H 'content-type: application/json' \
  -d '{"conversation_id":"'$(uuidgen)'","messages":[{"role":"user","parts":[{"type":"text","text":"Was passiert, wenn das Fehlerbudget aufgebraucht ist?"}]}]}'
  # streams step → tool_call → tool_result → sources → step → token … → done (stopReason, answerStatus);
  # Phoenix shows one trace: agent.run → llm / tool → MCP send tools/call → tools/call → search → embed.
  # Add "mode":"rag" for the Phase 1 pipeline with the same done event

# Own MCP server: 401 with a challenge without a token; the agent's hop-2 token (as kb-ai) lists the tools.
curl -si -X POST localhost:8000/mcp | grep -i www-authenticate   # … resource_metadata="…/.well-known/oauth-protected-resource/mcp"
curl -s localhost:8000/.well-known/oauth-protected-resource/mcp  # resource, authorization_servers, scopes_supported
MCP_TOKEN=$(curl -s -d grant_type=$X -d client_id=kb-ai -d client_secret=dev-only-change-me \
  -d subject_token=$USER_TOKEN -d subject_token_type=$AT -d scope=kb:read \
  http://localhost:8080/realms/kb/protocol/openid-connect/token | sed -E 's/.*"access_token":"([^"]+)".*/\1/')
curl -s localhost:8000/mcp -H "Authorization: Bearer $MCP_TOKEN" -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
  # search_knowledge_base, get_document, list_sources, ingest_url. MCP Inspector v2 (npx @modelcontextprotocol/inspector;
  # v1 0.17.x crashes on Node 24): Add Servers → Add manually, Streamable HTTP, URL http://localhost:8000/mcp;
  # then the server's Settings → Custom Headers: Authorization = Bearer $MCP_TOKEN (valid 5 min — mint it right before)
curl -s -o /dev/null -w '%{http_code}\n' -X DELETE localhost:8000/v1/documents/$DOC -H "Authorization: Bearer $TOKEN"  # 204

# Postgres: all three databases exist (`ai` once the AI service has started)
docker exec fs100-postgres-1 psql -U postgres -tAc "select datname from pg_database where datname in ('app','keycloak','ai')"
```

In the browser: log in at http://localhost:4200 as `alice` (admin: status card shows `api`, `db`,
`aiService` and `qdrant` = `ok`), then **Log out** and log in as `bob` / `carol` (no status card). The `status` span of
the card's AI-service call appears in Phoenix (http://localhost:6006, project `default`). Every response
carries an `x-request-id` header; the API and the AI service log it in their JSON log lines.

Then the demo path as `bob`: **Documents** → pick domains → drop files from `data/sample-docs/` → status
goes `queued → parsing → embedding → ready`. **Chat** → ask a question → the answer streams with `[1]` citations;
select one to read the passage, **Trace in Phoenix** opens the request's trace. **Inspector** shows the
raw hits with scores and a dashed line at the score threshold. As `carol` (viewer) there are no upload
or delete controls. Chat calls the real LLM unless `LLM_PROVIDER=fake`.

### Use the knowledge base from Claude Code / VS Code

MCP clients log in to the own MCP server through Keycloak themselves: no client to register, no token to
paste ([ADR-0014](../adr/0014-external-mcp-clients-cimd.md)). Keycloak fetches the client's Client ID Metadata
Document from claude.ai / vscode.dev (so it needs internet), creates a client for it and issues tokens with
`aud=http://localhost:8000/mcp`.

> **Experimental.** This relies on Keycloak's `cimd` and `resource-indicators` features, which are always on
> in Compose and may change with any Keycloak upgrade. A realm imported before M2.8 lacks the client
> policies: `pnpm stack:reset && pnpm stack:up` (wipes all local data, [§7](#changing-the-keycloak-realm)).

**Claude Code:**

```bash
claude mcp add --transport http fs100-kb http://localhost:8000/mcp
```

In Claude Code, run `/mcp` → `fs100-kb` → *Authenticate*. The browser opens Keycloak: log in (e.g. `carol`)
and allow access on the consent screen (once per user). Then ask, e.g., *"Search the FS100 knowledge base:
what happens when the error budget is exhausted?"* — Claude Code calls `search_knowledge_base`.

**VS Code** (`.vscode/mcp.json`, or *MCP: Add Server* → HTTP):

```json
{ "servers": { "fs100-kb": { "type": "http", "url": "http://localhost:8000/mcp" } } }
```

Start the server, allow the authentication prompt, log in in the browser; the tools are then available in
chat (agent mode).

External clients get the read tools (`search_knowledge_base`, `get_document`, `list_sources`) with your roles.
The server advertises only `kb:read`, so `ingest_url` fails with `insufficient_scope: needs kb:write` — add
documents in the app. Tokens live 5 minutes and the client refreshes them; after 30 minutes idle or 10 hours
it asks you to log in again. Not supported: Claude Desktop and claude.ai connectors (they connect from
Anthropic's cloud, which cannot reach `localhost`) and ChatGPT (Keycloak does not parse its metadata document).

## 5. Quality checks

Run them before every push — they are also what CI runs.

```bash
pnpm lint           # angular-eslint (web) · oxlint (api) · prettier --check · ruff + pyright (ai-service)
pnpm test           # Vitest (web, api unit + HTTP) · pytest (ai-service)
pnpm build          # production builds of web and api
pnpm format         # auto-fix formatting (prettier + ruff)
```

**End-to-end smoke** (Playwright, `e2e/`): logs in as `bob`, uploads a generated Markdown file, asks a
question, opens the citation and deletes the file again; then asks the fake LLM to `Add <url>`, rejects the
proposed `kb.ingest_url`, asks again and approves it (the API fetches `docs/adr/template.md` from this repo
on GitHub, so it needs internet) and deletes the ingested file. It needs `LLM_PROVIDER=fake` and runs
against whatever serves http://localhost:4200 — Mode B as in CI, or Mode A:

```bash
pnpm --filter @fs100/e2e exec playwright install chromium   # once per machine
LLM_PROVIDER=fake pnpm stack:up:full                        # free: no LLM tokens
pnpm e2e
```

CI (`.github/workflows/`) runs `ci.yml` (lint, test, build, contract drift), `e2e.yml` (this smoke),
`eval.yml` (retrieval eval on PRs touching the AI service, config or evals, **blocking** when hit@5 or
nDCG@10 drops more than 0.02 below the baseline; real-model agent / red-team / routing evals by hand with a
budget; nightly fixture contract) and, on `main`, `docker.yml` (multi-arch images to GHCR). The agent smoke
(fake LLM + fixture MCP servers) runs with the tests.

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
| `pnpm stack:up:full` | Same plus web, api and ai-service as containers (Mode B), rebuilt if changed |
| `pnpm stack:ps` | Container status and health |
| `pnpm stack:logs` / `pnpm stack:logs keycloak` | Follow logs (all services or one) |
| `pnpm mem` | Memory of the apps started by `pnpm dev` (RSS incl. child processes) and of each container |
| `pnpm stack:down` | Stop and remove containers; **keeps** data volumes |
| `pnpm stack:reset` | Stop and **delete all local data** (Postgres incl. Keycloak, Qdrant, Phoenix, model cache of Mode B) |
| `pnpm kb:backfill-originals` | Store the originals of documents indexed before M3a.1 (matched in `data/sample-docs/` by SHA-256); lists the rest — upload those again |
| `pnpm kb:reindex [--force --reason "…"]` · `pnpm kb:reindex --rollback` | Rebuild `kb_current` from the stored originals behind the golden-set gate, or point it back; the job runs in the AI service (`pnpm dev ai`). Also on the admin page **Re-index** |

**After pulling M3a.1** (existing data): start the AI service once (it creates the database `ai`), run
`pnpm kb:backfill-originals`, then `pnpm kb:reindex` — documents without an original block the swap
until they are uploaded again. The first swap moves `kb_current` from `kb__<model>__<dim>` to a
`kb__v2__…` collection; the old one stays for `--rollback`.

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
file — or pulling a change to it, e.g. M2.4 (client `kb-ai` with secret and token exchange, scopes `kb:read` /
`kb:write`, role `ingest-on-behalf`, self-registration off) or M2.8 (client policies for Claude Code / VS Code,
PKCE for public clients) — recreate the Keycloak state:

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
| `pnpm dev`: `[ai]` `Connection refused` (Qdrant :6333), `[api]` `ECONNREFUSED …:5432` | The infra is not running — `pnpm stack:reset` and `stack:down` stop it and do not start it again: `pnpm stack:up`, then `pnpm dev` |
| `pnpm stack:up` times out on Keycloak | First start imports the realm and builds its Quarkus image: wait, then `pnpm stack:logs keycloak`. Low Docker memory is the usual root cause |
| App login says "Invalid username or password" for `admin` | `admin` is the Keycloak server admin (realm `master`). Log in to the app as `alice` / `bob` / `carol` or **Register** — see [§3](#3-what-runs-where) |
| New `KEYCLOAK_ADMIN_PASSWORD` / `POSTGRES_PASSWORD` not accepted | The volumes still hold the first-start values — see [Changing credentials in `.env`](#changing-credentials-in-env) |
| Keycloak unhealthy after changing `POSTGRES_PASSWORD` | Same cause: Postgres still has the old password. Revert `.env`, or reset / `ALTER USER` as described there |
| Everything is slow | Usually memory: Docker infra + embedding model + IDE + browser on 16 GB. Check `sysctl vm.swapusage`; use `EMBEDDING_MODEL=intfloat/multilingual-e5-small`, stop `phoenix` when not needed, give Docker less RAM. The first page load after `pnpm install` also pre-bundles dependencies once |
| Realm / users don't match the JSON | The realm already existed — see [Changing the Keycloak realm](#changing-the-keycloak-realm) |
| `pnpm dev`: `[ai] … uv: not found` | Install uv ([installation guide](installation.md#24-uv-and-python-313)), then `uv sync --directory apps/ai-service` |
| `pnpm dev`: port 4200/3000/8000 in use | An old dev server is still running: `lsof -nP -iTCP:4200 -sTCP:LISTEN` and kill it |
| `[api]` exits on startup: `password authentication failed for user "postgres"` | `API_DATABASE_URL` in `.env` must repeat `POSTGRES_USER` / `POSTGRES_PASSWORD` (the API migrates on boot, so it fails fast) |
| `[ai]` exits on startup: `password authentication failed` or `connection … 5432 refused` | `AI_DATABASE_URL` must repeat `POSTGRES_USER` / `POSTGRES_PASSWORD` too, and Postgres must run (`pnpm stack:up`) |
| Documents stay `queued` | The AI service's worker runs them one at a time; a re-index blocks uploads until it ends. With `JOBS_INPROCESS_WORKER=false` nothing runs them |
| `pnpm kb:reindex` prints `kept` | The gate refused the build: a `test` metric dropped by more than 0.02, or a document has no stored original (listed) — `pnpm kb:backfill-originals`, upload it again, or `--force --reason "…"` |
| `POST /api/documents` → 409 for a file that failed | Dedupe is by content (SHA-256), failed rows included: delete the failed document, then upload again |
| `pnpm dev`: `[ai]` exits on startup with a Qdrant connection error | The AI service needs Qdrant at startup: `pnpm stack:up` first |
| `[ai]` exits: `LLM_PROVIDER=openai_compat needs LLM_API_KEY and LLM_MODEL` | Set both in `.env` (OpenRouter key with a credit limit, model from [ADR-0005](../adr/0005-llm-access-and-model.md)), or `LLM_PROVIDER=fake` |
| Chat and agent turns fail with 502 `Keycloak token endpoint: HTTP 400` | The realm predates M2.4 (no token exchange on `kb-api`): `pnpm stack:reset && pnpm stack:up` (wipes all local data), see §7 |
| Agent `tool_result` errors `Keycloak token endpoint: HTTP 401` | `AI_KEYCLOAK_CLIENT_SECRET` is missing in `.env` or differs from the realm's `kb-ai` secret (`.env.example`) |
| Agent proposes a write, then ends with `error` `Agent run failed` | `APPROVAL_SIGNING_KEY` is missing in `.env`, so writes fail closed. After pulling, list what `.env` lacks: `comm -23 <(grep -oE '^[A-Z_0-9]+=' .env.example \| sort) <(grep -oE '^[A-Z_0-9]+=' .env \| sort)` |
| `kb.ingest_url` fails with `Host … is not allowed` | Only hosts in `INGEST_URL_ALLOWED_HOSTS` are fetched, and only PDF, Markdown or text files (HTML pages get 415) |
| `web.fetch` missing for the agent, or `… is not an allowed host` | Editors and admins only; it reads only hosts in `WEB_FETCH_ALLOWED_HOSTS` (empty = unavailable), on every redirect too. Restart the AI service after changing it |
| Chat ends with `event: error`, `LLM request failed` | `detail` carries the provider's answer: 401 wrong key, 402 credits used up, 429 rate limit after retries — see `data/sample-docs/runbook-llm-provider-outage.md` |
| `[ai]` takes minutes to start, `/readyz` returns 503 | First start downloads the embedding model; watch the `[ai]` progress output. Changing `EMBEDDING_MODEL` downloads another one; then `pnpm kb:reindex --force --reason "new model"` rebuilds the collection with it (searches fail until then) |
| `pnpm stack:up:full`: `port is already allocated` on 3000/4200/8000 | `pnpm dev` (or one native app) still runs — stop it; both modes use the same ports |
| `pnpm stack:up:full` waits for minutes on `ai-service` | First start downloads the embedding model into the volume: `pnpm stack:logs ai-service` |
| Angular shows stale output | `rm -rf apps/web/.angular` and restart |
| Claude Code / VS Code: Keycloak shows an error (e.g. `Invalid scopes: kb:read`) instead of the login form | The realm predates M2.8: `pnpm stack:reset && pnpm stack:up` (wipes all local data). Otherwise check `pnpm stack:logs keycloak` — Keycloak must reach claude.ai / vscode.dev |
| Keycloak: every login fails with 500 `Condition with provider ID client-id-uri not found` | Keycloak runs without `--features=cimd,resource-indicators` (ADR-0014); keep them in the Compose `command` |
| Login page: "Cookie not found" | Use `http://localhost:…`, not `127.0.0.1` — cookies and redirect URIs are bound to `localhost` |
| Want a clean slate | `pnpm stack:reset`, `rm -rf node_modules apps/*/node_modules apps/ai-service/.venv`, then the steps in §1 |

## 9. What's next

Milestones **M1.0** (base setup), **M1.1** (infra + auth walking skeleton), **M1.2** (ingestion,
retrieval, eval harness — `pnpm eval:retrieval`, see [evals/README.md](../../evals/README.md)) and
**M1.3** (grounded chat, `POST /v1/chat` in the AI service), **M1.4** (documents, chat and search
relays in the API, `pnpm contracts:generate`), **M1.5** (Angular UI: documents, chat, inspector) and
**M1.6** (containers, Mode B, CI workflows, Playwright e2e) are done. The Azure readiness spike (M1.7)
is postponed while the project runs locally. Phase 2 ([plan-phase-2.md](../../plan-phase-2.md)): **M2.0**
(pins, spikes, identities), **M2.1** (agent harness, `POST /v1/agent` in the AI service), **M2.2**
(stored conversations, the agent chat UI with tool timeline and model picker, `config/taxonomy.yaml` with
document sub-topics) and **M2.3** (approvals for write tools, audit log, admin audit page at
http://localhost:4200/admin/audit) and **M2.4** (own MCP server at http://localhost:8000/mcp, Keycloak token
exchange on both internal hops, `kb.ingest_url`), **M2.5** (GitHub MCP server, sandbox write, routing),
**M2.6** (agent eval and red-team seed, `pnpm eval:agent`) and **M2.7** (prompt files with version and hash,
daily cost caps with `/api/me/usage` and the admin usage page at http://localhost:4200/admin/usage, README and
[system card](../system-card.md)) are done; **M2.8** (Claude Code / VS Code log in to the MCP server through
Keycloak, [§4](#use-the-knowledge-base-from-claude-code--vs-code)) is code-complete.
