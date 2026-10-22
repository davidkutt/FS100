"""Domain routers (D33): embedding similarity and the LLM classifier."""

import asyncio

import pytest
from pydantic import BaseModel

from ai_service import embeddings
from ai_service.catalog import DomainInfo, Taxonomy, load_taxonomy
from ai_service.core.settings import Settings
from ai_service.embeddings import Embedder
from ai_service.knowledge_base import Domain
from ai_service.llm import Message, Usage
from ai_service.routing import EmbeddingRouter, LlmRouter, Route
from support import FakeTextEmbedding

# One distinct word per domain: the fake embedder hashes words, so only that word matches.
WORDS: dict[Domain, str] = {
    "db": "postgres",
    "dev": "angular",
    "cloud": "azure",
    "devops": "kubernetes",
    "mlops": "mlflow",
    "ai": "prompts",
    "security": "secrets",
    "architecture": "boundaries",
    "sre": "oncall",
}


def test_the_embedding_router_is_confident_only_for_a_clear_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(embeddings, "TextEmbedding", FakeTextEmbedding)
    taxonomy = Taxonomy(version=1, domains={d: DomainInfo(description=w) for d, w in WORDS.items()})
    router = EmbeddingRouter(Embedder("fake"), taxonomy)

    clear = asyncio.run(router.route("kubernetes"))
    vague = asyncio.run(router.route("weather"))

    assert (clear.domains, clear.router, clear.needs_tools) == (["devops"], "embedding", True)
    assert clear.confident
    assert not vague.confident


class Classifier:
    """Stands in for the cheap model; records the prompt."""

    def __init__(self) -> None:
        self.messages: list[Message] = []

    async def complete_json[T: BaseModel](
        self, messages: list[Message], schema: type[T], model: str | None = None
    ) -> tuple[T, Usage]:
        self.messages = messages
        verdict = {"domains": ["sre"], "needs_tools": False, "confidence": 0.6}
        return schema.model_validate(verdict), Usage(30, 8, 1e-5, model or "default")


def test_the_llm_router_classifies_with_the_taxonomy_descriptions() -> None:
    llm = Classifier()
    router = LlmRouter(llm, load_taxonomy(Settings().taxonomy_config), "cheap/model")

    route = asyncio.run(router.route("Is the pager on?"))

    assert route == Route(["sre"], False, 0.6, "llm", Usage(30, 8, 1e-5, "cheap/model"))
    assert not route.confident
    system = str(llm.messages[0].get("content"))
    assert "- sre: Site reliability" in system
    assert llm.messages[1] == {"role": "user", "content": "Is the pager on?"}
