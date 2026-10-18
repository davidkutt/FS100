from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from opentelemetry import trace
from pydantic import BaseModel

router = APIRouter(tags=["health"])
status_router = APIRouter(prefix="/v1", tags=["health"])
tracer = trace.get_tracer(__name__)


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ServiceStatus(BaseModel):
    status: Literal["ok"]
    qdrant: Literal["ok", "down"]


def _ready(request: Request) -> bool:
    kb = getattr(request.app.state, "kb", None)
    try:
        return kb is not None and kb.client.collection_exists(kb.alias)
    except Exception:
        return False


@router.get("/healthz")
async def healthz() -> HealthResponse:
    """Liveness probe."""
    return HealthResponse(status="ok")


@router.get("/readyz")
def readyz(request: Request) -> HealthResponse:
    """Readiness: embedding model loaded (set at startup) and the Qdrant alias reachable."""
    if not _ready(request):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Qdrant or embedding model not ready"
        )
    return HealthResponse(status="ok")


@status_router.get("/status")
def service_status(request: Request) -> ServiceStatus:
    """Authenticated status for the API's admin status card; emits one span to Phoenix."""
    with tracer.start_as_current_span("status"):
        return ServiceStatus(status="ok", qdrant="ok" if _ready(request) else "down")
