"""MCP Server Health Checker — periodic health monitoring with degradation logic.

This module implements an Arq periodic task that performs health checks on all
registered MCP servers every 30 seconds. It tracks consecutive failures per
server and applies degradation logic:

- At 3 consecutive failures: mark *degraded*, notify Monitoring_Agent, route to fallback
- At 5 consecutive failures: mark *unavailable*
- On success: reset consecutive_failures to 0, mark *healthy*

The health checker integrates with the existing ``MCPRegistry`` and runs as a
cron job on the MAOS Arq worker (``WorkerSettings``).

Requirements: 14.3, 14.5.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from arq.cron import cron

from maos.mcp.models import MCPServerRecord

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

HEALTH_CHECK_INTERVAL_SECONDS = 30
"""Interval between health check cycles (Req 14.3)."""

DEGRADED_THRESHOLD = 3
"""Consecutive failures before marking a server as degraded (Req 14.5)."""

UNAVAILABLE_THRESHOLD = 5
"""Consecutive failures before marking a server as unavailable (Req 14.5)."""

HEALTH_CHECK_TIMEOUT_SECONDS = 10
"""TCP connection timeout for individual server health checks."""


# ---------------------------------------------------------------------------
# Health check implementation
# ---------------------------------------------------------------------------


async def _ping_server(server: MCPServerRecord) -> bool:
    """Attempt a TCP connection to the server's endpoint to verify reachability.

    This is a lightweight connectivity check that verifies the server is
    accepting connections. For MVP, this uses a raw TCP connection to the
    server's host:port parsed from its ``endpoint_url``.

    Parameters
    ----------
    server:
        The MCP server record containing the endpoint URL.

    Returns
    -------
    bool
        True if the server responded within the timeout, False otherwise.
    """
    try:
        parsed = urlparse(server.endpoint_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)

        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=HEALTH_CHECK_TIMEOUT_SECONDS,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (OSError, TimeoutError, ConnectionError):
        return False


def _determine_health_status(consecutive_failures: int) -> str:
    """Determine the health status based on the consecutive failure count.

    Parameters
    ----------
    consecutive_failures:
        Current number of consecutive failures.

    Returns
    -------
    str
        One of 'healthy', 'degraded', or 'unavailable'.
    """
    if consecutive_failures >= UNAVAILABLE_THRESHOLD:
        return "unavailable"
    if consecutive_failures >= DEGRADED_THRESHOLD:
        return "degraded"
    return "healthy"


async def _notify_monitoring_agent(server_name: str, consecutive_failures: int) -> None:
    """Notify the Monitoring_Agent about a degraded MCP server.

    Emits a structured log event that can be consumed by the Monitoring_Agent
    via log subscription or event bus. In a production deployment this would
    also enqueue an alert task for the Monitoring_Agent.

    Parameters
    ----------
    server_name:
        The name of the degraded server.
    consecutive_failures:
        The current consecutive failure count.
    """
    logger.warning(
        "MCP server degraded — notifying Monitoring_Agent",
        extra={
            "event_type": "mcp_server_degraded",
            "server_name": server_name,
            "consecutive_failures": consecutive_failures,
            "notified_agent": "Monitoring_Agent",
            "timestamp": datetime.now(tz=UTC).isoformat(),
        },
    )


async def _route_to_fallback(server: MCPServerRecord) -> None:
    """Route traffic to the configured fallback server (if any).

    Logs the fallback routing decision. Actual traffic rerouting is handled
    by the MCPRegistry's ``resolve_tool`` method which already prefers healthy
    servers over degraded ones.

    Parameters
    ----------
    server:
        The degraded server whose traffic should be rerouted.
    """
    if server.fallback_server:
        logger.info(
            "Routing traffic from degraded server to fallback",
            extra={
                "degraded_server": server.name,
                "fallback_server": server.fallback_server,
            },
        )
    else:
        logger.info(
            "No fallback configured for degraded server %s",
            server.name,
            extra={"degraded_server": server.name},
        )


# ---------------------------------------------------------------------------
# Core health check loop
# ---------------------------------------------------------------------------


async def run_health_checks(ctx: dict[str, Any]) -> None:
    """Execute health checks on all registered MCP servers.

    This function is invoked as an Arq periodic task every 30 seconds.
    It iterates over all registered servers, pings each one, and applies
    the degradation logic:

    1. On success: reset consecutive_failures to 0, set status 'healthy'.
    2. On failure: increment consecutive_failures.
    3. At 3 failures: mark 'degraded', notify Monitoring_Agent, route to fallback.
    4. At 5 failures: mark 'unavailable'.

    Parameters
    ----------
    ctx:
        Arq worker context dict. Must contain 'mcp_registry' key with an
        ``MCPRegistry`` instance (set up during worker ``on_startup``).
    """
    from maos.mcp.registry import MCPRegistry

    registry: MCPRegistry | None = ctx.get("mcp_registry")
    if registry is None:
        logger.debug("MCPRegistry not available in worker context; skipping health checks")
        return

    servers = await registry.list_servers()
    if not servers:
        return

    logger.debug("Running health checks on %d MCP servers", len(servers))

    for server in servers:
        is_healthy = await _ping_server(server)

        if is_healthy:
            # Reset failures and mark healthy
            if server.health_status != "healthy" or server.consecutive_failures > 0:
                await registry.update_health(server.name, "healthy", 0)
                logger.info(
                    "MCP server %s recovered — marked healthy",
                    server.name,
                )
        else:
            # Increment failure count
            new_failures = server.consecutive_failures + 1
            new_status = _determine_health_status(new_failures)

            await registry.update_health(server.name, new_status, new_failures)

            # At exactly 3 failures: notify and route to fallback (Req 14.5)
            if new_failures == DEGRADED_THRESHOLD:
                await _notify_monitoring_agent(server.name, new_failures)
                await _route_to_fallback(server)

            # Log status transitions
            if new_status != server.health_status:
                logger.warning(
                    "MCP server %s status changed: %s -> %s (failures=%d)",
                    server.name,
                    server.health_status,
                    new_status,
                    new_failures,
                )


# ---------------------------------------------------------------------------
# Arq cron schedule
# ---------------------------------------------------------------------------

# Arq cron job definition: runs every 30 seconds.
# Import this in WorkerSettings.cron_jobs to activate the periodic task.
mcp_health_check_cron = cron(
    run_health_checks,
    second={0, 30},
    run_at_startup=True,
)
"""Arq cron job that triggers MCP health checks every 30 seconds.

Add to ``WorkerSettings.cron_jobs`` to activate::

    class WorkerSettings:
        cron_jobs = [mcp_health_check_cron]
"""
