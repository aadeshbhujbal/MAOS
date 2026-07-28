"""Code Intelligence — Tree-sitter parsing for multi-language AST extraction.

This module provides the ``CodeParser`` class that uses Tree-sitter to parse
source files across six languages (Python, TypeScript, JavaScript, Java, Go,
Rust) and extract structural entities: function definitions, class definitions,
import statements, method signatures, and call relationships.

Implements Requirements 22.1, 22.2, 22.6:
- Multi-language AST parsing via Tree-sitter
- Extraction of functions, classes, imports, methods, calls
- < 200 ms per file (up to 5000 lines)
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel
from tree_sitter import Language, Parser, Query, QueryCursor

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

EntityType = Literal["function", "class", "method", "import", "call"]


class ParsedEntity(BaseModel):
    """A code entity extracted from a source file via Tree-sitter AST parsing."""

    name: str
    entity_type: EntityType
    file_path: str
    start_line: int
    end_line: int
    language: str
    signature: str  # function signature or class declaration line
    body: str  # full source code of the entity


# ---------------------------------------------------------------------------
# Language grammars — loaded lazily and cached
# ---------------------------------------------------------------------------

_LANGUAGE_CACHE: dict[str, Language] = {}

# Map file extensions to canonical language names
EXTENSION_MAP: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
}


def _load_language(lang: str) -> Language:
    """Load a Tree-sitter Language, caching after first load."""
    if lang in _LANGUAGE_CACHE:
        return _LANGUAGE_CACHE[lang]

    if lang == "python":
        import tree_sitter_python as ts_py  # type: ignore[import-untyped]

        language = Language(ts_py.language())
    elif lang == "typescript":
        import tree_sitter_typescript as ts_ts  # type: ignore[import-untyped]

        language = Language(ts_ts.language_typescript())
    elif lang == "javascript":
        import tree_sitter_javascript as ts_js  # type: ignore[import-untyped]

        language = Language(ts_js.language())
    elif lang == "java":
        import tree_sitter_java as ts_java  # type: ignore[import-untyped]

        language = Language(ts_java.language())
    elif lang == "go":
        import tree_sitter_go as ts_go  # type: ignore[import-untyped]

        language = Language(ts_go.language())
    elif lang == "rust":
        import tree_sitter_rust as ts_rust  # type: ignore[import-untyped]

        language = Language(ts_rust.language())
    else:
        msg = f"Unsupported language: {lang}"
        raise ValueError(msg)

    _LANGUAGE_CACHE[lang] = language
    return language


# ---------------------------------------------------------------------------
# Tree-sitter query patterns per language
# ---------------------------------------------------------------------------

_PYTHON_QUERIES = """
(function_definition
  name: (identifier) @function.name) @function.def

(class_definition
  name: (identifier) @class.name) @class.def

(import_statement) @import.stmt
(import_from_statement) @import.stmt

(call
  function: (identifier) @call.name) @call.expr

(call
  function: (attribute
    attribute: (identifier) @call.name)) @call.expr
"""

_TYPESCRIPT_QUERIES = """
(function_declaration
  name: (identifier) @function.name) @function.def

(class_declaration
  name: (type_identifier) @class.name) @class.def

(method_definition
  name: (property_identifier) @method.name) @method.def

(import_statement) @import.stmt

(call_expression
  function: (identifier) @call.name) @call.expr

(call_expression
  function: (member_expression
    property: (property_identifier) @call.name)) @call.expr
"""

_JAVASCRIPT_QUERIES = """
(function_declaration
  name: (identifier) @function.name) @function.def

(class_declaration
  name: (identifier) @class.name) @class.def

(method_definition
  name: (property_identifier) @method.name) @method.def

(import_statement) @import.stmt

(call_expression
  function: (identifier) @call.name) @call.expr

(call_expression
  function: (member_expression
    property: (property_identifier) @call.name)) @call.expr
"""

_JAVA_QUERIES = """
(method_declaration
  name: (identifier) @function.name) @function.def

(class_declaration
  name: (identifier) @class.name) @class.def

(import_declaration) @import.stmt

(method_invocation
  name: (identifier) @call.name) @call.expr
"""

_GO_QUERIES = """
(function_declaration
  name: (identifier) @function.name) @function.def

(method_declaration
  name: (field_identifier) @method.name) @method.def

(type_declaration
  (type_spec
    name: (type_identifier) @class.name)) @class.def

(import_declaration) @import.stmt

(call_expression
  function: (identifier) @call.name) @call.expr

(call_expression
  function: (selector_expression
    field: (field_identifier) @call.name)) @call.expr
"""

_RUST_QUERIES = """
(function_item
  name: (identifier) @function.name) @function.def

(struct_item
  name: (type_identifier) @class.name) @class.def

(impl_item
  type: (type_identifier) @class.name) @class.def

(use_declaration) @import.stmt

