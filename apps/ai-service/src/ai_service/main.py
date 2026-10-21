from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import Depends, FastAPI, Request, Response
from pydantic import BaseModel
from qdrant_client import QdrantClient

from ai_service import __version__
from ai_service.agent import Agent
from ai_service.api import agent, catalog, chat, documents, health
from ai_service.catalog import load_models, load_taxonomy
from ai_service.core.auth import ServiceAuth
from ai_service.core.logging import request_id, setup_logging
from ai_service.core.settings import Settings, get_settings
from ai_service.core.tracing import setup_tracing
from ai_service.embeddings import Embedder
from ai_service.knowledge_base import KnowledgeBase
from ai_service.llm import create_provider
from ai_service.mcp_client import McpClient
from ai_service.mcp_server import create_mcp
from ai_service.rag import ChatPipeline
from ai_service.tokens import Tokens
from ai_service.tools import kb_tools


class ServiceInfo(BaseModel):
    service: str
    version: str
    docs: str


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging()
    setup_tracing(settings)
    tokens = Tokens(settings)
    mcp = create_mcp(settings, lambda: app.state.kb, tokens)
    mcp_app = mcp.streamable_http_app(stateless_http=True, json_response=True)
    kb_client = McpClient(settings.mcp_resource_url, tokens)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        # Blocks startup until the model is loaded (first run downloads it into the cache dir).
        kb = KnowledgeBase(
            QdrantClient(settings.qdrant_url, api_key=settings.qdrant_api_key),
            Embedder(settings.embedding_model, settings.embedding_cache_dir),
            settings.qdrant_alias,
            settings.chunk_size,
            settings.chunk_overlap,
        )
        kb.ensure_collection()
        llm = create_provider(settings)
        app.state.kb = kb
        app.state.models = load_models(settings.models_config)
        app.state.taxonomy = load_taxonomy(settings.taxonomy_config)
        app.state.chat = ChatPipeline(
            kb, llm, settings.retrieval_top_k, settings.retrieval_score_threshold
        )
        app.state.agent = Agent(
            llm, settings, lambda domains, caller: kb_tools(kb_client, caller, domains)
        )
        # Starlette does not run a mounted app's lifespan.
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="FS100 AI service", version=__version__, lifespan=lifespan)
    app.include_router(health.router)
    # Every /v1 router is included with this dependency: service token required.
    service_auth = [Depends(ServiceAuth(settings))]
    app.include_router(health.status_router, dependencies=service_auth)
    app.include_router(documents.router, dependencies=service_auth)
    app.include_router(chat.router, dependencies=service_auth)
    app.include_router(agent.router, dependencies=service_auth)
    app.include_router(catalog.router, dependencies=service_auth)

    @app.middleware("http")
    async def propagate_request_id(  # pyright: ignore[reportUnusedFunction]
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("x-request-id") or str(uuid4())
        # Not reset: the context dies with the request task, and uvicorn's access log needs it.
        request_id.set(rid)
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response

    @app.get("/", tags=["meta"])
    async def info() -> ServiceInfo:  # pyright: ignore[reportUnusedFunction]
        return ServiceInfo(service=settings.otel_service_name, version=__version__, docs="/docs")

    # Last, so `/mcp` and its RFC 9728 metadata sit at the root behind every FastAPI route.
    app.mount("/", mcp_app)
    return app


app = create_app()
