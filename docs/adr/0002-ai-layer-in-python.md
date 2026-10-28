# ADR-0002: All AI code lives in a Python service; NestJS is the product API

- **Status:** Accepted
- **Date:** 2026-10-12
- **Plan reference:** D3, D5, D11, D12, D21

## Context

Grove needs retrieval (parsing, chunking, embeddings, vector search), grounded generation with
streaming, an evaluation harness and LLM tracing — and in Phase 2 an agent loop, tools and an MCP client.
The surrounding product needs authentication, RBAC, document metadata, quotas and an HTTP API for the
browser. The AI ecosystem (fastembed, qdrant-client, OpenInference, Phoenix, eval tooling, MLflow) is
Python-first.

## Decision

- **`apps/ai-service` (FastAPI, Python 3.13) owns all AI concerns:** parsing, chunking, embeddings,
  retrieval, prompting, LLM calls, evals, tracing; from Phase 2 also the agent loop, tools and the MCP
  client.
- **`apps/api` (NestJS 12) is the product API / BFF:** authentication (Keycloak JWT), RBAC, document
  metadata in Postgres, throttling, and relaying the AI service's SSE stream unchanged.
- **Only NestJS (and the web app) are browser-facing.** The AI service is internal and requires a
  client-credentials token with `aud=kb-ai` plus a `user` context object; Keycloak token exchange
  (on-behalf-of) replaces the context object in Phase 2/3.

## Alternatives considered

- **AI in NestJS (TypeScript)** — possible with the OpenAI SDK and Qdrant JS client, but evals, tracing
  and retrieval tuning would be split from the Python tooling; every experiment would cross languages.
- **Python only (FastAPI as the product API)** — loses the NestJS learning goal and the clean separation
  of the product/security boundary from the AI runtime.
- **Agent framework (LangChain, LlamaIndex …)** — rejected through Phase 2: writing against the raw
  `openai` SDK teaches what frameworks hide (D11).

## Consequences

- Retrieval, prompt and LLM call run in one process: no network hop while tuning, one trace per request.
- Two hops for chat (browser → Nest → AI service): abort must propagate on both, and SSE must survive
  proxies (tested in M1.4/M1.6).
- Contracts span three apps: OpenAPI + JSON Schema in `packages/contracts`, drift-checked in CI (D14).
- Two runtimes to operate and containerise; acceptable, and a realistic enterprise pattern.