(call_expression
  function: (identifier) @call.name) @call.expr

(call_expression
  function: (field_expression
    field: (field_identifier) @call.name)) @call.expr
"""

_QUERY_MAP: dict[str, str] = {
    "python": _PYTHON_QUERIES,
    "typescript": _TYPESCRIPT_QUERIES,
    "javascript": _JAVASCRIPT_QUERIES,
    "java": _JAVA_QUERIES,
    "go": _GO_QUERIES,
    "rust": _RUST_QUERIES,
}

# Cache compiled queries per language
_QUERY_CACHE: dict[str, Query] = {}


def _get_query(lang: str) -> Query:
    """Get (or compile and cache) the Tree-sitter Query for a language."""
    if lang in _QUERY_CACHE:
        return _QUERY_CACHE[lang]

    language = _load_language(lang)
    query_src = _QUERY_MAP[lang]
    query = Query(language, query_src)
    _QUERY_CACHE[lang] = query
    return query


# ---------------------------------------------------------------------------
# CodeParser
# ---------------------------------------------------------------------------


class CodeParser:
    """Multi-language code parser using Tree-sitter for AST extraction.

    Supports Python, TypeScript, JavaScript, Java, Go, and Rust.
    Extracts function definitions, class definitions, import statements,
    method signatures, and call relationships.

    Language grammars are loaded lazily and cached after first use.
    """

    def supported_languages(self) -> list[str]:
        """Return the list of supported language identifiers."""
        return ["python", "typescript", "javascript", "java", "go", "rust"]

    def detect_language(self, file_path: str) -> str | None:
        """Detect language from file extension. Returns None if unsupported."""
        _, ext = os.path.splitext(file_path)
        return EXTENSION_MAP.get(ext.lower())

    def parse_file(
        self, content: str, language: str, file_path: str
    ) -> list[ParsedEntity]:
        """Parse source code and extract structural entities.

        Args:
            content: Source code as a string.
            language: One of the supported language identifiers.
            file_path: Path to the source file (stored in extracted entities).

        Returns:
            List of ParsedEntity objects extracted from the AST.

        Raises:
            ValueError: If the language is not supported.
        """
        if language not in _QUERY_MAP:
            msg = f"Unsupported language: {language}"
            raise ValueError(msg)

        lang_obj = _load_language(language)
        parser = Parser(lang_obj)
        source_bytes = content.encode("utf-8")
        tree = parser.parse(source_bytes)

        query = _get_query(language)
        cursor = QueryCursor(query)
        captures = cursor.captures(tree.root_node)

        entities: list[ParsedEntity] = []
        source_lines = content.split("\n")

        # Process function definitions
        entities.extend(
            self._extract_functions(captures, source_bytes, source_lines, file_path, language)
        )

        # Process class definitions
        entities.extend(
            self._extract_classes(captures, source_bytes, source_lines, file_path, language)
        )

        # Process method definitions (TypeScript, JavaScript, Go)
        entities.extend(
            self._extract_methods(captures, source_bytes, source_lines, file_path, language)
        )

        # Process import statements
        entities.extend(
            self._extract_imports(captures, source_bytes, source_lines, file_path, language)
        )

        # Process call expressions
        entities.extend(
            self._extract_calls(captures, source_bytes, source_lines, file_path, language)
        )

        return entities

    def _extract_functions(
        self,
        captures: dict[str, list],  # type: ignore[type-arg]
        source_bytes: bytes,
        source_lines: list[str],
        file_path: str,
        language: str,
    ) -> list[ParsedEntity]:
        """Extract function definition entities from captures."""
        entities: list[ParsedEntity] = []
        func_defs = captures.get("function.def", [])
        func_names = captures.get("function.name", [])

        for i, node in enumerate(func_defs):
            name = ""
            if i < len(func_names):
                name = source_bytes[
                    func_names[i].start_byte : func_names[i].end_byte
                ].decode("utf-8")

            start_line = node.start_point[0] + 1  # 1-indexed
            end_line = node.end_point[0] + 1
            body = source_bytes[node.start_byte : node.end_byte].decode("utf-8")

            # Signature is the first line of the definition
            signature = (
                source_lines[start_line - 1].strip()
                if start_line <= len(source_lines)
                else ""
            )

            entities.append(
                ParsedEntity(
                    name=name,
                    entity_type="function",
                    file_path=file_path,
                    start_line=start_line,
                    end_line=end_line,
                    language=language,
                    signature=signature,
                    body=body,
                )
            )

        return entities

    def _extract_classes(
        self,
        captures: dict[str, list],  # type: ignore[type-arg]
        source_bytes: bytes,
        source_lines: list[str],
        file_path: str,
        language: str,
    ) -> list[ParsedEntity]:
        """Extract class definition entities from captures."""
        entities: list[ParsedEntity] = []
        class_defs = captures.get("class.def", [])
        class_names = captures.get("class.name", [])

        for i, node in enumerate(class_defs):
            name = ""
            if i < len(class_names):
                name = source_bytes[
                    class_names[i].start_byte : class_names[i].end_byte
                ].decode("utf-8")

            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            body = source_bytes[node.start_byte : node.end_byte].decode("utf-8")
            signature = (
                source_lines[start_line - 1].strip()
                if start_line <= len(source_lines)
                else ""
            )

            entities.append(
                ParsedEntity(
                    name=name,
                    entity_type="class",
                    file_path=file_path,
                    start_line=start_line,
                    end_line=end_line,
                    language=language,
                    signature=signature,
                    body=body,
                )
            )

        return entities

    def _extract_methods(
        self,
        captures: dict[str, list],  # type: ignore[type-arg]
        source_bytes: bytes,
        source_lines: list[str],
        file_path: str,
        language: str,
    ) -> list[ParsedEntity]:
        """Extract method definition entities from captures."""
        entities: list[ParsedEntity] = []
        method_defs = captures.get("method.def", [])
        method_names = captures.get("method.name", [])

        for i, node in enumerate(method_defs):
            name = ""
            if i < len(method_names):
                name = source_bytes[
                    method_names[i].start_byte : method_names[i].end_byte
                ].decode("utf-8")

            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            body = source_bytes[node.start_byte : node.end_byte].decode("utf-8")
            signature = (
                source_lines[start_line - 1].strip()
                if start_line <= len(source_lines)
                else ""
            )

            entities.append(
                ParsedEntity(
                    name=name,
                    entity_type="method",
                    file_path=file_path,
                    start_line=start_line,
                    end_line=end_line,
                    language=language,
                    signature=signature,
                    body=body,
                )
            )

        return entities

    def _extract_imports(
        self,
        captures: dict[str, list],  # type: ignore[type-arg]
        source_bytes: bytes,
        source_lines: list[str],
        file_path: str,
        language: str,
    ) -> list[ParsedEntity]:
        """Extract import statement entities from captures."""
        entities: list[ParsedEntity] = []
        import_stmts = captures.get("import.stmt", [])

        for node in import_stmts:
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            body = source_bytes[node.start_byte : node.end_byte].decode("utf-8")
            signature = body.strip().split("\n")[0]

            # Extract a meaningful name from the import
            name = self._import_name(body, language)

            entities.append(
                ParsedEntity(
                    name=name,
                    entity_type="import",
                    file_path=file_path,
                    start_line=start_line,
                    end_line=end_line,
                    language=language,
                    signature=signature,
                    body=body,
                )
            )

        return entities

    def _extract_calls(
        self,
        captures: dict[str, list],  # type: ignore[type-arg]
        source_bytes: bytes,
        source_lines: list[str],
        file_path: str,
        language: str,
    ) -> list[ParsedEntity]:
        """Extract call expression entities from captures."""
        entities: list[ParsedEntity] = []
        call_exprs = captures.get("call.expr", [])
        call_names = captures.get("call.name", [])

        for i, node in enumerate(call_exprs):
            name = ""
            if i < len(call_names):
                name = source_bytes[
                    call_names[i].start_byte : call_names[i].end_byte
                ].decode("utf-8")

            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            body = source_bytes[node.start_byte : node.end_byte].decode("utf-8")
            signature = body.strip().split("\n")[0]

            entities.append(
                ParsedEntity(
                    name=name,
                    entity_type="call",
                    file_path=file_path,
                    start_line=start_line,
                    end_line=end_line,
                    language=language,
                    signature=signature,
                    body=body,
                )
            )

        return entities

    @staticmethod
    def _import_name(body: str, language: str) -> str:
        """Extract a canonical name from an import statement."""
        body = body.strip()
        if language == "python":
            # "from foo.bar import baz" -> "foo.bar"
            # "import foo.bar" -> "foo.bar"
            if body.startswith("from "):
                parts = body.split()
                return parts[1] if len(parts) >= 2 else body
            if body.startswith("import "):
                parts = body.split()
                return parts[1].rstrip(",") if len(parts) >= 2 else body
        elif language in ("typescript", "javascript"):
            # import X from 'module' -> module
            if "from" in body:
                parts = body.split("from")
                module = parts[-1].strip().strip("'\"`;")
                return module
            return body.split()[1] if len(body.split()) > 1 else body
        elif language == "java":
            # import com.foo.Bar; -> com.foo.Bar
            parts = body.replace(";", "").split()
            return parts[-1] if parts else body
        elif language == "go":
            # import "fmt" or import ( "fmt" ... )
            # Simple heuristic: grab quoted strings
            import re

            matches = re.findall(r'"([^"]+)"', body)
            return matches[0] if matches else body
        elif language == "rust":
            # use std::collections::HashMap; -> std::collections::HashMap
            parts = body.replace(";", "").split()
            return parts[-1] if len(parts) >= 2 else body

        return body
