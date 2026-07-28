"""Context Engine REST API — exposes real-time project context for tenants.

Provides the authenticated ``GET /v1/context/current`` endpoint that returns
the full ``ContextState`` for the requesting tenant. Authentication is enforced
via the standard MAOS header-based auth (Bearer token, X-Tenant-Id, X-Auth-Scope).

Requirements: 15.3, 15.4, 15.6, 15.7.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from maos.api.auth import RequesterContext, get_authenticated_requester
from maos.context.engine import ContextEngine
from maos.context.models import ContextState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level engine reference (set during app startup via configure_engine)
# ---------------------------------------------------------------------------

_context_engine: ContextEngine | None = None


def configure_engine(engine: ContextEngine) -> None:
    """Configure the module-level ContextEngine reference.

    Called during FastAPI app startup to wire the engine instance into the
    router's endpoint handlers.

    Parameters
    ----------
    engine:
        The initialized ``ContextEngine`` instance.
    """
    global _context_engine
    _context_engine = engine


def _get_engine() -> ContextEngine:
    """Return the configured ContextEngine or raise 503 if not initialized."""
    if _context_engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Context Engine is not initialized.",
        )
    return _context_engine


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

context_router = APIRouter(
    prefix="/v1/context",
    tags=["context"],
    dependencies=[Depends(get_authenticated_requester)],
)


@context_router.get(
    "/current",
    response_model=ContextState,
    responses={
        401: {"description": "Missing or invalid authentication headers"},
        503: {"description": "Context Engine not initialized"},
    },
)
async def get_current_context(
    ctx: Annotated[RequesterContext, Depends(get_authenticated_requester)],
) -> ContextState:
    """Return the current ContextState for the authenticated tenant.

    Retrieves the full context state snapshot from the ContextEngine's
    Redis/Dragonfly cache. On cache miss, returns a fresh empty state.

    Requires authentication headers:
    - Authorization: Bearer <token>
    - X-Tenant-Id: <tenant_id>
    - X-Auth-Scope: context:read (or any valid scope)
    """
    engine = _get_engine()
    state = await engine.get_current(ctx.tenant_id)

    logger.debug(
        "Returned context state for tenant",
        extra={"tenant_id": ctx.tenant_id, "updated_at": str(state.updated_at)},
    )
    return state
