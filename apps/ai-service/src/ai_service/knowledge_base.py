import hashlib
import re
from typing import Any, Literal
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


class Chunk(BaseModel):
    chunk_index: int
    page: int | None
    heading: str | None
    text: str


class DocumentInfo(BaseModel):
    doc_id: UUID
    title: str
    filename: str
    domains: list[Domain]
    topics: list[str]
    chunk_count: int


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
        # Outside the branch, so collections from before a new index get it too (no-op if present).
        for field in ("doc_id", "owner_id", "domains"):
            self.client.create_payload_index(
                self.collection, field, models.PayloadSchemaType.KEYWORD
            )
        self.client.create_payload_index(
            self.collection, "chunk_index", models.PayloadSchemaType.INTEGER
        )
        # Prefix matching: `devops/` selects a whole domain (D48).
        topics = models.KeywordIndexParams(type=models.KeywordIndexType.KEYWORD, prefix=True)
        self.client.create_payload_index(self.collection, "topics", topics)
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
        topics: list[str] | None = None,
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
                "topics": topics or [],
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

    def documents(self, domains: list[Domain] | None = None) -> list[DocumentInfo]:
        """Every ingested document by title; its first chunk carries the labels."""
        # shortcut: one page of 10 000 documents; page with `next_page_offset` beyond that
        labels = _domains(domains)
        facet = self.client.facet(
            self.alias, "doc_id", facet_filter=models.Filter(must=labels), limit=10_000, exact=True
        )
        counts = {str(hit.value): hit.count for hit in facet.hits}
        first, _ = self.client.scroll(
            self.alias, models.Filter(must=[*labels, _equals("chunk_index", 0)]), limit=10_000
        )
        documents = [_info(p.payload or {}, counts) for p in first]
        return sorted(documents, key=lambda doc: doc.title.lower())

    def document(self, doc_id: UUID) -> DocumentInfo | None:
        first, _ = self.client.scroll(
            self.alias,
            models.Filter(must=[_equals("doc_id", str(doc_id)), _equals("chunk_index", 0)]),
            limit=1,
        )
        if not first:
            return None
        count = self.client.count(self.alias, _of(doc_id).filter, exact=True).count
        return _info(first[0].payload or {}, {str(doc_id): count})

    def chunks(self, doc_id: UUID, offset: int, limit: int) -> list[Chunk]:
        """Chunks `offset` … `offset + limit - 1` of a document, in reading order."""
        window = models.FieldCondition(
            key="chunk_index", range=models.Range(gte=offset, lt=offset + limit)
        )
        points, _ = self.client.scroll(
            self.alias,
            models.Filter(must=[_equals("doc_id", str(doc_id)), window]),
            limit=limit,
            with_payload=True,
        )
        chunks = [Chunk.model_validate(p.payload) for p in points]
        return sorted(chunks, key=lambda c: c.chunk_index)

    def update_labels(
        self, doc_id: UUID, domains: list[Domain] | None, topics: list[str] | None
    ) -> None:
        """Payload update on every chunk of the document, no re-embedding (D48)."""
        labels = {"domains": domains, "topics": topics}
        payload = {key: value for key, value in labels.items() if value is not None}
        if payload:
            self.client.set_payload(self.alias, payload, _of(doc_id), wait=True)

    def delete(self, doc_id: UUID) -> None:
        self.client.delete(self.alias, _of(doc_id), wait=True)


def _info(payload: dict[str, Any], chunk_counts: dict[str, int]) -> DocumentInfo:
    return DocumentInfo.model_validate(
        {**payload, "chunk_count": chunk_counts.get(payload["doc_id"], 0)}
    )


def _equals(key: str, value: str | int) -> models.FieldCondition:
    return models.FieldCondition(key=key, match=models.MatchValue(value=value))


def _domains(domains: list[Domain] | None) -> list[models.Condition]:
    return (
        [models.FieldCondition(key="domains", match=models.MatchAny(any=[str(d) for d in domains]))]
        if domains
        else []
    )


def _of(doc_id: UUID) -> models.FilterSelector:
    return models.FilterSelector(filter=models.Filter(must=[_equals("doc_id", str(doc_id))]))
