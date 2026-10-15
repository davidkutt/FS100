import pytest

from ai_service import embeddings
from ai_service.embeddings import Embedder
from support import FakeTextEmbedding


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("intfloat/multilingual-e5-small", ["query: q", "passage: p"]),
        ("intfloat/multilingual-e5-large", ["query: q", "passage: p"]),
        ("BAAI/bge-m3", ["q", "p"]),
    ],
)
def test_prefixes_depend_on_the_model(
    monkeypatch: pytest.MonkeyPatch, model: str, expected: list[str]
) -> None:
    fake = FakeTextEmbedding()

    def text_embedding(*_args: object, **_kwargs: object) -> FakeTextEmbedding:
        return fake

    monkeypatch.setattr(embeddings, "TextEmbedding", text_embedding)
    embedder = Embedder(model)

    embedder.embed_queries(["q"])
    embedder.embed_passages(["p"])

    assert fake.texts == expected
    assert embedder.dim == FakeTextEmbedding.embedding_size
