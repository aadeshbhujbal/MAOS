"""Failed-unit reassignment selection (pure core).

This module implements the deterministic reassignment rule the
Sub_Orchestrator uses to select an alternative Subagent when a Sub_Subtask
fails (Req 11.2).

**Reassignment rule:** Given a failed Sub_Subtask whose ``attempts`` counter
and ``assigned_subagent_id`` are populated:

1. If ``attempts >= max_attempts``, return ``None`` (cap reached, no retry).
2. Filter candidates to those that match the Sub_Subtask's
   ``platform_system``, ``required_skill``, ``mode``, have
   ``status == "available"``, AND are **not** the currently assigned agent
   (``assigned_subagent_id``).
3. Among the remaining candidates, select exactly one using the same
   deterministic selection rule as :func:`~maos.core.selection.select_subagent`
   (highest ``selection_priority``, tie-break by smallest ``subagent_id``).
4. Return the selected :class:`SubagentSpec`, or ``None`` if no alternative
   exists.

The function is **pure**, **total**, and **side-effect-free**.
"""

from __future__ import annotations

from maos.contracts.agents import SubagentSpec
from maos.contracts.work_units import SubSubtask
from maos.core.selection import select_subagent


def select_reassignment(
    failed_sub_subtask: SubSubtask,
    candidates: list[SubagentSpec],
    max_attempts: int,
) -> SubagentSpec | None:
    """Select an alternative Subagent for a failed Sub_Subtask (Req 11.2).

    Given a failed Sub_Subtask whose ``attempts`` counter and
    ``assigned_subagent_id`` are populated, applies the reassignment rule:

    1. Returns ``None`` if ``failed_sub_subtask.attempts >= max_attempts``
       (cap reached, no reassignment).
    2. Filters ``candidates`` to those matching the Sub_Subtask's
       ``platform_system``, ``required_skill``, ``mode``, with
       ``status == "available"``, excluding the currently assigned agent.
    3. Selects one candidate using the same deterministic rule as
       :func:`~maos.core.selection.select_subagent` (highest
       ``selection_priority``, tie-break by smallest ``subagent_id``).

    Args:
        failed_sub_subtask: The Sub_Subtask that has failed and needs
            reassignment. Must have ``attempts`` and ``assigned_subagent_id``
            populated.
        candidates: The list of candidate Subagent specifications to choose
            from.
        max_attempts: The configured maximum number of attempts. If the
            Sub_Subtask's ``attempts`` has reached this cap, no reassignment
            is performed.

    Returns:
        The selected :class:`SubagentSpec` for reassignment, or ``None`` if
        the attempt cap is reached or no alternative candidate exists.
    """
    # 1. Cap check — no reassignment if max attempts reached.
    if failed_sub_subtask.attempts >= max_attempts:
        return None

    # 2. Exclude the currently assigned agent from candidates.
    current_agent_id = failed_sub_subtask.assigned_subagent_id
    filtered_candidates = [
        spec
        for spec in candidates
        if spec.subagent_id != current_agent_id
    ]

    # 3. Reuse the deterministic selection rule from the selection module.
    return select_subagent(
        candidates=filtered_candidates,
        platform_system=failed_sub_subtask.platform_system,
        skill_id=failed_sub_subtask.required_skill,
        mode=failed_sub_subtask.mode,
    )
