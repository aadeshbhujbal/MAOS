"""Text extraction for the ingestion pipeline (Req 3.2, 3.5, 3.6, 3.7, 3.9).

This module provides extractors for:

- **PDF** — via PyPDF2, preserving paragraph structure.
- **Markdown** — splitting on heading boundaries (H1/H2/H3).
- **Code files** — using Tree-sitter to detect function/class boundaries.

All extractors raise ``ExtractionError`` on failure with a descriptive message
identifying the failure reason.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

import PyPDF2
import tree_sitter
import tree_sitter_go
import tree_sitter_java
import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_rust
import tree_sitter_typescript

# ---------------------------------------------------------------------------
# Public data structures
# ---------------------------------------------------------------------------


class ExtractionError(Exception):
    """Raised when text extraction fails for a given file."""


@dataclass
class MarkdownSection:
    """A section of a Markdown document split on heading boundaries."""

    heading: str
    level: int
    body: str


@dataclass
class CodeBlock:
    """A function or class boundary detected via Tree-sitter."""

    name: str
    kind: str  # "function" | "class"
    start_line: int
    end_line: int
    content: str


# ---------------------------------------------------------------------------
# Language → Tree-sitter parser mapping
# ---------------------------------------------------------------------------

_LANGUAGE_MAP: dict[str, object] = {
    "python": tree_sitter_python.language(),
    "javascript": tree_sitter_javascript.language(),
    "typescript": tree_sitter_typescript.language_typescript(),
    "java": tree_sitter_java.language(),
    "go": tree_sitter_go.language(),
    "rust": tree_sitter_rust.language(),
}

# Tree-sitter node types that represent function/class boundaries per language.
_FUNCTION_NODE_TYPES: dict[str, list[str]] = {
    "python": ["function_definition", "class_definition"],
    "javascript": [
        "function_declaration", "class_declaration", "arrow_function", "method_definition",
    ],
    "typescript": [
        "function_declaration", "class_declaration", "arrow_function", "method_definition",
    ],
    "java": ["method_declaration", "class_declaration", "interface_declaration"],
    "go": ["function_declaration", "method_declaration", "type_declaration"],
    "rust": ["function_item", "impl_item", "struct_item", "enum_item", "trait_item"],
}


# ---------------------------------------------------------------------------
# PDF extraction (Req 3.5)
# ---------------------------------------------------------------------------


def extract_pdf(file_content: bytes) -> str:
    """Extract text from a PDF preserving paragraph structure.

    Parameters
    ----------
    file_content:
        Raw bytes of the PDF file.

    Returns
    -------
    str
        Extracted text with paragraphs separated by double newlines.

    Raises
    ------
    ExtractionError
        If the PDF is corrupt or cannot be read.
    """
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(file_content))
    except Exception as exc:
        raise ExtractionError(
            f"Failed to read PDF: {exc}. The file may be corrupt or not a valid PDF."
        ) from exc

    pages: list[str] = []
    for page_num, page in enumerate(reader.pages):
        try:
            text = page.extract_text()
            if text:
                pages.append(text.strip())
        except Exception as exc:
            raise ExtractionError(
                f"Failed to extract text from page {page_num + 1}: {exc}"
            ) from exc

    return "\n\n".join(pages)


# ---------------------------------------------------------------------------
# Markdown extraction (Req 3.6)
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)


def extract_markdown(content: str) -> list[MarkdownSection]:
    """Split a Markdown document on H1/H2/H3 heading boundaries.

    Parameters
    ----------
    content:
        Raw Markdown text.

    Returns
    -------
    list[MarkdownSection]
        Sections with heading text, level, and body content.
        If there is content before the first heading it is returned
        with heading="" and level=0.
    """
    sections: list[MarkdownSection] = []
    matches = list(_HEADING_RE.finditer(content))

    if not matches:
        # No headings — return entire content as a single section.
        return [MarkdownSection(heading="", level=0, body=content.strip())]

    # Content before the first heading.
    preamble = content[: matches[0].start()].strip()
    if preamble:
        sections.append(MarkdownSection(heading="", level=0, body=preamble))

    for i, match in enumerate(matches):
        level = len(match.group(1))
        heading = match.group(2).strip()

        # Body extends from after this heading to start of the next heading.
        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[body_start:body_end].strip()

        sections.append(MarkdownSection(heading=heading, level=level, body=body))

    return sections


# ---------------------------------------------------------------------------
# Code extraction via Tree-sitter (Req 3.7)
# ---------------------------------------------------------------------------


def _get_parser(language: str) -> tree_sitter.Parser | None:
    """Return a configured Tree-sitter parser for the given language, or None."""
    lang = _LANGUAGE_MAP.get(language)
    if lang is None:
        return None
    parser = tree_sitter.Parser(lang)  # type: ignore[arg-type]
    return parser


def _extract_name(node: tree_sitter.Node, source_lines: list[str]) -> str:
    """Extract the identifier name from a tree-sitter AST node."""
    # Look for a 'name' or 'identifier' child node.
    for child in node.children:
        if child.type in ("identifier", "name", "type_identifier"):
            return source_lines[child.start_point.row][
                child.start_point.column : child.end_point.column
            ]
    # Fallback: use first line up to a reasonable boundary.
    first_line = source_lines[node.start_point.row][node.start_point.column :]
    return first_line.split("(")[0].split("{")[0].strip()[:60]


def _classify_kind(node_type: str) -> str:
    """Classify a tree-sitter node type as 'function' or 'class'."""
    class_keywords = ("class", "struct", "enum", "interface", "trait", "impl", "type")
    if any(kw in node_type for kw in class_keywords):
        return "class"
    return "function"


def _walk_for_blocks(
    node: tree_sitter.Node,
    target_types: list[str],
    source_lines: list[str],
    all_content: str,
) -> list[CodeBlock]:
    """Recursively walk the AST collecting blocks matching target types."""
    blocks: list[CodeBlock] = []

    if node.type in target_types:
        name = _extract_name(node, source_lines)
        kind = _classify_kind(node.type)
        start_line = node.start_point.row + 1  # 1-indexed
        end_line = node.end_point.row + 1
        content = all_content[node.start_byte : node.end_byte]
        blocks.append(
            CodeBlock(
                name=name,
                kind=kind,
                start_line=start_line,
                end_line=end_line,
                content=content,
            )
        )
    else:
        for child in node.children:
            blocks.extend(_walk_for_blocks(child, target_types, source_lines, all_content))

    return blocks


def extract_code(content: str, language: str) -> list[CodeBlock]:
    """Extract function/class boundaries from source code using Tree-sitter.

    Parameters
    ----------
    content:
        Source code as a string.
    language:
        Programming language identifier (python, javascript, typescript, java, go, rust).

    Returns
    -------
    list[CodeBlock]
        Detected code blocks. If the language is unsupported, falls back to
        returning the entire content as a single block.

    Raises
    ------
    ExtractionError
        If parsing fails due to an internal error.
    """
    parser = _get_parser(language)
    if parser is None:
        # Unsupported language — fallback to raw text as a single block.
        lines = content.splitlines()
        return [
            CodeBlock(
                name="<module>",
                kind="function",
                start_line=1,
                end_line=max(len(lines), 1),
                content=content,
            )
        ]

    try:
        tree = parser.parse(content.encode("utf-8"))
    except Exception as exc:
        raise ExtractionError(
            f"Tree-sitter parsing failed for language '{language}': {exc}"
        ) from exc

    target_types = _FUNCTION_NODE_TYPES.get(language, [])
    source_lines = content.splitlines()
    blocks = _walk_for_blocks(tree.root_node, target_types, source_lines, content)

    # If no blocks detected (e.g., a script with no functions/classes), return the whole file.
    if not blocks:
        return [
            CodeBlock(
                name="<module>",
                kind="function",
                start_line=1,
                end_line=max(len(source_lines), 1),
                content=content,
            )
        ]

    return blocks
