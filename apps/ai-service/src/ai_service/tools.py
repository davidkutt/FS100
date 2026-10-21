import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

import openai
from openai.types.chat import ChatCompletionToolParam
from pydantic import BaseModel, Field, HttpUrl

from ai_service.core.auth import Caller
from ai_service.knowledge_base import Domain, Hit
from ai_service.mcp_client import McpClient

ToolKind = Literal["read", "write"]
Risk = Literal["low", "medium", "high"]
Role = Literal["viewer", "editor", "admin"]
_RANK: dict[str, int] = {"viewer": 0, "editor": 1, "admin": 2}
# HTML comments hide instructions; forged delimiter tags would break out of the data block (D31).
_UNTRUSTED = re.compile(r"<!--.*?(?:-->|$)|</?(?:tool_result|sources?)\b", re.I | re.S)


class TransientToolError(Exception):
    """Worth retrying: the harness retries it with backoff before reporting it to the model."""


@dataclass(frozen=True)
class ToolOutput:
    content: str
    summary: str  # one line for the UI timeline
    hits: list[Hit] | None = None  # KB hits: the harness numbers and renders them as sources


@dataclass(frozen=True)
class ToolSpec[A: BaseModel]:
    """One tool in the registry (D30), whatever serves it."""

    name: str  # namespaced: kb.search_knowledge_base
    description: str
    args: type[A]
    run: Callable[[A], Awaitable[ToolOutput]]
    kind: ToolKind = "read"
    risk: Risk = "low"
    min_role: Role = "viewer"
    timeout_s: float | None = None  # None = AGENT_TOOL_TIMEOUT_S
    result_budget_tokens: int = 2000

    @property
    def requires_approval(self) -> bool:
        return self.kind == "write"

    @property
    def wire_name(self) -> str:
        return self.name.replace(".", "_")  # function names allow no dots

    def definition(self) -> ChatCompletionToolParam:
        return openai.pydantic_function_tool(
            self.args, name=self.wire_name, description=self.description
        )


def permitted(min_role: Role, roles: list[str]) -> bool:
    return max((_RANK.get(role, -1) for role in roles), default=-1) >= _RANK[min_role]


def untrusted(text: str) -> str:
    return _UNTRUSTED.sub("", text)


def wrap(tool: str, status: str, content: str, budget_tokens: int) -> tuple[str, bool]:
    """Tool output as a delimited, labelled data block, cut to the tool's budget."""
    limit = budget_tokens * 4  # shortcut: ~4 chars/token, use a tokenizer if budgets get tight
    truncated = len(content) > limit
    body = content[:limit] + ("\n[truncated]" if truncated else "")
    label = f'tool="{tool}" status="{status}" trust="untrusted"'
    return f"<tool_result {label}>\n{body}\n</tool_result>", truncated


class SearchArgs(BaseModel):
    query: str = Field(min_length=1, description="What to look for; one topic per search.")
    domains: list[Domain] | None = Field(
        None, description="Only search these domains; null searches all."
    )


class DocumentArgs(BaseModel):
    doc_id: UUID
    offset: int = Field(0, ge=0, description="First chunk; use `next_offset` to read on.")


class SourcesArgs(BaseModel):
    domains: list[Domain] | None = Field(None, description="Only these domains; null lists all.")


class IngestArgs(BaseModel):
    url: HttpUrl = Field(description="A PDF, Markdown or text file")
    domains: list[Domain] = Field(min_length=1)


def kb_tools(mcp: McpClient, caller: Caller, domains: list[Domain] | None) -> list[ToolSpec[Any]]:
    """The own MCP server's tools (D34), called as `caller`; `domains` is the default filter."""

    async def call(tool: str, args: BaseModel, write: bool = False) -> dict[str, Any]:
        result = await mcp.call(caller, tool, args.model_dump(mode="json"), write=write)
        if result.is_error:
            raise RuntimeError(" ".join(c.text for c in result.content if c.type == "text"))
        return result.structured_content or {}

    async def search(args: SearchArgs) -> ToolOutput:
        filtered = SearchArgs(query=args.query, domains=args.domains or domains)
        hits = [
            Hit.model_validate(hit)
            for hit in (await call("search_knowledge_base", filtered))["hits"]
        ]
        summary = f"{len(hits)} hits, top score {hits[0].score:.2f}" if hits else "no hits"
        return ToolOutput("", summary, hits)

    async def get_document(args: DocumentArgs) -> ToolOutput:
        doc = await call("get_document", args)
        summary = f"{len(doc['chunks'])} of {doc['chunk_count']} chunks"
        return ToolOutput(json.dumps(doc, ensure_ascii=False), summary)

    async def list_sources(args: SourcesArgs) -> ToolOutput:
        sources = (await call("list_sources", args))["sources"]
        return ToolOutput(json.dumps(sources, ensure_ascii=False), f"{len(sources)} documents")

    async def ingest_url(args: IngestArgs) -> ToolOutput:
        started = await call("ingest_url", args, write=True)
        return ToolOutput(json.dumps(started), f"document {started['doc_id']} {started['status']}")

    return [
        ToolSpec(
            name="kb.search_knowledge_base",
            description="Search the knowledge base (runbooks, ADRs, setup guides, handbooks). "
            "Returns numbered sources to cite. Search again with other words or domains if needed.",
            args=SearchArgs,
            run=search,
            result_budget_tokens=3000,
        ),
        ToolSpec(
            name="kb.get_document",
            description="Read a document from the knowledge base, a few chunks at a time.",
            args=DocumentArgs,
            run=get_document,
            result_budget_tokens=3000,
        ),
        ToolSpec(
            name="kb.list_sources",
            description="List the documents in the knowledge base, e.g. all ADRs (architecture).",
            args=SourcesArgs,
            run=list_sources,
        ),
        ToolSpec(
            name="kb.ingest_url",
            description="Add the document at a URL to the knowledge base (after the user's OK).",
            args=IngestArgs,
            run=ingest_url,
            kind="write",
            risk="medium",
            min_role="editor",
        ),
    ]
