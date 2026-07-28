"""Knowledge Graph client for Neo4j — code relationships and impact analysis.

Provides a ``KnowledgeGraphClient`` that wraps the Neo4j async driver to manage
code entities, relationships, impact analysis traversals, and circular dependency
detection (Requirements 12.1, 12.2, 12.3, 12.6, 12.7, 12.8, 12.9).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from maos.knowledge.graph_models import CodeEntity, NodeType, RelationType

logger = logging.getLogger(__name__)


class KnowledgeGraphClient:
    """Neo4j-backed Knowledge Graph for code entity relationships (Req 12).

    Manages nodes representing code symbols (functions, classes, services, etc.)
    and directed edges representing relationships (CALLS, IMPORTS, DEPENDS_ON, etc.).
    Supports impact analysis via configurable-depth graph traversal and circular
    dependency detection within module scopes.
    """

    def __init__(self, uri: str, user: str, password: str) -> None:
        self._uri = uri
        self._user = user
        self._password = password
        self._driver: Any = None

    async def connect(self) -> None:
        """Establish Neo4j connection and verify connectivity."""
        from neo4j import AsyncGraphDatabase  # type: ignore[import-untyped]

        self._driver = AsyncGraphDatabase.driver(self._uri, auth=(self._user, self._password))
        await self._driver.verify_connectivity()
        logger.info("KnowledgeGraphClient connected to Neo4j at %s", self._uri)

    async def close(self) -> None:
        """Close the Neo4j driver connection."""
        if self._driver:
            await self._driver.close()
            self._driver = None

    async def add_entity(self, entity: CodeEntity) -> None:
        """Create or update a code entity node (Req 12.1).

        Uses MERGE to upsert by ``entity_id``, applying the node's ``NodeType``
        as a Neo4j label. The ``last_updated`` timestamp is always refreshed.
        Additional properties from the entity are stored as node properties.
        """
        node_type = entity.node_type.value
        query = (
            f"MERGE (e:{node_type} {{entity_id: $entity_id}}) "
            "SET e.file_path = $file_path, "
            "    e.line_number = $line_number, "
            "    e.module = $module, "
            "    e.language = $language, "
            "    e.last_updated = $last_updated, "
            "    e.properties = $properties"
        )

        async with self._driver.session() as session:
            await session.run(
                query,
                entity_id=entity.entity_id,
                file_path=entity.file_path,
                line_number=entity.line_number,
                module=entity.module,
                language=entity.language,
                last_updated=entity.last_updated.isoformat(),
                properties=str(entity.properties),
            )

    async def add_relationship(
        self,
        source_id: str,
        target_id: str,
        rel_type: RelationType,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Create a directed edge between two entities (Req 12.2).

        Both source and target must already exist as nodes. The relationship
        type is used as the Neo4j relationship label. Updates ``last_updated``
        on both involved nodes to reflect the modification timestamp.
        """
        rel_label = rel_type.value
        now = datetime.now(UTC).isoformat()
        query = (
            "MATCH (a {entity_id: $source_id}) "
            "MATCH (b {entity_id: $target_id}) "
            f"MERGE (a)-[r:{rel_label}]->(b) "
            "SET r.metadata = $metadata, "
            "    a.last_updated = $now, "
            "    b.last_updated = $now"
        )

        async with self._driver.session() as session:
            await session.run(
                query,
                source_id=source_id,
                target_id=target_id,
                metadata=str(metadata or {}),
                now=now,
            )

    async def impact_analysis(self, entity_id: str, depth: int = 3) -> list[CodeEntity]:
        """Return all transitively affected downstream entities (Req 12.3).

        Performs a variable-length path traversal from the given entity up to
        ``depth`` hops, returning distinct downstream nodes. Target: < 500ms
        on graphs up to 50,000 nodes.
        """
        # Neo4j does not support parameterised relationship depth, so we
        # interpolate the integer directly (safe - validated as int).
        max_depth = int(depth)
        query = (
            "MATCH (start {entity_id: $entity_id}) "
            f"MATCH path = (start)-[*1..{max_depth}]->(affected) "
            "RETURN DISTINCT affected.entity_id AS entity_id, "
            "       labels(affected)[0] AS node_type, "
            "       affected.file_path AS file_path, "
            "       affected.line_number AS line_number, "
            "       affected.module AS module, "
            "       affected.language AS language, "
            "       affected.last_updated AS last_updated"
        )

        results: list[CodeEntity] = []
        async with self._driver.session() as session:
            result = await session.run(query, entity_id=entity_id)
            async for record in result:
                results.append(
                    CodeEntity(
                        entity_id=record["entity_id"],
                        node_type=NodeType(record["node_type"]),
                        file_path=record["file_path"] or "",
                        line_number=record["line_number"] or 0,
                        module=record["module"] or "",
                        language=record["language"] or "",
                        last_updated=(
                            datetime.fromisoformat(record["last_updated"])
                            if record["last_updated"]
                            else datetime.now(UTC)
                        ),
                    )
                )
        return results

    async def detect_circular_deps(self, module_scope: str) -> list[list[str]]:
        """Detect circular dependencies within a module scope (Req 12.7).

        Searches for cycles (length 2-10) among nodes whose ``module``
        property starts with the given scope prefix. Returns up to 100 cycles
        as lists of entity IDs.
        """
        query = (
            "MATCH path = (a)-[:IMPORTS|DEPENDS_ON*2..10]->(a) "
            "WHERE a.module STARTS WITH $module_scope "
            "RETURN [n IN nodes(path) | n.entity_id] AS cycle "
            "LIMIT 100"
        )

        cycles: list[list[str]] = []
        async with self._driver.session() as session:
            result = await session.run(query, module_scope=module_scope)
            async for record in result:
                cycles.append(record["cycle"])
        return cycles

    async def query(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute an arbitrary Cypher query (Req 12.6).

        Agents may invoke this through the ``graph_query`` MCP tool for
        ad-hoc knowledge graph exploration.
        """
        results: list[dict[str, Any]] = []
        async with self._driver.session() as session:
            result = await session.run(cypher, **(params or {}))
            async for record in result:
                results.append(dict(record))
        return results

    async def health_check(self) -> dict[str, str]:
        """Check Neo4j connectivity (Req 12.9).

        Returns ``{"status": "healthy"}`` on success, or
        ``{"status": "unhealthy", "reason": ...}`` on failure.
        """
        try:
            await self._driver.verify_connectivity()
            return {"status": "healthy"}
        except Exception as exc:
            return {"status": "unhealthy", "reason": str(exc)}
