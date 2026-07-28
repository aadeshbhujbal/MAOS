"""Checkpoint retention sweeper.

Periodically purges checkpoint rows from the LangGraph Postgres checkpoint
tables (``checkpoints``, ``checkpoint_writes``) that are older than the
configured retention period. Deployed as a Kubernetes CronJob (task 37.3).

Requirements: 7.10.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from maos.config.settings import Settings
from maos.memory.database import DatabasePool, create_pool

logger = logging.getLogger(__name__)

# Default sweep interval in seconds (1 hour).
_DEFAULT_SWEEP_INTERVAL_SECONDS: int = 3600

# Default retention period in seconds (7 days).
_DEFAULT_RETENTION_SECONDS: int = 7 * 24 * 3600


async def sweep_checkpoints(pool: DatabasePool, retention_seconds: int) -> int:
    """Delete checkpoint rows older than *retention_seconds* from now.

    Targets the LangGraph checkpoint tables:
    - ``checkpoints`` — main checkpoint state blobs.
    - ``checkpoint_writes`` — per-node write records.

    Parameters
    ----------
    pool:
        An open ``DatabasePool`` instance.
    retention_seconds:
        Maximum age (in seconds) of checkpoints to keep. Rows whose
        ``created_at`` (or equivalent timestamp column) is older than
        ``now() - retention_seconds`` will be deleted.

    Returns
    -------
    int
        Total number of rows deleted across both tables.
    """
    cutoff = datetime.now(tz=UTC) - timedelta(seconds=retention_seconds)

    deleted_total = 0

    # Delete from checkpoint_writes first (child/dependent rows).
    async with pool.acquire() as conn:
        cur = await conn.execute(
            "DELETE FROM checkpoint_writes WHERE created_at < %s",
            (cutoff,),
            prepare=False,
        )
        writes_deleted = cur.rowcount or 0
        deleted_total += writes_deleted

    # Delete from checkpoints (parent rows).
    async with pool.acquire() as conn:
        cur = await conn.execute(
            "DELETE FROM checkpoints WHERE created_at < %s",
            (cutoff,),
            prepare=False,
        )
        checkpoints_deleted = cur.rowcount or 0
        deleted_total += checkpoints_deleted

    logger.info(
        "Checkpoint sweep complete: deleted %d checkpoint rows and %d write rows "
        "(cutoff=%s, retention=%ds).",
        checkpoints_deleted,
        writes_deleted,
        cutoff.isoformat(),
        retention_seconds,
    )

    return deleted_total


async def run_checkpoint_sweeper(settings: Settings) -> None:
    """Scheduled entrypoint that sweeps checkpoints in a loop.

    Opens a database pool, then repeatedly calls :func:`sweep_checkpoints`
    at a configurable interval. The loop runs indefinitely until cancelled
    (e.g. by SIGTERM in the CronJob container).

    This function is intended to be deployed as a Kubernetes CronJob
    (task 37.3) or run as a long-lived async task during development.

    Parameters
    ----------
    settings:
        Application settings providing Postgres connection details and
        (optionally) retention/interval overrides via environment variables.
    """
    # Allow override via environment (MAOS_CHECKPOINT_RETENTION_SECONDS,
    # MAOS_CHECKPOINT_SWEEP_INTERVAL_SECONDS); fall back to defaults.
    retention_seconds: int = int(
        getattr(settings, "checkpoint_retention_seconds", _DEFAULT_RETENTION_SECONDS)
    )
    sweep_interval: int = int(
        getattr(settings, "checkpoint_sweep_interval_seconds", _DEFAULT_SWEEP_INTERVAL_SECONDS)
    )

    pool = create_pool(settings.postgres)
    await pool.open()

    logger.info(
        "Checkpoint sweeper started (retention=%ds, interval=%ds).",
        retention_seconds,
        sweep_interval,
    )

    try:
        while True:
            try:
                deleted = await sweep_checkpoints(pool, retention_seconds)
                logger.debug("Sweep cycle finished, deleted %d rows.", deleted)
            except Exception:
                logger.exception("Error during checkpoint sweep cycle.")
            await asyncio.sleep(sweep_interval)
    finally:
        await pool.close()
        logger.info("Checkpoint sweeper stopped; pool closed.")
