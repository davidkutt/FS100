"""Own MCP server (D34, ADR-0010): the knowledge base for the own agent and other MCP clients."""

import asyncio
from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID

import httpx2
import jwt
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.caching import CacheHint
from mcp.server.mcpserver import Elicit, MCPServer, Resolve
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import AnyHttpUrl, BaseModel, Field, HttpUrl

from ai_service.core.auth import Caller, Jwt
from ai_service.core.settings import Settings
from ai_service.knowledge_base import DocumentInfo, DocumentSection, Domain, Hit, KnowledgeBase
from ai_service.query import STRATEGY, QueryTransformer, Strategy
from ai_service.tokens import Tokens
from ai_service.tools import Role, permitted

Domains = Annotated[list[Domain] | None, Field(description="Only these domains; null = all.")]
API_TRANSPORT: httpx2.AsyncBaseTransport | None = None  # tests answer for the API


class SearchResult(BaseModel):
    hits: list[Hit]


class DocumentWindow(DocumentInfo):
    section_count: int
    sections: list[DocumentSection]
    next_offset: int | None  # null: the window ends with the last section


class Sources(BaseModel):
    sources: list[DocumentInfo]


class Outline(DocumentInfo):
    headings: list[str]


class IngestStarted(BaseModel):
    doc_id: UUID
    status: str


class Confirmation(BaseModel):
    confirm: bool = Field(description="Add this document to the knowledge base?")


class KbTokenVerifier:
    """Admits Keycloak tokens for this resource only (`aud` = MCP resource URL, D35)."""

    def __init__(self, settings: Settings) -> None:
        self._jwt = Jwt(settings, settings.mcp_resource_url)

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = await asyncio.to_thread(self._jwt.decode, token)
        except jwt.PyJWTError:
            return None
        return AccessToken(
            token=token,
            client_id=claims.get("azp", ""),
            scopes=claims.get("scope", "").split(),
            expires_at=claims["exp"],
            subject=claims["sub"],
            claims=claims,
        )


def _claims(min_role: Role, scope: str = "kb:read") -> dict[str, Any]:
    """Scope and role: Keycloak grants the optional scopes to any role (ADR-0009)."""
    token = get_access_token()
    if token is None or scope not in token.scopes:
        raise ToolError(f"insufficient_scope: needs {scope}")
    claims = token.claims or {}
    if not permitted(min_role, Caller.of(claims, token.token).roles):
        raise ToolError(f"Not permitted for your role (needs {min_role})")
    return claims


def _detail(response: httpx2.Response) -> str:
    """RFC 9457 `detail` of an API error, else the status line."""
    try:
        return response.json()["detail"]
    except (ValueError, KeyError, TypeError):
        return f"HTTP {response.status_code}"


