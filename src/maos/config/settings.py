"""Typed application settings for MAOS.

Settings load from the process environment (and an optional ``.env`` file for
local development) via ``pydantic-settings``. Real secrets are sourced at
runtime from a managed secrets store (Vault / cloud KMS) and are never embedded
in source artifacts (Req 9.10, TC-13); the fields here are placeholders /
connection references only.

Environment variables are prefixed with ``MAOS_`` unless an explicit alias is
declared (provider SDK keys keep their conventional names so the underlying
SDKs can also read them).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from maos.config.knowledge_settings import KnowledgeSettings
from maos.config.neo4j_settings import Neo4jSettings


class PostgresSettings(BaseSettings):
    """Postgres connection settings (checkpointer + tables, pgvector)."""

    model_config = SettingsConfigDict(env_prefix="MAOS_POSTGRES_", extra="ignore")

    dsn: str = Field(
        default="postgresql://maos:maos@localhost:5432/maos",
        description="Async-capable Postgres DSN; pooled via PgBouncer in deployment.",
    )


class RedisSettings(BaseSettings):
    """Redis connection settings (Shared_Context, cache, pub/sub)."""

    model_config = SettingsConfigDict(env_prefix="MAOS_REDIS_", extra="ignore")

    url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis URL backing Shared_Context and caching.",
    )


class BrokerSettings(BaseSettings):
    """Message broker / background-worker queue settings (Arq)."""

    model_config = SettingsConfigDict(env_prefix="MAOS_BROKER_", extra="ignore")

    url: str = Field(
        default="redis://localhost:6379/1",
        description="Broker URL for the internal Agent_Message bus and task queues.",
    )


class ProviderSettings(BaseSettings):
    """LLM provider credentials/placeholders.

    These are referenced ONLY behind the LLM_Provider_Adapter (Req 8.1, TC-4);
    no agent logic reads them directly. Keys are loaded from a managed secrets
    source at runtime and default to empty here.
    """

    model_config = SettingsConfigDict(extra="ignore")

    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")
    aws_region: str = Field(default="", alias="AWS_REGION")


class DragonflyCacheSettings(BaseSettings):
    """Dragonfly (Redis-compatible) cache settings for prompt and semantic caches (Req 15.7).

    Dragonfly is a high-performance, Redis-compatible in-memory store used as the
    backing store for the LLM prompt cache and semantic cache layers.
    """

    model_config = SettingsConfigDict(env_prefix="MAOS_DRAGONFLY_", extra="ignore")

    cache_url: str = Field(
        default="redis://localhost:6379/2",
        alias="MAOS_DRAGONFLY_CACHE_URL",
        description="Dragonfly connection URL for LLM prompt and semantic caches.",
    )
    prompt_cache_ttl: int = Field(
        default=3600,
        alias="MAOS_PROMPT_CACHE_TTL",
        gt=0,
        description="TTL in seconds for prompt cache entries (default 1 hour).",
    )
    semantic_cache_threshold: float = Field(
        default=0.95,
        alias="MAOS_SEMANTIC_CACHE_THRESHOLD",
        ge=0.0,
        le=1.0,
        description="Cosine similarity threshold for semantic cache hits (0.0-1.0).",
    )


class ScalabilitySettings(BaseSettings):
    """Scalability and concurrency cap settings (Req 14.1, 14.4)."""

    model_config = SettingsConfigDict(env_prefix="MAOS_", extra="ignore")

    max_queue_depth: int = Field(
        default=200,
        alias="MAOS_MAX_QUEUE_DEPTH",
        gt=0,
        description=(
            "Maximum pending jobs in the broker queue before backpressure "
            "engages (HTTP 429 + Retry-After)."
        ),
    )
    global_concurrency_cap: int = Field(
        default=100,
        alias="MAOS_GLOBAL_CONCURRENCY_CAP",
        gt=0,
        description="Maximum tasks executing simultaneously across all tenants.",
    )
    tenant_concurrency_cap: int = Field(
        default=10,
        alias="MAOS_TENANT_CONCURRENCY_CAP",
        gt=0,
        description="Maximum tasks executing simultaneously per tenant.",
    )
    backpressure_retry_after: int = Field(
        default=30,
        alias="MAOS_BACKPRESSURE_RETRY_AFTER",
        gt=0,
        description="Retry-After header value (seconds) when backpressure is active.",
    )


class BudgetSettings(BaseSettings):
    """Cost/token budget placeholders (Req 15.5, 15.6)."""

    model_config = SettingsConfigDict(env_prefix="MAOS_", extra="ignore")

    default_task_token_budget: int = Field(
        default=100_000,
        alias="MAOS_DEFAULT_TASK_TOKEN_BUDGET",
        gt=0,
        description="Default per-Task token budget when a Task omits one.",
    )
    tenant_daily_token_ceiling: int = Field(
        default=5_000_000,
        alias="MAOS_TENANT_DAILY_TOKEN_CEILING",
        gt=0,
        description="Per-Tenant daily token ceiling for cost control.",
    )


class Settings(BaseSettings):
    """Top-level MAOS settings aggregating each subsystem's configuration."""

    model_config = SettingsConfigDict(
        env_prefix="MAOS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = Field(
        default="development",
        description="Deployment environment name (development | staging | production).",
    )
    service_name: str = Field(default="maos", description="Logical service name.")

    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    broker: BrokerSettings = Field(default_factory=BrokerSettings)
    providers: ProviderSettings = Field(default_factory=ProviderSettings)
    budgets: BudgetSettings = Field(default_factory=BudgetSettings)
    scalability: ScalabilitySettings = Field(default_factory=ScalabilitySettings)
    dragonfly_cache: DragonflyCacheSettings = Field(default_factory=DragonflyCacheSettings)
    knowledge: KnowledgeSettings = Field(default_factory=KnowledgeSettings)
    neo4j: Neo4jSettings = Field(default_factory=Neo4jSettings)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance loaded from the environment."""
    return Settings()
