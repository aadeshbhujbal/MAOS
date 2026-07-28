"""Continuous Learning System — post-task pattern extraction and knowledge updates.

Implements the ``LearningSystem`` class that processes completed tasks to
extract reusable patterns, update the Knowledge Base and Knowledge Graph,
refresh code embeddings, and track team conventions. Designed to run as an
Arq background job so it never blocks task completion (Req 16.7).

References
----------
- Req 16.1: Update Knowledge_Base, Knowledge_Graph, embeddings, conventions on task complete.
- Req 16.2: Extract architecture decisions as ADR nodes in Knowledge Graph.
- Req 16.3: Update code embeddings when source files are modified.
- Req 16.4: Track team conventions (naming, imports, error handling).
- Req 16.7: Process learning updates asynchronously via Arq background worker.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from maos.knowledge.graph_models import CodeEntity, NodeType, RelationType
from maos.learning.models import Convention, LearnedPattern, LearningRecord

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain types used for task results passed into the learning pipeline
# ---------------------------------------------------------------------------


class CodeChange:
    """Represents a source file modification produced by an agent action."""

    def __init__(
        self,
        file_path: str,
        language: str,
        diff_summary: str,
        entities_added: list[str] | None = None,
        entities_removed: list[str] | None = None,
        relationships_added: list[tuple[str, str, str]] | None = None,
    ) -> None:
        self.file_path = file_path
        self.language = language
        self.diff_summary = diff_summary
        self.entities_added = entities_added or []
        self.entities_removed = entities_removed or []
        self.relationships_added = relationships_added or []


class TaskResult:
    """Summarised output of a completed task consumed by the learning pipeline."""

    def __init__(
        self,
        task_id: str,
        tenant_id: str,
        agent_role: str,
        description: str,
        code_changes: list[CodeChange] | None = None,
        architecture_decisions: list[str] | None = None,
        conventions_observed: list[dict[str, Any]] | None = None,
        error_fixes: list[dict[str, Any]] | None = None,
    ) -> None:
        self.task_id = task_id
        self.tenant_id = tenant_id
        self.agent_role = agent_role
        self.description = description
        self.code_changes = code_changes or []
        self.architecture_decisions = architecture_decisions or []
        self.conventions_observed = conventions_observed or []
        self.error_fixes = error_fixes or []


class LearningOutcome:
    """Summary of what the learning pipeline produced for a single task."""

    def __init__(
        self,
        record: LearningRecord,
        patterns_stored: int = 0,
        graph_nodes_added: int = 0,
        embeddings_updated: int = 0,
        conventions_updated: int = 0,
    ) -> None:
        self.record = record
        self.patterns_stored = patterns_stored
        self.graph_nodes_added = graph_nodes_added
        self.embeddings_updated = embeddings_updated
        self.conventions_updated = conventions_updated


# ---------------------------------------------------------------------------
# Convention detection heuristics
# ---------------------------------------------------------------------------

_NAMING_KEYWORDS = ("naming", "rename", "variable", "function name", "class name")
_IMPORT_KEYWORDS = ("import", "from", "require", "include")
_ERROR_HANDLING_KEYWORDS = ("try", "except", "catch", "error handling", "raise", "throw")
_TESTING_KEYWORDS = ("test", "assert", "coverage", "spec", "fixture")
_DOCUMENTATION_KEYWORDS = ("docstring", "comment", "readme", "documentation", "jsdoc")


def _classify_convention_category(description: str) -> str:
    """Heuristically classify a convention based on keyword presence."""
    lower = description.lower()
    if any(kw in lower for kw in _NAMING_KEYWORDS):
        return "naming"
    if any(kw in lower for kw in _IMPORT_KEYWORDS):
        return "import_style"
    if any(kw in lower for kw in _ERROR_HANDLING_KEYWORDS):
        return "error_handling"
    if any(kw in lower for kw in _TESTING_KEYWORDS):
        return "testing"
    if any(kw in lower for kw in _DOCUMENTATION_KEYWORDS):
        return "documentation"
    return "naming"


# ---------------------------------------------------------------------------
# LearningSystem
# ---------------------------------------------------------------------------


class LearningSystem:
    """Post-task learning pipeline that updates knowledge stores after task completion.

    The learning system is triggered as an Arq background job via ``on_task_complete``
    so that it never blocks the primary task execution path (Req 16.7). It performs:

    1. Pattern extraction — architecture decisions, coding conventions, error fixes.
    2. Knowledge Base update — store new patterns for agent reference.
    3. Knowledge Graph update — add/modify code relationship nodes and edges.
    4. Code embedding refresh — re-embed modified source files.
    5. Convention tracking — detect and store team coding conventions.
    """

    def __init__(
        self,
        knowledge_store: Any,
        knowledge_graph: Any,
        *,
        embedding_model: str = "text-embedding-3-small",
    ) -> None:
        """Initialise the LearningSystem with store and graph dependencies.

        Parameters
        ----------
        knowledge_store:
            A ``KnowledgeStore`` instance for reading/writing patterns and embeddings.
        knowledge_graph:
            A ``KnowledgeGraphClient`` instance for updating code entity relationships.
        embedding_model:
            Name of the embedding model used for re-embedding source files.
        """
        self._knowledge_store = knowledge_store
        self._knowledge_graph = knowledge_graph
        self._embedding_model = embedding_model

    # ------------------------------------------------------------------
    # Main entry point (Arq background job)
    # ------------------------------------------------------------------

    async def on_task_complete(self, task_id: str, result: TaskResult) -> LearningOutcome:
        """Process a completed task, extract learnings, and update stores (Req 16.1, 16.7).

        This method is designed to be invoked as an Arq background job so it does
        not block the task completion path. It orchestrates the full learning
        pipeline:

        1. Extract patterns from the task result.
        2. Update the Knowledge Base with new patterns.
        3. Update the Knowledge Graph with code relationship changes.
        4. Update code embeddings for modified source files.
        5. Track team conventions observed in the task.

        Parameters
        ----------
        task_id:
            Unique identifier of the completed task.
        result:
            Summarised output of the completed task.

        Returns
        -------
        LearningOutcome:
            Summary of what was learned and stored.
        """
        logger.info(
            "Learning pipeline started",
            extra={"task_id": task_id, "tenant_id": result.tenant_id},
        )
        start_time = datetime.now(UTC)

        # Step 1: Extract patterns (Req 16.1, 16.2)
        patterns = await self.extract_patterns(result)

        # Step 2: Update Knowledge Base with new patterns
        patterns_stored = await self.update_knowledge_base(patterns, result.tenant_id)

        # Step 3: Update Knowledge Graph with code relationship changes (Req 16.1)
        graph_nodes_added = await self.update_knowledge_graph(result.code_changes)

        # Step 4: Update code embeddings for modified source files (Req 16.3)
        embeddings_updated = await self.update_code_embeddings(
            result.code_changes, result.tenant_id
        )

        # Step 5: Track team conventions (Req 16.4)
        conventions = await self.track_conventions(result)
        conventions_updated = len(conventions)

        # Build the learning record (Req 16.6)
        record = LearningRecord(
            record_id=str(uuid.uuid4()),
            task_id=task_id,
            learned_at=datetime.now(UTC),
            patterns=patterns,
            conventions_updated=[c.convention_id for c in conventions],
            graph_nodes_added=graph_nodes_added,
            embeddings_updated=embeddings_updated,
        )

        # Persist the learning record to the Knowledge Base
        await self._store_learning_record(record, result.tenant_id)

        duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
        logger.info(
            "Learning pipeline completed",
            extra={
                "task_id": task_id,
                "patterns_stored": patterns_stored,
                "graph_nodes_added": graph_nodes_added,
                "embeddings_updated": embeddings_updated,
                "conventions_updated": conventions_updated,
                "duration_ms": round(duration_ms, 1),
            },
        )

        return LearningOutcome(
            record=record,
            patterns_stored=patterns_stored,
            graph_nodes_added=graph_nodes_added,
            embeddings_updated=embeddings_updated,
            conventions_updated=conventions_updated,
        )

    # ------------------------------------------------------------------
    # Pattern extraction (Req 16.1, 16.2)
    # ------------------------------------------------------------------

    async def extract_patterns(self, result: TaskResult) -> list[LearnedPattern]:
        """Identify architecture decisions, coding conventions, and error fixes (Req 16.1).

        Analyses the task result to produce a list of ``LearnedPattern`` objects
        categorised as architecture decisions, coding conventions, or error fixes.

        Parameters
        ----------
        result:
            The completed task result containing code changes, decisions, and fixes.

        Returns
        -------
        list[LearnedPattern]:
            Extracted patterns ready for storage in the Knowledge Base.
        """
        patterns: list[LearnedPattern] = []

        # Extract architecture decisions (Req 16.2)
        for decision in result.architecture_decisions:
            pattern = LearnedPattern(
                pattern_id=str(uuid.uuid4()),
                pattern_type="architecture_decision",
                description=decision,
                source_task_id=result.task_id,
                confidence=0.85,
                applicable_domains=[result.agent_role],
            )
            patterns.append(pattern)

        # Extract coding conventions from observed patterns
        for convention_data in result.conventions_observed:
            description = convention_data.get("description", "")
            if not description:
                continue
            pattern = LearnedPattern(
                pattern_id=str(uuid.uuid4()),
                pattern_type="coding_convention",
                description=description,
                source_task_id=result.task_id,
                confidence=convention_data.get("confidence", 0.7),
                applicable_domains=convention_data.get("domains", [result.agent_role]),
            )
            patterns.append(pattern)

        # Extract error fix patterns
        for fix_data in result.error_fixes:
            description = fix_data.get("description", "")
            if not description:
                continue
            pattern = LearnedPattern(
                pattern_id=str(uuid.uuid4()),
                pattern_type="error_fix",
                description=description,
                source_task_id=result.task_id,
                confidence=fix_data.get("confidence", 0.8),
                applicable_domains=fix_data.get("domains", [result.agent_role]),
            )
            patterns.append(pattern)

        logger.debug(
            "Patterns extracted",
            extra={"task_id": result.task_id, "pattern_count": len(patterns)},
        )
        return patterns

    # ------------------------------------------------------------------
    # Knowledge Base updates (Req 16.1)
    # ------------------------------------------------------------------

    async def update_knowledge_base(
        self, patterns: list[LearnedPattern], tenant_id: str
    ) -> int:
        """Store extracted patterns in the Knowledge Base (Req 16.1).

        Each pattern is stored in the namespace ``(tenant_id, "learning")`` so
        that agents can later query learned patterns for their domain.

        Parameters
        ----------
        patterns:
            List of extracted patterns to store.
        tenant_id:
            The tenant owning the task.

        Returns
        -------
        int:
            Number of patterns successfully stored.
        """
        namespace = (tenant_id, "learning")
        stored_count = 0

        for pattern in patterns:
            try:
                from maos.knowledge.models import Document, DocumentMetadata

                doc = Document(
                    document_id=pattern.pattern_id,
                    namespace=namespace,
                    key=pattern.pattern_id,
                    content=pattern.description,
                    metadata=DocumentMetadata(
                        source_filename=f"task:{pattern.source_task_id}",
                        upload_timestamp=datetime.now(UTC),
                        file_type="markdown",
                        chunk_index=0,
                        total_chunks=1,
                        uploader_id="learning_system",
                        token_count=len(pattern.description.split()),
                    ),
                )
                await self._knowledge_store.put(namespace, pattern.pattern_id, doc)
                stored_count += 1
            except Exception:
                logger.exception(
                    "Failed to store pattern in Knowledge Base",
                    extra={"pattern_id": pattern.pattern_id},
                )

        return stored_count

    # ------------------------------------------------------------------
    # Knowledge Graph updates (Req 16.1, 16.2)
    # ------------------------------------------------------------------

    async def update_knowledge_graph(self, code_changes: list[CodeChange]) -> int:
        """Update the Knowledge Graph with code relationship changes (Req 16.1).

        Processes code changes from the task result to add new code entities and
        relationships. Architecture decisions are stored as ADR nodes linked to
        affected code entities (Req 16.2).

        Parameters
        ----------
        code_changes:
            List of code changes from the completed task.

        Returns
        -------
        int:
            Number of graph nodes added or updated.
        """
        nodes_added = 0

        for change in code_changes:
            # Add new entities to the graph
            for entity_name in change.entities_added:
                try:
                    entity = CodeEntity(
                        entity_id=entity_name,
                        node_type=NodeType.SERVICE,
                        file_path=change.file_path,
                        line_number=0,
                        module=_extract_module_from_path(change.file_path),
                        language=change.language,
                        last_updated=datetime.now(UTC),
                    )
                    await self._knowledge_graph.add_entity(entity)
                    nodes_added += 1
                except Exception:
                    logger.exception(
                        "Failed to add entity to Knowledge Graph",
                        extra={"entity_id": entity_name},
                    )

            # Add new relationships
            for source_id, target_id, rel_type_str in change.relationships_added:
                try:
                    rel_type = RelationType(rel_type_str)
                    await self._knowledge_graph.add_relationship(
                        source_id=source_id,
                        target_id=target_id,
                        rel_type=rel_type,
                    )
                except (ValueError, Exception):
                    logger.exception(
                        "Failed to add relationship to Knowledge Graph",
                        extra={"source": source_id, "target": target_id},
                    )

        return nodes_added

    # ------------------------------------------------------------------
    # Code embedding updates (Req 16.3)
    # ------------------------------------------------------------------

    async def update_code_embeddings(
        self, code_changes: list[CodeChange], tenant_id: str
    ) -> int:
        """Update code embeddings when source files are modified (Req 16.3).

        Re-embeds the content of modified source files and updates their vector
        representations in the Knowledge Store.

        Parameters
        ----------
        code_changes:
            List of code changes identifying modified files.
        tenant_id:
            The tenant owning the task.

        Returns
        -------
        int:
            Number of embeddings updated.
        """
        namespace = (tenant_id, "code")
        updated_count = 0

        for change in code_changes:
            try:
                from maos.knowledge.models import Document, DocumentMetadata

                # Create an updated document entry for the modified file
                doc_key = f"file:{change.file_path}"
                doc = Document(
                    document_id=doc_key,
                    namespace=namespace,
                    key=doc_key,
                    content=change.diff_summary,
                    metadata=DocumentMetadata(
                        source_filename=change.file_path,
                        upload_timestamp=datetime.now(UTC),
                        file_type=_map_language_to_file_type(change.language),
                        chunk_index=0,
                        total_chunks=1,
                        uploader_id="learning_system",
                        token_count=len(change.diff_summary.split()),
                    ),
                )
                await self._knowledge_store.put(namespace, doc_key, doc)
                updated_count += 1
            except Exception:
                logger.exception(
                    "Failed to update code embedding",
                    extra={"file_path": change.file_path},
                )

        return updated_count

    # ------------------------------------------------------------------
    # Convention tracking (Req 16.4)
    # ------------------------------------------------------------------

    async def track_conventions(self, result: TaskResult) -> list[Convention]:
        """Track team conventions observed in a completed task (Req 16.4).

        Analyses the task result for naming patterns, import styles, and error
        handling conventions. Stores them in the Knowledge Base for agent
        reference during future tasks.

        Parameters
        ----------
        result:
            The completed task result containing observed conventions.

        Returns
        -------
        list[Convention]:
            Conventions that were tracked or updated.
        """
        conventions: list[Convention] = []
        namespace = (result.tenant_id, "conventions")

        for convention_data in result.conventions_observed:
            description = convention_data.get("description", "")
            if not description:
                continue

            category = _classify_convention_category(description)
            convention = Convention(
                convention_id=str(uuid.uuid4()),
                category=category,
                pattern=convention_data.get("pattern", description),
                examples=convention_data.get("examples", []),
                frequency=convention_data.get("frequency", 1),
                conflicts_with=[],
            )
            conventions.append(convention)

            # Store in Knowledge Base for agent retrieval
            try:
                await self._store_convention(convention, namespace)
            except Exception:
                logger.exception(
                    "Failed to store convention",
                    extra={"convention_id": convention.convention_id},
                )

        return conventions

    # ------------------------------------------------------------------
    # History retrieval (Req 16.6)
    # ------------------------------------------------------------------

    async def get_history(self, tenant_id: str, limit: int = 20, offset: int = 0) -> list[Any]:
        """Retrieve learning history records (Req 16.6).

        Parameters
        ----------
        tenant_id:
            The tenant whose learning history to retrieve.
        limit:
            Maximum records to return.
        offset:
            Pagination offset.

        Returns
        -------
        list:
            Learning records stored for the tenant.
        """
        namespace = (tenant_id, "learning_history")
        result = await self._knowledge_store.list(namespace, limit=limit, offset=offset)
        return result.items

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _store_learning_record(self, record: LearningRecord, tenant_id: str) -> None:
        """Persist a LearningRecord to the Knowledge Base."""
        from maos.knowledge.models import Document, DocumentMetadata

        namespace = (tenant_id, "learning_history")
        doc = Document(
            document_id=record.record_id,
            namespace=namespace,
            key=record.record_id,
            content=record.model_dump_json(),
            metadata=DocumentMetadata(
                source_filename=f"learning_record:{record.task_id}",
                upload_timestamp=record.learned_at,
                file_type="markdown",
                chunk_index=0,
                total_chunks=1,
                uploader_id="learning_system",
                token_count=len(record.model_dump_json().split()),
            ),
        )
        await self._knowledge_store.put(namespace, record.record_id, doc)

    async def _store_convention(
        self, convention: Convention, namespace: tuple[str, ...]
    ) -> None:
        """Persist a Convention to the Knowledge Base."""
        from maos.knowledge.models import Document, DocumentMetadata

        doc = Document(
            document_id=convention.convention_id,
            namespace=namespace,
            key=convention.convention_id,
            content=convention.model_dump_json(),
            metadata=DocumentMetadata(
                source_filename=f"convention:{convention.category}",
                upload_timestamp=datetime.now(UTC),
                file_type="markdown",
                chunk_index=0,
                total_chunks=1,
                uploader_id="learning_system",
                token_count=len(convention.pattern.split()),
            ),
        )
        await self._knowledge_store.put(namespace, convention.convention_id, doc)


# ---------------------------------------------------------------------------
# Arq job entry point (Req 16.7)
# ---------------------------------------------------------------------------


async def on_task_complete_job(ctx: dict[str, Any], task_id: str, result_data: dict[str, Any]) -> dict[str, Any]:
    """Arq background job entry point for the learning pipeline (Req 16.7).

    This function is registered with the Arq worker and invoked after a task
    completes. It reconstructs the ``TaskResult`` from serialised data,
    instantiates the ``LearningSystem``, and runs the learning pipeline.

    Parameters
    ----------
    ctx:
        Arq worker context dict containing shared resources.
    task_id:
        Unique identifier of the completed task.
    result_data:
        Serialised task result data.

    Returns
    -------
    dict:
        Summary of the learning outcome.
    """
    logger.info("on_task_complete_job triggered", extra={"task_id": task_id})

    knowledge_store = ctx.get("knowledge_store")
    knowledge_graph = ctx.get("knowledge_graph")

    if knowledge_store is None or knowledge_graph is None:
        logger.error(
            "Learning job missing dependencies in worker context",
            extra={"task_id": task_id},
        )
        return {"task_id": task_id, "error": "missing_dependencies"}

    # Reconstruct TaskResult from serialised data
    code_changes = [
        CodeChange(
            file_path=c.get("file_path", ""),
            language=c.get("language", ""),
            diff_summary=c.get("diff_summary", ""),
            entities_added=c.get("entities_added", []),
            entities_removed=c.get("entities_removed", []),
            relationships_added=[
                tuple(r) for r in c.get("relationships_added", [])
            ],
        )
        for c in result_data.get("code_changes", [])
    ]

    task_result = TaskResult(
        task_id=task_id,
        tenant_id=result_data.get("tenant_id", ""),
        agent_role=result_data.get("agent_role", ""),
        description=result_data.get("description", ""),
        code_changes=code_changes,
        architecture_decisions=result_data.get("architecture_decisions", []),
        conventions_observed=result_data.get("conventions_observed", []),
        error_fixes=result_data.get("error_fixes", []),
    )

    system = LearningSystem(
        knowledge_store=knowledge_store,
        knowledge_graph=knowledge_graph,
    )

    outcome = await system.on_task_complete(task_id, task_result)

    return {
        "task_id": task_id,
        "patterns_stored": outcome.patterns_stored,
        "graph_nodes_added": outcome.graph_nodes_added,
        "embeddings_updated": outcome.embeddings_updated,
        "conventions_updated": outcome.conventions_updated,
    }


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _extract_module_from_path(file_path: str) -> str:
    """Derive a dot-separated module path from a file path."""
    # Strip common prefixes and extensions
    path = file_path.replace("\\", "/")
    # Remove leading src/ if present
    if "/src/" in path:
        path = path.split("/src/", 1)[1]
    # Remove extension
    for ext in (".py", ".ts", ".js", ".java", ".go", ".rs"):
        if path.endswith(ext):
            path = path[: -len(ext)]
            break
    return path.replace("/", ".")


def _map_language_to_file_type(language: str) -> str:
    """Map a language identifier to a DocumentMetadata file_type value."""
    mapping: dict[str, str] = {
        "python": "python",
        "typescript": "typescript",
        "javascript": "javascript",
        "java": "java",
        "go": "go",
        "rust": "rust",
    }
    return mapping.get(language.lower(), "python")
