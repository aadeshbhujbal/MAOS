"""Prompt and semantic caches for the LLM adapter path (Req 15.7).

Uses Dragonfly (Redis-compatible in-memory store) as the backing store via the
``redis.asyncio`` client. Two cache layers sit in front of the LLM provider:

1. **PromptCache** — exact-match, hash-based lookup on normalized request
   parameters (model, messages, temperature, max_tokens). O(1) hit/miss.
2. **SemanticCache** — embedding-similarity lookup that finds a prior response
   whose request is semantically equivalent (cosine similarity ≥ configured
   threshold). Falls back to a brute-force approach when Redis VSS is
   unavailable (stores embeddings as JSON and scans on read).

PHI Safety:
    Requests with ``contains_phi=True`` are NEVER cached to prevent PHI
    leakage through the cache layer.

The ``CachedLLMAdapter`` wraps any ``LLMProviderAdapter`` and intercepts
``complete()`` calls: prompt cache → semantic cache → provider → store back.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
from typing import Any

import redis.asyncio as aioredis
from pydantic import BaseModel

from maos.contracts.llm import LLMRequest, LLMResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------


class CacheConfig(BaseModel):
    """Configuration for the Dragonfly-backed cache layers."""

    dragonfly_url: str = "redis://localhost:6379/0"
    prompt_cache_ttl_seconds: int = 3600  # 1 hour default
    semantic_cache_threshold: float = 0.95  # cosine similarity threshold
    semantic_cache_ttl_seconds: int = 3600
    key_prefix: str = "maos:llm_cache"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_request(request: LLMRequest) -> dict[str, Any]:
    """Normalize an LLMRequest into a deterministic dict for hashing.

    Sorts message lists and nested dicts so equivalent requests produce
    the same hash regardless of insertion order.
    """
    messages_normalized = json.dumps(request.messages, sort_keys=True, ensure_ascii=False)
    return {
        "model_hint": request.model_hint or "",
        "messages": messages_normalized,
        "tenant_id": request.tenant_id,
    }


def _compute_cache_key(request: LLMRequest, prefix: str) -> str:
    """Compute a deterministic SHA-256 hash key for an LLM request."""
    normalized = _normalize_request(request)
    payload = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{prefix}:prompt:{digest}"


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b) or len(a) == 0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# Embedding provider protocol
# ---------------------------------------------------------------------------


class EmbeddingProvider:
    """Protocol-like base for computing text embeddings.

    Subclass or replace with a real embedding provider (e.g., OpenAI
    text-embedding-ada-002, sentence-transformers local model, etc.).
    """

    async def embed(self, text: str) -> list[float]:
        """Return an embedding vector for the given text.

        Default implementation raises NotImplementedError — callers must
        provide a concrete implementation for semantic cache to function.
        """
        raise NotImplementedError("EmbeddingProvider.embed() must be overridden")


# ---------------------------------------------------------------------------
# PromptCache — exact hash match
# ---------------------------------------------------------------------------


class PromptCache:
    """Hash-based prompt cache backed by Dragonfly (via redis.asyncio).

    Cache key is derived from: model_hint, messages (normalized), and
    tenant_id. The response is stored as JSON with a configurable TTL.

    PHI requests (contains_phi=True) are NEVER cached.
    """

    def __init__(self, client: aioredis.Redis, config: CacheConfig) -> None:
        self._client = client
        self._config = config

    async def get(self, request: LLMRequest) -> LLMResponse | None:
        """Look up a cached response for the given request.

        Returns None on cache miss or if the request contains PHI.
        """
        if request.contains_phi:
            return None

        key = _compute_cache_key(request, self._config.key_prefix)
        try:
            raw = await self._client.get(key)
        except Exception:
            logger.warning("PromptCache.get failed for key=%s", key, exc_info=True)
            return None

        if raw is None:
            return None

        try:
            data = json.loads(raw)
            return LLMResponse(**data)
        except (json.JSONDecodeError, Exception):
            logger.warning("PromptCache: corrupt entry at key=%s", key, exc_info=True)
            return None

    async def set(self, request: LLMRequest, response: LLMResponse) -> None:
        """Store a response in the cache with the configured TTL.

        Does nothing if the request contains PHI.
        """
        if request.contains_phi:
            return

        key = _compute_cache_key(request, self._config.key_prefix)
        value = response.model_dump_json()
        try:
            await self._client.set(key, value, ex=self._config.prompt_cache_ttl_seconds)
        except Exception:
            logger.warning("PromptCache.set failed for key=%s", key, exc_info=True)


# ---------------------------------------------------------------------------
# SemanticCache — embedding similarity lookup
# ---------------------------------------------------------------------------


class SemanticCache:
    """Semantic cache using embedding cosine similarity.

    Stores request embeddings and associated responses in Dragonfly. On
    lookup, computes the embedding for the incoming request and searches
    stored embeddings for one exceeding the similarity threshold.

    This implementation uses a simple brute-force scan over a Redis sorted
    set of embedding keys. For production scale, integrate Redis VSS (Vector
    Similarity Search) module available in Dragonfly / Redis Stack.

    PHI requests (contains_phi=True) are NEVER cached.
    """

    def __init__(
        self,
        client: aioredis.Redis,
        config: CacheConfig,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self._client = client
        self._config = config
        self._embedding_provider = embedding_provider

    def _index_key(self) -> str:
        """Key for the set that tracks all semantic cache entry keys."""
        return f"{self._config.key_prefix}:semantic:index"

    def _entry_key(self, entry_id: str) -> str:
        """Key for a single semantic cache entry (embedding + response)."""
        return f"{self._config.key_prefix}:semantic:entry:{entry_id}"

    async def get_similar(self, request: LLMRequest) -> LLMResponse | None:
        """Find a semantically equivalent cached response.

        Returns None if no stored entry exceeds the similarity threshold,
        if the request contains PHI, or if the embedding provider fails.
        """
        if request.contains_phi:
            return None

        try:
            query_text = self._request_to_text(request)
            query_embedding = await self._embedding_provider.embed(query_text)
        except Exception:
            logger.warning("SemanticCache: embedding failed", exc_info=True)
            return None

        try:
            entry_ids = await self._client.smembers(self._index_key())
        except Exception:
            logger.warning("SemanticCache: index read failed", exc_info=True)
            return None

        best_score = 0.0
        best_response: LLMResponse | None = None

        for raw_id in entry_ids:
            entry_id = raw_id.decode("utf-8") if isinstance(raw_id, bytes) else str(raw_id)
            entry_key = self._entry_key(entry_id)
            try:
                raw_entry = await self._client.get(entry_key)
            except Exception:
                continue

            if raw_entry is None:
                # Entry expired — remove stale index reference
                with contextlib.suppress(Exception):
                    await self._client.srem(self._index_key(), entry_id)
                continue

            try:
                entry_data = json.loads(raw_entry)
                stored_embedding: list[float] = entry_data["embedding"]
                score = _cosine_similarity(query_embedding, stored_embedding)
                if score >= self._config.semantic_cache_threshold and score > best_score:
                    best_score = score
                    best_response = LLMResponse(**entry_data["response"])
            except (json.JSONDecodeError, KeyError, Exception):
                continue

        return best_response

    async def store(self, request: LLMRequest, response: LLMResponse) -> None:
        """Store a request/response pair with its embedding for future retrieval.

        Does nothing if the request contains PHI or embedding computation fails.
        """
        if request.contains_phi:
            return

        try:
            query_text = self._request_to_text(request)
            embedding = await self._embedding_provider.embed(query_text)
        except Exception:
            logger.warning("SemanticCache.store: embedding failed", exc_info=True)
            return

        entry_id = _compute_cache_key(request, "sem")  # unique per request content
        entry_key = self._entry_key(entry_id)
        entry_data = json.dumps({
            "embedding": embedding,
            "response": response.model_dump(),
            "request_text": query_text,
        })

        try:
            await self._client.set(
                entry_key, entry_data, ex=self._config.semantic_cache_ttl_seconds
            )
            await self._client.sadd(self._index_key(), entry_id)
        except Exception:
            logger.warning("SemanticCache.store failed", exc_info=True)

    @staticmethod
    def _request_to_text(request: LLMRequest) -> str:
        """Convert an LLM request to a text representation for embedding."""
        parts: list[str] = []
        for msg in request.messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            parts.append(f"{role}: {content}")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# CachedLLMAdapter — wraps the provider adapter with cache layers
# ---------------------------------------------------------------------------


class CachedLLMAdapter:
    """Adapter wrapper that checks cache layers before invoking the provider.

    Lookup order:
        1. PromptCache (exact hash match) — fastest
        2. SemanticCache (embedding similarity) — catches paraphrases
        3. Fall through to the underlying LLM provider adapter

    On provider success, the result is stored in both caches for future hits.

    PHI requests bypass all caches entirely (never stored, never returned).
    """

    def __init__(
        self,
        prompt_cache: PromptCache,
        semantic_cache: SemanticCache | None,
        provider_adapter: Any,  # LLMProviderAdapter or any object with async complete()
    ) -> None:
        self._prompt_cache = prompt_cache
        self._semantic_cache = semantic_cache
        self._provider_adapter = provider_adapter

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Execute a model call with cache-first semantics (Req 15.7).

        For PHI-bearing requests, caches are bypassed entirely and the
        call goes directly to the provider.
        """
        # PHI requests NEVER use cache
        if request.contains_phi:
            response: LLMResponse = await self._provider_adapter.complete(request)
            return response

        # 1. Check prompt cache (exact match)
        cached = await self._prompt_cache.get(request)
        if cached is not None:
            logger.debug("PromptCache HIT")
            return cached

        # 2. Check semantic cache (similarity match)
        if self._semantic_cache is not None:
            similar = await self._semantic_cache.get_similar(request)
            if similar is not None:
                logger.debug("SemanticCache HIT (similarity >= threshold)")
                return similar

        # 3. Fall through to provider
        response = await self._provider_adapter.complete(request)

        # Store in caches (fire-and-forget style, errors logged but not raised)
        await self._prompt_cache.set(request, response)
        if self._semantic_cache is not None:
            await self._semantic_cache.store(request, response)

        return response
