"""Result-aggregation contracts for the work-unit hierarchy.

Defines the per-unit result captured for a Sub_Subtask (``SubSubtaskResult``),
the Subtask-level aggregate produced by a Sub_Orchestrator (``SubtaskResult``),
and the Task-level aggregate produced by the Root_Orchestrator (``TaskResult``).
These are pure Pydantic v2 contracts consumed by ``aggregate_subtask`` /
``aggregate_task``.

Traceability:
- Each result carries its unit's terminal ``state`` and identifiers, so the
  Task result can report the status of every Subtask and Sub_Subtask together
  with their ids (Req 12.3).
- ``TaskResult`` references the originating ``task_id`` returned to the
  Requester (Req 12.4).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from maos.contracts.work_units import PlatformSystem, WorkUnitState


class SubSubtaskResult(BaseModel):
    """Terminal result of a single Sub_Subtask (Req 12.1, 12.3)."""

    sub_subtask_id: str
    subtask_id: str                    # traceable (Req 12.3)
    task_id: str                       # traceable (Req 12.3)
    state: WorkUnitState               # terminal state of the unit (Req 12.3)
    assigned_subagent_id: str | None = None  # executing Subagent id (Req 3.4)
    attempts: int = 0
    output: dict | None = None         # conforms to Skill output contract on success
    error: str | None = None           # populated when not completed


class SubtaskResult(BaseModel):
    """Aggregate of all Sub_Subtask results for a Subtask (Req 12.1, 12.3)."""

    subtask_id: str
    task_id: str                       # traceable (Req 12.3)
    platform_system: PlatformSystem    # preserved association (Req 3.4)
    state: WorkUnitState               # aggregated terminal state (Req 12.1)
    sub_subtask_results: list[SubSubtaskResult] = Field(default_factory=list)


class TaskResult(BaseModel):
    """Aggregate Task result returned to the Requester (Req 12.2, 12.3, 12.4)."""

    task_id: str                       # originating Task id (Req 12.4)
    state: WorkUnitState               # aggregated terminal state (Req 12.2)
    subtask_results: list[SubtaskResult] = Field(default_factory=list)
    created_at: datetime
