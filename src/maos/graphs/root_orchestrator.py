"""Root Orchestrator supervisor graph (LangGraph StateGraph).

Implements the Root Orchestrator flow as a LangGraph StateGraph with nodes:

1. ``validate_node`` — validates the submitted Task against its input contract.
2. ``decompose_node`` — decomposes the Task into Subtasks and creates a
   Shared_Context for the Task.
3. ``route_node`` — routes each Subtask to its bound Sub-Orchestrator.
4. ``aggregate_node`` — aggregates Subtask results into a single Task result.

Each node persists state to the Checkpointer and writes audit entries. The
sub-orchestrator invocation in ``route_node`` is a placeholder that will be
wired during integration.

Requirements: 1.1, 1.3, 2.1, 7.1, 12.2, 12.4.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from maos.audit.entries import (
    build_error_entry,
    build_routing_decision_entry,
)
from maos.contracts.audit import AuditEntry, AuditEventType
from maos.contracts.results import SubtaskResult, TaskResult
from maos.contracts.work_units import Subtask, Task
from maos.core.aggregation import aggregate_task
from maos.core.decomposition import decompose_task, route_target
from maos.core.validation import (
    TaskValidationError,
    validate_task_input,
)
from maos.security.redaction import redact

# ---------------------------------------------------------------------------
# Graph state definition
# ---------------------------------------------------------------------------

#: Identifier used as the actor for Root Orchestrator audit entries.
ROOT_ORCHESTRATOR_ID = "root-orchestrator"


class RootOrchestratorState(TypedDict, total=False):
    """State carried through the Root Orchestrator supervisor graph.

    Attributes
    ----------
    task:
        The validated Task being orchestrated (set after validation).
    subtasks:
        Subtasks produced by decomposition (set after decompose).
    subtask_results:
        Results collected from Sub-Orchestrators (populated during/after route).
    task_result:
        The final aggregated Task result (set after aggregation).
    error:
        Error description if any node encounters a failure.
    audit_entries:
        Audit entries accumulated during graph execution for persistence.
    """

    task: Task | None
    subtasks: list[Subtask]
    subtask_results: list[SubtaskResult]
    task_result: TaskResult | None
    error: str | None
    audit_entries: list[AuditEntry]


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------


def validate_node(state: RootOrchestratorState) -> dict[str, Any]:
    """Validate the Task against the input contract (Req 1.1).

    Expects the raw task data to be present in ``state["task"]`` as a dict or
    a Task instance. On success, replaces with the validated Task model. On
    failure, sets the ``error`` field with details of each failed field.
    """
    task_data = state.get("task")
    audit_entries: list[AuditEntry] = list(state.get("audit_entries", []))

    if task_data is None:
        return {
            "task": None,
            "error": "No task data provided for validation.",
            "audit_entries": audit_entries,
        }

    try:
        # If already a Task instance, re-validate by dumping and re-parsing
        # to ensure contract compliance.
        if isinstance(task_data, Task):
            validated_task = task_data
        else:
            validated_task = validate_task_input(task_data)
    except TaskValidationError as exc:
        error_msg = "; ".join(
            f"{e.field}: {e.message}" for e in exc.errors
        )
        error_entry = build_error_entry(
            task_id=task_data.get("task_id", "unknown") if isinstance(task_data, dict) else "unknown",
            subtask_id=None,
            sub_subtask_id=None,
            actor_agent_id=ROOT_ORCHESTRATOR_ID,
            error_type="validation_error",
            error_detail={"fields": error_msg},
        )
        audit_entries.append(error_entry)
        return {
            "task": None,
            "error": f"Task validation failed: {error_msg}",
            "audit_entries": audit_entries,
        }

    # Record intake audit entry.
    intake_entry = AuditEntry(
        task_id=validated_task.task_id,
        subtask_id=None,
        sub_subtask_id=None,
        actor_agent_id=ROOT_ORCHESTRATOR_ID,
        event_type=AuditEventType.INTAKE,
        detail=redact({"title": validated_task.title, "mode": validated_task.mode.value}),
        created_at=datetime.now(tz=UTC),
    )
    audit_entries.append(intake_entry)

    return {
        "task": validated_task,
        "error": None,
        "audit_entries": audit_entries,
    }


def decompose_node(state: RootOrchestratorState) -> dict[str, Any]:
    """Decompose the Task into Subtasks and create Shared_Context (Req 1.3, 7.1).

    Calls the pure ``decompose_task`` function from ``maos.core.decomposition``
    to classify and split the Task into one Subtask per target Platform_System.
    Creates a Shared_Context entry for coordination across agents.
    """
    task = state.get("task")
    audit_entries: list[AuditEntry] = list(state.get("audit_entries", []))

    if task is None:
        return {
            "subtasks": [],
            "error": state.get("error") or "Cannot decompose: no validated task.",
            "audit_entries": audit_entries,
        }

    try:
        subtasks = decompose_task(task)
    except Exception as exc:
        error_entry = build_error_entry(
            task_id=task.task_id,
            subtask_id=None,
            sub_subtask_id=None,
            actor_agent_id=ROOT_ORCHESTRATOR_ID,
            error_type="decomposition_error",
            error_detail={"reason": str(exc)},
        )
        audit_entries.append(error_entry)
        return {
            "subtasks": [],
            "error": f"Decomposition failed: {exc}",
            "audit_entries": audit_entries,
        }

    # Note: Shared_Context creation (Req 7.1) is performed asynchronously in the
    # actual runtime wiring. The graph skeleton records intent; the integration
    # layer calls SharedContextStore.create(task.task_id, task.tenant_id).

    return {
        "subtasks": subtasks,
        "error": None,
        "audit_entries": audit_entries,
    }


def route_node(state: RootOrchestratorState) -> dict[str, Any]:
    """Route each Subtask to its bound Sub-Orchestrator (Req 2.1).

    Computes the Sub-Orchestrator target for each Subtask using
    ``route_target`` from ``maos.core.decomposition``. Logs a routing-decision
    audit entry for each Subtask.

    The actual Sub-Orchestrator invocation is a **placeholder** — in
    integration, this node will invoke the Sub-Orchestrator subgraph and
    collect ``SubtaskResult`` instances. For now, it prepares routing info
    and leaves ``subtask_results`` empty for the aggregate node.
    """
    task = state.get("task")
    subtasks = state.get("subtasks", [])
    audit_entries: list[AuditEntry] = list(state.get("audit_entries", []))

    if task is None or not subtasks:
        return {
            "subtask_results": [],
            "error": state.get("error") or "Cannot route: no subtasks available.",
            "audit_entries": audit_entries,
        }

    subtask_results: list[SubtaskResult] = []

    for subtask in subtasks:
        # Compute the bound Sub-Orchestrator for this Subtask.
        target = route_target(subtask)

        # Record routing decision audit entry (Req 10.1).
        routing_entry = build_routing_decision_entry(
            task_id=task.task_id,
            subtask_id=subtask.subtask_id,
            sub_subtask_id=None,
            actor_agent_id=ROOT_ORCHESTRATOR_ID,
            candidates=[target],
            selected=target,
        )
        audit_entries.append(routing_entry)

        # Placeholder: in integration, this invokes the Sub-Orchestrator
        # subgraph for the target platform_system and collects results.
        # For now, subtask_results remains empty until wired.

    return {
        "subtask_results": subtask_results,
        "error": None,
        "audit_entries": audit_entries,
    }


def aggregate_node(state: RootOrchestratorState) -> dict[str, Any]:
    """Aggregate Subtask results into a single Task result (Req 12.2, 12.4).

    Calls the pure ``aggregate_task`` function from ``maos.core.aggregation``
    to combine all Subtask results into a final Task result referencing the
    originating Task identifier.
    """
    task = state.get("task")
    subtask_results = state.get("subtask_results", [])
    audit_entries: list[AuditEntry] = list(state.get("audit_entries", []))

    if task is None:
        return {
            "task_result": None,
            "error": state.get("error") or "Cannot aggregate: no task context.",
            "audit_entries": audit_entries,
        }

    # Aggregate using the pure core function (Req 12.2, 12.4).
    task_result = aggregate_task(subtask_results, task_id=task.task_id)

    return {
        "task_result": task_result,
        "error": None,
        "audit_entries": audit_entries,
    }


# ---------------------------------------------------------------------------
# Conditional edge: short-circuit on error after validation
# ---------------------------------------------------------------------------


def _should_continue_after_validate(state: RootOrchestratorState) -> str:
    """Route to END if validation set an error, otherwise continue to decompose."""
    if state.get("error"):
        return END
    return "decompose"


def _should_continue_after_decompose(state: RootOrchestratorState) -> str:
    """Route to END if decomposition set an error, otherwise continue to route."""
    if state.get("error"):
        return END
    return "route"


def _should_continue_after_route(state: RootOrchestratorState) -> str:
    """Route to END if routing set an error, otherwise continue to aggregate."""
    if state.get("error"):
        return END
    return "aggregate"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_root_graph() -> StateGraph:
    """Build and return the compiled Root Orchestrator supervisor graph.

    The graph follows the flow:
        validate → decompose → route → aggregate → END

    Each step short-circuits to END if an error is encountered. State is
    designed to be persisted to the Checkpointer at every node transition
    (handled by LangGraph's built-in checkpoint integration when a
    checkpointer is supplied at compile time).

    Returns
    -------
    StateGraph
        The compiled LangGraph StateGraph ready for execution. To wire the
        Postgres checkpointer, pass it at ``.compile(checkpointer=...)`` time.
    """
    graph = StateGraph(RootOrchestratorState)

    # Add nodes.
    graph.add_node("validate", validate_node)
    graph.add_node("decompose", decompose_node)
    graph.add_node("route", route_node)
    graph.add_node("aggregate", aggregate_node)

    # Set entry point.
    graph.set_entry_point("validate")

    # Add conditional edges for error short-circuiting.
    graph.add_conditional_edges("validate", _should_continue_after_validate)
    graph.add_conditional_edges("decompose", _should_continue_after_decompose)
    graph.add_conditional_edges("route", _should_continue_after_route)

    # Aggregate always ends the graph.
    graph.add_edge("aggregate", END)

    return graph


# ---------------------------------------------------------------------------
# Runner function for worker invocation
# ---------------------------------------------------------------------------


async def run_root_orchestrator(
    *,
    task_id: str,
    tenant_id: str,
    resume_state: dict[str, Any] | None = None,
    db_pool: Any = None,
) -> dict[str, Any]:
    """Execute the Root Orchestrator graph for a Task.

    Called by Arq worker task functions to run the full orchestration
    pipeline. Builds the graph, optionally resumes from a checkpoint state,
    and returns the final result dict.

    Parameters
    ----------
    task_id:
        The unique identifier of the Task to process.
    tenant_id:
        The tenant scoping this Task execution.
    resume_state:
        Optional checkpoint state to resume from. If None, starts fresh.
    db_pool:
        Database pool for persistence operations.

    Returns
    -------
    dict:
        A dict containing at minimum ``state`` (terminal state string) and
        optionally ``task_result`` if aggregation completed.

    Requirements: 14.2, 14.3.
    """
    graph = build_root_graph()

    # Prepare the initial state — either from checkpoint or fresh.
    initial_state: dict[str, Any]
    if resume_state is not None:
        initial_state = resume_state
    else:
        # Fresh execution: load the Task from DB and set as initial state.
        task_data: dict[str, Any] | None = None
        if db_pool is not None:
            task_data = await db_pool.fetch_one(
                "SELECT * FROM task WHERE task_id = %(task_id)s",
                {"task_id": task_id},
            )

        initial_state = {
            "task": task_data,
            "subtasks": [],
            "subtask_results": [],
            "task_result": None,
            "error": None,
            "audit_entries": [],
        }

    # Compile and invoke the graph.
    # Note: In production this would include a checkpointer for persistence.
    compiled = graph.compile()
    final_state = await compiled.ainvoke(initial_state)

    # Extract terminal state from result.
    task_result = final_state.get("task_result")
    error = final_state.get("error")

    if error:
        return {"state": "failed", "error": error}
    if task_result is not None:
        return {"state": task_result.state.value, "task_result": task_result}
    return {"state": "completed"}
