"""PostgreSQL-backed Knowledge Graph connection settings.

Environment variables are prefixed with ``MAOS_GRAPH_``.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GraphSettings(BaseSettings):
    """PostgreSQL-backed Knowledge Graph settings."""

    model_config = SettingsConfigDict(env_prefix="MAOS_GRAPH_", extra="ignore")

    dsn: str = Field(
        default="",
        description="PostgreSQL DSN for knowledge graph tables. Falls back to MAOS_POSTGRES_DSN if empty.",
    )
