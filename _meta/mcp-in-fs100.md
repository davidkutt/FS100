# MCP in FS100 — how it fits, and how to check it by hand

> **State:** M2.4 done (own MCP server + token exchange), M2.5 (external MCP servers) in progress.
> **Written / verified:** 2026-10-21 against the running stack, MCP Inspector **v2.12.0**, Node 24.
> **Theory behind it:** [batch-06 — MCP & safe actions](ai-theory/batch-06-mcp-safe-actions.md).
> **Decisions:** [ADR-0009 token exchange](../docs/adr/0009-token-exchange-internal-hops.md) ·
> [ADR-0010 own MCP server](../docs/adr/0010-own-mcp-server-sdk-v2.md).

---

## 1. The picture

FS100 is **both** an MCP server and an MCP client, in the same process (the AI service on `:8000`):

```
browser ──JWT aud=kb-api──▶ NestJS :3000
                               │  hop 1: token exchange → aud=kb-ai
                               ▼
                         AI service :8000  ── agent loop (agent.py) ── MCP client (mcp_client.py)
                               │                                            │
                               │  hop 2: kb-ai exchanges again,             │  POST /mcp
                               │  scope=kb:read (+ kb:write if approved)    │  Bearer aud=http://localhost:8000/mcp
                               ▼                                            ▼
                         own MCP server  /mcp  (mcp_server.py, mounted in the same FastAPI app)
                               │
                               └── knowledge base (Qdrant + bge-m3); ingest_url → NestJS /internal/documents/from-url
```

- **Server:** `/mcp` exposes the knowledge base as MCP tools. The agent uses it on every turn, and any other
  MCP client (the Inspector, later Claude Code / VS Code) can use the same endpoint.
- **Client:** the agent never calls the knowledge base directly. Its `kb.*` tools go through
  `McpClient` → HTTP → `/mcp`, so MCP auth and tracing run on every turn (ADR-0010).
- **Stateless:** no `Mcp-Session-Id`; every request carries its own token. The agent's client pins protocol
  `2026-07-28`; the Inspector connects with the older `2025-11-25` handshake by default. Both work.

## 2. Where things live

| What | Where |
|---|---|
| Server: tools, resource, token check | [`apps/ai-service/src/ai_service/mcp_server.py`](../apps/ai-service/src/ai_service/mcp_server.py) |
| Client the agent uses | [`apps/ai-service/src/ai_service/mcp_client.py`](../apps/ai-service/src/ai_service/mcp_client.py) |
| Hop-2 exchange + kb-ai service token | [`apps/ai-service/src/ai_service/tokens.py`](../apps/ai-service/src/ai_service/tokens.py) |
| Mount at `/mcp` (last, after all FastAPI routes) | [`apps/ai-service/src/ai_service/main.py`](../apps/ai-service/src/ai_service/main.py) |
| Agent tool specs (`kb.*`) | [`apps/ai-service/src/ai_service/tools.py`](../apps/ai-service/src/ai_service/tools.py) |
| Realm: clients `kb-api`, `kb-ai`, scopes `kb:read` / `kb:write` | [`infra/keycloak/realm-kb.json`](../infra/keycloak/realm-kb.json) |
| Env: `MCP_RESOURCE_URL` (= hop-2 audience) | [`.env.example`](../.env.example) |
| Tests | `apps/ai-service/tests/test_mcp.py` |
| External servers (M2.5, in progress) | `config/mcp_servers.yaml` |

## 3. Tokens: who holds what

| Token | Who gets it | `aud` | Accepted by |
|---|---|---|---|
| User token | browser (`kb-web`, PKCE) | `kb-api` | NestJS `/api/*` |
| Hop 1 | NestJS (`kb-api`) exchanges the user token | `kb-ai` | AI service `/v1/*` |
| Hop 2 | AI service (`kb-ai`) exchanges the hop-1 token, `scope=kb:read` (+`kb:write`) | `http://localhost:8000/mcp` | `/mcp` only |
| kb-ai service token | client credentials | `kb-api` (via role `ingest-on-behalf`) | NestJS `/internal/documents/from-url` |

Rules worth remembering:

- `/mcp` accepts **only** hop-2 tokens. A hop-1 token gets `401`.
- Hop 2 asks for the audience **by scope**, not with `audience=` (Keycloak only takes client ids there).
- Keycloak hands `kb:write` to anyone who asks, viewers included. **The server checks scope and role**:
  `kb:read` + viewer for the read tools, `kb:write` + editor for `ingest_url`.
