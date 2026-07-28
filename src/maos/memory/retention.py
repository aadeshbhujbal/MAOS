"""Retention sweepers for Semantic_Memory and Working_Memory checkpoints.

Provides standalone async callables that can be scheduled by Arq workers or
Kubernetes CronJobs to purge expired data from the persistence layer.

- ``sweep_semantic_memory``: removes pgvector rows past their ``retention_at``.
- ``sweep_checkpoints``: removes checkpoint rows older than the configured
  replay window.
- ``run_retention_sweep``: top-level entry point suitable for Arq workers or
  standalone script invocation.

Requirements: 7.10.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from maos.config.settings import Settings, get_settings
from maos.memory.database import DatabasePool, create_pool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

_DEFAULT_BATCH_SIZE: int = 1000
_DEFAULT_REPLAY_WINDOW_HOURS: int = 72


# ---------------------------------------------------------------------------
# Semantic Memory Sweeper
# ---------------------------------------------------------------------------


async def sweep_semantic_memory(
    pool: DatabasePool,
    batch_size: int = _DEFAULT_BATCH_SIZE,
) -> int:
    """Delete semantic_memory rows whose retention period has expired.

    Removes rows where ``retention_at < now()`` from the ``semantic_memory``
    table in batches to avoid long-running transactions. Designed to be invoked
    by Arq workers or Kubernetes CronJobs.

    Parameters
    ----------
    pool:
        An open ``DatabasePool`` instance.
    batch_size:
        Maximum number of rows to delete per batch iteration. The function
        loops until no more expired rows remain, deleting up to *batch_size*
        rows per iteration.

    Returns
    -------
    int
        Total number of rows deleted.
    """
    now = datetime.now(tz=UTC)
    total_deleted = 0

    while True:
        async with pool.acquire() as conn:
            cur = await conn.execute(
                """
                DELETE FROM semantic_memory
                WHERE id IN (
                    SELECT id FROM semantic_memory
                    WHERE retention_at < %s
                    LIMIT %s
                )
                """,
                (now, batch_size),
                prepare=False,
            )
            deleted = cur.rowcount or 0

        total_deleted += deleted

        if deleted < batch_size:
            # No more expired rows (or fewer than a full batch remain).
            break

    if total_deleted > 0:
        logger.info(
            "Semantic memory sweep complete: deleted %d expired entries (cutoff=%s).",
            total_deleted,
            now.isoformat(),
        )
    else:
        logger.debug("Semantic memory sweep: no expired entries found.")

    return total_deleted


# ---------------------------------------------------------------------------
# Checkpoint Sweeper
# ---------------------------------------------------------------------------


async def sweep_checkpoints(
    pool: DatabasePool,
    replay_window_hours: int = _DEFAULT_REPLAY_WINDOW_HOURS,
    batch_size: int = _DEFAULT_BATCH_SIZE,
) -> int:
    """Delete checkpoint rows older than the configured replay window.

    Targets the LangGraph checkpoint tables:
    - ``checkpoint_writes`` — per-node write records (deleted first).
    - ``checkpoints`` — main checkpoint state blobs.

    Parameters
    ----------
    pool:
        An open ``DatabasePool`` instance.
    replay_window_hours:
        Maximum age (in hours) of checkpoints to keep. Rows whose
        ``created_at`` is older than ``now() - replay_window_hours`` are
        deleted. Defaults to 72 hours.
    batch_size:
        Maximum number of rows to delete per batch iteration.

    Returns
    -------
    int
        Total number of rows deleted across both tables.
    """
    cutoff = datetime.now(tz=UTC) - timedelta(hours=replay_window_hours)
    total_deleted = 0

    # Delete from checkpoint_writes first (child/dependent rows).
    while True:
        async with pool.acquire() as conn:
            cur = await conn.execute(
                """
                DELETE FROM checkpoint_writes
                WHERE ctid IN (
                    SELECT ctid FROM checkpoint_writes
                    WHERE created_at < %s
                    LIMIT %s
                )
                """,
                (cutoff, batch_size),
                prepare=False,
            )
            deleted = cur.rowcount or 0

        total_deleted += deleted

        if deleted < batch_size:
            break

    # Delete from checkpoints (parent rows).
    while True:
        async with pool.acquire() as conn:
            cur = await conn.execute(
                """
                DELETE FROM checkpoints
                WHERE ctid IN (
                    SELECT ctid FROM checkpoints
                    WHERE created_at < %s
                    LIMIT %s
                )
                """,
                (cutoff, batch_size),
                prepare=False,
            )
            deleted = cur.rowcount or 0

        total_deleted += deleted

        if deleted < batch_size:
            break

    if total_deleted > 0:
        logger.info(
            "Checkpoint sweep complete: deleted %d rows (cutoff=%s, window=%dh).",
            total_deleted,
            cutoff.isoformat(),
            replay_window_hours,
        )
    else:
        logger.debug(
            "Checkpoint sweep: no expired rows found (window=%dh).",
            replay_window_hours,
        )

    return total_deleted


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


async def run_retention_sweep(
    settings: Settings | None = None,
    *,
    replay_window_hours: int = _DEFAULT_REPLAY_WINDOW_HOURS,
    batch_size: int = _DEFAULT_BATCH_SIZE,
) -> dict[str, int]:
    """Run both retention sweepers: semantic memory and checkpoints.

    Creates a database pool, executes both sweepers, closes the pool, and
    returns the deletion counts. Suitable for invocation by Arq workers or as
    a standalone script (via ``python -m maos.memory.retention``).

    Parameters
    ----------
    settings:
        Application settings. If ``None``, loads from the environment via
        :func:`~maos.config.settings.get_settings`.
    replay_window_hours:
        Checkpoint replay window in hours (default 72).
    batch_size:
        Batch size for both sweepers (default 1000).

    Returns
    -------
    dict[str, int]
        A mapping with keys ``"semantic_memory_deleted"`` and
        ``"checkpoints_deleted"`` containing the respective row counts.
    """
    if settings is None:
        settings = get_settings()

    pool = create_pool(settings.postgres)
    await pool.open()

    try:
        semantic_deleted = await sweep_semantic_memory(pool, batch_size=batch_size)
        checkpoints_deleted = await sweep_checkpoints(
            pool,
            replay_window_hours=replay_window_hours,
            batch_size=batch_size,
        )
    finally:
        await pool.close()

    logger.info(
        "Retention sweep finished: semantic_memory=%d, checkpoints=%d.",
        semantic_deleted,
        checkpoints_deleted,
    )

    return {
        "semantic_memory_deleted": semantic_deleted,
        "checkpoints_deleted": checkpoints_deleted,
    }


# ---------------------------------------------------------------------------
# Standalone script support
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(run_retention_sweep())
