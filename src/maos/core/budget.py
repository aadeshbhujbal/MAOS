"""Reasoning-step and tool-invocation budget accounting (pure core).

This module provides a pure, side-effect-free budget tracker that counts
reasoning steps and tool invocations against the declared
:class:`~maos.contracts.agents.AgenticCapability` budgets
(``max_reasoning_steps``, ``max_tool_invocations``).

Usage:
    >>> from maos.contracts.agents import AgenticCapability
    >>> cap = AgenticCapability(max_reasoning_steps=5, max_tool_invocations=3)
    >>> tracker = BudgetTracker(capability=cap)
    >>> tracker = record_reasoning_step(tracker)
    >>> tracker = record_tool_invocation(tracker)

When a budget limit is reached, a :exc:`BudgetExceededError` is raised
containing the ``budget_type`` and the current counts at the point of
violation.

Requirements: 4.3, 4.6
"""

from __future__ import annotations

from dataclasses import dataclass

from maos.contracts.agents import AgenticCapability


class BudgetExceededError(Exception):
    """Raised when an agent reaches its declared reasoning-step or tool-invocation budget.

    Attributes:
        budget_type: Either ``"reasoning_steps"`` or ``"tool_invocations"``.
        current_count: The count at which the budget was exceeded (equal to the max).
        max_budget: The declared maximum from AgenticCapability.
    """

    def __init__(
        self,
        budget_type: str,
        current_count: int,
        max_budget: int,
    ) -> None:
        self.budget_type = budget_type
        self.current_count = current_count
        self.max_budget = max_budget
        super().__init__(
            f"Budget exceeded: {budget_type} reached {current_count}/{max_budget}"
        )


@dataclass(frozen=True)
class BudgetTracker:
    """Immutable tracker for reasoning steps and tool invocations.

    The tracker is a pure value object — each recording operation returns a new
    instance with updated counts while the original remains unchanged.

    Attributes:
        capability: The declared budgets from the Subagent's AgenticCapability.
        reasoning_steps: Number of reasoning steps recorded so far.
        tool_invocations: Number of tool invocations recorded so far.
    """

    capability: AgenticCapability
    reasoning_steps: int = 0
    tool_invocations: int = 0


def record_reasoning_step(tracker: BudgetTracker) -> BudgetTracker:
    """Increment the reasoning step count and return an updated tracker.

    Raises:
        BudgetExceededError: If the reasoning-step budget has already been
            reached (i.e., ``reasoning_steps >= max_reasoning_steps``).
    """
    new_count = tracker.reasoning_steps + 1
    if new_count > tracker.capability.max_reasoning_steps:
        raise BudgetExceededError(
            budget_type="reasoning_steps",
            current_count=new_count,
            max_budget=tracker.capability.max_reasoning_steps,
        )
    return BudgetTracker(
        capability=tracker.capability,
        reasoning_steps=new_count,
        tool_invocations=tracker.tool_invocations,
    )


def record_tool_invocation(tracker: BudgetTracker) -> BudgetTracker:
    """Increment the tool invocation count and return an updated tracker.

    Raises:
        BudgetExceededError: If the tool-invocation budget has already been
            reached (i.e., ``tool_invocations >= max_tool_invocations``).
    """
    new_count = tracker.tool_invocations + 1
    if new_count > tracker.capability.max_tool_invocations:
        raise BudgetExceededError(
            budget_type="tool_invocations",
            current_count=new_count,
            max_budget=tracker.capability.max_tool_invocations,
        )
    return BudgetTracker(
        capability=tracker.capability,
        reasoning_steps=tracker.reasoning_steps,
        tool_invocations=new_count,
    )


# ---------------------------------------------------------------------------
# Per-Task token-budget enforcement (pure, no I/O)
# Requirements: 15.5, 15.6
# ---------------------------------------------------------------------------


class TokenBudgetExceededError(Exception):
    """Raised when a Task's cumulative token usage reaches or exceeds its configured budget.

    The Cost_Meter calls :func:`check_token_budget` before each model invocation.
    When this exception is raised, no further model invocations should occur for
    that Task and a budget-exceeded result must be returned to the caller.

    Attributes:
        task_id: The identifier of the Task whose budget was exceeded.
        cumulative_tokens: The cumulative token count at the point of violation.
        budget: The configured per-Task token budget.
    """

    def __init__(
        self,
        task_id: str,
        cumulative_tokens: int,
        budget: int,
    ) -> None:
        self.task_id = task_id
        self.cumulative_tokens = cumulative_tokens
        self.budget = budget
        super().__init__(
            f"Token budget exceeded for task {task_id}: "
            f"{cumulative_tokens}/{budget} tokens consumed"
        )


def check_token_budget(cumulative_tokens: int, budget: int, task_id: str) -> None:
    """Guard that stops further model invocations when the token budget is reached.

    This pure function is called by the Cost_Meter before each model invocation.
    If the cumulative token usage has reached or exceeded the configured budget,
    it raises :exc:`TokenBudgetExceededError`; otherwise it returns ``None``
    silently, indicating the invocation may proceed.

    Args:
        cumulative_tokens: Total tokens consumed so far for the given Task.
        budget: The configured per-Task token budget ceiling.
        task_id: Identifier of the Task being checked.

    Returns:
        None when usage is within budget.

    Raises:
        TokenBudgetExceededError: When ``cumulative_tokens >= budget``.
    """
    if cumulative_tokens >= budget:
        raise TokenBudgetExceededError(
            task_id=task_id,
            cumulative_tokens=cumulative_tokens,
            budget=budget,
        )
