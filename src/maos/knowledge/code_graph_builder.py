"""Code Graph Builder — Build and incrementally update code graphs from AST.

This module provides the ``CodeGraphBuilder`` class that constructs a knowledge
graph from Tree-sitter parsed AST entities. It creates nodes for each code entity
and edges for CALLS, IMPORTS, INHERITS, and IMPLEMENTS relationships. Supports
incremental re-parsing on git commit (only modified files), circular dependency
detection, and maintains a symbol index mapping fully qualified names to file
locations.

Implements Requirements 22.3, 22.4, 22.7, 22.8:
- Build code graph from parsed AST: nodes per entity, edges for relationships
- Incremental re-parsing on git commit (only modified files)
- Detect circular dependencies and add CIRCULAR_DEPENDENCY edges
- Maintain symbol index: fully qualified name → file path + line number
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from maos.knowledge.code_intelligence import CodeParser, ParsedEntity
from maos.knowledge.graph import KnowledgeGraphClient
from maos.knowledge.graph_models import CodeEntity, NodeType, RelationType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Symbol Index
# ---------------------------------------------------------------------------


@dataclass
class SymbolLocation:
    """Location of a symbol in the codebase."""

    file_path: str
    line_number: int
    entity_type: str
    language: str


class SymbolIndex:
    """Maps fully qualified names to file path + line number (Req 22.8).

    The index maintains a dictionary of symbol names to their source locations,
    enabling fast lookups of where any entity is defined in the codebase.
    """

    def __init__(self) -> None:
        self._index: dict[str, SymbolLocation] = {}

    def add(
        self,
        fully_qualified_name: str,
        file_path: str,
        line_number: int,
        entity_type: str,
        language: str,
    ) -> None:
        """Register a symbol in the index."""
        self._index[fully_qualified_name] = SymbolLocation(
            file_path=file_path,
            line_number=line_number,
            entity_type=entity_type,
            language=language,
        )

    def lookup(self, fully_qualified_name: str) -> SymbolLocation | None:
        """Look up a symbol by fully qualified name. Returns None if not found."""
        return self._index.get(fully_qualified_name)

    def remove_file(self, file_path: str) -> int:
        """Remove all symbols from a given file. Returns count of removed entries."""
        to_remove = [
            name
            for name, loc in self._index.items()
            if loc.file_path == file_path
        ]
        for name in to_remove:
            del self._index[name]
        return len(to_remove)

    def all_symbols(self) -> dict[str, SymbolLocation]:
        """Return a copy of the full symbol index."""
        return dict(self._index)

    def __len__(self) -> int:
        return len(self._index)


# ---------------------------------------------------------------------------
# Entity-to-NodeType classification
# ---------------------------------------------------------------------------


def _classify_node_type(entity: ParsedEntity) -> NodeType:
    """Classify a parsed entity into a Knowledge Graph NodeType.

    Heuristic classification based on entity type and naming conventions:
    - Classes ending with 'Controller' -> CONTROLLER
    - Classes ending with 'Service' -> SERVICE
    - Classes ending with 'Repository'/'Repo' -> REPOSITORY
    - Classes ending with 'Test'/'Tests'/'Spec' -> TEST_SUITE
    - Classes ending with 'Component'/'Widget' -> FRONTEND_COMPONENT
    - Classes ending with 'Screen'/'Activity' -> MOBILE_SCREEN
    - Anything else defaults to SERVICE for classes, SERVICE for functions
    """
    name = entity.name
    if entity.entity_type == "class":
        if name.endswith("Controller") or name.endswith("Handler"):
            return NodeType.CONTROLLER
        if name.endswith("Repository") or name.endswith("Repo"):
            return NodeType.REPOSITORY
        if name.endswith("Test") or name.endswith("Tests") or name.endswith("Spec"):
            return NodeType.TEST_SUITE
        if name.endswith("Component") or name.endswith("Widget"):
            return NodeType.FRONTEND_COMPONENT
        if name.endswith("Screen") or name.endswith("Activity"):
            return NodeType.MOBILE_SCREEN
        return NodeType.SERVICE
    # Functions and methods default to SERVICE
    return NodeType.SERVICE


# ---------------------------------------------------------------------------
# Fully Qualified Name helpers
# ---------------------------------------------------------------------------


def _compute_module(file_path: str, repo_root: str) -> str:
    """Compute a module path from a file path relative to the repo root.

    For example: 'src/maos/knowledge/graph.py' -> 'src.maos.knowledge.graph'
    """
    try:
        relative = Path(file_path).relative_to(Path(repo_root))
    except ValueError:
        relative = Path(file_path)

    # Remove extension and convert path separators to dots
    parts = list(relative.with_suffix("").parts)
    return ".".join(parts)


def _fully_qualified_name(module: str, entity_name: str) -> str:
    """Construct a fully qualified name from module path and entity name."""
    if not entity_name:
        return module
    return f"{module}.{entity_name}"


# ---------------------------------------------------------------------------
# Git integration for incremental updates
# ---------------------------------------------------------------------------


@dataclass
class GitDiff:
    """Result of diffing two git commits."""

    modified_files: list[str] = field(default_factory=list)
    added_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)


def get_modified_files(
    repo_path: str, base_ref: str = "HEAD~1", head_ref: str = "HEAD"
) -> GitDiff:
    """Get files modified between two git commits (Req 22.4).

    Uses ``git diff --name-status`` to determine which files were added,
    modified, or deleted between two refs. Only returns files with supported
    extensions for Tree-sitter parsing.

    Args:
        repo_path: Path to the git repository root.
        base_ref: Base git reference (default HEAD~1).
        head_ref: Head git reference (default HEAD).

    Returns:
        GitDiff with categorized file paths.
    """
    supported_extensions = {".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".go", ".rs"}
    diff = GitDiff()

    try:
        result = subprocess.run(
            ["git", "diff", "--name-status", base_ref, head_ref],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.warning("Failed to get git diff: %s", exc)
        return diff

    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        parts = line.split("\t", maxsplit=1)
        if len(parts) < 2:
            continue

        status, file_path = parts[0], parts[1]
        ext = Path(file_path).suffix.lower()
        if ext not in supported_extensions:
            continue

        if status.startswith("A"):
            diff.added_files.append(file_path)
        elif status.startswith("M"):
            diff.modified_files.append(file_path)
        elif status.startswith("D"):
            diff.deleted_files.append(file_path)

    return diff


# ---------------------------------------------------------------------------
# Code Graph Builder
# ---------------------------------------------------------------------------


class CodeGraphBuilder:
    """Builds and maintains a code knowledge graph from parsed AST entities.

    Uses ``CodeParser`` (Tree-sitter) to parse source files and
    ``KnowledgeGraphClient`` (Neo4j) to store the resulting graph of code
    entities and their relationships.

    Supports:
    - Full repository graph construction
    - Incremental updates based on git diffs (Req 22.4)
    - Circular dependency detection with CIRCULAR_DEPENDENCY edge creation (Req 22.7)
    - Symbol index maintenance for fast lookups (Req 22.8)
    """

    def __init__(
        self,
        graph_client: KnowledgeGraphClient,
        repo_root: str,
        parser: CodeParser | None = None,
    ) -> None:
        self._graph = graph_client
        self._repo_root = repo_root
        self._parser = parser or CodeParser()
        self._symbol_index = SymbolIndex()

    @property
    def symbol_index(self) -> SymbolIndex:
        """Access the symbol index for lookups."""
        return self._symbol_index

    async def build_file(self, file_path: str, content: str) -> list[CodeEntity]:
        """Parse a single file and add its entities/edges to the graph (Req 22.3).

        Args:
            file_path: Path to the source file (relative or absolute).
            content: Source code content of the file.

        Returns:
            List of CodeEntity objects created in the graph.
        """
        language = self._parser.detect_language(file_path)
        if language is None:
            logger.debug("Skipping unsupported file: %s", file_path)
            return []

        entities = self._parser.parse_file(content, language, file_path)
        if not entities:
            return []

        module = _compute_module(file_path, self._repo_root)
        now = datetime.now(UTC)

        created_entities: list[CodeEntity] = []
        # Track entities in this file for relationship building
        functions_and_classes: dict[str, str] = {}  # name -> entity_id
        imports: list[ParsedEntity] = []
        calls: list[ParsedEntity] = []

        # First pass: create nodes for definitions (functions, classes, methods)
        for parsed in entities:
            if parsed.entity_type in ("function", "class", "method"):
                fqn = _fully_qualified_name(module, parsed.name)
                node_type = _classify_node_type(parsed)

                code_entity = CodeEntity(
                    entity_id=fqn,
                    node_type=node_type,
                    file_path=file_path,
                    line_number=parsed.start_line,
                    module=module,
                    language=language,
                    last_updated=now,
                    properties={
                        "signature": parsed.signature,
                        "entity_type": parsed.entity_type,
                    },
                )

                await self._graph.add_entity(code_entity)
                created_entities.append(code_entity)
                functions_and_classes[parsed.name] = fqn

                # Update symbol index
                self._symbol_index.add(
                    fully_qualified_name=fqn,
                    file_path=file_path,
                    line_number=parsed.start_line,
                    entity_type=parsed.entity_type,
                    language=language,
                )

            elif parsed.entity_type == "import":
                imports.append(parsed)
            elif parsed.entity_type == "call":
                calls.append(parsed)

        # Second pass: create IMPORTS edges
        for imp in imports:
            target_module = imp.name  # imported module name

            # Find entities in this file to connect from
            for _entity_name, entity_id in functions_and_classes.items():
                # Create IMPORTS edge from first entity in file to the imported module
                # Use the import name as the target entity_id
                await self._graph.add_relationship(
                    source_id=entity_id,
                    target_id=target_module,
                    rel_type=RelationType.IMPORTS,
                    metadata={"import_statement": imp.signature},
                )
                break  # Only link from the first entity as module-level import

        # Third pass: create CALLS edges
        for call in calls:
            callee_name = call.name
            # If the callee is defined in this file, create an internal CALLS edge
            if callee_name in functions_and_classes:
                target_id = functions_and_classes[callee_name]
                # Find the closest containing function/class for the caller
                caller_id = self._find_containing_entity(
                    call.start_line, entities, module
                )
                if caller_id and caller_id != target_id:
                    await self._graph.add_relationship(
                        source_id=caller_id,
                        target_id=target_id,
                        rel_type=RelationType.CALLS,
                        metadata={"line": str(call.start_line)},
                    )
            else:
                # External call — create edge to a qualified target
                caller_id = self._find_containing_entity(
                    call.start_line, entities, module
                )
                if caller_id:
                    target_fqn = callee_name  # May resolve later
                    await self._graph.add_relationship(
                        source_id=caller_id,
                        target_id=target_fqn,
                        rel_type=RelationType.CALLS,
                        metadata={"line": str(call.start_line)},
                    )

        # Fourth pass: detect inheritance/implementation from class signatures
        await self._extract_inheritance(entities, module, language)

        return created_entities

    async def build_repository(self, file_paths: list[str]) -> int:
        """Build the full code graph for a list of files.

        Args:
            file_paths: List of file paths to parse and graph.

        Returns:
            Total number of entities created.
        """
        total_entities = 0
        for file_path in file_paths:
            abs_path = Path(self._repo_root) / file_path
            if not abs_path.is_file():
                logger.debug("Skipping non-existent file: %s", file_path)
                continue
            content = abs_path.read_text(encoding="utf-8", errors="replace")
            entities = await self.build_file(file_path, content)
            total_entities += len(entities)
            logger.debug("Processed %s: %d entities", file_path, len(entities))

        logger.info(
            "Repository graph built: %d entities from %d files",
            total_entities,
            len(file_paths),
        )
        return total_entities

    async def incremental_update(
        self, base_ref: str = "HEAD~1", head_ref: str = "HEAD"
    ) -> dict[str, int]:
        """Incrementally update the graph based on git diff (Req 22.4).

        Only re-parses modified and added files, and removes entities for
        deleted files. This avoids rebuilding the entire graph on every commit.

        Args:
            base_ref: Base git reference for the diff.
            head_ref: Head git reference for the diff.

        Returns:
            Summary dict with counts of added, modified, and deleted file updates.
        """
        diff = get_modified_files(self._repo_root, base_ref, head_ref)
        summary = {"added": 0, "modified": 0, "deleted": 0}

        # Handle deleted files: remove their entities from the graph and index
        for file_path in diff.deleted_files:
            removed = self._symbol_index.remove_file(file_path)
            summary["deleted"] += removed
            logger.info("Removed %d entities for deleted file: %s", removed, file_path)

        # Handle modified files: remove old entities, re-parse
        for file_path in diff.modified_files:
            self._symbol_index.remove_file(file_path)
            abs_path = Path(self._repo_root) / file_path
            if abs_path.is_file():
                content = abs_path.read_text(encoding="utf-8", errors="replace")
                entities = await self.build_file(file_path, content)
                summary["modified"] += len(entities)
                logger.debug(
                    "Re-parsed modified file %s: %d entities", file_path, len(entities)
                )

        # Handle added files: parse fresh
        for file_path in diff.added_files:
            abs_path = Path(self._repo_root) / file_path
            if abs_path.is_file():
                content = abs_path.read_text(encoding="utf-8", errors="replace")
                entities = await self.build_file(file_path, content)
                summary["added"] += len(entities)
                logger.debug(
                    "Parsed new file %s: %d entities", file_path, len(entities)
                )

        logger.info(
            "Incremental update complete: added=%d, modified=%d, deleted=%d",
            summary["added"],
            summary["modified"],
            summary["deleted"],
        )
        return summary

    async def detect_and_mark_circular_dependencies(
        self, module_scope: str
    ) -> list[list[str]]:
        """Detect circular dependencies and add CIRCULAR_DEPENDENCY edges (Req 22.7).

        Queries the graph for cycles within the given module scope, then creates
        CIRCULAR_DEPENDENCY edges between the involved entities to make cycles
        explicitly visible in the graph.

        Args:
            module_scope: Module prefix to scope the detection (e.g. 'src.maos').

        Returns:
            List of detected cycles, where each cycle is a list of entity IDs.
        """
        cycles = await self._graph.detect_circular_deps(module_scope)

        if not cycles:
            logger.info("No circular dependencies found in scope: %s", module_scope)
            return []

        # Add CIRCULAR_DEPENDENCY edges for each detected cycle
        for cycle in cycles:
            if len(cycle) < 2:
                continue
            # Create an edge from the last entity back to the first
            # to explicitly mark the cycle
            await self._graph.add_relationship(
                source_id=cycle[-2],  # Second-to-last (before the repeated start)
                target_id=cycle[0],
                rel_type=RelationType.CIRCULAR_DEPENDENCY,
                metadata={
                    "cycle_length": str(len(cycle) - 1),
                    "cycle_entities": ",".join(cycle[:-1]),
                    "detected_at": datetime.now(UTC).isoformat(),
                },
            )

        logger.warning(
            "Detected %d circular dependencies in scope '%s'",
            len(cycles),
            module_scope,
        )
        return cycles

    def _find_containing_entity(
        self,
        line: int,
        entities: list[ParsedEntity],
        module: str,
    ) -> str | None:
        """Find the entity that contains the given line number.

        Returns the fully qualified name of the smallest enclosing
        function/class/method at the given line, or None.
        """
        best_match: ParsedEntity | None = None
        best_size = float("inf")

        for entity in entities:
            if entity.entity_type not in ("function", "class", "method"):
                continue
            if entity.start_line <= line <= entity.end_line:
                size = entity.end_line - entity.start_line
                if size < best_size:
                    best_size = size
                    best_match = entity

        if best_match:
            return _fully_qualified_name(module, best_match.name)
        return None

    async def _extract_inheritance(
        self,
        entities: list[ParsedEntity],
        module: str,
        language: str,
    ) -> None:
        """Extract INHERITS and IMPLEMENTS edges from class signatures.

        Parses class definition signatures to detect inheritance patterns:
        - Python: class Foo(Bar, ABC) or class Foo(BaseClass)
        - Java: class Foo extends Bar implements Baz
        - TypeScript: class Foo extends Bar implements IBaz
        - Rust: impl Trait for Struct
        """
        for entity in entities:
            if entity.entity_type != "class":
                continue

            fqn = _fully_qualified_name(module, entity.name)
            parents = self._parse_inheritance(entity.signature, language)

            for parent_name, rel_type in parents:
                await self._graph.add_relationship(
                    source_id=fqn,
                    target_id=parent_name,
                    rel_type=rel_type,
                    metadata={"language": language},
                )

    @staticmethod
    def _parse_inheritance(
        signature: str, language: str
    ) -> list[tuple[str, RelationType]]:
        """Parse a class signature to extract parent classes and interfaces.

        Returns a list of (parent_name, relationship_type) tuples.
        """
        results: list[tuple[str, RelationType]] = []

        if language == "python":
            # class Foo(Bar, Baz):
            import re

            match = re.search(r"class\s+\w+\s*\(([^)]+)\)", signature)
            if match:
                parents_str = match.group(1)
                for parent in parents_str.split(","):
                    parent = parent.strip()
                    if parent and parent not in ("ABC", "object", "BaseModel"):
                        results.append((parent, RelationType.INHERITS))

        elif language in ("typescript", "javascript"):
            # class Foo extends Bar implements IBaz, IQux
            import re

            extends_match = re.search(r"extends\s+([\w.]+)", signature)
            if extends_match:
                results.append((extends_match.group(1), RelationType.INHERITS))

            implements_match = re.search(r"implements\s+(.+?)(?:\{|$)", signature)
            if implements_match:
                for iface in implements_match.group(1).split(","):
                    iface = iface.strip()
                    if iface:
                        results.append((iface, RelationType.IMPLEMENTS))

        elif language == "java":
            # class Foo extends Bar implements Baz, Qux
            import re

            extends_match = re.search(r"extends\s+([\w.]+)", signature)
            if extends_match:
                results.append((extends_match.group(1), RelationType.INHERITS))

            implements_match = re.search(r"implements\s+(.+?)(?:\{|$)", signature)
            if implements_match:
                for iface in implements_match.group(1).split(","):
                    iface = iface.strip()
                    if iface:
                        results.append((iface, RelationType.IMPLEMENTS))

        elif language == "rust":
            # impl Trait for Struct
            import re

            impl_match = re.search(r"impl\s+([\w:]+)\s+for\s+([\w:]+)", signature)
            if impl_match:
                results.append((impl_match.group(1), RelationType.IMPLEMENTS))

        elif language == "go":
            # Go uses structural typing — no explicit inheritance in signatures
            pass

        return results
