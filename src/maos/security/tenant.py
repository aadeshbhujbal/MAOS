"""Tenant-isolation guard for MAOS.

This module provides pure, I/O-free functions that enforce tenant isolation
at the data-access boundary. Every data access must pass through
``enforce_tenant_isolation`` before proceeding, and ``propagate_tenant``
extracts the tenant_id that must be carried unchanged to all child units.

Requirements: 9.1, 9.2, 9.3
"""

from __future__ import annotations

from maos.contracts.work_units import Task


class TenantViolationError(Exception):
    """Raised when a tenant-isolation boundary is violated.

    Attributes:
        task_tenant_id: The tenant associated with the originating Task.
        requested_tenant_id: The tenant that was requested for access.
    """

    def __init__(self, task_tenant_id: str, requested_tenant_id: str) -> None:
        self.task_tenant_id = task_tenant_id
        self.requested_tenant_id = requested_tenant_id
        super().__init__(
            f"Tenant isolation violation: task tenant '{task_tenant_id}' "
            f"!= requested tenant '{requested_tenant_id}'"
        )


def enforce_tenant_isolation(
    task_tenant_id: str, requested_tenant_id: str
) -> None:
    """Guard called before any data access to ensure tenant match.

    If ``requested_tenant_id`` does not equal ``task_tenant_id``, raises
    ``TenantViolationError``. Otherwise returns None.

    This implements the restriction from Req 9.2 (restrict data access to
    the Task's tenant) and the denial from Req 9.3 (deny cross-tenant access).

    Args:
        task_tenant_id: The tenant identifier associated with the originating Task.
        requested_tenant_id: The tenant identifier of the data being requested.

    Raises:
        TenantViolationError: If the tenants do not match.
    """
    if requested_tenant_id != task_tenant_id:
        raise TenantViolationError(task_tenant_id, requested_tenant_id)


def propagate_tenant(task: Task) -> str:
    """Extract and return the tenant_id that must be carried unchanged to all child units.

    Every Subtask and Sub_Subtask derived from a Task must propagate the
    same ``tenant_id`` without modification (Req 9.1, 9.2). This function
    extracts the authoritative tenant identifier from the originating Task.

    Args:
        task: The parent Task whose tenant_id scopes all child work.

    Returns:
        The tenant_id string that must be propagated to all child units.
    """
    return task.tenant_id
