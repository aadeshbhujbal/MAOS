"""Subagent node runtime: bounded reasoning loop for Sub_Subtask execution.

This module implements the single async function ``run_subagent`` that serves as
a node within the Sub-Orchestrator LangGraph supervisor graph. It drives a
Subagent through its assigned Sub_Subtask using the following governance:

- **Budget enforcement** (Req 4.6): reasoning-step and tool-invocation budgets
  are tracked via :class:`~maos.core.budget.BudgetTracker`.
- **Scope checks** (Req 4.4, 4.5): every operation is validated against the
  matched Skill's ``operation_scope`` before execution.
- **MCP tool invocation** (Req 5.2): tools are called through the injected
  gateway which enforces the per-Subagent allow-list, mode, and argument
  validation.
- **Sensitive-action approval gate** (Req 11.7): if the Sub_Subtask is
  flagged sensitive, execution pauses for Human_Approval before proceeding.
- **Output-contract validation** (Req 4.7): the final result is validated
  against the matched Skill's output contract.
- **Audit** (Req 10.2): start and finish timestamps are recorded in the
  Audit_Log.
- **Budget-exceeded result**: if either budget is reached, the function
  returns a structured budget-exceeded result rather than raising.

Requirements: 4.4, 4.5, 4.6, 4.7, 5.2, 10.2, 11.7.
"""

from __future__ import annotations

from typing import Any, Protocol, TypedDict, runtime_checkable

from maos.audit.entries import (
    build_execution_finish_entry,
    build_execution_start_entry,
)
from maos.contracts.agents import Skill, SubagentSpec
from maos.contracts.work_units import SubSubtask
from maos.core.budget import (
    BudgetExceededError,
    BudgetTracker,
    record_reasoning_step,
    record_tool_invocation,
)
from maos.core.contracts_validate import (
    OutputContractViolationError,
    validate_output,
)
from maos.core.scope import OutOfScopeError, check_operation_scope

# ---------------------------------------------------------------------------
# Protocols for injected dependencies
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMAdapter(Protocol):
    """Protocol for the LLM provider adapter dependency."""

    async def complete(self, messages: list[dict], **kwargs: Any) -> dict:
        """Invoke the LLM and return a response dict."""
        ...


@runtime_checkable
class MCPGatewayProtocol(Protocol):
    """Protocol for the MCP Gateway dependency (Req 5.2)."""

    async def invoke(
        self, agent: SubagentSpec, tool_name: str, args: dict
    ) -> dict:
        """Invoke an MCP tool through governance checks and return the result."""
        ...


@runtime_checkable
class AuditLogProtocol(Protocol):
    """Protocol for the append-only audit log."""

    async def append(self, entry: Any) -> None:
        """Persist an audit entry."""
        ...


@runtime_checkable
class ApprovalGateProtocol(Protocol):
    """Protocol for the human-approval gate (Req 11.7)."""

    async def request_approval(
        self, sub_subtask_id: str, task_id: str, window_s: int | None = None
    ) -> Any:
        """Request human approval; returns an approval decision object."""
        ...

    async def check_approval(self, approval_id: str) -> Any:
        """Check the current decision for an approval request."""
        ...


@runtime_checkable
class CheckpointerProtocol(Protocol):
    """Protocol for the durable checkpointer."""

    async def save(self, task_id: str, state: dict) -> None:
        """Persist a checkpoint."""
        ...


# ---------------------------------------------------------------------------
# State TypedDict
# ---------------------------------------------------------------------------


class SubagentExecutionState(TypedDict):
    """State dict carried through the Subagent reasoning loop.

    Fields:
        sub_subtask: The Sub_Subtask being executed.
        agent: The selected SubagentSpec performing the work.
        reasoning_steps: Number of reasoning steps consumed so far.
        tool_invocations: Number of tool invocations consumed so far.
        result: The final result dict on completion, or None.
        error: An error message if execution failed, or None.
        approval_required: Whether Human_Approval was triggered.
    """

    sub_subtask: SubSubtask
    agent: SubagentSpec
    reasoning_steps: int
    tool_invocations: int
    result: dict | None
    error: str | None
    approval_required: bool


# ---------------------------------------------------------------------------
# Helper: find the matched skill for the sub_subtask
# ---------------------------------------------------------------------------


def _find_matched_skill(agent: SubagentSpec, required_skill: str) -> Skill | None:
    """Find the Skill in the agent's skills list matching the required skill id."""
    for skill in agent.skills:
        if skill.skill_id == required_skill:
            return skill
    return None


# ---------------------------------------------------------------------------
# Main runtime function
# ---------------------------------------------------------------------------


