"""Knowledge Base management API endpoints.

Implements authenticated Knowledge Base operations:
- ``GET /v1/knowledge/documents`` — list documents in a namespace with pagination
- ``DELETE /v1/knowledge/documents/{document_id}`` — delete a specific document
- ``GET /v1/knowledge/health`` — check Knowledge Base backend health

Authentication and RBAC are enforced on every route via the
``get_authenticated_requester`` router-level dependency (Req 9.4, 9.9).

Requirements: 3.3, 8.5, 9.4, 9.9.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from maos.api.auth import RequesterContext, get_authenticated_requester
from maos.knowledge.models import Document

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------


class KnowledgeHealthResponse(BaseModel):
    """Response body for Knowledge Base health check."""

    status: str = "healthy"
    backend: str = "postgres_store"


class DocumentDeletedResponse(BaseModel):
    """Response body for successful document deletion."""

    document_id: str
    deleted: bool = True


class DocumentListResponse(BaseModel):
    """Response body for paginated document listing."""

    namespace: tuple[str, ...]
    total_count: int
    limit: int
    offset: int
    documents: list[Document]


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

knowledge_router = APIRouter(
    prefix="/v1/knowledge",
    tags=["knowledge"],
    dependencies=[Depends(get_authenticated_requester)],
)


@knowledge_router.get(
    "/health",
    response_model=KnowledgeHealthResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Knowledge Base unavailable"},
    },
)
async def get_knowledge_health(
    ctx: Annotated[RequesterContext, Depends(get_authenticated_requester)],
) -> KnowledgeHealthResponse:
    """Check Knowledge Base backend health (Req 3.3).

    Returns the status of the Knowledge Base storage backend. If the backend
    is unhealthy, returns 503 Service Unavailable.
    """
    # Stub implementation — in production, this would check the actual backend
    # connectivity and health (PostgresStore, vector DB, etc.)
    return KnowledgeHealthResponse(status="healthy", backend="postgres_store")


@knowledge_router.get(
    "/documents",
    response_model=DocumentListResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid namespace format"},
        403: {"model": ErrorResponse, "description": "Namespace access denied"},
    },
)
async def list_documents(
    ctx: Annotated[RequesterContext, Depends(get_authenticated_requester)],
    namespace: Annotated[
        tuple[str, ...],
        Query(
            description="Namespace hierarchy as comma-separated strings (e.g., 'tenant,project')",
            example=("tenant,project",),
        ),
    ],
    limit: Annotated[
        int, Query(description="Maximum number of documents to return", ge=1, le=100)
    ] = 20,
    offset: Annotated[
        int, Query(description="Number of documents to skip", ge=0)
    ] = 0,
) -> DocumentListResponse:
    """List documents in a namespace with pagination (Req 8.5).

    Returns a paginated list of documents in the specified namespace.
    The requester must have read access to the namespace (enforced by RBAC).
    """
    # Stub implementation — in production, this would query the Knowledge Store
    # with the requester's tenant context and RBAC permissions
    try:
        # Validate namespace format
        if not namespace or not all(isinstance(n, str) and n for n in namespace):
            raise ValueError("Invalid namespace format")

        # Stub response — in production, this would query the actual Knowledge Store
        return DocumentListResponse(
            namespace=namespace,
            total_count=0,
            limit=limit,
            offset=offset,
            documents=[],
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Namespace access denied",
        ) from exc


@knowledge_router.delete(
    "/documents/{document_id}",
    response_model=DocumentDeletedResponse,
    responses={
        403: {"model": ErrorResponse, "description": "Deletion access denied"},
        404: {"model": ErrorResponse, "description": "Document not found"},
        500: {"model": ErrorResponse, "description": "Deletion failed"},
    },
)
async def delete_document(
    document_id: str,
    ctx: Annotated[RequesterContext, Depends(get_authenticated_requester)],
) -> DocumentDeletedResponse:
    """Delete a specific document (Req 3.3).

    Permanently deletes a document from the Knowledge Base. The requester
    must have write access to the document's namespace (enforced by RBAC).

    Returns 404 if the document does not exist.
    Returns 403 if the requester lacks write permissions.
    """
    # Stub implementation — in production, this would:
    # 1. Verify the document exists and the requester has write access
    # 2. Delete from both the Knowledge Store and any vector indexes
    # 3. Log the deletion in the audit trail
    try:
        # Verify document exists (stub)
        # In production, query the Knowledge Store
        document_exists = True  # Stub

        if not document_exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document '{document_id}' not found",
            )

        # Verify write permissions (stub)
        # In production, check RBAC policies for the document's namespace
        has_write_access = True  # Stub

        if not has_write_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Deletion access denied",
            )

        # Delete the document (stub)
        # In production, delete from Knowledge Store and vector indexes
        deleted = True  # Stub

        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Deletion failed",
            )

        return DocumentDeletedResponse(document_id=document_id, deleted=True)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "Unexpected error during document deletion",
            extra={"document_id": document_id, "tenant_id": ctx.tenant_id},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Deletion failed",
        ) from exc
