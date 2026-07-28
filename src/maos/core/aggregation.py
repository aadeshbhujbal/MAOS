"""Result aggregation across the work-unit hierarchy (pure core).

This module implements the two pure aggregation functions that produce the
Subtask-level and Task-level result summaries:

- :func:`aggregate_subtask` — combines a list of terminal
  :class:`~maos.contracts.results.SubSubtaskResult` into a single
  :class:`~maos.contracts.results.SubtaskResult` (Req 12.1).
- :func:`aggregate_task` — combines a list of terminal
  :class:`~maos.contracts.results.SubtaskResult` into a single
  :class:`~maos.contracts.results.TaskResult` (Req 12.2, 12.3, 12.4).

**Aggregation rules:**

1. Every unit's status and identifiers — including ``permanently_failed`` ones —
   are included in the result (Req 11.6, 12.3).
2. The aggregated ``state`` is determined by:
   - ``completed`` — iff every child unit is ``completed``.
   - ``permanently_failed`` — if any child is ``permanently_failed``.
   - ``failed`` — otherwise (mix of terminal states none of which are
     ``permanently_failed``).
3. The ``TaskResult`` references the originating ``task_id`` (Req 12.4).

Both functions are **pure** — total, side-effect-free, and deterministic.
"""

from __future__ import annotations

from datetime import UTC, datetime

from maos.contracts.results import SubSubtaskResult, SubtaskResult, TaskResult
from maos.contracts.work_units import PlatformSystem, WorkUnitState


def _compute_aggregate_state(child_states: list[WorkUnitState]) -> WorkUnitState:
    """Derive a parent state from its children's terminal states.

    Rules:
    - All completed → completed.
    - Any permanently_failed → permanently_failed (Req 11.6).
    - Otherwise → failed.
    """
    if not child_states:
        # Edge case: no children means nothing to aggregate; treat as completed.
        return WorkUnitState.COMPLETED

    all_completed = all(s == WorkUnitState.COMPLETED for s in child_states)
    if all_completed:
        return WorkUnitState.COMPLETED

    any_permanently_failed = any(
        s == WorkUnitState.PERMANENTLY_FAILED for s in child_states
    )
    if any_permanently_failed:
        return WorkUnitState.PERMANENTLY_FAILED

    return WorkUnitState.FAILED


def aggregate_subtask(
    results: list[SubSubtaskResult],
    platform_system: PlatformSystem | None = None,
) -> SubtaskResult:
    """Aggregate Sub_Subtask results into a single Subtask result (Req 12.1).

    Combines all terminal :class:`SubSubtaskResult` instances belonging to a
    single Subtask into a :class:`SubtaskResult`. Every unit's status and
    identifiers are preserved — including ``permanently_failed`` ones
    (Req 11.6, 12.3).

    The aggregated Subtask ``state`` follows the rules in
    :func:`_compute_aggregate_state`.

    Args:
        results: Terminal results from all Sub_Subtasks of one Subtask.
            Must be non-empty and share the same ``subtask_id`` and ``task_id``.
        platform_system: The Platform_System of the owning Subtask. If not
            supplied, defaults to :attr:`PlatformSystem.BACKEND`. The
            Sub_Orchestrator always knows its own platform and should pass it.

    Returns:
        A :class:`SubtaskResult` with the aggregated state and per-Sub_Subtask
        statuses.

    Raises:
        ValueError: If ``results`` is empty.
    """
    if not results:
        raise ValueError("Cannot aggregate an empty list of Sub_Subtask results.")

    subtask_id = results[0].subtask_id
    task_id = results[0].task_id

    if platform_system is None:
        platform_system = PlatformSystem.BACKEND

    child_states = [r.state for r in results]
    aggregated_state = _compute_aggregate_state(child_states)

    return SubtaskResult(
        subtask_id=subtask_id,
        task_id=task_id,
        platform_system=platform_system,
        state=aggregated_state,
        sub_subtask_results=list(results),
    )


def aggregate_task(
    subtask_results: list[SubtaskResult],
    task_id: str,
) -> TaskResult:
    """Aggregate Subtask results into a single Task result (Req 12.2, 12.3, 12.4).

    Combines all terminal :class:`SubtaskResult` instances belonging to a
    single Task into a :class:`TaskResult`. The result includes:

    - The status of each Subtask and each Sub_Subtask together with their
      associated identifiers (Req 12.3).
    - A reference to the originating ``task_id`` (Req 12.4).
    - All ``permanently_failed`` units are preserved to inform the Requester
      about partial failures (Req 11.6).

    The aggregated Task ``state`` follows the rules in
    :func:`_compute_aggregate_state`.

    Args:
        subtask_results: Terminal results from all Subtasks of one Task. May be
            empty (in which case the Task is considered completed with no work).
        task_id: The originating Task identifier (Req 12.4).

    Returns:
        A :class:`TaskResult` referencing the originating ``task_id`` with the
        aggregated state and per-Subtask/per-Sub_Subtask statuses.
    """
    child_states = [r.state for r in subtask_results]
    aggregated_state = _compute_aggregate_state(child_states)

    return TaskResult(
        task_id=task_id,
        state=aggregated_state,
        subtask_results=list(subtask_results),
        created_at=datetime.now(tz=UTC),
    )
