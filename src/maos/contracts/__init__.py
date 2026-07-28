"""Pydantic v2 domain contracts (work units, agents, messages, MCP, LLM, results, audit)."""

from __future__ import annotations

from maos.contracts.agents import (
    AgenticCapability,
    Skill,
    SubagentSpec,
)
from maos.contracts.work_units import (
    OperatingMode,
    PlatformSystem,
    SubSubtask,
    Subtask,
    Task,
    WorkUnitState,
)

__all__ = [
    "AgenticCapability",
    "OperatingMode",
    "PlatformSystem",
    "Skill",
    "SubSubtask",
    "SubagentSpec",
    "Subtask",
    "Task",
    "WorkUnitState",
]

# --- Task 2.3: message, MCP, LLM, result, and audit contracts ---
from maos.contracts.audit import AuditEntry, AuditEventType
from maos.contracts.llm import LLMRequest, LLMResponse
from maos.contracts.mcp import MCPInvocation, MCPToolDescriptor
from maos.contracts.messaging import AgentMessage, MessageType
from maos.contracts.results import SubSubtaskResult, SubtaskResult, TaskResult

__all__ += [
    "AgentMessage",
    "AuditEntry",
    "AuditEventType",
    "LLMRequest",
    "LLMResponse",
    "MCPInvocation",
    "MCPToolDescriptor",
    "MessageType",
    "SubSubtaskResult",
    "SubtaskResult",
    "TaskResult",
]
