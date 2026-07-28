"""Async Postgres access layer with PgBouncer-compatible connection pooling.

This module provides the shared ``DatabasePool`` used by all stateful
repositories (Agent_Registry, Audit_Log, Cost_Meter, work-unit persistence,
Checkpointer) so they share one pool rather than each opening separate
connections.

Key design decisions:
- **PgBouncer statement-level pooling compatibility**: PgBouncer in statement
  mode does not support prepared statements, so all queries use the *simple
  query protocol* (``prepare=False`` on cursors / ``autocommit=True`` on pool
  connections by default).
- The pool is created once at service startup and closed on shutdown.

Requirements: 14.3, TC-5.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from maos.config.settings import PostgresSettings


class DatabasePool:
    """Thin async wrapper around a ``psycopg_pool.AsyncConnectionPool``.

    The pool is PgBouncer-compatible (no prepared statements) and exposes
    convenience helpers for common query patterns used by all MAOS repos.
    """

    def __init__(self, dsn: str, *, min_size: int = 2, max_size: int = 10) -> None:
        """Initialize the pool (it must be opened before use via ``open()``).

        Parameters
        ----------
        dsn:
            Postgres DSN (typically from ``PostgresSettings.dsn``).
        min_size:
            Minimum connections maintained in the pool.
        max_size:
            Maximum connections the pool may hold.
        """
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        # Pool instance created on open(); None until then.
        self._pool: AsyncConnectionPool | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def open(self) -> None:
        """Open the underlying connection pool.

        Connections use ``autocommit=True`` and ``row_factory=dict_row`` for
        PgBouncer statement-pooling compatibility (no implicit transactions,
        no prepared statements).
        """
        self._pool = AsyncConnectionPool(
            conninfo=self._dsn,
            min_size=self._min_size,
            max_size=self._max_size,
            open=False,
            # PgBouncer statement-level pooling: autocommit avoids BEGIN/COMMIT
            # wrapping each statement and dict_row provides convenient dicts.
            kwargs={"autocommit": True, "row_factory": dict_row},
        )
        await self._pool.open()

    async def close(self) -> None:
        """Close the pool, releasing all connections."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    # ------------------------------------------------------------------
    # Context-manager: acquire a raw connection
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        """Yield an async connection from the pool.

        Usage::

            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1")
        """
        if self._pool is None:
            raise RuntimeError("DatabasePool is not open. Call open() first.")
        async with self._pool.connection() as conn:
            yield conn  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Convenience query helpers (use simple query protocol — no prepare)
    # ------------------------------------------------------------------

    async def execute(
        self,
        query: str | sql.Composed,
        params: Sequence[Any] | dict[str, Any] | None = None,
    ) -> None:
        """Execute a statement without returning rows.

        Uses ``prepare=False`` for PgBouncer compatibility.
        """
        async with self.acquire() as conn:
            await conn.execute(query, params, prepare=False)

    async def fetch_one(
        self,
        query: str | sql.Composed,
        params: Sequence[Any] | dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Execute a query and return the first row as a dict, or ``None``.

        Uses ``prepare=False`` for PgBouncer compatibility.
        """
        async with self.acquire() as conn:
            cur = await conn.execute(query, params, prepare=False)
            return await cur.fetchone()  # type: ignore[return-value]

    async def fetch_all(
        self,
        query: str | sql.Composed,
        params: Sequence[Any] | dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a query and return all rows as a list of dicts.

        Uses ``prepare=False`` for PgBouncer compatibility.
        """
        async with self.acquire() as conn:
            cur = await conn.execute(query, params, prepare=False)
            rows = await cur.fetchall()
            return rows  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_pool(settings: PostgresSettings) -> DatabasePool:
    """Build a ``DatabasePool`` from application settings.

    The caller is responsible for calling ``await pool.open()`` before use and
    ``await pool.close()`` on shutdown.

    Example (FastAPI lifespan)::

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            pool = create_pool(get_settings().postgres)
            await pool.open()
            app.state.db = pool
            yield
            await pool.close()
    """
    return DatabasePool(
        dsn=settings.dsn,
        min_size=2,
        max_size=10,
    )
