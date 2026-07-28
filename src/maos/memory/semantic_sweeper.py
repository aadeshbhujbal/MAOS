"""Semantic_Memory retention sweeper.

Periodically purges expired rows from the ``semantic_memory`` pgvector table
where ``retention_at < now()``. Deployed as a Kubernetes CronJob or invoked
by an Arq worker.

Requirements: 7.10.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from maos.config.settings import Settings
from maos.memory.database import DatabasePool, create_pool

logger = logging.getLogger(__name__)

# Default sweep interval in seconds (1 hour).
_DEFAULT_SWEEP_INTERVAL_SECONDS: int = 3600


async def sweep_semantic_memory(pool: DatabasePool) -> int:
    """Delete semantic_memory rows whose retention period has expired.

    Removes all rows where ``retention_at < now()`` from the
    ``semantic_memory`` table.

    Parameters
    ----------
    pool:
        An open ``DatabasePool`` instance.

    Returns
    -------
    int
        Number of rows deleted.
    """
    now = datetime.now(tz=UTC)

    async with pool.acquire() as conn:
        cur = await conn.execute(
            "DELETE FROM semantic_memory WHERE retention_at < %s",
            (now,),
            prepare=False,
        )
        deleted = cur.rowcount or 0

    logger.info(
        "Semantic memory sweep complete: deleted %d expired entries (cutoff=%s).",
        deleted,
        now.isoformat(),
    )

    return deleted


async def run_semantic_memory_sweeper(settings: Settings) -> None:
    """Scheduled entrypoint that sweeps expired semantic memory entries in a loop.

    Opens a database pool, then repeatedly calls :func:`sweep_semantic_memory`
    at a configurable interval. The loop runs indefinitely until cancelled
    (e.g. by SIGTERM in the CronJob container).

    This function is intended to be deployed as a Kubernetes CronJob or run
    as an Arq worker task.

    Parameters
    ----------
    settings:
        Application settings providing Postgres connection details and
        (optionally) sweep interval overrides via environment variables.
    """
    sweep_interval: int = int(
        getattr(
            settings,
            "semantic_memory_sweep_interval_seconds",
            _DEFAULT_SWEEP_INTERVAL_SECONDS,
        )
    )

    pool = create_pool(settings.postgres)
    await pool.open()

    logger.info(
        "Semantic memory sweeper started (interval=%ds).",
        sweep_interval,
    )

    try:
        while True:
            try:
                deleted = await sweep_semantic_memory(pool)
                logger.debug("Semantic memory sweep cycle finished, deleted %d rows.", deleted)
            except Exception:
                logger.exception("Error during semantic memory sweep cycle.")
            await asyncio.sleep(sweep_interval)
    finally:
        await pool.close()
        logger.info("Semantic memory sweeper stopped; pool closed.")
