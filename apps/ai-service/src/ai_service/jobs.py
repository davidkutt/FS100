"""Jobs (D53, ADR-0015): Procrastinate in the database `ai`. Locally the worker runs inside the API
process, so jobs share its loaded models."""

import asyncio
import hashlib
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from opentelemetry import trace
from procrastinate import App, BaseConnector, JobContext, PsycopgConnector, RetryStrategy
from procrastinate.jobs import Job
from procrastinate.retry import RetryDecision
from procrastinate.testing import InMemoryConnector
from pydantic import BaseModel
from pypdf.errors import PyPdfError
from qdrant_client import QdrantClient

from ai_service import reindex as reindexing
from ai_service.contextual import Contextualizer
from ai_service.ingest import parse_stored
from ai_service.knowledge_base import SPAN_KIND, Domain, IngestResult, KnowledgeBase
from ai_service.reindex import ReindexReport
from ai_service.storage import (
    JobState,
    MemoryStore,
    PgStore,
    Progress,
    Store,
    ensure_database,
    migrate,
)

INGEST, REINDEX = "ingest", "reindex"
# Ingest and re-index never overlap: a build would miss a document upserted meanwhile.
KB_LOCK = "kb"
STATES: dict[str, JobState] = {
    "todo": "queued",
    "succeeded": "ready",
    "failed": "failed",
    "cancelled": "cancelled",
    "aborted": "cancelled",
}
RUNNING: tuple[JobState, ...] = (
    "parsing",
    "contextualizing",
    "embedding",
    "building",
    "evaluating",
)
Stage = Callable[[JobState], Awaitable[None]]
tracer = trace.get_tracer(__name__)


@dataclass(frozen=True)
class Deps:
    """What the tasks need, handed to the worker as `additional_context`."""

    kb: KnowledgeBase
    store: Store
    golden: Path
    threshold: float | None
    contextualizer: Contextualizer


class JobStatus(BaseModel):
    id: int
    state: JobState
    error: str | None = None
    result: IngestResult | ReindexReport | None = None


class ReindexRun(BaseModel):
    id: int
    state: JobState
    error: str | None = None
    reason: str
    force: bool
    requested_by: str
    report: ReindexReport | None = None


class _Transient(RetryStrategy):
    """Retries what may pass (Qdrant or Postgres away), never a document that cannot be parsed."""

    def get_retry_decision(self, *, exception: BaseException, job: Job) -> RetryDecision | None:
        if isinstance(exception, ValueError | PyPdfError):
            return None
        return super().get_retry_decision(exception=exception, job=job)


async def ingest(
    context: JobContext,
    *,
    doc_id: str,
    version: int,
    filename: str,
    owner_id: str,
    domains: list[Domain],
    topics: list[str],
    title: str | None,
) -> None:
    """Idempotent per document version: the point IDs derive from it (D54)."""
    deps = _deps(context)
    kb, store = deps.kb, deps.store

    async def work(stage: Stage) -> IngestResult | None:
        data = await store.original(UUID(doc_id), version)
        if data is None:
            return None  # deleted since
        attributes = {SPAN_KIND: "CHAIN", "doc_id": doc_id, "filename": filename}
        with tracer.start_as_current_span("ingest", attributes=attributes):
            await stage("parsing")
            with tracer.start_as_current_span("parse"):
                sections = await parse_stored(store, UUID(doc_id), version, filename, data)
            split = await asyncio.to_thread(kb.split, sections)
            if deps.contextualizer.on(domains):
                await stage("contextualizing")
            split, cost = await deps.contextualizer.contextualize(
                sections, split, doc_id=UUID(doc_id), version=version, domains=domains
            )
            await stage("embedding")
            result = await asyncio.to_thread(
                kb.index,
                split,
                doc_id=UUID(doc_id),
                version=version,
                filename=filename,
                sha256=hashlib.sha256(data).hexdigest(),
                owner_id=owner_id,
                domains=domains,
                topics=topics,
                title=title,
            )
            return result.model_copy(update={"context_cost_usd": cost})

    await _tracked(context, work)


async def reindex(context: JobContext, *, reason: str, force: bool, requested_by: str) -> None:
    deps = _deps(context)

    async def work(stage: Stage) -> ReindexReport:
        return await reindexing.reindex(
            deps.kb,
            deps.contextualizer,
            deps.store,
            deps.golden,
            deps.threshold,
            reason=reason,
            force=force,
            requested_by=requested_by,
            stage=stage,
        )

    await _tracked(context, work)


async def retry_stalled(context: JobContext, timestamp: int) -> None:
    await retry_stalled_jobs(context.app)


