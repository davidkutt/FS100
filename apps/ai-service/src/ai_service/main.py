import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Request, Response
from pydantic import BaseModel
from qdrant_client import QdrantClient

from ai_service import __version__
from ai_service.agent import Agent
from ai_service.api import agent, catalog, chat, documents, health, jobs
from ai_service.catalog import McpServers, load_models, load_servers, load_taxonomy
from ai_service.contextual import Contextualizer
from ai_service.core.auth import Caller, ServiceAuth
from ai_service.core.logging import request_id, setup_logging
from ai_service.core.settings import Settings, get_settings
from ai_service.core.tracing import setup_tracing
from ai_service.embeddings import Embedder, load_reranker
from ai_service.jobs import Deps, open_jobs, run_worker
from ai_service.knowledge_base import Domain, KnowledgeBase
from ai_service.llm import create_provider
from ai_service.mcp_client import McpClient
from ai_service.mcp_server import create_mcp
from ai_service.query import QueryTransformer
from ai_service.rag import ChatPipeline
from ai_service.routing import create_router
from ai_service.tokens import Tokens
from ai_service.tools import ToolSpec, kb_tools, registry, sandbox_tools, web_tools


class ServiceInfo(BaseModel):
    service: str
    version: str
    docs: str


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging()
    setup_tracing(settings)
    tokens = Tokens(settings)
    mcp = create_mcp(settings, lambda: app.state.kb, tokens, lambda: app.state.query)
    mcp_app = mcp.streamable_http_app(stateless_http=True, json_response=True)
    kb_client = McpClient(settings.mcp_resource_url)
    servers = McpServers(load_servers(settings.mcp_servers_config))
    native = sandbox_tools(settings) + web_tools(settings)

    async def tools(domains: list[Domain] | None, caller: Caller) -> list[ToolSpec[Any]]:
        # Native and own tools first: they win a name clash (D30).
        return registry(kb_tools(kb_client, tokens, caller, domains), native, await servers.tools())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        taxonomy = load_taxonomy(settings.taxonomy_config)
        # Blocks startup until the model is loaded (first run downloads it into the cache dir).
        kb = KnowledgeBase(
            QdrantClient(settings.qdrant_url, api_key=settings.qdrant_api_key),
            Embedder(settings.embedding_model, settings.embedding_cache_dir),
            settings.qdrant_alias,
            settings.chunk_size,
            settings.chunk_overlap,
            settings.sparse_model,
            settings.parent_size,
            reranker=load_reranker(
                settings.reranker_model, settings.rerank_candidates, settings.embedding_cache_dir
            ),
            topics=taxonomy.topics(),
            threshold=settings.retrieval_score_threshold,
        )
        kb.ensure_collection()
        llm = create_provider(settings)
        app.state.kb = kb
        app.state.query = QueryTransformer(llm, settings.query_model or None)
        app.state.models = load_models(settings.models_config)
        app.state.taxonomy = taxonomy
        app.state.chat = ChatPipeline(
            kb, llm, settings.retrieval_top_k, settings.retrieval_score_threshold
        )
        router = create_router(settings, kb.embedder, taxonomy, llm)
        app.state.agent = Agent(llm, settings, tools, router)
        # Starlette does not run a mounted app's lifespan.
        async with open_jobs(settings.ai_database_url) as (queue, store), mcp.session_manager.run():
            app.state.jobs, app.state.store = queue, store
            golden = Path(settings.golden_dataset)
            contextualizer = Contextualizer(
                llm,
                settings.contextual_model or settings.llm_model,  # named: it is in the stored key
                taxonomy.topics(),
                settings.contextual_domains,
                settings.contextual_max_cost_usd_per_doc,
                store,
            )
            threshold = settings.retrieval_score_threshold
            app.state.deps = deps = Deps(kb, store, golden, threshold, contextualizer)
            worker = settings.jobs_inprocess_worker and asyncio.create_task(run_worker(queue, deps))
            yield
            if worker:
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker

    app = FastAPI(title="Grove AI service", version=__version__, lifespan=lifespan)
    app.include_router(health.router)
    # Every /v1 router is included with this dependency: service token required.
    service_auth = [Depends(ServiceAuth(settings))]
    app.include_router(health.status_router, dependencies=service_auth)
    app.include_router(documents.router, dependencies=service_auth)
    app.include_router(chat.router, dependencies=service_auth)
    app.include_router(agent.router, dependencies=service_auth)
    app.include_router(catalog.router, dependencies=service_auth)
    app.include_router(jobs.router, dependencies=service_auth)
    app.include_router(jobs.admin, dependencies=service_auth)

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
