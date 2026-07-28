"""Environment MCP Server — stub for development.

Provides access to environment variables and system configuration.
Access tier: read.

Requirements: KB-10u 17.1, 17.2, 17.3.
"""

from __future__ import annotations

from .base import MCPServerBase, ServerConfig


class EnvironmentMCPServer(MCPServerBase):
    """MCP server providing environment variable access."""

    name = "environment"
    access_tier = "read"
    auth_method = "api_key"

    def __init__(self, config: ServerConfig) -> None:
        self._config = config

    @property
    def supported_tools(self) -> list[str]:
        return [
            "env_get",
            "env_list",
            "env_set",
            "env_unset",
            "system_info",
            "process_list",
        ]

    async def env_get(self, *, key: str, default: str | None = None) -> dict:
        """Get the value of a single environment variable."""
        return {"key": key, "value": default, "found": False}

    async def env_list(self, *, prefix: str | None = None) -> dict:
        """List all environment variables, optionally filtered by prefix."""
        return {"prefix": prefix, "variables": {}, "total": 0}

    async def env_set(self, *, key: str, value: str) -> dict:
        """Set an environment variable (ephemeral, process-scoped)."""
        return {"key": key, "set": True}

    async def env_unset(self, *, key: str) -> dict:
        """Unset (remove) an environment variable."""
        return {"key": key, "unset": True}

    async def system_info(self) -> dict:
        """Get system-level information (OS, CPU, memory, etc.)."""
        return {
            "os": "",
            "os_version": "",
            "cpu_count": 0,
            "python_version": "",
            "hostname": "",
        }

    async def process_list(self) -> dict:
        """List running processes."""
        return {"processes": [], "total": 0}
