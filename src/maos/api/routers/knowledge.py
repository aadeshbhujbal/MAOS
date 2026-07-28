"""Knowledge Base document upload endpoint.

Implements ``POST /v1/knowledge/documents`` for multipart file upload with
validation, text extraction, chunking, and storage in the Knowledge Store.

Validations:
- File size: reject > 10 MB with HTTP 413.
- File format: accept PDF (.pdf), Markdown (.md), and code files
  (.py, .ts, .js, .java, .go, .rs) — reject unsupported with HTTP 415.
- Extraction failure: return HTTP 422 with descriptive error.

Documents are stored in namespace ``(tenant_id, target_role)`` as specified
in the upload request.

Requirements: 3.1, 3.2, 3.8, 3.9, 3.10.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from maos.api.auth import RequesterContext, get_authenticated_requester
from maos.knowledge.ingestion.chunking import Chunk, chunk_code, chunk_markdown, chunk_text
from maos.knowledge.ingestion.extractors import (
    ExtractionError,
    extract_code,
    extract_markdown,
    extract_pdf,
)
from maos.knowledge.models import Document, DocumentMetadata
from maos.knowledge.store import KnowledgeStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

# Mapping from file extension to internal file_type label.
_EXTENSION_TO_TYPE: dict[str, str] = {
    ".pdf": "pdf",
    ".md": "markdown",
    ".py": "python",
    ".ts": "typescript",
    ".js": "javascript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
}

_ALLOWED_EXTENSIONS = set(_EXTENSION_TO_TYPE.keys())

# Extension to Tree-sitter language identifier for code extraction.
_EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".js": "javascript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
}

# ---------------------------------------------------------------------------
# Module-level store reference (set during app startup)
# ---------------------------------------------------------------------------

_knowledge_store: KnowledgeStore | None = None


def configure_store(store: KnowledgeStore) -> None:
    """Configure the module-level KnowledgeStore reference.

    Called during FastAPI app startup to wire the store instance into the
    router's endpoint handlers.
    """
    global _knowledge_store
    _knowledge_store = store


def _get_store() -> KnowledgeStore:
    """Return the configured KnowledgeStore or raise 503 if not initialized."""
    if _knowledge_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Knowledge Store is not initialized.",
        )
    return _knowledge_store


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class DocumentUploadResponse(BaseModel):
    """Response body for a successful document upload."""

    document_id: str
    chunk_count: int
    namespace: tuple[str, str]


class UploadErrorResponse(BaseModel):
    """Response body for upload validation or extraction errors."""

    detail: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_file_extension(filename: str | None) -> str | None:
    """Extract the lowercased file extension from a filename."""
    if not filename:
        return None
    dot_idx = filename.rfind(".")
    if dot_idx == -1:
        return None
    return filename[dot_idx:].lower()


def _extract_content(file_content: bytes, extension: str) -> str:
    """Extract text content from file bytes based on extension.

    Raises ExtractionError on failure.
    """
    if extension == ".pdf":
        return extract_pdf(file_content)

    # All other supported formats are text-based.
    try:
        text = file_content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExtractionError(
            f"Failed to decode file as UTF-8: {exc}"
        ) from exc

    return text


def _chunk_content(text: str, extension: str) -> list[Chunk]:
    """Chunk extracted text using the appropriate strategy for the file type."""
    if extension == ".md":
        sections = extract_markdown(text)
        return chunk_markdown(sections)

    if extension in _EXTENSION_TO_LANGUAGE:
        language = _EXTENSION_TO_LANGUAGE[extension]
        blocks = extract_code(text, language)
        return chunk_code(blocks)

    # PDF or fallback: plain text chunking.
    return chunk_text(text)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

knowledge_router = APIRouter(
    prefix="/v1/knowledge",
    tags=["knowledge"],
    dependencies=[Depends(get_authenticated_requester)],
)


@knowledge_router.post(
    "/documents",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentUploadResponse,
    responses={
        413: {"model": UploadErrorResponse, "description": "File too large"},
        415: {"model": UploadErrorResponse, "description": "Unsupported file format"},
        422: {"model": UploadErrorResponse, "description": "Extraction failure"},
    },
)
async def upload_document(
    ctx: Annotated[RequesterContext, Depends(get_authenticated_requester)],
    file: Annotated[UploadFile, File(...)],
    target_role: Annotated[str, Form(...)],
) -> DocumentUploadResponse:
    """Upload a document to the Knowledge Base.

    Accepts multipart form data with:
    - ``file``: The document file (PDF, .md, or code file).
    - ``target_role``: The agent role namespace to store the document in.

    The tenant_id is extracted from the authenticated ``X-Tenant-Id`` header.

    Documents are stored in namespace ``(tenant_id, target_role)``.
    """
    store = _get_store()
    tenant_id = ctx.tenant_id

    # --- Validate file extension (Req 3.2) ---
    extension = _get_file_extension(file.filename)
    if extension is None or extension not in _ALLOWED_EXTENSIONS:
        supported = ", ".join(sorted(_ALLOWED_EXTENSIONS))
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Unsupported file format: '{extension or 'unknown'}'. "
                f"Supported formats: {supported}."
            ),
        )

    # --- Read file content ---
    file_content = await file.read()

    # --- Validate file size (Req 3.8) ---
    if len(file_content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"File size ({len(file_content)} bytes) exceeds the maximum "
                f"allowed size of {MAX_FILE_SIZE_BYTES} bytes (10 MB)."
            ),
        )

    # --- Extract text (Req 3.9) ---
    try:
        text = _extract_content(file_content, extension)
    except ExtractionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Text extraction failed: {exc}",
        ) from exc

    if not text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Extracted text is empty. The file may contain no readable content.",
        )

    # --- Chunk content (Req 3.3, 3.6, 3.7) ---
    chunks = _chunk_content(text, extension)
    if not chunks:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Chunking produced no output. The file may contain no processable content.",
        )

    # --- Store documents in namespace (Req 3.10) ---
    namespace = (tenant_id, target_role)
    document_id = str(uuid.uuid4())
    file_type = _EXTENSION_TO_TYPE[extension]
    now = datetime.now(UTC)
    total_chunks = len(chunks)

    for chunk in chunks:
        chunk_key = f"{document_id}:{chunk.chunk_index}"
        metadata = DocumentMetadata(
            source_filename=file.filename or "unknown",
            upload_timestamp=now,
            file_type=file_type,  # type: ignore[arg-type]
            chunk_index=chunk.chunk_index,
            total_chunks=total_chunks,
            uploader_id=ctx.requester_id,
            token_count=chunk.token_count,
        )
        doc = Document(
            document_id=document_id,
            namespace=namespace,
            key=chunk_key,
            content=chunk.content,
            embedding=None,
            metadata=metadata,
        )
        await store.put(namespace=namespace, key=chunk_key, document=doc)

    logger.info(
        "Document uploaded successfully",
        extra={
            "document_id": document_id,
            "namespace": namespace,
            "chunk_count": total_chunks,
            "file_type": file_type,
            "tenant_id": tenant_id,
        },
    )

    return DocumentUploadResponse(
        document_id=document_id,
        chunk_count=total_chunks,
        namespace=namespace,
    )
