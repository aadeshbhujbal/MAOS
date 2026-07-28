"""Arq task functions for MAOS orchestration workers.

Each task function loads state from the Postgres checkpointer, resumes from
the latest checkpoint, and runs the appropriate LangGraph orchestration graph.
Workers are stateless — all durable state is in Postgres (Req 14.2, 14.3).

Functions:
- ``process_task`` — runs the Root Orchestrator graph for a top-level Task.
- ``process_subtask`` — runs a Sub-Orchestrator graph for a Subtask.

Requirements: 14.1, 14.2, 14.3, TC-8.
"""

from __future__ import annotations

import logging
from typing import Any

from maos.workers.concurrency import ConcurrencyLimiter

logger = logging.getLogger(__name__)


async def process_task(ctx: dict[str, Any], task_id: str) -> dict[str, Any]:
    """Process a top-level Task via the Root Orchestrator LangGraph graph.

    Steps:
    1. Acquire a concurrency slot (global + per-tenant).
    2. Load the Task from the database.
    3. Load the latest checkpoint (Working_Memory) if any.
    4. Run the Root Orchestrator graph from the checkpoint.
    5. Release the concurrency slot on completion.

    The worker context ``ctx`` is populated by ``WorkerSettings.on_startup``
    with shared resources (db_pool, etc.).

    Parameters
    ----------
    ctx:
        Arq worker context dict (contains ``db_pool`` and other shared state).
    task_id:
        The unique identifier of the Task to process.

    Returns
    -------
    dict:
        A summary of the execution result including task_id and final state.

    Requirements: 14.1, 14.2, 14.3.
    """
    logger.info("process_task started", extra={"task_id": task_id})

    db_pool = ctx.get("db_pool")
    if db_pool is None:
        raise RuntimeError("Worker context missing 'db_pool'. Was on_startup called?")

    # Load the task record from the database
    task_row = await db_pool.fetch_one(
        "SELECT task_id, tenant_id, mode, state FROM task WHERE task_id = %(task_id)s",
        {"task_id": task_id},
    )
    if task_row is None:
        logger.error("Task not found", extra={"task_id": task_id})
        return {"task_id": task_id, "error": "task_not_found"}

    tenant_id: str = task_row["tenant_id"]

    # Acquire concurrency slot
    redis_url: str = ctx.get("redis_url", "redis://localhost:6379/1")
    limiter = ConcurrencyLimiter(redis_url=redis_url)

    acquired = await limiter.acquire(tenant_id=tenant_id)
    if not acquired:
        # Should not normally happen since backpressure guards enqueue,
        # but handle gracefully — job will be retried by Arq.
        logger.warning(
            "Concurrency limit reached during execution",
            extra={"task_id": task_id, "tenant_id": tenant_id},
        )
        return {"task_id": task_id, "error": "concurrency_limit_reached", "retry": True}

    try:
        # Load the latest checkpoint for resumption (Req 14.3, 7.6, 7.7)
        checkpoint_row = await db_pool.fetch_one(
            "SELECT state_data FROM checkpoints "
            "WHERE task_id = %(task_id)s ORDER BY created_at DESC LIMIT 1",
            {"task_id": task_id},
        )

        resume_state = checkpoint_row["state_data"] if checkpoint_row else None

        # Execute the Root Orchestrator graph.
        # The actual LangGraph execution is handled by the graphs module.
        # Here we invoke it with the checkpoint state for resumption.
        from maos.graphs.root_orchestrator import run_root_orchestrator

        result = await run_root_orchestrator(
            task_id=task_id,
            tenant_id=tenant_id,
            resume_state=resume_state,
            db_pool=db_pool,
        )

        logger.info(
            "process_task completed",
            extra={"task_id": task_id, "result_state": result.get("state")},
        )
        return {"task_id": task_id, "state": result.get("state", "completed")}

    finally:
        await limiter.release(tenant_id=tenant_id)


async def process_subtask(ctx: dict[str, Any], subtask_id: str) -> dict[str, Any]:
    """Process a Subtask via the appropriate Sub-Orchestrator LangGraph graph.

    Steps:
    1. Acquire a concurrency slot (global + per-tenant).
    2. Load the Subtask from the database.
    3. Load the latest checkpoint if any.
    4. Run the Sub-Orchestrator graph for the Subtask's platform_system.
    5. Release the concurrency slot on completion.

    Parameters
    ----------
    ctx:
        Arq worker context dict.
    subtask_id:
        The unique identifier of the Subtask to process.

    Returns
    -------
    dict:
        A summary of the execution result including subtask_id and final state.

    Requirements: 14.1, 14.2, 14.3.
    """
    logger.info("process_subtask started", extra={"subtask_id": subtask_id})

    db_pool = ctx.get("db_pool")
    if db_pool is None:
        raise RuntimeError("Worker context missing 'db_pool'. Was on_startup called?")

    # Load the subtask record
    subtask_row = await db_pool.fetch_one(
        "SELECT subtask_id, task_id, tenant_id, platform_system, mode, state "
        "FROM subtask WHERE subtask_id = %(subtask_id)s",
        {"subtask_id": subtask_id},
    )
    if subtask_row is None:
        logger.error("Subtask not found", extra={"subtask_id": subtask_id})
        return {"subtask_id": subtask_id, "error": "subtask_not_found"}

    tenant_id: str = subtask_row["tenant_id"]
    platform_system: str = subtask_row["platform_system"]

    # Acquire concurrency slot
    redis_url: str = ctx.get("redis_url", "redis://localhost:6379/1")
    limiter = ConcurrencyLimiter(redis_url=redis_url)

    acquired = await limiter.acquire(tenant_id=tenant_id)
    if not acquired:
        logger.warning(
            "Concurrency limit reached during subtask execution",
            extra={"subtask_id": subtask_id, "tenant_id": tenant_id},
        )
        return {"subtask_id": subtask_id, "error": "concurrency_limit_reached", "retry": True}

    try:
        # Load checkpoint for resumption
        checkpoint_row = await db_pool.fetch_one(
            "SELECT state_data FROM checkpoints "
            "WHERE task_id = %(task_id)s AND subtask_id = %(subtask_id)s "
            "ORDER BY created_at DESC LIMIT 1",
            {"task_id": subtask_row["task_id"], "subtask_id": subtask_id},
        )

        resume_state = checkpoint_row["state_data"] if checkpoint_row else None

        # Execute the Sub-Orchestrator graph for this platform
        from maos.graphs.sub_orchestrator import run_sub_orchestrator

        result = await run_sub_orchestrator(
            subtask_id=subtask_id,
            task_id=subtask_row["task_id"],
            tenant_id=tenant_id,
            platform_system=platform_system,
            resume_state=resume_state,
            db_pool=db_pool,
        )

        logger.info(
            "process_subtask completed",
            extra={"subtask_id": subtask_id, "result_state": result.get("state")},
        )
        return {"subtask_id": subtask_id, "state": result.get("state", "completed")}

    finally:
        await limiter.release(tenant_id=tenant_id)
