"""Redis-backed Shared_Context for per-Task agent coordination.

The ``SharedContextStore`` provides a scoped, low-latency key-value store that
agents read from and write to during execution of a single Task. Each Task gets
its own Redis hash, with access restricted to agents assigned to that Task's
Subtasks or Sub_Subtasks.

Key design points:
- Per-Task Redis hash key: ``ctx:{task_id}``
- Metadata stored under reserved keys (prefixed ``__meta:``).
- Assigned agents tracked in a Redis set: ``ctx:{task_id}:agents``
- Writes are attributed (agent_id + timestamp) and rejected when the context
  is closed or the agent is unassigned.
- TTL is applied when the context is closed (terminal Task state).

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.10.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ContextClosedError(Exception):
    """Raised when a write is attempted on a closed (terminal) Shared_Context."""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(f"Shared_Context for task '{task_id}' is closed to further writes.")


class ContextAccessDeniedError(Exception):
    """Raised when an unassigned agent attempts to read or write a Shared_Context."""

    def __init__(self, task_id: str, agent_id: str) -> None:
        self.task_id = task_id
        self.agent_id = agent_id
        super().__init__(
            f"Agent '{agent_id}' is not assigned to task '{task_id}' "
            f"and cannot access its Shared_Context."
        )


# ---------------------------------------------------------------------------
# SharedContextStore
# ---------------------------------------------------------------------------


class SharedContextStore:
    """Redis-backed per-Task Shared_Context.

    Parameters
    ----------
    redis_client:
        An async Redis client instance (``redis.asyncio.Redis``).
    default_ttl_seconds:
        TTL (in seconds) applied to the Redis key when the context is closed.
        Implements the configured retention period (Req 7.10).
    """

    # Reserved metadata key prefix within the Redis hash.
    _META_PREFIX = "__meta:"

    def __init__(self, redis_client: aioredis.Redis, default_ttl_seconds: int = 86400) -> None:  # type: ignore[type-arg]
        self._redis = redis_client
        self._default_ttl = default_ttl_seconds

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _context_key(task_id: str) -> str:
        """Redis hash key for a Task's Shared_Context."""
        return f"ctx:{task_id}"

    @staticmethod
    def _agents_key(task_id: str) -> str:
        """Redis set key tracking assigned agents for a Task."""
        return f"ctx:{task_id}:agents"

    async def _is_open(self, task_id: str) -> bool:
        """Return True if the context exists and is open (not closed)."""
        raw = await self._redis.hget(self._context_key(task_id), f"{self._META_PREFIX}open")
        if raw is None:
            return False
        # Redis returns bytes; decode for comparison.
        value = raw.decode() if isinstance(raw, bytes) else str(raw)
        return value == "1"

    async def _is_assigned(self, task_id: str, agent_id: str) -> bool:
        """Return True if the agent is in the assigned-agents set for this Task."""
        return bool(await self._redis.sismember(self._agents_key(task_id), agent_id))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create(self, task_id: str, tenant_id: str) -> None:
        """Create a per-Task Shared_Context with initial metadata.

        Called when the Root_Orchestrator accepts a Task (Req 7.1).

        Parameters
        ----------
        task_id:
            Unique Task identifier.
        tenant_id:
            Tenant (clinic) identifier scoping this context.
        """
        key = self._context_key(task_id)
        now = datetime.now(UTC).isoformat()

        # Store metadata fields in the hash under reserved keys.
        await self._redis.hset(
            key,
            mapping={
                f"{self._META_PREFIX}tenant_id": tenant_id,
                f"{self._META_PREFIX}created_at": now,
                f"{self._META_PREFIX}open": "1",
            },
        )

    async def add_assigned_agent(self, task_id: str, agent_id: str) -> None:
        """Register an agent as assigned to this Task's Shared_Context.

        Called when routing assigns a Subtask/Sub_Subtask to an agent.

        Parameters
        ----------
        task_id:
            Task identifier whose context is being updated.
        agent_id:
            Agent identifier to add to the assigned set.
        """
        await self._redis.sadd(self._agents_key(task_id), agent_id)

    async def write(self, task_id: str, agent_id: str, key: str, value: dict[str, Any]) -> None:
        """Write a key-value entry to the Task's Shared_Context.

        The entry is stored as a JSON blob that includes the writing agent_id
        and a timestamp for attribution (Req 7.2).

        Raises
        ------
        ContextClosedError
            If the context has been closed (Req 7.4).
        ContextAccessDeniedError
            If the agent is not assigned to this Task (Req 7.3, 7.5).
        """
        # Check context is open.
        if not await self._is_open(task_id):
            raise ContextClosedError(task_id)

        # Check agent assignment.
        if not await self._is_assigned(task_id, agent_id):
            raise ContextAccessDeniedError(task_id, agent_id)

        # Build attributed entry.
        entry: dict[str, Any] = {
            "value": value,
            "agent_id": agent_id,
            "written_at": datetime.now(UTC).isoformat(),
        }

        ctx_key = self._context_key(task_id)
        await self._redis.hset(ctx_key, key, json.dumps(entry))

    async def read(self, task_id: str, agent_id: str, key: str) -> dict[str, Any] | None:
        """Read a value from the Task's Shared_Context.

        Returns the stored value dict (without attribution wrapper), or None
        if the key does not exist. Same agent-assignment check applies (Req 7.3).

        Raises
        ------
        ContextAccessDeniedError
            If the agent is not assigned to this Task (Req 7.3, 7.5).
        """
        # Check agent assignment.
        if not await self._is_assigned(task_id, agent_id):
            raise ContextAccessDeniedError(task_id, agent_id)

        ctx_key = self._context_key(task_id)
        raw = await self._redis.hget(ctx_key, key)
        if raw is None:
            return None

        raw_str = raw.decode() if isinstance(raw, bytes) else str(raw)
        entry: dict[str, Any] = json.loads(raw_str)
        return entry.get("value")

    async def close(self, task_id: str) -> None:
        """Close the Shared_Context to further writes and apply TTL retention.

        Called when a Task reaches a terminal state (completed/failed) (Req 7.4).
        The configured TTL is applied to both the context hash and the agents set
        so they are auto-expired after the retention period (Req 7.10).
        """
        ctx_key = self._context_key(task_id)
        agents_key = self._agents_key(task_id)

        # Mark context as closed.
        await self._redis.hset(ctx_key, f"{self._META_PREFIX}open", "0")

        # Apply TTL for retention (Req 7.10).
        await self._redis.expire(ctx_key, self._default_ttl)
        await self._redis.expire(agents_key, self._default_ttl)
