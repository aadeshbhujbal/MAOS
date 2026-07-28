"""Parallel fan-out/fan-in execution workflow for MAOS.

Implements parallel execution of independent subtasks from the Planning Agent's
DAG, synchronization points (fan-in) waiting for all parallel tasks to complete,
dependency constraint validation before proceeding, and retry with escalation
to the Planning Agent for re-planning on persistent failures.

Design reference: Parallel Execution Workflow state diagram (design.md)

Requirements
------------
- Req 17.2: Parallel execution of independent subtasks with result merging
- Req 17.4: Validate dependency constraints before proceeding to dependents
- Req 17.5: Retry failed subtasks 3x, then escalate for re-planning
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from langgraph.func import entrypoint, task  # type: ignore[import-untyped]

from maos.planning.models import ExecutionPlan, PlannedSubtask
from maos.resilience.retry import RetryConfig, RetryExhaustedError, execute_with_retry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Maximum number of retry attempts per subtask before escalation (Req 17.5).
MAX_SUBTASK_RETRIES: int = 3

#: Retry configuration for individual subtask execution.
SUBTASK_RETRY_CONFIG = RetryConfig(
    max_attempts=MAX_SUBTASK_RETRIES,
    base_delay=1.0,
    max_delay=15.0,
    jitter=True,
)


# ---------------------------------------------------------------------------
# Subtask execution status
# ---------------------------------------------------------------------------


class SubtaskStatus(str, Enum):
    """Status of a subtask within the parallel workflow."""

    WAITING = "waiting"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    ESCALATED = "escalated"


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


@dataclass
class SubtaskResult:
    """Result of a single subtask execution.

    Attributes:
        subtask_id: Identifier of the subtask.
        assigned_agent: Agent that executed (or was assigned to) the subtask.
        status: Final status of the subtask.
        output: Arbitrary output data from the subtask execution.
        attempts: Number of execution attempts made.
        duration_ms: Wall-clock execution duration in milliseconds.
        error: Error description if the subtask failed/escalated.
    """

    subtask_id: str
    assigned_agent: str
    status: SubtaskStatus
    output: dict[str, Any] = field(default_factory=dict)
    attempts: int = 0
    duration_ms: float = 0.0
    error: str | None = None


@dataclass
class ParallelWorkflowResult:
    """Final result of the parallel fan-out/fan-in workflow.

    Attributes:
        workflow_id: Unique identifier for this workflow execution.
        plan_id: The execution plan identifier.
        subtask_results: Results for each subtask.
        total_duration_ms: Total wall-clock execution time.
        final_status: Overall workflow outcome.
        escalated_subtasks: IDs of subtasks that required re-planning.
        replan_requested: Whether re-planning was triggered.
    """

    workflow_id: str
    plan_id: str
    subtask_results: list[SubtaskResult]
    total_duration_ms: float
    final_status: str
    escalated_subtasks: list[str] = field(default_factory=list)
    replan_requested: bool = False


# ---------------------------------------------------------------------------
# Structured log emission (Req 17.2 — observability)
# ---------------------------------------------------------------------------


def _emit_fanout_event(
    workflow_id: str,
    plan_id: str,
    subtask_ids: list[str],
    level: str,
) -> None:
    """Emit structured log event for a fan-out dispatch."""
    logger.info(
        "parallel_fanout",
        extra={
            "workflow_id": workflow_id,
            "plan_id": plan_id,
            "subtask_ids": subtask_ids,
            "parallel_count": len(subtask_ids),
            "level": level,
        },
    )


def _emit_fanin_event(
    workflow_id: str,
    plan_id: str,
    subtask_ids: list[str],
    completed: int,
    failed: int,
) -> None:
    """Emit structured log event for a fan-in synchronization."""
    logger.info(
        "parallel_fanin",
        extra={
            "workflow_id": workflow_id,
            "plan_id": plan_id,
            "subtask_ids": subtask_ids,
            "completed": completed,
            "failed": failed,
        },
    )


def _emit_escalation_event(
    workflow_id: str,
    plan_id: str,
    subtask_id: str,
    error: str,
) -> None:
    """Emit structured log event when a subtask escalates to Planning Agent."""
    logger.warning(
        "subtask_escalated",
        extra={
            "workflow_id": workflow_id,
            "plan_id": plan_id,
            "subtask_id": subtask_id,
            "error": error,
            "action": "replan_requested",
        },
    )


# ---------------------------------------------------------------------------
# Dependency graph utilities (Req 17.4)
# ---------------------------------------------------------------------------


def validate_dependency_constraints(
    plan: ExecutionPlan,
    completed_ids: set[str],
    candidate_id: str,
) -> bool:
    """Check whether all prerequisites for a subtask are satisfied (Req 17.4).

    Parameters
    ----------
    plan:
        The execution plan containing the dependency graph.
    completed_ids:
        Set of subtask IDs that have already completed successfully.
    candidate_id:
        The subtask ID to evaluate for readiness.

    Returns
    -------
    bool
        True if all prerequisite subtasks for *candidate_id* are in
        *completed_ids*; False otherwise.
    """
    prerequisites = plan.dependency_graph.get(candidate_id, [])
    return all(prereq in completed_ids for prereq in prerequisites)


def get_ready_subtasks(
    plan: ExecutionPlan,
    completed_ids: set[str],
    in_progress_ids: set[str],
    failed_ids: set[str],
) -> list[PlannedSubtask]:
    """Identify subtasks whose dependencies are met and are ready to run.

    A subtask is ready when:
    - All its prerequisites are in ``completed_ids``
    - It is not already completed, in-progress, or permanently failed

    Parameters
    ----------
    plan:
        The execution plan with subtasks and dependency graph.
    completed_ids:
        Subtask IDs that completed successfully.
    in_progress_ids:
        Subtask IDs currently executing.
    failed_ids:
        Subtask IDs that have permanently failed (escalated).

    Returns
    -------
    list[PlannedSubtask]
        Subtasks eligible for immediate execution.
    """
    excluded = completed_ids | in_progress_ids | failed_ids
    ready: list[PlannedSubtask] = []

    for subtask in plan.subtasks:
        if subtask.subtask_id in excluded:
            continue
        if validate_dependency_constraints(plan, completed_ids, subtask.subtask_id):
            ready.append(subtask)

    return ready


# ---------------------------------------------------------------------------
# @task: execute a single subtask (Req 17.2)
# ---------------------------------------------------------------------------


@task
async def execute_subtask(
    subtask_id: str,
    assigned_agent: str,
    description: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Execute a single subtask by dispatching to the assigned agent.

    This is the primary execution point for each parallel subtask. It delegates
    to the appropriate specialized agent and returns the result. The @task
    decorator provides LangGraph checkpoint/resumability.

    Parameters
    ----------
    subtask_id:
        Unique identifier for this subtask.
    assigned_agent:
        The agent role to dispatch execution to.
    description:
        Human-readable subtask description.
    context:
        Workflow context shared across subtasks.

    Returns
    -------
    dict
        Subtask execution result with keys: subtask_id, status, output.
    """
    # Delegate to the assigned agent. In a full integration this would
    # invoke the agent via the Root Orchestrator's agent dispatch.
    output: dict[str, Any] = {
        "subtask_id": subtask_id,
        "agent": assigned_agent,
        "description": description,
        "executed": True,
    }

    return {
        "subtask_id": subtask_id,
        "status": "completed",
        "output": output,
    }


