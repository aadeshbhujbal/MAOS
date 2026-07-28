"""Planning domain contracts for MAOS.

This module defines the execution plan models produced by the Planning Agent:

- ``PlannedSubtask`` — a single unit of work within an execution plan (Req 11.1).
- ``ExecutionPlan`` — the full decomposition with DAG dependencies (Req 11.2).
- ``PlanValidationResult`` — DAG validation outcome (Req 11.4).

These are pure Pydantic v2 contracts: they carry no behaviour beyond validation
so the Planning Agent and Hypothesis correctness properties can construct and
reason about them deterministically.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PlannedSubtask(BaseModel):
    """A single unit of work within an execution plan (Req 11.1, 11.3)."""

    subtask_id: str
    description: str
    assigned_agent: str
    effort_estimate: Literal["small", "medium", "large"]
    prerequisites: list[str] = []
    domain: str
    expected_outputs: list[str] = []


class ExecutionPlan(BaseModel):
    """Full decomposition of a request into a DAG of subtasks (Req 11.2)."""

    plan_id: str
    request_text: str
    subtasks: list[PlannedSubtask] = Field(min_length=1)
    dependency_graph: dict[str, list[str]]
    total_estimated_effort: str
    created_at: datetime
    status: Literal["draft", "validated", "executing", "completed", "failed"] = "draft"


class PlanValidationResult(BaseModel):
    """DAG validation outcome reporting acyclicity and orphans (Req 11.4)."""

    is_valid: bool
    is_acyclic: bool
    cycle_details: list[str] = []
    orphaned_subtasks: list[str] = []
