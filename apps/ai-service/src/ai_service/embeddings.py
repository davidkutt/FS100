import math
from typing import Literal

from fastembed import SparseTextEmbedding, TextEmbedding
from fastembed.common.model_description import ModelSource, PoolingType
from fastembed.rerank.cross_encoder import TextCrossEncoder  # pyright: ignore[reportMissingTypeStubs] (no __init__.py in fastembed.rerank)
from opentelemetry import trace
from qdrant_client import models

tracer = trace.get_tracer(__name__)
BATCH = 16  # ingest peak 2.5 GB vs. 3.8 GB at 256, same speed (M3a.1, D50)
# The collection's `sparse` vector (D56, ADR-0016); `none` = dense only.
Sparse = Literal["none", "bm25-english", "bm25-neutral"]

# Benchmark candidates missing from fastembed's built-in list (D9); their HF repos ship ONNX files.
for _name, _dim, _pooling, _extra in (
    ("intfloat/multilingual-e5-small", 384, PoolingType.MEAN, []),
    ("intfloat/multilingual-e5-base", 768, PoolingType.MEAN, []),
    ("BAAI/bge-m3", 1024, PoolingType.CLS, ["onnx/model.onnx_data"]),
):
    TextEmbedding.add_custom_model(
        _name, _pooling, True, ModelSource(hf=_name), _dim, additional_files=_extra
    )
# Rerank candidates' int8 ONNX files, named like fastembed's `BAAI/bge-reranker-v2-m3-int8` (D57).
for _repo, _file in (
    ("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1", "onnx/model_qint8_arm64.onnx"),
    ("jinaai/jina-reranker-v2-base-multilingual", "onnx/model_int8.onnx"),
):
    TextCrossEncoder.add_custom_model(f"{_repo}-int8", ModelSource(hf=_repo), _file)


class Embedder:
    """fastembed (ONNX, CPU); the one place that applies E5 `query: ` / `passage: ` prefixes."""

    def __init__(self, model_name: str, cache_dir: str | None = None) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir
        self._model = TextEmbedding(model_name, cache_dir=cache_dir)
        self.dim: int = self._model.embedding_size
        e5 = "e5" in model_name.lower()
        self._query_prefix, self._passage_prefix = ("query: ", "passage: ") if e5 else ("", "")
        self._bm25: dict[Sparse, SparseTextEmbedding] = {}  # loaded on first use: a few KB each

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return self._embed([self._query_prefix + text for text in texts])

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return self._embed([self._passage_prefix + text for text in texts])

    def embed_sparse(
        self, texts: list[str], kind: Sparse, query: bool = False
    ) -> list[models.SparseVector]:
        attributes = {"openinference.span.kind": "EMBEDDING", "embedding.model_name": kind}
        with tracer.start_as_current_span("embed_sparse", attributes=attributes):
            if kind not in self._bm25:
                neutral = kind == "bm25-neutral"  # no stemming, no stop words: DE and EN alike
                self._bm25[kind] = SparseTextEmbedding(
                    "Qdrant/bm25", cache_dir=self.cache_dir, disable_stemmer=neutral
                )
            model = self._bm25[kind]
            # Queries: term presence; passages: BM25 term weights. Qdrant applies the IDF.
            vectors = model.query_embed(texts) if query else model.embed(texts, batch_size=BATCH)
            return [
                models.SparseVector(indices=v.indices.tolist(), values=v.values.tolist())
                for v in vectors
            ]

    def _embed(self, texts: list[str]) -> list[list[float]]:
        attributes = {
            "openinference.span.kind": "EMBEDDING",
            "embedding.model_name": self.model_name,
        }
        with tracer.start_as_current_span("embed", attributes=attributes):
            return [vector.tolist() for vector in self._model.embed(texts, batch_size=BATCH)]


class Reranker:
    """Cross-encoder (fastembed, ONNX, CPU) over the fused candidates (D57, ADR-0017)."""

    def __init__(self, model_name: str, candidates: int, cache_dir: str | None = None) -> None:
        self.model_name = model_name
        self.candidates = candidates  # tuned per model to the latency budget
        self._model = TextCrossEncoder(model_name, cache_dir=cache_dir)

    def scores(self, query: str, texts: list[str]) -> list[float]:
        """The logits through a sigmoid: 0…1 like the cosine similarity they replace."""
        attributes = {"openinference.span.kind": "RERANKER", "reranker.model_name": self.model_name}
        with tracer.start_as_current_span("rerank", attributes=attributes):
            logits = self._model.rerank(query, texts, batch_size=BATCH)
            return [1 / (1 + math.exp(-logit)) for logit in logits]


def load_reranker(model_name: str, candidates: int, cache_dir: str | None) -> Reranker | None:
    return None if model_name == "none" else Reranker(model_name, candidates, cache_dir)
