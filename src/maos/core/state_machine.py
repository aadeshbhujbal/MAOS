"""Work-unit state machine (pure orchestration core).

Every work unit (Subtask and Sub_Subtask) moves through a single explicit
lifecycle. This module encodes that lifecycle as:

1. A **state-to-targets** table (:data:`LEGAL_TRANSITIONS`) listing, for each
   source state, the set of legal destination states.
2. An **event-driven transition table** (:data:`EVENT_TRANSITIONS`) mapping
   ``(current_state, event)`` pairs to a concrete next state.

Two pure, deterministic application functions are provided:

- :func:`apply_transition` — takes a target state and returns it when the
  transition is legal.
- :func:`apply_event` — takes a named event string and returns the resolved
  next state, or raises :class:`IllegalTransitionError` when no rule matches.

The logic here performs no I/O, holds no state, and depends only on its
arguments, so the correctness property (design Property 7) is directly
executable with Hypothesis.

Legal transitions (design "(d) Work-Unit State Machine"; Req 2.7):

- ``assigned``           -> ``in_progress``        (subagent starts)
- ``assigned``           -> ``awaiting_approval``  (sensitive action gate)
- ``awaiting_approval``  -> ``in_progress``        (Human_Approval granted)
- ``awaiting_approval``  -> ``failed``             (approval denied / window elapsed)
- ``in_progress``        -> ``completed``          (result conforms to output contract)
- ``in_progress``        -> ``failed``             (error)
- ``in_progress``        -> ``timed_out``          (no response within timeout)
- ``timed_out``          -> ``failed``             (counts as failed attempt — automatic)
- ``failed``             -> ``assigned``           (reassigned: alt subagent, attempts left)
- ``failed``             -> ``permanently_failed`` (max attempts reached / no alternative)

``completed`` and ``permanently_failed`` are terminal: they have no outgoing
transitions.

Scope note: this module governs *which* transitions are legal. Attempt and
timeout accounting (Req 11.3 / 11.4) — counting a ``timed_out`` as a failed
attempt and enforcing the attempt cap before allowing
``failed -> permanently_failed`` — is layered on top of this table elsewhere and
is deliberately not implemented here.

Requirements:
- Req 2.7 — while a Subtask or Sub_Subtask is assigned but not yet completed,
  the responsible orchestrator tracks its status as one of the defined states,
  and every state change must be a legal transition.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from maos.contracts.work_units import WorkUnitState

__all__ = [
    "EVENT_TRANSITIONS",
    "LEGAL_TRANSITIONS",
    "IllegalTransitionError",
    "apply_event",
    "apply_transition",
    "handle_timeout",
    "is_legal_transition",
    "is_terminal",
    "legal_targets",
    "record_attempt",
    "should_permanently_fail",
]


# ---------------------------------------------------------------------------
# State-to-targets table
# ---------------------------------------------------------------------------

# The legal transition table, keyed by source state. Each value is the frozen
# set of states that source state may transition to. States absent as a key, or
# mapped to an empty set, are terminal (``completed``, ``permanently_failed``).
# Wrapped in a read-only mapping so the table cannot be mutated at runtime,
# keeping the state machine deterministic and tamper-proof.
LEGAL_TRANSITIONS: Mapping[WorkUnitState, frozenset[WorkUnitState]] = MappingProxyType(
    {
        WorkUnitState.ASSIGNED: frozenset(
            {WorkUnitState.IN_PROGRESS, WorkUnitState.AWAITING_APPROVAL}
        ),
        WorkUnitState.AWAITING_APPROVAL: frozenset(
            {WorkUnitState.IN_PROGRESS, WorkUnitState.FAILED}
        ),
        WorkUnitState.IN_PROGRESS: frozenset(
            {
                WorkUnitState.COMPLETED,
                WorkUnitState.FAILED,
                WorkUnitState.TIMED_OUT,
            }
        ),
        WorkUnitState.TIMED_OUT: frozenset({WorkUnitState.FAILED}),
        WorkUnitState.FAILED: frozenset(
            {WorkUnitState.ASSIGNED, WorkUnitState.PERMANENTLY_FAILED}
        ),
        WorkUnitState.COMPLETED: frozenset(),
        WorkUnitState.PERMANENTLY_FAILED: frozenset(),
    }
)


# ---------------------------------------------------------------------------
# Event-driven transition table
# ---------------------------------------------------------------------------

# Maps (current_state, event_name) -> next_state.
# Each key is a tuple of (WorkUnitState, str) and the value is the resulting
# WorkUnitState. Events are named after the triggering condition from the
# design's state-machine diagram.
EVENT_TRANSITIONS: Mapping[
    tuple[WorkUnitState, str], WorkUnitState
] = MappingProxyType(
    {
        # assigned → in_progress (subagent starts)
        (WorkUnitState.ASSIGNED, "subagent_starts"): WorkUnitState.IN_PROGRESS,
        # assigned → awaiting_approval (sensitive action gate)
        (WorkUnitState.ASSIGNED, "sensitive_action_gate"): WorkUnitState.AWAITING_APPROVAL,
        # awaiting_approval → in_progress (approval granted)
        (WorkUnitState.AWAITING_APPROVAL, "approval_granted"): WorkUnitState.IN_PROGRESS,
        # awaiting_approval → failed (approval denied / window elapsed)
        (WorkUnitState.AWAITING_APPROVAL, "approval_denied"): WorkUnitState.FAILED,
        # in_progress → completed (result conforms)
        (WorkUnitState.IN_PROGRESS, "result_conforms"): WorkUnitState.COMPLETED,
        # in_progress → failed (error)
        (WorkUnitState.IN_PROGRESS, "error"): WorkUnitState.FAILED,
        # in_progress → timed_out (timeout)
        (WorkUnitState.IN_PROGRESS, "timeout"): WorkUnitState.TIMED_OUT,
        # timed_out → failed (counts as failed attempt — automatic transition)
        (WorkUnitState.TIMED_OUT, "failed_attempt"): WorkUnitState.FAILED,
        # failed → assigned (reassigned, alt subagent, attempts left)
        (WorkUnitState.FAILED, "reassigned"): WorkUnitState.ASSIGNED,
        # failed → permanently_failed (max attempts or no alternative)
        (WorkUnitState.FAILED, "max_attempts_reached"): WorkUnitState.PERMANENTLY_FAILED,
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class IllegalTransitionError(ValueError):
    """Raised when a work-unit transition is not permitted by the state machine.

    Carries the offending ``current`` and ``target`` states (or the event name)
    so callers can report exactly which transition was rejected (Req 2.7).
    Subclasses :class:`ValueError` so existing ``ValueError`` handlers still
    catch it.
    """

    def __init__(
        self,
        current: WorkUnitState,
        target: WorkUnitState | None = None,
        *,
        event: str | None = None,
    ) -> None:
        self.current = current
        self.target = target
        self.event = event
        if event is not None:
            msg = (
                f"illegal work-unit transition: no rule for "
                f"({current.value}, {event!r})"
            )
        else:
            msg = f"illegal work-unit transition: {current.value} -> {target.value if target else '?'}"
        super().__init__(msg)


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def legal_targets(current: WorkUnitState) -> frozenset[WorkUnitState]:
    """Return the set of states ``current`` may legally transition to (Req 2.7).

    Terminal states return an empty frozenset.
    """
    return LEGAL_TRANSITIONS.get(current, frozenset())


def is_terminal(state: WorkUnitState) -> bool:
    """Return True iff ``state`` has no legal outgoing transitions (Req 2.7).

    The terminal states are ``completed`` and ``permanently_failed``.
    """
    return not legal_targets(state)


def is_legal_transition(current: WorkUnitState, target: WorkUnitState) -> bool:
    """Return True iff transitioning ``current`` -> ``target`` is permitted (Req 2.7)."""
    return target in legal_targets(current)


# ---------------------------------------------------------------------------
# Transition application (target-based)
# ---------------------------------------------------------------------------


def apply_transition(
    current: WorkUnitState, target: WorkUnitState
) -> WorkUnitState:
    """Apply a transition to ``current``, returning the next state (Req 2.7).

    Pure and deterministic. When ``current`` -> ``target`` is one of the legal
    transitions in :data:`LEGAL_TRANSITIONS`, returns ``target``. Otherwise
    raises :class:`IllegalTransitionError` and leaves the state unchanged (the
    function never mutates its arguments — :class:`WorkUnitState` is immutable —
    so "unchanged" is guaranteed by construction).

    Args:
        current: The work unit's current lifecycle state.
        target: The state the caller wishes to transition to.

    Returns:
        ``target`` when the transition is legal.

    Raises:
        IllegalTransitionError: When the transition is not permitted, including
            any transition out of a terminal state.
    """
    if not is_legal_transition(current, target):
        raise IllegalTransitionError(current, target)
    return target


# ---------------------------------------------------------------------------
# Transition application (event-based)
# ---------------------------------------------------------------------------


def apply_event(current_state: WorkUnitState, event: str) -> WorkUnitState:
    """Apply a named event to ``current_state``, returning the next state (Req 2.7).

    Looks up the ``(current_state, event)`` pair in :data:`EVENT_TRANSITIONS`
    and returns the mapped next state. If no rule exists for the pair, raises
    :class:`IllegalTransitionError`.

    This is the event-driven complement to :func:`apply_transition`: instead of
    the caller specifying the desired *target* state, the caller names the
    *event* that occurred and the state machine resolves the correct target.

    Args:
        current_state: The work unit's current lifecycle state.
        event: The event name that has occurred (e.g. ``"subagent_starts"``,
            ``"approval_granted"``, ``"error"``, ``"timeout"``).

    Returns:
        The next :class:`~maos.contracts.work_units.WorkUnitState`.

    Raises:
        IllegalTransitionError: When no ``(current_state, event)`` rule exists
            in the transition table.
    """
    key = (current_state, event)
    next_state = EVENT_TRANSITIONS.get(key)
    if next_state is None:
        raise IllegalTransitionError(current_state, event=event)
    return next_state


# ---------------------------------------------------------------------------
# Attempt and timeout accounting (Req 11.3, 11.4)
# ---------------------------------------------------------------------------

from maos.contracts.work_units import SubSubtask


def record_attempt(sub_subtask: SubSubtask) -> SubSubtask:
    """Return a new SubSubtask with ``attempts`` incremented by 1 (Req 11.3).

    Uses an immutable pattern — creates a shallow copy via ``model_copy`` so
    the original instance is never mutated.

    Args:
        sub_subtask: The current SubSubtask instance.

    Returns:
        A new :class:`~maos.contracts.work_units.SubSubtask` with
        ``attempts = sub_subtask.attempts + 1``.
    """
    return sub_subtask.model_copy(update={"attempts": sub_subtask.attempts + 1})


def should_permanently_fail(sub_subtask: SubSubtask, max_attempts: int) -> bool:
    """Return True if the sub_subtask has exhausted its attempt budget (Req 11.4).

    The work unit should be moved to ``permanently_failed`` when it has
    accumulated at least ``max_attempts`` failed attempts.

    Args:
        sub_subtask: The SubSubtask to inspect.
        max_attempts: The configured maximum number of attempts allowed.

    Returns:
        ``True`` when ``sub_subtask.attempts >= max_attempts``, else ``False``.
    """
    return sub_subtask.attempts >= max_attempts


def handle_timeout(
    sub_subtask: SubSubtask, max_attempts: int
) -> tuple[SubSubtask, WorkUnitState]:
    """Treat a timeout as a failed attempt and determine the next state (Req 11.3, 11.4).

    A timeout counts as one failed attempt. This function:
    1. Increments the attempt counter (via :func:`record_attempt`).
    2. Decides the resulting state:
       - ``permanently_failed`` if the attempt cap has been reached.
       - ``failed`` otherwise (allowing reassignment to another subagent).

    Args:
        sub_subtask: The SubSubtask that timed out.
        max_attempts: The configured maximum number of attempts allowed.

    Returns:
        A tuple of ``(updated_sub_subtask, next_state)`` where
        ``updated_sub_subtask`` has its ``attempts`` incremented and
        ``next_state`` is either
        :attr:`~maos.contracts.work_units.WorkUnitState.PERMANENTLY_FAILED` or
        :attr:`~maos.contracts.work_units.WorkUnitState.FAILED`.
    """
    updated = record_attempt(sub_subtask)
    if should_permanently_fail(updated, max_attempts):
        return updated, WorkUnitState.PERMANENTLY_FAILED
    return updated, WorkUnitState.FAILED
