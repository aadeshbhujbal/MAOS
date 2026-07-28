"""Planning Agent - task decomposition and execution plan generation.

The Planning Agent is responsible for:
- Analyzing incoming task requests and decomposing them into subtasks (Req 11.1)
- Assigning each subtask to the most appropriate specialized agent (Req 11.3)
- Estimating effort levels for each subtask (Req 11.6)
- Building a dependency graph between subtasks (Req 11.2)
- Validating the plan is an acyclic DAG (Req 11.4)
- Requesting clarification when domain keywords are ambiguous (Req 11.7)

The Planning Agent operates as a LangGraph node that produces an ExecutionPlan
which is consumed by the Root Orchestrator.

Requirements: 2.1, 11.1, 11.2, 11.3, 11.4, 11.6, 11.7.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime

from maos.planning.assignment import assign_agent, estimate_effort
from maos.planning.models import (
    ExecutionPlan,
    PlannedSubtask,
    PlanValidationResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Subtask decomposition patterns
# ---------------------------------------------------------------------------
# These patterns identify common task structures in natural language requests
# to help decompose complex requests into subtasks.
# ---------------------------------------------------------------------------

_CONJUNCTIONS = re.compile(
    r"\band\b|\bthen\b|\bnext\b|\bafter\b|\bfollowed by\b|;",
    re.IGNORECASE,
)

_NUMBERED_LIST = re.compile(r"^\d+\.\s+", re.MULTILINE)

_BULLET_LIST = re.compile(r"^[-•*]\s+", re.MULTILINE)

_COMMA_SEPARATED = re.compile(r",\s+(?:and\s+)?")


class PlanningAgent:
    """Planning Agent for task decomposition and execution plan generation.

    The Planning Agent analyzes a natural language request, decomposes it into
    subtasks, assigns each subtask to an appropriate agent, estimates effort,
    and builds a dependency graph to produce an ExecutionPlan.

    Attributes:
        max_subtasks: Maximum number of subtasks to generate (default: 20)
        require_clarification: Whether to request clarification for ambiguous domains

    Requirements: 2.1, 11.1, 11.2, 11.3, 11.4, 11.6, 11.7
    """

    def __init__(
        self,
        max_subtasks: int = 20,
        require_clarification: bool = True,
    ) -> None:
        """Initialize the Planning Agent.

        Parameters
        ----------
        max_subtasks:
            Maximum number of subtasks to generate. Requests that would decompose
            into more subtasks will be rejected or require clarification.
        require_clarification:
            Whether to request clarification when domain keywords are ambiguous
            rather than making best-guess assignments (Req 11.7).
        """
        self.max_subtasks = max_subtasks
        self.require_clarification = require_clarification

    # ------------------------------------------------------------------
    # Main planning interface
    # ------------------------------------------------------------------

    async def create_plan(
        self,
        request_text: str,
        task_id: str | None = None,
    ) -> ExecutionPlan:
        """Create an execution plan for a given request.

        Decomposes the request into subtasks, assigns agents, estimates effort,
        builds dependencies, and validates the plan is an acyclic DAG.

        Parameters
        ----------
        request_text:
            Natural language description of the task to plan.
        task_id:
            Optional task identifier to associate with the plan.

        Returns
        -------
        ExecutionPlan
            The generated execution plan with subtasks, dependencies, and validation.

        Raises
        ------
        ValueError
            If the request is too complex (exceeds max_subtasks) or if
            clarification is required and require_clarification is True.
        """
        logger.info(
            "Creating execution plan",
            extra={"task_id": task_id, "request_length": len(request_text)},
        )

        # Decompose request into subtask descriptions
        subtask_descriptions = self._decompose_request(request_text)

        if len(subtask_descriptions) > self.max_subtasks:
            error_msg = (
                f"Request is too complex: would decompose into "
                f"{len(subtask_descriptions)} subtasks (max: {self.max_subtasks}). "
                "Please break this into multiple smaller requests."
            )
            logger.warning(
                "Request exceeds max subtasks",
                extra={
                    "task_id": task_id,
                    "subtask_count": len(subtask_descriptions),
                    "max_subtasks": self.max_subtasks,
                },
            )
            raise ValueError(error_msg)

        # Build PlannedSubtask instances with agent assignment and effort estimation
        subtasks: list[PlannedSubtask] = []
        requires_clarification = False

        for idx, description in enumerate(subtask_descriptions, start=1):
            subtask_id = f"{task_id or 'plan'}_subtask_{idx}_{uuid.uuid4().hex[:8]}"

            # Assign agent using domain keywords (Req 11.3)
            assigned_agent = assign_agent(description)

            # Check if clarification is needed (Req 11.7)
            if assigned_agent.startswith("CLARIFICATION_NEEDED"):
                requires_clarification = True
                if self.require_clarification:
                    logger.info(
                        "Clarification needed for subtask",
                        extra={
                            "subtask_id": subtask_id,
                            "description": description,
                        },
                    )

            # Estimate effort (Req 11.6)
            effort = estimate_effort(description)

            # Extract domain from assigned agent (fallback to "general" if clarification needed)
            domain = (
                assigned_agent.replace("_Agent", "").lower()
                if not assigned_agent.startswith("CLARIFICATION_")
                else "general"
            )

            subtask = PlannedSubtask(
                subtask_id=subtask_id,
                description=description,
                assigned_agent=assigned_agent,
                effort_estimate=effort,
                prerequisites=[],
                domain=domain,
                expected_outputs=[],  # Will be populated by execution
            )
            subtasks.append(subtask)

        if requires_clarification and self.require_clarification:
            raise ValueError(
                "CLARIFICATION_NEEDED: One or more subtasks could not be assigned "
                "to a specific agent based on domain keywords. Please clarify the "
                "domain(s) involved or provide more specific technical details."
            )

        # Build dependency graph (Req 11.2)
        dependency_graph = self._build_dependency_graph(subtasks)

        # Calculate total estimated effort
        total_effort = self._calculate_total_effort(subtasks)

        # Create the plan
        plan = ExecutionPlan(
            plan_id=f"plan_{uuid.uuid4().hex}",
            request_text=request_text,
            subtasks=subtasks,
            dependency_graph=dependency_graph,
            total_estimated_effort=total_effort,
            created_at=datetime.now(UTC),
            status="draft",
        )

        # Validate the plan is an acyclic DAG (Req 11.4)
        validation = self.validate_plan(plan)
        if not validation.is_valid:
            errors: list[str] = []
            if not validation.is_acyclic:
                errors.append("contains cycles")
            if validation.orphaned_subtasks:
                orphan_list = ", ".join(validation.orphaned_subtasks)
                errors.append(f"has orphaned subtasks: {orphan_list}")
            error_msg = "Generated plan failed validation: " + "; ".join(errors)
            logger.error(
                "Plan validation failed",
                extra={
                    "plan_id": plan.plan_id,
                    "is_acyclic": validation.is_acyclic,
                    "orphaned_subtasks": validation.orphaned_subtasks,
                },
            )
            raise ValueError(error_msg)

        logger.info(
            "Execution plan created successfully",
            extra={
                "plan_id": plan.plan_id,
                "subtask_count": len(subtasks),
                "total_effort": total_effort,
            },
        )

        return plan

    # ------------------------------------------------------------------
    # Request decomposition
    # ------------------------------------------------------------------

    def _decompose_request(self, request_text: str) -> list[str]:
        """Decompose a request into subtask descriptions.

        Identifies subtasks based on common patterns:
        - Numbered lists (1., 2., 3., ...)
        - Bullet points (-, •, *)
        - Conjunctions (and, then, next, after)
        - Comma-separated clauses

        Parameters
        ----------
        request_text:
            Natural language request text.

        Returns
        -------
        list[str]
            List of subtask descriptions in execution order.
        """
        request_text = request_text.strip()
        subtasks: list[str] = []

        # Try numbered list decomposition first
        numbered_matches = list(_NUMBERED_LIST.finditer(request_text))
        if len(numbered_matches) > 1:
            # Split by numbered list markers
            parts = _NUMBERED_LIST.split(request_text)
            subtasks = [p.strip() for p in parts if p.strip()]
            logger.debug(
                "Decomposed using numbered list pattern",
                extra={"subtask_count": len(subtasks)},
            )
            return subtasks

        # Try bullet list decomposition
        bullet_matches = list(_BULLET_LIST.finditer(request_text))
        if len(bullet_matches) > 1:
            parts = _BULLET_LIST.split(request_text)
            subtasks = [p.strip() for p in parts if p.strip()]
            logger.debug(
                "Decomposed using bullet list pattern",
                extra={"subtask_count": len(subtasks)},
            )
            return subtasks

        # Try conjunction-based decomposition
        if _CONJUNCTIONS.search(request_text):
            parts = _CONJUNCTIONS.split(request_text)
            subtasks = [p.strip() for p in parts if p.strip()]
            if len(subtasks) > 1:
                logger.debug(
                    "Decomposed using conjunction pattern",
                    extra={"subtask_count": len(subtasks)},
                )
                return subtasks

        # Try comma-separated decomposition (for simple multi-step requests)
        if "," in request_text:
            parts = _COMMA_SEPARATED.split(request_text)
            if len(parts) > 1:
                subtasks = [p.strip() for p in parts if p.strip()]
                logger.debug(
                    "Decomposed using comma pattern",
                    extra={"subtask_count": len(subtasks)},
                )
                return subtasks

        # Default: treat entire request as a single subtask
        logger.debug("No decomposition patterns found, treating as single subtask")
        return [request_text]

    # ------------------------------------------------------------------
    # Dependency graph construction
    # ------------------------------------------------------------------

    def _build_dependency_graph(
        self,
        subtasks: list[PlannedSubtask],
    ) -> dict[str, list[str]]:
        """Build a dependency graph for the subtasks.

        For now, uses a simple sequential dependency model where each subtask
        depends on the previous one. In a full implementation, this would use
        more sophisticated analysis to identify actual data dependencies.

        Parameters
        ----------
        subtasks:
            List of planned subtasks in execution order.

        Returns
        -------
        dict[str, list[str]]
            Mapping from subtask_id to list of prerequisite subtask_ids.
        """
        dependency_graph: dict[str, list[str]] = {}

        for idx, subtask in enumerate(subtasks):
            if idx == 0:
                # First subtask has no dependencies
                dependency_graph[subtask.subtask_id] = []
            else:
                # Each subtask depends on the previous one (sequential)
                previous_id = subtasks[idx - 1].subtask_id
                dependency_graph[subtask.subtask_id] = [previous_id]

        return dependency_graph

    def _calculate_total_effort(
        self,
        subtasks: list[PlannedSubtask],
    ) -> str:
        """Calculate total estimated effort for the plan.

        Uses a simple weighted sum: small=1, medium=3, large=8.

        Parameters
        ----------
        subtasks:
            List of planned subtasks.

        Returns
        -------
        str
            Human-readable description of total effort.
        """
        weights = {"small": 1, "medium": 3, "large": 8}
        total_score = sum(weights[sub.effort_estimate] for sub in subtasks)

        if total_score <= 3:
            return "small"
        elif total_score <= 10:
            return "medium"
        elif total_score <= 20:
            return "large"
        return "very_large"

    # ------------------------------------------------------------------
    # Plan validation
    # ------------------------------------------------------------------

    def validate_plan(self, plan: ExecutionPlan) -> PlanValidationResult:
        """Validate an execution plan.

        Checks that:
        - The dependency graph is acyclic (Req 11.4)
        - All subtasks are reachable from the start (no orphans)

        Parameters
        ----------
        plan:
            The execution plan to validate.

        Returns
        -------
        PlanValidationResult
            Validation result with details on any issues found.
        """
        is_acyclic = self._check_acyclic(plan)
        orphaned_subtasks = self._find_orphaned_subtasks(plan)

        is_valid = is_acyclic and not orphaned_subtasks

        return PlanValidationResult(
            is_valid=is_valid,
            is_acyclic=is_acyclic,
            cycle_details=[] if is_acyclic else ["Cycle detected in dependency graph"],
            orphaned_subtasks=orphaned_subtasks,
        )

    def _check_acyclic(self, plan: ExecutionPlan) -> bool:
        """Check if the dependency graph is acyclic using depth-first search.

        Parameters
        ----------
        plan:
            The execution plan to check.

        Returns
        -------
        bool
            True if the graph is acyclic, False if cycles are detected.
        """
        visited: set[str] = set()
        rec_stack: set[str] = set()

        def dfs(node: str) -> bool:
            """Recursive DFS to detect cycles."""
            visited.add(node)
            rec_stack.add(node)

            for neighbor in plan.dependency_graph.get(node, []):
                if neighbor not in visited:
                    if not dfs(neighbor):
                        return False
                elif neighbor in rec_stack:
                    return False  # Cycle detected

            rec_stack.remove(node)
            return True

        for node in plan.dependency_graph:
            if node not in visited and not dfs(node):
                return False

        return True

    def _find_orphaned_subtasks(self, plan: ExecutionPlan) -> list[str]:
        """Find subtasks that are not reachable from any start node.

        A start node is a subtask with no prerequisites. Orphaned subtasks
        are those that are not reachable from any start node via the dependency graph.

        Parameters
        ----------
        plan:
            The execution plan to check.

        Returns
        -------
        list[str]
            List of orphaned subtask IDs.
        """
        # Find start nodes (no prerequisites)
        start_nodes = [
            subtask.subtask_id
            for subtask in plan.subtasks
            if not plan.dependency_graph.get(subtask.subtask_id)
        ]

        if not start_nodes:
            # No start nodes means all subtasks are prerequisites of each other
            # (which would indicate a cycle or complete graph)
            return [subtask.subtask_id for subtask in plan.subtasks]

        # BFS from all start nodes
        reachable: set[str] = set()
        queue = list(start_nodes)

        while queue:
            node = queue.pop(0)
            if node in reachable:
                continue
            reachable.add(node)

            # Find all subtasks that depend on this node
            for subtask in plan.subtasks:
                if (
                    node in plan.dependency_graph.get(subtask.subtask_id, [])
                    and subtask.subtask_id not in reachable
                ):
                    queue.append(subtask.subtask_id)

        # Orphans are subtasks not reachable from any start node
        orphaned = [
            subtask.subtask_id
            for subtask in plan.subtasks
            if subtask.subtask_id not in reachable
        ]

        return orphaned
