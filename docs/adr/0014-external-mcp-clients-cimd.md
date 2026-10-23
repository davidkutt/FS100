# ADR-0014: External MCP clients via Keycloak CIMD, with the experimental features always on

- **Status:** Accepted (M2.8)
- **Date:** 2026-10-22
- **Plan reference:** D35 ([plan-phase-2.md §3](../../plan-phase-2.md#3-decisions))

## Context

Demo step 11: Claude Code adds `http://localhost:8000/mcp`, logs in through Keycloak and searches the
knowledge base. MCP 2026-07-28 clients register by **Client ID Metadata Document** (CIMD: the
`client_id` is an HTTPS URL to a JSON document) and send `resource` (RFC 8707). Keycloak 26.8 has both
only as experimental features (`cimd`, `resource-indicators`). D35 kept them off the critical path, and
the plan put them in an opt-in Compose profile `mcp-ext`.

## Decision

- **Keycloak always runs with `--features=cimd,resource-indicators`**; there is no `mcp-ext` profile. The
  CIMD policies live in `realm-kb.json`. A toggle does not work: a realm import that contains them
  makes Keycloak refuse to start without the features, and an existing realm with them makes every login
  fail (`500 Condition with provider ID client-id-uri not found`), kb-web included.
- **One client policy per client** (Keycloak's MCP guide): condition `client-id-uri` (scheme `https`,
  host `claude.ai` or `vscode.dev`) → profile with executor `client-id-metadata-document`: trusted
  domains (`claude.ai`, `localhost`, `127.0.0.1` / `vscode.dev`, `127.0.0.1`, `code.visualstudio.com`),
  same-domain check off (loopback redirects), resource allow-list `http://localhost:8000/mcp`. Keycloak
  fetches the document, creates a public client with that `client_id` and adds an audience mapper for
  the allowed resource, so `aud` = the MCP URL. Any other `resource` → `invalid_target`.
- **No `kb-mcp` client.** The executor's allow-list binds the audience; a `resource_url` client only
  matters for pre-registered clients, and we have none.
- **Scopes and roles:** `kb:read` and `kb:write` become realm-default optional scopes, so created clients
  can request them. Created clients get *full scope* off, so a scope mapping on `kb:read` puts the realm
  roles `viewer`/`editor`/`admin` into their tokens. `kb-web` and `kb-api` now list their scopes
  explicitly and still cannot request `kb:*`.
- **PKCE S256 for every public client** (policy `pkce-for-public-clients`, `pkce-enforcer` with
  auto-configure). The CIMD profiles' own `pkce-enforcer` never runs when the client is created, so
  created clients would accept requests without PKCE.
- **The MCP server is unchanged.** It already checks `aud`, `kb:read` and the role. Its metadata
  advertises `kb:read` only, so external clients get read tools; `ingest_url` there fails with
  `insufficient_scope: needs kb:write` (a tool error, not a 403 step-up; ADR-0010), and for a viewer on
  the role as well.

Verified on a throwaway Keycloak 26.8.1 with the AI service on :8001, using Claude Code's and VS Code's
real metadata documents and a scripted PKCE login (`.claude/skills/realm-check/cimd-login.sh`):

| Case | Result |
|---|---|
| carol, Claude Code, `scope=kb:read`, `resource` = MCP URL | consent screen → `aud=http://localhost:8001/mcp`, `kb:read`, roles `[viewer]` |
| bob, VS Code, `kb:read kb:write` | `aud` = MCP URL, both scopes, roles `[viewer, editor]` |
| carol at `/mcp`: `tools/list`, `search_knowledge_base` | 200, 4 tools, hits |
| carol at `/mcp`: `ingest_url` | tool error `insufficient_scope: needs kb:write` |
| No `scope` | `aud` = MCP URL, no `kb:read` → `/mcp` 403 `insufficient_scope` (step-up challenge) |
| Wrong `resource` · redirect URI not in the document · `client_id` on another host | `invalid_target` · 400 · 400 |
| No `code_challenge`, or `plain` | `invalid_request` |
| kb-web token at `/mcp` · kb-web asking for `kb:read` | 401 · `invalid_scope` |
| ADR-0009 token matrix | unchanged |

## Alternatives considered

- **Opt-in profile `mcp-ext`** (the plan) — a trap, see above; switching back would need a script that
  removes the policies before every restart without the features.
- **Pre-registered public clients** (no experimental features) — each user enters a client id and a fixed
  callback port per tool by hand; CIMD is what MCP 2026-07-28 clients try first and needs no setup.
- **Dynamic client registration** — deprecated in MCP 2026-07-28; Keycloak's anonymous registration
  needs trusted-host policies per machine.

## Consequences

- Two experimental features run on every login. Our own flows don't use them (no `resource`, no URL
  client ids), and the token matrix is unchanged, but a Keycloak upgrade may change them. Check every
  bump with `infra-upgrade-check`, including a CIMD login.
- Keycloak needs internet access to fetch the metadata documents (cached 5 min to 3 days).
- Claude Desktop and claude.ai connectors connect from Anthropic's cloud and cannot reach `localhost`;
  ChatGPT's metadata document is not parsed by Keycloak (guide). Not supported.
- Existing local stacks need `pnpm stack:reset` (wipes local data) to import the realm; the new
  `command` alone only switches the features on.
