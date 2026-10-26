"""Query transformation (D58): HyDE, the survivor of M3a.4 — a cheap model writes a passage that
answers the question, and retrieval searches it next to the question."""

import hashlib
import json
import logging
from dataclasses import dataclass, field, replace
from typing import Literal

from opentelemetry import trace
from pydantic import BaseModel

from ai_service import prompts
from ai_service.knowledge_base import SPAN_KIND
from ai_service.llm import Message, StructuredLlm, Usage

Strategy = Literal["plain", "hyde"]  # multi-query and the standalone rewrite lost on `dev`
STRATEGY = (  # for the agent and other MCP clients
    "`hyde` also searches with a passage a model drafts as the answer: finds more for vague, "
    "paraphrased or cross-language questions, but takes seconds longer."
)
CACHE_SIZE = 1024
PROMPT = prompts.load("hyde")
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class Passage(BaseModel):
    passage: str


@dataclass(frozen=True)
class Query:
    """`text` is searched on every side and scores the hits; `passages` add dense candidates
    (`KnowledgeBase.search`)."""

    text: str
    passages: list[str] = field(default_factory=list[str])
    usage: Usage | None = None  # None: no call (plain, cached or failed)


class QueryTransformer:
    """Cached per prompt, model and question; a failed call searches the question alone."""

    def __init__(self, llm: StructuredLlm, model: str | None) -> None:
        self._llm = llm
        self._model = model
        self._cache: dict[str, Query] = {}

    async def expand(self, question: str, strategy: Strategy) -> Query:
        if strategy == "plain":
            return Query(question)
        key = hashlib.sha256(json.dumps([PROMPT.hash, self._model, question]).encode()).hexdigest()
        if cached := self._cache.get(key):
            return replace(cached, usage=None)
        messages: list[Message] = [
            {"role": "system", "content": PROMPT.text},
            {"role": "user", "content": question},
        ]
        attributes = {
            SPAN_KIND: "CHAIN",
            "input.value": question,
            "llm.prompt_template.version": PROMPT.ref,
            "prompt.hash": PROMPT.hash,
        }
        with tracer.start_as_current_span("hyde", attributes=attributes):
            try:
                passage, usage = await self._llm.complete_json(messages, Passage, self._model)
            except Exception as error:
                logger.warning("HyDE failed, searching the question alone: %r", error)
                return Query(question)
        query = Query(question, [passage.passage], usage)
        if len(self._cache) >= CACHE_SIZE:
            del self._cache[next(iter(self._cache))]  # the oldest entry
        self._cache[key] = query
        return query
