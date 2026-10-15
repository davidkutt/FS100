from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field
from pypdf.errors import PyPdfError

from ai_service.ingest import UnsupportedDocumentError
from ai_service.knowledge_base import Domain, Hit, IngestResult, KnowledgeBase

router = APIRouter(prefix="/v1", tags=["documents"])


def get_kb(request: Request) -> KnowledgeBase:
    return request.app.state.kb


KB = Annotated[KnowledgeBase, Depends(get_kb)]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(5, ge=1, le=50)
    score_threshold: float | None = None
    domains: list[Domain] | None = None
    doc_ids: list[UUID] | None = None


class SearchResponse(BaseModel):
    embedding_model: str
    hits: list[Hit]


@router.post("/ingest")
def ingest(
    kb: KB,
    file: UploadFile,
    doc_id: Annotated[UUID, Form()],
    owner_id: Annotated[str, Form()],
    domains: Annotated[list[Domain], Form()],
    title: Annotated[str | None, Form()] = None,
) -> IngestResult:
    """Parse, chunk, embed and upsert one document; re-ingesting a `doc_id` replaces its chunks."""
    try:
        return kb.ingest(
            doc_id=doc_id,
            filename=file.filename or "",
            data=file.file.read(),
            owner_id=owner_id,
            domains=domains,
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


@router.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(kb: KB, doc_id: UUID) -> None:
    kb.delete(doc_id)