# ---------------------------------------------------------------------------
# Subtask execution with retry (Req 17.5)
# ---------------------------------------------------------------------------


async def _execute_subtask_with_retry(
    subtask: PlannedSubtask,
    context: dict[str, Any],
    workflow_id: str,
) -> SubtaskResult:
    """Execute a subtask with retry logic (Req 17.5).

    Retries the subtask up to ``MAX_SUBTASK_RETRIES`` times with exponential
    backoff. If all retries are exhausted, the subtask is marked as failed and
    escalation is triggered.

    Parameters
    ----------
    subtask:
        The planned subtask to execute.
    context:
        Shared workflow context.
    workflow_id:
        Parent workflow identifier for log correlation.

    Returns
    -------
    SubtaskResult
        Result with status indicating completed or failed.
    """
    start_ms = time.perf_counter_ns() / 1_000_000

    async def _attempt() -> dict[str, Any]:
        return await execute_subtask(
            subtask_id=subtask.subtask_id,
            assigned_agent=subtask.assigned_agent,
            description=subtask.description,
            context=context,
        )

    try:
        result_data = await execute_with_retry(
            _attempt,
            config=SUBTASK_RETRY_CONFIG,
        )
        end_ms = time.perf_counter_ns() / 1_000_000
        return SubtaskResult(
            subtask_id=subtask.subtask_id,
            assigned_agent=subtask.assigned_agent,
            status=SubtaskStatus.COMPLETED,
            output=result_data.get("output", {}),
            attempts=1,  # Succeeded; exact attempt count not exposed by retry
            duration_ms=round(end_ms - start_ms, 2),
        )
    except RetryExhaustedError as exc:
        end_ms = time.perf_counter_ns() / 1_000_000
        error_msg = str(exc.last_exception)
        logger.error(
            "subtask_retry_exhausted",
            extra={
                "workflow_id": workflow_id,
                "subtask_id": subtask.subtask_id,
                "attempts": exc.attempts,
                "error": error_msg,
            },
        )
        return SubtaskResult(
            subtask_id=subtask.subtask_id,
            assigned_agent=subtask.assigned_agent,
            status=SubtaskStatus.FAILED,
            attempts=exc.attempts,
            duration_ms=round(end_ms - start_ms, 2),
            error=error_msg,
        )


