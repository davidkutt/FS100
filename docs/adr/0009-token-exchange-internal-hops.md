# ADR-0009: Keycloak standard token exchange on the internal hops

- **Status:** Accepted (M2.4)
- **Date:** 2026-10-19 (accepted 2026-10-21)
- **Plan reference:** D5, D35, D36 ([plan-phase-2.md §3](../../plan-phase-2.md#3-decisions))

## Context

In Phase 1, NestJS calls the AI service with a client-credentials token (`kb-api` service account) and
passes the user in a `user` body object. Phase 2 adds a third hop, AI service → own MCP server. That
server is an OAuth protected resource, so it needs a real user token for its own audience, with scopes.
Identity should travel in tokens, not in request bodies. Plan risk "token exchange audience rules
misconfigured" was rated medium–high, so M2.0 spiked it first.

## Decision

- **Hop 1:** NestJS (`kb-api`) exchanges the user's `kb-api` token for `audience=kb-ai` on every user
  request to the AI service (`chat`, `search`, agent turns), cached per subject token until `exp − 150 s`
  — the AI service exchanges that token again during a run of up to 120 s; a resume always exchanges
  afresh, so the AI service sees the roles as they are now. System calls
  (background ingest, labels, delete, catalog, status) keep the `kb-api` service token.
- **Hop 2:** the AI service (confidential client `kb-ai`) exchanges that token with `scope=kb:read`, or
  `scope=kb:read kb:write` for an approved write only, and **no `audience` parameter**. The audience
  comes from the client scopes' audience mapper (*Included Custom Audience* = MCP resource URL). Cached
  per subject token and scope until `exp − 30 s` (each MCP call takes ≤ 20 s).
- The AI service takes `sub` and realm roles from the token; the `user` body object is gone from
  `/v1/chat` and `/v1/agent`. The **MCP server checks scope and realm role** (`kb:read` + `viewer` for
  the read tools, `kb:write` + `editor` for `ingest_url`).
- **Trusted-subsystem exception (D36), kept:** `ingest_url` calls the API's
  `/internal/documents/from-url` with `kb-ai`'s service-account token and an `onBehalfOf: {sub, name}`
  body. The route needs the `kb-api` **client** role `ingest-on-behalf`, which only `kb-ai`'s service
  account holds; Keycloak's audience resolver then adds `aud=kb-api` to that account's tokens, so no
  audience mapper on `kb-ai` is needed — one would leak `kb-api` into every hop-2 token. The API audits
  each call as `documents.from_url` with the service identity. The URL fetch (allow-listed hosts, no IP
  literals or private addresses on any redirect, size cap) happens in the API, which stores the result
  like an upload.

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

## Realm export (M2.4)

- A `clientScopes` list in a realm import **replaces** Keycloak's built-in scopes: without `basic`,
  `roles` and `profile`, tokens lose `sub`, `realm_access` and `preferred_username`. The export
  therefore carries `basic`, `roles`, `profile` (only username and name mappers), `email`,
  `web-origins` and `acr` as realm defaults, plus `kb:read` and `kb:write`.
- A client with `optionalClientScopes` but no `defaultClientScopes` gets **no** default scopes, so
  `kb-ai` lists them explicitly.
- Verified on a throwaway Keycloak 26.8.1 with the committed file: user token `aud=kb-api` with roles;
  hop 1 `aud=kb-ai`, same `sub` and roles; hop 2 `aud=http://localhost:8000/mcp` with `kb:read`
  (and `kb:write` on request, also for a viewer); `kb-ai` on the raw user token → 403; `kb-ai`'s
  service token `aud=kb-api` with `resource_access.kb-api.roles=[ingest-on-behalf]`. End to end
  through API and AI service: an agent turn as `bob` searched via `/mcp`; `ingest_url` as `bob` asked,
  fetched and stored the file as Bob's; `carol` (viewer) and a token without `kb:write` were refused.

## Delegation spike (M2.4): dropped for Phase 2

Goal: replace the `onBehalfOf` exception by a delegated token (`sub` = user, `act` = `kb-ai`).

- `token-exchange-delegation:v1` is a **preview** feature and needs a second preview feature,
  `parameterized-scopes:v1` (Keycloak refuses to start otherwise).
- An exchange with `actor_token` fails with `400 Invalid may_act claim in the subject_token` unless the
  subject token names its actor in `may_act` (RFC 8693 §4.4). That claim comes from a parameterized
  client scope (type *Client Delegation*, mapper *Parameterized Scope Client Sub*). Requesting it on the
  hop-1 exchange (`scope=may_act:kb-ai`) did not add the claim within the time box.
- **Outcome:** keep the documented trusted-subsystem exception. Two preview features on the hot path
  of every turn are not worth it for one write tool; revisit when delegation is supported (P3b, with
  per-user GitHub access).

## Alternatives considered

- **Client credentials + `user` body object** (Phase 1) — the AI service has to trust NestJS's claim
  about the user, and the MCP server could not tell users apart.
- **Forwarding the user's `kb-api` token unchanged** — wrong audience at every hop; it breaks audience
  validation and the RFC 9728 resource model.
- **Legacy token exchange (V1)** — preview feature with fine-grained permissions; V2 covers the
  internal→internal case and is supported.

## Consequences

- Up to two extra token requests per turn; both results are cached. A resume always
  exchanges hop 1 afresh; a write asks for its own `kb:write` token.
- Realm JSON grows (client scopes incl. the built-in ones, `kb-ai` secret and service account, exchange
  flags, a client role). It is only imported into an empty volume, so existing setups need
  `pnpm stack:reset` (wipes local data) or the admin console. `AI_KEYCLOAK_CLIENT_SECRET` must match the
  realm's `kb-ai` secret.
- Keycloak is now on the hot path of every turn: if Keycloak is down, so is the agent.
