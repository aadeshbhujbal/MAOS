"""Task decomposition and routing (pure core).

This module holds the side-effect-free logic the Root_Orchestrator uses to turn
an accepted, valid :class:`~maos.contracts.work_units.Task` into one or more
:class:`~maos.contracts.work_units.Subtask` records, and to compute which
Sub_Orchestrator a Subtask is bound to.

Implemented here (task 3.3):

- **Classification + decomposition (Req 1.3):** classify a Task to the set of
  Platform_Systems it targets and produce exactly one Subtask per target
  Platform_System, so every Subtask targets *exactly one* Platform_System.
- **Traceable identifiers (Req 1.4):** assign each Subtask a unique
  ``subtask_id`` that is traceable to the originating ``task_id``.
- **Mode / tenant propagation (Req 1.6):** copy the Task's ``mode`` and
  ``tenant_id`` onto every derived Subtask.
- **Routing target (Req 2.1):** compute the Sub_Orchestrator bound to a
  Subtask's ``platform_system`` (the orchestrator the Subtask routes to).

Everything in this module is **pure**: no I/O, no global mutation, and
deterministic given its inputs. Identifier generation is injected (or uses a
deterministic default scheme) so Hypothesis property tests are reproducible.

Note:
    Subtask -> Sub_Subtask decomposition and the full traceability-chain builder
    are added separately (task 3.6) and append to this module without modifying
    the Task -> Subtask logic below.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

from maos.contracts.work_units import (
    PlatformSystem,
    Subtask,
    Task,
)

# ---------------------------------------------------------------------------
# Task -> Subtask decomposition (Req 1.3, 1.4, 1.6) and routing (Req 2.1)
# ---------------------------------------------------------------------------

#: Payload key a Requester may use to declare target Platform_Systems explicitly.
#: When present and resolvable, it takes precedence over keyword classification.
TARGET_SYSTEMS_KEY = "target_systems"

#: Prefix for the deterministic Sub_Orchestrator identifier scheme (Req 2.1).
SUB_ORCHESTRATOR_ID_PREFIX = "sub-orchestrator"

#: Canonical ordering of Platform_Systems. Decomposition always emits Subtasks
#: in this order so the output is independent of input/classification order.
_CANONICAL_ORDER: tuple[PlatformSystem, ...] = tuple(PlatformSystem)

#: Lower-cased keyword hints used to classify a Task when no explicit
#: ``target_systems`` declaration is provided. Deterministic and order-stable.
_KEYWORD_MAP: dict[PlatformSystem, tuple[str, ...]] = {
    PlatformSystem.BACKEND: (
        "backend",
        "nestjs",
        "nest.js",
        "healthcarebackend",
        "server-side",
        "server side",
    ),
    PlatformSystem.WEB: (
        "web",
        "next.js",
        "nextjs",
        "frontend-web",
        "frontend web",
        "browser",
    ),
    PlatformSystem.MOBILE: (
        "mobile",
        "expo",
        "react native",
        "react-native",
        "ios",
        "android",
    ),
}

#: Signature of an injectable Subtask-id generator: ``(task_id, platform) -> id``.
SubtaskIdFactory = Callable[[str, PlatformSystem], str]


class DecompositionError(ValueError):
    """Raised when a Task cannot be decomposed into at least one Subtask.

    A valid, accepted Task is expected to map to at least one Platform_System
    (the unmappable case is rejected earlier as an unsupported-task error,
    Req 1.5). This guards the invariant that decomposition yields *one or more*
    Subtasks (Req 1.3).
    """


def default_subtask_id(task_id: str, platform_system: PlatformSystem) -> str:
    """Deterministically derive a traceable ``subtask_id`` (Req 1.4).

    The scheme embeds the originating ``task_id`` so the Subtask is traceable to
    its Task, and the ``platform_system`` so the identifier is unique among the
    Subtasks of a single Task (decomposition produces at most one Subtask per
    Platform_System).

    Args:
        task_id: The originating Task identifier.
        platform_system: The Platform_System the Subtask targets.

    Returns:
        A deterministic identifier of the form ``"{task_id}::subtask::{system}"``.
    """
    return f"{task_id}::subtask::{platform_system.value}"


def _coerce_platform_system(value: object) -> PlatformSystem | None:
    """Best-effort, case-insensitive coercion of a value to a PlatformSystem.

    Accepts an existing :class:`PlatformSystem`, or a string matching either the
    enum value or name (e.g. ``"BACKEND"`` / ``"backend"``). Returns ``None`` for
    anything that does not resolve, so callers can ignore noise in the payload.
    """
    if isinstance(value, PlatformSystem):
        return value
    if isinstance(value, str):
        normalized = value.strip().upper()
        for system in _CANONICAL_ORDER:
            if normalized == system.value or normalized == system.name:
                return system
    return None


def _explicit_target_systems(payload: Mapping[str, object]) -> list[PlatformSystem]:
    """Resolve an explicit ``target_systems`` declaration to canonical order."""
    declared = payload.get(TARGET_SYSTEMS_KEY)
    if not isinstance(declared, (list, tuple, set, frozenset)):
        return []
    resolved: set[PlatformSystem] = set()
    for entry in declared:
        system = _coerce_platform_system(entry)
        if system is not None:
            resolved.add(system)
    return [system for system in _CANONICAL_ORDER if system in resolved]


def _keyword_target_systems(task: Task) -> list[PlatformSystem]:
    """Classify a Task to Platform_Systems by scanning its text for keywords."""
    haystack = f"{task.title}\n{task.description}".lower()
    return [
        system
        for system in _CANONICAL_ORDER
        if any(keyword in haystack for keyword in _KEYWORD_MAP[system])
    ]


def classify_target_systems(task: Task) -> list[PlatformSystem]:
    """Classify a Task to the Platform_Systems it targets (Req 1.3).

    Resolution is deterministic and returns Platform_Systems in canonical order
    with no duplicates:

    1. If the Task ``payload`` declares ``target_systems`` and at least one entry
       resolves to a Platform_System, that declaration is authoritative.
    2. Otherwise the Task ``title`` and ``description`` are scanned for the
       per-system keyword hints.

    The result may be empty when nothing matches; :func:`decompose_task` treats
    an empty classification as a :class:`DecompositionError`.

    Args:
        task: The valid Task to classify.

    Returns:
        The targeted Platform_Systems in canonical order, without duplicates.
    """
    explicit = _explicit_target_systems(task.payload)
    if explicit:
        return explicit
    return _keyword_target_systems(task)


def decompose_task(
    task: Task,
    *,
    id_factory: SubtaskIdFactory = default_subtask_id,
    target_systems: Iterable[PlatformSystem] | None = None,
) -> list[Subtask]:
    """Decompose a valid Task into one Subtask per target Platform_System.

    Each produced Subtask targets exactly one Platform_System (Req 1.3), carries
    a unique identifier traceable to the originating ``task_id`` (Req 1.4), and
    inherits the Task's ``mode`` and ``tenant_id`` (Req 1.6). Subtasks are
    returned in canonical Platform_System order, independent of classification
    or input order.

    Args:
        task: The valid, accepted Task to decompose.
        id_factory: Injectable generator for Subtask identifiers; defaults to the
            deterministic :func:`default_subtask_id` scheme. Receives
            ``(task_id, platform_system)`` and must return a unique, traceable id.
        target_systems: Optional explicit set of target Platform_Systems. When
            omitted, the targets are derived via :func:`classify_target_systems`.

    Returns:
        A list of one or more Subtasks, one per distinct target Platform_System,
        in canonical order.

    Raises:
        DecompositionError: If no target Platform_System can be determined, so the
            Task cannot yield at least one Subtask.
    """
    if target_systems is None:
        systems = classify_target_systems(task)
    else:
        # Deduplicate and impose canonical order so output is order-independent.
        requested = set(target_systems)
        systems = [system for system in _CANONICAL_ORDER if system in requested]

    if not systems:
        raise DecompositionError(
            f"Task {task.task_id!r} could not be mapped to any Platform_System; "
            "it cannot be decomposed into at least one Subtask."
        )

    return [
        Subtask(
            subtask_id=id_factory(task.task_id, system),
            task_id=task.task_id,           # traceable to the Task (Req 1.4)
            platform_system=system,         # exactly one Platform_System (Req 1.3)
            mode=task.mode,                 # propagated from the Task (Req 1.6)
            tenant_id=task.tenant_id,       # propagated from the Task (Req 1.6)
            input_contract=dict(task.payload),
        )
        for system in systems
    ]


def bound_sub_orchestrator(platform_system: PlatformSystem) -> str:
    """Return the identifier of the Sub_Orchestrator bound to a Platform_System.

    Each Sub_Orchestrator is bound to exactly one Platform_System, so this is a
    deterministic, total mapping from Platform_System to Sub_Orchestrator id.

    Args:
        platform_system: The Platform_System whose bound Sub_Orchestrator is wanted.

    Returns:
        A deterministic identifier of the form
        ``"sub-orchestrator::{platform_system}"``.
    """
    return f"{SUB_ORCHESTRATOR_ID_PREFIX}::{platform_system.value}"


def route_target(subtask: Subtask) -> str:
    """Compute the Sub_Orchestrator a Subtask routes to (Req 2.1).

    A Subtask routes to the Sub_Orchestrator bound to its ``platform_system``;
    this function returns that bound Sub_Orchestrator's identifier.

    Args:
        subtask: The Subtask to route.

    Returns:
        The identifier of the bound Sub_Orchestrator.
    """
    return bound_sub_orchestrator(subtask.platform_system)


def route_subtask_target(subtask: Subtask) -> PlatformSystem:
    """Return the routing target for a Subtask — its Platform_System (Req 2.1).

    This is the explicit routing-target concept from the design: each Subtask
    targets exactly one Platform_System, and the routing target is simply that
    Platform_System. The function is trivial by design (it reads
    ``subtask.platform_system``), but provides a named, typed entry point that
    makes the routing-target concept explicit in the codebase.

    Args:
        subtask: The Subtask whose routing target is needed.

    Returns:
        The :class:`PlatformSystem` that the Subtask targets.
    """
    return subtask.platform_system


# ---------------------------------------------------------------------------
# Subtask -> Sub_Subtask decomposition and traceability chain (task 3.6)
# ---------------------------------------------------------------------------

from maos.contracts.work_units import SubSubtask

#: Signature of an injectable SubSubtask-id generator: ``(subtask_id, skill) -> id``.
SubSubtaskIdFactory = Callable[[str, str], str]


def _default_sub_subtask_id(subtask_id: str, skill: str) -> str:
    """Deterministically derive a traceable ``sub_subtask_id`` (Req 2.2).

    The scheme embeds the originating ``subtask_id`` and the ``skill`` so the
    SubSubtask is traceable to its Subtask and unique among siblings.

    Args:
        subtask_id: The originating Subtask identifier.
        skill: The required skill for this SubSubtask.

    Returns:
        A deterministic identifier of the form ``"{subtask_id}::sub_subtask::{skill}"``.
    """
    return f"{subtask_id}::sub_subtask::{skill}"


def decompose_subtask(
    subtask: Subtask,
    required_skills: list[str],
    *,
    id_factory: SubSubtaskIdFactory | None = None,
) -> list[SubSubtask]:
    """Decompose a Subtask into one Sub_Subtask per required skill (Req 2.2, 3.1).

    Each produced SubSubtask targets exactly one skill, carries a unique
    identifier traceable to both the originating ``subtask_id`` and ``task_id``
    (Req 2.2), and inherits the Subtask's ``platform_system``, ``mode``, and
    ``tenant_id``.

    Args:
        subtask: The Subtask to decompose.
        required_skills: The list of skills that must be covered. One SubSubtask
            is created per skill.
        id_factory: Injectable generator for SubSubtask identifiers; defaults to
            the deterministic :func:`_default_sub_subtask_id` scheme. Receives
            ``(subtask_id, skill)`` and must return a unique, traceable id.

    Returns:
        A list of SubSubtasks, one per required skill, in the order the skills
        are provided.
    """
    factory = id_factory if id_factory is not None else _default_sub_subtask_id

    return [
        SubSubtask(
            sub_subtask_id=factory(subtask.subtask_id, skill),
            subtask_id=subtask.subtask_id,          # traceable to Subtask (Req 2.2)
            task_id=subtask.task_id,                 # traceable to Task (Req 2.2)
            platform_system=subtask.platform_system, # propagated from Subtask
            mode=subtask.mode,                       # propagated from Subtask
            tenant_id=subtask.tenant_id,             # propagated from Subtask
            required_skill=skill,
            input_contract=dict(subtask.input_contract),
        )
        for skill in required_skills
    ]


def build_traceability_chain(
    task: Task,
    subtasks: list[Subtask],
    sub_subtasks: list[SubSubtask],
) -> dict:
    """Build the full hierarchical traceability chain (Req 2.2, 3.1, 3.4).

    Returns a dictionary representing the Task → Subtask → SubSubtask hierarchy
    with platform_system and assigned_subagent_id preserved at each level,
    enabling full traceability resolution from any node.

    Args:
        task: The root Task.
        subtasks: All Subtasks derived from the Task.
        sub_subtasks: All SubSubtasks derived from the Subtasks.

    Returns:
        A dict of the form::

            {
                "task_id": "<task_id>",
                "subtasks": [
                    {
                        "subtask_id": "<subtask_id>",
                        "platform_system": "<platform_system>",
                        "sub_subtasks": [
                            {
                                "sub_subtask_id": "<sub_subtask_id>",
                                "platform_system": "<platform_system>",
                                "assigned_subagent_id": "<agent_id or None>",
                            },
                            ...
                        ],
                    },
                    ...
                ],
            }
    """
    # Index sub_subtasks by their parent subtask_id for efficient lookup.
    sub_subtasks_by_subtask: dict[str, list[dict]] = {}
    for sst in sub_subtasks:
        entry = {
            "sub_subtask_id": sst.sub_subtask_id,
            "platform_system": sst.platform_system.value,
            "assigned_subagent_id": sst.assigned_subagent_id,
        }
        sub_subtasks_by_subtask.setdefault(sst.subtask_id, []).append(entry)

    subtask_entries = []
    for st in subtasks:
        subtask_entries.append({
            "subtask_id": st.subtask_id,
            "platform_system": st.platform_system.value,
            "sub_subtasks": sub_subtasks_by_subtask.get(st.subtask_id, []),
        })

    return {
        "task_id": task.task_id,
        "subtasks": subtask_entries,
    }
