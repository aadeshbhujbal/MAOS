"""Work-unit domain contracts for MAOS.

This module defines the three-level work-unit hierarchy used throughout the
orchestration core — ``Task`` (root), ``Subtask`` (per Platform_System), and
``SubSubtask`` (skill-scoped unit assigned to a Subagent) — together with the
shared enumerations they depend on (``OperatingMode``, ``PlatformSystem``, and
the ``WorkUnitState`` lifecycle).

These are pure Pydantic v2 contracts: they carry no behaviour beyond validation
so the orchestration logic and Hypothesis correctness properties can construct
and reason about them deterministically.

Traceability:
- Every Subtask references its parent ``task_id`` (Req 1.4).
- Every SubSubtask references both ``subtask_id`` and ``task_id`` (Req 2.2).
- ``mode`` is required on a Task (Req 1.6) and propagated to its children.
- ``is_sensitive`` gates Human_Approval for RUNTIME actions (Req 11.7).
- ``token_budget`` records the per-Task budget (Req 15.5).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class OperatingMode(str, Enum):
    """Operating mode for a work unit (Req 1.6)."""

    DEVELOPMENT = "DEVELOPMENT"
    RUNTIME = "RUNTIME"


class PlatformSystem(str, Enum):
    """Target Platform_System for a Subtask / SubSubtask (Req 1.3)."""

    BACKEND = "BACKEND"
    WEB = "WEB"
    MOBILE = "MOBILE"


class WorkUnitState(str, Enum):
    """Lifecycle state shared by all work units (state machine, Req 2.7)."""

    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    PERMANENTLY_FAILED = "permanently_failed"


class Task(BaseModel):
    """Root work unit submitted by a requester (Req 1)."""

    task_id: str                       # ULID, server-assigned
    tenant_id: str                     # clinic scope (Req 9.1)
    requester_id: str
    auth_scope: list[str]              # RBAC scopes (Req 9.4)
    mode: OperatingMode                # required (Req 1.6)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    payload: dict                      # validated against Task input contract
    token_budget: int                  # per-Task budget (Req 15.5)
    created_at: datetime


class Subtask(BaseModel):
    """Per-Platform_System decomposition of a Task (Req 1.3, 1.4)."""

    subtask_id: str
    task_id: str                       # traceable to Task (Req 1.4)
    platform_system: PlatformSystem    # exactly one (Req 1.3)
    mode: OperatingMode                # propagated from Task (Req 1.6)
    tenant_id: str
    input_contract: dict
    state: WorkUnitState = WorkUnitState.ASSIGNED


class SubSubtask(BaseModel):
    """Skill-scoped unit assigned to a Subagent (Req 2)."""

    sub_subtask_id: str
    subtask_id: str                    # traceable (Req 2.2)
    task_id: str                       # traceable (Req 2.2)
    platform_system: PlatformSystem
    mode: OperatingMode
    tenant_id: str
    required_skill: str
    input_contract: dict
    is_sensitive: bool = False         # gates Human_Approval (Req 11.7)
    assigned_subagent_id: str | None = None
    attempts: int = 0
    state: WorkUnitState = WorkUnitState.ASSIGNED
