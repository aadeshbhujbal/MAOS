"""LangGraph Functional API ingestion workflow.

Defines the durable document ingestion pipeline using LangGraph's ``@entrypoint``
and ``@task`` decorators. The workflow orchestrates:

1. **extract_text** — delegates to format-specific extractors (PDF, Markdown, code).
2. **chunk_content** — splits extracted text into sized chunks with metadata.
3. **embed_and_store** — persists chunks as Documents in the Knowledge Store.

Each ``@task`` is individually retryable (3x with exponential backoff) and
observable via structured logging. The ``@entrypoint`` uses a Postgres
checkpointer for durable execution state.

References
----------
- Req 7.1: @entrypoint decorator for durable, checkpointed ingestion workflow
- Req 7.2: @task decorators for individual processing steps with retry
- Req 7.4: Retry up to 3 times with exponential backoff
- Req 7.5: Same Postgres checkpointer as existing LangGraph graphs
- Req 10.1: Structured log event on ingestion completion
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from langgraph.func import entrypoint, task  # type: ignore[import-untyped]
from langgraph.types import RetryPolicy  # type: ignore[import-untyped]

from maos.knowledge.ingestion.chunking import Chunk, chunk_code, chunk_markdown, chunk_text
from maos.knowledge.ingestion.extractors import (
    CodeBlock,
    ExtractionError,
    MarkdownSection,
    extract_code,
    extract_markdown,
    extract_pdf,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


@dataclass
class IngestionResult:
    """Final result of the ingestion workflow.

    Attributes:
        document_id: Unique identifier for the ingested document batch.
        chunk_count: Total number of chunks stored.
    """

    document_id: str
    chunk_count: int


# ---------------------------------------------------------------------------
# File type → language mapping for code extraction
# ---------------------------------------------------------------------------

_EXTENSION_TO_LANGUAGE: dict[str, str] = {
    "python": "python",
    "py": "python",
    "typescript": "typescript",
    "ts": "typescript",
    "javascript": "javascript",
    "js": "javascript",
    "java": "java",
    "go": "go",
    "rust": "rust",
    "rs": "rust",
}


# ---------------------------------------------------------------------------
# Module-level store reference (set during app startup)
# ---------------------------------------------------------------------------

_knowledge_store: Any = None
_checkpointer: Any = None


def set_workflow_store(store: Any) -> None:
    """Bind the KnowledgeStore instance used by embed_and_store.

    Called once during FastAPI lifespan initialization.
    """
    global _knowledge_store
    _knowledge_store = store


def get_workflow_store() -> Any:
    """Return the bound KnowledgeStore instance."""
    if _knowledge_store is None:
        raise RuntimeError(
            "KnowledgeStore not bound. Call set_workflow_store() during app startup."
        )
    return _knowledge_store


def set_checkpointer(checkpointer: Any) -> None:
    """Bind the Postgres checkpointer shared with existing LangGraph graphs (Req 7.5)."""
    global _checkpointer
    _checkpointer = checkpointer


def get_checkpointer() -> Any:
    """Return the bound Postgres checkpointer."""
    if _checkpointer is None:
        raise RuntimeError(
            "Checkpointer not bound. Call set_checkpointer() during app startup."
        )
    return _checkpointer


# ---------------------------------------------------------------------------
# @task: extract_text (Req 7.2, 7.4)
# ---------------------------------------------------------------------------


@task(retry=RetryPolicy(max_attempts=3, backoff_factor=2.0))
async def extract_text(
    file_content: bytes,
    file_type: str,
    filename: str,
) -> dict[str, Any]:
    """Extract text from uploaded file content.

    Delegates to the appropriate extractor based on file_type.

    Parameters
    ----------
    file_content:
        Raw bytes of the uploaded file.
    file_type:
        The file format identifier (pdf, markdown, python, typescript, etc.).
    filename:
        Original filename for error reporting.

    Returns
    -------
    dict
        Keys: "text" (str | None), "sections" (list[MarkdownSection] | None),
        "blocks" (list[CodeBlock] | None), "file_type" (str).

    Raises
    ------
    ExtractionError
        When extraction fails for the given file.
    """
    if file_type == "pdf":
        text = extract_pdf(file_content)
        return {"text": text, "sections": None, "blocks": None, "file_type": file_type}

    if file_type == "markdown":
        content_str = file_content.decode("utf-8")
        sections = extract_markdown(content_str)
        return {"text": None, "sections": sections, "blocks": None, "file_type": file_type}

    # Code files
    language = _EXTENSION_TO_LANGUAGE.get(file_type)
    if language is None:
        raise ExtractionError(
            f"Unsupported file type '{file_type}' for file '{filename}'. "
            f"Supported types: pdf, markdown, python, typescript, javascript, java, go, rust."
        )

    content_str = file_content.decode("utf-8")
    blocks = extract_code(content_str, language)
    return {"text": None, "sections": None, "blocks": blocks, "file_type": file_type}


# ---------------------------------------------------------------------------
# @task: chunk_content (Req 7.2, 7.4)
# ---------------------------------------------------------------------------


@task(retry=RetryPolicy(max_attempts=3, backoff_factor=2.0))
async def chunk_content(extracted: dict[str, Any]) -> list[Chunk]:
    """Split extracted content into sized chunks.

    Applies the appropriate chunking strategy based on extracted data type:
    - Plain text (from PDF): token-based splitting
    - Markdown sections: heading-aware splitting
    - Code blocks: function/class boundary splitting

    Parameters
    ----------
    extracted:
        Output from extract_text task.

    Returns
    -------
    list[Chunk]
        Chunks ready for embedding and storage.
    """
    file_type = extracted["file_type"]

    if extracted.get("text") is not None:
        # PDF or plain text → token-based chunking
        return chunk_text(extracted["text"])

    if extracted.get("sections") is not None:
        # Markdown → heading-aware chunking
        sections: list[MarkdownSection] = extracted["sections"]
        return chunk_markdown(sections)

    if extracted.get("blocks") is not None:
        # Code → boundary-aware chunking
        blocks: list[CodeBlock] = extracted["blocks"]
        return chunk_code(blocks)

    # Fallback: shouldn't happen if extract_text is correct
    raise ValueError(f"No extractable content found for file_type='{file_type}'")


# ---------------------------------------------------------------------------
# @task: embed_and_store (Req 7.2, 7.4)
# ---------------------------------------------------------------------------


@task(retry=RetryPolicy(max_attempts=3, backoff_factor=2.0))
async def embed_and_store(
    chunks: list[Chunk],
    document_id: str,
    tenant_id: str,
    target_role: str,
    filename: str,
    file_type: str,
    uploader_id: str,
) -> int:
    """Persist chunks as Documents in the Knowledge Store.

    Each chunk is stored with its metadata under the namespace
    ``(tenant_id, target_role)``. Embedding generation is handled
    by the KnowledgeStore's ``put()`` method.

    Parameters
    ----------
    chunks:
        Chunked content from chunk_content task.
    document_id:
        Unique identifier for this ingestion batch.
    tenant_id:
        Tenant identifier for namespace scoping.
    target_role:
        Agent role for namespace scoping.
    filename:
        Source filename for metadata.
    file_type:
        File format identifier for metadata.
    uploader_id:
        Identity of the uploader for audit trail.

    Returns
    -------
    int
        Number of chunks stored.
    """
    from datetime import UTC, datetime

    from maos.knowledge.models import Document, DocumentMetadata

    store = get_workflow_store()
    namespace = (tenant_id, target_role)
    total_chunks = len(chunks)
    upload_ts = datetime.now(tz=UTC)

    for chunk in chunks:
        chunk_key = f"{document_id}:chunk:{chunk.chunk_index}"
        metadata = DocumentMetadata(
            source_filename=filename,
            upload_timestamp=upload_ts,
            file_type=file_type,
            chunk_index=chunk.chunk_index,
            total_chunks=total_chunks,
            uploader_id=uploader_id,
            token_count=chunk.token_count,
        )
        doc = Document(
            document_id=f"{document_id}:{chunk.chunk_index}",
            namespace=namespace,
            key=chunk_key,
            content=chunk.content,
            embedding=None,  # Generated by KnowledgeStore.put()
            metadata=metadata,
        )
        await store.put(namespace=namespace, key=chunk_key, document=doc)

    return total_chunks


# ---------------------------------------------------------------------------
# @entrypoint: ingest_document (Req 7.1, 7.5, 10.1)
# ---------------------------------------------------------------------------


@entrypoint(checkpointer=None)  # Checkpointer bound at runtime via get_checkpointer()
async def ingest_document(
    file_content: bytes,
    file_type: str,
    filename: str,
    tenant_id: str,
    target_role: str,
    uploader_id: str = "system",
) -> IngestionResult:
    """Durable document ingestion workflow (Req 7.1, 7.5).

    Orchestrates text extraction → chunking → embedding/storage as a
    checkpointed LangGraph workflow. Emits structured log events on
    completion with ingestion metrics (Req 10.1).

    Parameters
    ----------
    file_content:
        Raw bytes of the uploaded file.
    file_type:
        File format identifier (pdf, markdown, python, typescript, etc.).
    filename:
        Original filename of the uploaded file.
    tenant_id:
        Tenant identifier for namespace scoping.
    target_role:
        Target agent role for namespace scoping.
    uploader_id:
        Identity of the uploader (default "system").

    Returns
    -------
    IngestionResult
        Contains document_id and chunk_count.
    """
    start_time_ms = time.perf_counter_ns() / 1_000_000
    document_id = str(uuid.uuid4())
    namespace = (tenant_id, target_role)

    # Step 1: Extract text (Req 7.2)
    extracted = await extract_text(file_content, file_type, filename)

    # Step 2: Chunk content (Req 7.2)
    chunks = await chunk_content(extracted)

    # Step 3: Embed and store (Req 7.2)
    chunk_count = await embed_and_store(
        chunks=chunks,
        document_id=document_id,
        tenant_id=tenant_id,
        target_role=target_role,
        filename=filename,
        file_type=file_type,
        uploader_id=uploader_id,
    )

    # Compute total tokens across all chunks
    total_tokens = sum(c.token_count for c in chunks)

    # Compute processing duration
    end_time_ms = time.perf_counter_ns() / 1_000_000
    processing_duration_ms = round(end_time_ms - start_time_ms, 2)

    # Emit structured log event (Req 10.1)
    logger.info(
        "document_ingested",
        extra={
            "document_id": document_id,
            "namespace": namespace,
            "chunk_count": chunk_count,
            "total_tokens": total_tokens,
            "processing_duration_ms": processing_duration_ms,
        },
    )

    return IngestionResult(document_id=document_id, chunk_count=chunk_count)
