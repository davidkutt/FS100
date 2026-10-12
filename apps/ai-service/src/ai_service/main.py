from fastapi import FastAPI
from pydantic import BaseModel

from ai_service import __version__
from ai_service.api import health
from ai_service.core.settings import Settings, get_settings


class ServiceInfo(BaseModel):
    service: str
    version: str
    docs: str


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="FS100 AI service", version=__version__)
    app.include_router(health.router)

    @app.get("/", tags=["meta"])
    async def info() -> ServiceInfo:  # pyright: ignore[reportUnusedFunction]
        return ServiceInfo(service=settings.otel_service_name, version=__version__, docs="/docs")

    return app


app = create_app()
