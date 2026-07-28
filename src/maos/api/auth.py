"""Authentication and RBAC dependencies for the MAOS API surface.

Implements header-based authentication and permission checking for all
Task-processing routes (Req 9.4, 9.9). Health/readiness endpoints remain
unauthenticated.

Scheme:
    - ``Authorization: Bearer <token>`` — required bearer token identifying the
      requester (validated for non-empty; full JWT/OAuth2 verification is a
      deployment concern layered on top).
    - ``X-Tenant-Id`` — required header identifying the clinic/tenant scope.
    - ``X-Auth-Scope`` — required comma-separated list of RBAC permissions
      granted to the requester (e.g. ``tasks:submit,tasks:read``).

The ``get_authenticated_requester`` dependency extracts these headers, validates
presence and minimal structure, and returns a ``RequesterContext`` carrying
tenant, requester identity, and scopes. Routes that need fine-grained permission
checks use ``require_permission(permission)`` which verifies the scope list
contains the needed permission.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import Depends, Header, HTTPException, status


@dataclass(frozen=True, slots=True)
class RequesterContext:
    """Authenticated requester identity extracted from request headers.

    Attributes:
        tenant_id: The clinic/tenant scope associated with the request (Req 9.1).
        requester_id: Identifier derived from the bearer token (opaque string).
        auth_scope: List of RBAC permissions granted to the requester (Req 9.4).
    """

    tenant_id: str
    requester_id: str
    auth_scope: list[str] = field(default_factory=list)


async def get_authenticated_requester(
    authorization: str | None = Header(default=None),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    x_auth_scope: str | None = Header(default=None, alias="X-Auth-Scope"),
) -> RequesterContext:
    """FastAPI dependency that authenticates the requester via headers.

    Validates presence and minimal structure of the required authentication
    headers and returns a ``RequesterContext`` for downstream use.

    Raises:
        HTTPException (401): If any required header is missing or malformed.
    """
    # Validate Authorization header
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Expect "Bearer <token>" format
    parts = authorization.split(" ", maxsplit=1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must be in the format 'Bearer <token>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    requester_id = parts[1].strip()

    # Validate X-Tenant-Id
    if not x_tenant_id or not x_tenant_id.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or empty X-Tenant-Id header.",
        )

    # Validate X-Auth-Scope
    if not x_auth_scope or not x_auth_scope.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or empty X-Auth-Scope header.",
        )

    # Parse comma-separated scopes, stripping whitespace
    scopes = [s.strip() for s in x_auth_scope.split(",") if s.strip()]
    if not scopes:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Auth-Scope header contains no valid scopes.",
        )

    return RequesterContext(
        tenant_id=x_tenant_id.strip(),
        requester_id=requester_id,
        auth_scope=scopes,
    )


def require_permission(permission: str) -> Callable[..., RequesterContext]:
    """Return a FastAPI dependency that asserts a specific permission is present.

    Use as a dependency on individual routes that need fine-grained RBAC beyond
    the base authentication. The returned dependency itself depends on
    ``get_authenticated_requester`` so that authentication is enforced first.

    Args:
        permission: The required permission string (e.g. ``"tasks:submit"``).

    Returns:
        A dependency callable that raises 403 if the permission is absent.

    Example::

        @router.post("/sensitive")
        async def sensitive_endpoint(
            ctx: RequesterContext = Depends(require_permission("admin:write")),
        ) -> ...:
            ...
    """

    async def _check_permission(
        ctx: RequesterContext = Depends(get_authenticated_requester),
    ) -> RequesterContext:
        if permission not in ctx.auth_scope:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission '{permission}' is required but not in auth scope.",
            )
        return ctx

    return _check_permission
