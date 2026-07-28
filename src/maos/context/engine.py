"""Context Engine — real-time project state awareness for agents.

The ``ContextEngine`` maintains a per-tenant snapshot of current project state
(open files, active branches, deployments, incidents, etc.) in **Dragonfly**
(a Redis-wire-compatible in-memory store), and provides role-filtered context
injection into agent prompts.

Key design points:
- Backend: Dragonfly (accessed via ``redis.asyncio`` client — wire-compatible).
- Per-tenant key pattern: ``maos:context:{tenant_id}``
- State stored as JSON with a 1-hour TTL; cache miss yields fresh empty state.
- Role-based filtering ensures agents only receive domain-relevant context.
- State updates are event-driven: each ``ContextEvent`` mutates the snapshot.
- Target: state update within 5 seconds of triggering event.
- Connection URL sourced from ``MAOS_REDIS_URL`` (which points to Dragonfly).

Requirements: 15.1, 15.2, 15.3, 15.5, 15.7, 15.8.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis

from maos.context.models import AgentContext, ContextEvent, ContextState

logger = logging.getLogger(__name__)

# Dragonfly key prefix and TTL (accessed via redis.asyncio — wire-compatible)
_CONTEXT_PREFIX = "maos:context:"
_CONTEXT_TTL_SECONDS = 3600  # 1 hour

# Domain relevance mapping: which context fields are relevant to which agent roles
_ROLE_RELEVANCE: dict[str, list[str]] = {
    "backend": ["relevant_files", "relevant_branches", "relevant_deployments", "recent_changes"],
    "frontend": ["relevant_files", "relevant_branches", "recent_changes"],
    "mobile": ["relevant_files", "relevant_branches", "recent_changes"],
    "database": ["relevant_files", "relevant_branches", "relevant_deployments"],
    "devops": ["relevant_deployments", "relevant_branches", "relevant_incidents"],
    "security": ["relevant_files", "relevant_incidents", "recent_changes"],
    "monitoring": ["relevant_deployments", "relevant_incidents"],
    "incident_response": ["relevant_incidents", "relevant_deployments", "recent_changes"],
    "qa": ["relevant_files", "relevant_branches", "recent_changes"],
    "documentation": ["relevant_files", "recent_changes"],
    "architecture": ["relevant_files", "relevant_branches", "relevant_deployments"],
    "infrastructure": ["relevant_deployments", "relevant_incidents"],
    "ml_ai": ["relevant_files", "relevant_branches", "recent_changes"],
    "ui_ux": ["relevant_files", "relevant_branches", "recent_changes"],
    "api": ["relevant_files", "relevant_branches", "recent_changes"],
    "planning": [
        "relevant_files",
        "relevant_branches",
        "relevant_deployments",
        "relevant_incidents",
        "recent_changes",
    ],
}


class ContextEngine:
    """Dragonfly-backed real-time project state tracker (Req 15).

    Uses the ``redis.asyncio`` client to connect to Dragonfly (Redis-wire-compatible
    in-memory store). Connection URL is sourced from ``MAOS_REDIS_URL`` via
    ``maos.config.settings.RedisSettings``.

    Parameters
    ----------
    redis_url:
        Dragonfly/Redis connection URL (e.g. ``redis://localhost:6379/0``).
        This should be the value of ``MAOS_REDIS_URL`` from settings.
    """

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._redis: aioredis.Redis | None = None  # type: ignore[type-arg]

    async def _get_redis(self) -> aioredis.Redis:  # type: ignore[type-arg]
        """Lazy-initialize and return the async Dragonfly client (redis.asyncio)."""
        if self._redis is None:
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_current(self, tenant_id: str) -> ContextState:
        """Get full context state for a tenant (Req 15.1, 15.7).

        On cache miss (key expired or absent in Dragonfly), returns a fresh
        empty state — this is the fallback-to-fresh-query behavior.
        """
        r = await self._get_redis()
        key = f"{_CONTEXT_PREFIX}{tenant_id}"
        raw: str | None = await r.get(key)
        if raw is None:
            return ContextState(tenant_id=tenant_id, updated_at=datetime.now(UTC))
        return ContextState(**json.loads(raw))

    async def update(self, tenant_id: str, event: ContextEvent) -> None:
        """Process a context event and update Dragonfly-cached state (Req 15.3, 15.5).

        Applies the event to the current state and persists the updated snapshot
        to Dragonfly with a 1-hour TTL. Designed to complete within 5 seconds
        of the triggering event.
        """
        r = await self._get_redis()
        state = await self.get_current(tenant_id)

        self._apply_event(state, event)

        state.updated_at = datetime.now(UTC)

        # Persist to Redis with TTL
        key = f"{_CONTEXT_PREFIX}{tenant_id}"
        await r.set(key, state.model_dump_json(), ex=_CONTEXT_TTL_SECONDS)

        logger.info(
            "context_state_updated",
            extra={
                "tenant_id": tenant_id,
                "event_type": event.event_type,
                "key": key,
            },
        )

    async def inject_for_agent(self, agent_role: str, state: ContextState) -> AgentContext:
        """Filter context by agent role relevance (Req 15.2, 15.8).

        Returns an ``AgentContext`` containing only the context items relevant
        to the specified agent role.
        """
        role_key = self._normalize_role(agent_role)
        relevant_fields = _ROLE_RELEVANCE.get(role_key, ["relevant_files", "recent_changes"])

        return AgentContext(
            agent_role=agent_role,
            relevant_files=state.open_files if "relevant_files" in relevant_fields else [],
            relevant_branches=(
                state.active_branches if "relevant_branches" in relevant_fields else []
            ),
            relevant_deployments=(
                state.running_deployments if "relevant_deployments" in relevant_fields else []
            ),
            relevant_incidents=(
                state.active_incidents if "relevant_incidents" in relevant_fields else []
            ),
            relevant_issues=(
                state.assigned_issues if "relevant_issues" in relevant_fields else []
            ),
            recent_changes=state.recent_commits if "recent_changes" in relevant_fields else [],
        )

    async def close(self) -> None:
        """Close Dragonfly connection and release resources."""
        if self._redis:
            await self._redis.aclose()
            self._redis = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_role(agent_role: str) -> str:
        """Normalize agent role string to a lookup key.

        Strips common suffixes like ``_agent`` or ``agent`` and lowercases.
        """
        key = agent_role.lower().replace("_agent", "").replace("agent", "").strip("_").strip()
        return key

    @staticmethod
    def _apply_event(state: ContextState, event: ContextEvent) -> None:
        """Mutate *state* in place based on the event type and payload."""
        payload: dict[str, Any] = event.payload

        if event.event_type == "file_edited":
            file_path = payload.get("file_path", "")
            if file_path and file_path not in state.open_files:
                state.open_files.append(file_path)

        elif event.event_type == "commit_pushed":
            commit = payload.get("commit_sha", "")
            if commit:
                state.recent_commits.append(commit)
                # Keep only the last 50 commits to bound memory usage
                state.recent_commits = state.recent_commits[-50:]

        elif event.event_type == "deployment_started":
            dep = payload.get("deployment_id", "")
            if dep and dep not in state.running_deployments:
                state.running_deployments.append(dep)

        elif event.event_type == "deployment_completed":
            dep = payload.get("deployment_id", "")
            if dep in state.running_deployments:
                state.running_deployments.remove(dep)

        elif event.event_type == "incident_created":
            incident = payload.get("incident_id", "")
            if incident and incident not in state.active_incidents:
                state.active_incidents.append(incident)

        elif event.event_type == "incident_resolved":
            incident = payload.get("incident_id", "")
            if incident in state.active_incidents:
                state.active_incidents.remove(incident)

        elif event.event_type == "branch_created":
            branch = payload.get("branch_name", "")
            if branch and branch not in state.active_branches:
                state.active_branches.append(branch)

        elif event.event_type == "branch_merged":
            branch = payload.get("branch_name", "")
            if branch in state.active_branches:
                state.active_branches.remove(branch)

        elif event.event_type == "issue_assigned":
            issue = payload.get("issue_id", "")
            if issue and issue not in state.assigned_issues:
                state.assigned_issues.append(issue)

        elif event.event_type == "sprint_updated":
            state.current_sprint = payload.get("sprint_name", "")

