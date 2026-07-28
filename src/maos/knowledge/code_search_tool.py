"""MCP tool: code_search — Structural code search for agents.

Provides the ``code_search`` MCP tool registered in agent allow-lists,
enabling agents to execute structural queries against the code graph
(e.g., "find all classes implementing interface X") and receive matching
code entities with file locations.

Uses ``CodeGraphBuilder`` (symbol index) for local fast lookups and
``KnowledgeGraphClient`` (Neo4j) for relationship-based structural queries.

Tool name for allow-list registration: ``code_search``

Functions
---------
code_search(query, tenant_id, query_type, language)
    Accept structural queries and return matching code entities with file locations.

Requirements: 22.5
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from maos.knowledge.code_graph_builder import CodeGraphBuilder
from maos.knowledge.graph import KnowledgeGraphClient
from maos.knowledge.graph_models import RelationType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool metadata for MCP Registry registration
# ---------------------------------------------------------------------------

TOOL_NAME: str = "code_search"
"""The canonical tool name used in agent MCP allow-lists (Req 22.5)."""

TOOL_DESCRIPTION: str = (
    "Search for code entities using structural queries such as "
    "'find all classes implementing interface X', "
    "'find all callers of function Y', or "
    "'find all imports of module Z'. "
    "Returns matching code entities with file paths and line numbers."
)


# ---------------------------------------------------------------------------
# Query types supported by the code_search tool
# ---------------------------------------------------------------------------


class CodeSearchQueryType(StrEnum):
    """Supported structural query types for code search."""

    IMPLEMENTS = "implements"
    INHERITS = "inherits"
    CALLS = "calls"
    CALLED_BY = "called_by"
    IMPORTS = "imports"
    IMPORTED_BY = "imported_by"
    DEPENDS_ON = "depends_on"
    SYMBOL_LOOKUP = "symbol_lookup"
    BY_NODE_TYPE = "by_node_type"


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


class CodeSearchResult(BaseModel):
    """A single code search result returned to the agent."""

    entity_id: str
    node_type: str
    file_path: str
    line_number: int
    module: str
    language: str
    relationship: str | None = None


# ---------------------------------------------------------------------------
# Shared references (set during application startup)
# ---------------------------------------------------------------------------

_graph_client: KnowledgeGraphClient | None = None
_code_graph_builder: CodeGraphBuilder | None = None


def configure(
    client: KnowledgeGraphClient,
    builder: CodeGraphBuilder | None = None,
) -> None:
    """Bind the module-level clients used by the code_search tool functions.

    Called during application startup to inject initialized instances.

    Parameters
    ----------
    client:
        An initialized and connected KnowledgeGraphClient for graph queries.
    builder:
        An optional CodeGraphBuilder for symbol index lookups.
    """
    global _graph_client, _code_graph_builder
    _graph_client = client
    _code_graph_builder = builder
    logger.info("code_search tool configured with KnowledgeGraphClient")


def _get_client() -> KnowledgeGraphClient:
    """Return the configured graph client, raising if not yet initialized."""
    if _graph_client is None:
        raise RuntimeError(
            "code_search tool not configured — call configure() during startup"
        )
    return _graph_client


# ---------------------------------------------------------------------------
# Query-type to Cypher mapping
# ---------------------------------------------------------------------------

_RELATIONSHIP_QUERIES: dict[CodeSearchQueryType, tuple[RelationType, str]] = {
    CodeSearchQueryType.IMPLEMENTS: (RelationType.IMPLEMENTS, "incoming"),
    CodeSearchQueryType.INHERITS: (RelationType.INHERITS, "incoming"),
    CodeSearchQueryType.CALLS: (RelationType.CALLS, "outgoing"),
    CodeSearchQueryType.CALLED_BY: (RelationType.CALLS, "incoming"),
    CodeSearchQueryType.IMPORTS: (RelationType.IMPORTS, "outgoing"),
    CodeSearchQueryType.IMPORTED_BY: (RelationType.IMPORTS, "incoming"),
    CodeSearchQueryType.DEPENDS_ON: (RelationType.DEPENDS_ON, "outgoing"),
}


def _build_relationship_cypher(
    rel_type: RelationType,
    direction: str,
    target_entity: str,
) -> tuple[str, dict[str, Any]]:
    """Build a Cypher query for relationship-based structural search.

    Parameters
    ----------
    rel_type:
        The relationship type to traverse.
    direction:
        'incoming' — find nodes that have the relationship pointing TO target.
        'outgoing' — find nodes that the target has the relationship pointing FROM.
    target_entity:
        The entity_id or name to search against.

    Returns
    -------
    tuple of (cypher_query, params)
    """
    rel_label = rel_type.value

    if direction == "incoming":
        # Find entities that have the given relationship TO the target
        # e.g., "find all classes implementing interface X"
        # => (source)-[:IMPLEMENTS]->(target where entity_id contains X)
        cypher = (
            f"MATCH (source)-[:{rel_label}]->(target) "
            "WHERE target.entity_id CONTAINS $target_name "
            "RETURN source.entity_id AS entity_id, "
            "       labels(source)[0] AS node_type, "
            "       source.file_path AS file_path, "
            "       source.line_number AS line_number, "
            "       source.module AS module, "
            "       source.language AS language "
            "LIMIT 50"
        )
    else:
        # Find entities that the target points TO via the relationship
        # e.g., "find all functions that X calls"
        # => (source where entity_id contains X)-[:CALLS]->(target)
        cypher = (
            f"MATCH (source)-[:{rel_label}]->(target) "
            "WHERE source.entity_id CONTAINS $target_name "
            "RETURN target.entity_id AS entity_id, "
            "       labels(target)[0] AS node_type, "
            "       target.file_path AS file_path, "
            "       target.line_number AS line_number, "
            "       target.module AS module, "
            "       target.language AS language "
            "LIMIT 50"
        )

    return cypher, {"target_name": target_entity}


# ---------------------------------------------------------------------------
# Tool function
# ---------------------------------------------------------------------------


async def code_search(
    query: str,
    tenant_id: str,
    query_type: str = "symbol_lookup",
    language: str | None = None,
) -> list[dict[str, Any]]:
    """Execute a structural code search and return matching entities (Req 22.5).

    Accepts structural queries such as:
    - "find all classes implementing interface X" (query_type=implements, query=X)
    - "find all callers of function Y" (query_type=called_by, query=Y)
    - "find symbol Z" (query_type=symbol_lookup, query=Z)
    - "find all controllers" (query_type=by_node_type, query=CONTROLLER)

    Parameters
    ----------
    query:
        The search term — entity name, interface name, module name, or node type.
    tenant_id:
        The tenant identifier for namespace scoping and audit logging.
    query_type:
        One of: implements, inherits, calls, called_by, imports, imported_by,
        depends_on, symbol_lookup, by_node_type. Default: symbol_lookup.
    language:
        Optional language filter (python, typescript, javascript, java, go, rust).

    Returns
    -------
    list[dict[str, Any]]
        Matching code entities with entity_id, node_type, file_path,
        line_number, module, and language fields.
    """
    client = _get_client()

    logger.debug(
        "code_search invoked: query=%s tenant=%s type=%s language=%s",
        query,
        tenant_id,
        query_type,
        language,
    )

    # Validate query_type
    try:
        search_type = CodeSearchQueryType(query_type)
    except ValueError:
        logger.warning("Invalid query_type: %s, falling back to symbol_lookup", query_type)
        search_type = CodeSearchQueryType.SYMBOL_LOOKUP

    results: list[dict[str, Any]] = []

    if search_type == CodeSearchQueryType.SYMBOL_LOOKUP:
        results = await _symbol_lookup(client, query, language)
    elif search_type == CodeSearchQueryType.BY_NODE_TYPE:
        results = await _by_node_type(client, query, language)
    elif search_type in _RELATIONSHIP_QUERIES:
        rel_type, direction = _RELATIONSHIP_QUERIES[search_type]
        cypher, params = _build_relationship_cypher(rel_type, direction, query)

        # Add optional language filter
        if language:
            cypher = cypher.replace(
                "LIMIT 50",
                "AND source.language = $language LIMIT 50"
                if direction == "incoming"
                else "AND target.language = $language LIMIT 50",
            )
            params["language"] = language

        raw_results = await client.query(cypher=cypher, params=params)
        results = [
            {
                "entity_id": r.get("entity_id", ""),
                "node_type": r.get("node_type", ""),
                "file_path": r.get("file_path", ""),
                "line_number": r.get("line_number", 0),
                "module": r.get("module", ""),
                "language": r.get("language", ""),
                "relationship": f"{search_type.value}:{query}",
            }
            for r in raw_results
        ]

    logger.info(
        "code_search completed: query=%s tenant=%s type=%s result_count=%d",
        query,
        tenant_id,
        search_type.value,
        len(results),
    )
    return results


# ---------------------------------------------------------------------------
# Internal query implementations
# ---------------------------------------------------------------------------


async def _symbol_lookup(
    client: KnowledgeGraphClient,
    query: str,
    language: str | None = None,
) -> list[dict[str, Any]]:
    """Look up symbols by name using the symbol index or graph query.

    First checks the local symbol index (CodeGraphBuilder) for fast results,
    then falls back to a Neo4j query for broader search.
    """
    # Try local symbol index first (fast path)
    if _code_graph_builder is not None:
        location = _code_graph_builder.symbol_index.lookup(query)
        if location is not None:
            result: dict[str, Any] = {
                "entity_id": query,
                "node_type": location.entity_type,
                "file_path": location.file_path,
                "line_number": location.line_number,
                "module": "",
                "language": location.language,
                "relationship": None,
            }
            return [result]

        # Try partial match on symbol index
        all_symbols = _code_graph_builder.symbol_index.all_symbols()
        partial_matches = [
            {
                "entity_id": name,
                "node_type": loc.entity_type,
                "file_path": loc.file_path,
                "line_number": loc.line_number,
                "module": "",
                "language": loc.language,
                "relationship": None,
            }
            for name, loc in all_symbols.items()
            if query.lower() in name.lower()
        ]
        if partial_matches:
            # Apply language filter if specified
            if language:
                partial_matches = [
                    m for m in partial_matches if m["language"] == language
                ]
            return partial_matches[:50]

    # Fallback: Neo4j graph query for broader structural search
    cypher = (
        "MATCH (e) "
        "WHERE e.entity_id CONTAINS $query "
    )
    params: dict[str, Any] = {"query": query}

    if language:
        cypher += "AND e.language = $language "
        params["language"] = language

    cypher += (
        "RETURN e.entity_id AS entity_id, "
        "       labels(e)[0] AS node_type, "
        "       e.file_path AS file_path, "
        "       e.line_number AS line_number, "
        "       e.module AS module, "
        "       e.language AS language "
        "LIMIT 50"
    )

    raw_results = await client.query(cypher=cypher, params=params)
    return [
        {
            "entity_id": r.get("entity_id", ""),
            "node_type": r.get("node_type", ""),
            "file_path": r.get("file_path", ""),
            "line_number": r.get("line_number", 0),
            "module": r.get("module", ""),
            "language": r.get("language", ""),
            "relationship": None,
        }
        for r in raw_results
    ]


async def _by_node_type(
    client: KnowledgeGraphClient,
    node_type: str,
    language: str | None = None,
) -> list[dict[str, Any]]:
    """Find all entities of a given node type (e.g., CONTROLLER, SERVICE)."""
    # Use the node_type as a Neo4j label for efficient lookups
    cypher = (
        f"MATCH (e:{node_type}) "
    )
    params: dict[str, Any] = {}

    if language:
        cypher += "WHERE e.language = $language "
        params["language"] = language

    cypher += (
        "RETURN e.entity_id AS entity_id, "
        "       labels(e)[0] AS node_type, "
        "       e.file_path AS file_path, "
        "       e.line_number AS line_number, "
        "       e.module AS module, "
        "       e.language AS language "
        "LIMIT 50"
    )

    raw_results = await client.query(cypher=cypher, params=params)
    return [
        {
            "entity_id": r.get("entity_id", ""),
            "node_type": r.get("node_type", ""),
            "file_path": r.get("file_path", ""),
            "line_number": r.get("line_number", 0),
            "module": r.get("module", ""),
            "language": r.get("language", ""),
            "relationship": None,
        }
        for r in raw_results
    ]
