"""MCP tool: code_search — Structural code search for agents.

Provides the ``code_search`` MCP tool registered in agent allow-lists,
enabling agents to execute structural queries against the code graph
(e.g., "find all classes implementing interface X") and receive matching
code entities with file locations.

Uses ``CodeGraphBuilder`` (symbol index) for local fast lookups and
``KnowledgeGraphClient`` (PostgreSQL) for relationship-based structural queries.

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
# Query-type to relationship mapping
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


def _build_relationship_sql(
    rel_type: RelationType,
    direction: str,
    target_entity: str,
) -> tuple[str, dict[str, Any]]:
    """Build a SQL query for relationship-based structural search.

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
    tuple of (sql_query, params)
    """
    rel_label = rel_type.value

    if direction == "incoming":
        # Find entities that have the given relationship TO the target
        sql = """
            SELECT n.entity_id, n.node_type, n.file_path,
                   n.line_number, n.module, n.language
            FROM kg_edges e
            JOIN kg_nodes n ON n.entity_id = e.source_id
            WHERE e.target_id ILIKE %(target_name)s
              AND e.rel_type = %(rel_type)s
            LIMIT 50
        """
    else:
        # Find entities that the target points TO via the relationship
        sql = """
            SELECT n.entity_id, n.node_type, n.file_path,
                   n.line_number, n.module, n.language
            FROM kg_edges e
            JOIN kg_nodes n ON n.entity_id = e.target_id
            WHERE e.source_id ILIKE %(target_name)s
              AND e.rel_type = %(rel_type)s
            LIMIT 50
        """

    return sql, {"target_name": f"%{target_entity}%", "rel_type": rel_label}


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
        sql, params = _build_relationship_sql(rel_type, direction, query)

        # Add optional language filter
        if language:
            sql = sql.replace(
                "LIMIT 50",
                "AND n.language = %(language)s LIMIT 50",
            )
            params["language"] = language

        raw_results = await client.execute(sql=sql, params=params)
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
    then falls back to a SQL ILIKE query for broader search.
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

    # Fallback: SQL ILIKE query on kg_nodes for broader search
    sql = """
        SELECT entity_id, node_type, file_path, line_number, module, language
        FROM kg_nodes
        WHERE entity_id ILIKE %(query)s
    """
    params: dict[str, Any] = {"query": f"%{query}%"}

    if language:
        sql += " AND language = %(language)s"
        params["language"] = language

    sql += " LIMIT 50"

    raw_results = await client.execute(sql=sql, params=params)
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
    sql = "SELECT * FROM kg_nodes WHERE node_type = %(node_type)s"
    params: dict[str, Any] = {"node_type": node_type}

    if language:
        sql += " AND language = %(language)s"
        params["language"] = language

    sql += " LIMIT 50"

    raw_results = await client.execute(sql=sql, params=params)
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
