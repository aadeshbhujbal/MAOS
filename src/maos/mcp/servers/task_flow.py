"""Task Flow MCP Server — stub for development.

Provides task/subtask lifecycle management, status tracking, and dependency management.
Access tier: read_write.

Requirements: KB-10u 17.1, 17.2, 17.3.
"""

from __future__ import annotations

from .base import MCPServerBase, ServerConfig


class TaskFlowMCPServer(MCPServerBase):
    """MCP server providing task flow operations."""

    name = "task_flow"
    access_tier = "read_write"
    auth_method = "api_key"

    def __init__(self, config: ServerConfig) -> None:
        self._config = config

    @property
    def supported_tools(self) -> list[str]:
        return [
            "task_create",
            "task_status",
            "task_update",
            "task_cancel",
            "task_dependencies",
            "task_history",
            "subtask_create",
            "subtask_status",
        ]

    async def task_create(
        self,
        *,
        tenant_id: str,
        mode: str,
        description: str,
        tags: list[str] | None = None,
    ) -> dict:
        """Create a new top-level task."""
        return {
            "task_id": "",
            "tenant_id": tenant_id,
            "mode": mode,
            "description": description,
            "tags": tags or [],
            "created": True,
        }

    async def task_status(self, *, task_id: str) -> dict:
        """Get the current status of a task."""
        return {
            "task_id": task_id,
            "state": "unknown",
            "progress": 0.0,
            "subtask_count": 0,
            "completed_subtasks": 0,
        }

    async def task_update(
        self, *, task_id: str, description: str | None = None, tags: list[str] | None = None
    ) -> dict:
        """Update a task's metadata."""
        return {"task_id": task_id, "updated": True}

    async def task_cancel(
        self, *, task_id: str, reason: str = "user_requested"
    ) -> dict:
        """Cancel an active task."""
        return {"task_id": task_id, "cancelled": True, "reason": reason}

    async def task_dependencies(self, *, task_id: str) -> dict:
        """Get the dependency graph for a task."""
        return {"task_id": task_id, "dependencies": [], "dependents": []}

    async def task_history(self, *, task_id: str) -> dict:
        """Get the execution history for a task."""
        return {"task_id": task_id, "events": [], "total": 0}

    async def subtask_create(
        self,
        *,
        task_id: str,
        description: str,
        platform_system: str,
        mode: str,
    ) -> dict:
        """Create a new subtask under a task."""
        return {
            "subtask_id": "",
            "task_id": task_id,
            "description": description,
            "platform_system": platform_system,
            "mode": mode,
            "created": True,
        }

    async def subtask_status(self, *, subtask_id: str) -> dict:
        """Get the status of a subtask."""
        return {
            "subtask_id": subtask_id,
            "state": "unknown",
            "task_id": "",
            "assigned_agent": None,
        }
