import hashlib
import re
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from opentelemetry import trace
from pydantic import BaseModel
from qdrant_client import QdrantClient, models

from ai_service.embeddings import Embedder
from ai_service.ingest import chunk, parse

Domain = Literal["db", "dev", "cloud", "devops", "mlops", "ai", "security", "architecture", "sre"]
SPAN_KIND = "openinference.span.kind"
tracer = trace.get_tracer(__name__)


class Hit(BaseModel):
    chunk_id: str
    doc_id: UUID
    title: str
    filename: str
    page: int | None
    heading: str | None
    domains: list[Domain]
    score: float
    text: str


class IngestResult(BaseModel):
    doc_id: UUID
    chunk_count: int
    page_count: int | None
    embedding_model: str


class KnowledgeBase:
    """Documents in Qdrant: one collection per embedding model, always used via the alias (D10)."""

    def __init__(
        self,
        client: QdrantClient,
        embedder: Embedder,
        alias: str,
        chunk_size: int,
        chunk_overlap: int,
    ) -> None:
        self.client = client
        self.embedder = embedder
        self.alias = alias
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        slug = re.sub(r"[^a-z0-9]+", "-", embedder.model_name.lower()).strip("-")
        self.collection = f"kb__{slug}__{embedder.dim}"

    def ensure_collection(self) -> None:
        """Create the model's collection if missing and point the alias at it.

        A new EMBEDDING_MODEL thus starts empty (re-ingest); the old collection stays for rollback.
        """
        if not self.client.collection_exists(self.collection):
            dense = models.VectorParams(size=self.embedder.dim, distance=models.Distance.COSINE)
            self.client.create_collection(self.collection, vectors_config={"dense": dense})
            for field in ("doc_id", "owner_id", "domains"):
                self.client.create_payload_index(
                    self.collection, field, models.PayloadSchemaType.KEYWORD
                )
        alias = models.CreateAlias(collection_name=self.collection, alias_name=self.alias)
        self.client.update_collection_aliases(
            change_aliases_operations=[models.CreateAliasOperation(create_alias=alias)]
        )

    def ingest(
        self,
        *,
        doc_id: UUID,
        filename: str,
        data: bytes,
        owner_id: str,
        domains: list[Domain],
        title: str | None = None,
    ) -> IngestResult:
        attributes = {SPAN_KIND: "CHAIN", "doc_id": str(doc_id), "filename": filename}
        with tracer.start_as_current_span("ingest", attributes=attributes):
            with tracer.start_as_current_span("parse"):
                sections = parse(filename, data)
            with tracer.start_as_current_span("chunk"):
                chunks = chunk(sections, self.chunk_size, self.chunk_overlap)
            if not chunks:
                raise ValueError("No extractable text (scanned PDF?)")
            vectors = self.embedder.embed_passages([c.text for c in chunks])
            payload = {
                "doc_id": str(doc_id),
                "title": title or filename,
                "filename": filename,
                "domains": domains,
                "owner_id": owner_id,
                "visibility": "org",
                "allowed_groups": [],
                "sha256": hashlib.sha256(data).hexdigest(),
                "embedding_model": self.embedder.model_name,
            }
            points = [
                models.PointStruct(
                    id=str(uuid5(NAMESPACE_URL, f"{doc_id}:{index}")),
                    vector={"dense": vector},
                    payload={
                        **payload,
                        "chunk_index": index,
                        "text": c.text,
                        "page": c.page,
                        "heading": c.heading,
                    },
                )
                for index, (c, vector) in enumerate(zip(chunks, vectors, strict=True))
            ]
            with tracer.start_as_current_span("upsert"):
                self.delete(
                    doc_id
                )  # re-ingest replaces, also when the new version has fewer chunks
                self.client.upsert(self.alias, points, wait=True)
        return IngestResult(
            doc_id=doc_id,
            chunk_count=len(points),
            page_count=max((s.page or 0 for s in sections), default=0) or None,
            embedding_model=self.embedder.model_name,
        )

    def search(
        self,
        query: str,
        top_k: int,
        score_threshold: float | None = None,
        domains: list[Domain] | None = None,
        doc_ids: list[UUID] | None = None,
    ) -> list[Hit]:
        with tracer.start_as_current_span(
            "search", attributes={SPAN_KIND: "RETRIEVER", "input.value": query}
        ):
            vector = self.embedder.embed_queries([query])[0]
            must: list[models.Condition] = [
                models.FieldCondition(key=key, match=models.MatchAny(any=[str(v) for v in values]))
                for key, values in (("domains", domains), ("doc_id", doc_ids))
                if values
            ]
            response = self.client.query_points(
                self.alias,
                query=vector,
                using="dense",
                limit=top_k,
                score_threshold=score_threshold,
                query_filter=models.Filter(must=must),
                with_payload=True,
            )
        return [
            Hit.model_validate({**(p.payload or {}), "chunk_id": str(p.id), "score": p.score})
            for p in response.points
        ]

    def delete(self, doc_id: UUID) -> None:
        match = models.FieldCondition(key="doc_id", match=models.MatchValue(value=str(doc_id)))
        self.client.delete(
            self.alias, models.FilterSelector(filter=models.Filter(must=[match])), wait=True
        )
