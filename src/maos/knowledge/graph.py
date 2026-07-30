"""Knowledge Graph client — PostgreSQL adjacency tables for code relationships.

Provides a ``KnowledgeGraphClient`` that uses asyncpg connection pool to manage
code entities (nodes) and relationships (edges) in PostgreSQL adjacency tables.
Supports impact analysis via recursive CTE traversal and circular dependency
detection within module scopes.

Replaces the former Neo4j-backed implementation with PostgreSQL tables,
keeping the same public interface for backward compatibility.

Requirements: 12.1, 12.2, 12.3, 12.6, 12.7, 12.8, 12.9
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from maos.knowledge.graph_models import CodeEntity, NodeType, RelationType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DDL for code graph adjacency tables
# ---------------------------------------------------------------------------

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS code_graph_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_type VARCHAR(64) NOT NULL,
    name VARCHAR(512) NOT NULL,
    file_path TEXT NOT NULL DEFAULT '',
    line_number INTEGER NOT NULL DEFAULT 0,
    module VARCHAR(512) NOT NULL DEFAULT '',
    language VARCHAR(32) NOT NULL DEFAULT '',
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_updated TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(name, tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_cgn_name ON code_graph_nodes(name);
CREATE INDEX IF NOT EXISTS idx_cgn_node_type ON code_graph_nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_cgn_tenant ON code_graph_nodes(tenant_id);
CREATE INDEX IF NOT EXISTS idx_cgn_file_path ON code_graph_nodes(file_path);
CREATE INDEX IF NOT EXISTS idx_cgn_module ON code_graph_nodes(module);

CREATE TABLE IF NOT EXISTS code_graph_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_node_id UUID NOT NULL REFERENCES code_graph_nodes(id) ON DELETE CASCADE,
    target_node_id UUID NOT NULL REFERENCES code_graph_nodes(id) ON DELETE CASCADE,
    edge_type VARCHAR(64) NOT NULL,
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(source_node_id, target_node_id, edge_type)
);

CREATE INDEX IF NOT EXISTS idx_cge_source ON code_graph_edges(source_node_id);
CREATE INDEX IF NOT EXISTS idx_cge_target ON code_graph_edges(target_node_id);
CREATE INDEX IF NOT EXISTS idx_cge_type ON code_graph_edges(edge_type);
CREATE INDEX IF NOT EXISTS idx_cge_tenant ON code_graph_edges(tenant_id);
"""


