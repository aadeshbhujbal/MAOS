"""File System MCP Server — stub for development.

Provides read/write/list operations on the repository filesystem.
Access tier: read_write.

Requirements: KB-10u 17.1, 17.2, 17.3.
"""

from __future__ import annotations

from .base import MCPServerBase, ServerConfig


class FileSystemMCPServer(MCPServerBase):
    """MCP server providing file system operations."""

    name = "file_system"
    access_tier = "read_write"
    auth_method = "api_key"

    def __init__(self, config: ServerConfig) -> None:
        self._config = config

    # ------------------------------------------------------------------
    # Server metadata
    # ------------------------------------------------------------------

    @property
    def supported_tools(self) -> list[str]:
        return [
            "file_read",
            "file_write",
            "file_list",
            "file_delete",
            "file_search",
            "dir_create",
            "dir_list",
        ]

    # ------------------------------------------------------------------
    # Tool implementations (stubs)
    # ------------------------------------------------------------------

    async def file_read(self, *, path: str, encoding: str = "utf-8") -> dict:
        """Read a file from the repository."""
        return {
            "path": path,
            "content": "",
            "encoding": encoding,
            "size_bytes": 0,
        }

    async def file_write(self, *, path: str, content: str, encoding: str = "utf-8") -> dict:
        """Write content to a file in the repository."""
        return {
            "path": path,
            "bytes_written": len(content.encode(encoding)),
            "success": True,
        }

    async def file_list(self, *, directory: str, pattern: str = "*") -> dict:
        """List files in a directory matching a glob pattern."""
        return {"directory": directory, "pattern": pattern, "files": []}

    async def file_delete(self, *, path: str) -> dict:
        """Delete a file from the repository."""
        return {"path": path, "deleted": True}

    async def file_search(self, *, query: str, root: str = ".") -> dict:
        """Search for files containing a text query."""
        return {"query": query, "root": root, "matches": []}

    async def dir_create(self, *, path: str) -> dict:
        """Create a directory."""
        return {"path": path, "created": True}

    async def dir_list(self, *, path: str) -> dict:
        """List the contents of a directory."""
        return {"path": path, "entries": [], "subdirs": []}
