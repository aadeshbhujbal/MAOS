"""Agent_Message contracts for the MAOS Message_Bus.

Defines the structured unit of communication exchanged between agents across the
three levels of the hierarchy (``AgentMessage``) and the closed set of message
intents (``MessageType``). These are pure Pydantic v2 contracts so the
Message_Bus serialization round-trip (Req 6.5) and schema validation (Req 6.2)
can be exercised deterministically.

Traceability:
- Every message carries the originating ``task_id`` preserved on delivery (Req 6.4).
- ``payload`` references PHI by id only; no raw PHI/secrets (Req 9.5).
- ``subtask_id`` / ``sub_subtask_id`` are optional so level-spanning and
  Task-scoped messages are both representable (Req 6.1).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class MessageType(str, Enum):
    """Closed set of Agent_Message intents (Req 6.1)."""

    ASSIGN = "assign"
    RESULT = "result"
    STATUS = "status"
    ERROR = "error"
    APPROVAL_REQUEST = "approval_request"
    APPROVAL_DECISION = "approval_decision"


class AgentMessage(BaseModel):
    """A structured unit of communication exchanged via the Message_Bus (Req 6.1)."""

    message_id: str
    sender_id: str
    recipient_id: str
    task_id: str                       # preserved on delivery (Req 6.4)
    subtask_id: str | None
    sub_subtask_id: str | None
    type: MessageType
    payload: dict                      # PHI referenced by id only (Req 9.5)
    created_at: datetime
