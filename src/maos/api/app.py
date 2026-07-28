"""FastAPI application factory for MAOS.

``create_app`` builds a configured FastAPI instance with the health/readiness
probes (the only unauthenticated endpoints, Req 10.6 / 9.9) and the stub
routers for the authenticated v1 surface. Keeping construction in a factory
makes the app testable and lets workers/tests build isolated instances.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from maos import __version__
from maos.api import health, knowledge, learning, routers
from maos.api.routers.context import configure_engine, context_router
from maos.api.routers.mcp_registry import configure_registry, mcp_registry_router
from maos.config.settings import Settings, get_settings
from maos.context.engine import ContextEngine
from maos.knowledge.retrieval import set_knowledge_store
from maos.knowledge.store import KnowledgeStore
from maos.mcp.registry import MCPRegistry
from maos.observability import instrument_fastapi, setup_observability, shutdown_observability

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: initialize shared resources on startup, clean up on shutdown."""
    settings: Settings = app.state.settings

    # 1. Observability (logging, tracing, metrics)
    setup_observability(
        service_name=settings.service_name,
        environment=settings.environment,
    )
    instrument_fastapi(app)

    # 2. Knowledge Store
    knowledge_store = KnowledgeStore(
        postgres_dsn=settings.postgres.dsn,
        embedding_dimensions=settings.knowledge.embedding_dimensions,
    )
    try:
        await knowledge_store.initialize()
    except Exception:
        logger.warning("KnowledgeStore initialization failed — retrieval will be unavailable")
    else:
        set_knowledge_store(knowledge_store)
    app.state.knowledge_store = knowledge_store

    # 3. MCP Registry
    mcp_registry = MCPRegistry()
    configure_registry(mcp_registry)
    app.state.mcp_registry = mcp_registry

    # 4. Context Engine
    context_engine = ContextEngine(redis_url=settings.redis.url)
    configure_engine(context_engine)
    app.state.context_engine = context_engine

    logger.info("MAOS application started successfully")

    yield

    # Shutdown: clean up resources
    logger.info("MAOS application shutting down")
    shutdown_observability()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and return a configured FastAPI application.

    Args:
        settings: Optional settings override (primarily for tests). Defaults to
            the cached environment-loaded settings.
    """
    settings = settings or get_settings()

    app = FastAPI(
        title="Multi-Agent Orchestration System (MAOS)",
        version=__version__,
        summary="Standalone async multi-agent orchestration service.",
        lifespan=lifespan,
    )

    # Stash settings for lifespan and downstream dependency wiring.
    app.state.settings = settings

    # Unauthenticated health/readiness probes (Req 10.6). No tenant data.
    app.include_router(health.router)

    # Authenticated Task-processing surface (Req 9.9). Stubs for now.
    app.include_router(routers.tasks_router)

    # Authenticated Knowledge Base management (Req 3.3, 8.5).
    app.include_router(knowledge.knowledge_router)

    # Authenticated Learning system access (Req 16.1, 16.4, 16.6).
    app.include_router(learning.learning_router)

    # MCP Server Registry management (Req 14.1, 14.6, 14.7).
    app.include_router(mcp_registry_router)

    # Context Engine API (Req 15.3, 15.4).
    app.include_router(context_router)

    return app
