"""Contextual retrieval (D60, ADR-0019): per chunk, a cheap model reads the whole document and the
chunk, writes a short context that is indexed with the chunk, and picks the chunk's sub-topics."""

import asyncio
import hashlib
import json
import logging
from collections.abc import Collection
from dataclasses import replace
from uuid import UUID

from opentelemetry import trace
from pydantic import BaseModel

from ai_service import prompts
from ai_service.ingest import Section
from ai_service.knowledge_base import SPAN_KIND, Domain
from ai_service.llm import Message, StructuredLlm
from ai_service.storage import Store

PROMPT = prompts.load("contextual")
CONCURRENCY = 8
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class Label(BaseModel):
    context: str
    topics: list[str]


type Split = list[tuple[Section, list[Section]]]


class Contextualizer:
    """For documents in one of `domains`. The document goes into the system message and the chunk
    after it, so every call after the first reads the document from the provider's prompt cache
    (with the document in a user message, gpt-6-luna at OpenRouter cached nothing). Labels are kept
    in `store` by the hash of model and messages: contexts differ from run to run, so a re-index
    that wrote them anew would move retrieval by itself (M3a.6: up to 0.04 nDCG@10 on `test`).
    Chunks without a label (the first new call failed, a later one failed, or the document reached
    `max_usd`) are indexed as they are; their sub-topics come from the embedding fallback
    (`KnowledgeBase.index`)."""

    def __init__(
        self,
        llm: StructuredLlm,
        model: str | None,
        topics: dict[str, str],
        domains: Collection[Domain],
        max_usd: float,
        store: Store | None = None,
    ) -> None:
        self._llm = llm
        self._model = model
        self._topics = topics
        self._store = store
        self.domains = set(domains)
        self.max_usd = max_usd

    def on(self, domains: list[Domain]) -> bool:
        return not self.domains.isdisjoint(domains)

    async def contextualize(
        self,
        sections: list[Section],
        split: Split,
        *,
        doc_id: UUID,
        version: int,
        domains: list[Domain],
    ) -> tuple[Split, float]:
        """The chunks with their labels, and what the new calls cost in USD."""
        if not self.on(domains) or not split:
            return split, 0.0
        offered = {t: d for t, d in self._topics.items() if t.split("/")[0] in domains}
        listed = "\n".join(f"- {topic}: {description}" for topic, description in offered.items())
        # The heading path: the parser drops heading-only blocks such as a title over a subheading.
        document = "\n\n".join(
            f"[{section.heading}]\n{section.text}" if section.heading else section.text
            for section in sections
        )
        system: Message = {
            "role": "system",
            "content": PROMPT.text.format(topics=listed, document=document),
        }
        calls: dict[str, list[Message]] = {}
        keys: list[str] = []  # per chunk, in order
        for _, children in split:
            for chunk in children:
                messages: list[Message] = [
                    system,
                    {"role": "user", "content": f"<chunk>\n{chunk.text}\n</chunk>"},
                ]
                key = hashlib.sha256(json.dumps([self._model, messages]).encode()).hexdigest()
                keys.append(key)
                calls[key] = messages
        stored = await self._store.contexts(doc_id) if self._store else {}
        labels = {key: Label.model_validate(stored[key]) for key in calls if key in stored}
        new = [key for key in calls if key not in labels]
        semaphore = asyncio.Semaphore(CONCURRENCY)
        spent = 0.0

        async def label(key: str) -> tuple[str, Label | None]:
            nonlocal spent
            async with semaphore:
                if spent >= self.max_usd:  # calls already in flight still finish
                    return key, None
                result, usage = await self._llm.complete_json(
                    calls[key], Label, self._model, f"{doc_id}:{version}"
                )
            spent += usage.cost_usd or 0
            return key, result

        async def label_or_none(key: str) -> tuple[str, Label | None]:
            try:
                return await label(key)
            except Exception as error:
                logger.warning("No context for a chunk of %s: %r", doc_id, error)
                return key, None

        attributes = {
            SPAN_KIND: "CHAIN",
            "doc_id": str(doc_id),
            "chunks": len(keys),
            "stored": len(labels),
            "llm.prompt_template.version": PROMPT.ref,
            "prompt.hash": PROMPT.hash,
        }
        with tracer.start_as_current_span("contextualize", attributes=attributes) as span:
            fresh: list[tuple[str, Label | None]] = []
            try:
                fresh = [await label(new[0])] if new else []  # alone: it fills the prompt cache
                fresh += await asyncio.gather(*map(label_or_none, new[1:]))
            except Exception as error:
                logger.warning("Contextual retrieval failed for %s, no context: %r", doc_id, error)
            span.set_attribute("cost_usd", spent)
        made = {key: found for key, found in fresh if found}
        if self._store and made:
            await self._store.put_contexts(doc_id, {k: v.model_dump() for k, v in made.items()})
        labels |= made
        if spent >= self.max_usd:
            logger.warning("%s reached the cost cap of %.2f USD", doc_id, self.max_usd)

        found = iter(labels.get(key) for key in keys)

        def labelled(chunk: Section) -> Section:
            if (label := next(found)) is None:
                return chunk
            topics = tuple(topic for topic in label.topics if topic in offered)
            return replace(chunk, context=label.context.strip() or None, topics=topics)

        return [(parent, [labelled(c) for c in children]) for parent, children in split], spent
