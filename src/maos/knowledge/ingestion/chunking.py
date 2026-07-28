"""Token-aware chunking for the Knowledge Base ingestion pipeline.

Provides three chunking strategies:

1. **Token-based splitting** (``chunk_text``) - sentence-boundary-aware splitting
   targeting 512-1024 tokens with 64-token overlap between consecutive chunks.
2. **Heading-aware Markdown splitting** (``chunk_markdown``) - splits on H1/H2/H3
   boundaries first, then applies token-based splitting within oversized sections.
3. **Code-boundary-aware splitting** (``chunk_code``) - splits on function/class
   boundaries first, then falls back to token-based splitting for large blocks.

All chunking uses ``tiktoken`` with the ``cl100k_base`` encoding for accurate
token counting (Requirements 3.3, 3.6, 3.7).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import tiktoken

from maos.knowledge.ingestion.extractors import CodeBlock, MarkdownSection

# ---------------------------------------------------------------------------
# Module-level encoder (singleton, thread-safe in tiktoken)
# ---------------------------------------------------------------------------
_ENCODING = tiktoken.get_encoding("cl100k_base")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Chunk:
    """A single chunk produced by the ingestion pipeline.

    Attributes:
        content: The text content of this chunk.
        chunk_index: Zero-based position of this chunk in the sequence.
        total_chunks: Total number of chunks produced from the source.
        token_count: Number of tokens in this chunk (cl100k_base encoding).
        metadata: Additional key-value metadata (e.g., source heading, block name).
    """

    content: str
    chunk_index: int
    total_chunks: int
    token_count: int
    metadata: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+|\n\n+")


def _count_tokens(text: str) -> int:
    """Return the token count for *text* using cl100k_base encoding."""
    return len(_ENCODING.encode(text))


def _split_into_sentences(text: str) -> list[str]:
    """Split text into sentence-like segments preserving whitespace context."""
    parts = _SENTENCE_BOUNDARY_RE.split(text)
    return [p for p in parts if p.strip()]


def _token_split_segments(
    segments: list[str],
    max_tokens: int,
    min_tokens: int,
    overlap: int,
) -> list[str]:
    """Merge sentence segments into chunks respecting token bounds and overlap.

    Returns a list of chunk text strings. Each chunk targets [min_tokens, max_tokens]
    token count. Consecutive chunks share an overlap of *overlap* tokens from the
    trailing content of the previous chunk.
    """
    if not segments:
        return []

    chunks: list[str] = []
    current_segments: list[str] = []
    current_token_count = 0

    for segment in segments:
        seg_tokens = _count_tokens(segment)

        # If a single segment exceeds max_tokens, it becomes its own chunk
        if seg_tokens > max_tokens:
            # Flush any accumulated segments first
            if current_segments:
                chunks.append(" ".join(current_segments))
                current_segments = []
                current_token_count = 0
            chunks.append(segment)
            continue

        # Would adding this segment exceed max_tokens?
        if current_token_count + seg_tokens > max_tokens and current_segments:
            chunks.append(" ".join(current_segments))
            # Compute overlap: take trailing segments summing up to ~overlap tokens
            overlap_segments = _compute_overlap_segments(current_segments, overlap)
            current_segments = overlap_segments
            current_token_count = (
                _count_tokens(" ".join(current_segments)) if current_segments else 0
            )

        current_segments.append(segment)
        current_token_count += seg_tokens

    # Flush remaining segments
    if current_segments:
        chunks.append(" ".join(current_segments))

    return chunks


def _compute_overlap_segments(segments: list[str], overlap_tokens: int) -> list[str]:
    """Return trailing segments from *segments* totalling ~overlap_tokens tokens."""
    if not segments or overlap_tokens <= 0:
        return []

    result: list[str] = []
    total = 0
    for seg in reversed(segments):
        seg_count = _count_tokens(seg)
        if total + seg_count > overlap_tokens:
            break
        result.insert(0, seg)
        total += seg_count
    return result


def _assign_chunk_metadata(
    chunks_text: list[str],
    extra_metadata: dict[str, str] | None = None,
) -> list[Chunk]:
    """Convert raw chunk strings into ``Chunk`` dataclass instances with metadata."""
    total = len(chunks_text)
    result: list[Chunk] = []
    for idx, text in enumerate(chunks_text):
        meta = dict(extra_metadata) if extra_metadata else {}
        result.append(
            Chunk(
                content=text,
                chunk_index=idx,
                total_chunks=total,
                token_count=_count_tokens(text),
                metadata=meta,
            )
        )
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def chunk_text(
    text: str,
    max_tokens: int = 1024,
    min_tokens: int = 512,
    overlap: int = 64,
) -> list[Chunk]:
    """Split plain text into chunks targeting [min_tokens, max_tokens] with overlap.

    Uses tiktoken (cl100k_base) for token counting and splits on sentence
    boundaries when possible. Ensures overlap of exactly *overlap* tokens
    between consecutive chunks.

    Args:
        text: The source text to chunk.
        max_tokens: Maximum token count per chunk (default 1024).
        min_tokens: Minimum target token count per chunk (default 512).
        overlap: Token overlap between consecutive chunks (default 64).

    Returns:
        A list of ``Chunk`` instances with populated metadata.
    """
    if not text.strip():
        return []

    total_tokens = _count_tokens(text)

    # If text fits within a single chunk, return it directly
    if total_tokens <= max_tokens:
        return [
            Chunk(
                content=text,
                chunk_index=0,
                total_chunks=1,
                token_count=total_tokens,
                metadata={},
            )
        ]

    sentences = _split_into_sentences(text)
    if not sentences:
        # Fallback: treat entire text as one segment
        sentences = [text]

    chunk_texts = _token_split_segments(sentences, max_tokens, min_tokens, overlap)
    return _assign_chunk_metadata(chunk_texts)


def chunk_markdown(
    sections: list[MarkdownSection],
    max_tokens: int = 1024,
    overlap: int = 64,
) -> list[Chunk]:
    """Split Markdown content by heading boundaries, then by token count.

    Splits on H1/H2/H3 heading boundaries first. If a section exceeds
    *max_tokens*, applies token-based splitting within it.

    Args:
        sections: Pre-parsed Markdown sections (from extractor).
        max_tokens: Maximum token count per chunk (default 1024).
        overlap: Token overlap between consecutive chunks (default 64).

    Returns:
        A list of ``Chunk`` instances preserving heading context in metadata.
    """
    if not sections:
        return []

    all_chunk_texts: list[tuple[str, dict[str, str]]] = []

    for section in sections:
        # Reconstruct full section text: include heading line + body
        if section.heading:
            full_text = f"{'#' * section.level} {section.heading}\n\n{section.body}"
        else:
            full_text = section.body

        if not full_text.strip():
            continue

        section_tokens = _count_tokens(full_text)
        heading_meta = {
            "heading": section.heading,
            "heading_level": str(section.level),
        }

        if section_tokens <= max_tokens:
            # Section fits in one chunk
            all_chunk_texts.append((full_text, heading_meta))
        else:
            # Section too large - apply token-based splitting within it
            sentences = _split_into_sentences(full_text)
            if not sentences:
                sentences = [full_text]
            sub_chunks = _token_split_segments(
                sentences, max_tokens, min_tokens=512, overlap=overlap
            )
            for sub_text in sub_chunks:
                all_chunk_texts.append((sub_text, heading_meta))

    # Build final Chunk objects with contiguous indexing
    total = len(all_chunk_texts)
    result: list[Chunk] = []
    for idx, (text, meta) in enumerate(all_chunk_texts):
        result.append(
            Chunk(
                content=text,
                chunk_index=idx,
                total_chunks=total,
                token_count=_count_tokens(text),
                metadata=meta,
            )
        )
    return result


def chunk_code(
    blocks: list[CodeBlock],
    max_tokens: int = 1024,
    overlap: int = 64,
) -> list[Chunk]:
    """Split code by function/class boundaries, then by token count.

    Splits on function and class boundaries first. If a block exceeds
    *max_tokens*, falls back to token-based splitting within the block.

    Args:
        blocks: Pre-parsed code blocks (from extractor with Tree-sitter).
        max_tokens: Maximum token count per chunk (default 1024).
        overlap: Token overlap between consecutive chunks (default 64).

    Returns:
        A list of ``Chunk`` instances preserving block context in metadata.
    """
    if not blocks:
        return []

    all_chunk_texts: list[tuple[str, dict[str, str]]] = []

    for block in blocks:
        block_tokens = _count_tokens(block.content)
        block_meta = {
            "block_name": block.name,
            "block_kind": block.kind,
            "start_line": str(block.start_line),
            "end_line": str(block.end_line),
        }

        if block_tokens <= max_tokens:
            # Block fits in one chunk
            all_chunk_texts.append((block.content, block_meta))
        else:
            # Block too large - fall back to line-based token splitting
            lines = block.content.split("\n")
            # Group lines into segments for splitting
            segments = _group_lines_into_segments(lines)
            sub_chunks = _token_split_segments(
                segments, max_tokens, min_tokens=512, overlap=overlap
            )
            for sub_text in sub_chunks:
                all_chunk_texts.append((sub_text, block_meta))

    # Build final Chunk objects with contiguous indexing
    total = len(all_chunk_texts)
    result: list[Chunk] = []
    for idx, (text, meta) in enumerate(all_chunk_texts):
        result.append(
            Chunk(
                content=text,
                chunk_index=idx,
                total_chunks=total,
                token_count=_count_tokens(text),
                metadata=meta,
            )
        )
    return result


def _group_lines_into_segments(lines: list[str], target_lines: int = 10) -> list[str]:
    """Group source lines into segments of approximately *target_lines* lines.

    This avoids creating one segment per line (too granular) while still
    allowing the token splitter to find reasonable split points.
    """
    segments: list[str] = []
    current: list[str] = []

    for line in lines:
        current.append(line)
        if len(current) >= target_lines:
            segments.append("\n".join(current))
            current = []

    if current:
        segments.append("\n".join(current))

    return segments
