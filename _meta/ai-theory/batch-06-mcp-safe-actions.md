# Batch 6 — MCP & safe actions

> **Topics:** #30 Model Context Protocol · #31 Tool & MCP authorization, on-behalf-of · #32 Human-in-the-loop approvals · #33 Tool permission model & audit log
> **Needed for:** Phase 2 (agent with real domain tools) · **Builds on:** batch-04 (#20 injection, lethal trifecta), batch-05 (#26 agent loop, #28 `search_kb`, #29 tool routing)
> **Written:** 2026-10-14
> **Verified with:** MCP spec **2026-07-28**, `mcp` Python SDK **2.3.0** (starlette 1.8.0, uvicorn 0.54.0, httpx 0.28.1, PyJWT 2.15.1, cryptography 50.0.2) on Python 3.13.16; PostgreSQL 16.15 + psycopg 3.3.6; openai 3.31.0. Keycloak 26.8 facts come from its docs only (no Keycloak binary was reachable from the sandbox). GitHub, AKS and Azure MCP servers were not run (no credentials); their facts are from their docs and listings.
> **Tested sketches:** tool registry + permission model, approval store, hash-chained audit log, token-exchange client, tool gate with a real in-memory MCP server — **41 pytest, all green** (Appendix A).

---

## 0. The picture

Batch 5 made the model *request* tool calls and the harness execute them. So far the only tool was `search_kb`: read-only, your own data, your own code. Phase 2 adds tools that live elsewhere (GitHub, AKS, Azure) and tools that change things (create an issue). This batch covers everything between "the model asked for X" and "X happened":

```
model tool call
   │
   ▼
① Where does the tool come from, and can its definition be trusted?   #30 MCP
② With whose authority does it run?                                    #31 OAuth for MCP, token exchange
③ Is this user allowed? Must a human agree first?                      #33 permission model + #32 approvals
④ What exactly happened, provably?                                     #33 audit log
   │
   ▼
side effect
```

One rule ties the four topics together: **the model proposes, the harness disposes.** Nothing the model writes counts as authority: not a tool name, not an argument, not "the user already approved this", and not an annotation a server claims about itself. Authority comes from three places only: the verified user token, the reviewed tool registry, and the user's own click on a separate endpoint.

> **Heads-up: MCP changed fundamentally on 28 July 2026.** Most tutorials, blog posts and v1 SDK examples describe the old session-based protocol (`initialize` handshake, `Mcp-Session-Id`, server-initiated requests). Revision 2026-07-28 is **stateless**. Read §1.3 before following any tutorial.

---

## 1. #30 Model Context Protocol

### 1.1 Why

Without a protocol, every agent integrates every API by hand: N agents × M services adapters. MCP is a protocol: a server exposes tools, resources and prompts once, and any MCP host (Claude, ChatGPT, VS Code, Cursor, your own harness) can discover and call them. It matters to kb-agent in two ways:

- **As a client**, kb-agent gets GitHub, AKS and Azure tools without writing API clients (P2 domain tools, plan §13.6).
- **As a server**, the knowledge base becomes usable from any MCP host. "Ask my runbooks from Claude Code" is a strong portfolio demo, and it is what plan §12 means by exposing `/v1/search` "through the MCP server".

But MCP is a transport for *capabilities*, and every capability you add is attack surface. The protocol tells you **how** to call a tool. It doesn't tell you **whether** you should. §2–§4 cover that part.

### 1.2 Mental model

| Role | Is | In kb-agent |
|---|---|---|
| **Host** | The application the user talks to; owns the LLM, the UI and the consent decisions | AI service (agent loop) + Angular UI |
| **Client** | One protocol connection from the host to one server | `mcp.client.Client` instances inside the AI service |
| **Server** | Exposes capabilities | GitHub MCP server, AKS MCP server, kb-agent's own `/mcp` |

| Primitive | Controlled by | Use |
|---|---|---|
| **Tools** | the **model** (it decides to call) | actions and queries: `search_kb`, `issue_write` |
| **Resources** | the **application** (it decides what to load) | readable data by URI: a document, an ADR |
| **Prompts** | the **user** (picks a template) | slash-command-like templates |

The model never talks to the server. The host lists tools, translates them into the LLM's `tools` array (batch 5), receives tool calls and calls the server. That's why every check in this batch lives in the host.

### 1.3 What 2026-07-28 changed, and why it matters

| Before (≤ 2025-11-25) | Now (2026-07-28) | Consequence for kb-agent |
|---|---|---|
| `initialize` / `initialized` handshake per connection | **No handshake.** Every request carries `_meta`: `io.modelcontextprotocol/protocolVersion`, `…/clientCapabilities`, `…/clientInfo` | Any request can hit any replica, so no sticky sessions behind a load balancer (P4/P5) |
| `Mcp-Session-Id` header, per-session state | **No protocol sessions.** Cross-call state uses explicit, server-minted handles passed as ordinary tool arguments | A handle is a name, not a capability: bind it to `sub` server-side |
| Optional version probing | `server/discover` (servers MUST implement it): supported versions, capabilities, identity | Cheap compatibility probe for `/readyz` |
| Server → client requests mid-call (`sampling/createMessage`, `elicitation/create`, `roots/list`) | **Multi Round-Trip Requests (MRTR):** the server returns `resultType: "input_required"` with `inputRequests` (+ an opaque `requestState`); the client retries the *same* request with `inputResponses` + `requestState` | Same shape as kb-agent's approval flow (§3.4): a stateless pause and resume |
| HTTP GET stream + `resources/subscribe` | `subscriptions/listen`: one long-lived POST stream, opt-in per notification type | Ignore in P2; re-list tools between turns |
| `ping`, `logging/setLevel` | Removed. Log level is set per request in `_meta` | — |
| SSE resumability (`Last-Event-ID`) | **Removed.** A broken stream loses the in-flight request; the client re-issues it with a new id | For non-idempotent tools, "re-issue" means "maybe executed twice" (§3.3) |
| Tasks in core | Official extension `io.modelcontextprotocol/tasks` (`tasks/get` polling, `tasks/update`) | Long-running operations later (P3+) |
| — | Required `Mcp-Method` / `Mcp-Name` headers on Streamable HTTP POSTs (mismatch → `-32020`) | A gateway or WAF can route and filter by tool without parsing JSON |
| — | `ttlMs` + `cacheScope` on list/read results; deterministic tool order (SHOULD) | Cache `tools/list`; a stable order keeps prompt-cache prefixes stable (#39) |
| Roots, Sampling, Logging | **Deprecated** (at least 12 months before removal) | Don't build on them; never offer sampling (a server spending your LLM budget) |
| Dynamic Client Registration (DCR) | DCR **deprecated** in favour of **Client ID Metadata Documents (CIMD)** | Affects external MCP hosts connecting to *your* server (§2.3) |
| Error codes | MCP range `-32020…-32099`: `HeaderMismatch -32020`, `MissingRequiredClientCapability -32021`, `UnsupportedProtocolVersion -32022`; resource-not-found is now `-32602` | Map these in your adapter |

Smaller items worth knowing: `inputSchema`/`outputSchema` may use any JSON Schema 2020-12 keyword; `structuredContent` can be any JSON value; OpenTelemetry context can travel in `_meta` (`traceparent`, `tracestate`, `baggage`), so your AI-service trace can continue into an MCP server you own.

### 1.4 The wire, verified (mcp 2.3.0 over Streamable HTTP)

A raw request and response (experiment 2, abbreviated):

```
POST /mcp
MCP-Protocol-Version: 2026-07-28              ← the SDK routes eras by this header (§1.5)
Mcp-Method: tools/call
Mcp-Name: search_kb
Authorization: Bearer …
{"jsonrpc":"2.0","id":1,"method":"tools/call",
 "params":{"name":"search_kb","arguments":{"query":"x"},
           "_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28",
                    "io.modelcontextprotocol/clientCapabilities":{"elicitation":{"form":{}}},
                    "io.modelcontextprotocol/clientInfo":{"name":"kb-agent","version":"0"}}}}

→ 200 {"result":{"content":[{"type":"text","text":"hits for x"}],"isError":false,
                 "resultType":"complete","structuredContent":{"result":"hits for x"},
                 "_meta":{"io.modelcontextprotocol/serverInfo":{…}}}}      ← no Mcp-Session-Id
```

| Probe | Result |
|---|---|
| `Mcp-Method`/`Mcp-Name` missing, or `Mcp-Name` ≠ the body's tool name | 400, `-32020` "mcp-name header does not match the request body's 'name' parameter" |
| `_meta` without `protocolVersion` | 400, `-32602` "params._meta must be an object carrying the required … envelope keys" |
| `server/discover` | `supportedVersions: ["2026-07-28"]`, capabilities, `ttlMs: 0`, `cacheScope: "private"` |
| `tools/list` result keys | `tools`, `ttlMs`, `cacheScope`, `resultType`, `_meta` |
| Tool returning a Pydantic model | `structuredContent` **and** the same JSON as text in `content` (spec SHOULD, for backwards compatibility) |
| Argument fails Pydantic validation | `isError: true` with the validation message, so the model can self-correct |
| Tool raises an exception | `isError: true`, text "Error executing tool boom"; the exception message (with a planted password) is not leaked |
| Tool with an `Annotated[Confirm, Resolve(ask)]` parameter | The parameter is **absent from `inputSchema`**, so the model can't pre-fill "confirmed: true". The call returns `resultType: "input_required"` with `inputRequests: {"…:ask": {"method": "elicitation/create", "params": {"mode": "form", …}}}` and `requestState: "v1.…"` (≈400 characters) |
| Retry with `inputResponses` + intact `requestState` | Completes |
| Tampered `requestState`; the same state with **another user's** token; the same state with **changed arguments** | All rejected: 400, `-32602` "Invalid or expired requestState" |
| `inputResponses` without `requestState` | The question is asked again; unsolicited answers are ignored |

Two lessons from MRTR:

1. The server's continuation state travels **through the client**, so it must be sealed and bound to user, request and expiry. The SDK does this (AES-256-GCM; expiry, principal, audience and request binding). A hand-rolled server must do the same.
2. "Ask the user, then retry the same request" is exactly the shape your approvals need (§3.4).

### 1.5 Python SDK 2.x gotchas (all verified)

- **`FastMCP` is gone.** Use `from mcp.server.mcpserver import MCPServer`; importing `mcp.server.fastmcp` raises with a migration hint. v1 tutorials won't run.
- Models use snake_case attributes (`tool.input_schema`, `result.is_error`, `result.structured_content`). Dump with `by_alias=True` to get wire names.
- **Era routing by header.** The HTTP app treats a POST as 2026-07-28 only if it carries `MCP-Protocol-Version: 2026-07-28`. Without the header it falls back to the legacy session transport: raw calls got "Missing session ID" plus a freshly minted `Mcp-Session-Id`. The SDK client sets the header; curl tests and hand-written clients must set it too.
- `RequestStateSecurity.ephemeral()` uses a per-process key, so two replicas can't read each other's `requestState`. In production pass `keys=[…]` from the secret store (the list is a rotation ring: `keys[0]` seals, every key unseals). Default TTL is 600 s.
- A client without an elicitation callback doesn't declare the capability. A tool that needs elicitation then fails with **`MCPError -32021`**, raised as an exception, not returned as an `isError` result. Your adapter must turn it into a tool message.
- Unknown tool: SDK 2.3.0 returns an `isError: true` result; the spec example uses a JSON-RPC `-32602` error. Handle both.
- Authorization: `MCPServer(token_verifier=…, auth=AuthSettings(issuer_url=…, resource_server_url=…, required_scopes=[…], validate_token_resource=True))` gives the 401/403 and Protected Resource Metadata behaviour of §2.3.

### 1.6 Plan mapping

**kb-agent as MCP server (own tools)**

- Keep tools as plain Python functions in `ai_service/tools/` (`search_kb`, `get_document`, `list_adrs`). The agent loop calls them **in-process**: no network hop, no serialization, no second token. A thin `MCPServer` adapter exposes the *same functions* at `/mcp` for external hosts, and a contract test asserts both paths return the same result for the same input. Routing your own agent through your own `/mcp` endpoint "eats the dog food" but costs latency and a second token for nothing.
- Read-only tools first: `readOnlyHint: true`, `openWorldHint: false`, output schemas generated from Pydantic.
- The AI service isn't browser-facing (plan §5). For a local demo with Claude Code or MCP Inspector, expose `/mcp` on localhost only; in P4/P5 it gets its own ingress route. It is a resource server in its own right (§2.3).

**kb-agent as MCP client (domain tools)**

| Server | How | Least-privilege knobs | Note |
|---|---|---|---|
| GitHub (DevOps) | Remote `https://api.githubcopilot.com/mcp/` or the `ghcr.io/github/github-mcp-server` image | `--read-only` / `X-MCP-Readonly: true` (overrides an explicit tool list); `--toolsets` / `X-MCP-Toolsets` (default `context, repos, issues, pull_requests, users`; add `actions` for CI triage); `--exclude-tools`; `--lockdown-mode` (on public repos, withholds content from authors without push access; GitHub calls it a best-effort filter, not an access limit); a fine-grained PAT limited to the kb-agent repo | Server-side filters are the second layer; your registry is the first (§4.2) |
| AKS (SRE) | `aks-mcp`, launched as a local stdio subprocess per its listing | `--access-level readonly` (default), `--allow-namespaces`, `--enabled-components` | Its docs call the access level "a guardrail … not a security boundary". The Azure identity it runs with must be read-only |
| Azure (Cloud) | Azure MCP server | read-only mode plus a Reader-only identity | Same rule: the credential is the boundary |

**Import pipeline** (per server, at startup and between turns):

1. `tools/list`.
2. Keep only reviewed tools whose **fingerprint** (sha256 of description + `inputSchema`) matches the pinned value.
3. Map names: `github__issue_write`. OpenAI-compatible APIs allow only `[A-Za-z0-9_-]`, max 64 characters (the openai 3.31 type docs say so), while MCP allows dots and 128 characters.
4. Attach a policy (§4.2).
5. Offer the subset this user may call to the model.

The tool list stays fixed within a turn (batch 5). A `list_changed` notification or an expired `ttlMs` takes effect at the next turn, after the pins are checked again.

**Tool results are untrusted data**, exactly like retrieved chunks (batch 4). GitHub is the textbook lethal trifecta: one token reads private repos (private data); issues and PR comments are written by strangers (untrusted content); and the same server can write comments and PRs in public repos (an exfiltration channel). Invariant Labs' disclosure of 26 May 2025 ("toxic agent flow") used exactly this combination: a malicious issue in a public repo made an agent copy private-repo data into a public pull request; their first mitigation was restricting each session to one repository. kb-agent's defences: a repo allow-list as an argument rule, read-only tools in P2, writes behind approval, lockdown mode, and never "private read" plus "public write" in one turn without an approval in between.

### 1.7 Pitfalls

1. **Following a pre-July-2026 tutorial.** Sessions, `initialize` and server-initiated sampling don't match the current spec or SDK 2.x.
2. **Trusting tool annotations.** The spec says clients MUST treat them as untrusted unless the server is trusted. A server can mark `delete_repository` as `readOnlyHint: true` (tested: the registry ignores it).
3. **Trusting tool descriptions.** They are prompt text written by a third party (tool poisoning), and they can change after you approved them (rug pull). Pin them and review changes.
4. **Feeding both `structuredContent` and its text twin into the prompt.** That doubles the tokens. Pick one per tool: structured for your own tools, capped text for external ones.
5. **Forgetting the defaults.** No annotations means `readOnlyHint=false`, `destructiveHint=true`, `openWorldHint=true`. Assume the worst.
6. **Exposing every tool a server offers.** GitHub's default toolsets contain dozens of tools: more selection errors, prompt bloat, bigger blast radius. Expose a reviewed handful.
7. **Name collisions and illegal characters.** Two servers can both offer `search`, and `.` is illegal in OpenAI-style tool names. Namespace and sanitise; don't rely on `serverInfo.name`, which isn't unique.
8. **Re-issuing a request after a dropped stream.** 2026-07-28 has no resumability. For a write, a dropped stream means "maybe executed": record it as `unknown` (§3.3).
9. **Running a local stdio server with your full Azure CLI login.** The access level isn't a boundary; the identity is.
10. **Hand-rolled `requestState` or state handles without sealing and user binding** (state-handle hijacking).

### 1.8 Self-check (#30)

1. Which three roles does MCP define, and which kb-agent component plays the host?
2. Name three changes in 2026-07-28 that remove per-connection state.
3. What is `requestState` for, and what must a server bind it to?
4. Why is `Annotated[Confirm, Resolve(ask)]` safer than a `confirmed: bool` tool parameter?
5. Why must the SDK's request-state key not be `ephemeral()` in production?
6. A tool from an untrusted server has no annotations. What risk do you assume?
7. Why should the agent call your own tools in-process instead of through your own `/mcp`?
8. Name the three legs of the lethal trifecta for the GitHub MCP server.

<details><summary>Answers</summary>

1. Host, client, server. The AI service (agent loop) plus the Angular UI form the host; each `mcp.client.Client` is a client.
2. Any three of: no `initialize` handshake (version and capabilities in every request's `_meta`); no `Mcp-Session-Id`; list results no longer vary per connection; server-initiated requests replaced by MRTR; GET stream and resumability removed.
3. It carries the server's continuation state through the client between MRTR rounds. Bind it to the authenticated principal, the original request (tool + arguments), an audience and an expiry, and seal it (integrity, ideally confidentiality).
4. The resolved parameter isn't in `inputSchema`, so the model can't supply it. The answer comes from the user via the client and is bound to this exact request.
5. A per-process key means another replica (or the same service after a restart) can't unseal the state, so multi-round calls fail. Use shared keys from the secret store with a rotation ring.
6. The spec defaults: not read-only, destructive, open-world. In kb-agent an unreviewed tool from an untrusted server isn't exposed at all.
7. No hop, no serialization, no second token, one place to authorize. The MCP adapter exists for *external* hosts; a contract test keeps the two paths equal.
8. Private data (the token reads private repos), untrusted content (issues and comments by strangers), an exfiltration channel (writing public comments or PRs).
</details>

---

## 2. #31 Tool & MCP authorization, on-behalf-of

### 2.1 Why

An agent with tools is a deputy: it acts with *some* credential. If that credential is broader than the user's rights (a shared admin token, or a forwarded user token that everything accepts), a fooled model or a malicious user turns the agent into a **confused deputy**. Every tool call needs provable answers to three questions:

1. **Who is the user?** From a signed token, never from a JSON field.
2. **Which client is acting?** `azp` (and later `act`), so the audit can say "kb-ai acting for bob".
3. **What may this token do here?** Audience (this service only) and scope (this operation only).

### 2.2 Two different problems

| | A. Client → MCP server | B. Server → downstream API on behalf of the user |
|---|---|---|
| Example | Claude Code calls kb-agent's `/mcp`; the AI service calls GitHub's remote MCP | The AI service calls a Keycloak-protected downstream (Nest, a future `kb-tools` service); an MCP server calls GitHub's REST API |
| Standard | MCP authorization spec: OAuth 2.1 + RFC 9728 + RFC 8707 + RFC 9207 + CIMD/DCR | RFC 8693 token exchange; URL-mode elicitation for third-party OAuth |
| Forbidden | Sending a token not issued by the MCP server's own authorization server | **Token passthrough**: forwarding the incoming token downstream |

### 2.3 Problem A: MCP authorization (2026-07-28)

**Flow:**

1. Request without a token → **401** with `WWW-Authenticate: Bearer resource_metadata="…/.well-known/oauth-protected-resource/mcp", scope="…"`.
2. The client fetches the **Protected Resource Metadata** (RFC 9728): `resource`, `authorization_servers`, `scopes_supported`.
3. It fetches the authorization server metadata (RFC 8414 or OIDC discovery; clients must support both).
4. Client registration, in priority order: **CIMD** (the `client_id` is an HTTPS URL pointing to a JSON metadata document), pre-registration, DCR (deprecated).
5. Authorization code flow with **PKCE** and **`resource=<canonical MCP server URL>`** in both the authorize and the token request (RFC 8707). Clients send it even if the AS ignores it.
6. The client validates `iss` in the authorization response against the issuer it recorded (RFC 9207, the mix-up defence).
7. Bearer token on every request, never in the query string.

**Server side (MUST):** validate the token per OAuth 2.1 §5.2 **and** check that it was issued for this server (audience). Invalid or expired → 401. Insufficient scope → **403** with `error="insufficient_scope", scope="…"`; the client then re-authorizes with the union of old and new scopes (step-up). Never accept or forward any other token.

**Verified with the SDK** (experiment 2): no token, wrong `aud` and expired token → 401 with `resource_metadata`; missing required scope → 403 `insufficient_scope` "Required scope: kb:read". The metadata is served at `/.well-known/oauth-protected-resource/mcp` (the path is inserted after the well-known prefix; the bare `/.well-known/oauth-protected-resource` returns 404, so clients must follow the URL in the header).

**Keycloak as the MCP authorization server** (Keycloak's MCP guide, nightly docs):

- Spec 2025-03-26 is supported; 2025-06-18 through 2026-07-28 are **experimental**.
- The `resource` parameter is **ignored** unless Keycloak runs with `--features=resource-indicators` (experimental). With it, the MCP server is registered as a client with a `resource_url` attribute, and unknown resources get `invalid_target`.
- CIMD needs `--features=cimd` plus a client policy (experimental). DCR is supported.
- Without those features, bind the audience with an optional client scope (e.g. `mcp:kb`) carrying an **Audience mapper whose "Included Custom Audience" is the canonical MCP URL**.
- RFC 9728 metadata is the MCP server's job; Keycloak's guide lists it on the MCP-server side, not as an authorization-server feature.

→ **P2 recommendation:** kb-agent's `/mcp` validates `aud == canonical URL` (`validate_token_resource=True`). Register MCP Inspector and Claude Code as **pre-registered public clients** with PKCE and the `mcp:kb` scope. No experimental Keycloak features needed; CIMD later.

**SSRF, for kb-agent as a client of remote MCP servers.** The discovery URLs (`resource_metadata`, `authorization_servers`, token endpoints) come from the server. The AI service runs inside your network, so: HTTPS only, block private and link-local ranges (`169.254.169.254` is the cloud metadata endpoint), validate every redirect hop, don't hand-roll IP parsing, and allow-list MCP server origins in configuration.

### 2.4 Problem B: on-behalf-of with Keycloak token exchange

RFC 8693 in one sentence: a confidential client presents a user's token (`subject_token`) to the authorization server and receives a new token for a different audience, still about the same user.

Keycloak **standard token exchange (V2)**, officially supported since 26.2 and on by default:

| Rule (Keycloak docs) | Consequence for kb-agent |
|---|---|
| The requester must be a **confidential** client with the per-client switch **"Standard token exchange"** on | `kb-api` and `kb-ai` qualify; `kb-web` (public) can't exchange |
| The subject token's `aud` must contain the requester | The browser token needs `aud ⊇ kb-api` (already true: audience mapper on `kb-web`); a token exchanged again by the AI service must contain `kb-ai` |
| `subject_token_type` must be an access token; `requested_token_type` access (default), ID or refresh | — |
| `audience` takes client ids and **filters** the audiences the requester's token would get; it never adds one | The target audience needs an Audience mapper on the requester's client scopes |
| `scope` **can add** the requester's optional scopes, so an exchange can *widen* the token, unless the **`downscope-assertion-grant-enforcer`** client-policy executor is configured | Configure the executor *and* check the result (the sketch rejects a widened scope) |
| The `resource` parameter is **not supported** in token exchange | MCP's RFC 8707 audience must come from a mapper, not from `resource` |
| Refresh tokens only on request, and only if "Allow refresh token in Standard Token Exchange" is on (default **No**) | Keep it off. CVE-2026-93999 (19 Sep 2026, CVSS 4.2): refreshing an exchanged token could restore an audience for a since-*disabled* client |
| Impersonation (acting as another user) isn't in V2 | Good; kb-agent never needs it |
| An `act` claim only comes with **token exchange delegation**: preview in 26.8.0 (`--features=token-exchange-delegation,parameterized-scopes`, fine-grained admin permissions v2, a `delegation:client:<client-id>` scope, plus an `actor_token`) | In P2 the actor shows up as `azp`; `act` is a P3+ option once it leaves preview |

Errors to map: `access_denied` (403) → tool message "not permitted"; `invalid_client` / `invalid_request` (400) → a configuration bug, so alert; 5xx → retry once.

### 2.5 kb-agent token topology

**Today (P1, D5).** Nest calls the AI service with a **client-credentials** token (`azp=kb-api`, `aud=kb-ai`) plus a JSON `user: {sub, roles}` object. The AI service has to *believe* that object: anyone holding the kb-api client secret can claim to be any user. That's fine for retrieving org-wide documents. It is not fine for tools that act.

**P2 (recommended):**

```
Browser ──(user token: azp=kb-web, aud=kb-api)──────────────▶ Nest
Nest ──exchange(subject=user token, audience=kb-ai)──▶ Keycloak ──▶ token: sub=bob, azp=kb-api, aud=kb-ai
Nest ──(exchanged token)──▶ AI service: validate iss, exp, aud=kb-ai, azp=kb-api → Principal(sub, roles, scopes)
AI service ──▶ own tools, in-process: authorize(Principal, tool, args)
AI service ──▶ GitHub MCP: server-side credential (see the options table below)
```

- The `user` body field goes away (or is ignored); roles come from the signed token. Check `azp == kb-api`, so a browser token that somehow carries `aud=kb-ai` can't call the AI service directly.
- Exchange once per chat request, cached per **subject token** until `exp − 30 s` (sketch). User tokens live 5 minutes (plan §7.7). A long agent turn, or an approval that waits 10 minutes, must not reuse the original token: the resume request arrives with a fresh one (§3.4). Never store tokens with pending actions.
- Verify in M2 that `realm_access.roles` survives the exchange. It depends on kb-api's role scope mappings, and "Full scope allowed" is deprecated in Keycloak 26.8.

**P3 (tools in separate services).** The AI service exchanges again (`audience=kb-tools`, `scope=github:write`). Each hop is narrower than the last, and each service validates its own audience.

**GitHub credential options:**

| Option | Who GitHub sees | Fits | Cost |
|---|---|---|---|
| Shared fine-grained PAT (one repo, read-only) in the AI service | the bot | P2 read tools | Attribution exists only in *your* audit log; harness RBAC is the only per-user gate |
| Same PAT with Issues: write, behind approval | the bot (the issue body says "created by kb-agent for bob, approval a1b2") | P2 write demo | Still a shared credential, so the approval and the audit carry the weight |
| Per-user tokens via Keycloak identity brokering (GitHub as an IdP, stored tokens, broker token endpoint) | the user | P3 writes "as the user" | A GitHub OAuth app, token storage, consent UX |
| GitHub tools inside your own MCP server + URL-mode elicitation for GitHub OAuth | the user | When the MCP server is reused by other hosts | You run the OAuth client and token store; the server becomes stateful |

Never forward the user's Keycloak token to GitHub (wrong issuer, wrong audience: passthrough), and never give the agent a PAT broader than the repo allow-list.

### 2.6 Roles vs scopes vs arguments

**Effective permission = role ∩ scope ∩ argument rules ∩ approval.**

- **Role:** what *bob* may do (editor). Keycloak realm roles (D6).
- **Scope:** what *this token* may do (`github:write`, only if the client requested it and bob consented). Keycloak client scopes.
- **Argument rules:** which *resources* (only repo `me/kb-agent`). They live in your registry, because neither Keycloak nor GitHub knows "only this repo for this agent".
- **Approval:** whether bob must confirm this specific action now.

### 2.7 Pitfalls

1. **Token passthrough:** forwarding the incoming token downstream. The downstream can't tell who validated what, and audiences blur.
2. **Checking the signature but not `aud`** (or not `azp`). A token minted for another service is still a valid token.
3. **Trusting identity from the request body** (the P1 `user` object) for anything that acts.
4. **Assuming exchange only narrows.** Keycloak's `scope` can widen unless the downscope enforcer is configured; check the result.
5. **Refresh tokens from token exchange** (default off; see CVE-2026-93999).
6. **Caching exchanged tokens by `sub`.** Key by the subject token, so logout and session revocation take effect and two sessions don't share a token.
7. **Executing an approved action with the token from the original request.** It may have expired, or the roles may have changed. Use the fresh token from the resume request.
8. **Building P2 on Keycloak's experimental MCP features** (`resource-indicators`, `cimd`); they may change in breaking ways.
9. **SSRF through MCP discovery URLs** when kb-agent is the client.
10. **Treating a tool's access level as the boundary** (AKS `readonly`, GitHub `--read-only`) instead of the credential behind it.
11. **Logging token-exchange form bodies.** `subject_token` is a live credential (see batch 4's `redact` rules).

### 2.8 Self-check (#31)

1. What three questions must every tool call answer, and which token claim answers each?
2. Why is P1's `user: {sub, roles}` body field acceptable for retrieval but not for write tools?
3. Name two Keycloak standard token exchange behaviours that surprise people who assume "exchange only narrows".
4. Why doesn't kb-agent pass `resource` in the token exchange, and how does the MCP audience get into the token instead?
5. An approval waits 10 minutes. Which token executes the action, and why?
6. What does the MCP server answer for a valid token that lacks the required scope, and what does the client do next?
7. What is token passthrough, and why is it forbidden?
8. Compare a shared fine-grained PAT with per-user brokered GitHub tokens: what does each mean for attribution?

<details><summary>Answers</summary>

1. Who is the user (`sub` from a verified token), which client acts (`azp`, later `act`), what may this token do here (`aud` + `scope`).
2. Retrieval of org-wide documents doesn't depend on who asks. For actions, identity drives authorization and audit, and anyone with the kb-api secret could claim any `sub`.
3. `scope` can add optional scopes (widening) unless `downscope-assertion-grant-enforcer` is configured; `audience` filters but never adds; refresh tokens can be issued if the client allows it; `resource` is ignored.
4. Keycloak's token exchange doesn't support `resource`. An Audience mapper on a client scope ("Included Custom Audience" = canonical URL) puts the audience into tokens; with token exchange you pass the target client id in `audience`.
5. A fresh token from the resume request (exchanged again). The original one may have expired after 5 minutes, and the user's roles must be re-checked at execution time.
6. 403 with `WWW-Authenticate: Bearer error="insufficient_scope", scope="…", resource_metadata="…"`. The client re-authorizes with the union of previously requested and newly challenged scopes, then retries a bounded number of times.
7. A server forwarding the token it received to another API. It breaks audience boundaries, bypasses the downstream's controls and destroys attribution; MCP servers must only accept tokens issued for themselves.
8. Shared PAT: GitHub sees the bot, attribution exists only in kb-agent's audit log, and the harness is the only per-user gate. Brokered per-user tokens: GitHub sees and enforces the user's own rights, at the cost of an OAuth app and token storage.
</details>

---

## 3. #32 Human-in-the-loop approvals

### 3.1 Why

- Batch 4 established that **the model will be fooled**. Read-only tools bound the damage to what the user sees; write tools turn a fooled model into an actor. The OWASP LLM Top 10 2026 moved Excessive Agency up to #3.
- The MCP tools spec says there SHOULD always be a human able to deny tool invocations, with clear indicators when tools run and confirmation prompts for operations.
- An approval is only worth something if it is **specific** (this exact action), **fresh** (now, by this user), **unforgeable** (neither the model nor the client can fake it) and **binding** (exactly what was approved runs, exactly once).

### 3.2 What to gate

| Tier | Examples | Default | Who may approve |
|---|---|---|---|
| READ | `search_kb`, `issue_read`, `kubectl get` | runs without a prompt | — |
| WRITE (reversible, contained) | create an issue, comment, add a label | approval every time | the requester, role ≥ editor |
| DESTRUCTIVE / external effect | delete, merge, deploy, scale, send | approval + admin; in P2 simply not exposed | the requester, role admin (later: a second person) |
| FORBIDDEN | anything not reviewed | never exposed | — |

**Approval fatigue is real.** If every read asks for confirmation, users start clicking "Approve" without reading. Gate writes only, keep them rare, and make the prompt specific enough to read in five seconds.

### 3.3 The pending-action state machine

```
pending ──approve──▶ approved ──claim──▶ executing ──▶ succeeded | failed
   │                    │                    └── crash / stale ──▶ unknown   (never retried automatically)
   ├──reject──▶ rejected
   └──TTL────▶ expired              approved but not claimed within 60 s ──▶ expired
```

Each transition is a single conditional `UPDATE … WHERE status = … RETURNING`, the same pattern batch 2 verified for ingestion. Invariants, each covered by a test:

1. **Bound to the requester.** Only the requester's `sub` (from the token) can decide or resume. Anyone else gets "not found", so the endpoint isn't an existence oracle.
2. **Bound to the content.** The UI echoes the **action hash** (sha256 of tool + canonical, validated arguments). A mismatch returns `changed`, so nothing can change between what was shown and what runs. Execution uses the **stored** arguments, never a client copy.
3. **Fresh.** 10 minutes to decide; an approval not claimed within 60 seconds expires.
4. **Exactly once.** With 8 concurrent approve/reject requests there was 1 winner and 7 × `already_decided`; with 16 concurrent claims, 1 executor. A second resume returns the stored result without executing again.
5. **Re-authorized at decision time and at execution time.** If bob's role is revoked after he approved, the action is denied and not executed.
6. **"Unknown" is a state.** A crash while `executing` turns into `unknown` after 5 minutes. It is shown to the user and never retried automatically: GitHub's create-issue API has no idempotency key, so a retry may create a duplicate.
7. **A rejection is information for the model.** It receives "The user rejected this action. Do not retry it." (+ the user's note), so it doesn't propose the same action again in a loop.
8. **Approval is not a tool.** Decisions arrive on a separate endpoint with the user's own token. The model never sees an approval secret, and "the user already approved this" in a message or a document changes nothing.

### 3.4 Approvals in a stateless streaming chat

kb-agent's chat is stateless and streamed (D12). An approval must pause a turn and resume it later, possibly from another replica:

```
Browser                         Nest                              AI service                        GitHub MCP
POST /api/chat ───────────────▶ auth, exchange ─────────────────▶ loop: model → issue_write(args)
                                                                  gate → pending row (+ turn snapshot)
◀── SSE approval_required {approvalId, tool, server, risk, args, actionHash, reason, expiresAt}
◀── SSE done {stopReason: "awaiting_approval"}
   (user reads the card, clicks Approve)
POST /api/approvals/{id} {decision, actionHash, note} ──────────▶ decide() + audit approval.approved
POST /api/chat {messages, resume: {approvalId}} ─▶ fresh token ─▶ resume(): re-authorize, claim,
                                                                  execute ─────────────────────────▶ tools/call
                                                                  append stored snapshot + tool result,
                                                                  continue the loop
◀── SSE tool_result, token …, done
```

| | MCP MRTR | kb-agent approval |
|---|---|---|
| Pause signal | `resultType: "input_required"` | SSE `approval_required` + `done.stopReason: "awaiting_approval"` |
| Continuation state | `requestState`, sealed, travels through the client | `pending_actions` row + turn snapshot, server-side; the client holds only the id |
| Binding | principal + request + audience + TTL | requester `sub` + action hash + TTL + single-use claim |
| Resume | retry the same request with `inputResponses` | `POST /api/chat` with `resume.approvalId` |
| Answer comes from | the client, on the user's behalf | the user's own HTTP request, with the user's own token |

Why server-side state here: the turn snapshot contains the assistant message with its tool calls, the results of the other calls in that step and `reasoning_details`, which must be echoed unchanged (batch 5). It is big, and the client must not be able to forge tool results (batch 5's history is client-held). A sealed blob would also work, but it is larger and still needs a single-use record for exactly-once execution.

**One pending approval per turn.** If the model emits several write calls in one step, the first one becomes the pending action; the others get the tool message "Only one action can await approval at a time; propose it again after this one is decided." Read calls in the same step run normally.

### 3.5 The approval card (UI rules)

- **Who and what:** server + human-readable title ("GitHub · Create issue"), a risk badge, and the target resource (repo).
- **The exact arguments**, field by field, not the model's summary. Long text in a scrollable monospace block; invisible characters stripped and flagged (batch 4); URLs shown as plain text, never as links.
- **The model's explanation**, labelled "Agent's explanation (may be wrong)".
- **Context:** which turn, when requested, time left.
- **Buttons:** Reject and Approve, plus an optional note. Reject has default focus for destructive actions. Keyboard-accessible; the decision is announced with `aria-live`.
- **The action hash** goes back with the decision.
- **No editing in P2.** An edited action is a new action with a new hash (P3). No "always allow" in P2 either (later: per-tool allowances for low-risk writes, each one recorded in the audit log).
- **Afterwards:** show the outcome (e.g. a link to the created issue, taken from the structured result).
- **After a reload:** `GET /api/approvals?status=pending` brings open cards back.

### 3.6 Elicitation from external MCP servers (P2 policy)

An elicitation is a *server* asking the *user* something mid-call. It is not an approval of kb-agent's action, so keep the two apart.

- **P2:** kb-agent's MCP clients **don't declare elicitation**. A server that needs input fails with `-32021`; the adapter turns that into the tool message "This tool needs interactive input, which kb-agent doesn't support yet."
- **P3:** render elicitations in the same card component. Show which server is asking. Form mode only for non-secret data (the spec forbids passwords, API keys, tokens and payment data in form mode). URL mode: show the full URL with the host highlighted, open it only on an explicit click, never prefetch it, never open it anywhere the agent can read the page. Treat a timeout as "cancel".

### 3.7 Pitfalls

1. **Approval as a tool, a tool argument (`confirm: true`) or text the model can produce.**
2. **Approving a description instead of the action:** the model's summary instead of the exact arguments.
3. **Executing the client's copy of the arguments on approval** instead of the stored copy.
4. **No TTL:** approvals that live forever.
5. **Double execution** on a double click, a retry or two replicas.
6. **Retrying an `unknown` write.**
7. **Reusing the original access token after approval** (expired, or roles revoked in the meantime).
8. **Approval fatigue** from gating reads.
9. **Rendering links or Markdown in the arguments.** A click is an exfiltration channel (batch 4).
10. **Accepting client-supplied tool results** for an approved action (forged history).
11. **Pending actions that vanish on reload.**

### 3.8 Self-check (#32)

1. What four properties make an approval meaningful?
2. Why does the UI send the action hash back with the decision?
3. Why does `resume` use the stored arguments and a fresh token?
4. What happens when 16 workers try to execute the same approved action, and which SQL pattern guarantees it?
5. A process crashes while an issue is being created. What status does the action get, and why isn't it retried?
6. Why does the model get "The user rejected this action. Do not retry it." instead of nothing?
7. How does kb-agent's approval flow resemble MCP MRTR, and where does it differ?
8. What is kb-agent's P2 policy for elicitation requests from external servers?

<details><summary>Answers</summary>

1. Specific, fresh, unforgeable, binding.
2. It proves the user approved exactly the action stored on the server. If anything differs (a race, a bug, tampering), the decision fails with `changed` instead of approving something unseen.
3. Stored arguments: the client must not be able to change what runs. Fresh token: the original may have expired, and roles must be re-checked at execution time.
4. Exactly one wins. `UPDATE pending_actions SET status='executing' … WHERE id=$1 AND status='approved' AND decided_at > now() - 60 s RETURNING *`; the others get no row.
5. `unknown` (from `executing`, via boot recovery). The side effect may have happened, and GitHub's create-issue call has no idempotency key, so a retry could create a duplicate. The user checks.
6. So it can tell the user and continue, instead of proposing the same action again in a loop.
7. Both pause a request and resume it with the user's answer, bound to user, request and TTL. MRTR keeps sealed state in the client and lets the client answer; kb-agent keeps state server-side, the answer comes from the user's own request, and execution is claimed exactly once.
8. Don't declare the capability; turn `-32021` into a tool message. Render elicitations in P3 with form mode for non-secrets only and URL mode behind an explicit click.
</details>

---

## 4. #33 Tool permission model & audit log

### 4.1 Why

Batch 5's harness validated arguments and capped steps, but every tool was allowed for everyone. With real tools you need two things:

- a **permission model** that decides per user, per tool and per resource, in code, before anything runs;
- an **audit log** that answers "who did what, under which decision" months later, even if someone tries to rewrite history.

Prompts aren't access control ("never call delete" is a suggestion to a model that will be fooled). Traces aren't an audit trail (sampled, short retention, full of prompts).

### 4.2 The permission model

A `ToolPolicy` per exposed tool, built from your own code (trusted) or from a reviewed MCP import:

| Field | Example | Why |
|---|---|---|
| `name` / `server` / `remote_name` | `github__issue_write` / `github` / `issue_write` | Namespacing, portable names |
| `risk` | `WRITE` | Picks the tier defaults |
| `min_role` | `editor` | D6 realm roles |
| `scopes` | `{github:write}` | The token must carry them |
| `approval` | `true` | Tier default; a review may tighten it, never loosen it |
| `arg_rules` | `repo_allowlist("me/kb-agent")` | Resource-level policy |
| `redact` | `{"body"}` | Audit preview |
| `timeout_s` / `max_result_chars` | 20 / 8,000 | Bounds latency and prompt size |
| pinned fingerprint | sha256(description + schema) | Rug-pull detection |

Add a per-user rate limit for writes (e.g. 10 per hour; not in the sketch).

**Three enforcement points:**

1. **Exposure (per turn).** Only tools the user could ever be allowed to call go into `tools`. The MCP spec allows `tools/list` to vary by the presented authorization. This means less confusion, fewer wasted steps and a smaller prompt, but it is **not** a security boundary on its own.
2. **Execution (per call), the authoritative check.** Registry lookup → schema validation → role ∩ scope ∩ argument rules → approval → timeout → result cap.
3. **Downstream.** The credential itself: a fine-grained PAT, a Reader identity, an audience-bound token. This is what still holds if 1 and 2 have a bug.

**External servers.** The reviewed allow-list (e.g. `tools/allowlist.yaml`) lives in the repo and changes through PR review: tool name, risk, scopes, argument rules, pinned fingerprint. Annotations from untrusted servers are ignored; unreviewed tools are skipped and logged (`mcp.tool_skipped`); a fingerprint mismatch disables the tool until it is reviewed again.

**Tracing.** Add `kb.authz.decision`, `kb.approval.id` and `kb.tool.server` to the `TOOL` span (batch 5's span tree). OpenInference also has a `GUARDRAIL` span kind if you want the check as its own span. The audit row carries the `trace_id`, so you can click through.

### 4.3 The audit log

| | Audit log | App logs | Traces (Phoenix) |
|---|---|---|---|
| Answers | Who did what, under which decision | What went wrong | Why it was slow; what the model saw |
| Completeness | Every security-relevant event, no sampling | Best effort | May be sampled |
| Content | ids, decisions, redacted arguments, fingerprints | ids, errors | Full prompts and tool payloads |
| Mutability | Append-only, tamper-evident | Rotated | Deleted by retention |
| Retention | Longest (policy, e.g. 1 year) | Days to weeks | 14 days (batch 4) |
| Linked by | `trace_id`, `request_id`, `approval_id` | same ids | `trace_id` |

**Events:** `tool.executed`, `tool.failed`, `tool.denied`, `approval.requested`, `approval.approved`, `approval.rejected`, `approval.expired`, `approval.unknown`, `mcp.tool_skipped`, `mcp.tools_changed`, `auth.exchange_denied`.

**Fields:** `ts`, `event`, `sub`, `actor` (`azp`/`act`), `tool`, `server`, `risk`, `decision`, `reason`, `approval_id`, `trace_id`, `request_id`, `args_preview` (redacted, truncated), `args_fp` (HMAC), `result_status`, `result_fp`, `prev_hash`, `hash`.

**Not stored:** tokens, full results, prompts (they're in traces with short retention), names and e-mail addresses (`sub` only).

**Who writes.** The component that performs the action: the AI service executes tools, so it writes the tool and approval events. Nest keeps auditing its own domain (document upload and delete); `request_id` joins the two.

**Tamper evidence (verified on PostgreSQL 16.15):**

| Control | Result |
|---|---|
| Insert-only grants for the app role | `UPDATE`, `DELETE`, `TRUNCATE` → `InsufficientPrivilege` |
| Hash chain: edit a row | detected ("content was modified") |
| Hash chain: delete a row in the middle | detected (`prev_hash` mismatch) |
| Hash chain: cut the tail cleanly | **not detectable without an anchor**; detected with one |
| 8 writers × 20 appends **without** a lock | chain broken in **10/10** trials (writers read the same head and fork) |
| Same load **with** `pg_advisory_xact_lock` | 160/160 rows, chain linear (repeated over 4 runs) |

**The anchor.** Periodically (nightly, and on every deploy) copy the head hash somewhere the database's admins can't rewrite: a CI artifact, object storage with a retention lock (Azure immutable blob storage in P5), or a signed log line. A hash chain doesn't stop a DBA; it makes silent rewriting detectable.

**Privacy.**
- Store `sub` (a pseudonymous id), not names.
- Argument previews can contain personal data, so redact secret-looking keys and values, truncate long strings, and fingerprint with **HMAC**, not plain SHA-256. A plain hash of `{"pin":"1234"}` can be brute-forced offline; an HMAC with a key from the secret store can't (tested).
- Document the retention period (it goes into the system card, #59).
- Deletion requests vs append-only: the standard trick is crypto-shredding (encrypt previews per user, delete the key). Decide in P3+.

**Fail closed for writes.** If the audit insert fails, don't execute the write. An action you can't record shouldn't happen. The sketch records `approval.requested` before execution and `tool.executed`/`tool.failed` after.

### 4.4 Pitfalls

1. **"Access control" in the prompt.** Prompts aren't permissions.
2. **Hiding tools as the only control.** Exposure filtering is convenience; execution checks are the boundary.
3. **Checking roles without scopes**, or scopes without roles.
4. **No resource-level rules.** A role says "may create issues", not "in which repo".
5. **Annotation-driven policy for untrusted servers.**
6. **An audit log that stores everything** (tokens, full arguments, prompts). It becomes a data leak with long retention.
7. **Using traces or app logs as the audit trail** (sampling, retention, mutability).
8. **A hash chain without serialization** (forks) **or without an anchor** (truncation).
9. **Audit written by a component other than the executor.** A crash between action and report leaves a gap.
10. **An app role with `UPDATE`/`DELETE` on the audit table.**
11. **Plain hashes of low-entropy arguments.**
12. **Executing a write when the audit insert failed.**

### 4.5 Self-check (#33)

1. Name the three enforcement points, and say which one is authoritative.
2. Which four sets intersect to give the effective permission for a tool call?
3. How does the registry handle a tool from an untrusted server whose description changed since review?
4. Why do audit, logs and traces need to be separate?
5. What did the experiment show about hash-chain writers without a lock, and what fixes it?
6. Which tampering does a hash chain detect on its own, and which needs an anchor?
7. Why HMAC instead of SHA-256 for argument fingerprints?
8. Why must the AI service, not Nest, write the `tool.executed` record?

<details><summary>Answers</summary>

1. Exposure (which tools the model sees), execution (the authoritative check before each call), downstream (the credential's own limits).
2. Role, token scope, argument rules, approval policy.
3. The fingerprint (sha256 of description + `inputSchema`) no longer matches the pin, so the tool is skipped (`mcp.tool_skipped`) until someone reviews it again.
4. Different questions, completeness, content and retention. The audit log must be complete, minimal and append-only; traces are sampled, hold full prompts and expire after 14 days; logs are best-effort.
5. 8 writers × 20 appends forked the chain in 10/10 trials. A transaction-scoped advisory lock (`pg_advisory_xact_lock`) serializes appends: 160/160 rows, linear.
6. On its own: edits and deletions in the middle (and forks). With an anchor (a head hash stored outside the database): truncation of the tail and a rewritten chain.
7. Low-entropy values (PINs, short names) can be brute-forced from a plain hash; an HMAC needs the secret key.
8. The writer must be the component that performed the action; otherwise a crash between the action and the report leaves an unrecorded side effect.
</details>

---

## 5. Change list for the Phase 2 plan

No Phase 2 plan exists yet (open question in DONE.md). Apply these together with the change lists in batch-03 §8, batch-04 §C and batch-05 §5.

| # | Plan item | Change |
|---|---|---|
| 1 | D3 service split | The AI service hosts the **tool gateway** (registry, gate, approvals, audit) and an MCP adapter at `/mcp` for its own tools. The agent calls its own tools in-process; a contract test keeps both paths equal. |
| 2 | D5 service auth | Replace the `user` body object with **RFC 8693 exchange in Nest** (`audience=kb-ai`). The AI service validates `aud=kb-ai` and `azp=kb-api` and builds the principal from the token. Exchange cache keyed by subject token; no refresh tokens; `downscope-assertion-grant-enforcer`; check in M2 that roles survive the exchange. |
| 3 | §7.7 Keycloak realm | "Standard token exchange" on `kb-api` (and on `kb-ai` once P3 needs a second hop); a client policy with the downscope enforcer; optional client scopes `github:write` and `mcp:kb` (Audience mapper = canonical MCP URL); pre-registered public client(s) with PKCE for MCP Inspector / Claude Code. |
| 4 | D6 RBAC | Role ↔ tier mapping: viewer = READ; editor = WRITE with approval; admin = DESTRUCTIVE with approval (not exposed in P2). |
| 5 | D12 / §7.3 SSE | New event `approval_required` `{approvalId, tool, server, title, risk, args, actionHash, reason, expiresAt}`; `done.stopReason` gains `awaiting_approval`; resume via `POST /api/chat` `{messages, resume: {approvalId}}`. |
| 6 | §7.1 / §7.2 endpoints | `POST /api/approvals/{id}` `{decision, actionHash, note}` → `POST /v1/approvals/{id}`; `GET /api/approvals?status=pending`. problem+json mapping: `not_found` 404, `changed` 409, `already_decided` 409, `expired` 410, `forbidden` 403. |
| 7 | Data | The AI service gets Postgres access (schema `agent`): `pending_actions` (with the turn snapshot) and `audit_events`; an insert-only role for the audit table; a sweeper for expiry; boot recovery `executing` → `unknown`; a nightly head-hash anchor. |
| 8 | D2 versions | MCP spec 2026-07-28; pin `mcp==2.3.0` (SDK 2.x API). Keycloak **26.8.0** was released on 1 Oct 2026 (the plan says 26.7.x). |
| 9 | Appendix A env vars | `MCP_PUBLIC_URL` (canonical), `MCP_REQUEST_STATE_KEYS`, `MCP_GITHUB_URL`, `MCP_GITHUB_TOKEN` (fine-grained PAT, AI service only), `TOOLS_ALLOWLIST_PATH`, `APPROVAL_TTL_S=600`, `APPROVAL_EXECUTE_WINDOW_S=60`, `AUDIT_FP_KEY`, `AGENT_DATABASE_URL`. |
| 10 | §13.6 Phase 2 tools | Read-only domain tools plus exactly one write (`github__issue_write`) behind approval; AKS/Azure with Reader identities; repo allow-list; GitHub lockdown mode. |
| 11 | §11 Risks | Add: tool poisoning / rug pull (pins), GitHub toxic flow (allow-list, lockdown, approval), approval fatigue, SSRF via MCP discovery, reliance on Keycloak's experimental MCP features. |
| 12 | P2 Definition of Done | Exactly-once approval test; role-revoked-after-approval test; untrusted-annotation test; `-32021` handling; audit chain verified in CI; the requestState key shared across replicas. |
| 13 | ADRs | ADR-0009 "Tool gateway: registry, approvals, audit"; ADR-0010 "Identity for tools: token exchange and the GitHub credential" (numbers assume ADR-0008 is the latest). |

---

## 6. Verification log

| What | How | Result |
|---|---|---|
| Current MCP revision and its changes | 2026-07-28 changelog, tools, authorization, elicitation and security pages | Stateless core, MRTR, `server/discover`, CIMD over DCR, new error codes (§1.3) |
| SDK version and API | `pip index versions mcp`; installed 2.3.0; read `mcp_types.version`, `MCPServer`, `Client`, `resolve.py`, `request_state.py` | Known versions 2024-11-05 … 2026-07-28; `FastMCP` → `MCPServer` |
| Wire behaviour | Experiments 1 + 2: in-memory and Streamable HTTP on uvicorn, raw httpx | Table in §1.4 |
| MRTR state security | Tampered state, replay by another user, changed arguments | All rejected (`-32602`) |
| Missing elicitation capability | Experiment 3 | `MCPError -32021` raised |
| Unknown tool | Experiments 1 + 3 | `isError: true` result (spec example: `-32602` error) |
| OAuth resource-server behaviour | `token_verifier` + `AuthSettings`, RS256 tokens from PyJWT | 401 for none/wrong-aud/expired, 403 `insufficient_scope`, PRM path |
| OpenAI tool-name constraint | openai 3.31.0 `FunctionDefinition.name` docs | `[A-Za-z0-9_-]`, max 64 |
| Approval races | PostgreSQL 16.15, psycopg 3.3.6, 8 and 16 threads behind a barrier | 1 winner each; stable over 4 runs |
| Audit chain | Same DB; unlocked vs advisory lock; insert-only role | 10/10 forks unlocked; 0 with lock; grants enforced |
| Token exchange client | httpx `MockTransport` emulating Keycloak's documented behaviour | Request shape, cache, error mapping, widening/aud/azp/refresh checks |
| **Not verified** | — | Keycloak's actual exchange behaviour (no binary reachable), Keycloak MCP features, GitHub/AKS/Azure MCP servers (no credentials) |

---

## Appendix A — Tested sketches

Package `kbtools/` (Python 3.13, `mcp==2.3.0`, `psycopg[binary]`, `jsonschema`, `httpx`). Tests need a PostgreSQL DSN in `KB_TEST_DSN` (default `postgresql://kb:kb@localhost/kbtest`); DB tests are skipped without one.

| File | Tests | What they prove |
|---|---|---|
| `test_policy.py` | 11 | Annotation defaults; untrusted servers expose only reviewed tools; a lying `readOnlyHint` is ignored; rug pull disables the tool; trusted servers use annotations; reviews can't loosen approval; portable names and collisions; role/scope/argument matrix; deterministic visible-tool list |
| `test_token_exchange.py` | 8 | RFC 8693 request shape + client auth; cache per subject token with skew; 403 → `forbidden`; 400 → `config`; widened scope, wrong `aud`, wrong `azp` and refresh tokens rejected |
| `test_approvals.py` | 6 | Happy path; double click; binding to hash, owner, role and expiry; approve/reject race (8 threads → 1 winner); parallel claims (16 → 1); unclaimed approval expires; stuck execution → `unknown` |
| `test_audit.py` | 5 | Edit/delete/truncation detection (truncation only with an anchor); fork without a lock; 8 × 20 concurrent appends with a lock; insert-only role; redaction + HMAC fingerprints |
| `test_gate.py` | 11 | With a real in-memory MCP server: untrusted filtering; injected text in a read result stays data; viewer denied; unreviewed/unknown denied; argument rule; invalid arguments never reach the server; approval → exactly-once execution; rejection message; role revoked after approval; another user can't resume; generic crash message + chain verifies |

### A.1 Permission model and MCP import — `kbtools/policy.py`

```python
"""Tool permission model (#33): registry, MCP import with trust + pinning, authorization.

Rules:
- Deny by default. A tool the registry doesn't know is never exposed or executed.
- Effective permission = realm role (what the user may do) ∩ token scope (what this token may do)
  ∩ argument rules (which resources) ∩ approval policy (whether a human must confirm).
- Annotations from an MCP server are hints. From an untrusted server they are ignored; only reviewed,
  pinned tools are exposed, with the risk we assigned at review time.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Literal


class Risk(IntEnum):
    READ = 1
    WRITE = 2
    DESTRUCTIVE = 3


ROLE_RANK = {"viewer": 1, "editor": 2, "admin": 3}

# Default policy per risk tier (D6 roles). A reviewed tool may tighten it, never loosen below these.
TIER_DEFAULTS: dict[Risk, dict[str, Any]] = {
    Risk.READ: {"min_role": "viewer", "approval": False},
    Risk.WRITE: {"min_role": "editor", "approval": True},
    Risk.DESTRUCTIVE: {"min_role": "admin", "approval": True},
}

ArgRule = Callable[[dict[str, Any]], "str | None"]  # returns a denial reason or None


@dataclass(frozen=True)
class Principal:
    sub: str
    roles: frozenset[str]
    scopes: frozenset[str]

    @property
    def rank(self) -> int:
        return max((ROLE_RANK.get(r, 0) for r in self.roles), default=0)


@dataclass(frozen=True)
class ToolPolicy:
    name: str                       # model-facing name, unique across servers
    server: str                     # "local" or an MCP server id
    remote_name: str                # name on that server
    description: str
    input_schema: dict[str, Any]
    risk: Risk
    min_role: str
    scopes: frozenset[str] = frozenset()
    approval: bool = False
    arg_rules: tuple[ArgRule, ...] = ()
    redact: frozenset[str] = frozenset()   # argument keys never written to the audit log in clear
    timeout_s: float = 20.0
    max_result_chars: int = 8_000


@dataclass(frozen=True)
class Decision:
    outcome: Literal["allow", "approval", "deny"]
    reason: str


def fingerprint(description: str, input_schema: dict[str, Any]) -> str:
    """Hash of what the model sees. Pinned at review; any change disables the tool (rug pull)."""
    blob = json.dumps({"d": description, "s": input_schema}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


_NAME_OK = re.compile(r"[^A-Za-z0-9_-]")


def model_tool_name(server: str, remote: str) -> str:
    """MCP allows dots and 128 chars; OpenAI-style function names allow [A-Za-z0-9_-], max 64."""
    name = _NAME_OK.sub("_", f"{server}__{remote}")
    if len(name) > 64:
        digest = hashlib.sha256(name.encode()).hexdigest()[:8]
        name = f"{name[:55]}_{digest}"
    return name


@dataclass(frozen=True)
class Review:
    """An entry in the reviewed allow-list for an external server (lives in the repo, code-reviewed)."""
    remote_name: str
    risk: Risk
    pinned: str                      # fingerprint at review time
    scopes: frozenset[str] = frozenset()
    arg_rules: tuple[ArgRule, ...] = ()
    redact: frozenset[str] = frozenset()
    approval: bool | None = None     # None = tier default; True can tighten READ; False never loosens WRITE+


@dataclass
class ImportReport:
    exposed: list[ToolPolicy] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)   # remote name -> reason (logged, never shown to model)


def risk_from_annotations(ann: dict[str, Any] | None) -> Risk:
    """Spec defaults: readOnlyHint=false, destructiveHint=true (when not read-only)."""
    ann = ann or {}
    if ann.get("readOnlyHint", False):
        return Risk.READ
    return Risk.DESTRUCTIVE if ann.get("destructiveHint", True) else Risk.WRITE


def import_mcp_tools(server: str, tools: list[dict[str, Any]], *, trusted: bool,
                     reviews: dict[str, Review] | None = None) -> ImportReport:
    """Turn a tools/list result (wire format dicts) into policies."""
    reviews = reviews or {}
    rep = ImportReport()
    seen: set[str] = set()
    for t in tools:
        remote, desc, schema = t["name"], t.get("description", ""), t.get("inputSchema", {})
        fp = fingerprint(desc, schema)
        review = reviews.get(remote)
        if review is not None:
            if review.pinned != fp:
                rep.skipped[remote] = "definition changed since review"
                continue
            risk = review.risk
        elif trusted:
            risk = risk_from_annotations(t.get("annotations"))
        else:
            rep.skipped[remote] = "not in reviewed allow-list"
            continue
        tier = TIER_DEFAULTS[risk]
        approval = tier["approval"]
        if review is not None and review.approval is True:
            approval = True                      # tightening is allowed; loosening is ignored
        name = model_tool_name(server, remote)
        if name in seen:
            rep.skipped[remote] = f"name collision on {name}"
            continue
        seen.add(name)
        rep.exposed.append(ToolPolicy(
            name=name, server=server, remote_name=remote, description=desc, input_schema=schema,
            risk=risk, min_role=tier["min_role"], approval=approval,
            scopes=review.scopes if review else frozenset(),
            arg_rules=review.arg_rules if review else (),
            redact=review.redact if review else frozenset(),
        ))
    return rep


def authorize(p: Principal, pol: ToolPolicy, args: dict[str, Any] | None) -> Decision:
    if p.rank < ROLE_RANK[pol.min_role]:
        return Decision("deny", f"requires role {pol.min_role}")
    missing = pol.scopes - p.scopes
    if missing:
        return Decision("deny", f"token lacks scope {' '.join(sorted(missing))}")
    if args is not None:
        for rule in pol.arg_rules:
            why = rule(args)
            if why:
                return Decision("deny", why)
    return Decision("approval" if pol.approval else "allow", "ok")


def visible_tools(p: Principal, registry: list[ToolPolicy]) -> list[ToolPolicy]:
    """Tools offered to the model this turn: only those the user could ever be allowed to call.
    Argument rules still run at execution time."""
    return sorted((t for t in registry if authorize(p, t, None).outcome != "deny"), key=lambda t: t.name)


def repo_allowlist(*repos: str) -> ArgRule:
    allowed = {r.lower() for r in repos}

    def rule(args: dict[str, Any]) -> str | None:
        repo = f"{args.get('owner', '')}/{args.get('repo', '')}".lower()
        return None if repo in allowed else f"repository {repo} is not allowed"
    return rule
```

### A.2 Canonical arguments, fingerprints, redaction — `kbtools/canonical.py`

```python
"""Canonical arguments and fingerprints shared by approvals and the audit log."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def action_hash(tool: str, args: dict[str, Any]) -> str:
    """What the approver saw = what gets executed. Hash *validated* args (defaults applied)."""
    return hashlib.sha256(canonical_json({"tool": tool, "args": args}).encode()).hexdigest()


def keyed_fingerprint(key: bytes, value: Any) -> str:
    """For the audit log: HMAC, not plain SHA-256, so low-entropy values can't be brute-forced offline."""
    return hmac.new(key, canonical_json(value).encode(), hashlib.sha256).hexdigest()


_SECRET_KEYS = re.compile(r"(pass(word)?|secret|token|api[_-]?key|authorization|cookie|credential)", re.I)
_SECRET_VALUES = re.compile(
    r"(sk-or-v1-[0-9a-f]{20,}|sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"
    r"|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.)"
)


def redact(value: Any, extra_keys: frozenset[str] = frozenset(), max_str: int = 256) -> Any:
    """Preview for the audit log: drop secret-looking keys/values, truncate long strings."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in extra_keys or _SECRET_KEYS.search(str(k)):
                out[k] = "[REDACTED]"
            else:
                out[k] = redact(v, extra_keys, max_str)
        return out
    if isinstance(value, list):
        return [redact(v, extra_keys, max_str) for v in value[:50]]
    if isinstance(value, str):
        s = _SECRET_VALUES.sub("[REDACTED]", value)
        return s if len(s) <= max_str else s[:max_str] + f"…(+{len(s) - max_str} chars)"
    return value
```

### A.3 Schema — `kbtools/schema.sql`

```sql
-- Batch 6 sketch schema (AI service owns it: the component that executes the action writes the record).

create table if not exists pending_actions (
  id             text primary key,               -- 128-bit random, URL-safe; not a capability (owner checked)
  requester_sub  text not null,                  -- from the verified token, never from the request body
  tool           text not null,                  -- model-facing name
  server         text not null,
  remote_name    text not null,
  args           jsonb not null,                 -- validated, canonical
  action_hash    char(64) not null,              -- sha256(tool + args) shown in the UI and echoed on approve
  risk           smallint not null,
  min_role       text not null,
  status         text not null check (status in
                 ('pending','approved','rejected','expired','executing','succeeded','failed','unknown')),
  reason         text,                           -- the model's stated reason (untrusted, display only)
  decided_by     text,
  decided_at     timestamptz,
  decision_note  text,
  created_at     timestamptz not null default now(),
  expires_at     timestamptz not null,
  started_at     timestamptz,
  finished_at    timestamptz,
  trace_id       text,
  turn_id        text,
  result         jsonb,                          -- what the harness feeds back to the model on resume
  attempts       smallint not null default 0
);
create index if not exists pending_actions_owner on pending_actions (requester_sub, status);

create table if not exists audit_events (
  seq           bigserial primary key,
  ts            timestamptz not null default clock_timestamp(),
  event         text not null,      -- tool.denied | tool.executed | tool.failed | approval.requested | approval.approved | ...
  sub           text,               -- end user (from token)
  actor         text,               -- acting client (azp / act), e.g. kb-ai
  tool          text,
  server        text,
  risk          smallint,
  decision      text,
  reason        text,
  approval_id   text,
  trace_id      text,
  request_id    text,
  args_preview  jsonb,              -- redacted + truncated
  args_fp       char(64),           -- HMAC of full canonical args
  result_status text,
  result_fp     char(64),
  prev_hash     char(64) not null,
  hash          char(64) not null unique
);
```

### A.4 Approval store — `kbtools/approvals.py`

```python
"""Human-in-the-loop approvals (#32): a pending-action state machine with conditional transitions.

pending ──approve──▶ approved ──claim──▶ executing ──▶ succeeded | failed
   │                    │                     └── (crash, stale) ──▶ unknown   (never auto-retried)
   ├──reject──▶ rejected
   └──timeout─▶ expired          approved but not claimed within the window ──▶ expired

Every transition is one conditional UPDATE … RETURNING, so double clicks, approve/reject races and
parallel executors resolve to exactly one winner without explicit locks.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .canonical import action_hash
from .policy import ROLE_RANK, Principal, ToolPolicy

APPROVAL_TTL_S = 600        # time to decide
EXECUTE_WINDOW_S = 60       # approved → must be claimed within this window


class ApprovalError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code     # not_found | not_yours | changed | expired | already_decided | forbidden


@dataclass(frozen=True)
class Pending:
    id: str
    tool: str
    args: dict[str, Any]
    action_hash: str
    risk: int
    expires_at: Any


class ApprovalStore:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def create(self, p: Principal, pol: ToolPolicy, args: dict[str, Any], *, reason: str | None,
               trace_id: str | None, turn_id: str | None) -> Pending:
        aid = secrets.token_urlsafe(16)
        h = action_hash(pol.name, args)
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """insert into pending_actions (id, requester_sub, tool, server, remote_name, args, action_hash,
                       risk, min_role, status, reason, expires_at, trace_id, turn_id)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s, now() + make_interval(secs => %s), %s,%s)
                   returning id, expires_at""",
                (aid, p.sub, pol.name, pol.server, pol.remote_name, Jsonb(args), h, int(pol.risk),
                 pol.min_role, reason, APPROVAL_TTL_S, trace_id, turn_id))
            row = cur.fetchone()
        self.conn.commit()
        return Pending(aid, pol.name, args, h, int(pol.risk), row["expires_at"])

    def decide(self, aid: str, approver: Principal, decision: Literal["approved", "rejected"],
               shown_hash: str, note: str | None = None) -> dict[str, Any]:
        """The approver echoes the hash of what the UI displayed. Requester-only in P2."""
        # Role is re-checked at decision time (it may have been revoked since the proposal).
        # Rejecting never needs a role: anyone may say no to their own pending action.
        allowed = [r for r, rank in ROLE_RANK.items() if rank <= approver.rank] if decision == "approved" \
            else list(ROLE_RANK)
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """update pending_actions
                      set status = %s, decided_by = %s, decided_at = now(), decision_note = %s
                    where id = %s and status = 'pending' and expires_at > now()
                      and requester_sub = %s and action_hash = %s and min_role = any(%s)
                returning *""",
                (decision, approver.sub, note, aid, approver.sub, shown_hash, allowed))
            row = cur.fetchone()
        self.conn.commit()
        if row is None:
            raise self._why(aid, approver, shown_hash, allowed)
        return row

    def claim(self, aid: str) -> dict[str, Any] | None:
        """Exactly one executor wins. Returns the row (with the stored args) or None."""
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """update pending_actions
                      set status = 'executing', started_at = now(), attempts = attempts + 1
                    where id = %s and status = 'approved'
                      and decided_at > now() - make_interval(secs => %s)
                returning *""",
                (aid, EXECUTE_WINDOW_S))
            row = cur.fetchone()
        self.conn.commit()
        return row

    def finish(self, aid: str, ok: bool, result: dict[str, Any]) -> bool:
        with self.conn.cursor() as cur:
            cur.execute(
                """update pending_actions set status = %s, finished_at = now(), result = %s
                    where id = %s and status = 'executing' returning id""",
                ("succeeded" if ok else "failed", Jsonb(result), aid))
            done = cur.fetchone() is not None
        self.conn.commit()
        return done

    def expire(self) -> list[str]:
        """Sweeper: pending past TTL, and approved-but-never-claimed past the window."""
        with self.conn.cursor() as cur:
            cur.execute(
                """update pending_actions set status = 'expired'
                    where (status = 'pending' and expires_at <= now())
                       or (status = 'approved' and decided_at <= now() - make_interval(secs => %s))
                returning id""", (EXECUTE_WINDOW_S,))
            ids = [r[0] for r in cur.fetchall()]
        self.conn.commit()
        return ids

    def recover_stuck(self, older_than_s: int = 300) -> list[str]:
        """Boot recovery: an 'executing' row whose process died. The side effect may or may not have
        happened, so mark 'unknown' and show it to the user — never retry a non-idempotent write."""
        with self.conn.cursor() as cur:
            cur.execute(
                """update pending_actions set status = 'unknown', finished_at = now()
                    where status = 'executing' and started_at <= now() - make_interval(secs => %s)
                returning id""", (older_than_s,))
            ids = [r[0] for r in cur.fetchall()]
        self.conn.commit()
        return ids

    def get(self, aid: str) -> dict[str, Any] | None:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute("select * from pending_actions where id = %s", (aid,))
            row = cur.fetchone()
        self.conn.commit()
        return row

    # -- helpers ---------------------------------------------------------------------------------
    def _why(self, aid: str, approver: Principal, shown_hash: str, allowed: list[str]) -> ApprovalError:
        row = self.get(aid)
        if row is None:
            return ApprovalError("not_found", "no such action")
        if row["requester_sub"] != approver.sub:
            return ApprovalError("not_found", "no such action")  # don't reveal other users' actions
        if row["status"] != "pending":
            return ApprovalError("already_decided", f"action is {row['status']}")
        if row["action_hash"] != shown_hash:
            return ApprovalError("changed", "the action differs from what was shown")
        if row["min_role"] not in allowed:
            return ApprovalError("forbidden", f"requires role {row['min_role']}")
        return ApprovalError("expired", "approval window has passed")
```

### A.5 Hash-chained audit log — `kbtools/audit.py`

```python
"""Audit log (#33): append-only, hash-chained, redacted.

- Writer = the component that performs the action (the AI service executes tools → it writes).
- Append-only is enforced by grants (insert/select only for the app role), detection by the hash chain.
- The chain needs one ordering: appends take a transaction-scoped advisory lock, or two writers read
  the same head and fork the chain.
- A chain only proves integrity relative to an anchor: periodically copy the head hash somewhere the
  database's admins can't rewrite (CI artifact, object storage with retention lock, a signed log line).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .canonical import canonical_json, keyed_fingerprint, redact

GENESIS = "0" * 64
_LOCK_KEY = 0x6B62_6175  # "kbau"
_HASHED_FIELDS = ("event", "sub", "actor", "tool", "server", "risk", "decision", "reason", "approval_id",
                  "trace_id", "request_id", "args_preview", "args_fp", "result_status", "result_fp")


@dataclass(frozen=True)
class AuditEvent:
    event: str
    sub: str | None = None
    actor: str | None = None
    tool: str | None = None
    server: str | None = None
    risk: int | None = None
    decision: str | None = None
    reason: str | None = None
    approval_id: str | None = None
    trace_id: str | None = None
    request_id: str | None = None
    args: dict[str, Any] | None = None
    redact_keys: frozenset[str] = frozenset()
    result_status: str | None = None
    result: Any = None


def _record_hash(prev: str, rec: dict[str, Any]) -> str:
    body = {k: rec.get(k) for k in _HASHED_FIELDS}
    return hashlib.sha256((prev + canonical_json(body)).encode()).hexdigest()


class AuditLog:
    def __init__(self, conn: psycopg.Connection, fp_key: bytes):
        self.conn = conn
        self.fp_key = fp_key

    def _row(self, e: AuditEvent) -> dict[str, Any]:
        return {
            "event": e.event, "sub": e.sub, "actor": e.actor, "tool": e.tool, "server": e.server,
            "risk": e.risk, "decision": e.decision, "reason": e.reason, "approval_id": e.approval_id,
            "trace_id": e.trace_id, "request_id": e.request_id,
            "args_preview": redact(e.args, e.redact_keys) if e.args is not None else None,
            "args_fp": keyed_fingerprint(self.fp_key, e.args) if e.args is not None else None,
            "result_status": e.result_status,
            "result_fp": keyed_fingerprint(self.fp_key, e.result) if e.result is not None else None,
        }

    def head(self) -> str:
        with self.conn.cursor() as cur:
            cur.execute("select hash from audit_events order by seq desc limit 1")
            r = cur.fetchone()
        return r[0] if r else GENESIS

    def append(self, e: AuditEvent, *, lock: bool = True) -> str:
        rec = self._row(e)
        with self.conn.transaction():
            with self.conn.cursor() as cur:
                if lock:
                    cur.execute("select pg_advisory_xact_lock(%s)", (_LOCK_KEY,))
                prev = self.head()
                h = _record_hash(prev, rec)
                cols = list(rec) + ["prev_hash", "hash"]
                vals = [Jsonb(v) if k == "args_preview" and v is not None else v for k, v in rec.items()]
                cur.execute(
                    f"insert into audit_events ({', '.join(cols)}) values ({', '.join(['%s'] * len(cols))})",
                    vals + [prev, h])
        return h

    def _insert_with_prev(self, e: AuditEvent, prev: str) -> str:
        """Test hook: an append that read the head earlier (what a writer without the lock does)."""
        rec = self._row(e)
        h = _record_hash(prev, rec)
        cols = list(rec) + ["prev_hash", "hash"]
        vals = [Jsonb(v) if k == "args_preview" and v is not None else v for k, v in rec.items()]
        with self.conn.transaction(), self.conn.cursor() as cur:
            cur.execute(f"insert into audit_events ({', '.join(cols)}) values ({', '.join(['%s'] * len(cols))})",
                        vals + [prev, h])
        return h


def verify_chain(conn: psycopg.Connection, anchor: str | None = None) -> tuple[bool, str]:
    """Recompute every hash. Detects edits, deletions in the middle and forks. With `anchor`
    (a head hash stored elsewhere earlier) it also detects truncation and a rewritten tail."""
    prev = GENESIS
    seen_anchor = anchor is None
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select * from audit_events order by seq")
        for row in cur:
            rec = {k: row[k] for k in _HASHED_FIELDS}
            if row["prev_hash"] != prev:
                return False, f"seq {row['seq']}: prev_hash mismatch (deleted row or fork)"
            if _record_hash(prev, rec) != row["hash"]:
                return False, f"seq {row['seq']}: content was modified"
            prev = row["hash"]
            if prev == anchor:
                seen_anchor = True
    conn.commit()
    if not seen_anchor:
        return False, "anchor hash not found (truncated or rewritten)"
    return True, prev
```

### A.6 Token exchange client — `kbtools/token_exchange.py`

```python
"""On-behalf-of tokens (#31): RFC 8693 standard token exchange against Keycloak.

Keycloak 26.x standard token exchange (V2), per its docs:
- requester must be a confidential client with "Standard token exchange" switched on,
- the subject token's `aud` must contain the requester,
- `audience` takes client ids and only *filters* audiences; `resource` is not supported,
- `scope` can *add* the requester's optional scopes unless the `downscope-assertion-grant-enforcer`
  client-policy executor is configured → we check the result ourselves as well,
- refresh tokens only on request and only if the client allows it (default No) → we never ask.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Callable

import httpx

GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"
ACCESS = "urn:ietf:params:oauth:token-type:access_token"


class ExchangeError(Exception):
    def __init__(self, kind: str, detail: str):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind          # forbidden | config | widened | upstream


@dataclass(frozen=True)
class Exchanged:
    token: str
    exp: float
    aud: tuple[str, ...]
    scope: frozenset[str]


def _claims(jwt: str) -> dict:
    """Unverified read of a token we just received over TLS from the AS — a sanity check, not auth."""
    payload = jwt.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


class TokenExchanger:
    def __init__(self, token_url: str, client_id: str, client_secret: str, http: httpx.Client,
                 clock: Callable[[], float] = time.time, skew_s: float = 30.0, max_entries: int = 1024):
        self.token_url, self.client_id, self.secret = token_url, client_id, client_secret
        self.http, self.clock, self.skew = http, clock, skew_s
        self.cache: dict[str, Exchanged] = {}
        self.max_entries = max_entries

    def exchange(self, subject_token: str, *, audience: str, scope: str | None = None) -> Exchanged:
        # Key by the subject token itself (hashed): two sessions of the same user must not share tokens.
        key = hashlib.sha256(f"{subject_token}|{audience}|{scope or ''}".encode()).hexdigest()
        hit = self.cache.get(key)
        if hit and hit.exp - self.skew > self.clock():
            return hit
        form = {"grant_type": GRANT, "subject_token": subject_token, "subject_token_type": ACCESS,
                "requested_token_type": ACCESS, "audience": audience}
        if scope:
            form["scope"] = scope
        r = self.http.post(self.token_url, data=form, auth=(self.client_id, self.secret))
        if r.status_code >= 500:
            raise ExchangeError("upstream", f"HTTP {r.status_code}")
        body = r.json()
        if r.status_code == 403 or body.get("error") == "access_denied":
            raise ExchangeError("forbidden", body.get("error_description", "access denied"))
        if r.status_code != 200:
            raise ExchangeError("config", f"{body.get('error')}: {body.get('error_description', '')}")
        if "refresh_token" in body:
            raise ExchangeError("config", "exchange returned a refresh token; disable it on the client")
        c = _claims(body["access_token"])
        aud = tuple(c["aud"]) if isinstance(c.get("aud"), list) else (c.get("aud"),)
        if audience not in aud:
            raise ExchangeError("config", f"issued token is not for {audience}: aud={aud}")
        granted = frozenset((c.get("scope") or "").split())
        if scope and not granted <= frozenset(scope.split()) | {"openid", "profile", "email"}:
            raise ExchangeError("widened", f"granted {sorted(granted)} ⊄ requested {scope!r}")
        if c.get("azp") != self.client_id:
            raise ExchangeError("config", f"azp={c.get('azp')} (expected {self.client_id})")
        out = Exchanged(body["access_token"], float(c["exp"]), aud, granted)
        if len(self.cache) >= self.max_entries:
            self.cache.pop(next(iter(self.cache)))
        self.cache[key] = out
        return out
```

### A.7 Tool gate — `kbtools/gate.py`

```python
"""The tool gate: one choke point between the model's tool calls and anything with side effects.

model tool call ─▶ known? ─▶ args valid? ─▶ authorize ─┬─ deny ─────────▶ tool message "not permitted"
                                                       ├─ allow ────────▶ execute ─▶ audit ─▶ tool message
                                                       └─ approval ─────▶ pending action ─▶ turn ends
user decides (separate HTTP endpoint, user's own token) ─▶ resume(aid) ─▶ re-authorize ─▶ claim ─▶ execute
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal

import jsonschema

from .approvals import ApprovalStore, Pending
from .audit import AuditEvent, AuditLog
from .policy import Principal, ToolPolicy, authorize

# executor(server, remote_name, args) -> (is_error, text)
Executor = Callable[[str, str, dict[str, Any]], Awaitable[tuple[bool, str]]]


@dataclass(frozen=True)
class GateResult:
    kind: Literal["result", "approval_required", "denied", "invalid", "error"]
    tool_message: str          # what goes back to the model as the `tool` message (untrusted data)
    is_error: bool = False
    pending: Pending | None = None


class ToolGate:
    def __init__(self, registry: list[ToolPolicy], executor: Executor, approvals: ApprovalStore,
                 audit: AuditLog, actor: str = "kb-ai"):
        self.registry = {t.name: t for t in registry}
        self.executor, self.approvals, self.audit, self.actor = executor, approvals, audit, actor

    def _audit(self, p: Principal, pol: ToolPolicy | None, event: str, **kw: Any) -> None:
        fallback_tool = kw.pop("tool", None)
        self.audit.append(AuditEvent(
            event=event, sub=p.sub, actor=self.actor, tool=pol.name if pol else fallback_tool,
            server=pol.server if pol else None, risk=int(pol.risk) if pol else None,
            redact_keys=pol.redact if pol else frozenset(), **kw))

    async def handle(self, p: Principal, name: str, raw_args: str | dict[str, Any], *,
                     trace_id: str, reason: str | None = None, turn_id: str | None = None) -> GateResult:
        pol = self.registry.get(name)
        if pol is None:
            self._audit(p, None, "tool.denied", tool=name, decision="deny", reason="unknown tool", trace_id=trace_id)
            return GateResult("denied", f"Unknown tool: {name}", True)
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            jsonschema.Draft202012Validator(pol.input_schema).validate(args)
        except (json.JSONDecodeError, jsonschema.ValidationError) as e:
            loc = "/".join(str(x) for x in getattr(e, "absolute_path", [])) or "arguments"
            return GateResult("invalid", f"Invalid arguments ({loc}): {getattr(e, 'message', str(e))}", True)

        d = authorize(p, pol, args)
        if d.outcome == "deny":
            self._audit(p, pol, "tool.denied", decision="deny", reason=d.reason, args=args, trace_id=trace_id)
            return GateResult("denied", f"Not permitted: {d.reason}.", True)
        if d.outcome == "approval":
            pend = self.approvals.create(p, pol, args, reason=reason, trace_id=trace_id, turn_id=turn_id)
            self._audit(p, pol, "approval.requested", decision="approval", approval_id=pend.id, args=args,
                        trace_id=trace_id)
            return GateResult("approval_required", "Waiting for the user's decision.", False, pend)
        return await self._execute(p, pol, args, trace_id=trace_id, approval_id=None)

    async def _execute(self, p: Principal, pol: ToolPolicy, args: dict[str, Any], *, trace_id: str,
                       approval_id: str | None) -> GateResult:
        try:
            async with asyncio.timeout(pol.timeout_s):
                is_err, text = await self.executor(pol.server, pol.remote_name, args)
        except TimeoutError:
            is_err, text = True, f"Tool timed out after {pol.timeout_s:.0f} s."
        except Exception:  # noqa: BLE001 — details go to logs/trace, never to the model
            is_err, text = True, "Tool failed with an internal error."
        if len(text) > pol.max_result_chars:
            text = text[: pol.max_result_chars] + f"\n…[truncated {len(text) - pol.max_result_chars} chars]"
        self._audit(p, pol, "tool.failed" if is_err else "tool.executed", decision="allow",
                    approval_id=approval_id, args=args, result_status="error" if is_err else "ok",
                    result=text, trace_id=trace_id)
        return GateResult("error" if is_err else "result", text, is_err)

    def decide(self, aid: str, approver: Principal, decision: Literal["approved", "rejected"], shown_hash: str,
               *, note: str | None = None, trace_id: str | None = None) -> dict[str, Any]:
        """Backs POST /v1/approvals/{id}: the user's own request, never a tool the model can call."""
        row = self.approvals.decide(aid, approver, decision, shown_hash, note)   # raises ApprovalError
        self._audit(approver, self.registry.get(row["tool"]), f"approval.{decision}", tool=row["tool"],
                    decision=decision, approval_id=aid, reason=note, trace_id=trace_id)
        return row

    async def resume(self, aid: str, p: Principal, *, trace_id: str) -> GateResult:
        """Called on the request that continues the turn after the user decided. Idempotent."""
        row = self.approvals.get(aid)
        if row is None or row["requester_sub"] != p.sub:
            return GateResult("denied", "Unknown approval.", True)
        status = row["status"]
        if status in ("succeeded", "failed"):
            r = row["result"]                      # stored result: a second resume never re-executes
            return GateResult("result" if status == "succeeded" else "error", r["text"], r["is_error"])
        if status == "rejected":
            note = f" Note: {row['decision_note']}" if row["decision_note"] else ""
            return GateResult("denied", f"The user rejected this action. Do not retry it.{note}", True)
        if status in ("pending", "expired"):
            return GateResult("denied", "Not executed: the approval expired or is still open.", True)
        if status == "unknown":
            return GateResult("error", "The outcome of this action is unknown; ask the user to check.", True)
        if status == "executing":
            return GateResult("error", "This action is still running.", True)

        pol = self.registry.get(row["tool"])
        args = row["args"]                         # stored args — never the client's copy
        d = authorize(p, pol, args) if pol else None
        if pol is None or d.outcome == "deny":
            self.approvals.claim(aid) and self.approvals.finish(
                aid, False, {"text": "Not permitted at execution time.", "is_error": True})
            self._audit(p, pol, "tool.denied", tool=row["tool"], decision="deny", approval_id=aid,
                        reason=(d.reason if d else "tool no longer registered"), args=args, trace_id=trace_id)
            return GateResult("denied", "Not permitted at execution time.", True)
        claimed = self.approvals.claim(aid)
        if claimed is None:
            return GateResult("error", "This action was already executed or has expired.", True)
        res = await self._execute(p, pol, args, trace_id=trace_id, approval_id=aid)
        self.approvals.finish(aid, not res.is_error, {"text": res.tool_message, "is_error": res.is_error})
        return res
```

---

## Sources

- MCP specification 2026-07-28: [changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog) · [authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization) · [tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools) · [elicitation](https://modelcontextprotocol.io/specification/2026-07-28/client/elicitation) · [security best practices](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices) · [release tag](https://github.com/modelcontextprotocol/specification/releases/tag/2026-07-28)
- MCP Python SDK `mcp` 2.3.0 (PyPI; source read from the installed package)
- Keycloak: [Configuring and using token exchange](https://www.keycloak.org/securing-apps/token-exchange) · [Integrating with MCP (nightly)](https://www.keycloak.org/nightly/securing-apps/mcp-authz-server) · [Keycloak 26.8.0 released](https://www.keycloak.org/2026/10/keycloak-2680-released)
- CVE-2026-93999 analysis: [Skycloak](https://skycloak.io/?p=4448)
- GitHub MCP toxic agent flow: [Invariant Labs, 26 May 2025](https://invariantlabs.ai/blog/mcp-github-vulnerability)
- GitHub MCP server settings (secondary source): [developertoolkit.ai](https://developertoolkit.ai/en/ecosystem/mcp/github-mcp/)
- AKS MCP server listing (secondary source): [mcpservers.org](https://mcpservers.org/fr/servers/Azure/aks-mcp)
