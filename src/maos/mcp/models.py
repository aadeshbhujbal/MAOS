"""MCP Server Registry domain contracts for MAOS.

This module defines the models used by the MCP Registry for dynamic server
registration, health monitoring, and tool resolution:

- ``MCPServerRecord`` — registry entry for a single MCP server (Req 14.1, 14.2).
- ``MCPToolResolution`` — resolved tool endpoint with access control info (Req 14.4).

These are pure Pydantic v2 contracts: they carry no behaviour beyond validation
so the MCP Registry and Hypothesis correctness properties can construct and
reason about them deterministically.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class MCPServerRecord(BaseModel):
    """Registry entry for a single MCP server (Req 14.1, 14.2)."""

    name: str
    endpoint_url: str
    supported_tools: list[str] = []
    health_status: Literal["healthy", "degraded", "unavailable"] = "healthy"
    auth_method: Literal["oauth2", "api_key", "mTLS", "none"] = "none"
    access_tier: Literal["read", "read_write", "admin"] = "read"
    last_health_check: datetime | None = None
    consecutive_failures: int = Field(ge=0, default=0)
    fallback_server: str | None = None
    registered_at: datetime


class MCPToolResolution(BaseModel):
    """Resolved tool endpoint with access control info (Req 14.4)."""

    tool_name: str
    server_name: str
    endpoint_url: str
    access_tier: Literal["read", "read_write", "admin"]
    requires_approval: bool = False
