"""Domain routing (D33): which tool groups and which default search filter a turn gets."""

import asyncio
from dataclasses import dataclass
from typing import Literal, Protocol

import numpy as np
from pydantic import BaseModel, Field

from ai_service.catalog import Taxonomy
from ai_service.core.settings import Settings
from ai_service.embeddings import Embedder
from ai_service.knowledge_base import Domain
from ai_service.llm import Message, StructuredLlm, Usage

RouterName = Literal["embedding", "llm", "user"]
# Calibrated on the retrieval_v1 questions with bge-m3 (ADR-0012); below it: every tool, no filter.
MIN_CONFIDENCE = 0.8
TEMPERATURE = 0.03  # softmax over cosine similarities
PROMPT = """\
Classify a question to an assistant for software, platform and operations engineers.
Domains:
{domains}
Return the domains the question is about (usually one, [] if none), whether answering it needs \
tools (the knowledge base or GitHub; false only for small talk), and your confidence from 0 to 1."""


@dataclass(frozen=True)
class Route:
    domains: list[Domain]
    needs_tools: bool
    confidence: float
    router: RouterName
    usage: Usage | None = None  # the classifier's tokens

    @property
    def confident(self) -> bool:
        return self.confidence >= MIN_CONFIDENCE


class Router(Protocol):
    async def route(self, question: str) -> Route: ...


class EmbeddingRouter:
    """Cosine similarity of the question to each domain description; no tokens."""

    def __init__(self, embedder: Embedder, taxonomy: Taxonomy) -> None:
        self._embedder = embedder
        self._domains = list(taxonomy.domains)
        descriptions = [
            f"{domain}: {info.description}" for domain, info in taxonomy.domains.items()
        ]
        self._vectors = _unit(np.array(embedder.embed_passages(descriptions)))

    async def route(self, question: str) -> Route:
        return await asyncio.to_thread(self._route, question)

    def _route(self, question: str) -> Route:
        scores = self._vectors @ _unit(np.array(self._embedder.embed_queries([question])))[0]
        weights = np.exp((scores - scores.max()) / TEMPERATURE)
        best = int(scores.argmax())
        confidence = float(weights[best] / weights.sum())
        return Route([self._domains[best]], True, confidence, "embedding")


class Classification(BaseModel):
    domains: list[Domain]
    needs_tools: bool
    confidence: float = Field(ge=0, le=1)


class LlmRouter:
    """A cheap model classifies the question with structured output."""

    def __init__(self, llm: StructuredLlm, taxonomy: Taxonomy, model: str | None) -> None:
        domains = "\n".join(f"- {d}: {info.description}" for d, info in taxonomy.domains.items())
        self._llm = llm
        self._model = model
        self._prompt = PROMPT.format(domains=domains)

    async def route(self, question: str) -> Route:
        messages: list[Message] = [
            {"role": "system", "content": self._prompt},
            {"role": "user", "content": question},
        ]
        result, usage = await self._llm.complete_json(messages, Classification, self._model)
        return Route(result.domains, result.needs_tools, result.confidence, "llm", usage)


def create_router(
    settings: Settings, embedder: Embedder, taxonomy: Taxonomy, llm: StructuredLlm
) -> Router:
    if settings.router == "llm":
        return LlmRouter(llm, taxonomy, settings.router_model or None)
    return EmbeddingRouter(embedder, taxonomy)


def _unit(vectors: np.ndarray) -> np.ndarray:
    return vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
