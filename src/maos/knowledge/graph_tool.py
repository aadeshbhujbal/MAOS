"""MCP tool: graph_query — Knowledge Graph query and impact analysis for agents.

Provides the ``graph_query`` MCP tool registered in agent allow-lists,
enabling agents to execute Cypher queries against the tenant-scoped
Knowledge Graph and perform impact analysis traversals.

Tool name for allow-list registration: ``graph_query``

Functions
---------
graph_query(query, tenant_id, depth)
    Execute a Cypher query scoped to the tenant's graph namespace.
impact_analysis(entity_id, tenant_id, depth)
    Traverse affected entities downstream from a given entity.

Requirements: 12.6, 5.5, 9.5
"""

from __future__ import annotations

import logging
from typing import Any

from maos.knowledge.graph import KnowledgeGraphClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool metadata for MCP Registry registration
# ---------------------------------------------------------------------------

TOOL_NAME: str = "graph_query"
"""The canonical tool name used in agent MCP allow-lists (Req 12.6, 9.5)."""

TOOL_DESCRIPTION: str = (
    "Execute Cypher queries against the Knowledge Graph and perform "
    "impact analysis on code entities within the tenant's scope."
)

# ---------------------------------------------------------------------------
# Shared client reference (set during application startup)
# ---------------------------------------------------------------------------

_graph_client: KnowledgeGraphClient | None = None


def configure(client: KnowledgeGraphClient) -> None:
    """Bind the module-level graph client used by tool functions.

    Called during application startup to inject the initialized
    ``KnowledgeGraphClient`` instance.

    Parameters
    ----------
    client:
        An initialized and connected KnowledgeGraphClient.
    """
    global _graph_client
    _graph_client = client
    logger.info("graph_query tool configured with KnowledgeGraphClient")


def _get_client() -> KnowledgeGraphClient:
    """Return the configured graph client, raising if not yet initialized."""
    if _graph_client is None:
        raise RuntimeError(
            "graph_query tool not configured — call configure() during startup"
        )
    return _graph_client


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------


async def graph_query(
    query: str,
    tenant_id: str,
    depth: int = 3,
) -> list[dict[str, Any]]:
    """Execute a Cypher query scoped to the tenant's graph namespace (Req 12.6).

    Delegates to :meth:`KnowledgeGraphClient.query` after injecting a
    tenant-scope constraint. The ``depth`` parameter is passed as a Cypher
    query parameter available to the caller's query as ``$depth``.

    Parameters
    ----------
    query:
        A Cypher query string. The query is executed within the context of
        the tenant's graph namespace.
    tenant_id:
        The tenant identifier used to scope the query. Passed as the
        ``$tenant_id`` parameter to the Cypher execution context.
    depth:
        Maximum traversal depth for path-based queries (default 3).
        Available as ``$depth`` in the Cypher query.

    Returns
    -------
    list[dict[str, Any]]
        A list of result records, each as a dict of column names to values.
    """
    client = _get_client()

    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "depth": depth,
    }

    logger.debug(
        "graph_query invoked: tenant=%s depth=%d query=%.100s",
        tenant_id,
        depth,
        query,
    )

    results = await client.query(cypher=query, params=params)

    logger.info(
        "graph_query completed: tenant=%s result_count=%d",
        tenant_id,
        len(results),
    )
    return results


async def impact_analysis(
    entity_id: str,
    tenant_id: str,
    depth: int = 3,
) -> list[dict[str, Any]]:
    """Traverse affected entities downstream from a given entity (Req 12.3).

    Delegates to :meth:`KnowledgeGraphClient.impact_analysis` and returns
    the results as serializable dicts scoped to the tenant's graph namespace.

    Parameters
    ----------
    entity_id:
        The fully-qualified identifier of the starting entity node.
    tenant_id:
        The tenant identifier for namespace scoping and audit logging.
    depth:
        Maximum traversal depth in hops (default 3).

    Returns
    -------
    list[dict[str, Any]]
        A list of affected entity records with fields: entity_id, node_type,
        file_path, line_number, module, language, last_updated.
    """
    client = _get_client()

    logger.debug(
        "impact_analysis invoked: entity=%s tenant=%s depth=%d",
        entity_id,
        tenant_id,
        depth,
    )

    entities = await client.impact_analysis(entity_id=entity_id, depth=depth)

    results: list[dict[str, Any]] = [
        {
            "entity_id": entity.entity_id,
            "node_type": entity.node_type.value,
            "file_path": entity.file_path,
            "line_number": entity.line_number,
            "module": entity.module,
            "language": entity.language,
            "last_updated": entity.last_updated.isoformat(),
        }
        for entity in entities
    ]

    logger.info(
        "impact_analysis completed: entity=%s tenant=%s affected_count=%d",
        entity_id,
        tenant_id,
        len(results),
    )
    return results
