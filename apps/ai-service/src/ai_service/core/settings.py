from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    qdrant_url: str = "http://localhost:6333"  # ":memory:" = in-process Qdrant (tests, evals)
    qdrant_api_key: str | None = None
    qdrant_alias: str = "kb_current"
    embedding_model: str = "BAAI/bge-m3"
    embedding_cache_dir: str = ".cache/fastembed"
    chunk_size: int = 1000
    chunk_overlap: int = 150
    otel_exporter_otlp_endpoint: str = ""  # empty = tracing off (tests, CI)
    otel_service_name: str = "ai-service"


@lru_cache
def get_settings() -> Settings:
    return Settings()
