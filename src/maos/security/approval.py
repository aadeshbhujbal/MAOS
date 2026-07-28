"""Human_Approval gate via LangGraph interrupt.

This module implements the Human_Approval mechanism for sensitive Sub_Subtasks.
When a Sub_Subtask is flagged as sensitive, the orchestration graph pauses at
the approval gate (the LangGraph interrupt point) and waits for an authorized
human to grant or deny the action within a configurable time window.

The gate persists approval requests in the ``approval`` Postgres table and
exposes methods to request, check, grant, and deny approvals.

Requirements: 11.7, 11.8.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field

from maos.memory.database import DatabasePool

# ---------------------------------------------------------------------------
# Enum
# ---------------------------------------------------------------------------


class ApprovalDecision(str, Enum):
    """Possible outcomes of a Human_Approval request."""

    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


# ---------------------------------------------------------------------------
# Pydantic model
# ---------------------------------------------------------------------------


class ApprovalRequest(BaseModel):
    """A pending or resolved Human_Approval record.

    Represents the interrupt state for a sensitive Sub_Subtask.  The graph
    pauses at ``request_approval`` and resumes only once a decision is
    recorded (APPROVED, DENIED, or EXPIRED).
    """

    approval_id: str = Field(
        description="Unique identifier for this approval request (ULID/UUID)."
    )
    sub_subtask_id: str = Field(
        description="The Sub_Subtask that requires approval before proceeding."
    )
    task_id: str = Field(
        description="Originating Task identifier for traceability."
    )
    requested_at: datetime = Field(
        description="Timestamp when the approval was requested."
    )
    window_seconds: int = Field(
        gt=0,
        description="Seconds within which the approval must be granted before expiry.",
    )
    decision: ApprovalDecision | None = Field(
        default=None,
        description="The decision once resolved; None while pending.",
    )
    approver_id: str | None = Field(
        default=None,
        description="Identifier of the human who granted or denied the request.",
    )
    decided_at: datetime | None = Field(
        default=None,
        description="Timestamp when the decision was made.",
    )


# ---------------------------------------------------------------------------
# Gate implementation
# ---------------------------------------------------------------------------


class HumanApprovalGate:
    """Manages Human_Approval requests persisted in the ``approval`` table.

    This class represents the LangGraph interrupt point for sensitive actions.
    The orchestration graph pauses at ``request_approval`` and resumes only
    after ``check_approval`` returns a non-pending decision.

    Parameters
    ----------
    pool:
        An open ``DatabasePool`` instance for async Postgres access.
    default_window_seconds:
        Default time window (in seconds) within which approval must be
        granted before the request is marked as EXPIRED.
    """

    def __init__(
        self, pool: DatabasePool, *, default_window_seconds: int = 300
    ) -> None:
        self._pool = pool
        self._default_window_seconds = default_window_seconds

    # ------------------------------------------------------------------
    # Request
    # ------------------------------------------------------------------

    async def request_approval(
        self,
        sub_subtask_id: str,
        task_id: str,
        window_s: int | None = None,
    ) -> ApprovalRequest:
        """Create a pending approval record and return it.

        This is the LangGraph interrupt point — after this call the graph
        pauses and waits for a human decision.

        Parameters
        ----------
        sub_subtask_id:
            Identifier of the Sub_Subtask requiring approval.
        task_id:
            Originating Task identifier for traceability.
        window_s:
            Optional override for the approval window (seconds).  Falls back
            to the gate's ``default_window_seconds``.

        Returns
        -------
        ApprovalRequest
            The newly created pending approval record.
        """
        approval_id = str(uuid.uuid4())
        now = datetime.now(tz=UTC)
        window = window_s if window_s is not None else self._default_window_seconds

        await self._pool.execute(
            """
            INSERT INTO approval (approval_id, sub_subtask_id, task_id,
                                  requested_at, window_s, decision,
                                  approver_id, decided_at)
            VALUES (%(approval_id)s, %(sub_subtask_id)s, %(task_id)s,
                    %(requested_at)s, %(window_s)s, NULL, NULL, NULL)
            """,
            {
                "approval_id": approval_id,
                "sub_subtask_id": sub_subtask_id,
                "task_id": task_id,
                "requested_at": now,
                "window_s": window,
            },
        )

        return ApprovalRequest(
            approval_id=approval_id,
            sub_subtask_id=sub_subtask_id,
            task_id=task_id,
            requested_at=now,
            window_seconds=window,
            decision=None,
            approver_id=None,
            decided_at=None,
        )

    # ------------------------------------------------------------------
    # Check (with auto-expiry)
    # ------------------------------------------------------------------

    async def check_approval(self, approval_id: str) -> ApprovalDecision:
        """Read the current decision for an approval request.

        If the configured window has elapsed and no decision was recorded,
        this method marks the request as EXPIRED in the database and returns
        ``ApprovalDecision.EXPIRED``.

        Parameters
        ----------
        approval_id:
            The approval record to check.

        Returns
        -------
        ApprovalDecision
            The current (or newly expired) decision.

        Raises
        ------
        ValueError
            If no approval record with the given id exists.
        """
        row = await self._pool.fetch_one(
            """
            SELECT sub_subtask_id, task_id, requested_at, window_s,
                   decision, approver_id, decided_at
            FROM approval
            WHERE approval_id = %(approval_id)s
            """,
            {"approval_id": approval_id},
        )

        if row is None:
            raise ValueError(f"No approval record found for id={approval_id!r}")

        # Already decided — return immediately.
        if row["decision"] is not None:
            return ApprovalDecision(row["decision"])

        # Check expiry: if window has elapsed, mark as expired.
        requested_at: datetime = row["requested_at"]
        window_s: int = row["window_s"]
        now = datetime.now(tz=UTC)

        elapsed = (now - requested_at).total_seconds()
        if elapsed >= window_s:
            await self._pool.execute(
                """
                UPDATE approval
                SET decision = %(decision)s, decided_at = %(decided_at)s
                WHERE approval_id = %(approval_id)s AND decision IS NULL
                """,
                {
                    "decision": ApprovalDecision.EXPIRED.value,
                    "decided_at": now,
                    "approval_id": approval_id,
                },
            )
            return ApprovalDecision.EXPIRED

        # Still pending — return None-equivalent.  The caller should
        # re-check later.  For the type contract we raise to signal
        # "no decision yet" — but since the return is ApprovalDecision,
        # we raise a specific error the caller can catch.
        raise PendingApprovalError(approval_id)

    # ------------------------------------------------------------------
    # Grant / Deny
    # ------------------------------------------------------------------

    async def grant(self, approval_id: str, approver_id: str) -> None:
        """Mark an approval request as APPROVED.

        Parameters
        ----------
        approval_id:
            The approval record to approve.
        approver_id:
            Identifier of the human granting approval.

        Raises
        ------
        ValueError
            If no pending approval with the given id exists or it was already
            decided.
        """
        await self._resolve(approval_id, approver_id, ApprovalDecision.APPROVED)

    async def deny(self, approval_id: str, approver_id: str) -> None:
        """Mark an approval request as DENIED.

        Parameters
        ----------
        approval_id:
            The approval record to deny.
        approver_id:
            Identifier of the human denying approval.

        Raises
        ------
        ValueError
            If no pending approval with the given id exists or it was already
            decided.
        """
        await self._resolve(approval_id, approver_id, ApprovalDecision.DENIED)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _resolve(
        self, approval_id: str, approver_id: str, decision: ApprovalDecision
    ) -> None:
        """Update a pending approval to the given decision.

        Only updates rows where ``decision IS NULL`` (still pending) to avoid
        overwriting a prior decision.
        """
        now = datetime.now(tz=UTC)

        row = await self._pool.fetch_one(
            """
            UPDATE approval
            SET decision = %(decision)s,
                approver_id = %(approver_id)s,
                decided_at = %(decided_at)s
            WHERE approval_id = %(approval_id)s AND decision IS NULL
            RETURNING approval_id
            """,
            {
                "decision": decision.value,
                "approver_id": approver_id,
                "decided_at": now,
                "approval_id": approval_id,
            },
        )

        if row is None:
            raise ValueError(
                f"Approval {approval_id!r} does not exist or was already decided."
            )


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class PendingApprovalError(Exception):
    """Raised when an approval is still pending (no decision, window not elapsed).

    The caller (typically the LangGraph node) should wait/retry until the
    window elapses or a human decides.
    """

    def __init__(self, approval_id: str) -> None:
        self.approval_id = approval_id
        super().__init__(
            f"Approval {approval_id!r} is still pending — no decision yet and "
            f"window has not elapsed."
        )
