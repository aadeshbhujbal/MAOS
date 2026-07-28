"""MCP_Tool contracts for governed tool invocation.

Defines the descriptor that the Agent_Registry / MCP_Gateway uses to govern a
tool (``MCPToolDescriptor``) and the redacted invocation envelope an agent emits
to call one (``MCPInvocation``). These are pure Pydantic v2 contracts; the
governance logic (allow-list, mode, arg validation) lives in the MCP_Gateway.

Traceability:
- ``allowed_modes`` enforces RUNTIME/DEVELOPMENT least-privilege (Req 5.8, 5.9).
- ``args_ref`` is a reference/redacted handle — never raw secrets/PHI (Req 5.6).
- An invocation links the acting ``subagent_id`` and ``sub_subtask_id`` so the
  completion can be recorded to the Audit_Log (Req 5.5).
"""

from __future__ import annotations

from pydantic import BaseModel

from maos.contracts.work_units import OperatingMode


class MCPToolDescriptor(BaseModel):
    """Descriptor governing a single MCP_Tool (Req 5.1, 5.8, 5.9)."""

    name: str
    server: str
    input_contract: dict
    output_contract: dict
    allowed_modes: list[OperatingMode]   # RUNTIME/DEVELOPMENT least-privilege (Req 5.8, 5.9)


class MCPInvocation(BaseModel):
    """A redacted MCP_Tool invocation envelope emitted by a Subagent (Req 5.6)."""

    tool_name: str
    subagent_id: str
    sub_subtask_id: str
    args_ref: str                        # reference/redacted, never raw secrets/PHI (Req 5.6)
