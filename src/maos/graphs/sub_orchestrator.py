"""Sub-Orchestrator LangGraph subgraph.

Implements the Sub-Orchestrator flow as a LangGraph StateGraph. Each
Sub-Orchestrator is bound to a single Platform_System and performs:

1. **Decompose** — Decomposes the incoming Subtask into Sub_Subtasks (Req 2.2).
2. **Select & Assign** — For each Sub_Subtask, uses the Agent_Registry to pick a
   Subagent (Req 2.3, 2.5) and records the routing decision in audit (Req 2.6).
3. **Execute** — Placeholder for invoking the Subagent node runtime (task 27.3).
4. **Handle Failure** — On failure, uses reassignment to pick an alternative
   (Req 11.2); marks permanently_failed if the attempt cap is reached (Req 11.3).
5. **Aggregate** — Aggregates all Sub_Subtask results into a Subtask result (Req 12.1).

The graph uses conditional edges to implement the retry/reassignment loop.

Requirements: 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 11.1, 11.2, 11.3, 12.1.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from maos.audit.entries import (
    build_failure_entry,
    build_routing_decision_entry,
)
from maos.contracts.results import SubSubtaskResult, SubtaskResult
from maos.contracts.work_units import (
    SubSubtask,
    Subtask,
    WorkUnitState,
)
from maos.core.aggregation import aggregate_subtask
from maos.core.decomposition import decompose_subtask
from maos.core.reassignment import select_reassignment
from maos.core.state_machine import record_attempt, should_permanently_fail
from maos.registry.repository import AgentRegistryRepo

# ---------------------------------------------------------------------------
# State definition
# ---------------------------------------------------------------------------


class SubOrchestratorState(TypedDict, total=False):
    """State for the Sub-Orchestrator subgraph.

    Attributes:
        subtask: The Subtask being processed (input to the graph).
        sub_subtasks: List of Sub_Subtasks produced by decomposition.
        sub_subtask_results: Accumulated results from Subagent execution.
        subtask_result: The aggregated Subtask result (output of the graph).
        error: Error message if the graph encounters a fatal issue.
    """

    subtask: Subtask | None
    sub_subtasks: list[SubSubtask]
    sub_subtask_results: list[SubSubtaskResult]
    subtask_result: SubtaskResult | None
    error: str | None


# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

#: Default maximum number of attempts per Sub_Subtask before permanently failing.
DEFAULT_MAX_ATTEMPTS: int = 3

#: Default list of skills to decompose a Subtask into when the Subtask does not
#: declare explicit required skills. Used as a simple fallback for decomposition.
DEFAULT_REQUIRED_SKILLS: list[str] = ["general"]


# ---------------------------------------------------------------------------
# Graph node functions
# ---------------------------------------------------------------------------


async def decompose_node(state: SubOrchestratorState) -> SubOrchestratorState:
    """Decompose the Subtask into Sub_Subtasks (Req 2.2).

    Calls the pure decompose_subtask function to produce Sub_Subtasks with
    unique traceable identifiers. Uses the Subtask's input_contract to determine
    required skills (if declared), otherwise falls back to a default set.
    """
    subtask = state.get("subtask")
    if subtask is None:
        return {"error": "No subtask provided to Sub-Orchestrator"}

    # Determine required skills from the input_contract or use defaults.
    required_skills: list[str] = subtask.input_contract.get(
        "required_skills", DEFAULT_REQUIRED_SKILLS
    )
    if not required_skills:
        required_skills = DEFAULT_REQUIRED_SKILLS

    sub_subtasks = decompose_subtask(subtask, required_skills)
    return {"sub_subtasks": sub_subtasks}


async def select_and_assign_node(
    state: SubOrchestratorState,
    *,
    registry: AgentRegistryRepo,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> SubOrchestratorState:
    """Select and assign a Subagent for each Sub_Subtask (Req 2.3, 2.5, 2.6).

    For each Sub_Subtask, uses AgentRegistryRepo.select() to pick a Subagent
    that matches the platform_system, required_skill, and mode. Records the
    routing decision in audit. If no Subagent is available for a Sub_Subtask,
    marks it as unroutable (Req 2.4).
    """
    sub_subtasks = state.get("sub_subtasks", [])
    if not sub_subtasks:
        return {"error": "No sub_subtasks to assign"}

    updated_sub_subtasks: list[SubSubtask] = []
    audit_entries = []

    for sst in sub_subtasks:
        # Use the registry to select the best matching Subagent.
        selected = await registry.select(
            platform=sst.platform_system,
            skill_id=sst.required_skill,
            mode=sst.mode,
        )

        # Get candidates for audit purposes.
        candidates = await registry.available_agents(sst.platform_system)
        candidate_ids = [c.subagent_id for c in candidates]

        if selected is not None:
            # Assign the selected Subagent.
            updated = sst.model_copy(
                update={
                    "assigned_subagent_id": selected.subagent_id,
                    "state": WorkUnitState.ASSIGNED,
                }
            )
        else:
            # No matching Subagent: mark as permanently_failed (unroutable, Req 2.4).
            updated = sst.model_copy(
                update={
                    "state": WorkUnitState.PERMANENTLY_FAILED,
                }
            )

        updated_sub_subtasks.append(updated)

        # Record routing decision in audit (Req 2.6).
        sub_orchestrator_id = f"sub-orchestrator::{sst.platform_system.value}"
        entry = build_routing_decision_entry(
            task_id=sst.task_id,
            subtask_id=sst.subtask_id,
            sub_subtask_id=sst.sub_subtask_id,
            actor_agent_id=sub_orchestrator_id,
            candidates=candidate_ids,
            selected=selected.subagent_id if selected else None,
        )
        audit_entries.append(entry)

    return {"sub_subtasks": updated_sub_subtasks}


async def execute_node(state: SubOrchestratorState) -> SubOrchestratorState:
    """Execute Sub_Subtasks via the Subagent node runtime (placeholder for task 27.3).

    This node is a placeholder that produces results for each assigned
    Sub_Subtask. The actual Subagent reasoning loop, MCP tool invocation, scope
    enforcement, and budget accounting will be implemented in task 27.3.

    For now, marks each assigned Sub_Subtask as completed with an empty output,
    and each unroutable one as permanently_failed.
    """
    sub_subtasks = state.get("sub_subtasks", [])
    results: list[SubSubtaskResult] = []

    for sst in sub_subtasks:
        if sst.state == WorkUnitState.PERMANENTLY_FAILED:
            # Already marked unroutable — produce a failed result.
            results.append(
                SubSubtaskResult(
                    sub_subtask_id=sst.sub_subtask_id,
                    subtask_id=sst.subtask_id,
                    task_id=sst.task_id,
                    state=WorkUnitState.PERMANENTLY_FAILED,
                    assigned_subagent_id=sst.assigned_subagent_id,
                    attempts=sst.attempts,
                    error="No matching Subagent available (unroutable)",
                )
            )
        elif sst.assigned_subagent_id is not None:
            # Placeholder: simulate successful execution.
            # Task 27.3 will replace this with the actual Subagent runtime.
            results.append(
                SubSubtaskResult(
                    sub_subtask_id=sst.sub_subtask_id,
                    subtask_id=sst.subtask_id,
                    task_id=sst.task_id,
                    state=WorkUnitState.COMPLETED,
                    assigned_subagent_id=sst.assigned_subagent_id,
                    attempts=sst.attempts + 1,
                    output={},
                )
            )
        else:
            # No agent assigned and not permanently failed — treat as failed.
            results.append(
                SubSubtaskResult(
                    sub_subtask_id=sst.sub_subtask_id,
                    subtask_id=sst.subtask_id,
                    task_id=sst.task_id,
                    state=WorkUnitState.FAILED,
                    assigned_subagent_id=None,
                    attempts=sst.attempts,
                    error="Sub_Subtask not assigned to any Subagent",
                )
            )

    return {"sub_subtask_results": results}


async def handle_failure_node(
    state: SubOrchestratorState,
    *,
    registry: AgentRegistryRepo,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> SubOrchestratorState:
    """Handle failed Sub_Subtasks via reassignment (Req 11.1, 11.2, 11.3).

    For each failed Sub_Subtask result:
    - Increment the attempt counter.
    - If max attempts reached, mark as permanently_failed.
    - Otherwise, use select_reassignment to find an alternative Subagent.
    - If an alternative is found, reassign the Sub_Subtask.
    - If no alternative exists, mark as permanently_failed.

    Updates the sub_subtasks and sub_subtask_results in state.
    """
    results = state.get("sub_subtask_results", [])
    sub_subtasks = state.get("sub_subtasks", [])

    # Index sub_subtasks by id for lookup.
    sst_by_id = {sst.sub_subtask_id: sst for sst in sub_subtasks}

    updated_results: list[SubSubtaskResult] = []
    updated_sub_subtasks: list[SubSubtask] = list(sub_subtasks)

    for result in results:
        if result.state != WorkUnitState.FAILED:
            # Not failed — keep as is.
            updated_results.append(result)
            continue

        sst = sst_by_id.get(result.sub_subtask_id)
        if sst is None:
            updated_results.append(result)
            continue

        # Record the attempt (Req 11.3).
        updated_sst = record_attempt(sst)

        if should_permanently_fail(updated_sst, max_attempts):
            # Cap reached — permanently failed (Req 11.3).
            final_sst = updated_sst.model_copy(
                update={"state": WorkUnitState.PERMANENTLY_FAILED}
            )
            # Replace in the sub_subtasks list.
            updated_sub_subtasks = [
                final_sst if s.sub_subtask_id == sst.sub_subtask_id else s
                for s in updated_sub_subtasks
            ]
            updated_results.append(
                SubSubtaskResult(
                    sub_subtask_id=result.sub_subtask_id,
                    subtask_id=result.subtask_id,
                    task_id=result.task_id,
                    state=WorkUnitState.PERMANENTLY_FAILED,
                    assigned_subagent_id=result.assigned_subagent_id,
                    attempts=updated_sst.attempts,
                    error=result.error or "Max attempts reached",
                )
            )

            # Record failure in audit (Req 11.1).
            sub_orchestrator_id = (
                f"sub-orchestrator::{sst.platform_system.value}"
            )
            _failure_entry = build_failure_entry(
                task_id=sst.task_id,
                subtask_id=sst.subtask_id,
                sub_subtask_id=sst.sub_subtask_id,
                actor_agent_id=sub_orchestrator_id,
                reason=result.error or "Max attempts reached — permanently failed",
            )
            # In production this entry would be persisted to the AuditLog.
            continue

        # Attempt reassignment (Req 11.2).
        candidates = await registry.available_agents(sst.platform_system)
        alternative = select_reassignment(
            failed_sub_subtask=updated_sst,
            candidates=candidates,
            max_attempts=max_attempts,
        )

        if alternative is not None:
            # Reassign to the alternative Subagent.
            reassigned_sst = updated_sst.model_copy(
                update={
                    "assigned_subagent_id": alternative.subagent_id,
                    "state": WorkUnitState.ASSIGNED,
                }
            )
            updated_sub_subtasks = [
                reassigned_sst if s.sub_subtask_id == sst.sub_subtask_id else s
                for s in updated_sub_subtasks
            ]
            # The reassigned Sub_Subtask will go through execute again —
            # remove this result so it can be re-executed.
            # (Result not appended to updated_results.)
        else:
            # No alternative available — permanently failed.
            final_sst = updated_sst.model_copy(
                update={"state": WorkUnitState.PERMANENTLY_FAILED}
            )
            updated_sub_subtasks = [
                final_sst if s.sub_subtask_id == sst.sub_subtask_id else s
                for s in updated_sub_subtasks
            ]
            updated_results.append(
                SubSubtaskResult(
                    sub_subtask_id=result.sub_subtask_id,
                    subtask_id=result.subtask_id,
                    task_id=result.task_id,
                    state=WorkUnitState.PERMANENTLY_FAILED,
                    assigned_subagent_id=updated_sst.assigned_subagent_id,
                    attempts=updated_sst.attempts,
                    error=result.error or "No alternative Subagent available",
                )
            )

            # Record failure in audit (Req 11.1).
            sub_orchestrator_id = (
                f"sub-orchestrator::{sst.platform_system.value}"
            )
            _failure_entry = build_failure_entry(
                task_id=sst.task_id,
                subtask_id=sst.subtask_id,
                sub_subtask_id=sst.sub_subtask_id,
                actor_agent_id=sub_orchestrator_id,
                reason=result.error or "No alternative — permanently failed",
            )

    return {
        "sub_subtasks": updated_sub_subtasks,
        "sub_subtask_results": updated_results,
    }


async def aggregate_node(state: SubOrchestratorState) -> SubOrchestratorState:
    """Aggregate Sub_Subtask results into a Subtask result (Req 12.1).

    Calls the pure aggregate_subtask function to combine all terminal
    Sub_Subtask results into a single SubtaskResult. Includes every unit's
    status and identifiers (including permanently_failed ones).
    """
    results = state.get("sub_subtask_results", [])
    subtask = state.get("subtask")

    if not results:
        return {"error": "No sub_subtask_results to aggregate"}

    platform_system = subtask.platform_system if subtask else None
    subtask_result = aggregate_subtask(results, platform_system=platform_system)
    return {"subtask_result": subtask_result}


# ---------------------------------------------------------------------------
# Conditional edge: check if any failed Sub_Subtasks need retry
# ---------------------------------------------------------------------------


def _should_retry(state: SubOrchestratorState) -> str:
    """Determine whether the graph should route to failure handling or aggregation.

    Returns:
        "handle_failure" if any sub_subtask_results have FAILED state.
        "aggregate" if all results are terminal (completed or permanently_failed).
    """
    results = state.get("sub_subtask_results", [])
    has_failed = any(r.state == WorkUnitState.FAILED for r in results)
    if has_failed:
        return "handle_failure"
    return "aggregate"


def _after_failure_handling(state: SubOrchestratorState) -> str:
    """Determine next step after failure handling.

    Returns:
        "execute" if there are Sub_Subtasks in ASSIGNED state (reassigned, need re-execution).
        "aggregate" if all Sub_Subtasks have reached terminal states.
    """
    sub_subtasks = state.get("sub_subtasks", [])
    has_assigned = any(sst.state == WorkUnitState.ASSIGNED for sst in sub_subtasks)
    if has_assigned:
        return "execute"
    return "aggregate"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_sub_orchestrator_graph(
    registry: AgentRegistryRepo,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> StateGraph:
    """Build the Sub-Orchestrator LangGraph StateGraph.

    Constructs a graph with the following flow:

        decompose -> select_and_assign -> execute -> [conditional]
                                                      |
                                            +---------+---------+
                                            |                   |
                                    handle_failure          aggregate -> END
                                            |
                                    [conditional]
                                     |          |
                                  execute    aggregate -> END

    Args:
        registry: The AgentRegistryRepo instance for Subagent selection.
        max_attempts: Maximum retry attempts before permanently failing a
            Sub_Subtask (Req 11.3).

    Returns:
        A compiled LangGraph StateGraph implementing the Sub-Orchestrator flow.
    """
    graph = StateGraph(SubOrchestratorState)

    # --- Define node functions with bound dependencies ---

    async def _decompose(state: SubOrchestratorState) -> SubOrchestratorState:
        return await decompose_node(state)

    async def _select_and_assign(state: SubOrchestratorState) -> SubOrchestratorState:
        return await select_and_assign_node(state, registry=registry, max_attempts=max_attempts)

    async def _execute(state: SubOrchestratorState) -> SubOrchestratorState:
        return await execute_node(state)

    async def _handle_failure(state: SubOrchestratorState) -> SubOrchestratorState:
        return await handle_failure_node(state, registry=registry, max_attempts=max_attempts)

    async def _aggregate(state: SubOrchestratorState) -> SubOrchestratorState:
        return await aggregate_node(state)

    # --- Add nodes ---
    graph.add_node("decompose", _decompose)
    graph.add_node("select_and_assign", _select_and_assign)
    graph.add_node("execute", _execute)
    graph.add_node("handle_failure", _handle_failure)
    graph.add_node("aggregate", _aggregate)

    # --- Set entry point ---
    graph.set_entry_point("decompose")

    # --- Add edges ---
    # Linear: decompose -> select_and_assign -> execute
    graph.add_edge("decompose", "select_and_assign")
    graph.add_edge("select_and_assign", "execute")

    # Conditional: after execute, check if any failures need handling.
    graph.add_conditional_edges(
        "execute",
        _should_retry,
        {
            "handle_failure": "handle_failure",
            "aggregate": "aggregate",
        },
    )

    # Conditional: after failure handling, either re-execute or aggregate.
    graph.add_conditional_edges(
        "handle_failure",
        _after_failure_handling,
        {
            "execute": "execute",
            "aggregate": "aggregate",
        },
    )

    # Terminal: aggregate -> END
    graph.add_edge("aggregate", END)

    return graph


# ---------------------------------------------------------------------------
# Runner function for worker invocation
# ---------------------------------------------------------------------------


async def run_sub_orchestrator(
    *,
    subtask_id: str,
    task_id: str,
    tenant_id: str,
    platform_system: str,
    resume_state: dict[str, Any] | None = None,
    db_pool: Any = None,
) -> dict[str, Any]:
    """Execute the Sub-Orchestrator graph for a Subtask.

    Called by Arq worker task functions to run the Sub-Orchestrator pipeline
    for a specific Platform_System. Builds the graph, optionally resumes from
    a checkpoint state, and returns the final result dict.

    Parameters
    ----------
    subtask_id:
        The unique identifier of the Subtask to process.
    task_id:
        The parent Task identifier for traceability.
    tenant_id:
        The tenant scoping this execution.
    platform_system:
        The Platform_System this Sub-Orchestrator handles.
    resume_state:
        Optional checkpoint state to resume from. If None, starts fresh.
    db_pool:
        Database pool for persistence operations.

    Returns
    -------
    dict:
        A dict containing at minimum ``state`` (terminal state string) and
        optionally ``subtask_result`` if aggregation completed.

    Requirements: 14.2, 14.3.
    """
    from maos.contracts.work_units import PlatformSystem, Subtask, WorkUnitState

    # Build a registry instance for agent selection.
    registry = AgentRegistryRepo(pool=db_pool)

    graph = build_sub_orchestrator_graph(registry=registry)

    # Prepare the initial state — either from checkpoint or fresh.
    if resume_state is not None:
        initial_state: dict[str, Any] = resume_state
    else:
        # Fresh execution: load the Subtask from DB.
        subtask_data: dict[str, Any] | None = None
        if db_pool is not None:
            subtask_data = await db_pool.fetch_one(
                "SELECT * FROM subtask WHERE subtask_id = %(subtask_id)s",
                {"subtask_id": subtask_id},
            )

        # Construct a Subtask model from DB data if available.
        subtask_obj: Subtask | None = None
        if subtask_data is not None:
            subtask_obj = Subtask(
                subtask_id=subtask_data["subtask_id"],
                task_id=subtask_data["task_id"],
                platform_system=PlatformSystem(subtask_data["platform_system"]),
                mode=subtask_data["mode"],
                tenant_id=subtask_data["tenant_id"],
                state=WorkUnitState(subtask_data["state"]),
                input_contract=subtask_data.get("input_contract", {}),
            )

        initial_state = {
            "subtask": subtask_obj,
            "sub_subtasks": [],
            "sub_subtask_results": [],
            "subtask_result": None,
            "error": None,
        }

    # Compile and invoke the graph.
    compiled = graph.compile()
    final_state = await compiled.ainvoke(initial_state)

    # Extract terminal state from result.
    subtask_result = final_state.get("subtask_result")
    error = final_state.get("error")

    if error:
        return {"state": "failed", "error": error}
    if subtask_result is not None:
        return {"state": "completed", "subtask_result": subtask_result}
    return {"state": "completed"}
