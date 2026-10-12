from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from the process environment.

    `pnpm dev` loads the repo-root `.env` before starting the service; containers
    get their environment from Compose (and later Helm / Azure). Variable names
    match `.env.example` (case-insensitive).
    """

    model_config = SettingsConfigDict(extra="ignore")

    ai_port: int = 8000
    otel_service_name: str = "ai-service"


@lru_cache
def get_settings() -> Settings:
    return Settings()