- A missing scope or role is a **tool error** (`isError: true`), not an HTTP 403.
- All tokens live 5 minutes. When the Inspector suddenly says `invalid_token`, mint a new one.

## 4. What the server offers

| Name | Kind | Needs | What it does |
|---|---|---|---|
| `search_knowledge_base` | tool | `kb:read` · viewer | best chunks for a `query` (`top_k ≤ 10`, optional `domains`, `doc_ids`) |
| `get_document` | tool | `kb:read` · viewer | a document's labels + a window of chunks; page on with `next_offset` |
| `list_sources` | tool | `kb:read` · viewer | every document; `domains: ["architecture"]` = the ADRs |
| `ingest_url` | tool | `kb:write` · editor | adds a document from a URL **after a confirmation** (MRTR elicitation), via NestJS (host allow-list, SSRF guard, size limit) |
| `kb://documents/{doc_id}` | resource template | `kb:read` · viewer | labels + headings of one document |

No prompts.

---

## 5. Manual check with MCP Inspector (step by step)

Goal: prove that a normal MCP client can connect to `/mcp` with a user's token, sees the 4 tools and can
call one. Takes about 5 minutes.

### 5.1 Stack running

```bash
pnpm stack:up
```

```bash
pnpm dev
```

Check that the AI service answers and that `/mcp` asks for a token:

```bash
curl -s localhost:8000/readyz
curl -si -X POST localhost:8000/mcp | grep -i www-authenticate
```

Expected: `{"status":"ok"}` and a `WWW-Authenticate: Bearer error="invalid_token" …` line.

### 5.2 Start the Inspector (in a second terminal)

```bash
npx @modelcontextprotocol/inspector
```

It opens the browser by itself (the URL contains an `MCP_INSPECTOR_API_TOKEN`; that one protects the
Inspector, it has nothing to do with Keycloak). If it says **PORT IS IN USE**, an old Inspector is still
running: close it, or start this one on other ports:

```bash
CLIENT_PORT=6374 SERVER_PORT=6377 npx @modelcontextprotocol/inspector
```

Use **v2** (what plain `npx @modelcontextprotocol/inspector` installs now). v1 (`@0.17.x`) crashes on
Node 24 with `Controller is already closed` as soon as it connects to our server.

### 5.3 Mint an MCP token (do this right before connecting — it lives 5 min)

Run from the repo root. These are the same two exchanges NestJS and the AI service do:

```bash
X=urn:ietf:params:oauth:grant-type:token-exchange; AT=urn:ietf:params:oauth:token-type:access_token
KC=http://localhost:8080/realms/kb/protocol/openid-connect/token
mcp_token() {  # usage: mcp_token <bob|alice|carol> "<scope>"
  local user hop1
  user=$(.claude/skills/user-token/login.sh "$1")
  hop1=$(curl -s -d grant_type=$X -d client_id=kb-api -d client_secret=dev-only-change-me \
    -d subject_token=$user -d subject_token_type=$AT -d audience=kb-ai $KC \
    | sed -E 's/.*"access_token":"([^"]+)".*/\1/')
  curl -s -d grant_type=$X -d client_id=kb-ai -d client_secret=dev-only-change-me \
    -d subject_token=$hop1 -d subject_token_type=$AT --data-urlencode "scope=$2" $KC \
    | sed -E 's/.*"access_token":"([^"]+)".*/\1/'
}
mcp_token bob kb:read | pbcopy
```

The token is now on the clipboard. (Want to look inside? Paste it into jwt.io: `aud` must be
`http://localhost:8000/mcp`, `scope` contains `kb:read`, `realm_access.roles` has `editor`.)

### 5.4 Add the server in the Inspector

1. **Add Servers → Add manually.**
2. Server ID: `fs100-kb` · Transport: **Streamable HTTP** · URL: `http://localhost:8000/mcp` → **Add**.
   Use `localhost`, not `127.0.0.1`: the server only accepts the `localhost` host (DNS-rebinding guard).
3. On the new `fs100-kb` card: **Settings → Custom Headers → + Add Header**.
   Key `Authorization`, value `Bearer ` followed by the pasted token. Close the dialog.
4. Flip the `fs100-kb` toggle on.

### 5.5 What you should see

- The card says **Connected** and `MCP 2025-11-25`.
- The **Protocol** panel on the right lists `initialize`, `tools/list`, `prompts/list`,
  `resources/list`, `resources/templates/list`, all **OK**.
