"""MCP Server Registry: dynamic registration, health monitoring, and tool resolution.

This module provides the ``MCPRegistry`` class that manages the lifecycle of
MCP servers in the platform:

- Dynamic registration with unique-name enforcement (Req 14.1, 14.8)
- Tool resolution with agent allow-list verification (Req 14.4)
- Server listing with health status (Req 14.6)
- Credential rotation without service restart (Req 14.7)
- Health status updates for monitoring integration (Req 14.2)

For MVP, registry state is stored in-memory using a dict protected by
asyncio.Lock for thread-safety. This can be migrated to Postgres later
using the existing ``DatabasePool`` from ``maos.memory.database``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from maos.mcp.models import MCPServerRecord, MCPToolResolution

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DuplicateServerError(Exception):
    """Raised when attempting to register a server with an existing name.

    HTTP-equivalent: 409 Conflict.
    """

    def __init__(self, server_name: str) -> None:
        self.server_name = server_name
        super().__init__(f"MCP server with name '{server_name}' is already registered")


class ToolNotFoundError(Exception):
    """Raised when a requested tool cannot be found in any registered server."""

    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name
        super().__init__(f"Tool '{tool_name}' not found in any registered MCP server")


class ToolNotAllowedError(Exception):
    """Raised when a tool exists but is not in the requesting agent's allow-list."""

    def __init__(self, tool_name: str, server_name: str) -> None:
        self.tool_name = tool_name
        self.server_name = server_name
        super().__init__(
            f"Tool '{tool_name}' on server '{server_name}' is not in agent's allow-list"
        )


# ---------------------------------------------------------------------------
# MCPRegistry (in-memory MVP)
# ---------------------------------------------------------------------------


