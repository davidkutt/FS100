---
name: realm-check
description: Checks a change to infra/keycloak/realm-kb.json on a throwaway Keycloak (container fs100-m24-kc on :8081) — token-exchange matrix of ADR-0009, CIMD logins of Claude Code / VS Code (ADR-0014), and optionally the API and AI service on :3001/:8001 against it — without resetting the user's stack or touching their running `pnpm dev`. Use when editing the realm, client scopes, client policies, token exchange, service accounts or MCP audiences ("does the realm import work", "check the token matrix", "verify kb-ai / kb-api exchange", "does Claude Code's login still work").
---

# Realm change on a throwaway Keycloak

The real realm only imports into an empty volume; `pnpm stack:reset` wipes the user's data — ask first.
This recipe never touches it. Scratch files go to the session scratchpad (`$S`).

1. Start Keycloak on :8081 with the edited file (≈ 20 s; rerun after each edit, the import runs once):

   ```bash
   docker rm -f fs100-m24-kc 2>/dev/null
   docker run -d --name fs100-m24-kc -p 127.0.0.1:8081:8080 -e KC_BOOTSTRAP_ADMIN_USERNAME=admin \
     -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin -e KC_HOSTNAME=http://localhost:8081 \
     -v "$PWD/infra/keycloak/realm-kb.json:/opt/keycloak/data/import/realm-kb.json:ro" \
     quay.io/keycloak/keycloak:26.8.1 start-dev --import-realm --features=cimd,resource-indicators
   until curl -sf localhost:8081/realms/kb/.well-known/openid-configuration >/dev/null; do sleep 2; done
   ```

2. Token matrix: `.claude/skills/realm-check/matrix.sh`. Expect: user token `aud=kb-api` with `sub`,
   `preferred_username`, roles; hop 1 `aud=kb-ai`; hop 2 `aud=http://localhost:8000/mcp` + `kb:read kb:write`
   (also for carol — the MCP server checks the role); raw user token → `access_denied`; kb-ai's service token
   `aud=kb-api`, `resource_access.kb-api.roles=[ingest-on-behalf]`.
   CIMD (Keycloak fetches the real metadata documents, so it needs internet):
   `.claude/skills/realm-check/cimd-login.sh carol | python3 .claude/skills/realm-check/claims.py` (Claude Code,
   `kb:read`) → `aud=http://localhost:8000/mcp`, `kb:read`, roles `[viewer]`; VS Code:
   `cimd-login.sh bob https://vscode.dev/oauth/client-metadata.json http://127.0.0.1:33418/ "kb:read kb:write"`.
   A wrong 5th arg (`resource`), a redirect URI not in the document or a `client_id` on another host →
   `authorize refused: 400`. The full table is in ADR-0014.
3. Optional, the apps against it. The realm's MCP audience must be the port you run on, so import a copy:
   `sed 's#localhost:8000/mcp#localhost:8001/mcp#g' infra/keycloak/realm-kb.json > $S/realm-8001.json` and mount
   that in step 1 (`cimd-login.sh` then needs `http://localhost:8001/mcp` as 5th arg). Then, from `apps/ai-service`
   and the repo root (`env -i` keeps `.env` values out):

   ```bash
   env -i PATH="$PATH" HOME="$HOME" AI_KEYCLOAK_ISSUER=http://localhost:8081/realms/kb \
     AI_KEYCLOAK_CLIENT_SECRET=dev-only-change-me MCP_RESOURCE_URL=http://localhost:8001/mcp \
     AI_API_URL=http://localhost:3001 QDRANT_URL=:memory: EMBEDDING_MODEL=intfloat/multilingual-e5-small \
     LLM_PROVIDER=fake APPROVAL_SIGNING_KEY=dev-only-change-me-approval-signing-key \
     OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 RETRIEVAL_SCORE_THRESHOLD=0.5 \
     uv run uvicorn ai_service.main:app --host 127.0.0.1 --port 8001 > $S/ai8001.log 2>&1   # background
   pnpm --filter @fs100/api build
   env -i PATH="$PATH" HOME="$HOME" API_PORT=3001 API_DATABASE_URL=:memory: \
     KEYCLOAK_ISSUER=http://localhost:8081/realms/kb KEYCLOAK_CLIENT_SECRET=dev-only-change-me \
     AI_SERVICE_URL=http://localhost:8001 node apps/api/dist/main.js > $S/api3001.log 2>&1      # background
   ```

   User token: `KEYCLOAK_URL=http://localhost:8081 .claude/skills/user-token/login.sh bob`, then call
   `localhost:3001/api/*` as in the `user-token` skill (upload, conversation turn); the span tree via
   `agent-turn-check`'s `spans.py <traceId>`.
4. Clean up: kill the :8001/:3001 processes (`lsof -nP -iTCP:8001 -iTCP:3001 -sTCP:LISTEN -t`), then
   `docker rm -f fs100-m24-kc`.

## Pitfalls

- A `clientScopes` list in the import replaces Keycloak's built-in scopes: tokens lose `sub`, roles and
  `preferred_username` unless `basic`, `roles`, `profile` … are in the file (they are; keep them).
- A client with `optionalClientScopes` but no `defaultClientScopes` gets no default scopes at all.
- Preview features (e.g. `token-exchange-delegation`) go on the `docker run` command (`--features=…`);
  Keycloak refuses to start when one depends on another that is off — or when the realm has a client policy
  whose executor/condition belongs to a disabled feature (CIMD). An existing realm with such a policy starts
  but every login fails with 500.
- Clients created by CIMD get *full scope* off (realm roles only via the scope mapping on `kb:read`), a consent
  screen, and only realm-default scopes. A `pkce-enforcer` inside the CIMD profile never runs on them, and one
  without `auto-configure` throws an NPE; PKCE comes from the public-client policy.
- `pnpm dev` hot-reloads changed code against the user's real Keycloak: after a realm-dependent change their
  running apps may fail until they reset — tell them.
