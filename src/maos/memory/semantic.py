"""pgvector-backed Semantic_Memory store.

Provides long-term memory backed by a Postgres table with the ``pgvector``
extension for cosine-similarity search over embeddings.

Key guarantees:
- Every stored entry is tagged with ``tenant_id`` and ``mode`` (Req 7.8).
- Retrieval applies a **mandatory** pre-filter on ``(tenant_id, mode)`` so
  that queries never cross tenant or mode boundaries (Req 7.9).
- RUNTIME content is PHI-redacted before embedding (Req 9.5) — the ``redact``
  helper from ``maos.security.redaction`` is applied to the text (wrapped as
  a dict value) before the embedding function is called.

Requirements: 7.8, 7.9, 9.5, TC-6.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from maos.memory.database import DatabasePool
from maos.security.redaction import redact

# Type alias for the embedding function: async str -> list[float]
EmbeddingFn = Callable[[str], Awaitable[list[float]]]


# ---------------------------------------------------------------------------
# Table DDL (for reference / migration use)
# ---------------------------------------------------------------------------
# CREATE EXTENSION IF NOT EXISTS vector;
#
# CREATE TABLE semantic_memory (
#     id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#     tenant_id     TEXT NOT NULL,
#     mode          TEXT NOT NULL,       -- 'DEVELOPMENT' or 'RUNTIME'
#     embedding     vector(1536) NOT NULL,
#     text          TEXT NOT NULL,
#     meta          JSONB NOT NULL DEFAULT '{}',
#     retention_at  TIMESTAMPTZ NOT NULL,
#     created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
# );
#
# -- Mandatory pre-filter index for tenant/mode scoped queries (Req 7.9)
# CREATE INDEX idx_semantic_memory_tenant_mode
#     ON semantic_memory (tenant_id, mode);
#
# -- Optional: IVFFlat or HNSW index for vector similarity
# CREATE INDEX idx_semantic_memory_embedding_cosine
#     ON semantic_memory USING hnsw (embedding vector_cosine_ops);
# ---------------------------------------------------------------------------


class SemanticMemoryStore:
    """Long-term semantic memory backed by pgvector.

    Stores embedded text with tenant and mode tagging, and retrieves the
    top-k results using cosine similarity with mandatory tenant/mode
    pre-filtering.
    """

    def __init__(self, pool: DatabasePool, embed_fn: EmbeddingFn) -> None:
        """Initialize the store.

        Parameters
        ----------
        pool:
            An open ``DatabasePool`` instance for async Postgres access.
        embed_fn:
            An async callable that takes a string and returns an embedding
            vector (list of floats). The dimensionality must match the
            ``vector`` column declared in the table DDL.
        """
        self._pool = pool
        self._embed_fn = embed_fn

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def write(
        self,
        tenant_id: str,
        mode: str,
        text: str,
        meta: dict[str, Any],
        *,
        retention_at: datetime | None = None,
    ) -> str:
        """Generate an embedding for *text* and persist to semantic_memory.

        For RUNTIME mode, the text is PHI-redacted before embedding
        (Req 9.5). The entry is tagged with ``tenant_id`` and ``mode``
        (Req 7.8).

        Parameters
        ----------
        tenant_id:
            The clinic/tenant scope for this entry.
        mode:
            Agent operating mode — ``"DEVELOPMENT"`` or ``"RUNTIME"``.
        text:
            The text content to embed and store.
        meta:
            Arbitrary metadata stored as JSONB alongside the entry.
        retention_at:
            Optional expiry timestamp. Defaults to 90 days from now if
            not provided.

        Returns
        -------
        str
            The generated UUID for the inserted row.
        """
        # PHI redaction for RUNTIME content (Req 9.5):
        # Wrap text in a dict so the redaction logic can inspect/strip
        # PHI-marker keys from the metadata, and apply pattern-based
        # redaction to the text content itself.
        if mode == "RUNTIME":
            redacted_data = redact({"content": text, **meta})
            text_to_embed = redacted_data.pop("content", text)
            meta = redacted_data
        else:
            text_to_embed = text

        # Generate embedding vector
        embedding = await self._embed_fn(text_to_embed)

        # Generate a unique ID for this entry
        entry_id = str(uuid.uuid4())

        # Default retention: 90 days from now
        if retention_at is None:
            retention_at = datetime.now(UTC) + timedelta(days=90)

        # Insert into the semantic_memory table
        query = """
            INSERT INTO semantic_memory (id, tenant_id, mode, embedding, text, meta, retention_at)
            VALUES (%s, %s, %s, %s::vector, %s, %s::jsonb, %s)
        """
        params = (
            entry_id,
            tenant_id,
            mode,
            str(embedding),  # pgvector accepts text representation '[0.1, 0.2, ...]'
            text_to_embed,
            json.dumps(meta),
            retention_at,
        )

        await self._pool.execute(query, params)
        return entry_id

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    async def query(
        self,
        tenant_id: str,
        mode: str,
        query_text: str,
        k: int = 5,
    ) -> list[dict[str, Any]]:
        """Retrieve the top-k semantically similar entries.

        Performs cosine similarity search with a **mandatory** pre-filter
        on ``(tenant_id, mode)`` so retrieval never crosses tenant or mode
        boundaries (Req 7.9).

        Parameters
        ----------
        tenant_id:
            The clinic/tenant scope to search within.
        mode:
            Agent operating mode to scope the search to.
        query_text:
            The query string to embed and search against.
        k:
            Number of top results to return (default 5).

        Returns
        -------
        list[dict]
            Top-k results ordered by cosine similarity (most similar first).
            Each dict contains: id, tenant_id, mode, text, meta, score,
            retention_at, created_at.
        """
        # Generate the query embedding
        query_embedding = await self._embed_fn(query_text)

        # Cosine similarity search with mandatory tenant/mode pre-filter
        # The <=> operator computes cosine distance; lower = more similar.
        search_query = """
            SELECT
                id,
                tenant_id,
                mode,
                text,
                meta,
                retention_at,
                created_at,
                1 - (embedding <=> %s::vector) AS score
            FROM semantic_memory
            WHERE tenant_id = %s
              AND mode = %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """
        params = (
            str(query_embedding),
            tenant_id,
            mode,
            str(query_embedding),
            k,
        )

        rows = await self._pool.fetch_all(search_query, params)
        return rows
