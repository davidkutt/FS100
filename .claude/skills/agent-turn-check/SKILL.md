---
name: agent-turn-check
description: Streams one `POST /v1/agent` turn against the locally running AI service as a seed user (PKCE login + the API's token exchange), summarizes the SSE v2 events, and prints that turn's Phoenix span tree through Phoenix's REST API. Use when verifying an agent/harness change end to end ("curl /v1/agent", "does Phoenix show the span tree", "try the agent with the real model", check tool calls, stopReason, cached tokens).
---

# Agent turn + Phoenix span tree

Run from the repo root. Scratch files go to the session scratchpad (`$S` below).

0. Against the user's own `pnpm dev`: list what their `.env` lacks before the first turn (names only,
   never values): `comm -23 <(grep -oE '^[A-Z_0-9]+=' .env.example | sort -u) <(cat .env .env.local | grep -oE '^[A-Z_0-9]+=' | sort -u)`.
   Without `APPROVAL_SIGNING_KEY` a write ends in `Agent run failed`; without `AI_KEYCLOAK_CLIENT_SECRET`
   every `kb.*` call is a 401. Ask them for all missing lines plus one `pnpm dev` restart at once.
   Writes and approvals through NestJS: `user-token` skill + `POST /api/approvals/<id>` `{"decision":"approve"|"reject"}`.
1. Infra: `pnpm stack:up` (waits for healthy). Check port 8000 is free: `lsof -iTCP:8000 -sTCP:LISTEN`.
2. AI service in the background, free first: `LLM_PROVIDER=fake pnpm dev ai > $S/ai.log 2>&1`
   (shell vars win over `.env`). Real model: `pnpm dev ai` — costs ~0.001 USD per turn; say so.
3. Wait for ready: `until curl -sf localhost:8000/readyz; do sleep 1; done` (bge-m3 load takes ~30 s).
4. Token + turn. `sub` and roles come from the token (no `user` body since M2.4), so exchange a seed
   user's token like the API does (hop 1); a bare service token has no roles and gets no tools:

   ```bash
   BOB=$(.claude/skills/user-token/login.sh bob)   # carol = viewer, alice = admin
   TOKEN=$(curl -s -d grant_type=urn:ietf:params:oauth:grant-type:token-exchange -d client_id=kb-api \
     -d client_secret=dev-only-change-me -d subject_token=$BOB \
     -d subject_token_type=urn:ietf:params:oauth:token-type:access_token -d audience=kb-ai \
     http://localhost:8080/realms/kb/protocol/openid-connect/token | sed -E 's/.*"access_token":"([^"]+)".*/\1/')
   curl -sN localhost:8000/v1/agent -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
     -d '{"conversation_id":"'$(uuidgen | tr A-Z a-z)'","messages":[{"role":"user","parts":[{"type":"text","text":"QUESTION"}]}]}' > $S/turn.sse
   ```

5. Summarize: `python3 .claude/skills/agent-turn-check/summarize.py $S/turn.sse` (event list, answer, trace id).
6. Span tree: `python3 .claude/skills/agent-turn-check/spans.py <traceId>` — expect `agent.run` → `llm`
   (prompt version + model) → `ChatCompletion` and `tool` → `MCP send tools/call` → `tools/call …` →
   `search` → `embed` (the KB tools go through the own MCP server, ADR-0010).
7. Stop the AI service task when done; leave the infra running unless asked.

## Pitfalls

- The exchange fails (HTTP 400/403) or tool results say `Keycloak token endpoint: HTTP 401`: the realm
  predates M2.4 or `AI_KEYCLOAK_CLIENT_SECRET` is unset. Resetting wipes the user's
  data — ask, or check on a throwaway Keycloak (`realm-check` skill).

- Many `no hits` usually means the local corpus, not the harness: count the documents with
  `curl -s -X POST localhost:6333/collections/kb_current/facet -H 'content-type: application/json' -d '{"key":"doc_id","limit":100}'`
  and upload `data/sample-docs/*` via `/v1/documents` (see docs/setup/startup.md §4) if the runbooks are missing.
- Parallel tool spans start at the same time: build the tree from `parent_id`, never from start order.
- Phoenix REST: `GET localhost:6006/v1/projects/default/spans?trace_id=<id>&limit=100` → `data[]` with
  `context.span_id`, `parent_id`, `span_kind`, `attributes`.
