import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

import openai
from openai.types.chat import ChatCompletionToolParam
from pydantic import BaseModel, Field

from ai_service.knowledge_base import Domain, Hit, KnowledgeBase

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


def kb_search(
    kb: KnowledgeBase, top_k: int, score_threshold: float | None, domains: list[Domain] | None
) -> ToolSpec[SearchArgs]:
    """Native KB adapter until the MCP path (M2.4); `domains` is the default filter."""

    async def run(args: SearchArgs) -> ToolOutput:
        hits = await asyncio.to_thread(
            kb.search, args.query, top_k, score_threshold, args.domains or domains
        )
        summary = f"{len(hits)} hits, top score {hits[0].score:.2f}" if hits else "no hits"
        return ToolOutput("", summary, hits)

    return ToolSpec(
        name="kb.search_knowledge_base",
        description="Search the knowledge base (runbooks, ADRs, setup guides, handbooks). "
        "Returns numbered sources to cite. Search again with other words or domains if needed.",
        args=SearchArgs,
        run=run,
        result_budget_tokens=3000,
    )
