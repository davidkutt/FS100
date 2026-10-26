from functools import lru_cache
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from ai_service.embeddings import Sparse
from ai_service.knowledge_base import Domain


class Settings(BaseSettings):
    """Runtime configuration, read from the process environment.

    `pnpm dev` loads the repo-root `.env` before starting the service; containers
    get their environment from Compose (and later Helm / Azure). Variable names
    match `.env.example` (case-insensitive).
    """

    # env_ignore_empty: `.env.example` leaves optional values blank (`QDRANT_API_KEY=`).
    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True)

    ai_port: int = 8000
    ai_keycloak_issuer: str = "http://localhost:8080/realms/kb"
    ai_keycloak_audience: str = "kb-ai"
    ai_keycloak_realm_url: str = ""  # JWKS and token base URL; empty = the issuer (Compose differs)
    # Confidential client kb-ai: hop-2 token exchange and the internal ingest (ADR-0009).
    ai_keycloak_client_id: str = "kb-ai"
    ai_keycloak_client_secret: str = ""
    # The MCP server's resource URL = the audience of hop-2 tokens; the agent connects to it.
    mcp_resource_url: str = "http://localhost:8000/mcp"
    ai_api_url: str = "http://localhost:3000"  # NestJS, for `ingest_url`
    qdrant_url: str = "http://localhost:6333"  # ":memory:" = in-process Qdrant (tests, evals)
    qdrant_api_key: str | None = None
    qdrant_alias: str = "kb_current"
    # Originals and jobs (D52, D53); created on boot if missing. ":memory:" = in-process (tests).
    ai_database_url: str = "postgresql://postgres:dev-only-change-me@localhost:5432/ai"
    jobs_inprocess_worker: bool = True  # false from P4: a separate worker Deployment
    golden_dataset: str = "../../evals/datasets/retrieval_v1.jsonl"  # the re-index gate (D55)
    embedding_model: str = "BAAI/bge-m3"
    embedding_cache_dir: str = ".cache/fastembed"
    chunk_size: int = 1000
    chunk_overlap: int = 150
    # Parent sections (D59, ADR-0018): search returns each once, with its whole text (≤ this many
    # characters); 0 = each chunk is its own parent. A change takes effect with `pnpm kb:reindex`.
    parent_size: int = 2000
    # Sparse side of new collections (D56, ADR-0016); a change takes effect with `pnpm kb:reindex`.
    sparse_model: Sparse = "bm25-english"
    # Cross-encoder over the fused candidates (D57); off: it lost hit@5 on `test` (ADR-0017). Its
    # scores replace the cosine similarity, so RETRIEVAL_SCORE_THRESHOLD changes with it.
    reranker_model: str = "none"
    rerank_candidates: int = 10  # jina int8: p95 1.5 s on the M1 (D57)
    retrieval_top_k: int = 5
    retrieval_score_threshold: float | None = 0.55
    query_model: str = ""  # query transformation (D58); empty = LLM_MODEL
    # Contextual retrieval (D60, ADR-0019): documents of these domains (comma-separated) get a
    # context per chunk at ingest, which sends each whole document to LLM_BASE_URL. Empty = off.
    # A change applies to new uploads; `pnpm kb:reindex` applies it to the stored documents.
    contextual_domains: Annotated[list[Domain], NoDecode] = []
    contextual_model: str = ""  # empty = LLM_MODEL
    contextual_max_cost_usd_per_doc: float = 0.05  # then the rest of its chunks go without context
    llm_provider: Literal["openai_compat", "fake"] = "fake"  # unset = no paid calls (tests, CI)
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_max_output_tokens: int = 800
    llm_timeout_s: float = 60
    # Relative to the app directory (`pnpm dev`, tests); the image sets absolute paths.
    models_config: str = "../../config/models.yaml"
    taxonomy_config: str = "../../config/taxonomy.yaml"
    mcp_servers_config: str = "../../config/mcp_servers.yaml"
    # Domain routing (D33): the embedding router needs no tokens; `llm` asks ROUTER_MODEL.
    router: Literal["embedding", "llm"] = "embedding"
    router_model: str = ""  # empty = LLM_MODEL
    # The repo the GitHub MCP server reads, and the one write (D37, D39); PATs live in `.env.local`.
    github_repo: str = ""
    github_sandbox_repo: str = ""
    github_pat_sandbox_write: str = ""
    web_fetch_allowed_hosts: str = ""  # comma-separated host[:port]; empty = no `web.fetch`
    agent_max_steps: int = 8
    agent_max_parallel_tools: int = 4
    agent_tool_timeout_s: float = 20
    agent_run_timeout_s: float = 120
    agent_run_input_token_budget: int = 60_000
    agent_run_cost_cap_usd: float = 0.05
    # Comma-separated: the first signs, all verify (rotation). Empty = write tools fail closed.
    approval_signing_key: str = ""
    approval_ttl_min: float = 15
    otel_exporter_otlp_endpoint: str = ""  # empty = tracing off (tests, CI)
    otel_service_name: str = "ai-service"

    @field_validator("contextual_domains", mode="before")
    @classmethod
    def _comma_separated(cls, value: object) -> object:
        return (
            [part.strip() for part in value.split(",") if part.strip()]
            if isinstance(value, str)
            else value
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
