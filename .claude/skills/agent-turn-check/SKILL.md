---
name: agent-turn-check
description: Streams one `POST /v1/agent` turn against the locally running AI service with a kb-api service token, summarizes the SSE v2 events, and prints that turn's Phoenix span tree through Phoenix's REST API. Use when verifying an agent/harness change end to end ("curl /v1/agent", "does Phoenix show the span tree", "try the agent with the real model", check tool calls, stopReason, cached tokens).
---

# Agent turn + Phoenix span tree

Run from the repo root. Scratch files go to the session scratchpad (`$S` below).

1. Infra: `pnpm stack:up` (waits for healthy). Check port 8000 is free: `lsof -iTCP:8000 -sTCP:LISTEN`.
2. AI service in the background, free first: `LLM_PROVIDER=fake pnpm dev ai > $S/ai.log 2>&1`
   (shell vars win over `.env`). Real model: `pnpm dev ai` — costs ~0.001 USD per turn; say so.
3. Wait for ready: `until curl -sf localhost:8000/readyz; do sleep 1; done` (bge-m3 load takes ~30 s).
4. Token + turn:

   ```bash
   TOKEN=$(curl -s -d grant_type=client_credentials -d client_id=kb-api -d client_secret=dev-only-change-me \
     http://localhost:8080/realms/kb/protocol/openid-connect/token | sed -E 's/.*"access_token":"([^"]+)".*/\1/')
   curl -sN localhost:8000/v1/agent -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
     -d '{"conversation_id":"'$(uuidgen | tr A-Z a-z)'","messages":[{"role":"user","parts":[{"type":"text","text":"QUESTION"}]}],"user":{"sub":"dev","roles":["viewer"]}}' > $S/turn.sse
   ```

5. Summarize: `python3 .claude/skills/agent-turn-check/summarize.py $S/turn.sse` (event list, answer, trace id).
6. Span tree: `python3 .claude/skills/agent-turn-check/spans.py <traceId>` — expect `agent.run` → `llm`
   (prompt version + model) → `ChatCompletion` and `tool` → `search` → `embed`.
7. Stop the AI service task when done; leave the infra running unless asked.

## Pitfalls

- Many `no hits` usually means the local corpus, not the harness: count the documents with
  `curl -s -X POST localhost:6333/collections/kb_current/facet -H 'content-type: application/json' -d '{"key":"doc_id","limit":100}'`
  and ingest `data/sample-docs/*` via `/v1/ingest` (see docs/setup/startup.md §4) if the runbooks are missing.
- Parallel tool spans start at the same time: build the tree from `parent_id`, never from start order.
- Phoenix REST: `GET localhost:6006/v1/projects/default/spans?trace_id=<id>&limit=100` → `data[]` with
  `context.span_id`, `parent_id`, `span_kind`, `attributes`.
