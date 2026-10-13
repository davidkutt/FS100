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

Endpoints today: `GET /` (service info), `GET /healthz`, OpenAPI UI at `/docs`. Logs are JSON lines on stdout
(`LOG_LEVEL`); every response carries `x-request-id` (the caller's, if safe, else a new UUID).

Layout (grows per plan.md §6): `src/ai_service/api/` routers · `core/` settings (later auth, logging,
tracing) · `tests/`. Add dependencies with `uv add <pkg>` (runtime) or `uv add --dev <pkg>`.