class KnowledgeGraphClient:
    """PostgreSQL-backed Knowledge Graph for code entity relationships (Req 12).

    Manages nodes representing code symbols (functions, classes, services, etc.)
    and directed edges representing relationships (CALLS, IMPORTS, DEPENDS_ON,
    etc.). Supports impact analysis via recursive CTE graph traversal and
    circular dependency detection within module scopes.

    Accepts an asyncpg connection pool for all database operations.
    """

    def __init__(self, pool: Any, tenant_id: str = "default") -> None:
        """Initialize with an asyncpg connection pool.

        Parameters
        ----------
        pool:
            An asyncpg pool (from asyncpg.create_pool).
        tenant_id:
            Default tenant for scoping operations.
        """
        self._pool = pool
        self._tenant_id = tenant_id

    async def create_tables(self) -> None:
        """Create the code_graph_nodes and code_graph_edges tables if needed."""
        async with self._pool.acquire() as conn:
            await conn.execute(CREATE_TABLES_SQL)
        logger.info("Code graph tables created/verified")

    async def connect(self) -> None:
        """Compatibility method — creates tables on connect."""
        await self.create_tables()

    async def close(self) -> None:
        """No-op for pool-based connections (pool lifecycle managed externally)."""
        pass

    # ------------------------------------------------------------------
    # Node operations
    # ------------------------------------------------------------------

    async def add_entity(self, entity: CodeEntity) -> None:
        """Create or update a code entity node (Req 12.1).

        Uses INSERT ... ON CONFLICT to upsert by (name, tenant_id).
        """
        now = datetime.now(UTC)
        metadata = json.dumps(entity.properties) if entity.properties else "{}"

        sql = """
            INSERT INTO code_graph_nodes
                (id, node_type, name, file_path, line_number, module, language,
                 tenant_id, metadata, last_updated)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10)
            ON CONFLICT (name, tenant_id)
            DO UPDATE SET
                node_type = EXCLUDED.node_type,
                file_path = EXCLUDED.file_path,
                line_number = EXCLUDED.line_number,
                module = EXCLUDED.module,
                language = EXCLUDED.language,
                metadata = EXCLUDED.metadata,
                last_updated = EXCLUDED.last_updated
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                sql,
                uuid.uuid4(),
                entity.node_type.value,
                entity.entity_id,
                entity.file_path,
                entity.line_number,
                entity.module,
                entity.language,
                self._tenant_id,
                metadata,
                now,
            )

    # ------------------------------------------------------------------
    # Edge operations
    # ------------------------------------------------------------------

    async def add_relationship(
        self,
        source_id: str,
        target_id: str,
        rel_type: RelationType,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Create a directed edge between two entities (Req 12.2).

        Ensures both source and target nodes exist (creates a placeholder for
        the target if it doesn't exist yet), then upserts the edge.
        """
        now = datetime.now(UTC)
        meta_json = json.dumps(metadata or {})

        async with self._pool.acquire() as conn:
            # Ensure target node exists (may be an external/unresolved reference)
            await conn.execute(
                """
                INSERT INTO code_graph_nodes
                    (id, node_type, name, file_path, tenant_id, last_updated)
                VALUES ($1, $2, $3, '', $4, $5)
                ON CONFLICT (name, tenant_id) DO NOTHING
                """,
                uuid.uuid4(),
                "SERVICE",
                target_id,
                self._tenant_id,
                now,
            )

            # Update last_updated on both nodes
            await conn.execute(
                """UPDATE code_graph_nodes SET last_updated = $1
                   WHERE name IN ($2, $3) AND tenant_id = $4""",
                now, source_id, target_id, self._tenant_id,
            )

            # Upsert edge
            await conn.execute(
                """
                INSERT INTO code_graph_edges
                    (id, source_node_id, target_node_id, edge_type, tenant_id, metadata)
                SELECT $1, src.id, tgt.id, $2, $3, $4::jsonb
                FROM code_graph_nodes src, code_graph_nodes tgt
                WHERE src.name = $5 AND src.tenant_id = $3
                  AND tgt.name = $6 AND tgt.tenant_id = $3
                ON CONFLICT (source_node_id, target_node_id, edge_type)
                DO UPDATE SET metadata = EXCLUDED.metadata
                """,
                uuid.uuid4(),
                rel_type.value,
                self._tenant_id,
                meta_json,
                source_id,
                target_id,
            )

    # ------------------------------------------------------------------
    # Graph traversal
    # ------------------------------------------------------------------

    async def get_dependencies(self, node_name: str) -> list[CodeEntity]:
        """Get all direct dependencies (outgoing edges) of a node."""
        sql = """
            SELECT n.name AS entity_id, n.node_type, n.file_path,
                   n.line_number, n.module, n.language, n.last_updated
            FROM code_graph_edges e
            JOIN code_graph_nodes src ON e.source_node_id = src.id
            JOIN code_graph_nodes n ON e.target_node_id = n.id
            WHERE src.name = $1 AND src.tenant_id = $2
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, node_name, self._tenant_id)
        return [self._row_to_entity(row) for row in rows]

    async def get_dependents(self, node_name: str) -> list[CodeEntity]:
        """Get all direct dependents (incoming edges) of a node."""
        sql = """
            SELECT n.name AS entity_id, n.node_type, n.file_path,
                   n.line_number, n.module, n.language, n.last_updated
            FROM code_graph_edges e
            JOIN code_graph_nodes n ON e.source_node_id = n.id
            JOIN code_graph_nodes tgt ON e.target_node_id = tgt.id
            WHERE tgt.name = $1 AND tgt.tenant_id = $2
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, node_name, self._tenant_id)
        return [self._row_to_entity(row) for row in rows]

    async def impact_analysis(self, entity_id: str, depth: int = 3) -> list[CodeEntity]:
        """Return all transitively affected downstream entities (Req 12.3).

        Uses a recursive CTE to traverse the graph up to ``depth`` hops.
        Target: < 500ms on graphs up to 50,000 nodes.
        """
        max_depth = int(depth)
        sql = f"""
            WITH RECURSIVE downstream AS (
                SELECT tgt.id, tgt.name AS entity_id, tgt.node_type,
                       tgt.file_path, tgt.line_number, tgt.module,
                       tgt.language, tgt.last_updated, 1 AS lvl
                FROM code_graph_edges e
                JOIN code_graph_nodes src ON e.source_node_id = src.id
                JOIN code_graph_nodes tgt ON e.target_node_id = tgt.id
                WHERE src.name = $1 AND src.tenant_id = $2

                UNION

                SELECT tgt.id, tgt.name, tgt.node_type,
                       tgt.file_path, tgt.line_number, tgt.module,
                       tgt.language, tgt.last_updated, d.lvl + 1
                FROM downstream d
                JOIN code_graph_edges e ON e.source_node_id = d.id
                JOIN code_graph_nodes tgt ON e.target_node_id = tgt.id
                WHERE d.lvl < {max_depth}
            )
            SELECT DISTINCT entity_id, node_type, file_path, line_number,
                           module, language, last_updated
            FROM downstream
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, entity_id, self._tenant_id)
        return [self._row_to_entity(row) for row in rows]

    async def detect_circular_deps(self, module_scope: str) -> list[list[str]]:
        """Detect circular dependencies within a module scope (Req 12.7).

        Uses a recursive CTE to find cycles among nodes whose module starts
        with the given scope prefix. Returns up to 100 cycles.
        """
        sql = """
            WITH RECURSIVE cycle_search AS (
                SELECT n.id, n.name, ARRAY[n.name] AS path, false AS is_cycle
                FROM code_graph_nodes n
                WHERE n.module LIKE $1 || '%'
                  AND n.tenant_id = $2

                UNION ALL

                SELECT tgt.id, tgt.name, cs.path || tgt.name,
                       tgt.name = cs.path[1]
                FROM cycle_search cs
                JOIN code_graph_edges e ON e.source_node_id = cs.id
                JOIN code_graph_nodes tgt ON e.target_node_id = tgt.id
                WHERE e.edge_type IN ('IMPORTS', 'DEPENDS_ON')
                  AND NOT cs.is_cycle
                  AND array_length(cs.path, 1) < 11
                  AND (tgt.name = cs.path[1] OR NOT tgt.name = ANY(cs.path))
            )
            SELECT path || path[1] AS cycle
            FROM cycle_search
            WHERE is_cycle
            LIMIT 100
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, module_scope, self._tenant_id)
        return [list(row["cycle"]) for row in rows]

    # ------------------------------------------------------------------
    # Query methods for code_search_tool and graph_tool
    # ------------------------------------------------------------------

    async def query(
        self,
        cypher: str | None = None,
        params: dict[str, Any] | None = None,
        sql: str | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a SQL query against the graph tables (Req 12.6).

        The ``cypher`` parameter is accepted for backward compatibility but
        is treated as SQL. New callers should use the ``sql`` parameter.
        """
        actual_sql = sql or cypher
        if not actual_sql:
            return []

        results: list[dict[str, Any]] = []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(actual_sql, *(params.values() if params else []))
            for row in rows:
                results.append(dict(row))
        return results

    async def query_relationship(
        self,
        rel_type: RelationType,
        direction: str,
        target_entity: str,
        language: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query nodes by relationship type and direction.

        Parameters
        ----------
        rel_type:
            The relationship type to search for.
        direction:
            'incoming' — find source nodes that have an edge TO the target.
            'outgoing' — find target nodes that the source has an edge FROM.
        target_entity:
            The entity name (partial match via ILIKE).
        language:
            Optional language filter.
        """
        if direction == "incoming":
            sql = """
                SELECT src.name AS entity_id, src.node_type, src.file_path,
                       src.line_number, src.module, src.language
                FROM code_graph_edges e
                JOIN code_graph_nodes src ON e.source_node_id = src.id
                JOIN code_graph_nodes tgt ON e.target_node_id = tgt.id
                WHERE e.edge_type = $1
                  AND tgt.name ILIKE '%' || $2 || '%'
                  AND tgt.tenant_id = $3
            """
        else:
            sql = """
                SELECT tgt.name AS entity_id, tgt.node_type, tgt.file_path,
                       tgt.line_number, tgt.module, tgt.language
                FROM code_graph_edges e
                JOIN code_graph_nodes src ON e.source_node_id = src.id
                JOIN code_graph_nodes tgt ON e.target_node_id = tgt.id
                WHERE e.edge_type = $1
                  AND src.name ILIKE '%' || $2 || '%'
                  AND src.tenant_id = $3
            """

        args: list[Any] = [rel_type.value, target_entity, self._tenant_id]

        if language:
            if direction == "incoming":
                sql += " AND src.language = $4"
            else:
                sql += " AND tgt.language = $4"
            args.append(language)

        sql += " LIMIT 50"

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        return [dict(row) for row in rows]

    async def search_entities(
        self,
        search_term: str,
        language: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search entities by name (partial match)."""
        sql = """
            SELECT name AS entity_id, node_type, file_path,
                   line_number, module, language
            FROM code_graph_nodes
            WHERE name ILIKE '%' || $1 || '%'
              AND tenant_id = $2
        """
        args: list[Any] = [search_term, self._tenant_id]

        if language:
            sql += " AND language = $3"
            args.append(language)

        sql += " LIMIT 50"

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        return [dict(row) for row in rows]

    async def search_by_node_type(
        self,
        node_type: str,
        language: str | None = None,
    ) -> list[dict[str, Any]]:
        """Find all entities of a given node type."""
        sql = """
            SELECT name AS entity_id, node_type, file_path,
                   line_number, module, language
            FROM code_graph_nodes
            WHERE node_type = $1 AND tenant_id = $2
        """
        args: list[Any] = [node_type, self._tenant_id]

        if language:
            sql += " AND language = $3"
            args.append(language)

        sql += " LIMIT 50"

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        return [dict(row) for row in rows]

    async def remove_file_entities(self, file_path: str) -> int:
        """Remove all nodes (and their edges via CASCADE) for a given file."""
        sql = """
            DELETE FROM code_graph_nodes
            WHERE file_path = $1 AND tenant_id = $2
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(sql, file_path, self._tenant_id)
            # asyncpg returns 'DELETE N'
            count = int(result.split()[-1]) if result else 0
        return count

    async def health_check(self) -> dict[str, str]:
        """Check PostgreSQL graph table connectivity (Req 12.9)."""
        try:
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return {"status": "healthy"}
        except Exception as exc:
            return {"status": "unhealthy", "reason": str(exc)}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_entity(row: Any) -> CodeEntity:
        """Convert a database row to a CodeEntity."""
        last_updated = row["last_updated"]
        if isinstance(last_updated, str):
            last_updated = datetime.fromisoformat(last_updated)
        elif last_updated is None:
            last_updated = datetime.now(UTC)

        return CodeEntity(
            entity_id=row["entity_id"],
            node_type=NodeType(row["node_type"]),
            file_path=row["file_path"] or "",
            line_number=row["line_number"] or 0,
            module=row["module"] or "",
            language=row["language"] or "",
            last_updated=last_updated,
        )
