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

Endpoints (all `/v1` routes are included with the `ServiceAuth` dependency in `main.py`, i.e. they need a
Keycloak token with `aud=kb-ai`: the user's, exchanged by the API (hop 1, ADR-0009), or the API's service
token for system calls; `sub` and realm roles come from that token):

| Endpoint | What it does |
|---|---|
| `GET /healthz` · `GET /readyz` | liveness · readiness (embedding model loaded, Qdrant alias reachable) |
| `POST /v1/documents` | multipart `file` (PDF/MD/TXT, ≤ 20 MB), `doc_id`, `owner_id`, `domains` (repeat the field), `topics?` (taxonomy ids), `title?` → original stored in Postgres `ai`, ingest queued → `202 {job_id, version}`; the same bytes keep their version, new bytes get the next one (D52) |
| `GET /v1/jobs/{job_id}` | `{state: queued\|parsing\|embedding\|building\|evaluating\|ready\|failed\|cancelled, error?, result?}`; `result` is the ingest result or the re-index report |
| `POST /v1/reindex` · `GET /v1/reindex` · `POST /v1/reindex/rollback` | admin only (role in the exchanged token): queue a re-index `{reason, force}` (force needs a reason) → `202 {job_id}`; alias target + latest runs with reports; point the alias back at the collection the last swap replaced (409 if none) (D55) |
| `POST /v1/search` | `{query, top_k=5, score_threshold?, domains?, doc_ids?, explain=false, strategy=plain}` → `{embedding_model, reranker_model, hits}`, hits in reranked order with the reranker's score (without a reranker: fused order, dense score), page, heading path; `explain` adds each hit's rank among the fused candidates and in the dense and the sparse top 50 (ADR-0016, ADR-0017); `strategy: hyde` adds a drafted passage (below) |
| `POST /v1/chat` | `{messages:[{role, content}], domains?}` → SSE `sources`, `token`…, `done` \| `error` (plan.md §7.3); retrieval uses `RETRIEVAL_TOP_K` / `RETRIEVAL_SCORE_THRESHOLD` |
| `POST /v1/agent` | `{conversation_id, messages:[{role, parts:[{type:"text", text}]}], mode="agent"\|"rag", model?, domains?, resume?:{signed_action, decision, note?, args}}` → SSE v2 `step`, `tool_call`, `tool_result`, `sources`, `token`…, `approval_required`, `done` (+ `error`) (plan-phase-2 §7.3); a write call ends the turn with an HMAC-signed action (`APPROVAL_SIGNING_KEY`, `APPROVAL_TTL_MIN`), `resume` continues it after checking signature, expiry, `sub`, conversation and args hash (else 422, ADR-0008); `mode=rag` runs the `/v1/chat` pipeline as baseline; limits `AGENT_*` (ADR-0007) |
| `PATCH /v1/documents/{doc_id}/labels` | `{domains?, topics?}` → payload update on every chunk, no re-embedding → 204; unknown topics → 422 |
| `GET /v1/models` · `GET /v1/tools` | model registry (`MODELS_CONFIG`) and tool registry with `min_role`; `model` on `/v1/agent` must be a registry id the caller's role reaches (tool-capable in agent mode), else 422; none = `LLM_MODEL` |
| `DELETE /v1/documents/{doc_id}` | cancels a queued ingest, removes the points from every `kb__*` collection (a rollback cannot bring them back) and the stored originals → 204; 409 while its job runs |
| `GET /v1/status` | authenticated status for the API's admin card (one span to Phoenix) |
| `/mcp` | own MCP server (SDK v2, stateless Streamable HTTP, ADR-0010): tools `search_knowledge_base` (optional `strategy`: `plain` \| `hyde`), `get_document`, `list_sources`, `ingest_url` (asks for confirmation first, then calls the API's `/internal/documents/from-url`), resource `kb://documents/{doc_id}`; Bearer with `aud=MCP_RESOURCE_URL` and scope `kb:read` (`kb:write` + editor for `ingest_url`), else 401/403 with a `WWW-Authenticate` challenge |
| `GET /.well-known/oauth-protected-resource/mcp` | RFC 9728 metadata of `/mcp` (public) |
| `GET /` · `/docs` | service info · OpenAPI UI |

On startup the service loads `EMBEDDING_MODEL` and, if set, `RERANKER_MODEL` (first run downloads them
into `EMBEDDING_CACHE_DIR`, 0.5–2.3 GB and 0.1–0.3 GB), creates the Postgres database `ai` if missing and migrates it (`AI_DATABASE_URL`;
`:memory:` = in-process, tests), starts the in-process job worker (`JOBS_INPROCESS_WORKER`, one job at a
time) and, only if the Qdrant alias `kb_current` does not exist yet, points it at a new empty collection
`kb__v2__<model>__<dim>__<timestamp>` (D54); after that only `pnpm kb:reindex` moves it. `/readyz` stays
503 until the model and the alias are there. Chat calls the LLM named by `LLM_PROVIDER`: `openai_compat`
(needs `LLM_API_KEY` + `LLM_MODEL`, else startup fails; OpenRouter or the HF router via `LLM_BASE_URL`)
or `fake` (deterministic, free — the default when unset, used by tests and CI). A different
`EMBEDDING_MODEL` needs `pnpm kb:reindex --force --reason …` (the gate cannot compare across models; the
service logs a warning until then). `QDRANT_URL=:memory:` runs Qdrant in-process (tests, evals).

**Hybrid search (D56, ADR-0016):** every collection records its sparse side (`SPARSE_MODEL`, default
`bm25-english`: fastembed's `Qdrant/bm25`, a few KB downloaded on first use; `none` = dense only) in its
metadata, and ingest and search follow the collection, so a rollback to an older one keeps working. A
new `SPARSE_MODEL` takes effect with `pnpm kb:reindex` (the service logs a warning until then). A search
fuses the dense and the sparse top 50 under the same filter (RRF with Qdrant's k = 2, the sparse side at
half weight); `score` is the dense cosine similarity, and `RETRIEVAL_SCORE_THRESHOLD` applies to the
best hit — below it the search returns no hits (abstains), above it every hit stays.

**Reranking (D57, ADR-0017), off by default** (`RERANKER_MODEL=none`): it lost hit@5 on the exact-term
items of `test`. Opt-in: a fastembed cross-encoder (ONNX, CPU) scores the top `RERANK_CANDIDATES` (10;
`top_k` if larger) fused hits and keeps the best `top_k`; `score` is then its logit through a sigmoid
(0–1) and the threshold applies to that. It takes effect on restart, without a re-index, but needs its
own threshold: `jinaai/jina-reranker-v2-base-multilingual-int8` (**CC BY-NC 4.0**, p95 ≈ 1.5 s on the
M1) 0.35, `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1-int8` (Apache-2.0, ≈ 0.6 s) 0.40.

**HyDE per search (D58, M3a.4):** with `strategy: hyde` (MCP `search_knowledge_base`, `/v1/search`)
`QUERY_MODEL` (empty = `LLM_MODEL`) drafts a passage of at most 100 words that answers the query
(structured output, `prompts/hyde.md`); it joins the fusion as one more dense prefetch, while the reranker
and `score` still use the query, so the threshold holds. On `test` nDCG@10 0.81 → 0.87 for ~0.0001 USD,
but +3.6 s p50 with `openai/gpt-6-luna` — so the agent picks it per search; the chat (`mode=rag`) stays
plain. Passages are cached in the process per prompt, model and query (1,024 entries); a failed call (or
`LLM_PROVIDER=fake`) logs a warning and searches the query alone. Its cost is not yet counted in the
turn's usage or the cost caps.

**Contextual retrieval and chunk sub-topics (D60, ADR-0019, M3a.6):** for documents of
`CONTEXTUAL_DOMAINS` the ingest job (state `contextualizing`) asks `CONTEXTUAL_MODEL` (empty =
`LLM_MODEL`) once per chunk, with the whole document in the system message (cached by the provider after
the first call) and the chunk last, for `{context, topics}` (structured output, `prompts/contextual.md`).
The context (≤ 50 words) is embedded with the chunk on the dense and the sparse side and stored as
`context`, never cited; `topics` keeps only sub-topics of the document's domains (`chunk_topics`, next to
the document's own `topics`). A chunk without one — its domains are off, the call failed, or the document
reached `CONTEXTUAL_MAX_COST_USD_PER_DOC` — gets the sub-topic whose taxonomy description is most similar
to its vector. Labels are stored in `ai.chunk_contexts` by the hash of model and messages, so a re-index
reuses them (free and reproducible; contexts differ from run to run); the job result and the re-index
report record the cost of new calls per document (~0.035 USD for the sample corpus with
`openai/gpt-6-luna`).

**Re-index (D55, ADR-0015):** `pnpm kb:backfill-originals` stores the originals of documents indexed
before Phase 3 (found in `data/sample-docs/` by SHA-256; the rest are listed for re-upload).
`pnpm kb:reindex [--force --reason "…"]` queues the job for the running service's worker and prints the
report: build from the stored originals → golden `dev` + `test` against the new and the live collection
→ swap only if no `test` metric (hit@5, MRR@10, nDCG@10, abstention) drops by more than 0.02 and every
live document has an original; a refused build is deleted. `pnpm kb:reindex --rollback` re-points the
alias. Runs started on the admin page are in the API's audit log; CLI runs record `cli:<user>` and the
reason in the run report only.

**Evals:** `pnpm eval:retrieval` (CLI `kb-eval retrieval`) — see [`evals/README.md`](../../evals/README.md).

Layout: `api/` routers (health, documents, chat) · `core/` settings, auth, JSON logging, tracing (OTLP →
Phoenix, OpenInference spans for the `openai` SDK) · `ingest.py` parsers (PDFs by Docling in a child
process, pypdf as the fallback; stored parses) + chunker with parent sections · `contextual.py` context
and sub-topics per chunk (D60) · `embeddings.py`
fastembed + E5 prefixes · `knowledge_base.py` Qdrant collection/alias, ingest, search, delete · `llm.py`
provider protocol, `openai_compat`, `fake` · `prompts/` prompt files with `id`/`version` front matter, loaded with a content hash (ADR-0013) · `rag.py` prompt builder, citation check, gap signal, chat pipeline · `agent.py` agent loop (limits,
parallel read tools, retries, cancellation), `mode=rag` adapter · `tools.py` `ToolSpec`, role policy,
untrusted-output wrapper, KB tools via MCP · `mcp_server.py` the `/mcp` server · `mcp_client.py` calls it
with the caller's hop-2 token from `tokens.py` (Keycloak exchange as `kb-ai`, cached) ·
`storage.py` database `ai`: originals, job progress, migrations · `jobs.py` Procrastinate tasks (ingest,
re-index, stalled-job retry) and the worker · `reindex.py` build, gate, swap, rollback · `admin.py`
`kb-admin` CLI · `evals/` metrics + runner · `tests/` (no network, no model download: fastembed is faked, Qdrant runs in
memory, the LLM is `fake` or a mocked HTTP endpoint). Add dependencies with `uv add <pkg>` (runtime) or
`uv add --dev <pkg>`.
