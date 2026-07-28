"""RBAC scope enforcement for MAOS.

This module provides pure, I/O-free functions that enforce role-based
access control (RBAC) at the operation boundary.  Every on-behalf-of
operation must pass through ``enforce_rbac`` before proceeding.

Requirements: 9.4
"""

from __future__ import annotations


class RBACDeniedError(Exception):
    """Raised when a required permission is not in the authorization scope.

    Attributes:
        required_permission: The permission that was required but missing.
        auth_scope: The authorization scope that was checked against.
    """

    def __init__(self, required_permission: str, auth_scope: list[str]) -> None:
        self.required_permission = required_permission
        self.auth_scope = list(auth_scope)
        super().__init__(
            f"Permission denied: '{required_permission}' not in auth_scope {auth_scope}"
        )


def enforce_rbac(required_permission: str, auth_scope: list[str]) -> None:
    """Guard called before any on-behalf-of operation (Req 9.4).

    Checks that ``required_permission`` is present in ``auth_scope``.
    If not, raises ``RBACDeniedError``. Otherwise returns None.

    This is a pure function with no I/O.

    Args:
        required_permission: The permission required for the operation.
        auth_scope: The Requester's list of granted permissions/scopes.

    Raises:
        RBACDeniedError: If the required permission is not in auth_scope.
    """
    if required_permission not in auth_scope:
        raise RBACDeniedError(required_permission, auth_scope)


def has_permission(required_permission: str, auth_scope: list[str]) -> bool:
    """Check whether a permission is present in the authorization scope.

    Returns True if ``required_permission`` is in ``auth_scope``, False otherwise.
    This is a pure, non-throwing alternative to ``enforce_rbac``.

    Args:
        required_permission: The permission to check.
        auth_scope: The Requester's list of granted permissions/scopes.

    Returns:
        True if the permission is present, False otherwise.
    """
    return required_permission in auth_scope