class MCPRegistry:
    """Central registry for MCP server management (Req 14.1-14.8).

    Stores server records in an in-memory dict protected by asyncio.Lock
    for concurrency safety. This is the MVP implementation; migration to
    Postgres is straightforward by replacing the dict with SQL queries.

    Methods
    -------
    register(server)
        Register a new MCP server, rejecting duplicates with 409.
    deregister(name)
        Remove a server from the registry.
    resolve_tool(tool_name, agent_allow_list)
        Resolve a tool to its server endpoint, verifying the agent's allow-list.
    list_servers()
        Return all servers with current health status.
    get_server(name)
        Retrieve a single server by name.
    update_health(name, status, consecutive_failures)
        Update a server's health status.
    rotate_credentials(name, new_credentials)
        Rotate credentials without service restart.
    """

    def __init__(self) -> None:
        self._servers: dict[str, MCPServerRecord] = {}
        self._credentials: dict[str, dict[str, str]] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    async def register(self, server: MCPServerRecord) -> None:
        """Register a new MCP server in the registry.

        Parameters
        ----------
        server:
            The server record to register.

        Raises
        ------
        DuplicateServerError
            If a server with the same name already exists (HTTP 409).
        """
        async with self._lock:
            if server.name in self._servers:
                raise DuplicateServerError(server.name)
            self._servers[server.name] = server
        logger.info("Registered MCP server: %s at %s", server.name, server.endpoint_url)

    # ------------------------------------------------------------------
    # Deregistration
    # ------------------------------------------------------------------

    async def deregister(self, name: str) -> bool:
        """Remove an MCP server from the registry.

        Parameters
        ----------
        name:
            The unique name of the server to remove.

        Returns
        -------
        bool
            True if the server was found and removed, False otherwise.
        """
        async with self._lock:
            if name not in self._servers:
                return False
            del self._servers[name]
            self._credentials.pop(name, None)
        logger.info("Deregistered MCP server: %s", name)
        return True

    # ------------------------------------------------------------------
    # Tool resolution
    # ------------------------------------------------------------------

    async def resolve_tool(self, tool_name: str, agent_allow_list: list[str]) -> MCPToolResolution:
        """Resolve a tool name to a server endpoint, verifying the agent's allow-list.

        The method finds the first healthy server that supports the requested
        tool, then verifies the tool is in the agent's allow-list before
        returning the resolution.

        Parameters
        ----------
        tool_name:
            The name of the tool to resolve.
        agent_allow_list:
            List of tool names the requesting agent is permitted to use.

        Returns
        -------
        MCPToolResolution
            The resolved tool endpoint information.

        Raises
        ------
        ToolNotFoundError
            If no registered server provides the tool.
        ToolNotAllowedError
            If the tool exists but is not in the agent's allow-list.
        """
        async with self._lock:
            # Find servers that provide this tool, preferring healthy ones
            candidates: list[MCPServerRecord] = []
            for server in self._servers.values():
                if tool_name in server.supported_tools:
                    candidates.append(server)

        if not candidates:
            raise ToolNotFoundError(tool_name)

        # Verify allow-list before resolving
        if tool_name not in agent_allow_list:
            raise ToolNotAllowedError(tool_name, candidates[0].name)

        # Sort by health: healthy > degraded > unavailable
        health_priority = {"healthy": 0, "degraded": 1, "unavailable": 2}
        candidates.sort(key=lambda s: health_priority.get(s.health_status, 2))

        # Return the first non-unavailable server
        for server in candidates:
            if server.health_status != "unavailable":
                return MCPToolResolution(
                    tool_name=tool_name,
                    server_name=server.name,
                    endpoint_url=server.endpoint_url,
                    access_tier=server.access_tier,
                    requires_approval=server.access_tier in ("read_write", "admin"),
                )

        # All servers are unavailable — raise not found
        raise ToolNotFoundError(tool_name)

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    async def list_servers(self) -> list[MCPServerRecord]:
        """Return all registered MCP servers with current health status.

        Returns
        -------
        list[MCPServerRecord]
            All servers in the registry, sorted by name.
        """
        async with self._lock:
            return sorted(self._servers.values(), key=lambda s: s.name)

    # ------------------------------------------------------------------
    # Single server retrieval
    # ------------------------------------------------------------------

    async def get_server(self, name: str) -> MCPServerRecord | None:
        """Retrieve a single server record by name.

        Parameters
        ----------
        name:
            The unique server name.

        Returns
        -------
        MCPServerRecord | None
            The server record, or None if not found.
        """
        async with self._lock:
            return self._servers.get(name)

    # ------------------------------------------------------------------
    # Health updates
    # ------------------------------------------------------------------

    async def update_health(self, name: str, status: str, consecutive_failures: int) -> None:
        """Update the health status of a registered MCP server.

        Parameters
        ----------
        name:
            The server to update.
        status:
            The new health status ('healthy', 'degraded', 'unavailable').
        consecutive_failures:
            The current consecutive failure count.
        """
        async with self._lock:
            server = self._servers.get(name)
            if server is None:
                return
            # Create updated record (Pydantic models are immutable by default)
            updated = server.model_copy(
                update={
                    "health_status": status,
                    "consecutive_failures": consecutive_failures,
                    "last_health_check": datetime.now(tz=UTC),
                }
            )
            self._servers[name] = updated

        if status != "healthy":
            logger.warning(
                "MCP server %s health: %s (failures=%d)",
                name,
                status,
                consecutive_failures,
            )

    # ------------------------------------------------------------------
    # Credential rotation
    # ------------------------------------------------------------------

    async def rotate_credentials(self, name: str, new_credentials: dict[str, str]) -> None:
        """Rotate credentials for an MCP server without service restart.

        Updates the stored credentials in-place. The new credentials take
        effect immediately for subsequent tool invocations.

        Parameters
        ----------
        name:
            The name of the server whose credentials to rotate.
        new_credentials:
            The new credential payload (e.g., API key, OAuth tokens).

        Raises
        ------
        ValueError
            If the server is not found in the registry.
        """
        async with self._lock:
            if name not in self._servers:
                raise ValueError(f"Server '{name}' not found in registry")
            self._credentials[name] = new_credentials

        logger.info("Rotated credentials for MCP server: %s (no restart required)", name)

    # ------------------------------------------------------------------
    # Credential retrieval (internal use)
    # ------------------------------------------------------------------

    async def get_credentials(self, name: str) -> dict[str, str] | None:
        """Retrieve current credentials for a server.

        Parameters
        ----------
        name:
            The server name.

        Returns
        -------
        dict[str, str] | None
            The credential dict, or None if no credentials are stored.
        """
        async with self._lock:
            return self._credentials.get(name)
