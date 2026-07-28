"""Knowledge Base configuration settings.

Environment variables are prefixed with ``MAOS_KNOWLEDGE_``.
Controls embedding model selection, chunk sizing, and upload limits.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class KnowledgeSettings(BaseSettings):
    """Knowledge Base subsystem settings (Req 1.2, 9.2)."""

    model_config = SettingsConfigDict(env_prefix="MAOS_KNOWLEDGE_", extra="ignore")

    embedding_model: str = Field(
        default="text-embedding-3-small",
        description="OpenAI embedding model used for document vectorization.",
    )
    embedding_dimensions: int = Field(
        default=1536,
        description="Dimensionality of the embedding vectors.",
    )
    default_chunk_size: int = Field(
        default=768,
        description="Target chunk size in tokens for the ingestion splitter.",
    )
    chunk_overlap: int = Field(
        default=64,
        description="Overlap in tokens between consecutive chunks.",
    )
    max_file_size_mb: int = Field(
        default=10,
        description="Maximum allowed upload file size in megabytes.",
    )
