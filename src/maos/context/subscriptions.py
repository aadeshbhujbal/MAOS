"""Event Subscription Manager — polls MCP servers for events and updates context.

The ``EventSubscriptionManager`` periodically polls registered MCP servers
(GitHub_MCP, Jira_MCP, Kubernetes_MCP, Slack_MCP) for events and translates
them into ``ContextEvent`` instances dispatched to the ``ContextEngine``.

Detected events:
- commit_pushed — new commits pushed to a repository
- deployment_started — a deployment was initiated
- incident_created — a new incident was opened
- file_edited — a tracked file was modified
- branch_created — a new branch was created
- issue_assigned — an issue was assigned to the team

On active incident: elevates incident context to all related agents via the
Context Engine's update mechanism.

Requirements: 15.3, 15.4, 15.6, 15.7.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import Any

from maos.context.engine import ContextEngine
from maos.context.models import ContextEvent

logger = logging.getLogger(__name__)

# Supported event types that the subscription manager detects
SUPPORTED_EVENT_TYPES: list[str] = [
    "commit_pushed",
    "deployment_started",
    "incident_created",
    "file_edited",
    "branch_created",
    "issue_assigned",
]

# Default poll interval in seconds
DEFAULT_POLL_INTERVAL: float = 30.0


class EventSubscriptionManager:
    """Polls MCP servers for events and forwards them to the ContextEngine.

    The manager maintains a polling loop that queries registered MCP servers
    for new events at a configurable interval. Each detected event is
    translated into a ``ContextEvent`` and dispatched to the ``ContextEngine``
    for state mutation.

    On active incident detection, the manager elevates incident context by
    dispatching the incident event to all affected tenants immediately.

    Parameters
    ----------
    context_engine:
        The ``ContextEngine`` instance to dispatch events to.
    poll_interval:
        Interval in seconds between polling cycles. Defaults to 30s.
    mcp_servers:
        Optional list of MCP server names to poll. Defaults to the standard
        set: GitHub_MCP, Jira_MCP, Kubernetes_MCP, Slack_MCP.
    """

    def __init__(
        self,
        context_engine: ContextEngine,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        mcp_servers: list[str] | None = None,
    ) -> None:
        self._context_engine = context_engine
        self._poll_interval = poll_interval
        self._mcp_servers = mcp_servers or [
            "GitHub_MCP",
            "Jira_MCP",
            "Kubernetes_MCP",
            "Slack_MCP",
        ]
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._event_handlers: dict[str, Any] = self._build_event_handlers()

    def _build_event_handlers(self) -> dict[str, Any]:
        """Build mapping of event types to their handler callables."""
        return {
            "commit_pushed": self._handle_commit_pushed,
            "deployment_started": self._handle_deployment_started,
            "incident_created": self._handle_incident_created,
            "file_edited": self._handle_file_edited,
            "branch_created": self._handle_branch_created,
            "issue_assigned": self._handle_issue_assigned,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the polling loop as a background asyncio task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(
            "EventSubscriptionManager started",
            extra={
                "poll_interval": self._poll_interval,
                "mcp_servers": self._mcp_servers,
            },
        )

    async def stop(self) -> None:
        """Stop the polling loop and cancel the background task."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("EventSubscriptionManager stopped")

    @property
    def is_running(self) -> bool:
        """Return whether the polling loop is active."""
        return self._running

    @property
    def poll_interval(self) -> float:
        """Return the configured poll interval in seconds."""
        return self._poll_interval

    # ------------------------------------------------------------------
    # Polling loop
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Main polling loop — queries MCP servers at the configured interval."""
        while self._running:
            try:
                await self._poll_all_servers()
            except Exception:
                logger.exception("Error during MCP server polling cycle")
            await asyncio.sleep(self._poll_interval)

    async def _poll_all_servers(self) -> None:
        """Poll all registered MCP servers for new events."""
        for server_name in self._mcp_servers:
            try:
                events = await self._poll_server(server_name)
                for event in events:
                    await self._dispatch_event(event)
            except Exception:
                logger.warning(
                    "Failed to poll MCP server: %s",
                    server_name,
                    exc_info=True,
                )

    async def _poll_server(self, server_name: str) -> list[dict[str, Any]]:
        """Poll a single MCP server for new events.

        This is the integration point where a real implementation would call
        the MCP server's event endpoint. For now, returns an empty list —
        actual MCP server integration will provide events via the server's
        event stream or webhook callbacks.

        Parameters
        ----------
        server_name:
            The name of the MCP server to poll.

        Returns
        -------
        list[dict[str, Any]]
            A list of raw event dictionaries from the server.
        """
        # Integration point: in production, this calls the MCP server's
        # event API endpoint. The server returns events since the last poll.
        # Example: GET /events?since=<last_poll_timestamp>
        logger.debug("Polling MCP server: %s", server_name)
        return []

    # ------------------------------------------------------------------
    # Event dispatch
    # ------------------------------------------------------------------

    async def _dispatch_event(self, raw_event: dict[str, Any]) -> None:
        """Dispatch a raw event to the appropriate handler.

        Translates a raw event dictionary into a ``ContextEvent`` and calls
        ``ContextEngine.update()`` with the appropriate event.

        Parameters
        ----------
        raw_event:
            Raw event data from an MCP server containing at minimum:
            - event_type: one of SUPPORTED_EVENT_TYPES
            - tenant_id: the tenant scope
            - payload: event-specific data
        """
        event_type = raw_event.get("event_type", "")
        tenant_id = raw_event.get("tenant_id", "")

        if not event_type or not tenant_id:
            logger.warning("Received event with missing event_type or tenant_id: %s", raw_event)
            return

        if event_type not in SUPPORTED_EVENT_TYPES:
            logger.debug("Ignoring unsupported event type: %s", event_type)
            return

        handler = self._event_handlers.get(event_type)
        if handler:
            await handler(tenant_id, raw_event)

    async def process_event(self, raw_event: dict[str, Any]) -> None:
        """Public method to process a single event directly.

        Useful for webhook-based integrations where events are pushed rather
        than polled.

        Parameters
        ----------
        raw_event:
            Raw event data from an MCP server.
        """
        await self._dispatch_event(raw_event)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _handle_commit_pushed(self, tenant_id: str, raw_event: dict[str, Any]) -> None:
        """Handle a commit_pushed event from GitHub_MCP."""
        payload = raw_event.get("payload", {})
        event = ContextEvent(
            event_type="commit_pushed",
            tenant_id=tenant_id,
            timestamp=datetime.now(UTC),
            payload={"commit_sha": payload.get("commit_sha", "")},
        )
        await self._context_engine.update(tenant_id, event)
        logger.info(
            "Processed commit_pushed event",
            extra={"tenant_id": tenant_id, "commit_sha": payload.get("commit_sha")},
        )

    async def _handle_deployment_started(self, tenant_id: str, raw_event: dict[str, Any]) -> None:
        """Handle a deployment_started event from Kubernetes_MCP."""
        payload = raw_event.get("payload", {})
        event = ContextEvent(
            event_type="deployment_started",
            tenant_id=tenant_id,
            timestamp=datetime.now(UTC),
            payload={"deployment_id": payload.get("deployment_id", "")},
        )
        await self._context_engine.update(tenant_id, event)
        logger.info(
            "Processed deployment_started event",
            extra={"tenant_id": tenant_id, "deployment_id": payload.get("deployment_id")},
        )

    async def _handle_incident_created(self, tenant_id: str, raw_event: dict[str, Any]) -> None:
        """Handle an incident_created event — elevates incident context (Req 15.6).

        On active incident, the incident context is elevated to all related
        agents by dispatching the event through the ContextEngine. The engine's
        role-filtering ensures incident_response and monitoring agents receive
        incident context immediately.
        """
        payload = raw_event.get("payload", {})
        incident_id = payload.get("incident_id", "")
        severity = payload.get("severity", "medium")

        event = ContextEvent(
            event_type="incident_created",
            tenant_id=tenant_id,
            timestamp=datetime.now(UTC),
            payload={"incident_id": incident_id},
        )
        await self._context_engine.update(tenant_id, event)

        # Elevate incident context: on active incident, ensure all relevant
        # agents receive incident context via the engine's state update.
        # Critical severity incidents are flagged for immediate attention.
        if severity == "critical":
            logger.warning(
                "CRITICAL incident detected — context elevated for all agents",
                extra={
                    "tenant_id": tenant_id,
                    "incident_id": incident_id,
                    "severity": severity,
                },
            )
        else:
            logger.info(
                "Processed incident_created event — context elevated",
                extra={
                    "tenant_id": tenant_id,
                    "incident_id": incident_id,
                    "severity": severity,
                },
            )

    async def _handle_file_edited(self, tenant_id: str, raw_event: dict[str, Any]) -> None:
        """Handle a file_edited event from GitHub_MCP."""
        payload = raw_event.get("payload", {})
        event = ContextEvent(
            event_type="file_edited",
            tenant_id=tenant_id,
            timestamp=datetime.now(UTC),
            payload={"file_path": payload.get("file_path", "")},
        )
        await self._context_engine.update(tenant_id, event)
        logger.info(
            "Processed file_edited event",
            extra={"tenant_id": tenant_id, "file_path": payload.get("file_path")},
        )

    async def _handle_branch_created(self, tenant_id: str, raw_event: dict[str, Any]) -> None:
        """Handle a branch_created event from GitHub_MCP."""
        payload = raw_event.get("payload", {})
        event = ContextEvent(
            event_type="branch_created",
            tenant_id=tenant_id,
            timestamp=datetime.now(UTC),
            payload={"branch_name": payload.get("branch_name", "")},
        )
        await self._context_engine.update(tenant_id, event)
        logger.info(
            "Processed branch_created event",
            extra={"tenant_id": tenant_id, "branch_name": payload.get("branch_name")},
        )

    async def _handle_issue_assigned(self, tenant_id: str, raw_event: dict[str, Any]) -> None:
        """Handle an issue_assigned event from Jira_MCP."""
        payload = raw_event.get("payload", {})
        event = ContextEvent(
            event_type="issue_assigned",
            tenant_id=tenant_id,
            timestamp=datetime.now(UTC),
            payload={"issue_id": payload.get("issue_id", "")},
        )
        await self._context_engine.update(tenant_id, event)
        logger.info(
            "Processed issue_assigned event",
            extra={"tenant_id": tenant_id, "issue_id": payload.get("issue_id")},
        )
