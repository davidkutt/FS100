# syntax=docker/dockerfile:1
# Build from the repo root: docker build -f apps/ai-service/Dockerfile .
# The embedding model is not baked in: it downloads on first start into EMBEDDING_CACHE_DIR, a volume;
# Docling's models (≈ 1 GB) on the first PDF into HF_HOME, another one.
FROM python:3.13.16-slim-trixie AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY apps/ai-service/pyproject.toml apps/ai-service/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project
COPY apps/ai-service/src src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-editable

FROM python:3.13.16-slim-trixie
RUN useradd --create-home --uid 10001 app && mkdir -p /app/.cache/fastembed /app/.cache/huggingface \
  && chown app /app/.cache/fastembed /app/.cache/huggingface
WORKDIR /app
COPY --from=build /app/.venv .venv
COPY config/models.yaml config/taxonomy.yaml config/mcp_servers.yaml config/
# The re-index gate's golden set (D55).
COPY evals/datasets/retrieval_v1.jsonl evals/
ENV PATH=/app/.venv/bin:$PATH EMBEDDING_CACHE_DIR=/app/.cache/fastembed HF_HOME=/app/.cache/huggingface \
  MODELS_CONFIG=/app/config/models.yaml TAXONOMY_CONFIG=/app/config/taxonomy.yaml \
  MCP_SERVERS_CONFIG=/app/config/mcp_servers.yaml GOLDEN_DATASET=/app/evals/retrieval_v1.jsonl
USER app
EXPOSE 8000
# uvicorn listens only after startup loaded the model (first start downloads ≈ 2.3 GB for bge-m3).
# A TCP connect instead of GET /readyz: every HTTP request would be a trace in Phoenix.
HEALTHCHECK --interval=10s --timeout=3s --start-period=10m --retries=3 \
  CMD ["python", "-c", "import socket; socket.create_connection(('127.0.0.1', 8000), 2)"]
CMD ["uvicorn", "ai_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
