from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field
from pypdf.errors import PyPdfError

from ai_service.catalog import Taxonomy
from ai_service.ingest import UnsupportedDocumentError
from ai_service.knowledge_base import Domain, Hit, IngestResult, KnowledgeBase

router = APIRouter(prefix="/v1", tags=["documents"])


def get_kb(request: Request) -> KnowledgeBase:
    return request.app.state.kb


def get_taxonomy(request: Request) -> Taxonomy:
    return request.app.state.taxonomy


KB = Annotated[KnowledgeBase, Depends(get_kb)]
Tax = Annotated[Taxonomy, Depends(get_taxonomy)]


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


class SearchResponse(BaseModel):
    embedding_model: str
    hits: list[Hit]


class Labels(BaseModel):
    domains: list[Domain] | None = Field(None, min_length=1)
    topics: list[str] | None = None  # `domain/topic` ids from the taxonomy


@router.post("/ingest")
def ingest(
    kb: KB,
    taxonomy: Tax,
    file: UploadFile,
    doc_id: Annotated[UUID, Form()],
    owner_id: Annotated[str, Form()],
    domains: Annotated[list[Domain], Form()],
    topics: Annotated[list[str] | None, Form()] = None,
    title: Annotated[str | None, Form()] = None,
) -> IngestResult:
    """Parse, chunk, embed and upsert one document; re-ingesting a `doc_id` replaces its chunks."""
    _check_topics(taxonomy, topics)
    try:
        return kb.ingest(
            doc_id=doc_id,
            filename=file.filename or "",
            data=file.file.read(),
            owner_id=owner_id,
            domains=domains,
            topics=topics,
            title=title,
        )
    except UnsupportedDocumentError as error:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(error)) from error
    except (ValueError, PyPdfError) as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error


@router.post("/search")
def search(kb: KB, body: SearchRequest) -> SearchResponse:
    """Dense retrieval for the inspector and evals; no threshold unless one is given."""
    hits = kb.search(body.query, body.top_k, body.score_threshold, body.domains, body.doc_ids)
    return SearchResponse(embedding_model=kb.embedder.model_name, hits=hits)


@router.patch("/documents/{doc_id}/labels", status_code=status.HTTP_204_NO_CONTENT)
def update_labels(kb: KB, taxonomy: Tax, doc_id: UUID, body: Labels) -> None:
    """Change `domains` / `topics` of all chunks of a document without re-embedding (D48)."""
    _check_topics(taxonomy, body.topics)
    kb.update_labels(doc_id, body.domains, body.topics)


@router.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(kb: KB, doc_id: UUID) -> None:
    kb.delete(doc_id)
