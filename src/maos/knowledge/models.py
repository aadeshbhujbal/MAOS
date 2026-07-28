"""Knowledge Base domain contracts for MAOS.

This module defines the document-level models used by the Knowledge Store
(PostgresStore wrapper), ingestion pipeline, and retrieval system:

- ``DocumentMetadata`` — per-chunk provenance and sizing metadata (Req 3.4).
- ``Document`` — the stored unit with namespace, content, and optional embedding (Req 1.3).
- ``SearchResult`` — a single vector-similarity match returned from retrieval (Req 5.3).
- ``PaginatedResult`` — paginated listing of documents (Req 8.5).

These are pure Pydantic v2 contracts: they carry no behaviour beyond validation
so the Knowledge Store and Hypothesis correctness properties can construct and
reason about them deterministically.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DocumentMetadata(BaseModel):
    """Per-chunk provenance and sizing metadata (Req 3.4, 3.10)."""

    source_filename: str
    upload_timestamp: datetime
    file_type: Literal[
        "pdf", "markdown", "python", "typescript", "javascript", "java", "go", "rust"
    ]
    chunk_index: int = Field(ge=0)
    total_chunks: int = Field(gt=0)
    uploader_id: str
    token_count: int = Field(gt=0)


class Document(BaseModel):
    """Stored document unit with namespace, content, and optional embedding (Req 1.3)."""

    document_id: str
    namespace: tuple[str, ...]
    key: str
    content: str
    embedding: list[float] | None = None
    metadata: DocumentMetadata


class SearchResult(BaseModel):
    """A single vector-similarity match from the retrieval system (Req 5.3)."""

    document_id: str
    content: str
    relevance_score: float = Field(ge=0.0, le=1.0)
    source_filename: str
    metadata: DocumentMetadata


class PaginatedResult(BaseModel):
    """Paginated listing of documents (Req 8.5)."""

    total_count: int = Field(ge=0)
    limit: int = Field(gt=0)
    offset: int = Field(ge=0)
    items: list[Document]
