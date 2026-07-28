"""Database MCP Server — stub for development.

Provides database query execution and schema introspection.
Access tier: read_write.

Requirements: KB-10u 17.1, 17.2, 17.3.
"""

from __future__ import annotations

from .base import MCPServerBase, ServerConfig


class DatabaseMCPServer(MCPServerBase):
    """MCP server providing database operations."""

    name = "database"
    access_tier = "read_write"
    auth_method = "api_key"

    def __init__(self, config: ServerConfig) -> None:
        self._config = config

    @property
    def supported_tools(self) -> list[str]:
        return [
            "db_query",
            "db_execute",
            "db_list_tables",
            "db_describe_table",
            "db_schema",
            "db_transaction",
        ]

    async def db_query(self, *, sql: str, params: dict | None = None) -> dict:
        """Execute a read-only SQL query."""
        return {"sql": sql, "rows": [], "row_count": 0, "duration_ms": 0}

    async def db_execute(self, *, sql: str, params: dict | None = None) -> dict:
        """Execute a write SQL statement (INSERT/UPDATE/DELETE)."""
        return {
            "sql": sql,
            "rows_affected": 0,
            "duration_ms": 0,
        }

    async def db_list_tables(self) -> dict:
        """List all tables in the connected database."""
        return {"tables": [], "total": 0}

    async def db_describe_table(self, *, table_name: str) -> dict:
        """Describe the schema of a specific table."""
        return {"table_name": table_name, "columns": [], "primary_key": []}

    async def db_schema(self) -> dict:
        """Get the full database schema."""
        return {"tables": [], "views": [], "total_tables": 0}

    async def db_transaction(
        self, *, statements: list[str], isolation_level: str = "READ_COMMITTED"
    ) -> dict:
        """Execute multiple statements within a transaction."""
        return {
            "statements": statements,
            "isolation_level": isolation_level,
            "committed": True,
            "results": [],
        }
