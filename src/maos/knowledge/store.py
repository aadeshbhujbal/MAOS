"""Knowledge Store — PostgresStore wrapper with namespace scoping and vector search.

Wraps LangGraph v1.2 ``PostgresStore`` to provide namespace-scoped document
storage with vector similarity search. Each document is keyed by a
``(tenant_id, agent_role)`` namespace tuple, enabling strict tenant isolation
and role-based partitioning.

References
----------
- Req 1.1: Knowledge Base backed by LangGraph PostgresStore
- Req 1.2: Configurable embedding dimensions
- Req 1.3: Document model with namespace, content, embedding
- Req 1.4: Embedding dimensionality invariant (1536)
- Req 1.5: Vector similarity retrieval
- Req 1.6: Health-check endpoint for store connectivity
- Req 9.1: KnowledgeStore initialization in app lifecycle
- Req 9.2: Configuration via environment variables
"""

from __future__ import annotations

import logging
from typing import Any

from maos.knowledge.models import Document, DocumentMetadata, PaginatedResult, SearchResult

logger = logging.getLogger(__name__)


class StartupError(Exception):
    """Raised when KnowledgeStore fails to initialize."""


class KnowledgeStore:
    """Namespace-scoped document store backed by LangGraph PostgresStore (Req 1.1-1.6)."""

    def __init__(self, postgres_dsn: str, embedding_dimensions: int = 1536) -> None:
        self._dsn = postgres_dsn
        self._embedding_dimensions = embedding_dimensions
        self._store: Any = None  # PostgresStore instance (lazy)
        self._initialized = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Connect to PostgresStore. Raises StartupError on failure."""
        try:
            from langgraph.store.postgres import AsyncPostgresStore  # type: ignore[import-untyped]

            self._store = await AsyncPostgresStore.from_conn_string(self._dsn)
            await self._store.setup()  # create tables if needed
            self._initialized = True
            logger.info("KnowledgeStore initialized successfully")
        except Exception as exc:
            logger.error("KnowledgeStore initialization failed: %s", exc)
            raise StartupError(f"Failed to initialize KnowledgeStore: {exc}") from exc

    # ------------------------------------------------------------------
    # CRUD Operations
    # ------------------------------------------------------------------

    async def put(self, namespace: tuple[str, ...], key: str, document: Document) -> None:
        """Store a document in the given namespace."""
        self._ensure_initialized()
        await self._store.aput(
            namespace=namespace,
            key=key,
            value=document.model_dump(),
        )

    async def get(self, namespace: tuple[str, ...], key: str) -> Document | None:
        """Retrieve a document by namespace + key."""
        self._ensure_initialized()
        item = await self._store.aget(namespace=namespace, key=key)
        if item is None:
            return None
        return Document(**item.value)

    async def search(
        self, namespace: tuple[str, ...], query: str, k: int = 5
    ) -> list[SearchResult]:
        """Vector similarity search within a namespace. Returns top-k results."""
        self._ensure_initialized()
        results = await self._store.asearch(namespace=namespace, query=query, limit=k)
        return [
            SearchResult(
                document_id=item.value.get("document_id", ""),
                content=item.value.get("content", ""),
                relevance_score=item.score if hasattr(item, "score") else 0.0,
                source_filename=item.value.get("metadata", {}).get("source_filename", ""),
                metadata=DocumentMetadata(**item.value.get("metadata", {})),
            )
            for item in results
        ]

    async def delete(self, namespace: tuple[str, ...], key: str) -> bool:
        """Delete a document. Returns True if it existed."""
        self._ensure_initialized()
        await self._store.adelete(namespace=namespace, key=key)
        return True

    async def delete_namespace(self, namespace: tuple[str, ...]) -> int:
        """Delete all documents in a namespace. Returns count deleted."""
        self._ensure_initialized()
        items = await self._store.alist(namespace=namespace, limit=10_000)
        count = 0
        for item in items:
            await self._store.adelete(namespace=namespace, key=item.key)
            count += 1
        return count

    async def list(
        self, namespace: tuple[str, ...], limit: int = 20, offset: int = 0
    ) -> PaginatedResult:
        """List documents in a namespace with pagination."""
        self._ensure_initialized()
        all_items = await self._store.alist(namespace=namespace, limit=limit + offset)
        items_list = list(all_items)
        paged = items_list[offset : offset + limit]
        documents = [Document(**item.value) for item in paged]
        return PaginatedResult(
            total_count=len(items_list),
            limit=limit,
            offset=offset,
            items=documents,
        )

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> dict[str, Any]:
        """Return store connectivity status."""
        if not self._initialized:
            return {"status": "unavailable", "reason": "not_initialized"}
        try:
            # Simple connectivity test
            await self._store.alist(namespace=("_health",), limit=1)
            return {"status": "healthy"}
        except Exception as exc:
            return {"status": "unhealthy", "reason": str(exc)}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_initialized(self) -> None:
        if not self._initialized or self._store is None:
            raise RuntimeError("KnowledgeStore not initialized. Call initialize() first.")
