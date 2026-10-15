from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from opentelemetry import trace
from pydantic import BaseModel

router = APIRouter(tags=["health"])
status_router = APIRouter(prefix="/v1", tags=["health"])
tracer = trace.get_tracer(__name__)


class HealthResponse(BaseModel):
    status: Literal["ok"]


@router.get("/healthz")
async def healthz() -> HealthResponse:
    """Liveness probe."""
    return HealthResponse(status="ok")


@router.get("/readyz")
def readyz(request: Request) -> HealthResponse:
    """Readiness: embedding model loaded (set at startup) and the Qdrant alias reachable."""
    kb = getattr(request.app.state, "kb", None)
    try:
        ready = kb is not None and kb.client.collection_exists(kb.alias)
    except Exception:
        ready = False
    if not ready:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Qdrant or embedding model not ready"
        )
    return HealthResponse(status="ok")


@status_router.get("/status")
async def service_status() -> HealthResponse:
    """Authenticated status for the API's admin status card; emits one span to Phoenix."""
    with tracer.start_as_current_span("status"):
        return HealthResponse(status="ok")
