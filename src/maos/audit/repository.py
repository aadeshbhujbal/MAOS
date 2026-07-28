"""Stateful Audit_Log repository — append-only persistence over Postgres.

This module provides ``AuditLogRepo``, which wraps the shared
``DatabasePool`` and implements INSERT-only access to the ``audit_log``
table.  There are **no update or delete methods** — append-only enforcement
is guaranteed both in application code (no such methods exist) and at the
database layer (the ``maos_app`` role is granted INSERT/SELECT only; see
``002_audit_grants.sql``).

The ``detail`` field on ``AuditEntry`` is expected to be **already redacted**
by the builder functions in ``maos.audit.entries`` — this repository does NOT
re-redact.

Requirements: 10.3 (append-only), 10.7 (traceability identifiers on every entry).
"""

from __future__ import annotations

from maos.contracts.audit import AuditEntry, AuditEventType
from maos.memory.database import DatabasePool


class AuditLogRepo:
    """Append-only Audit_Log backed by Postgres.

    Provides:
    - ``append(entry)`` — INSERT a single entry; returns entry with server-assigned ``audit_id``.
    - ``query_by_task(task_id)`` — SELECT all entries for a given Task.
    - ``query_by_subtask(subtask_id)`` — SELECT all entries for a given Subtask.
    - ``query_by_sub_subtask(sub_subtask_id)`` — SELECT all entries for a given Sub_Subtask.

    NO update or delete methods — this enforces Req 10.3 (append-only) at the
    application layer in addition to DB grants.
    """

    def __init__(self, pool: DatabasePool) -> None:
        """Initialize with a shared ``DatabasePool``.

        Parameters
        ----------
        pool:
            The async Postgres connection pool (must be opened before use).
        """
        self._pool = pool

    # ------------------------------------------------------------------
    # Append (INSERT only — Req 10.3)
    # ------------------------------------------------------------------

    async def append(self, entry: AuditEntry) -> AuditEntry:
        """Persist a redacted audit entry and return it with a server-assigned ``audit_id``.

        The ``detail`` field must already be redacted (handled by the builder
        functions in ``maos.audit.entries``) — this method does NOT re-redact.

        Parameters
        ----------
        entry:
            The ``AuditEntry`` to persist.  ``audit_id`` is ignored on input
            (the DB assigns it via BIGSERIAL).

        Returns
        -------
        AuditEntry
            A copy of the entry with the server-assigned ``audit_id`` and the
            ``created_at`` timestamp from the database.
        """
        row = await self._pool.fetch_one(
            """
            INSERT INTO audit_log (task_id, subtask_id, sub_subtask_id,
                                   actor_agent_id, event_type, detail, created_at)
            VALUES (%(task_id)s, %(subtask_id)s, %(sub_subtask_id)s,
                    %(actor_agent_id)s, %(event_type)s, %(detail)s, %(created_at)s)
            RETURNING audit_id, created_at
            """,
            {
                "task_id": entry.task_id,
                "subtask_id": entry.subtask_id,
                "sub_subtask_id": entry.sub_subtask_id,
                "actor_agent_id": entry.actor_agent_id,
                "event_type": entry.event_type.value,
                "detail": entry.detail,
                "created_at": entry.created_at,
            },
        )

        if row is None:  # pragma: no cover — should never happen on INSERT RETURNING
            raise RuntimeError("INSERT INTO audit_log did not return a row")

        return entry.model_copy(
            update={
                "audit_id": row["audit_id"],
                "created_at": row["created_at"],
            }
        )

    # ------------------------------------------------------------------
    # Query helpers (SELECT only — no UPDATE/DELETE paths, Req 10.3)
    # ------------------------------------------------------------------

    async def query_by_task(self, task_id: str) -> list[AuditEntry]:
        """Fetch all audit entries for a given Task identifier.

        Parameters
        ----------
        task_id:
            The Task identifier to query.

        Returns
        -------
        list[AuditEntry]
            Entries ordered by ``audit_id`` (insertion order).
        """
        rows = await self._pool.fetch_all(
            """
            SELECT audit_id, task_id, subtask_id, sub_subtask_id,
                   actor_agent_id, event_type, detail, created_at
            FROM audit_log
            WHERE task_id = %(task_id)s
            ORDER BY audit_id
            """,
            {"task_id": task_id},
        )
        return [_row_to_entry(row) for row in rows]

    async def query_by_subtask(self, subtask_id: str) -> list[AuditEntry]:
        """Fetch all audit entries for a given Subtask identifier.

        Parameters
        ----------
        subtask_id:
            The Subtask identifier to query.

        Returns
        -------
        list[AuditEntry]
            Entries ordered by ``audit_id`` (insertion order).
        """
        rows = await self._pool.fetch_all(
            """
            SELECT audit_id, task_id, subtask_id, sub_subtask_id,
                   actor_agent_id, event_type, detail, created_at
            FROM audit_log
            WHERE subtask_id = %(subtask_id)s
            ORDER BY audit_id
            """,
            {"subtask_id": subtask_id},
        )
        return [_row_to_entry(row) for row in rows]

    async def query_by_sub_subtask(self, sub_subtask_id: str) -> list[AuditEntry]:
        """Fetch all audit entries for a given Sub_Subtask identifier.

        Parameters
        ----------
        sub_subtask_id:
            The Sub_Subtask identifier to query.

        Returns
        -------
        list[AuditEntry]
            Entries ordered by ``audit_id`` (insertion order).
        """
        rows = await self._pool.fetch_all(
            """
            SELECT audit_id, task_id, subtask_id, sub_subtask_id,
                   actor_agent_id, event_type, detail, created_at
            FROM audit_log
            WHERE sub_subtask_id = %(sub_subtask_id)s
            ORDER BY audit_id
            """,
            {"sub_subtask_id": sub_subtask_id},
        )
        return [_row_to_entry(row) for row in rows]


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


def _row_to_entry(row: dict) -> AuditEntry:
    """Convert a database row dict to an ``AuditEntry`` model instance."""
    return AuditEntry(
        audit_id=row["audit_id"],
        task_id=row["task_id"],
        subtask_id=row.get("subtask_id"),
        sub_subtask_id=row.get("sub_subtask_id"),
        actor_agent_id=row.get("actor_agent_id"),
        event_type=AuditEventType(row["event_type"]),
        detail=row["detail"],
        created_at=row["created_at"],
    )
