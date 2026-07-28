"""Neo4j Knowledge Graph connection settings.

Environment variables are prefixed with ``MAOS_NEO4J_``.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Neo4jSettings(BaseSettings):
    """Neo4j connection settings for the Knowledge Graph (Req 12.1)."""

    model_config = SettingsConfigDict(env_prefix="MAOS_NEO4J_", extra="ignore")

    uri: str = Field(
        default="bolt://localhost:7687",
        description="Neo4j Bolt protocol URI.",
    )
    user: str = Field(
        default="neo4j",
        description="Neo4j authentication username.",
    )
    password: str = Field(
        default="",
        description="Neo4j authentication password (loaded from secrets at runtime).",
    )
