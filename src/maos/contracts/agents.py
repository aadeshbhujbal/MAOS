"""Agent capability domain contracts for MAOS.

This module defines the capability models that describe what a Subagent can do
and how it is selected for work:

- ``Skill`` — a named capability with JSON Schema input/output contracts and a
  permitted ``operation_scope`` (Req 4.2, 4.4).
- ``AgenticCapability`` — the per-Subagent reasoning/tool budgets that bound
  autonomous execution (Req 4.3, 4.6).
- ``SubagentSpec`` — the registry record binding a Subagent to a single
  Platform_System and OperatingMode, the skills it declares, its capability
  budgets, and its MCP allow-list (Req 4.1, 5.1), plus the deterministic
  selection metadata (``status`` / ``selection_priority``, Req 2.5).

These are pure Pydantic v2 contracts: they carry no behaviour beyond validation
so the Agent_Registry and Hypothesis correctness properties can construct and
reason about them deterministically. ``OperatingMode`` and ``PlatformSystem``
are imported from :mod:`maos.contracts.work_units` and are not redefined here.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from maos.contracts.work_units import OperatingMode, PlatformSystem


class Skill(BaseModel):
    """A named Subagent capability with input/output contracts and scope (Req 4.2)."""

    skill_id: str
    input_contract: dict               # JSON Schema (Req 4.2)
    output_contract: dict              # JSON Schema (Req 4.2)
    operation_scope: list[str]         # permitted operations (Req 4.2, 4.4)


class AgenticCapability(BaseModel):
    """Per-Subagent reasoning and tool budgets bounding autonomy (Req 4.3, 4.6)."""

    max_reasoning_steps: int = Field(gt=0)   # Req 4.3, 4.6
    max_tool_invocations: int = Field(gt=0)  # Req 4.3, 4.6


class SubagentSpec(BaseModel):
    """Registry record describing a routable Subagent (Req 4.1, 5.1, 2.5)."""

    subagent_id: str
    role: str                          # Code_Reviewer, Debugger, ... extensible (Req 4.8)
    platform_system: PlatformSystem    # Req 4.1
    mode: OperatingMode                # Req 4.1
    skills: list[Skill] = Field(min_length=1)
    capability: AgenticCapability
    mcp_allow_list: list[str]          # permitted MCP_Tool names (Req 5.1)
    status: str = "available"          # available | draining | removed
    selection_priority: int = 0        # deterministic tie-break (Req 2.5)
