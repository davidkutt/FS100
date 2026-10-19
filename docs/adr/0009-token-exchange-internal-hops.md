# ADR-0009: Keycloak standard token exchange on the internal hops

- **Status:** Proposed (M2.0 spike done; accepted in M2.4 with the realm export and the delegation spike)
- **Date:** 2026-10-19
- **Plan reference:** D5, D35, D36 ([plan-phase-2.md §3](../../plan-phase-2.md#3-decisions))

## Context

In Phase 1, NestJS calls the AI service with a client-credentials token (`kb-api` service account) and
passes the user in a `user` body object. Phase 2 adds a third hop, AI service → own MCP server. That
server is an OAuth protected resource, so it needs a real user token for its own audience, with scopes.
Identity should travel in tokens, not in request bodies. Plan risk "token exchange audience rules
misconfigured" was rated medium–high, so M2.0 spiked it first.

## Decision

- **Hop 1:** NestJS (`kb-api`) exchanges the user's `kb-api` token for `audience=kb-ai`.
- **Hop 2:** the AI service (confidential client `kb-ai`) exchanges that token with `scope=kb:read` or
  `scope=kb:read kb:write`, and **no `audience` parameter**. The audience comes from the client scopes'
  audience mapper (*Included Custom Audience* = MCP resource URL).
- The **MCP server checks scope and realm role** (`kb:write` + `editor` for `ingest_url`).
- The `user` body object is removed (M2.4). System jobs keep client credentials. `kb.ingest_url` →
  `/internal/documents/from-url` stays a documented trusted-subsystem exception until the delegation spike.

## Spike results (M2.0)

Throwaway Keycloak 26.8.1 (`docker compose -p fs100-m20`, own volumes). Realm changes made through the
admin API: standard token exchange on `kb-api` and `kb-ai`; `kb-ai` confidential; client scopes `kb:read` and
`kb:write` with an audience mapper → `http://localhost:8000/mcp`, optional on `kb-ai`. Users `bob`
(editor) and `carol` (viewer).

| Step | Result |
|---|---|
| User token (`kb-web`) | `aud=kb-api`, `azp=kb-web`, realm roles |
| Hop 1: `kb-api`, `audience=kb-ai` | 200 · `aud=kb-ai`, `azp=kb-api`, same `sub` and roles |
| Hop 2: `kb-ai`, `scope=kb:read` | 200 · `aud=http://localhost:8000/mcp` (only), `scope` contains `kb:read` |
| Hop 2: `kb-ai`, `scope=kb:read kb:write` | 200 · both scopes, **also for the viewer** |
| `kb-ai` exchanges the raw user token (`aud=kb-api`) | **403** `Client is not within the token audience` |
| Hop 2 with `audience=http://localhost:8000/mcp` | **400** `Audience not found` (expects a client id) |
| Hop 1 with an audience `kb-api` cannot reach (`kb-web`) | **400** `Requested audience not available` |

Findings:

- **A11 holds:** only supported features were needed (no legacy `token-exchange` feature, no fine-grained
  admin permissions).
- **Request the MCP audience by scope, not by `audience`:** the parameter only takes client ids. A `kb-mcp`
  client is still useful for the CIMD stretch (`resource_url`), but not for the exchange.
- **Optional scopes are not role-gated:** a viewer can get `kb:write`. The resource server has to
  check the role. D35 already says scopes **plus** realm roles; the token matrix in M2.4 must include
  "viewer with `kb:write` → 403".
- The audience chain is enforced by Keycloak, so a stolen `kb-api` token cannot be turned into an MCP
  token by `kb-ai`.
- Exchanged tokens keep `sub`, `preferred_username` and realm roles, and drop `openid` from `scope`.
  There is no `act` claim, because delegation is a separate preview feature (M2.4 spike).
- Upgrading Keycloak 26.7.5 → 26.8.1 migrates the existing `kb` realm in place, and a fresh
  `--import-realm` of `infra/keycloak/realm-kb.json` still works.

## Alternatives considered

- **Client credentials + `user` body object** (Phase 1) — the AI service has to trust NestJS's claim
  about the user, and the MCP server could not tell users apart.
- **Forwarding the user's `kb-api` token unchanged** — wrong audience at every hop; it breaks audience
  validation and the RFC 9728 resource model.
- **Legacy token exchange (V1)** — preview feature with fine-grained permissions; V2 covers the
  internal→internal case and is supported.

## Consequences

- Two extra token requests per turn; both results are cached until `exp − 30 s`. A resume always
  exchanges fresh tokens.
- Realm JSON grows (client scopes, `kb-ai` secret, exchange flags). It is only imported into an empty
  volume, so existing setups need `pnpm stack:reset` (wipes local data) or the admin console.
- Keycloak is now on the hot path of every turn: if Keycloak is down, so is the agent.
