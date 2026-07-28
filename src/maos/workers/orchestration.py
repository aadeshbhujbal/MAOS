"""Arq worker orchestration entry point for MAOS.

This module provides the top-level Arq ``WorkerSettings`` class that is
invoked by ``arq worker maos.workers.orchestration.OrchestrationWorkerSettings``.
It configures stateless workers that consume Tasks from the Redis broker queue,
load the latest Postgres checkpoint, and run the LangGraph orchestration graph.

Workers are **stateless** — all durable state lives in Postgres via the
LangGraph checkpointer (Req 14.2, 14.3). Multiple worker replicas can run
concurrently behind the broker queue for horizontal scaling (TC-8).

The worker startup hook initialises shared resources (DB pool, Redis clients)
and passes them through the Arq worker context dict so task functions can
access them without per-job connection overhead.

Requirements: 14.1, 14.2, 14.3, 14.4, TC-8.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from arq.connections import RedisSettings as ArqRedisSettings

from maos.config.settings import get_settings
from maos.workers.tasks import process_subtask, process_task

logger = logging.getLogger(__name__)


def _parse_redis_url(url: str) -> ArqRedisSettings:
    """Parse a ``redis://host:port/db`` URL into Arq's RedisSettings.

    Supports both ``redis://`` and ``rediss://`` (TLS) schemes.
    """
    # Strip scheme
    without_scheme = url.replace("redis://", "").replace("rediss://", "")

    # Split path for DB number
    if "/" in without_scheme:
        host_port, db_str = without_scheme.rsplit("/", 1)
        database = int(db_str) if db_str else 0
    else:
        host_port = without_scheme
        database = 0

    # Split host and port
    if ":" in host_port:
        host, port_str = host_port.rsplit(":", 1)
        port = int(port_str)
    else:
        host = host_port
        port = 6379

    return ArqRedisSettings(host=host, port=port, database=database)


class OrchestrationWorkerSettings:
    """Arq WorkerSettings class for MAOS orchestration workers.

    Invoked by::

        arq worker maos.workers.orchestration.OrchestrationWorkerSettings

    Configures:
    - Redis connection pool from ``BrokerSettings.url``
    - Job timeout (600s — long-running orchestration graphs)
    - Max concurrent jobs capped to ``ScalabilitySettings.global_concurrency_cap``
      divided across worker replicas (default 10 per worker)
    - Task functions: ``process_task`` and ``process_subtask``
    - Startup/shutdown hooks for shared resource lifecycle

    Workers pick up tasks from the broker queue, load the latest checkpoint
    from Postgres, and run the appropriate LangGraph orchestration graph.
    All state is in Postgres; workers are fully stateless and horizontally
    scalable (Req 14.2, TC-8).

    Requirements: 14.1, 14.2, 14.3, TC-8.
    """

    # Task functions the worker can execute
    functions: ClassVar[list[Any]] = [process_task, process_subtask]

    # Arq reads up to this many jobs per poll cycle
    queue_read_limit: int = 50

    # Maximum concurrent jobs this single worker processes. The global cap
    # is enforced by the ConcurrencyLimiter across all workers; this limits
    # local resource usage per replica.
    max_jobs: int = 10

    # Job timeout — orchestration graphs are long-running
    job_timeout: int = 600

    # Health check interval (seconds)
    health_check_interval: int = 30

    @staticmethod
    def redis_settings() -> ArqRedisSettings:
        """Build Arq Redis connection settings from MAOS broker config."""
        settings = get_settings()
        return _parse_redis_url(settings.broker.url)

    @staticmethod
    async def on_startup(ctx: dict[str, Any]) -> None:
        """Worker startup hook — initialise shared resources.

        Opens the database pool and Redis client, storing them in the worker
        context so that task functions can access them without creating
        per-job connections.
        """
        settings = get_settings()

        # Database pool for checkpointing and persistence
        from maos.memory.database import create_pool

        pool = create_pool(settings.postgres)
        await pool.open()
        ctx["db_pool"] = pool

        # Store broker URL for ConcurrencyLimiter in task functions
        ctx["redis_url"] = settings.broker.url

        logger.info(
            "Orchestration worker started",
            extra={
                "broker_url": settings.broker.url,
                "global_cap": settings.scalability.global_concurrency_cap,
                "tenant_cap": settings.scalability.tenant_concurrency_cap,
            },
        )

    @staticmethod
    async def on_shutdown(ctx: dict[str, Any]) -> None:
        """Worker shutdown hook — clean up shared resources."""
        pool = ctx.get("db_pool")
        if pool is not None:
            await pool.close()
        logger.info("Orchestration worker shut down")
