import copy
import hashlib
import logging
import re
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

import numpy as np
from opentelemetry import trace
from pydantic import BaseModel
from qdrant_client import QdrantClient, models

from ai_service.embeddings import Embedder, Reranker, Sparse
from ai_service.ingest import Section, parents, parse

Domain = Literal["db", "dev", "cloud", "devops", "mlops", "ai", "security", "architecture", "sre"]
Priority = Literal["canonical", "normal", "low"]
Lifecycle = Literal["active", "retired"]
# A document's labels: NestJS owns them, chunks carry them in the payload (D48, D61).
LABELS = ("domains", "topics", "lifecycle", "priority", "priority_topics")
SPAN_KIND = "openinference.span.kind"
COLLECTIONS = "kb__"  # every generation: `kb__{model}__{dim}` (P1) and `kb__v2__…` (D54)
PREFETCH = 50  # candidates per side before fusion (D56)
FUSION = "rrf:2:0.5"  # RRF with Qdrant's k = 2, the sparse side at half weight (ADR-0016)
# Positions a priority moves a hit after reranking (D61), and how many of the question's nearest
# sub-topics may match its scope; tuned on `dev` (M3a.7).
BOOST: dict[Priority, int] = {"canonical": 3, "normal": 0, "low": -3}
QUESTION_TOPICS = 2
ACTIVE = models.FieldCondition(key="lifecycle", match=models.MatchValue(value="active"))
tracer = trace.get_tracer(__name__)
logger = logging.getLogger(__name__)


class Hit(BaseModel):
    """The best-matching chunk of a parent section; `text` is the section's (D59)."""

    chunk_id: str
    parent_id: str | None = None  # None: indexed before M3a.5, the chunk is its own parent
    doc_id: UUID
    title: str
    filename: str
    page: int | None
    heading: str | None
    domains: list[Domain]
    score: float
    text: str
    priority: Priority = "normal"
    priority_topics: list[str] = []


class ExplainedHit(Hit):
    """`explain` mode of `/v1/search`: the matching chunk inside the section, and the section's
    rank among the fused candidates and the chunk's in the dense and the sparse top 50 (None: not
    among them); its position is the reranked one, moved by `boost` positions (D61)."""

    chunk_text: str = ""
    fused_rank: int | None = None
    dense_rank: int | None = None
    sparse_rank: int | None = None
    boost: int = 0


