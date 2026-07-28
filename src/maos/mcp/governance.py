"""MCP governance: allow-list, mode, and argument-validation checks.

This module provides the pure, pre-invocation governance gate for MCP tool
calls. Before any tool actually executes, ``check_mcp_invocation`` verifies:

1. The tool is in the Subagent's ``mcp_allow_list`` (Req 5.2, 5.3).
2. The Subagent's operating mode is permitted by the tool (Req 5.8, 5.9).
3. The invocation arguments satisfy the tool's input contract (Req 5.4).

All checks are pure — no I/O, no side effects.
"""

from __future__ import annotations

from typing import Literal

from maos.contracts.agents import SubagentSpec
from maos.contracts.mcp import MCPToolDescriptor

DenialReason = Literal["not_in_allow_list", "mode_not_permitted", "invalid_arguments"]


class MCPDenialError(Exception):
    """Raised when an MCP tool invocation is denied by governance checks."""

    reason: DenialReason
    tool_name: str
    subagent_id: str

    def __init__(self, *, reason: DenialReason, tool_name: str, subagent_id: str) -> None:
        self.reason = reason
        self.tool_name = tool_name
        self.subagent_id = subagent_id
        super().__init__(
            f"MCP invocation denied: reason={reason}, "
            f"tool={tool_name}, subagent={subagent_id}"
        )


def check_mcp_invocation(
    agent: SubagentSpec,
    tool: MCPToolDescriptor,
    args: dict,
) -> None:
    """Validate an MCP tool invocation against governance rules.

    Raises :class:`MCPDenialError` if any check fails. Returns ``None`` on
    success.

    Checks (in order):
        1. Tool name must be in ``agent.mcp_allow_list`` (Req 5.2, 5.3).
        2. ``agent.mode`` must be in ``tool.allowed_modes`` (Req 5.8, 5.9).
        3. ``args`` must satisfy ``tool.input_contract`` — specifically, if
           the contract declares a ``"required"`` key, every listed field must
           be present in ``args`` (Req 5.4).

    Parameters
    ----------
    agent:
        The SubagentSpec attempting the invocation.
    tool:
        The MCPToolDescriptor describing the target tool.
    args:
        The arguments the Subagent intends to pass to the tool.

    Returns
    -------
    None
        If all governance checks pass.

    Raises
    ------
    MCPDenialError
        If any governance check fails.
    """
    # 1. Allow-list check (Req 5.2, 5.3)
    if tool.name not in agent.mcp_allow_list:
        raise MCPDenialError(
            reason="not_in_allow_list",
            tool_name=tool.name,
            subagent_id=agent.subagent_id,
        )

    # 2. Mode check (Req 5.8, 5.9)
    if agent.mode not in tool.allowed_modes:
        raise MCPDenialError(
            reason="mode_not_permitted",
            tool_name=tool.name,
            subagent_id=agent.subagent_id,
        )

    # 3. Argument validation against input contract (Req 5.4)
    required_fields = tool.input_contract.get("required")
    if required_fields is not None:
        for field in required_fields:
            if field not in args:
                raise MCPDenialError(
                    reason="invalid_arguments",
                    tool_name=tool.name,
                    subagent_id=agent.subagent_id,
                )
