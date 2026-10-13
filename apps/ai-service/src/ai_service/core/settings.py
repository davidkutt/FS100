from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from ai_service.core.logging import LogLevel


class Settings(BaseSettings):
    """Runtime configuration, read from the process environment.

    `pnpm dev` loads the repo-root `.env` before starting the service; containers
    get their environment from Compose (and later Helm / Azure). Variable names
    match `.env.example` (case-insensitive); `KEY=` (empty) behaves like an unset variable.
    """

    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True)

    ai_port: int = 8000
    log_level: LogLevel = "info"
    otel_service_name: str = "ai-service"


@lru_cache
def get_settings() -> Settings:
    return Settings()