# ---------------------------------------------------------------------------
# Fan-out/fan-in execution of one parallel batch (Req 17.2)
# ---------------------------------------------------------------------------


async def _execute_parallel_batch(
    subtasks: list[PlannedSubtask],
    context: dict[str, Any],
    workflow_id: str,
) -> list[SubtaskResult]:
    """Fan-out a batch of independent subtasks and fan-in their results.

    All subtasks in the batch execute concurrently via ``asyncio.gather``.
    The function awaits all of them (fan-in synchronization point) before
    returning.

    Parameters
    ----------
    subtasks:
        Independent subtasks to run in parallel.
    context:
        Shared workflow context.
    workflow_id:
        Workflow identifier for log correlation.

    Returns
    -------
    list[SubtaskResult]
        Results from all subtasks in the batch.
    """
    coros = [
        _execute_subtask_with_retry(subtask, context, workflow_id)
        for subtask in subtasks
    ]
    results: list[SubtaskResult] = await asyncio.gather(*coros)
    return results


# ---------------------------------------------------------------------------
# Planning Agent escalation (Req 17.5)
# ---------------------------------------------------------------------------


async def escalate_to_planning_agent(
    plan: ExecutionPlan,
    failed_subtasks: list[SubtaskResult],
    context: dict[str, Any],
) -> ExecutionPlan | None:
    """Escalate to the Planning Agent for re-planning (Req 17.5).

    When subtasks exhaust all retries, this function requests the Planning
    Agent to produce a revised execution plan that works around the failures.

    Parameters
    ----------
    plan:
        The original execution plan.
    failed_subtasks:
        Subtask results that could not be completed.
    context:
        Current workflow context.

    Returns
    -------
    ExecutionPlan | None
        A revised execution plan if re-planning succeeds, or None if
        re-planning is not possible.
    """
    logger.info(
        "replan_requested",
        extra={
            "plan_id": plan.plan_id,
            "failed_subtask_ids": [s.subtask_id for s in failed_subtasks],
            "failed_errors": [s.error for s in failed_subtasks],
        },
    )
    # In a full integration, this would invoke the Planning Agent to produce
    # a new plan. For now, return None indicating re-planning could not produce
    # an alternative.
    return None


# ---------------------------------------------------------------------------
# @entrypoint: run_parallel_workflow (Req 17.2, 17.4, 17.5)
# ---------------------------------------------------------------------------


