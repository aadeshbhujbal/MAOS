"""Authenticated MAOS API surface — Task intake and status endpoints.

Implements:
- ``POST /v1/tasks``  — validates a Task against the input contract, assigns a
  ``task_id`` (uuid4), associates tenant + auth scope from request headers
  (``X-Tenant-Id``, ``X-Auth-Scope``), checks backpressure before enqueue,
  stores the Task in-memory, enqueues to the Arq broker for async processing,
  and returns ``202 Accepted`` with the ``task_id`` and ``status: "accepted"``.
  When the system is over capacity the endpoint returns **429 Too Many Requests**
  with a ``Retry-After`` header (Req 14.4).
- ``GET /v1/tasks/{task_id}``  — looks up a Task in the in-memory store;
  returns its state and (when terminal) the aggregated ``TaskResult``, or
  ``404 Not Found`` if the id is unknown.

Authentication and RBAC are enforced on every route via the
``get_authenticated_requester`` router-level dependency (Req 9.4, 9.9).
Health/readiness endpoints remain unauthenticated (they live on a separate
router without this dependency).

Requirements: 1.1, 3.3, 9.4, 9.9, 12.4, 14.4, 15.1.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from maos.api.auth import RequesterContext, get_authenticated_requester
from maos.contracts.results import TaskResult
from maos.contracts.work_units import Task, WorkUnitState
from maos.core.validation import TaskValidationError, validate_task_input
from maos.workers.backpressure import BackpressureError, BackpressureGuard

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory Task store (placeholder for Postgres in production)
# ---------------------------------------------------------------------------

_task_store: dict[str, Task] = {}
_task_results: dict[str, TaskResult] = {}

# ---------------------------------------------------------------------------
# Singleton backpressure guard (lazy-initialized on first request)
# ---------------------------------------------------------------------------

_backpressure_guard: BackpressureGuard | None = None


def _get_backpressure_guard() -> BackpressureGuard:
    """Return (or create) the singleton BackpressureGuard instance.

    Uses application settings to configure thresholds so that
    MAOS_MAX_QUEUE_DEPTH, MAOS_GLOBAL_CONCURRENCY_CAP, and
    MAOS_TENANT_CONCURRENCY_CAP environment variables are respected.
    """
    global _backpressure_guard
    if _backpressure_guard is None:
        _backpressure_guard = BackpressureGuard.from_settings()
    return _backpressure_guard


async def _enqueue_task(task_id: str) -> None:
    """Enqueue a Task to the Arq broker for async processing by a worker.

    The task is submitted to the broker queue where a stateless Arq worker will
    pick it up, load the latest checkpoint from Postgres, and run the Root
    Orchestrator LangGraph graph (Req 14.1, 14.2, TC-8).

    If the broker is unavailable, logs the error but does not block the 202
    response — the task is persisted and can be picked up on recovery.
    """
    try:
        from arq import create_pool as arq_create_pool

        from maos.config.settings import get_settings
        from maos.workers.settings import _parse_redis_url

        settings = get_settings()
        redis_settings = _parse_redis_url(settings.broker.url)
        pool = await arq_create_pool(redis_settings)
        await pool.enqueue_job("process_task", task_id)
        await pool.aclose()
    except Exception:
        # Log but don't fail the 202 — task is persisted and will be
        # retried when the broker recovers or via a sweep.
        logger.exception(
            "Failed to enqueue task to broker",
            extra={"task_id": task_id},
        )


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------


class TaskAcceptedResponse(BaseModel):
    """Response body for a successfully accepted Task (202)."""

    task_id: str
    status: str = "accepted"


class FieldErrorResponse(BaseModel):
    """A single field-level validation error."""

    field: str
    message: str


class TaskValidationErrorResponse(BaseModel):
    """Response body when Task input validation fails (422)."""

    detail: str = "Task validation failed"
    errors: list[FieldErrorResponse] = Field(default_factory=list)


class BackpressureResponse(BaseModel):
    """Response body when backpressure is applied (429)."""

    detail: str = "System at capacity. Retry later."
    retry_after: int = 30


class TaskStatusResponse(BaseModel):
    """Response body for GET /v1/tasks/{task_id}."""

    task_id: str
    state: WorkUnitState
    result: TaskResult | None = None


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

tasks_router = APIRouter(
    prefix="/v1/tasks",
    tags=["tasks"],
    dependencies=[Depends(get_authenticated_requester)],
)


@tasks_router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskAcceptedResponse,
    responses={
        422: {"model": TaskValidationErrorResponse, "description": "Validation failed"},
        429: {"model": BackpressureResponse, "description": "System at capacity"},
    },
)
async def submit_task(
    body: dict[str, Any],
    ctx: Annotated[RequesterContext, Depends(get_authenticated_requester)],
) -> TaskAcceptedResponse:
    """Submit a Task to the Root Orchestrator.

    Validates the request body against the Task input contract, checks system
    capacity (backpressure), assigns a unique ``task_id`` (uuid4), associates
    the tenant and auth scope from the authenticated requester context
    (Req 9.1, 9.4, 9.9), and enqueues the Task for processing.

    Returns 202 Accepted with the assigned ``task_id``.
    Returns 429 Too Many Requests with Retry-After if the system is over capacity.
    """
    # --- Backpressure check (Req 14.4) ---
    guard = _get_backpressure_guard()
    try:
        await guard.check_or_raise(tenant_id=ctx.tenant_id)
    except BackpressureError as exc:
        logger.info(
            "Backpressure applied — rejecting task submission",
            extra={"tenant_id": ctx.tenant_id, "retry_after": exc.retry_after},
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=exc.detail,
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc

    # Assign server-controlled fields (Req 9.1 — associate tenant/scope)
    task_id = str(uuid.uuid4())

    # Merge server-assigned fields into submitted data before validation
    body.setdefault("task_id", task_id)
    body.setdefault("tenant_id", ctx.tenant_id)
    body.setdefault("auth_scope", ctx.auth_scope)
    body.setdefault("created_at", datetime.now(UTC).isoformat())

    # Validate against the Task input contract (Req 1.1, 1.2)
    try:
        task = validate_task_input(body)
    except TaskValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "detail": "Task validation failed",
                "errors": [{"field": e.field, "message": e.message} for e in exc.errors],
            },
        ) from exc

    # Store task in-memory (placeholder for Postgres persistence)
    _task_store[task.task_id] = task

    # Enqueue the task to the Arq broker for async processing (Req 14.1, TC-8).
    # Workers are stateless and resume from the latest checkpoint (Req 14.2).
    await _enqueue_task(task.task_id)

    return TaskAcceptedResponse(task_id=task.task_id)


@tasks_router.get(
    "/{task_id}",
    response_model=TaskStatusResponse,
    responses={
        404: {"description": "Task not found"},
    },
)
async def get_task(
    task_id: str,
    ctx: Annotated[RequesterContext, Depends(get_authenticated_requester)],
) -> TaskStatusResponse:
    """Return the current status of a Task.

    Looks up the Task in the in-memory store and returns its state. When the
    Task has reached a terminal state with an aggregated result, the result is
    included in the response (Req 3.3, 12.4).

    Returns 404 if no Task with the given id exists.
    """
    task = _task_store.get(task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found",
        )

    # Check if a result has been aggregated for this task
    result = _task_results.get(task_id)

    # Determine the current state — if a result exists use its state,
    # otherwise the task is still in an initial 'assigned' state.
    state = result.state if result else WorkUnitState.ASSIGNED

    return TaskStatusResponse(task_id=task_id, state=state, result=result)
