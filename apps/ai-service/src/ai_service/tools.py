import asyncio
import ipaddress
import json
import logging
import re
import socket
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Annotated, Any, Literal
from uuid import UUID

import httpx2
import openai
from openai.types.chat import ChatCompletionToolParam
from pydantic import BaseModel, Field, HttpUrl, RootModel, WithJsonSchema

from ai_service.core.auth import Caller
from ai_service.core.settings import Settings
from ai_service.knowledge_base import Domain, Hit
from ai_service.mcp_client import McpClient
from ai_service.tokens import Tokens

ToolKind = Literal["read", "write"]
Risk = Literal["low", "medium", "high"]
Role = Literal["viewer", "editor", "admin"]
_RANK: dict[str, int] = {"viewer": 0, "editor": 1, "admin": 2}
# HTML comments hide instructions; forged delimiter tags would break out of the data block (D31).
_UNTRUSTED = re.compile(r"<!--.*?(?:-->|$)|</?(?:tool_result|sources?)\b", re.I | re.S)
GITHUB_API = "https://api.github.com"
GITHUB_TRANSPORT: httpx2.AsyncBaseTransport | None = None  # tests answer for GitHub
WEB_TRANSPORT: httpx2.AsyncBaseTransport | None = None  # tests answer for the web
WEB_MAX_BYTES = 2_000_000  # decoded, so a gzip bomb stops here too
_NAT64 = ipaddress.ip_network("64:ff9b::/96")  # `is_global` lets it through; it embeds any IPv4
_HIDDEN = {"script", "style", "noscript", "template", "svg"}
_BLOCKS = {
    *("br", "p", "div", "li", "tr", "pre", "blockquote", "section", "article", "header"),
    *("footer", "nav", "main", "table", "ul", "ol", "dt", "dd", "hr", "title"),
    *(f"h{level}" for level in range(1, 7)),
}
# Set by the harness while an approved write runs; the write's idempotency key (D39).
approval_id: ContextVar[str | None] = ContextVar("approval_id", default=None)
logger = logging.getLogger(__name__)


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
    parameters: dict[str, Any] | None = None  # an MCP server's input schema; None = from `args`
    server: str | None = None  # the MCP server; None = native
    domains: tuple[Domain, ...] = ()  # the routes that offer it (D33); () = every route
    service_identity: str | None = None  # the credential it acts with, if not the user's (D37)
    available: bool = True  # False: listed for the catalog, never offered

    @property
    def requires_approval(self) -> bool:
        return self.kind == "write"

    @property
    def group(self) -> str:
        return self.name.split(".")[0]

    @property
    def wire_name(self) -> str:
        return self.name.replace(".", "_")  # function names allow no dots

    def definition(self) -> ChatCompletionToolParam:
        if self.parameters is None:
            return openai.pydantic_function_tool(
                self.args, name=self.wire_name, description=self.description
            )
        return {
            "type": "function",
            "function": {
                "name": self.wire_name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class JsonArgs(RootModel[dict[str, Any]]):
    """Arguments of an MCP server's tool: any JSON object, validated by that server."""


def registry(*groups: list[ToolSpec[Any]]) -> list[ToolSpec[Any]]:
    """One list for every source of tools (D30); on a wire-name clash the earlier group wins."""
    tools: dict[str, ToolSpec[Any]] = {}
    for tool in (tool for group in groups for tool in group):
        if (kept := tools.setdefault(tool.wire_name, tool)) is not tool:
            logger.warning("tool %s dropped: its name clashes with %s", tool.name, kept.name)
    return list(tools.values())


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
    # Strict function calling rejects `format: uri`; Pydantic still validates the URL.
    url: Annotated[HttpUrl, WithJsonSchema({"type": "string"})] = Field(
        description="A PDF, Markdown or text file"
    )
    domains: list[Domain] = Field(min_length=1)


class IssueArgs(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    body: str = Field(max_length=60_000, description="Markdown; link the runs or documents.")


class FetchArgs(BaseModel):
    url: Annotated[HttpUrl, WithJsonSchema({"type": "string"})] = Field(
        description="An http(s) URL on one of the allowed hosts"
    )


class _PageText(HTMLParser):
    """Text of an HTML page. Text hidden by CSS stays in: the result is untrusted data anyway."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _HIDDEN:
            self._hidden += 1
        elif tag in _BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _HIDDEN:
            self._hidden = max(0, self._hidden - 1)
        elif tag in _BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.parts.append(data)


def html_text(html: str) -> str:
    parser = _PageText()
    parser.feed(html)
    parser.close()
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)


async def public_ip(host: str, port: int) -> str:
    """The address to connect to. The caller pins it, so DNS rebinding cannot swap it later."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    ips = [ipaddress.ip_address(info[4][0]) for info in infos]
    if not ips or any(not ip.is_global or ip.is_multicast or ip in _NAT64 for ip in ips):
        raise RuntimeError(f"{host} is not a public address")
    return str(ips[0])


def kb_tools(
    mcp: McpClient, tokens: Tokens, caller: Caller, domains: list[Domain] | None
) -> list[ToolSpec[Any]]:
    """The own MCP server's tools (D34), called as `caller`; `domains` is the default filter."""

    async def call(tool: str, args: BaseModel, write: bool = False) -> dict[str, Any]:
        # Hop 2 (ADR-0009); a write gets `kb:write` and confirms the server's request (ADR-0008).
        token = await tokens.exchange(caller.token, "kb:read kb:write" if write else "kb:read")
        payload = args.model_dump(mode="json")
        result = await mcp.call(token, tool, payload, partition=caller.sub, write=write)
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
            server="kb",
            description="Search the knowledge base (runbooks, ADRs, setup guides, handbooks). "
            "Returns numbered sources to cite. Search again with other words or domains if needed.",
            args=SearchArgs,
            run=search,
            result_budget_tokens=3000,
        ),
        ToolSpec(
            name="kb.get_document",
            server="kb",
            description="Read a document from the knowledge base, a few chunks at a time.",
            args=DocumentArgs,
            run=get_document,
            result_budget_tokens=3000,
        ),
        ToolSpec(
            name="kb.list_sources",
            server="kb",
            description="List the documents in the knowledge base, e.g. all ADRs (architecture).",
            args=SourcesArgs,
            run=list_sources,
        ),
        ToolSpec(
            name="kb.ingest_url",
            server="kb",
            description="Add the document at a URL to the knowledge base (after the user's OK).",
            args=IngestArgs,
            run=ingest_url,
            kind="write",
            risk="medium",
            min_role="editor",
        ),
    ]


def sandbox_tools(settings: Settings) -> list[ToolSpec[Any]]:
    """The one GitHub write (D39): an issue in the sandbox repo with PAT #2, after approval."""
    repo, pat = settings.github_sandbox_repo, settings.github_pat_sandbox_write
    headers = {
        "authorization": f"Bearer {pat}",
        "accept": "application/vnd.github+json",
        "x-github-api-version": "2022-11-28",
    }

    async def github(method: str, path: str, **kwargs: Any) -> Any:
        async with httpx2.AsyncClient(
            base_url=GITHUB_API, headers=headers, transport=GITHUB_TRANSPORT, timeout=15
        ) as client:
            response = await client.request(method, f"/repos/{repo}{path}", **kwargs)
        if response.status_code >= 500:
            raise TransientToolError(f"GitHub: HTTP {response.status_code}")
        if not response.is_success:
            raise RuntimeError(f"GitHub: HTTP {response.status_code} {response.text[:200]}")
        return response.json()

    async def create_issue(args: IssueArgs) -> ToolOutput:
        if (key := approval_id.get()) is None:
            raise RuntimeError("Runs only as an approved action")
        marker = f"<!-- kb-agent:{key} -->"
        # Search before create, so a retry or a replayed action finds the first issue.
        # shortcut: the newest 100 issues only; enough while approvals expire within minutes
        recent = await github("GET", "/issues", params={"state": "all", "per_page": 100})
        issue = next((i for i in recent if marker in (i.get("body") or "")), None)
        if issue is None:
            body = {"title": args.title, "body": f"{args.body}\n\n{marker}"}
            issue = await github("POST", "/issues", json=body)
        content = json.dumps({"number": issue["number"], "url": issue["html_url"]})
        return ToolOutput(content, f"issue #{issue['number']} {issue['html_url']}")

    return [
        ToolSpec(
            name="github_sandbox.create_issue",
            description=f"Open an issue in the sandbox repo {repo or '(not configured)'} "
            "(after the user's OK).",
            args=IssueArgs,
            run=create_issue,
            kind="write",
            risk="medium",
            min_role="editor",
            service_identity="GITHUB_PAT_SANDBOX_WRITE",
            available=bool(repo and pat),
        )
    ]


def web_tools(settings: Settings) -> list[ToolSpec[Any]]:
    """`web.fetch`: a page from an allow-listed host as text, guarded as `ingest_url` (D36)."""
    hosts = {host.strip() for host in settings.web_fetch_allowed_hosts.split(",") if host.strip()}

    async def fetch(args: FetchArgs) -> ToolOutput:
        url = httpx2.URL(str(args.url))
        async with httpx2.AsyncClient(transport=WEB_TRANSPORT, timeout=15) as client:
            for _ in range(4):  # the first request and at most 3 redirects, each checked
                netloc = url.host if url.port is None else f"{url.host}:{url.port}"
                if url.scheme not in ("http", "https") or netloc not in hosts:
                    raise RuntimeError(f"{url.scheme}://{netloc} is not an allowed host")
                ip = await public_ip(url.host, url.port or (443 if url.scheme == "https" else 80))
                request = client.build_request(
                    "GET",
                    url.copy_with(host=ip),
                    headers={"host": netloc},
                    extensions={"sni_hostname": url.host},
                )
                response = await client.send(request, stream=True)
                try:
                    if response.has_redirect_location:
                        url = url.join(response.headers["location"])
                        continue
                    if response.status_code >= 500:
                        raise TransientToolError(f"{netloc}: HTTP {response.status_code}")
                    if not response.is_success:
                        raise RuntimeError(f"{netloc} answered HTTP {response.status_code}")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body += chunk
                        if len(body) > WEB_MAX_BYTES:
                            raise RuntimeError(f"The page is larger than {WEB_MAX_BYTES} bytes")
                    media = response.headers.get("content-type", "").split(";")[0].strip().lower()
                    encoding = response.encoding or "utf-8"
                finally:
                    await response.aclose()
                break
            else:
                raise RuntimeError(f"Too many redirects from {url.host}")
        text = bytes(body).decode(encoding, "replace")
        if "html" in media:
            text = html_text(text)
        elif not (media.startswith("text/") or media == "application/json"):
            raise RuntimeError(f"{media or 'An unknown type'} is not read; use a web page or text")
        return ToolOutput(f"{url}\n\n{text}", f"{netloc}: {len(text):,} chars")

    return [
        ToolSpec(
            name="web.fetch",
            description="Read a web page as text. Only these hosts: "
            f"{', '.join(sorted(hosts)) or '(none configured)'}.",
            args=FetchArgs,
            run=fetch,
            risk="medium",
            min_role="editor",
            result_budget_tokens=3000,
            available=bool(hosts),
        )
    ]
