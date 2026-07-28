"""Audit_Log contracts.

Defines the append-only audit record (``AuditEntry``) and the set of recorded
event types (``AuditEventType``). These are pure Pydantic v2 contracts; the
append-only guarantee is enforced by DB grants (Req 10.3), not app logic.

Traceability:
- ``audit_id`` is server-assigned (``BIGSERIAL``) and therefore ``None`` before
  persistence.
- Every entry includes the ``task_id`` and, where applicable, the ``subtask_id``
  and ``sub_subtask_id`` (Req 10.7, 3.1).
- ``detail`` is always redacted — no secrets/PHI (Req 5.6, 9.5, 9.10).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class AuditEventType(str, Enum):
    """Recorded Audit_Log event types (``audit_log.event_type``)."""

    INTAKE = "intake"
    ROUTING = "routing"
    EXECUTION_START = "execution_start"           # Req 10.2
    EXECUTION_FINISH = "execution_finish"         # Req 10.2
    TOOL_INVOCATION = "tool_invocation"
    ERROR = "error"
    FAILURE = "failure"                           # Req 11.1
    APPROVAL_REQUEST = "approval_request"
    APPROVAL_DECISION = "approval_decision"
    DELEGATION_ACCEPTED = "delegation_accepted"   # Req 16.5
    DELEGATION_DENIED = "delegation_denied"       # Req 16.7
    CONTEXT_HANDOFF = "context_handoff"           # Req 17.7


class AuditEntry(BaseModel):
    """An append-only Audit_Log entry with redacted detail (Req 10.3, 10.7)."""

    audit_id: int | None = None        # BIGSERIAL, server-assigned -> None pre-persist
    task_id: str                       # always present (Req 10.7)
    subtask_id: str | None = None      # where applicable (Req 10.7)
    sub_subtask_id: str | None = None  # where applicable (Req 10.7)
    actor_agent_id: str | None = None
    event_type: AuditEventType
    detail: dict                       # redacted: no secrets/PHI (Req 5.6, 9.5, 9.10)
    created_at: datetime
