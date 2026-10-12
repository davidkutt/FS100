from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]


@router.get("/healthz")
async def healthz() -> HealthResponse:
    """Liveness probe. Readiness (`/readyz`: Qdrant reachable, model loaded) follows in M1.2."""
    return HealthResponse(status="ok")
