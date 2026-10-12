# Architecture Decision Records

Short, numbered records of decisions that shape FS100. Each ADR references the decision ids of
[plan.md §3](../../plan.md#3-decisions) (`D1` … `D26`).

| ADR | Title | Status |
|---|---|---|
| [0001](0001-monorepo-and-pnpm.md) | Monorepo with pnpm workspaces, uv for Python | Accepted |
| [0002](0002-ai-layer-in-python.md) | All AI code lives in a Python service; NestJS is the product API | Accepted |
| [0003](0003-embeddings-in-process.md) | Embeddings computed in-process with fastembed | Accepted |
| 0004 | Embedding model, chunking and score threshold (benchmark) | Planned — M1.2 |
| 0005 | LLM access via OpenAI-compatible adapter; dev/demo model choice | Planned — M1.3 |
| 0006 | Azure region and quota | Planned — M1.7 |

## Writing a new ADR

1. Copy [`template.md`](template.md) to `NNNN-short-title.md` (next free number).
2. Keep it short: context, decision, consequences. Link evidence (eval runs, spikes, benchmarks).
3. Add it to the table above in the same PR. Superseded ADRs stay, with a link to their successor.
