# Architecture Decision Records

Short, numbered records of decisions that shape FS100. Each ADR references the decision ids of
[plan.md §3](../../plan.md#3-decisions) (`D1` … `D26`) or
[plan-phase-2.md §3](../../plan-phase-2.md#3-decisions) (`D27` … `D49`) or
[plan-phase-3.md §3](../../plan-phase-3.md#3-decisions) (`D50` …).

| ADR | Title | Status |
|---|---|---|
| [0001](0001-monorepo-and-pnpm.md) | Monorepo with pnpm workspaces, uv for Python | Accepted |
| [0002](0002-ai-layer-in-python.md) | All AI code lives in a Python service; NestJS is the product API | Accepted |
| [0003](0003-embeddings-in-process.md) | Embeddings computed in-process with fastembed | Accepted |
| [0004](0004-embedding-model-chunking-threshold.md) | Embedding model `bge-m3`, chunking 1000/150, score threshold 0.55 (benchmark) | Accepted |
| [0005](0005-llm-access-and-model.md) | LLM access via one OpenAI-compatible adapter; dev model `gpt-6-luna`, demo model `deepseek-v4.1-flash` | Accepted |
| 0006 | Azure region and quota | Planned — M1.7, postponed |
| [0007](0007-agent-harness-and-limits.md) | Own agent harness with hard limits; dev model for agent mode `gpt-6-luna` (tool-calling shortlist) | Accepted |
| [0008](0008-run-state-and-approvals.md) | Stateless agent turns; approvals as HMAC-signed actions, at-most-once | Accepted |
| [0009](0009-token-exchange-internal-hops.md) | Keycloak standard token exchange on the internal hops; delegation dropped for P2 | Accepted |
| [0010](0010-own-mcp-server-sdk-v2.md) | Own MCP server and client on Python SDK v2 (GitHub MCP check) | Accepted |
| [0011](0011-plain-vs-agentic-rag.md) | Agentic RAG for conversations; plain RAG stays the measured baseline | Proposed |
| [0012](0012-embedding-vs-llm-router.md) | Embedding router by default; the LLM classifier stays opt-in | Proposed |
| [0013](0013-prompt-versioning.md) | Prompts as versioned files in the repo, with a content hash on every record | Accepted |
| [0014](0014-external-mcp-clients-cimd.md) | External MCP clients via Keycloak CIMD, with the experimental features always on | Accepted |
| [0015](0015-stored-originals-job-queue-reindex.md) | Stored originals, a Postgres job queue and an eval-gated re-index | Accepted |
| [0016](0016-hybrid-search-sparse-side.md) | Hybrid search — BM25 computed in the AI service, weighted RRF | Accepted |
| [0017](0017-reranker.md) | Reranking — built and measured, off by default | Accepted |
| [0018](0018-docling-parent-child-chunking.md) | Docling parsing and parent-child chunking | Accepted |
| [0019](0019-contextual-retrieval-chunk-topics.md) | Contextual retrieval and chunk sub-topics — on for all domains, threshold kept | Accepted |

## Writing a new ADR

1. Copy [`template.md`](template.md) to `NNNN-short-title.md` (next free number).
2. Keep it short: context, decision, consequences. Link evidence (eval runs, spikes, benchmarks).
3. Add it to the table above in the same PR. Superseded ADRs stay, with a link to their successor.
