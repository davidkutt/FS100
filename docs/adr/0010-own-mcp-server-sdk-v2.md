# ADR-0010: Own MCP server and MCP client on Python SDK v2

- **Status:** Accepted (M2.4)
- **Date:** 2026-10-19 (accepted 2026-10-21)
- **Plan reference:** D34, D35, D38, D45 ([plan-phase-2.md §3](../../plan-phase-2.md#3-decisions))

## Context

The agent consumes its knowledge-base tools through its own MCP server, and later external clients
(Claude Code, VS Code) can use the same server. It has to run inside the AI service (one bge-m3 in RAM),
be stateless, act as an OAuth protected resource for Keycloak tokens
([ADR-0009](0009-token-exchange-internal-hops.md)), and join the agent's trace. The same SDK is the
client for the GitHub MCP server.

## Decision

- **`mcp` 2.3.x** (not 2.0.x as planned; 2.3.0 is the current line, 2026-10-02). v2 renamed FastMCP to
  `mcp.server.MCPServer`.
- **Mounted into FastAPI:** `mcp.streamable_http_app(streamable_http_path="/mcp", stateless_http=True,
  json_response=True)`, mounted at `/` after all FastAPI routes, so `/mcp` and
  `/.well-known/oauth-protected-resource/mcp` stay at the root. The FastAPI lifespan enters
  `mcp.session_manager.run()`, because Starlette does not run a mounted app's lifespan.
- **Auth:** a `TokenVerifier` on PyJWT and the existing JWKS settings checks `iss` and `aud = MCP
  resource URL` itself. `AuthSettings(issuer_url, resource_server_url, required_scopes=["kb:read"],
  validate_token_resource=False)`. Tools read claims via `get_access_token()` and check the role.
- **Host check:** the SDK's default DNS-rebinding protection stays on (only `localhost` hosts). The agent
  connects to `MCP_RESOURCE_URL` = `http://localhost:8000/mcp`, which is also the token audience; in Mode B
  the container calls itself on `localhost`, so the `ai-service:*` entry the spike suggested is not needed.
- **Errors:** raise `ToolError` for messages the model may see. Any other exception becomes a generic
  "Error executing tool X". A missing `kb:write` or role is a `ToolError` too, not an HTTP 403: the SDK
  checks `required_scopes` per endpoint only. No step-up for external clients either: they get `kb:read`
  only (M2.8, [ADR-0014](0014-external-mcp-clients-cimd.md)).
- **Tools** (`mcp_server.py`): `search_knowledge_base`, `get_document` (window + `next_offset`),
  `list_sources` (first chunk per document + a `doc_id` facet for counts; no `status` filter, Qdrant only
  holds ingested documents), `ingest_url`; resource `kb://documents/{doc_id}` (labels + headings).
  `ingest_url` confirms through MRTR: a `Resolve(...)` parameter returns `Elicit(...)`, the role and scope
  are checked in that resolver **before** asking, and a decline aborts the call.
- **Client** (`mcp_client.py`): one SDK `Client` per tool call, pinned to protocol `2026-07-28` (no
  discovery round trip), with the caller's hop-2 token ([ADR-0009](0009-token-exchange-internal-hops.md)).
  Its elicitation callback accepts only for writes, which the harness runs only after the user approved
  them (ADR-0008). The client lists the tools after each call to validate the output schema — an extra
  round trip until the M2.5 client manager keeps clients per turn and caches lists.
- **Harness:** the `kb.*` tool specs keep Pydantic argument models in `tools.py` (search offers only
  `query` and `domains`; `top_k` and the threshold stay server defaults) and run through the client; tool
  definitions from `tools/list` come with the M2.5 client manager.

## Spike results (M2.0)

Spike server (FastAPI + `MCPServer`, two tools) and SDK v2 client, against hop-2 tokens from a throwaway
Keycloak 26.8.1:

| Check | Result |
|---|---|
| `POST /mcp` without token | 401 · `WWW-Authenticate: Bearer error="invalid_token", …, resource_metadata="http://localhost:8000/.well-known/oauth-protected-resource/mcp"` |
| RFC 9728 metadata | 200 · `resource`, `authorization_servers=[…/realms/kb]`, `scopes_supported`, `bearer_methods_supported` |
| Hop-1 token (`aud=kb-ai`) on `/mcp` | 401 |
| Negotiated protocol | `2026-07-28` |
| `traceparent` via `_meta` | built into SDK v2 (client injects, server extracts): server span has the client's trace id, no own code |
| MRTR confirmation | tool returns `InputRequiredResult` with an `ElicitRequest`; the client answers through `elicitation_callback` and retries automatically; `ctx.input_responses` / `ctx.request_state` on the retry |
| Viewer calls the write tool with `kb:write` in scope | refused by the role check in the tool |

- `scopes_supported` in the metadata comes from `required_scopes`, so only `kb:read` shows up. Advertising
  `kb:write` needs a custom metadata route (only matters for the M2.8 stretch).
- If `validate_token_resource` is left unset, the SDK warns; its default changes to `True` in 3.0. We set
  it to `False` explicitly, because our verifier checks `aud`.

**GitHub MCP server** (client side, D38): `ghcr.io/github/github-mcp-server:v2.0.2` (2026-10-08; v2.0.0 is
a major release since the plan's "≥ 1.1.2"). The arm64 image runs `http --port 8082 --read-only
--lockdown-mode --toolsets repos,issues,pull_requests,actions`.

- `tools/list` works with a well-formed fake token. The token format is checked; the PAT is only used for
  API calls.
- It returns **25 tools, all `readOnlyHint`**: `actions_get`, `actions_list`, `get_commit`,
  `get_file_contents`, `get_job_logs`, `get_label`, `get_latest_release`, `get_release_by_tag`, `get_tag`,
  `issue_read`, `list_branches`, `list_commits`, `list_issue_fields`, `list_issue_types`, `list_issues`,
  `list_pull_requests`, `list_releases`, `list_repository_collaborators`, `list_tags`,
  `pull_request_read`, `search_code`, `search_commits`, `search_issues`, `search_pull_requests`,
  `search_repositories`.
- Output schemas are advertised to 2026-07-28 clients.
- Per-request headers `X-MCP-Readonly: false`, `X-MCP-Lockdown: false` and `X-MCP-Toolsets: all` did
  **not** loosen the server flags: still the same 25 read-only tools.
- Allow-list candidates for M2.5: `actions_list`, `actions_get`, `get_job_logs`, `list_issues`,
  `issue_read`, `search_issues`, `list_pull_requests`, `pull_request_read`, `list_commits`,
  `get_commit`, `get_file_contents`.

## Result (M2.4)

One agent turn is one Phoenix trace: `agent.run` → `tool` → `MCP send tools/call` →
`tools/call search_knowledge_base` → `search` → `embed` (the SDK carries `traceparent` in `_meta`).
NestJS has no spans (D21: `x-request-id` only), so the trace starts in the AI service.

## Alternatives considered

- **Separate MCP server process/container** — a second copy of bge-m3 (~2.3 GB) in RAM on a 16 GB Mac.
  It can become its own Deployment in P4, since the server is stateless.
- **Native KB tools only, MCP later** — the agent would not exercise MCP auth and tracing on every turn.
- **SDK v1 (`FastMCP`)** — no 2026-07-28 support (stateless, MRTR), and v1 is in maintenance.

## Consequences

- One tool path for the own agent and external clients; MCP auth and tracing run on every turn.
- An in-process HTTP hop with token validation per tool call; acceptable at local scale.
- SDK v2 still changes quickly (2.0 → 2.3 in six weeks); Dependabot bumps get reviewed against the MCP
  tests.
