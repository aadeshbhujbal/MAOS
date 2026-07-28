"""Agent_Message schema validation and (de)serialization codec.

Pure, deterministic functions backing the Message_Bus transport (task 6.1). These
functions own the schema-level concerns of Requirement 6 without performing any
I/O, registry lookups, or delivery, so they can be exercised in isolation by the
Hypothesis properties 17/18/19:

- :func:`validate_message` validates a raw dict against the ``AgentMessage``
  schema (Pydantic v2) and raises :class:`MessageValidationError` with per-field
  errors if invalid (Req 6.2, 6.3). On success returns the validated model.
- :func:`validate` (legacy) checks an arbitrary candidate and returns a typed
  ok/errors result that names every failed field (Req 6.1, 6.2, 6.3).
- :func:`serialize_message` / :func:`deserialize_message` convert an
  ``AgentMessage`` to bytes and back such that
  ``deserialize_message(serialize_message(m)) == m`` for any valid message
  (Req 6.5, Property 19). A stable Pydantic v2 JSON encoding is used so the
  round-trip preserves field values including ``created_at`` datetimes.
- Both the schema and the round-trip preserve the trace identifiers
  ``task_id`` / ``subtask_id`` / ``sub_subtask_id`` (Req 6.4, Property 18).

The codec is transport-agnostic and side-effect-free: it never opens a
connection, touches the Agent_Registry, or mutates its inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import ValidationError

from maos.contracts.messaging import AgentMessage

__all__ = [
    "FieldError",
    "MessageValidationError",
    "ValidationResult",
    "deserialize",
    "deserialize_message",
    "serialize",
    "serialize_message",
    "validate",
    "validate_message",
]


# ---------------------------------------------------------------------------
# Exception class (task 6.1)
# ---------------------------------------------------------------------------


class MessageValidationError(Exception):
    """Raised when a raw dict does not conform to the AgentMessage schema (Req 6.2, 6.3).

    Carries per-field validation errors so callers can report each failed field
    to the sender without delivering the message.
    """

    def __init__(self, errors: tuple[FieldError, ...]) -> None:
        self.field_errors = errors
        detail = "; ".join(f"{e.loc}: {e.message}" for e in errors)
        super().__init__(f"AgentMessage validation failed: {detail}")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldError:
    """A single schema violation, naming the offending field (Req 6.3).

    ``loc`` is the dotted path to the field that failed validation (e.g.
    ``"task_id"`` or ``"type"``), and ``message`` is the human-readable reason.
    """

    loc: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    """Typed outcome of validating a candidate Agent_Message (Req 6.2, 6.3).

    ``ok`` is ``True`` only when the candidate conforms to the ``AgentMessage``
    schema; in that case ``message`` holds the validated model. When ``ok`` is
    ``False``, ``errors`` names every field that failed and ``message`` is
    ``None``. This lets the Message_Bus deliver iff ``ok`` and otherwise return
    the validation errors to the sender (Property 17).
    """

    ok: bool
    message: AgentMessage | None = None
    errors: tuple[FieldError, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _format_loc(loc: tuple[object, ...]) -> str:
    """Render a Pydantic error location tuple as a dotted/indexed path."""
    parts: list[str] = []
    for item in loc:
        if isinstance(item, int):
            parts.append(f"[{item}]")
        elif parts:
            parts.append(f".{item}")
        else:
            parts.append(str(item))
    return "".join(parts) if parts else "__root__"


# ---------------------------------------------------------------------------
# Primary API (task 6.1)
# ---------------------------------------------------------------------------


def validate_message(data: dict) -> AgentMessage:
    """Validate a raw dict against the AgentMessage schema (Req 6.1, 6.2, 6.3).

    Returns a validated :class:`~maos.contracts.messaging.AgentMessage` on
    success. Raises :class:`MessageValidationError` with per-field errors if
    the data does not conform to the schema.

    This is a PURE function: no I/O, no side-effects, no registry lookups.
    """
    try:
        return AgentMessage.model_validate(data)
    except ValidationError as exc:
        errors = tuple(
            FieldError(loc=_format_loc(err["loc"]), message=err["msg"])
            for err in exc.errors()
        )
        raise MessageValidationError(errors) from exc


def serialize_message(msg: AgentMessage) -> bytes:
    """Serialize a valid AgentMessage to bytes (Req 6.4, 6.5).

    Uses Pydantic v2's stable JSON encoding so that every field — including the
    ``MessageType`` enum and the ``created_at`` datetime — is represented in a
    form that :func:`deserialize_message` can reconstruct exactly, yielding
    round-trip equality. The output is deterministic for a given message.

    Preserves ``task_id``, ``subtask_id``, and ``sub_subtask_id`` (Req 6.4).
    """
    return msg.model_dump_json().encode("utf-8")


def deserialize_message(raw: bytes) -> AgentMessage:
    """Deserialize bytes back to an AgentMessage (Req 6.5).

    For any valid message ``m``,
    ``deserialize_message(serialize_message(m)) == m`` (round-trip property).

    The trace identifiers ``task_id`` / ``subtask_id`` / ``sub_subtask_id`` are
    preserved on deserialization (Req 6.4, Property 18).

    Raises ``pydantic.ValidationError`` if ``raw`` does not conform to the
    schema.
    """
    return AgentMessage.model_validate_json(raw)


# ---------------------------------------------------------------------------
# Legacy API (preserved for backward compatibility)
# ---------------------------------------------------------------------------


def validate(candidate: object) -> ValidationResult:
    """Validate ``candidate`` against the Agent_Message schema (Req 6.2, 6.3).

    Accepts either a raw mapping/object or an existing ``AgentMessage`` and
    returns a :class:`ValidationResult`. On success the result carries the
    validated, normalized ``AgentMessage`` (preserving the trace identifiers per
    Req 6.4). On failure it carries a ``FieldError`` for every field that did not
    conform, so the caller can name each failed field without delivering the
    message (Property 17). This function is pure and does not mutate ``candidate``.
    """
    try:
        message = AgentMessage.model_validate(candidate)
    except ValidationError as exc:
        errors = tuple(
            FieldError(loc=_format_loc(err["loc"]), message=err["msg"])
            for err in exc.errors()
        )
        return ValidationResult(ok=False, message=None, errors=errors)
    return ValidationResult(ok=True, message=message, errors=())


def serialize(msg: AgentMessage) -> bytes:
    """Serialize an Agent_Message to bytes (Req 6.5).

    Uses Pydantic v2's stable JSON encoding so that every field — including the
    ``MessageType`` enum and the ``created_at`` datetime — is represented in a
    form that :func:`deserialize` can reconstruct exactly, yielding round-trip
    equality (Property 19). The output is deterministic for a given message.
    """
    return msg.model_dump_json().encode("utf-8")


def deserialize(raw: bytes) -> AgentMessage:
    """Deserialize bytes produced by :func:`serialize` back to an Agent_Message.

    For any valid message ``m``, ``deserialize(serialize(m)) == m`` (Req 6.5,
    Property 19), and the trace identifiers ``task_id`` / ``subtask_id`` /
    ``sub_subtask_id`` are preserved (Req 6.4, Property 18). Raises
    ``pydantic.ValidationError`` if ``raw`` does not conform to the schema.
    """
    return AgentMessage.model_validate_json(raw)
