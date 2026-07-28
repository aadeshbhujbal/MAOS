"""Retrieval Tool — LangGraph @task for vector similarity search.

Provides ``knowledge_search``, an MCP-compatible retrieval tool registered in
agent allow-lists.  It delegates to ``KnowledgeStore.search()`` with namespace
filtering applied *before* vector similarity computation and emits structured
observability logs per invocation.

References
----------
- Req 5.1: Top-k semantic similarity search within authorized namespace
- Req 5.2: Default k=5, configurable 1-20
- Req 5.3: Result includes content, relevance_score, source_filename, chunk metadata
- Req 5.4: Retrieval completes within 2000 ms for namespaces <= 10 000 docs
- Req 5.6: Namespace filtering before vector similarity computation
- Req 7.3: @task decorator for individual retryability and observability
- Req 10.2: Structured log event with query_namespace, result_count, top_score, latency_ms
- Req 10.4: Warning log when latency > 2000 ms
"""

from __future__ import annotations

import logging
import time
from typing import Any

from langgraph.func import task  # type: ignore[import-untyped]
from langgraph.types import RetryPolicy  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from maos.knowledge.models import DocumentMetadata

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


class RetrievalResult(BaseModel):
    """A single retrieval result returned from knowledge_search (Req 5.3)."""

    content: str
    relevance_score: float = Field(ge=0.0, le=1.0)
    source_filename: str
    metadata: DocumentMetadata


# ---------------------------------------------------------------------------
# Module-level store reference (set during app startup)
# ---------------------------------------------------------------------------

_knowledge_store: Any = None


def set_knowledge_store(store: Any) -> None:
    """Bind the KnowledgeStore instance used by the retrieval task.

    Called once during FastAPI lifespan initialization.
    """
    global _knowledge_store
    _knowledge_store = store


def get_knowledge_store() -> Any:
    """Return the bound KnowledgeStore instance.

    Raises
    ------
    RuntimeError
        If the store has not been bound via ``set_knowledge_store``.
    """
    if _knowledge_store is None:
        raise RuntimeError(
            "KnowledgeStore not bound. Call set_knowledge_store() during app startup."
        )
    return _knowledge_store


# ---------------------------------------------------------------------------
# Retrieval @task
# ---------------------------------------------------------------------------

_LATENCY_WARN_THRESHOLD_MS = 2000


@task(retry=RetryPolicy(max_attempts=3, backoff_factor=2.0))
async def knowledge_search(
    query: str,
    namespace: tuple[str, ...],
    k: int = 5,
) -> list[RetrievalResult]:
    """Vector similarity search within an authorized namespace (Req 5.1-5.6, 7.3).

    Parameters
    ----------
    query:
        Natural-language query string for semantic similarity matching.
    namespace:
        Namespace tuple ``(tenant_id, agent_role)`` applied as a pre-filter
        before vector similarity computation (Req 5.6).
    k:
        Number of top results to return.  Clamped to [1, 20] (Req 5.2).

    Returns
    -------
    list[RetrievalResult]
        Up to *k* results ordered by descending relevance score, each containing
        content, relevance_score, source_filename, and chunk metadata (Req 5.3).
    """
    # Clamp k to valid range (Req 5.2)
    k = max(1, min(k, 20))

    store = get_knowledge_store()

    start_ns = time.perf_counter_ns()

    # Namespace filtering is applied by KnowledgeStore.search() which scopes
    # the vector similarity computation to the given namespace (Req 5.6).
    search_results = await store.search(namespace=namespace, query=query, k=k)

    elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000

    # Build typed results (Req 5.3)
    results: list[RetrievalResult] = [
        RetrievalResult(
            content=r.content,
            relevance_score=r.relevance_score,
            source_filename=r.source_filename,
            metadata=r.metadata,
        )
        for r in search_results
    ]

    # Compute top_score for logging
    top_score = results[0].relevance_score if results else 0.0

    # Emit structured log (Req 10.2)
    logger.info(
        "knowledge_search completed",
        extra={
            "query_namespace": namespace,
            "result_count": len(results),
            "top_score": top_score,
            "latency_ms": round(elapsed_ms, 2),
        },
    )

    # Warn if latency exceeds threshold (Req 10.4)
    if elapsed_ms > _LATENCY_WARN_THRESHOLD_MS:
        logger.warning(
            "knowledge_search latency exceeded threshold",
            extra={
                "query_namespace": namespace,
                "latency_ms": round(elapsed_ms, 2),
                "threshold_ms": _LATENCY_WARN_THRESHOLD_MS,
                "query_preview": query[:100],
            },
        )

    return results
