# ai-service

FastAPI service (Python 3.13, managed with [uv](https://docs.astral.sh/uv/)) that owns every AI concern of
FS100: parsing, chunking, embeddings, retrieval, grounded chat, evals and tracing (plan.md D3,
[ADR-0002](../../docs/adr/0002-ai-layer-in-python.md)). Internal only — the browser talks to the NestJS API.

| Command (from the repo root)                                                        | What it does                    |
| ----------------------------------------------------------------------------------- | ------------------------------- |
| `uv sync --directory apps/ai-service`                                               | create `.venv`, install deps    |
| `uv run --directory apps/ai-service uvicorn ai_service.main:app --reload --port 8000` | dev server (also via `pnpm dev`) |
| `pnpm test:ai`                                                                      | pytest                          |
| `pnpm lint:ai`                                                                      | ruff check + format check, pyright (strict) |

Endpoints (all `/v1` routes are included with the `ServiceAuth` dependency in `main.py`, i.e. they need the
API's service token, `aud=kb-ai`):

| Endpoint | What it does |
|---|---|
| `GET /healthz` · `GET /readyz` | liveness · readiness (embedding model loaded, Qdrant alias reachable) |
| `POST /v1/ingest` | multipart `file` (PDF/MD/TXT), `doc_id`, `owner_id`, `domains` (repeat the field), `title?` → parse, chunk, embed, upsert; re-ingest replaces |
| `POST /v1/search` | `{query, top_k=5, score_threshold?, domains?, doc_ids?}` → hits with score, page, heading path |
| `POST /v1/chat` | `{messages:[{role, content}], domains?, user:{sub, roles}}` → SSE `sources`, `token`…, `done` \| `error` (plan.md §7.3); retrieval uses `RETRIEVAL_TOP_K` / `RETRIEVAL_SCORE_THRESHOLD` |
| `POST /v1/agent` | `{conversation_id, messages:[{role, parts:[{type:"text", text}]}], mode="agent"\|"rag", domains?, user:{sub, roles}}` → SSE v2 `step`, `tool_call`, `tool_result`, `sources`, `token`…, `done` (+ `error`) (plan-phase-2 §7.3); `mode=rag` runs the `/v1/chat` pipeline as baseline; limits `AGENT_*` (ADR-0007) |
| `DELETE /v1/documents/{doc_id}` | removes all points of a document → 204 |
| `GET /v1/status` | authenticated status for the API's admin card (one span to Phoenix) |
| `GET /` · `/docs` | service info · OpenAPI UI |

On startup the service loads `EMBEDDING_MODEL` (first run downloads it into `EMBEDDING_CACHE_DIR`,
0.5–2.3 GB) and points the Qdrant alias `kb_current` at the model's collection `kb__<model>__<dim>`;
`/readyz` stays 503 until both are done. Chat calls the LLM named by `LLM_PROVIDER`: `openai_compat`
(needs `LLM_API_KEY` + `LLM_MODEL`, else startup fails; OpenRouter or the HF router via `LLM_BASE_URL`)
or `fake` (deterministic, free — the default when unset, used by tests and CI). A different model therefore starts with an empty collection —
see `data/sample-docs/runbook-embedding-model-swap.md`. `QDRANT_URL=:memory:` runs Qdrant in-process
(tests, evals).

**Evals:** `pnpm eval:retrieval` (CLI `kb-eval retrieval`) — see [`evals/README.md`](../../evals/README.md).

Layout: `api/` routers (health, documents, chat) · `core/` settings, auth, JSON logging, tracing (OTLP →
Phoenix, OpenInference spans for the `openai` SDK) · `ingest.py` parsers + chunker · `embeddings.py`
fastembed + E5 prefixes · `knowledge_base.py` Qdrant collection/alias, ingest, search, delete · `llm.py`
provider protocol, `openai_compat`, `fake` · `rag.py` prompt builder, citation check, gap signal, chat pipeline · `agent.py` agent loop (limits,
parallel read tools, retries, cancellation), `mode=rag` adapter · `tools.py` `ToolSpec`, role policy,
untrusted-output wrapper, native KB search tool ·
`evals/` metrics + runner · `tests/` (no network, no model download: fastembed is faked, Qdrant runs in
memory, the LLM is `fake` or a mocked HTTP endpoint). Add dependencies with `uv add <pkg>` (runtime) or
`uv add --dev <pkg>`.