async def retry_stalled_jobs(jobs: App) -> None:
    """Jobs whose worker stopped sending heartbeats (crash, `kill -9`) run again."""
    for job in await jobs.job_manager.get_stalled_jobs():
        await jobs.job_manager.retry_job(job)


def create_jobs(connector: BaseConnector) -> App:
    jobs = App(connector=connector)
    retry = _Transient(max_attempts=3, exponential_wait=4)
    jobs.task(name=INGEST, queue="ingest", lock=KB_LOCK, retry=retry, pass_context=True)(ingest)
    jobs.task(name=REINDEX, queue="reindex", lock=KB_LOCK, pass_context=True)(reindex)
    stalled = jobs.task(name="retry_stalled", queue="maintenance", pass_context=True)
    jobs.periodic(cron="* * * * *")(stalled(retry_stalled))
    return jobs


@asynccontextmanager
async def open_jobs(url: str) -> AsyncGenerator[tuple[App, Store]]:
    """The queue and the store on the database `ai`, migrated on open."""
    if url == ":memory:":
        jobs = create_jobs(InMemoryConnector())
        async with jobs.open_async():
            yield jobs, MemoryStore()
        return
    await ensure_database(url)
    connector = PsycopgConnector(conninfo=url, max_size=4)
    async with create_jobs(connector).open_async() as jobs:
        await migrate(connector.pool)
        yield jobs, PgStore(connector.pool)


async def run_worker(jobs: App, deps: Deps, *, wait: bool = True) -> None:
    """One job at a time: parsing and embedding peak in jobs (D50). `wait=False`: drain, return."""
    await jobs.run_worker_async(
        concurrency=1,
        wait=wait,
        install_signal_handlers=False,  # uvicorn's
        shutdown_graceful_timeout=5,  # then the job is aborted and retried on the next start
        additional_context={"deps": deps},
    )


async def defer(jobs: App, task: str, **kwargs: Any) -> int:
    return await jobs.configure_task(task).defer_async(**kwargs)


async def job_status(jobs: App, store: Store, job_id: int) -> JobStatus | None:
    found = list(await jobs.job_manager.list_jobs_async(id=job_id))
    return _status(found[0], await store.progress(job_id)) if found else None


async def cancel_ingest(jobs: App, doc_id: UUID) -> bool:
    """Cancels the document's queued ingest jobs; False if one is already running."""
    for status in ("doing", "todo"):
        for job in await jobs.job_manager.list_jobs_async(task=INGEST, status=status):
            mine = job.task_kwargs["doc_id"] == str(doc_id)
            if mine and not await jobs.job_manager.cancel_job_by_id_async(cast(int, job.id)):
                return False
    return True


async def reindex_runs(jobs: App, store: Store, limit: int | None = 20) -> list[ReindexRun]:
    found = await jobs.job_manager.list_jobs_async(task=REINDEX)
    runs: list[ReindexRun] = []
    for job in sorted(found, key=lambda job: -cast(int, job.id))[:limit]:
        status = _status(job, await store.progress(cast(int, job.id)))
        report = status.result if isinstance(status.result, ReindexReport) else None
        runs.append(
            ReindexRun.model_validate(
                {**status.model_dump(exclude={"result"}), **job.task_kwargs, "report": report}
            )
        )
    return runs


async def rollback(jobs: App, store: Store, client: QdrantClient, alias: str) -> str:
    reports = [run.report for run in await reindex_runs(jobs, store, None) if run.report]
    return await asyncio.to_thread(reindexing.rollback, client, alias, reports)


def _status(job: Job, progress: Progress | None) -> JobStatus:
    status = job.status or "todo"
    # A retry starts with the last attempt's `failed` until its first stage; only the queue's own
    # status ends a job.
    running = progress.state if progress and progress.state in RUNNING else "queued"
    state = running if status == "doing" else STATES.get(status, "queued")
    error = progress.error if progress and state == "failed" else None
    result = progress.result if progress and state == "ready" else None
    return JobStatus.model_validate(
        {"id": job.id, "state": state, "error": error, "result": result}
    )


async def _tracked(
    context: JobContext, work: Callable[[Stage], Awaitable[BaseModel | None]]
) -> None:
    """Progress for `GET /v1/jobs/{id}`: each stage, then the result or the error."""
    store, job_id = _deps(context).store, cast(int, context.job.id)

    async def stage(state: JobState) -> None:
        await store.set_progress(job_id, Progress(state))

    try:
        result = await work(stage)
    except Exception as error:
        await store.set_progress(job_id, Progress("failed", str(error)))
        raise
    dump = result.model_dump(mode="json") if result else None
    await store.set_progress(job_id, Progress("ready", result=dump))


def _deps(context: JobContext) -> Deps:
    return cast(Deps, context.additional_context["deps"])  # pyright: ignore[reportUnknownMemberType]
