"""MCP Server Registry REST API — dynamic registration, listing, and management.

Provides authenticated endpoints for managing MCP servers in the platform:

- ``POST /v1/mcp/servers`` — Register a new MCP server (409 on duplicate)
- ``GET /v1/mcp/servers`` — List all servers with health status
- ``GET /v1/mcp/servers/{name}`` — Get server details
- ``DELETE /v1/mcp/servers/{name}`` — Deregister a server
- ``POST /v1/mcp/servers/{name}/rotate-credentials`` — Rotate server credentials

Authentication is enforced via the standard MAOS header-based auth
(Bearer token, X-Tenant-Id, X-Auth-Scope).

Requirements: 14.1, 14.6, 14.7.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from maos.api.auth import RequesterContext, get_authenticated_requester
from maos.mcp.models import MCPServerRecord
from maos.mcp.registry import DuplicateServerError, MCPRegistry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level registry reference (set during app startup via configure_registry)
# ---------------------------------------------------------------------------

_mcp_registry: MCPRegistry | None = None


def configure_registry(registry: MCPRegistry) -> None:
    """Configure the module-level MCPRegistry reference.

    Called during FastAPI app startup to wire the registry instance into the
    router's endpoint handlers.

    Parameters
    ----------
    registry:
        The initialized ``MCPRegistry`` instance.
    """
    global _mcp_registry
    _mcp_registry = registry


def _get_registry() -> MCPRegistry:
    """Return the configured MCPRegistry or raise 503 if not initialized."""
    if _mcp_registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MCP Registry is not initialized.",
        )
    return _mcp_registry


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------


class RegisterServerRequest(BaseModel):
    """Request body for registering a new MCP server."""

    name: str = Field(..., min_length=1, description="Unique server name")
    endpoint_url: str = Field(..., min_length=1, description="Server endpoint URL")
    supported_tools: list[str] = Field(
        default_factory=list, description="List of tool names this server provides"
    )
    auth_method: str = Field(
        default="none", description="Authentication method: oauth2, api_key, mTLS, none"
    )
    access_tier: str = Field(default="read", description="Access tier: read, read_write, admin")
    fallback_server: str | None = Field(
        default=None, description="Name of fallback server if this one is unavailable"
    )


class RegisterServerResponse(BaseModel):
    """Response body after successful server registration."""

    name: str
    endpoint_url: str
    status: str = "registered"
    registered_at: datetime


class ServerListResponse(BaseModel):
    """Response body for listing all MCP servers."""

    servers: list[MCPServerRecord]
    total: int


class RotateCredentialsRequest(BaseModel):
    """Request body for rotating server credentials."""

    credentials: dict[str, str] = Field(
        ..., description="New credential payload (e.g., API key, OAuth tokens)"
    )


class RotateCredentialsResponse(BaseModel):
    """Response body after successful credential rotation."""

    name: str
    status: str = "rotated"
    message: str = "Credentials rotated successfully. No restart required."


class ErrorResponse(BaseModel):
    """Standard error response body."""

    detail: str


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

mcp_registry_router = APIRouter(
    prefix="/v1/mcp/servers",
    tags=["mcp-registry"],
    dependencies=[Depends(get_authenticated_requester)],
)


@mcp_registry_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=RegisterServerResponse,
    responses={
        409: {"model": ErrorResponse, "description": "Server with this name already exists"},
        503: {"model": ErrorResponse, "description": "MCP Registry not initialized"},
    },
)
async def register_server(
    body: RegisterServerRequest,
    ctx: Annotated[RequesterContext, Depends(get_authenticated_requester)],
) -> RegisterServerResponse:
    """Register a new MCP server in the registry.

    Creates a new server record with the provided configuration. Rejects
    duplicate names with HTTP 409 Conflict (Req 14.1).

    Requires authentication headers:
    - Authorization: Bearer <token>
    - X-Tenant-Id: <tenant_id>
    - X-Auth-Scope: mcp:write (or any valid scope)
    """
    registry = _get_registry()
    now = datetime.now(tz=UTC)

    server_record = MCPServerRecord(
        name=body.name,
        endpoint_url=body.endpoint_url,
        supported_tools=body.supported_tools,
        auth_method=body.auth_method,  # type: ignore[arg-type]
        access_tier=body.access_tier,  # type: ignore[arg-type]
        fallback_server=body.fallback_server,
        registered_at=now,
    )

    try:
        await registry.register(server_record)
    except DuplicateServerError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    logger.info(
        "MCP server registered via API",
        extra={"server_name": body.name, "tenant_id": ctx.tenant_id},
    )

    return RegisterServerResponse(
        name=server_record.name,
        endpoint_url=server_record.endpoint_url,
        registered_at=now,
    )


@mcp_registry_router.get(
    "",
    response_model=ServerListResponse,
    responses={
        503: {"model": ErrorResponse, "description": "MCP Registry not initialized"},
    },
)
async def list_servers(
    ctx: Annotated[RequesterContext, Depends(get_authenticated_requester)],
) -> ServerListResponse:
    """List all registered MCP servers with current health status.

    Returns all servers in the registry sorted by name, including their
    health status and configuration (Req 14.6).

    Requires authentication headers:
    - Authorization: Bearer <token>
    - X-Tenant-Id: <tenant_id>
    - X-Auth-Scope: mcp:read (or any valid scope)
    """
    registry = _get_registry()
    servers = await registry.list_servers()

    return ServerListResponse(servers=servers, total=len(servers))


@mcp_registry_router.get(
    "/{name}",
    response_model=MCPServerRecord,
    responses={
        404: {"model": ErrorResponse, "description": "Server not found"},
        503: {"model": ErrorResponse, "description": "MCP Registry not initialized"},
    },
)
async def get_server(
    name: str,
    ctx: Annotated[RequesterContext, Depends(get_authenticated_requester)],
) -> MCPServerRecord:
    """Get details for a specific MCP server by name.

    Returns the full server record including health status, supported tools,
    and configuration.

    Requires authentication headers:
    - Authorization: Bearer <token>
    - X-Tenant-Id: <tenant_id>
    - X-Auth-Scope: mcp:read (or any valid scope)
    """
    registry = _get_registry()
    server = await registry.get_server(name)

    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP server '{name}' not found.",
        )

    return server


@mcp_registry_router.delete(
    "/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {"model": ErrorResponse, "description": "Server not found"},
        503: {"model": ErrorResponse, "description": "MCP Registry not initialized"},
    },
)
async def deregister_server(
    name: str,
    ctx: Annotated[RequesterContext, Depends(get_authenticated_requester)],
) -> None:
    """Deregister an MCP server from the registry.

    Removes the server and its stored credentials. Returns 404 if the
    server does not exist.

    Requires authentication headers:
    - Authorization: Bearer <token>
    - X-Tenant-Id: <tenant_id>
    - X-Auth-Scope: mcp:write (or any valid scope)
    """
    registry = _get_registry()
    removed = await registry.deregister(name)

    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP server '{name}' not found.",
        )

    logger.info(
        "MCP server deregistered via API",
        extra={"server_name": name, "tenant_id": ctx.tenant_id},
    )


@mcp_registry_router.post(
    "/{name}/rotate-credentials",
    response_model=RotateCredentialsResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Server not found"},
        503: {"model": ErrorResponse, "description": "MCP Registry not initialized"},
    },
)
async def rotate_credentials(
    name: str,
    body: RotateCredentialsRequest,
    ctx: Annotated[RequesterContext, Depends(get_authenticated_requester)],
) -> RotateCredentialsResponse:
    """Rotate credentials for an MCP server without service restart.

    Updates the stored credentials in-place. The new credentials take effect
    immediately for subsequent tool invocations (Req 14.7).

    Requires authentication headers:
    - Authorization: Bearer <token>
    - X-Tenant-Id: <tenant_id>
    - X-Auth-Scope: mcp:write (or any valid scope)
    """
    registry = _get_registry()

    # Verify server exists before rotating
    server = await registry.get_server(name)
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP server '{name}' not found.",
        )

    try:
        await registry.rotate_credentials(name, body.credentials)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    logger.info(
        "MCP server credentials rotated via API",
        extra={"server_name": name, "tenant_id": ctx.tenant_id},
    )

    return RotateCredentialsResponse(name=name)
