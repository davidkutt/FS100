---
name: user-token
description: Gets a Keycloak access token for a seed user (alice/bob/carol) from the shell by scripting the kb-web Authorization Code + PKCE login, then calls the NestJS /api/* routes with curl. Use when testing API endpoints by hand against the running stack, e.g. "try upload/chat end to end", "call /api/documents as bob", or checking RBAC (viewer → 403) without the browser.
---

# User token for /api/* from the shell

`kb-web` has no password grant (direct access grants off), so `login.sh` walks the browser flow with curl:
auth page → POST the login form → read `code` from the redirect → exchange it with the PKCE verifier.
Seed users log in with username = password (dev only).

1. Stack and API up: `pnpm stack:up`, then `pnpm dev api ai` (or check `curl -s localhost:3000/readyz`).
2. Tokens (5 min lifetime; rerun when you get 401):
   ```bash
   BOB=$(.claude/skills/user-token/login.sh bob)       # editor; alice = admin, carol = viewer
   curl -s localhost:3000/api/me -H "authorization: Bearer $BOB"
   ```
3. Typical calls:
   ```bash
   curl -s localhost:3000/api/documents -H "authorization: Bearer $BOB" \
     -F file=@data/sample-docs/runbook-rollback.md -F domains=devops     # 202 {"id":…}
   curl -s localhost:3000/api/documents -H "authorization: Bearer $BOB"  # poll until "ready"
   curl -sN localhost:3000/api/chat -H "authorization: Bearer $BOB" -H 'content-type: application/json' \
     -d '{"messages":[{"role":"user","content":"How do I roll back a deployment?"}],"domains":["devops"]}'
   curl -s -X DELETE localhost:3000/api/documents/<id> -H "authorization: Bearer $BOB"   # 204, clean up
   curl -s -X PATCH localhost:3000/api/documents/<id> -H "authorization: Bearer $BOB" -H 'content-type: application/json' \
     -d '{"domains":["devops"],"topics":["devops/deployment"]}'          # relabel, no re-embedding
   C=$(curl -s -X POST localhost:3000/api/conversations -H "authorization: Bearer $BOB" -H 'content-type: application/json' -d '{}' | jq -r .id)
   curl -sN localhost:3000/api/conversations/$C/messages -H "authorization: Bearer $BOB" -H 'content-type: application/json' \
     -d '{"text":"How do I roll back a deployment?"}'                  # SSE v2; then GET /api/conversations/$C
   curl -s localhost:3000/api/models -H "authorization: Bearer $BOB"     # also /api/tools, /api/taxonomy, /api/me/usage
   ```

## Pitfalls

- Chat spends real tokens when the AI service runs `LLM_PROVIDER=openai_compat`. Check first without
  printing secrets: `ps eww -o command= -p <uvicorn pid> | tr ' ' '\n' | grep -E '^LLM_(PROVIDER|MODEL)='`.
- `[api]` exits with `password authentication failed`: `API_DATABASE_URL` in `.env` doesn't repeat
  `POSTGRES_PASSWORD`. Don't edit the user's `.env`; tell them, and for a check pass a corrected
  `API_DATABASE_URL=… pnpm dev api` (process env beats `.env`).
- Re-uploading the same bytes → 409 (dedupe by SHA-256, failed rows included): delete the old document first.
- Uploads go into the real Qdrant and Postgres; delete test documents afterwards.