- **Tools** tab: `Tools (4)` → `search_knowledge_base`, `get_document`, `list_sources`, `ingest_url`.
- Click `list_sources` → **Execute Tool**: a JSON list of your documents (`doc_id`, `title`,
  `domains`, `chunk_count`). That's the check passed.

Optional, still read-only:

- `search_knowledge_base` with query `Was passiert, wenn das Fehlerbudget aufgebraucht ist?`
  (needs `slo-handbook.pdf` ingested) → hits with scores.
- **Resources** tab → template `kb://documents/{doc_id}` with a `doc_id` from `list_sources` → headings.

Careful with `ingest_url`: with a `kb:write` token as bob it asks for a confirmation, and confirming
**really adds a document**. Not tried in the Inspector yet.

### 5.6 When it doesn't work

| Symptom | Cause / fix |
|---|---|
| `invalid_token` / "Authentication required" | Token expired (5 min) or header missing. Mint a new one (§5.3), paste it in Settings → Custom Headers, toggle off and on |
| Same, right after pasting | Header row empty or switched off; or you pasted a hop-1 token (`aud=kb-ai`) — `/mcp` needs hop 2 |
| Inspector: `Controller is already closed`, then `Failed to fetch` | Inspector v1 on Node 24. Use v2 (§5.2) |
| `PORT IS IN USE at http://127.0.0.1:6274` | Another Inspector is running. Close it, or use `CLIENT_PORT` / `SERVER_PORT` |
| Connection refused | AI service not running: `pnpm dev` (or `pnpm dev ai`) |
| `login.sh` fails | Keycloak not up: `pnpm stack:up`; check with `pnpm stack:ps` |

---

## 6. The same checks with curl (no Inspector)

Use `mcp_token` from §5.3.

```bash
TOKEN=$(mcp_token bob kb:read)
mcp() { curl -s localhost:8000/mcp -H "Authorization: Bearer $1" -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' -d "$2"; echo; }

mcp $TOKEN '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
mcp $TOKEN '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"list_sources","arguments":{}}}'
curl -s localhost:8000/.well-known/oauth-protected-resource/mcp   # resource, authorization_servers, scopes_supported
```

Negative cases (verified 2026-10-21; none of them writes anything):

| Call | Result |
|---|---|
| `POST /mcp` without token | `401` + `WWW-Authenticate … resource_metadata=…` |
| hop-1 token (`aud=kb-ai`) on `/mcp` | `401` |
| `ingest_url` as **carol** (viewer) with `kb:read kb:write` | `isError`: `Not permitted for your role (needs editor)` |
| `ingest_url` as **bob** with only `kb:read` | `isError`: `insufficient_scope: needs kb:write` |

```bash
ING='{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"ingest_url","arguments":{"url":"https://example.com/a.md","domains":["dev"]}}}'
mcp "$(mcp_token carol 'kb:read kb:write')" "$ING"
mcp "$(mcp_token bob kb:read)" "$ING"
```

## 7. Automated checks

```bash
uv run --directory apps/ai-service pytest tests/test_mcp.py
```

13 tests, under a second, no Docker or Keycloak: the 401 challenge, audience and scope checks, the read
tools and the resource, role checks, `ingest_url` (asks first, adds nothing unless confirmed and
permitted, reports the API's refusal) and the hop-2 token cache.

To see MCP inside a real agent turn (one Phoenix trace: `agent.run` → `tool` → `MCP send tools/call` →
`tools/call search_knowledge_base` → `search` → `embed`), ask Claude Code for the `agent-turn-check`
skill, or follow the `/v1/agent` curl in [startup.md §4](../docs/setup/startup.md#4-check-that-everything-works)
and open Phoenix at http://localhost:6006.

## 8. What comes next

- **M2.5 (in progress):** the AI service also becomes a client of **external** MCP servers, configured in
  `config/mcp_servers.yaml`: the GitHub MCP server as a container (read-only, lockdown mode, allow-listed
  tools), tool namespacing (`kb.*`, `github.*`), list caching and a router. See
  [plan-phase-2.md M2.5](../plan-phase-2.md#m25--external-mcp-servers-github-write-routing-12-h).
- **M2.8 (stretch):** Claude Code and VS Code log in to `/mcp` themselves (OAuth discovery → CIMD → PKCE),
  so nobody pastes tokens any more. Until then a client needs a hand-made token as above, valid 5 minutes.