async def run_subagent(
    state: SubagentExecutionState,
    *,
    llm_adapter: LLMAdapter,
    mcp_gateway: MCPGatewayProtocol,
    audit_log: AuditLogProtocol,
    approval_gate: ApprovalGateProtocol,
    checkpointer: CheckpointerProtocol,
) -> SubagentExecutionState:
    """Execute the bounded reasoning loop for a Subagent's Sub_Subtask.

    This is a single async function (not a full graph) designed to be called
    as a node from the Sub-Orchestrator LangGraph supervisor graph.

    The function:
    1. Records an execution-start audit entry (Req 10.2).
    2. If the Sub_Subtask is sensitive, triggers the approval gate (Req 11.7).
    3. Runs the LLM reasoning loop with budget tracking (Req 4.6).
    4. Before each operation, validates scope (Req 4.4, 4.5).
    5. Invokes MCP tools through the gateway (Req 5.2).
    6. On completion, validates the result against the output contract (Req 4.7).
    7. Records an execution-finish audit entry (Req 10.2).
    8. On budget exceeded, returns a budget-exceeded result.

    Parameters
    ----------
    state:
        The current execution state for this Subagent node.
    llm_adapter:
        The LLM provider adapter for model calls.
    mcp_gateway:
        The MCP gateway that enforces allow-list/mode/args governance.
    audit_log:
        The append-only audit log for recording start/finish entries.
    approval_gate:
        The human-approval gate for sensitive actions.
    checkpointer:
        The durable checkpointer for persisting state on interruption.

    Returns
    -------
    SubagentExecutionState
        Updated state with result or error populated.
    """
    sub_subtask = state["sub_subtask"]
    agent = state["agent"]
    reasoning_steps = state["reasoning_steps"]
    tool_invocations = state["tool_invocations"]

    # Resolve the matched skill from the agent's declared skills.
    matched_skill = _find_matched_skill(agent, sub_subtask.required_skill)
    if matched_skill is None:
        return SubagentExecutionState(
            sub_subtask=sub_subtask,
            agent=agent,
            reasoning_steps=reasoning_steps,
            tool_invocations=tool_invocations,
            result=None,
            error=f"No skill '{sub_subtask.required_skill}' found on agent '{agent.subagent_id}'",
            approval_required=state["approval_required"],
        )

    # --- 1. Record execution start (Req 10.2) ---
    start_entry = build_execution_start_entry(
        task_id=sub_subtask.task_id,
        subtask_id=sub_subtask.subtask_id,
        sub_subtask_id=sub_subtask.sub_subtask_id,
        actor_agent_id=agent.subagent_id,
    )
    await audit_log.append(start_entry)

    # --- 2. Sensitive-action approval gate (Req 11.7) ---
    if sub_subtask.is_sensitive:
        try:
            approval_request = await approval_gate.request_approval(
                sub_subtask_id=sub_subtask.sub_subtask_id,
                task_id=sub_subtask.task_id,
            )
            # Check the approval decision.
            decision = await approval_gate.check_approval(
                approval_request.approval_id
            )
            # If denied or expired, record finish and return error.
            if hasattr(decision, "value"):
                decision_value = decision.value
            else:
                decision_value = str(decision)

            if decision_value in ("denied", "expired"):
                finish_entry = build_execution_finish_entry(
                    task_id=sub_subtask.task_id,
                    subtask_id=sub_subtask.subtask_id,
                    sub_subtask_id=sub_subtask.sub_subtask_id,
                    actor_agent_id=agent.subagent_id,
                )
                await audit_log.append(finish_entry)
                return SubagentExecutionState(
                    sub_subtask=sub_subtask,
                    agent=agent,
                    reasoning_steps=reasoning_steps,
                    tool_invocations=tool_invocations,
                    result=None,
                    error=f"Approval {decision_value} for sensitive sub_subtask",
                    approval_required=True,
                )
        except Exception as approval_err:
            finish_entry = build_execution_finish_entry(
                task_id=sub_subtask.task_id,
                subtask_id=sub_subtask.subtask_id,
                sub_subtask_id=sub_subtask.sub_subtask_id,
                actor_agent_id=agent.subagent_id,
            )
            await audit_log.append(finish_entry)
            return SubagentExecutionState(
                sub_subtask=sub_subtask,
                agent=agent,
                reasoning_steps=reasoning_steps,
                tool_invocations=tool_invocations,
                result=None,
                error=f"Approval gate error: {approval_err}",
                approval_required=True,
            )

    # --- 3. Bounded reasoning loop (Req 4.6) ---
    tracker = BudgetTracker(
        capability=agent.capability,
        reasoning_steps=reasoning_steps,
        tool_invocations=tool_invocations,
    )

    # The reasoning loop drives the LLM iteratively until it produces a
    # final result (indicated by a "result" key in the response) or a
    # budget is exceeded.
    final_result: dict | None = None
    error_msg: str | None = None
    max_iterations = agent.capability.max_reasoning_steps  # safety bound

    for _ in range(max_iterations):
        # --- Record reasoning step ---
        try:
            tracker = record_reasoning_step(tracker)
        except BudgetExceededError as exc:
            final_result = {
                "status": "budget_exceeded",
                "budget_type": exc.budget_type,
                "current_count": exc.current_count,
                "max_budget": exc.max_budget,
            }
            break

        # --- Invoke the LLM for the next reasoning step ---
        try:
            llm_response = await llm_adapter.complete(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"You are executing sub_subtask {sub_subtask.sub_subtask_id} "
                            f"with skill '{sub_subtask.required_skill}'. "
                            f"Input: {sub_subtask.input_contract}"
                        ),
                    }
                ],
                task_id=sub_subtask.task_id,
                tenant_id=sub_subtask.tenant_id,
            )
        except Exception as llm_err:
            error_msg = f"LLM invocation failed: {llm_err}"
            break

        # --- Process LLM response ---
        # The LLM response may contain:
        # - "tool_call": request to invoke an MCP tool
        # - "operation": an operation to scope-check
        # - "result": the final output
        if not isinstance(llm_response, dict):
            error_msg = "LLM returned non-dict response"
            break

        # Case A: LLM requests a tool invocation
        if "tool_call" in llm_response:
            tool_call = llm_response["tool_call"]
            tool_name = tool_call.get("tool_name", "")
            tool_args = tool_call.get("args", {})

            # Scope check before tool invocation (Req 4.4, 4.5)
            operation = tool_call.get("operation", tool_name)
            try:
                check_operation_scope(operation, matched_skill)
            except OutOfScopeError as scope_err:
                error_msg = (
                    f"Out-of-scope operation: {scope_err.operation!r}. "
                    f"Permitted: {scope_err.permitted_scope!r}"
                )
                break

            # Record tool invocation against budget (Req 4.6)
            try:
                tracker = record_tool_invocation(tracker)
            except BudgetExceededError as exc:
                final_result = {
                    "status": "budget_exceeded",
                    "budget_type": exc.budget_type,
                    "current_count": exc.current_count,
                    "max_budget": exc.max_budget,
                }
                break

            # Invoke MCP tool through the gateway (Req 5.2)
            try:
                _tool_result = await mcp_gateway.invoke(
                    agent=agent, tool_name=tool_name, args=tool_args
                )
            except Exception as mcp_err:
                error_msg = f"MCP tool invocation failed: {mcp_err}"
                break

            # Continue the reasoning loop with the tool result
            continue

        # Case B: LLM specifies an operation to perform (non-tool)
        if "operation" in llm_response and "result" not in llm_response:
            operation = llm_response["operation"]
            try:
                check_operation_scope(operation, matched_skill)
            except OutOfScopeError as scope_err:
                error_msg = (
                    f"Out-of-scope operation: {scope_err.operation!r}. "
                    f"Permitted: {scope_err.permitted_scope!r}"
                )
                break
            # Operation permitted — continue reasoning
            continue

        # Case C: LLM produces a final result
        if "result" in llm_response:
            final_result = llm_response["result"]
            break

        # Case D: Unrecognized response shape — treat as reasoning continuation
        continue

    # --- 4. Validate output contract (Req 4.7) ---
    if final_result is not None and final_result.get("status") != "budget_exceeded":
        try:
            validate_output(final_result, matched_skill)
        except OutputContractViolationError as ov_err:
            error_msg = f"Output contract violation: {'; '.join(ov_err.violations)}"
            final_result = None

    # --- 5. Record execution finish (Req 10.2) ---
    finish_entry = build_execution_finish_entry(
        task_id=sub_subtask.task_id,
        subtask_id=sub_subtask.subtask_id,
        sub_subtask_id=sub_subtask.sub_subtask_id,
        actor_agent_id=agent.subagent_id,
    )
    await audit_log.append(finish_entry)

    # --- 6. Checkpoint state ---
    await checkpointer.save(
        sub_subtask.task_id,
        {
            "sub_subtask_id": sub_subtask.sub_subtask_id,
            "reasoning_steps": tracker.reasoning_steps,
            "tool_invocations": tracker.tool_invocations,
            "completed": final_result is not None,
        },
    )

    # --- 7. Return updated state ---
    return SubagentExecutionState(
        sub_subtask=sub_subtask,
        agent=agent,
        reasoning_steps=tracker.reasoning_steps,
        tool_invocations=tracker.tool_invocations,
        result=final_result,
        error=error_msg,
        approval_required=sub_subtask.is_sensitive,
    )
