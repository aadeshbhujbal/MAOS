"""Base class and configuration for MCP server stubs.

All MCP server implementations in this package extend ``MCPServerBase`` and
define their ``name``, ``access_tier``, ``auth_method``, and ``supported_tools``
as class-level attributes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ServerConfig:
    """Configuration passed to each MCP server stub.

    Attributes
    ----------
    server_url:
        The base URL of the MCP server.
    auth_token:
        Optional bearer/auth token for authenticated servers.
    timeout_seconds:
        Request timeout in seconds.
    extra:
        Arbitrary extra configuration for server-specific use cases.
    """

    server_url: str = "http://localhost:8080"
    auth_token: str | None = None
    timeout_seconds: float = 30.0
    extra: dict[str, Any] = field(default_factory=dict)


class MCPServerBase:
    """Abstract base class for MCP server stubs.

    Subclasses must define:
    - ``name``: unique server identifier
    - ``access_tier``: ``read``, ``read_write``, or ``admin``
    - ``auth_method``: ``oauth2``, ``api_key``, ``mTLS``, or ``none``
    - ``supported_tools``: list of tool name strings
    - All tool methods matching ``supported_tools`` entries
    """

    name: str = "base"
    access_tier: str = "read"
    auth_method: str = "none"

    def __init__(self, config: ServerConfig) -> None:
        self._config = config

    @property
    def supported_tools(self) -> list[str]:
        """Return the list of tool names this server provides."""
        return []

    async def health_check(self) -> dict:
        """Check server health. Returns status dict."""
        return {"status": "healthy", "server": self.name}
