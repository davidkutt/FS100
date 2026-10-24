import copy
import hashlib
import logging
import re
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from opentelemetry import trace
from pydantic import BaseModel
from qdrant_client import QdrantClient, models

from ai_service.embeddings import Embedder
from ai_service.ingest import Section, chunk, parse

Domain = Literal["db", "dev", "cloud", "devops", "mlops", "ai", "security", "architecture", "sre"]
SPAN_KIND = "openinference.span.kind"
COLLECTIONS = "kb__"  # every generation: `kb__{model}__{dim}` (P1) and `kb__v2__…` (D54)
tracer = trace.get_tracer(__name__)
logger = logging.getLogger(__name__)


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
    """Documents in Qdrant, always used via the alias (D10); a re-index builds a new collection and
    moves the alias (D55)."""

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
        self.model_key = f"__{slug}__{embedder.dim}"  # part of every collection name of this model

    def ensure_collection(self) -> None:
        """Point the alias at a new, empty collection if it has none; afterwards only a re-index
        moves it (D55)."""
        if not self.client.collection_exists(self.alias):
            self.swap(self.create_collection())
        elif self.model_key not in (live := self.live_collection()):
            logger.warning(
                "%s is %s, not built with EMBEDDING_MODEL=%s: searches fail until "
                "`pnpm kb:reindex --force --reason 'new model'`",
                self.alias,
                live,
                self.embedder.model_name,
            )

    def create_collection(self) -> str:
        """An empty collection v2 (D54), named by model, dimension and build time."""
        name = f"{COLLECTIONS}v2{self.model_key}__{datetime.now(UTC):%Y%m%dt%H%M%S%f}"
        dense = models.VectorParams(size=self.embedder.dim, distance=models.Distance.COSINE)
        self.client.create_collection(name, vectors_config={"dense": dense})
        for field in (
            "doc_id",
            "owner_id",
            "domains",
            "lifecycle",
            "visibility",
            "allowed_groups",
            "kind",
            "path",
        ):
            self.client.create_payload_index(name, field, models.PayloadSchemaType.KEYWORD)
        for field in ("chunk_index", "version"):
            self.client.create_payload_index(name, field, models.PayloadSchemaType.INTEGER)
        # Prefix matching: `devops/` selects a whole domain (D48).
        topics = models.KeywordIndexParams(type=models.KeywordIndexType.KEYWORD, prefix=True)
        self.client.create_payload_index(name, "topics", topics)
        return name

    def live_collection(self) -> str:
        return live_collection(self.client, self.alias)

    def collections(self) -> list[str]:
        """The live collection and every one kept for a rollback."""
        names = (c.name for c in self.client.get_collections().collections)
        return [name for name in names if name.startswith(COLLECTIONS)]

    def swap(self, collection: str) -> None:
        swap(self.client, self.alias, collection)

    def at(self, collection: str) -> "KnowledgeBase":
        """The same knowledge base reading and writing `collection` instead of the alias."""
        view = copy.copy(self)
        view.alias = collection
        return view

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
        version: int = 1,
    ) -> IngestResult:
        attributes = {SPAN_KIND: "CHAIN", "doc_id": str(doc_id), "filename": filename}
        with tracer.start_as_current_span("ingest", attributes=attributes):
            return self.index(
                self.prepare(filename, data),
                doc_id=doc_id,
                version=version,
                filename=filename,
                sha256=hashlib.sha256(data).hexdigest(),
                owner_id=owner_id,
                domains=domains,
                topics=topics or [],
                title=title,
            )

    def prepare(self, filename: str, data: bytes) -> list[Section]:
        """Parse and chunk; a document without usable text raises ValueError or a pypdf error."""
        with tracer.start_as_current_span("parse"):
            sections = parse(filename, data)
        with tracer.start_as_current_span("chunk"):
            chunks = chunk(sections, self.chunk_size, self.chunk_overlap)
        if not chunks:
            raise ValueError("No extractable text (scanned PDF?)")
        return chunks

    def index(
        self,
        chunks: list[Section],
        *,
        doc_id: UUID,
        version: int,
        filename: str,
        sha256: str,
        owner_id: str,
        domains: list[Domain],
        topics: list[str],
        title: str | None,
    ) -> IngestResult:
        """Embed and upsert one version; running it again for the same version changes nothing."""
        vectors = self.embedder.embed_passages([c.text for c in chunks])
        payload = {
            "doc_id": str(doc_id),
            "version": version,
            "title": title or filename,
            "filename": filename,
            "domains": domains,
            "topics": topics,
            "owner_id": owner_id,
            "kind": "doc",
            "lifecycle": "active",
            "priority": "normal",
            "priority_topics": [],
            "visibility": "org",
            "allowed_groups": [],
            "sha256": sha256,
            "embedding_model": self.embedder.model_name,
        }
        points = [
            models.PointStruct(
                id=str(uuid5(NAMESPACE_URL, f"{doc_id}:{version}:{index}")),
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
            self.client.upsert(self.alias, points, wait=True)
            # Then what this version no longer has: older versions, chunks past its end.
            current = models.Filter(
                must=[
                    _equals("version", version),
                    models.FieldCondition(key="chunk_index", range=models.Range(lt=len(points))),
                ]
            )
            stale = models.Filter(must=[_equals("doc_id", str(doc_id))], must_not=[current])
            self.client.delete(self.alias, models.FilterSelector(filter=stale), wait=True)
        return IngestResult(
            doc_id=doc_id,
            chunk_count=len(points),
            page_count=max((c.page or 0 for c in chunks), default=0) or None,
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
        """Every ingested document by title."""
        labels = _domains(domains)
        facet = self.client.facet(
            self.alias, "doc_id", facet_filter=models.Filter(must=labels), limit=10_000, exact=True
        )
        counts = {str(hit.value): hit.count for hit in facet.hits}
        first = first_chunks(self.client, self.alias, labels).values()
        documents = [_info(payload, counts) for payload in first]
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
        """Payload update on every chunk of the document, no re-embedding (D48); in every
        collection, so a rollback keeps the labels."""
        labels = {"domains": domains, "topics": topics}
        payload = {key: value for key, value in labels.items() if value is not None}
        for name in self.collections() if payload else []:
            self.client.set_payload(name, payload, _of(doc_id), wait=True)

    def delete(self, doc_id: UUID) -> None:
        """From every collection, so a rollback cannot bring the document back."""
        for name in self.collections():
            self.client.delete(name, _of(doc_id), wait=True)

    def reconcile(self, labels: dict[UUID, dict[str, Any]]) -> None:
        """Documents missing from `labels` leave this collection; the others take its labels."""
        for doc_id in first_chunks(self.client, self.alias):
            if doc_id in labels:
                payload = {key: labels[doc_id][key] for key in ("domains", "topics")}
                self.client.set_payload(self.alias, payload, _of(doc_id), wait=True)
            else:
                self.client.delete(self.alias, _of(doc_id), wait=True)


def live_collection(client: QdrantClient, alias: str) -> str:
    aliases = client.get_aliases().aliases
    return next(a.collection_name for a in aliases if a.alias_name == alias)


def swap(client: QdrantClient, alias: str, collection: str) -> None:
    """Re-point the alias; Qdrant applies both operations together."""
    create = models.CreateAlias(collection_name=collection, alias_name=alias)
    operations: list[models.AliasOperations] = [models.CreateAliasOperation(create_alias=create)]
    if client.collection_exists(alias):
        delete = models.DeleteAlias(alias_name=alias)
        operations.insert(0, models.DeleteAliasOperation(delete_alias=delete))
    client.update_collection_aliases(change_aliases_operations=operations)


def first_chunks(
    client: QdrantClient, collection: str, must: list[models.Condition] | None = None
) -> dict[UUID, dict[str, Any]]:
    """The payload of each document's first chunk, which carries the document's labels."""
    # shortcut: one page of 10 000 documents; page with `next_page_offset` beyond that
    points, _ = client.scroll(
        collection, models.Filter(must=[*(must or []), _equals("chunk_index", 0)]), limit=10_000
    )
    return {UUID(p.payload["doc_id"]): p.payload for p in points if p.payload}


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
