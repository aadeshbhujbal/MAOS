"""Database migration runner for MAOS.

Applies SQL migration files from this package directory in lexicographic order.
Tracks applied migrations in a ``schema_migrations`` table to ensure each file
runs exactly once. Designed to be invoked by the Kubernetes migration Job:

    python -m maos.migrations.run

Requirements: 14.3.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import psycopg

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_MIGRATIONS_DIR = Path(__file__).parent


def _get_dsn() -> str:
    """Build the Postgres DSN from environment variables."""
    host = os.environ.get("MAOS_POSTGRES_HOST", "localhost")
    port = os.environ.get("MAOS_POSTGRES_PORT", "5432")
    db = os.environ.get("MAOS_POSTGRES_DB", "maos")
    user = os.environ.get("MAOS_POSTGRES_USER", "maos")
    password = os.environ.get("MAOS_POSTGRES_PASSWORD", "")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


# ---------------------------------------------------------------------------
# Migration tracking table
# ---------------------------------------------------------------------------

_CREATE_TRACKING_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename    TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _discover_migrations() -> list[Path]:
    """Return .sql migration files sorted lexicographically."""
    sql_files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
    return sql_files


async def run_migrations() -> int:
    """Connect to Postgres and apply pending migrations in order.

    Returns
    -------
    int
        Number of newly applied migrations.
    """
    dsn = _get_dsn()

    logger.info("Connecting to database for migrations...")
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=False) as conn:
        # Ensure the tracking table exists.
        async with conn.cursor() as cur:
            await cur.execute(_CREATE_TRACKING_TABLE)
        await conn.commit()

        # Discover already-applied migrations.
        async with conn.cursor() as cur:
            await cur.execute("SELECT filename FROM schema_migrations ORDER BY filename")
            applied = {row[0] for row in await cur.fetchall()}

        # Discover all available migration files.
        migrations = _discover_migrations()
        pending = [m for m in migrations if m.name not in applied]

        if not pending:
            logger.info("No pending migrations. Database is up to date.")
            return 0

        logger.info(
            "Found %d pending migration(s): %s",
            len(pending),
            ", ".join(m.name for m in pending),
        )

        # Apply each migration in a dedicated transaction.
        applied_count = 0
        for migration_file in pending:
            sql = migration_file.read_text(encoding="utf-8")
            logger.info("Applying migration: %s", migration_file.name)

            try:
                async with conn.cursor() as cur:
                    await cur.execute(sql)
                    await cur.execute(
                        "INSERT INTO schema_migrations (filename) VALUES (%s)",
                        (migration_file.name,),
                    )
                await conn.commit()
                applied_count += 1
                logger.info("Applied migration: %s", migration_file.name)
            except Exception:
                await conn.rollback()
                logger.exception(
                    "Failed to apply migration: %s. Rolling back and stopping.",
                    migration_file.name,
                )
                raise

    logger.info(
        "Migration complete: %d migration(s) applied successfully.", applied_count
    )
    return applied_count


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for the migration runner."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        count = asyncio.run(run_migrations())
    except Exception:
        logger.exception("Migration failed.")
        sys.exit(1)

    if count == 0:
        logger.info("Nothing to do.")
    sys.exit(0)


if __name__ == "__main__":
    main()
