import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, status
from procrastinate import App
from pydantic import BaseModel, Field

from ai_service.catalog import Taxonomy
from ai_service.ingest import supported
from ai_service.jobs import INGEST, cancel_ingest, defer
from ai_service.knowledge_base import Domain, ExplainedHit, KnowledgeBase
from ai_service.query import QueryTransformer, Strategy
from ai_service.storage import Store

router = APIRouter(prefix="/v1", tags=["documents"])
MAX_BYTES = 20 * 1024 * 1024  # D52


def get_kb(request: Request) -> KnowledgeBase:
    return request.app.state.kb


def get_taxonomy(request: Request) -> Taxonomy:
    return request.app.state.taxonomy


def get_jobs(request: Request) -> App:
    return request.app.state.jobs


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_query(request: Request) -> QueryTransformer:
    return request.app.state.query


KB = Annotated[KnowledgeBase, Depends(get_kb)]
Tax = Annotated[Taxonomy, Depends(get_taxonomy)]
Jobs = Annotated[App, Depends(get_jobs)]
Originals = Annotated[Store, Depends(get_store)]


def _check_topics(taxonomy: Taxonomy, topics: list[str] | None) -> None:
    if unknown := taxonomy.unknown_topics(topics or []):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown topics: {', '.join(unknown)}"
        )


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(5, ge=1, le=50)
    score_threshold: float | None = None
    domains: list[Domain] | None = None
    doc_ids: list[UUID] | None = None
    explain: bool = False  # the inspector's fused, dense and sparse ranks (D56, D57)
    strategy: Strategy = "plain"  # D58


class SearchResponse(BaseModel):
    embedding_model: str
    reranker_model: str | None  # None: `score` is the cosine similarity
    hits: list[ExplainedHit]


class Submitted(BaseModel):
    job_id: int
    version: int


class Labels(BaseModel):
    domains: list[Domain] | None = Field(None, min_length=1)
    topics: list[str] | None = None  # `domain/topic` ids from the taxonomy


@router.post("/documents", status_code=status.HTTP_202_ACCEPTED)
async def submit(
    jobs: Jobs,
    store: Originals,
    taxonomy: Tax,
    file: UploadFile,
    doc_id: Annotated[UUID, Form()],
    owner_id: Annotated[str, Form()],
    domains: Annotated[list[Domain], Form()],
    topics: Annotated[list[str] | None, Form()] = None,
    title: Annotated[str | None, Form()] = None,
) -> Submitted:
    """Store the original and queue its ingest (D52); poll `GET /v1/jobs/{job_id}`. The same
    bytes again keep their version; parse errors end the job `failed`."""
    _check_topics(taxonomy, topics)
    filename = file.filename or ""
    if not supported(filename):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Unsupported file type; expected PDF, MD or TXT"
        )
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Originals are kept up to 20 MB")
    version = await store.put_original(
        doc_id, file.content_type or "application/octet-stream", data
    )
    job_id = await defer(
        jobs,
        INGEST,
        doc_id=str(doc_id),
        version=version,
        filename=filename,
        owner_id=owner_id,
        domains=domains,
        topics=topics or [],
        title=title,
    )
    return Submitted(job_id=job_id, version=version)


@router.post("/search")
async def search(
    kb: KB, transformer: Annotated[QueryTransformer, Depends(get_query)], body: SearchRequest
) -> SearchResponse:
    """Retrieval as the chat runs it, for the inspector; no threshold unless one is given."""
    query = await transformer.expand(body.query, body.strategy)
    hits = await asyncio.to_thread(
        kb.search,
        query.text,
        body.top_k,
        body.score_threshold,
        body.domains,
        body.doc_ids,
        body.explain,
        query.passages,
    )
    return SearchResponse(
        embedding_model=kb.embedder.model_name,
        reranker_model=kb.reranker.model_name if kb.reranker else None,
        hits=[ExplainedHit.model_validate(hit.model_dump()) for hit in hits],
    )


@router.patch("/documents/{doc_id}/labels", status_code=status.HTTP_204_NO_CONTENT)
def update_labels(kb: KB, taxonomy: Tax, doc_id: UUID, body: Labels) -> None:
    """Change `domains` / `topics` of all chunks of a document without re-embedding (D48)."""
    _check_topics(taxonomy, body.topics)
    kb.update_labels(doc_id, body.domains, body.topics)


@router.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(kb: KB, jobs: Jobs, store: Originals, doc_id: UUID) -> None:
    """Cancels a queued ingest; removes the vectors from every collection and the originals."""
    if not await cancel_ingest(jobs, doc_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The document is being ingested; try again when it is done"
        )
    await asyncio.to_thread(kb.delete, doc_id)
    await store.delete_originals(doc_id)
