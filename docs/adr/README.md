# Architecture Decision Records

Short, numbered records of decisions that shape FS100. Each ADR references the decision ids of
[plan.md §3](../../plan.md#3-decisions) (`D1` … `D26`) or
[plan-phase-2.md §3](../../plan-phase-2.md#3-decisions) (`D27` …).

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

## Writing a new ADR

1. Copy [`template.md`](template.md) to `NNNN-short-title.md` (next free number).
2. Keep it short: context, decision, consequences. Link evidence (eval runs, spikes, benchmarks).
3. Add it to the table above in the same PR. Superseded ADRs stay, with a link to their successor.