@entrypoint(checkpointer=None)  # Checkpointer bound at runtime via app startup
async def run_parallel_workflow(
    plan: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute the parallel fan-out/fan-in workflow (Req 17.2).

    Processes an execution plan by scheduling independent subtasks in parallel
    (fan-out), synchronizing at each dependency level (fan-in), validating
    dependency constraints before dispatching dependents (Req 17.4), and
    retrying failures up to 3 times before escalating (Req 17.5).

    The workflow processes the DAG in topological layers: each layer contains
    subtasks whose prerequisites are all satisfied. Within a layer, subtasks
    execute concurrently.

    Parameters
    ----------
    plan:
        Serialized ``ExecutionPlan`` (dict) from the Planning Agent.
    context:
        Optional shared workflow context (e.g., tenant_id, branch).

    Returns
    -------
    dict
        Serialized ``ParallelWorkflowResult`` with subtask outcomes.
    """
    execution_plan = ExecutionPlan.model_validate(plan)
    workflow_id = str(uuid.uuid4())
    workflow_context = context or {}
    workflow_start_ms = time.perf_counter_ns() / 1_000_000

    # Emit workflow start event
    logger.info(
        "workflow_started",
        extra={
            "workflow_id": workflow_id,
            "plan_id": execution_plan.plan_id,
            "workflow_type": "parallel",
            "subtask_count": len(execution_plan.subtasks),
        },
    )

    # State tracking
    completed_ids: set[str] = set()
    in_progress_ids: set[str] = set()
    failed_ids: set[str] = set()
    all_results: list[SubtaskResult] = []
    escalated_subtasks: list[str] = []

    # Process DAG layer by layer (Req 17.2, 17.4)
    level = 0
    while True:
        # Determine which subtasks are ready (Req 17.4)
        ready = get_ready_subtasks(
            execution_plan, completed_ids, in_progress_ids, failed_ids
        )

        if not ready:
            # No more subtasks to schedule — done or blocked
            break

        level += 1
        ready_ids = [s.subtask_id for s in ready]
        in_progress_ids.update(ready_ids)

        # Emit fan-out event (Req 17.2)
        _emit_fanout_event(
            workflow_id=workflow_id,
            plan_id=execution_plan.plan_id,
            subtask_ids=ready_ids,
            level=str(level),
        )

        # Fan-out: execute ready subtasks in parallel (Req 17.2)
        batch_results = await _execute_parallel_batch(
            ready, workflow_context, workflow_id
        )

        # Fan-in: process results (Req 17.2)
        batch_completed = 0
        batch_failed = 0
        for result in batch_results:
            in_progress_ids.discard(result.subtask_id)
            all_results.append(result)

            if result.status == SubtaskStatus.COMPLETED:
                completed_ids.add(result.subtask_id)
                # Merge subtask output into workflow context
                workflow_context.update(result.output)
                batch_completed += 1
            else:
                # Subtask failed after retries — escalate (Req 17.5)
                failed_ids.add(result.subtask_id)
                escalated_subtasks.append(result.subtask_id)
                _emit_escalation_event(
                    workflow_id=workflow_id,
                    plan_id=execution_plan.plan_id,
                    subtask_id=result.subtask_id,
                    error=result.error or "unknown",
                )
                batch_failed += 1

        # Emit fan-in synchronization event
        _emit_fanin_event(
            workflow_id=workflow_id,
            plan_id=execution_plan.plan_id,
            subtask_ids=ready_ids,
            completed=batch_completed,
            failed=batch_failed,
        )

    # Escalate failed subtasks to Planning Agent for re-planning (Req 17.5)
    replan_requested = False
    if escalated_subtasks:
        failed_results = [r for r in all_results if r.subtask_id in escalated_subtasks]
        revised_plan = await escalate_to_planning_agent(
            execution_plan, failed_results, workflow_context
        )
        replan_requested = True
        if revised_plan is not None:
            logger.info(
                "replan_received",
                extra={
                    "workflow_id": workflow_id,
                    "original_plan_id": execution_plan.plan_id,
                    "revised_plan_id": revised_plan.plan_id,
                },
            )

    # Determine final status
    total_subtasks = len(execution_plan.subtasks)
    if len(completed_ids) == total_subtasks:
        final_status = "completed"
    elif escalated_subtasks:
        final_status = "partially_completed"
    else:
        final_status = "blocked"

    # Compute total duration
    workflow_end_ms = time.perf_counter_ns() / 1_000_000
    total_duration_ms = workflow_end_ms - workflow_start_ms

    # Emit workflow completion event
    logger.info(
        "workflow_completed",
        extra={
            "workflow_id": workflow_id,
            "plan_id": execution_plan.plan_id,
            "workflow_type": "parallel",
            "total_duration_ms": round(total_duration_ms, 2),
            "subtasks_completed": len(completed_ids),
            "subtasks_failed": len(failed_ids),
            "final_status": final_status,
            "replan_requested": replan_requested,
        },
    )

    result = ParallelWorkflowResult(
        workflow_id=workflow_id,
        plan_id=execution_plan.plan_id,
        subtask_results=all_results,
        total_duration_ms=round(total_duration_ms, 2),
        final_status=final_status,
        escalated_subtasks=escalated_subtasks,
        replan_requested=replan_requested,
    )

    # Return serializable dict for LangGraph entrypoint compatibility
    return {
        "workflow_id": result.workflow_id,
        "plan_id": result.plan_id,
        "subtask_results": [
            {
                "subtask_id": r.subtask_id,
                "assigned_agent": r.assigned_agent,
                "status": r.status.value,
                "output": r.output,
                "attempts": r.attempts,
                "duration_ms": r.duration_ms,
                "error": r.error,
            }
            for r in result.subtask_results
        ],
        "total_duration_ms": result.total_duration_ms,
        "final_status": result.final_status,
        "escalated_subtasks": result.escalated_subtasks,
        "replan_requested": result.replan_requested,
    }
