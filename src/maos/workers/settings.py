"""Arq WorkerSettings for MAOS orchestration workers.

Defines the Arq worker configuration: Redis connection pool, job timeout,
max concurrent jobs, and the task functions the workers execute.

Workers are stateless — all durable state lives in Postgres via the
LangGraph checkpointer (Req 14.2, 14.3). Multiple worker replicas can run
concurrently behind the broker queue for horizontal scaling (TC-8).

Requirements: 14.1, 14.2, 14.3, 14.5, TC-8.
"""

from __future__ import annotations

from typing import Any, ClassVar

from arq.connections import RedisSettings as ArqRedisSettings

from maos.config.settings import get_settings
from maos.mcp.health_checker import mcp_health_check_cron
from maos.workers.tasks import process_subtask, process_task


def _parse_redis_url(url: str) -> ArqRedisSettings:
    """Parse a ``redis://host:port/db`` URL into Arq's RedisSettings."""
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


class WorkerSettings:
    """Arq WorkerSettings class consumed by ``arq worker maos.workers.settings.WorkerSettings``.

    Configures:
    - Redis connection pool from ``BrokerSettings.url``
    - Job timeout (default 600s — long-running orchestration graphs)
    - Max concurrent jobs per worker (default 10)
    - Task functions registered for execution

    Requirements: 14.1, 14.2, TC-8.
    """

    # Task functions the worker can execute
    functions: ClassVar[list[Any]] = [process_task, process_subtask]

    # Arq cron jobs — periodic background tasks (Req 14.3, 14.5)
    cron_jobs: ClassVar[list[Any]] = [mcp_health_check_cron]

    # Arq polls the queue at this interval (seconds)
    queue_read_limit: int = 50

    # Maximum concurrent jobs this worker processes
    max_jobs: int = 10

    # Job timeout — orchestration graphs may be long-running
    job_timeout: int = 600

    # Health check interval
    health_check_interval: int = 30

    @staticmethod
    def redis_settings() -> ArqRedisSettings:
        """Build Arq Redis connection settings from MAOS broker config."""
        settings = get_settings()
        return _parse_redis_url(settings.broker.url)

    @staticmethod
    async def on_startup(ctx: dict[str, Any]) -> None:
        """Worker startup hook — initialize shared resources.

        Opens the database pool and MCPRegistry, storing them in the worker
        context so that task functions and cron jobs can access them.
        """
        from maos.mcp.registry import MCPRegistry
        from maos.memory.database import create_pool

        settings = get_settings()
        pool = create_pool(settings.postgres)
        await pool.open()
        ctx["db_pool"] = pool

        # Initialize MCPRegistry for health check cron job (Req 14.3)
        ctx["mcp_registry"] = MCPRegistry()

    @staticmethod
    async def on_shutdown(ctx: dict[str, Any]) -> None:
        """Worker shutdown hook — clean up shared resources."""
        pool = ctx.get("db_pool")
        if pool is not None:
            await pool.close()
