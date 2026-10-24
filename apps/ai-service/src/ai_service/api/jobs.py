import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, model_validator

from ai_service.api.documents import KB, Jobs, Originals
from ai_service.core.auth import get_caller, require_admin
from ai_service.jobs import (
    REINDEX,
    JobStatus,
    ReindexRun,
    defer,
    job_status,
    reindex_runs,
    rollback,
)

router = APIRouter(prefix="/v1", tags=["jobs"])
admin = APIRouter(prefix="/v1", tags=["jobs"], dependencies=[Depends(require_admin)])


class Queued(BaseModel):
    job_id: int


class ReindexRequest(BaseModel):
    reason: str = ""
    force: bool = False

    @model_validator(mode="after")
    def _forced_with_reason(self) -> "ReindexRequest":
        if self.force and not self.reason.strip():
            raise ValueError("`force` needs a `reason` (D55)")
        return self


class ReindexStatus(BaseModel):
    alias: str
    collection: str
    runs: list[ReindexRun]


class Alias(BaseModel):
    alias: str
    collection: str


@router.get("/jobs/{job_id}")
async def get_job(jobs: Jobs, store: Originals, job_id: int) -> JobStatus:
    found = await job_status(jobs, store, job_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Job {job_id} not found")
    return found


@admin.post("/reindex", status_code=status.HTTP_202_ACCEPTED)
async def start_reindex(request: Request, jobs: Jobs, body: ReindexRequest) -> Queued:
    """Build a collection from the stored originals, gate it on the golden set, swap (D55)."""
    requested_by = get_caller(request).sub
    job_id = await defer(jobs, REINDEX, **body.model_dump(), requested_by=requested_by)
    return Queued(job_id=job_id)


@admin.get("/reindex")
async def reindex_status(kb: KB, jobs: Jobs, store: Originals) -> ReindexStatus:
    """Where the alias points, and the latest runs with their reports."""
    collection = await asyncio.to_thread(kb.live_collection)
    runs = await reindex_runs(jobs, store)
    return ReindexStatus(alias=kb.alias, collection=collection, runs=runs)


@admin.post("/reindex/rollback")
async def reindex_rollback(kb: KB, jobs: Jobs, store: Originals) -> Alias:
    """Point the alias back at the collection the last swap replaced."""
    try:
        collection = await rollback(jobs, store, kb.client, kb.alias)
    except LookupError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    return Alias(alias=kb.alias, collection=collection)
