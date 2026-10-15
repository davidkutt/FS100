from fastembed import TextEmbedding
from fastembed.common.model_description import ModelSource, PoolingType
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

# Benchmark candidates missing from fastembed's built-in list (D9); their HF repos ship ONNX files.
for _name, _dim, _pooling, _extra in (
    ("intfloat/multilingual-e5-small", 384, PoolingType.MEAN, []),
    ("intfloat/multilingual-e5-base", 768, PoolingType.MEAN, []),
    ("BAAI/bge-m3", 1024, PoolingType.CLS, ["onnx/model.onnx_data"]),
):
    TextEmbedding.add_custom_model(
        _name, _pooling, True, ModelSource(hf=_name), _dim, additional_files=_extra
    )


class Embedder:
    """fastembed (ONNX, CPU); the one place that applies E5 `query: ` / `passage: ` prefixes."""

    def __init__(self, model_name: str, cache_dir: str | None = None) -> None:
        self.model_name = model_name
        self._model = TextEmbedding(model_name, cache_dir=cache_dir)
        self.dim: int = self._model.embedding_size
        e5 = "e5" in model_name.lower()
        self._query_prefix, self._passage_prefix = ("query: ", "passage: ") if e5 else ("", "")

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return self._embed([self._query_prefix + text for text in texts])

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return self._embed([self._passage_prefix + text for text in texts])

    def _embed(self, texts: list[str]) -> list[list[float]]:
        attributes = {
            "openinference.span.kind": "EMBEDDING",
            "embedding.model_name": self.model_name,
        }
        with tracer.start_as_current_span("embed", attributes=attributes):
            return [vector.tolist() for vector in self._model.embed(texts)]
