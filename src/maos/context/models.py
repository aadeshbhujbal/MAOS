"""Context Engine domain contracts for MAOS.

This module defines the real-time state tracking models used by the Context
Engine to maintain tenant-scoped development context:

- ``ContextEvent`` — an inbound event updating context state (Req 15.3).
- ``ContextState`` — the full tenant context snapshot cached in Redis (Req 15.1).
- ``AgentContext`` — role-filtered subset of context injected into agents (Req 15.8).

These are pure Pydantic v2 contracts: they carry no behaviour beyond validation
so the Context Engine and Hypothesis correctness properties can construct and
reason about them deterministically.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ContextEvent(BaseModel):
    """An inbound event that updates the tenant's context state (Req 15.3)."""

    event_type: str
    tenant_id: str
    timestamp: datetime
    payload: dict[str, str] = {}


class ContextState(BaseModel):
    """Full tenant context snapshot cached in Redis (Req 15.1, 15.2)."""

    tenant_id: str
    open_files: list[str] = []
    active_branches: list[str] = []
    current_sprint: str = ""
    assigned_issues: list[str] = []
    running_deployments: list[str] = []
    recent_commits: list[str] = []
    active_incidents: list[str] = []
    updated_at: datetime


class AgentContext(BaseModel):
    """Role-filtered context subset injected into agent prompts (Req 15.8)."""

    agent_role: str
    relevant_files: list[str] = []
    relevant_branches: list[str] = []
    relevant_deployments: list[str] = []
    relevant_incidents: list[str] = []
    relevant_issues: list[str] = []
    recent_changes: list[str] = []
