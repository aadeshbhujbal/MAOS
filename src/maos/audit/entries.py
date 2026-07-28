"""Audit-entry builder functions (pure, no I/O).

Each builder constructs an ``AuditEntry`` instance that always includes
``task_id`` (and ``subtask_id`` / ``sub_subtask_id`` where applicable) and
ensures all detail is redacted via ``maos.security.redaction.redact``.

Requirements: 2.6, 3.2, 5.5, 10.1, 10.2, 10.4, 10.7, 11.1.
"""

from __future__ import annotations

from datetime import UTC, datetime

from maos.contracts.audit import AuditEntry, AuditEventType
from maos.security.redaction import redact


def build_routing_decision_entry(
    task_id: str,
    subtask_id: str | None,
    sub_subtask_id: str | None,
    actor_agent_id: str,
    candidates: list[str],
    selected: str | None,
) -> AuditEntry:
    """Build an audit entry for a routing decision (Req 10.1).

    Records the candidate agents considered and the selected agent.
    """
    detail = redact({
        "candidates": candidates,
        "selected": selected,
    })
    return AuditEntry(
        task_id=task_id,
        subtask_id=subtask_id,
        sub_subtask_id=sub_subtask_id,
        actor_agent_id=actor_agent_id,
        event_type=AuditEventType.ROUTING,
        detail=detail,
        created_at=datetime.now(tz=UTC),
    )


def build_execution_start_entry(
    task_id: str,
    subtask_id: str | None,
    sub_subtask_id: str | None,
    actor_agent_id: str,
) -> AuditEntry:
    """Build an audit entry recording Sub_Subtask execution start (Req 10.2)."""
    now = datetime.now(tz=UTC)
    detail = redact({
        "start_timestamp": now.isoformat(),
    })
    return AuditEntry(
        task_id=task_id,
        subtask_id=subtask_id,
        sub_subtask_id=sub_subtask_id,
        actor_agent_id=actor_agent_id,
        event_type=AuditEventType.EXECUTION_START,
        detail=detail,
        created_at=now,
    )


def build_execution_finish_entry(
    task_id: str,
    subtask_id: str | None,
    sub_subtask_id: str | None,
    actor_agent_id: str,
) -> AuditEntry:
    """Build an audit entry recording Sub_Subtask execution finish (Req 10.2)."""
    now = datetime.now(tz=UTC)
    detail = redact({
        "finish_timestamp": now.isoformat(),
    })
    return AuditEntry(
        task_id=task_id,
        subtask_id=subtask_id,
        sub_subtask_id=sub_subtask_id,
        actor_agent_id=actor_agent_id,
        event_type=AuditEventType.EXECUTION_FINISH,
        detail=detail,
        created_at=now,
    )


def build_tool_invocation_entry(
    task_id: str,
    subtask_id: str | None,
    sub_subtask_id: str | None,
    actor_agent_id: str,
    tool_name: str,
    args_ref: str,
    result_status: str,
) -> AuditEntry:
    """Build an audit entry for MCP tool invocation completion (Req 5.5).

    Records the tool name, invoking subagent, sub_subtask id, a reference to
    the invocation arguments (never raw secrets/PHI), and result status.
    """
    detail = redact({
        "tool_name": tool_name,
        "subagent_id": actor_agent_id,
        "sub_subtask_id": sub_subtask_id,
        "args_ref": args_ref,
        "result_status": result_status,
    })
    return AuditEntry(
        task_id=task_id,
        subtask_id=subtask_id,
        sub_subtask_id=sub_subtask_id,
        actor_agent_id=actor_agent_id,
        event_type=AuditEventType.TOOL_INVOCATION,
        detail=detail,
        created_at=datetime.now(tz=UTC),
    )


def build_error_entry(
    task_id: str,
    subtask_id: str | None,
    sub_subtask_id: str | None,
    actor_agent_id: str,
    error_type: str,
    error_detail: dict,
) -> AuditEntry:
    """Build an audit entry for an error event (Req 10.4).

    Records the error type and affected identifiers. All detail is redacted.
    """
    detail = redact({
        "error_type": error_type,
        "task_id": task_id,
        "subtask_id": subtask_id,
        "sub_subtask_id": sub_subtask_id,
        **error_detail,
    })
    return AuditEntry(
        task_id=task_id,
        subtask_id=subtask_id,
        sub_subtask_id=sub_subtask_id,
        actor_agent_id=actor_agent_id,
        event_type=AuditEventType.ERROR,
        detail=detail,
        created_at=datetime.now(tz=UTC),
    )


def build_failure_entry(
    task_id: str,
    subtask_id: str | None,
    sub_subtask_id: str | None,
    actor_agent_id: str,
    reason: str,
) -> AuditEntry:
    """Build an audit entry for a failure event (Req 11.1).

    Records the failure reason. Detail is redacted.
    """
    detail = redact({
        "reason": reason,
    })
    return AuditEntry(
        task_id=task_id,
        subtask_id=subtask_id,
        sub_subtask_id=sub_subtask_id,
        actor_agent_id=actor_agent_id,
        event_type=AuditEventType.FAILURE,
        detail=detail,
        created_at=datetime.now(tz=UTC),
    )
