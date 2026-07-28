"""Learning API endpoints for accessing learned patterns and conventions.

Implements authenticated Learning operations:
- ``GET /v1/learning/patterns`` — list learned patterns with pagination
- ``GET /v1/learning/conventions`` — list team coding conventions
- ``GET /v1/learning/history`` — retrieve learning history records
- ``POST /v1/learning/trigger`` — manually trigger learning for a completed task

Authentication and RBAC are enforced on every route via the
``get_authenticated_requester`` router-level dependency (Req 9.4, 9.9).

Requirements: 3.3, 9.4, 9.9, 16.1, 16.4, 16.6.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from maos.api.auth import RequesterContext, get_authenticated_requester
from maos.learning.models import Convention, LearnedPattern, LearningRecord

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------


class LearningHealthResponse(BaseModel):
    """Response body for Learning system health check."""

    status: str = "healthy"
    system: str = "continuous_learning"


class PatternListResponse(BaseModel):
    """Response body for paginated pattern listing."""

    total_count: int
    limit: int
    offset: int
    patterns: list[LearnedPattern]


class ConventionListResponse(BaseModel):
    """Response body for convention listing."""

    total_count: int
    conventions: list[Convention]


class LearningHistoryResponse(BaseModel):
    """Response body for learning history."""

    total_count: int
    limit: int
    offset: int
    records: list[LearningRecord]


class TriggerLearningRequest(BaseModel):
    """Request body for manual learning trigger."""

    task_id: str
    tenant_id: str
    agent_role: str
    description: str


class TriggerLearningResponse(BaseModel):
    """Response body for learning trigger."""

    task_id: str
    status: str
    patterns_stored: int = 0
    graph_nodes_added: int = 0
    embeddings_updated: int = 0
    conventions_updated: int = 0


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

learning_router = APIRouter(
    prefix="/v1/learning",
    tags=["learning"],
    dependencies=[Depends(get_authenticated_requester)],
)


@learning_router.get(
    "/health",
    response_model=LearningHealthResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Learning system unavailable"},
    },
)
async def get_learning_health(
    ctx: Annotated[RequesterContext, Depends(get_authenticated_requester)],
) -> LearningHealthResponse:
    """Check Learning system health (Req 3.3).

    Returns the status of the Learning system pipeline. If the system
    is unhealthy, returns 503 Service Unavailable.
    """
    # Stub implementation — in production, this would check the actual
    # LearningSystem connectivity and health
    return LearningHealthResponse(status="healthy", system="continuous_learning")


@learning_router.get(
    "/patterns",
    response_model=PatternListResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request parameters"},
        403: {"model": ErrorResponse, "description": "Access denied"},
    },
)
async def list_patterns(
    ctx: Annotated[RequesterContext, Depends(get_authenticated_requester)],
    pattern_type: Annotated[
        str | None,
        Query(
            description=(
                "Filter by pattern type "
                "(architecture_decision, coding_convention, error_fix)"
            ),
        ),
    ] = None,
    limit: Annotated[
        int, Query(description="Maximum number of patterns to return", ge=1, le=100)
    ] = 20,
    offset: Annotated[
        int, Query(description="Number of patterns to skip", ge=0)
    ] = 0,
) -> PatternListResponse:
    """List learned patterns with pagination (Req 16.1, 16.2).

    Returns learned patterns for the requester's tenant. Patterns can be
    filtered by type (architecture decisions, coding conventions, error fixes).
    """
    # Stub implementation — in production, this would:
    # 1. Query the Knowledge Base for patterns in the tenant's learning namespace
    # 2. Filter by pattern_type if provided
    # 3. Apply pagination
    try:
        # Stub: return empty list for now
        # In production, use self._knowledge_store.list(namespace, limit, offset)
        return PatternListResponse(
            total_count=0,
            limit=limit,
            offset=offset,
            patterns=[],
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        ) from exc
    except Exception as exc:
        logger.exception(
            "Failed to list patterns",
            extra={"tenant_id": ctx.tenant_id},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve patterns",
        ) from exc


@learning_router.get(
    "/conventions",
    response_model=ConventionListResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request parameters"},
        403: {"model": ErrorResponse, "description": "Access denied"},
    },
)
async def list_conventions(
    ctx: Annotated[RequesterContext, Depends(get_authenticated_requester)],
    category: Annotated[
        str | None,
        Query(
            description=(
                "Filter by convention category "
                "(naming, import_style, error_handling)"
            ),
        ),
    ] = None,
    limit: Annotated[
        int, Query(description="Maximum number of conventions to return", ge=1, le=100)
    ] = 20,
) -> ConventionListResponse:
    """List team coding conventions (Req 16.4).

    Returns coding conventions observed and tracked for the requester's tenant.
    Conventions can be filtered by category (naming, import style, error handling, etc.).
    """
    # Stub implementation — in production, this would:
    # 1. Query the Knowledge Base for conventions in the tenant's conventions namespace
    # 2. Filter by category if provided
    # 3. Apply limit
    try:
        # Stub: return empty list for now
        # In production, use self._knowledge_store.list(namespace, limit, 0)
        return ConventionListResponse(
            total_count=0,
            conventions=[],
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        ) from exc
    except Exception as exc:
        logger.exception(
            "Failed to list conventions",
            extra={"tenant_id": ctx.tenant_id},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve conventions",
        ) from exc


@learning_router.get(
    "/history",
    response_model=LearningHistoryResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request parameters"},
        403: {"model": ErrorResponse, "description": "Access denied"},
    },
)
async def get_history(
    ctx: Annotated[RequesterContext, Depends(get_authenticated_requester)],
    limit: Annotated[
        int, Query(description="Maximum number of records to return", ge=1, le=100)
    ] = 20,
    offset: Annotated[
        int, Query(description="Number of records to skip", ge=0)
    ] = 0,
) -> LearningHistoryResponse:
    """Retrieve learning history records (Req 16.6).

    Returns audit records of what was learned from completed tasks for the
    requester's tenant. Records include patterns extracted, graph nodes added,
    embeddings updated, and conventions tracked.
    """
    # Stub implementation — in production, this would:
    # 1. Query the Knowledge Base for learning history in the tenant's history namespace
    # 2. Apply pagination
    # 3. Return LearningRecord instances
    try:
        # Stub: return empty list for now
        # In production, use LearningSystem.get_history(tenant_id, limit, offset)
        return LearningHistoryResponse(
            total_count=0,
            limit=limit,
            offset=offset,
            records=[],
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        ) from exc
    except Exception as exc:
        logger.exception(
            "Failed to retrieve learning history",
            extra={"tenant_id": ctx.tenant_id},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve learning history",
        ) from exc


@learning_router.post(
    "/trigger",
    response_model=TriggerLearningResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request body"},
        403: {"model": ErrorResponse, "description": "Trigger access denied"},
        500: {"model": ErrorResponse, "description": "Learning pipeline failed"},
    },
)
async def trigger_learning(
    request: TriggerLearningRequest,
    ctx: Annotated[RequesterContext, Depends(get_authenticated_requester)],
) -> TriggerLearningResponse:
    """Manually trigger learning for a completed task.

    This endpoint allows administrators to re-run the learning pipeline for a
    specific task. This is useful for:
    - Re-extracting patterns after a learning algorithm update
    - Updating knowledge stores after a manual correction
    - Debugging learning issues

    The requester must have write permissions for the tenant's learning namespace.
    """
    # Verify the requester has permission to trigger learning for this tenant
    has_admin_scope = "admin" in ctx.auth_scope or "system" in ctx.auth_scope
    if request.tenant_id != ctx.tenant_id and not has_admin_scope:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Trigger access denied: insufficient permissions",
        )

    try:
        # Stub implementation — in production, this would:
        # 1. Reconstruct the TaskResult from stored data
        # 2. Invoke LearningSystem.on_task_complete(task_id, result)
        # 3. Return the learning outcome

        return TriggerLearningResponse(
            task_id=request.task_id,
            status="triggered",
            patterns_stored=0,
            graph_nodes_added=0,
            embeddings_updated=0,
            conventions_updated=0,
        )
    except Exception as exc:
        logger.exception(
            "Learning pipeline trigger failed",
            extra={
                "task_id": request.task_id,
                "tenant_id": request.tenant_id,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Learning pipeline failed",
        ) from exc
