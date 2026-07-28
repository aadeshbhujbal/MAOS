"""Operation-scope enforcement (pure core).

This module implements the operation-scope check that a Subagent applies before
executing any operation within a Sub_Subtask (Req 4.4, 4.5).

**Rule:** an operation is permitted if and only if it appears in the matched
:class:`~maos.contracts.agents.Skill`'s ``operation_scope`` list. If the
operation is *not* in that list, an :class:`OutOfScopeError` is raised carrying
the rejected operation and the Skill's permitted scope so the caller can
produce a structured out-of-scope error response.

The function is **pure** — no I/O, no side effects. Its result depends solely
on the operation string and the Skill's ``operation_scope`` list.
"""

from __future__ import annotations

from maos.contracts.agents import Skill


class OutOfScopeError(Exception):
    """Raised when an operation is not within the matched Skill's operation scope.

    Attributes:
        operation: The rejected operation string.
        permitted_scope: The Skill's list of permitted operations.
    """

    def __init__(self, *, operation: str, permitted_scope: list[str]) -> None:
        self.operation = operation
        self.permitted_scope = permitted_scope
        super().__init__(
            f"Operation {operation!r} is out of scope. "
            f"Permitted scope: {permitted_scope!r}"
        )


def check_operation_scope(operation: str, skill: Skill) -> None:
    """Permit an operation iff it lies within the matched Skill's operation scope.

    If ``operation`` is present in ``skill.operation_scope``, the function
    returns ``None`` (success). Otherwise it raises :class:`OutOfScopeError`
    carrying the rejected operation and the Skill's permitted scope (Req 4.4,
    4.5).

    This is a **pure function** — total, side-effect-free, and deterministic.

    Args:
        operation: The operation the Subagent intends to execute.
        skill: The matched Skill whose ``operation_scope`` defines the
            permitted set of operations.

    Raises:
        OutOfScopeError: If ``operation`` is not in ``skill.operation_scope``.
    """
    if operation not in skill.operation_scope:
        raise OutOfScopeError(
            operation=operation,
            permitted_scope=list(skill.operation_scope),
        )
