"""Namespace-based access control for the Knowledge Store.

Enforces the ``(tenant_id, agent_role)`` namespace tuple structure and restricts
agent access to their own tenant and role scope, plus the shared ``"common"``
namespace within the same tenant.

References
----------
- Req 2.1: Restrict search results to agent's namespace.
- Req 2.2: Reject operations where namespace tenant_id != authenticated tenant_id.
- Req 2.3: Security agent scoped to ``(tenant_id, "security")``.
- Req 2.4: Backend agent scoped to ``(tenant_id, "backend")``.
- Req 2.5: Shared ``(tenant_id, "common")`` namespace accessible to all roles.
- Req 2.6: Deny and log access violations.
"""

from __future__ import annotations

import structlog

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The shared role name accessible by all agents within a tenant.
COMMON_ROLE: str = "common"

#: Valid agent roles for the platform (16 specialized + "common").
VALID_AGENT_ROLES: frozenset[str] = frozenset(
    {
        "backend",
        "frontend",
        "mobile",
        "security",
        "devops",
        "qa",
        "documentation",
        "architecture",
        "database",
        "monitoring",
        "incident_response",
        "infrastructure",
        "ml_ai",
        "ui_ux",
        "api",
        "planning",
        COMMON_ROLE,
    }
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AccessViolationError(Exception):
    """Raised when an agent attempts an unauthorized namespace access.

    Attributes
    ----------
    tenant_id : str
        The authenticated tenant of the requesting agent.
    requested_namespace : tuple[str, ...]
        The namespace the agent tried to access.
    reason : str
        Human-readable explanation of why access was denied.
    """

    def __init__(
        self,
        tenant_id: str,
        requested_namespace: tuple[str, ...],
        reason: str,
    ) -> None:
        self.tenant_id = tenant_id
        self.requested_namespace = requested_namespace
        self.reason = reason
        super().__init__(
            f"Access violation: tenant '{tenant_id}' denied access to "
            f"namespace {requested_namespace!r} — {reason}"
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_namespace(namespace: tuple[str, ...]) -> None:
    """Validate that *namespace* conforms to the ``(tenant_id, agent_role)`` structure.

    The namespace MUST be a tuple of exactly 2 non-empty string elements where
    element 1 (agent_role) is one of the recognized :data:`VALID_AGENT_ROLES`.

    Parameters
    ----------
    namespace : tuple[str, ...]
        The namespace tuple to validate.

    Raises
    ------
    ValueError
        If the namespace does not have exactly 2 elements, contains empty
        strings, or uses an unrecognized agent role.
    """
    if not isinstance(namespace, tuple):
        raise ValueError(
            f"Namespace must be a tuple, got {type(namespace).__name__}"
        )
    if len(namespace) != 2:
        raise ValueError(
            f"Namespace must have exactly 2 elements (tenant_id, agent_role), "
            f"got {len(namespace)} element(s): {namespace!r}"
        )
    tenant_id, agent_role = namespace
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError(
            f"Namespace tenant_id (element 0) must be a non-empty string, "
            f"got {tenant_id!r}"
        )
    if not isinstance(agent_role, str) or not agent_role.strip():
        raise ValueError(
            f"Namespace agent_role (element 1) must be a non-empty string, "
            f"got {agent_role!r}"
        )
    if agent_role not in VALID_AGENT_ROLES:
        raise ValueError(
            f"Namespace agent_role '{agent_role}' is not a recognized role. "
            f"Valid roles: {sorted(VALID_AGENT_ROLES)}"
        )


# ---------------------------------------------------------------------------
# Access Control
# ---------------------------------------------------------------------------


def check_namespace_access(
    namespace: tuple[str, ...],
    authenticated_tenant_id: str,
    agent_role: str,
) -> bool:
    """Check whether an agent may access the given namespace.

    Access rules (Req 2.1-2.6):

    1. The namespace must be a valid ``(tenant_id, role)`` 2-tuple.
    2. The namespace's tenant_id must match *authenticated_tenant_id*
       (tenant isolation — Req 2.2).
    3. The namespace's role must be either:
       - The agent's own *agent_role* (Req 2.1, 2.3, 2.4), **OR**
       - The shared ``"common"`` role (Req 2.5).

    If access is denied an :class:`AccessViolationError` is raised and a
    structured ``AccessViolationEvent`` is logged via structlog (Req 2.6).

    Parameters
    ----------
    namespace : tuple[str, ...]
        The target namespace tuple ``(tenant_id, role)``.
    authenticated_tenant_id : str
        The tenant_id of the authenticated agent.
    agent_role : str
        The role of the requesting agent.

    Returns
    -------
    bool
        ``True`` if access is permitted.

    Raises
    ------
    AccessViolationError
        If the agent is not allowed to access the namespace.
    ValueError
        If the namespace structure is invalid.
    """
    # Step 1: Validate namespace structure
    validate_namespace(namespace)

    ns_tenant_id, ns_role = namespace

    # Step 2: Tenant isolation check (Req 2.2)
    if ns_tenant_id != authenticated_tenant_id:
        reason = (
            f"Tenant mismatch: authenticated as '{authenticated_tenant_id}' "
            f"but namespace belongs to tenant '{ns_tenant_id}'"
        )
        _log_access_violation(
            authenticated_tenant_id=authenticated_tenant_id,
            agent_role=agent_role,
            requested_namespace=namespace,
            reason=reason,
        )
        raise AccessViolationError(
            tenant_id=authenticated_tenant_id,
            requested_namespace=namespace,
            reason=reason,
        )

    # Step 3: Role-based access check (Req 2.1, 2.3, 2.4, 2.5)
    if ns_role != agent_role and ns_role != COMMON_ROLE:
        reason = (
            f"Role mismatch: agent role '{agent_role}' cannot access "
            f"namespace role '{ns_role}' (only own role or '{COMMON_ROLE}' allowed)"
        )
        _log_access_violation(
            authenticated_tenant_id=authenticated_tenant_id,
            agent_role=agent_role,
            requested_namespace=namespace,
            reason=reason,
        )
        raise AccessViolationError(
            tenant_id=authenticated_tenant_id,
            requested_namespace=namespace,
            reason=reason,
        )

    return True


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _log_access_violation(
    *,
    authenticated_tenant_id: str,
    agent_role: str,
    requested_namespace: tuple[str, ...],
    reason: str,
) -> None:
    """Emit a structured ``AccessViolationEvent`` via structlog (Req 2.6).

    The structured fields enable filtering and alerting on unauthorized
    access attempts in the observability stack.
    """
    logger.warning(
        "AccessViolationEvent",
        event_type="access_violation",
        authenticated_tenant_id=authenticated_tenant_id,
        agent_role=agent_role,
        requested_namespace=requested_namespace,
        reason=reason,
    )
