"""Security audit trail writer.

Provides a unified ``AuditWriter`` service that coordinates:
- Audit entry building via ``maos.audit.entries`` builders
- Redaction enforcement via ``maos.security.redaction``
- Persistence via ``maos.audit.repository.AuditLogRepo``

This is the canonical entry point for all audit writes throughout the system.
It ensures every audit event includes required traceability identifiers (task_id,
subtask_id, sub_subtask_id) and that detail fields are redacted before persistence.

Requirements: 2.6, 5.5, 5.6, 10.1, 10.2, 10.3, 10.7, 11.1.
"""

from __future__ import annotations

from maos.audit import entries as audit_entries
from maos.audit.repository import AuditLogRepo
from maos.contracts.audit import AuditEntry


class AuditWriter:
    """Unified audit event log writer.

    Wraps the entry builders and repository to provide a single service for all
    audit writes. Guarantees:
    - All detail is redacted before persistence (Req 5.6, 9.5, 9.10)
    - Traceability identifiers are present on every entry (Req 10.7)
    - Append-only persistence is enforced (Req 10.3)

    Typical usage:
        writer = AuditWriter(audit_repo)
        await writer.log_routing_decision(...)
        await writer.log_execution_start(...)
        await writer.log_tool_invocation(...)
    """

    def __init__(self, audit_repo: AuditLogRepo) -> None:
        """Initialize with an audit log repository.

        Parameters
        ----------
        audit_repo:
            The append-only audit repository.
        """
        self._repo = audit_repo

    # ------------------------------------------------------------------
    # Routing events (Req 10.1)
    # ------------------------------------------------------------------

    async def log_routing_decision(
        self,
        *,
        task_id: str,
        subtask_id: str | None = None,
        sub_subtask_id: str | None = None,
        actor_agent_id: str,
        candidates: list[str],
        selected: str | None,
    ) -> AuditEntry:
        """Log a routing decision event (Req 10.1).

        Records the candidate agents considered and the selected agent.
        """
        entry = audit_entries.build_routing_decision_entry(
            task_id=task_id,
            subtask_id=subtask_id,
            sub_subtask_id=sub_subtask_id,
            actor_agent_id=actor_agent_id,
            candidates=candidates,
            selected=selected,
        )
        return await self._repo.append(entry)

    # ------------------------------------------------------------------
    # Execution lifecycle events (Req 10.2)
    # ------------------------------------------------------------------

    async def log_execution_start(
        self,
        *,
        task_id: str,
        subtask_id: str | None = None,
        sub_subtask_id: str | None = None,
        actor_agent_id: str,
    ) -> AuditEntry:
        """Log an execution start event (Req 10.2)."""
        entry = audit_entries.build_execution_start_entry(
            task_id=task_id,
            subtask_id=subtask_id,
            sub_subtask_id=sub_subtask_id,
            actor_agent_id=actor_agent_id,
        )
        return await self._repo.append(entry)

    async def log_execution_finish(
        self,
        *,
        task_id: str,
        subtask_id: str | None = None,
        sub_subtask_id: str | None = None,
        actor_agent_id: str,
    ) -> AuditEntry:
        """Log an execution finish event (Req 10.2)."""
        entry = audit_entries.build_execution_finish_entry(
            task_id=task_id,
            subtask_id=subtask_id,
            sub_subtask_id=sub_subtask_id,
            actor_agent_id=actor_agent_id,
        )
        return await self._repo.append(entry)

    # ------------------------------------------------------------------
    # Tool invocation events (Req 5.5)
    # ------------------------------------------------------------------

    async def log_tool_invocation(
        self,
        *,
        task_id: str,
        subtask_id: str | None = None,
        sub_subtask_id: str | None = None,
        actor_agent_id: str,
        tool_name: str,
        args_ref: str,
        result_status: str,
    ) -> AuditEntry:
        """Log an MCP tool invocation event (Req 5.5).

        Records the tool name, invoking subagent, sub_subtask id, a reference
        to the invocation arguments (never raw secrets/PHI), and result status.
        """
        entry = audit_entries.build_tool_invocation_entry(
            task_id=task_id,
            subtask_id=subtask_id,
            sub_subtask_id=sub_subtask_id,
            actor_agent_id=actor_agent_id,
            tool_name=tool_name,
            args_ref=args_ref,
            result_status=result_status,
        )
        return await self._repo.append(entry)

    # ------------------------------------------------------------------
    # Error and failure events (Req 10.4, 11.1)
    # ------------------------------------------------------------------

    async def log_error(
        self,
        *,
        task_id: str,
        subtask_id: str | None = None,
        sub_subtask_id: str | None = None,
        actor_agent_id: str,
        error_type: str,
        error_detail: dict,
    ) -> AuditEntry:
        """Log an error event (Req 10.4).

        Records the error type and affected identifiers. All detail is redacted.
        """
        entry = audit_entries.build_error_entry(
            task_id=task_id,
            subtask_id=subtask_id,
            sub_subtask_id=sub_subtask_id,
            actor_agent_id=actor_agent_id,
            error_type=error_type,
            error_detail=error_detail,
        )
        return await self._repo.append(entry)

    async def log_failure(
        self,
        *,
        task_id: str,
        subtask_id: str | None = None,
        sub_subtask_id: str | None = None,
        actor_agent_id: str,
        reason: str,
    ) -> AuditEntry:
        """Log a failure event (Req 11.1).

        Records the failure reason. Detail is redacted.
        """
        entry = audit_entries.build_failure_entry(
            task_id=task_id,
            subtask_id=subtask_id,
            sub_subtask_id=sub_subtask_id,
            actor_agent_id=actor_agent_id,
            reason=reason,
        )
        return await self._repo.append(entry)

    # ------------------------------------------------------------------
    # Direct append for custom events (rare)
    # ------------------------------------------------------------------

    async def append(self, entry: AuditEntry) -> AuditEntry:
        """Append a pre-built audit entry directly.

        This is provided for rare custom event types not covered by the
        convenience methods above. The entry should already be redacted.
        """
        return await self._repo.append(entry)