class DocumentSection(BaseModel):
    """A parent section (D59) in reading order."""

    index: int
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
    context_cost_usd: float = 0  # contextual retrieval (D60)


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
        sparse: Sparse = "none",
        parent_size: int = 0,
        fusion: str = FUSION,
        reranker: Reranker | None = None,
        topics: dict[str, str] | None = None,
        threshold: float | None = None,
    ) -> None:
        self.client = client
        self.embedder = embedder
        self.alias = alias
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.parent_size = parent_size  # D59; 0: each chunk is its own parent
        self.sparse: Sparse = sparse  # for new collections; each one keeps its own (`sparse_of`)
        self.fusion = fusion  # `rrf:<k>:<sparse weight>` or `dbsf`
        self.reranker = reranker
        self.topics = topics or {}  # `domain/topic` → description: chunk-topic fallback, boosts
        self.threshold = threshold  # RETRIEVAL_SCORE_THRESHOLD: only hits above it get a boost
        self._topic_vectors: dict[str, list[float]] | None = None
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
        elif (built := self.sparse_of()) != self.sparse:
            logger.warning(
                "%s has sparse=%s, not SPARSE_MODEL=%s: `pnpm kb:reindex` builds it",
                self.alias,
                built,
                self.sparse,
            )

    def create_collection(self) -> str:
        """An empty collection v2 (D54), named by model, dimension and build time; its metadata
        records the sparse side (D56)."""
        name = f"{COLLECTIONS}v2{self.model_key}__{datetime.now(UTC):%Y%m%dt%H%M%S%f}"
        dense = models.VectorParams(size=self.embedder.dim, distance=models.Distance.COSINE)
        # BM25 vectors hold term weights; Qdrant multiplies in the IDF of the collection.
        bm25 = models.SparseVectorParams(modifier=models.Modifier.IDF)
        self.client.create_collection(
            name,
            vectors_config={"dense": dense},
            sparse_vectors_config={"sparse": bm25} if self.sparse != "none" else None,
            metadata={"sparse": self.sparse},
        )
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
        for field in ("topics", "chunk_topics"):
            self.client.create_payload_index(name, field, topics)
        return name

    def live_collection(self) -> str:
        return live_collection(self.client, self.alias)

    def sparse_of(self) -> Sparse:
        """The sparse side this collection was built with; before M3a.2 none."""
        metadata = self.client.get_collection(self.alias).config.metadata or {}
        return metadata.get("sparse", "none")

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
            with tracer.start_as_current_span("parse"):
                sections = parse(filename, data)
            return self.index(
                self.split(sections),
                doc_id=doc_id,
                version=version,
                filename=filename,
                sha256=hashlib.sha256(data).hexdigest(),
                owner_id=owner_id,
                domains=domains,
                topics=topics or [],
                title=title,
            )

    def split(self, sections: list[Section]) -> list[tuple[Section, list[Section]]]:
        """Parents with their chunks; a document without usable text raises ValueError."""
        with tracer.start_as_current_span("chunk"):
            split = parents(sections, self.chunk_size, self.chunk_overlap, self.parent_size)
        if not split:
            raise ValueError("No extractable text (scanned PDF?)")
        return split

    def index(
        self,
        split: list[tuple[Section, list[Section]]],
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
        """Embed and upsert one version; running it again for the same version changes nothing. A
        chunk's context is embedded with it (D60); a chunk without sub-topics gets the most similar
        one of the document's domains."""
        chunks = [(n, parent, c) for n, (parent, children) in enumerate(split) for c in children]
        texts = [f"{c.context}\n\n{c.text}" if c.context else c.text for _, _, c in chunks]
        dense = self.embedder.embed_passages(texts)
        nearest = self._nearest_topics(
            dense, [t for t in self.topics if t.split("/")[0] in domains]
        )
        vectors: list[dict[str, models.Vector]] = [{"dense": vector} for vector in dense]
        if (sparse := self.sparse_of()) != "none":
            for named, vector in zip(
                vectors, self.embedder.embed_sparse(texts, sparse), strict=True
            ):
                named["sparse"] = vector
        # A new version (a changed note, M3c.1) keeps the lifecycle and priority set since (D61).
        previous = first_chunks(self.client, self.alias, [_equals("doc_id", str(doc_id))])
        kept = {
            key: value
            for chunk in previous.values()
            for key, value in chunk.items()
            if key in ("lifecycle", "priority", "priority_topics")
        }
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
            **kept,
        }
        points = [
            models.PointStruct(
                id=str(uuid5(NAMESPACE_URL, f"{doc_id}:{version}:{index}")),
                vector=vector,
                payload={
                    **payload,
                    "chunk_index": index,
                    "text": c.text,
                    "page": c.page,
                    "heading": c.heading,
                    "parent_id": f"{doc_id}:{version}:{n}",
                    "parent_text": parent.text,
                    "context": c.context,
                    "chunk_topics": list(c.topics) or fallback,
                },
            )
            for index, ((n, parent, c), vector, fallback) in enumerate(
                zip(chunks, vectors, nearest, strict=True)
            )
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
            page_count=max((c.page or 0 for _, _, c in chunks), default=0) or None,
            embedding_model=self.embedder.model_name,
        )

    def _nearest_topics(
        self, vectors: list[list[float]], ids: list[str], n: int = 1
    ) -> list[list[str]]:
        """Per vector the `n` sub-topics of `ids` with the most similar descriptions (D60, D61)."""
        if not ids:
            return [[] for _ in vectors]
        if self._topic_vectors is None:
            described = [f"{topic}: {text}" for topic, text in self.topics.items()]
            embedded = self.embedder.embed_passages(described)
            self._topic_vectors = dict(zip(self.topics, embedded, strict=True))
        topics = unit(np.array([self._topic_vectors[topic] for topic in ids]))
        nearest = np.argsort(-(unit(np.array(vectors)) @ topics.T), axis=1)[:, :n]
        return [[ids[i] for i in row] for row in nearest]

    def question_topics(self, query: list[float]) -> list[str]:
        """The sub-topics nearest to a question's vector; a priority's scope must hold one (D61)."""
        return self._nearest_topics([query], list(self.topics), QUESTION_TOPICS)[0]

    def _boosts(self, hits: list[Hit], query: list[float]) -> dict[str, int]:
        """Positions a priority moves each hit (D61): only when its scope holds one of the
        question's nearest sub-topics and the hit clears the threshold."""
        scoped = [
            hit
            for hit in hits
            if BOOST[hit.priority] and (self.threshold is None or hit.score >= self.threshold)
        ]
        if not scoped:
            return {}
        asked = set(self.question_topics(query))
        return {
            hit.chunk_id: BOOST[hit.priority] for hit in scoped if asked & {*hit.priority_topics}
        }

    def search(
        self,
        query: str,
        top_k: int,
        score_threshold: float | None = None,
        domains: list[Domain] | None = None,
        doc_ids: list[UUID] | None = None,
        explain: bool = False,
        passages: list[str] | None = None,
    ) -> list[Hit]:
        """Hybrid if the collection has a sparse side: dense and sparse top 50 under the same
        filter, fused (D56); the best chunk of each parent stands for it (D59), and the reranker
        orders these candidates (D57). `score` is the reranker's, without one the cosine
        similarity: the threshold is calibrated on it (ADR-0004, ADR-0017); below it for the best
        hit, the search abstains with no hits. `passages` (HyDE, D58) add dense candidates to the
        fusion; the reranker and the score still compare with `query`. Priorities move hits after
        reranking (D61), so a canonical one can rise into the top k; retired documents never
        match."""
        with tracer.start_as_current_span(
            "search", attributes={SPAN_KIND: "RETRIEVER", "input.value": query}
        ):
            dense = self.embedder.embed_queries([query])[0]
            must: list[models.Condition] = [
                models.FieldCondition(key=key, match=models.MatchAny(any=[str(v) for v in values]))
                for key, values in (("domains", domains), ("doc_id", doc_ids))
                if values
            ]
            where = models.Filter(must=[ACTIVE, *must])
            sides = [models.Prefetch(query=dense, using="dense", filter=where, limit=PREFETCH)]
            if (kind := self.sparse_of()) != "none":
                sparse = self.embedder.embed_sparse([query], kind, query=True)[0]
                sides.append(
                    models.Prefetch(query=sparse, using="sparse", filter=where, limit=PREFETCH)
                )
            own = list(sides)  # the question's, which `explain` ranks
            if passages:  # HyDE: a passage is compared with passages, on the dense side
                sides += [
                    models.Prefetch(query=vector, using="dense", filter=where, limit=PREFETCH)
                    for vector in self.embedder.embed_passages(passages)
                ]
            fused_points = self.client.query_points(
                self.alias,
                prefetch=sides,
                query=_fusion(self.fusion, [side.using == "sparse" for side in sides]),
                limit=PREFETCH,  # enough for top_k parents of several chunks each
                with_payload=True,
            ).points
            best: dict[str, models.ScoredPoint] = {}
            for p in fused_points:
                best.setdefault((p.payload or {}).get("parent_id") or str(p.id), p)
            points = list(best.values())
            # Room for a canonical hit to rise into the top k.
            limit = top_k + BOOST["canonical"]
            points = points[: max(limit, self.reranker.candidates) if self.reranker else limit]
            fused = {str(p.id): rank for rank, p in enumerate(points, 1)}
            chunk_texts = {str(p.id): (p.payload or {})["text"] for p in points}
            if self.reranker and points:
                texts = list(chunk_texts.values())
                scored = zip(self.reranker.scores(query, texts), points, strict=True)
                ranked = sorted(scored, key=lambda pair: -pair[0])
                points = [p.model_copy(update={"score": score}) for score, p in ranked]
            elif points:
                ids = models.HasIdCondition(has_id=[p.id for p in points])
                cosine = self.client.query_points(
                    self.alias,
                    query=dense,
                    using="dense",
                    query_filter=models.Filter(must=[ids]),
                    limit=len(points),
                ).points
                scores = {p.id: p.score for p in cosine}
                points = [p.model_copy(update={"score": scores[p.id]}) for p in points]
            hits: list[Hit] = [_hit(p) for p in points]
            boosts = self._boosts(hits, dense)
            moved = sorted(enumerate(hits), key=lambda pair: _moved(*pair, boosts))
            hits = [hit for _, hit in moved][:top_k]
            if (
                score_threshold is not None
                and max((h.score for h in hits), default=0) < score_threshold
            ):
                return []
            if explain:
                requests = [
                    models.QueryRequest(query=p.query, using=p.using, filter=where, limit=PREFETCH)
                    for p in own
                ]
                ranks = [
                    {str(p.id): rank for rank, p in enumerate(side.points, 1)}
                    for side in self.client.query_batch_points(self.alias, requests)
                ]
                hits = [
                    ExplainedHit(
                        **hit.model_dump(),
                        chunk_text=chunk_texts[hit.chunk_id],
                        fused_rank=fused[hit.chunk_id],
                        dense_rank=ranks[0].get(hit.chunk_id),
                        sparse_rank=ranks[1].get(hit.chunk_id) if len(ranks) > 1 else None,
                        boost=boosts.get(hit.chunk_id, 0),
                    )
                    for hit in hits
                ]
        return hits

    def documents(self, domains: list[Domain] | None = None) -> list[DocumentInfo]:
        """Every active document by title."""
        labels = [*_domains(domains), ACTIVE]
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
            models.Filter(must=[_equals("doc_id", str(doc_id)), _equals("chunk_index", 0), ACTIVE]),
            limit=1,
        )
        if not first:
            return None
        count = self.client.count(self.alias, _of(doc_id).filter, exact=True).count
        return _info(first[0].payload or {}, {str(doc_id): count})

    def sections(self, doc_id: UUID) -> list[DocumentSection]:
        """A document's parent sections (D59) in reading order."""
        # shortcut: one page of 10 000 chunks; page with `next_page_offset` beyond that
        points, _ = self.client.scroll(self.alias, _of(doc_id).filter, limit=10_000)
        first: dict[str, Hit] = {}
        for p in sorted(points, key=lambda p: (p.payload or {})["chunk_index"]):
            hit = _hit(p)
            first.setdefault(hit.parent_id or hit.chunk_id, hit)
        return [
            DocumentSection(index=index, page=hit.page, heading=hit.heading, text=hit.text)
            for index, hit in enumerate(first.values())
        ]

    def update_labels(self, doc_id: UUID, labels: dict[str, Any]) -> None:
        """Payload update of `LABELS` on every chunk of the document, no re-embedding (D48, D61);
        in every collection, so a rollback keeps the labels."""
        # shortcut: new domains keep the old domains' `chunk_topics` until `pnpm kb:reindex`;
        # recompute them here once retrieval filters or boosts on them.
        for name in self.collections() if labels else []:
            self.client.set_payload(name, labels, _of(doc_id), wait=True)

    def delete(self, doc_id: UUID) -> None:
        """From every collection, so a rollback cannot bring the document back."""
        for name in self.collections():
            self.client.delete(name, _of(doc_id), wait=True)

    def reconcile(self, labels: dict[UUID, dict[str, Any]]) -> None:
        """Documents missing from `labels` leave this collection; the others take its labels."""
        for doc_id in first_chunks(self.client, self.alias):
            if doc_id in labels:
                payload = {key: labels[doc_id][key] for key in LABELS}
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