def create_mcp(
    settings: Settings,
    kb: Callable[[], KnowledgeBase],
    tokens: Tokens,
    transformer: Callable[[], QueryTransformer],
) -> MCPServer:
    """`kb` and `transformer` are getters: they only exist once the app's lifespan has started."""
    mcp = MCPServer(
        "fs100-kb",
        instructions="The FS100 knowledge base: runbooks, ADRs, setup guides and handbooks.",
        # Clients may reuse the list (the SDK default `ttlMs: 0` makes them list before each call).
        cache_hints={"tools/list": CacheHint(ttl_ms=300_000)},
        token_verifier=KbTokenVerifier(settings),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(settings.ai_keycloak_issuer),
            resource_server_url=AnyHttpUrl(settings.mcp_resource_url),
            required_scopes=["kb:read"],
            validate_token_resource=False,  # KbTokenVerifier checks `aud`
        ),
    )

    @mcp.tool()
    async def search_knowledge_base(  # pyright: ignore[reportUnusedFunction]
        query: Annotated[str, Field(min_length=1, description="What to look for.")],
        top_k: Annotated[int, Field(ge=1, le=10)] = settings.retrieval_top_k,
        domains: Domains = None,
        doc_ids: Annotated[list[UUID] | None, Field(description="Only these documents.")] = None,
        strategy: Annotated[Strategy, Field(description=STRATEGY)] = "plain",
    ) -> SearchResult:
        """The chunks that match a query best, with their documents and scores."""
        _claims("viewer")
        # shortcut: HyDE's cost (~0.0001 USD) is not in the caller's usage or cost cap; return
        # it with the hits once callers account per tool call.
        expanded = await transformer().expand(query, strategy)
        hits = await asyncio.to_thread(
            kb().search,
            expanded.text,
            top_k,
            settings.retrieval_score_threshold,
            domains,
            doc_ids,
            passages=expanded.passages,
        )
        return SearchResult(hits=hits)

    @mcp.tool()
    async def get_document(  # pyright: ignore[reportUnusedFunction]
        doc_id: UUID,
        offset: Annotated[
            int, Field(ge=0, description="First section; `next_offset` pages on.")
        ] = 0,
        limit: Annotated[int, Field(ge=1, le=20)] = 5,
    ) -> DocumentWindow:
        """A document's labels and a window of its sections in reading order."""
        _claims("viewer")
        info = await asyncio.to_thread(kb().document, doc_id)
        if info is None:
            raise ToolError(f"Document {doc_id} not found")
        sections = await asyncio.to_thread(kb().sections, doc_id)
        end = min(offset + limit, len(sections))
        return DocumentWindow(
            **info.model_dump(),
            section_count=len(sections),
            sections=sections[offset:end],
            next_offset=end if end < len(sections) else None,
        )

    @mcp.tool()
    async def list_sources(domains: Domains = None) -> Sources:  # pyright: ignore[reportUnusedFunction]
        """Every document in the knowledge base, e.g. the ADRs with `domains: ["architecture"]`."""
        _claims("viewer")
        return Sources(sources=await asyncio.to_thread(kb().documents, domains))

    @mcp.resource("kb://documents/{doc_id}", mime_type="application/json")
    async def document(doc_id: UUID) -> str:  # pyright: ignore[reportUnusedFunction]
        """A document's labels and outline (its headings in reading order)."""
        _claims("viewer")
        info = await asyncio.to_thread(kb().document, doc_id)
        if info is None:
            raise ToolError(f"Document {doc_id} not found")
        sections = await asyncio.to_thread(kb().sections, doc_id)
        headings = list(dict.fromkeys(s.heading for s in sections if s.heading))
        return Outline(**info.model_dump(), headings=headings).model_dump_json()

    def confirmed(url: HttpUrl, domains: list[Domain]) -> Elicit[Confirmation]:
        _claims("editor", "kb:write")  # before asking, so nobody confirms what they may not do
        return Elicit(f"Add {url} to the knowledge base ({', '.join(domains)})?", Confirmation)

    @mcp.tool()
    async def ingest_url(  # pyright: ignore[reportUnusedFunction]
        url: Annotated[
            HttpUrl, Field(description="A web page, PDF, Markdown or text file on an allowed host")
        ],
        domains: Annotated[list[Domain], Field(min_length=1)],
        confirmation: Annotated[Confirmation, Resolve(confirmed)],
    ) -> IngestStarted:
        """Add the document at a URL to the knowledge base once the user confirms; it is
        ingested in the background."""
        claims = _claims("editor", "kb:write")
        if not confirmation.confirm:
            raise ToolError("Not confirmed; nothing was added")
        name = claims.get("name") or claims.get("preferred_username") or claims["sub"]
        # Trusted subsystem (D36): kb-ai's service account, the user named in the body.
        async with httpx2.AsyncClient(transport=API_TRANSPORT, timeout=30) as client:
            response = await client.post(
                f"{settings.ai_api_url}/internal/documents/from-url",
                json={
                    "url": str(url),
                    "domains": domains,
                    "onBehalfOf": {"sub": claims["sub"], "name": name},
                },
                headers={"authorization": f"Bearer {await tokens.service_token()}"},
            )
        if response.status_code != 202:
            raise ToolError(f"Not added: {_detail(response)}")
        started = response.json()
        return IngestStarted(doc_id=started["id"], status=started["status"])

    return mcp
