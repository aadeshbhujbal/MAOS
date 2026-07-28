"""Deterministic Subagent selection (pure core).

This module implements the single, side-effect-free selection rule the
Sub_Orchestrator uses to choose exactly one Subagent for a Sub_Subtask
(Req 2.3, 2.5).

**Deterministic selection rule (Req 2.5):** among the candidate
:class:`~maos.contracts.agents.SubagentSpec` records whose ``platform_system``,
a declared ``skill_id``, and ``mode`` all match the target, and whose
``status == "available"``, choose the candidate with the highest
``selection_priority``; break ties by the lexicographically smallest
``subagent_id``. When no candidate matches, return ``None``.

The function is **total**, **side-effect-free**, and **order-independent**: its
result depends only on the *set* of candidates and the target, never on the
order in which candidates are supplied. This makes routing reproducible and
directly testable (design Properties 5 and 6).
"""

from __future__ import annotations

from collections.abc import Iterable

from maos.contracts.agents import SubagentSpec
from maos.contracts.work_units import OperatingMode, PlatformSystem

#: Operational status a Subagent must declare to be eligible for routing (Req 2.5).
AVAILABLE_STATUS = "available"


def _is_candidate(
    spec: SubagentSpec,
    platform_system: PlatformSystem,
    skill_id: str,
    mode: OperatingMode,
) -> bool:
    """Return True iff ``spec`` matches the target and is available (Req 2.3, 2.5)."""
    return (
        spec.status == AVAILABLE_STATUS
        and spec.platform_system == platform_system
        and spec.mode == mode
        and any(skill.skill_id == skill_id for skill in spec.skills)
    )


def select_subagent(
    candidates: Iterable[SubagentSpec],
    platform_system: PlatformSystem,
    skill_id: str,
    mode: OperatingMode,
) -> SubagentSpec | None:
    """Select one Subagent for a Sub_Subtask deterministically (Req 2.3, 2.5).

    Filters ``candidates`` to those whose ``platform_system`` matches
    ``platform_system``, that declare a Skill with ``skill_id``, whose ``mode``
    matches ``mode``, and whose ``status == "available"``. Among the survivors,
    returns the one with the highest ``selection_priority``, breaking ties by
    the lexicographically smallest ``subagent_id``. Returns ``None`` when no
    candidate matches.

    This is a **pure function** — total, side-effect-free, and deterministic
    regardless of the iteration order of ``candidates``. Its result depends only
    on the *set* of candidates and the target parameters.

    Args:
        candidates: The candidate Subagent specifications to choose from.
        platform_system: The target Platform_System the Subagent must be bound to.
        skill_id: The required Skill identifier the Subagent must declare.
        mode: The Agent_Operating_Mode the Subagent must match.

    Returns:
        The selected :class:`SubagentSpec`, or ``None`` if none matches.
    """
    matching = [
        spec
        for spec in candidates
        if _is_candidate(spec, platform_system, skill_id, mode)
    ]
    if not matching:
        return None
    # Highest selection_priority wins; ties broken by smallest subagent_id.
    return min(
        matching,
        key=lambda spec: (-spec.selection_priority, spec.subagent_id),
    )


# Backward-compatible alias.
select = select_subagent