def _hit(point: models.ScoredPoint | models.Record) -> Hit:
    payload = point.payload or {}
    return Hit.model_validate(
        {
            **payload,
            "chunk_id": str(point.id),
            "score": getattr(point, "score", 0.0),
            "text": payload.get("parent_text", payload["text"]),
        }
    )


def _info(payload: dict[str, Any], chunk_counts: dict[str, int]) -> DocumentInfo:
    return DocumentInfo.model_validate(
        {**payload, "chunk_count": chunk_counts.get(payload["doc_id"], 0)}
    )


def _moved(position: int, hit: Hit, boosts: dict[str, int]) -> tuple[int, int]:
    """Sort key: `boost` positions up (down if negative); a raised hit goes before the one it
    meets, a lowered one after."""
    boost = boosts.get(hit.chunk_id, 0)
    return position - boost, -boost


def _fusion(spec: str, sparse: list[bool]) -> models.FusionQuery | models.RrfQuery:
    """`sparse` flags each prefetch; RRF gives sparse sides their weight, dense ones 1."""
    if spec == "dbsf":
        return models.FusionQuery(fusion=models.Fusion.DBSF)
    _, k, weight = spec.split(":")
    weights = [float(weight) if side else 1.0 for side in sparse]
    return models.RrfQuery(rrf=models.Rrf(k=int(k), weights=weights))


def _equals(key: str, value: str | int) -> models.FieldCondition:
    return models.FieldCondition(key=key, match=models.MatchValue(value=value))


def _domains(domains: list[Domain] | None) -> list[models.Condition]:
    return (
        [models.FieldCondition(key="domains", match=models.MatchAny(any=[str(d) for d in domains]))]
        if domains
        else []
    )


def unit(vectors: np.ndarray) -> np.ndarray:
    return vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)


def _of(doc_id: UUID) -> models.FilterSelector:
    return models.FilterSelector(filter=models.Filter(must=[_equals("doc_id", str(doc_id))]))
