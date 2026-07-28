"""Distributed concurrency limiter using Redis atomic counters.

Enforces a **global concurrency cap** (default 50 concurrent tasks) and a
**per-tenant concurrency cap** (default 10 concurrent tasks per tenant) across
all worker instances. Uses Redis INCR/DECR with TTL-backed safety keys to
prevent slot leaks if a worker crashes.

Requirements: 14.1.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# Redis key prefixes for concurrency counters
_GLOBAL_KEY = "maos:concurrency:global"
_TENANT_KEY_PREFIX = "maos:concurrency:tenant:"

# Safety TTL on counter keys — prevents leaked slots if a worker dies without
# releasing. Set to 2x the max job timeout (default 600s * 2 = 1200s).
_KEY_TTL_SECONDS = 1200


@dataclass
class ConcurrencyConfig:
    """Configuration for concurrency caps.

    Attributes
    ----------
    global_max:
        Maximum number of concurrently executing tasks across all tenants.
        Default: 50.
    per_tenant_max:
        Maximum number of concurrently executing tasks per tenant.
        Default: 10.
    """

    global_max: int = field(default=100)
    per_tenant_max: int = field(default=10)

    @classmethod
    def from_settings(cls) -> ConcurrencyConfig:
        """Create a ConcurrencyConfig from the application settings."""
        from maos.config.settings import get_settings

        s = get_settings().scalability
        return cls(
            global_max=s.global_concurrency_cap,
            per_tenant_max=s.tenant_concurrency_cap,
        )


class ConcurrencyLimiter:
    """Distributed concurrency limiter backed by Redis atomic counters.

    Usage::

        limiter = ConcurrencyLimiter(redis_url="redis://localhost:6379/1")
        if await limiter.acquire(tenant_id="clinic-123"):
            try:
                # ... do work ...
            finally:
                await limiter.release(tenant_id="clinic-123")

    The limiter uses Redis INCR to atomically check-and-acquire slots. If
    the counter would exceed the configured cap, the INCR is rolled back
    with DECR and ``acquire()`` returns False.

    Requirements: 14.1 (global concurrency limit), per-tenant isolation.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/1",
        config: ConcurrencyConfig | None = None,
    ) -> None:
        self._redis_url = redis_url
        self._config = config or ConcurrencyConfig()
        self._redis: aioredis.Redis | None = None

    @classmethod
    def from_settings(cls) -> ConcurrencyLimiter:
        """Create a ConcurrencyLimiter from the application settings."""
        from maos.config.settings import get_settings

        settings = get_settings()
        return cls(
            redis_url=settings.broker.url,
            config=ConcurrencyConfig.from_settings(),
        )

    async def _get_redis(self) -> aioredis.Redis:
        """Lazy-init Redis connection."""
        if self._redis is None:
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    async def acquire(self, tenant_id: str) -> bool:
        """Attempt to acquire a concurrency slot for the given tenant.

        Returns True if both the global and per-tenant caps allow execution,
        False otherwise (caller should apply backpressure).

        Parameters
        ----------
        tenant_id:
            The tenant requesting execution capacity.

        Returns
        -------
        bool:
            True if a slot was acquired, False if over capacity.
        """
        r = await self._get_redis()
        tenant_key = f"{_TENANT_KEY_PREFIX}{tenant_id}"

        # Atomically increment global counter
        global_count = await r.incr(_GLOBAL_KEY)
        await r.expire(_GLOBAL_KEY, _KEY_TTL_SECONDS)

        if global_count > self._config.global_max:
            # Over global cap — roll back
            await r.decr(_GLOBAL_KEY)
            logger.debug(
                "Global concurrency cap reached",
                extra={"global_count": global_count, "cap": self._config.global_max},
            )
            return False

        # Atomically increment per-tenant counter
        tenant_count = await r.incr(tenant_key)
        await r.expire(tenant_key, _KEY_TTL_SECONDS)

        if tenant_count > self._config.per_tenant_max:
            # Over per-tenant cap — roll back both
            await r.decr(tenant_key)
            await r.decr(_GLOBAL_KEY)
            logger.debug(
                "Per-tenant concurrency cap reached",
                extra={
                    "tenant_id": tenant_id,
                    "tenant_count": tenant_count,
                    "cap": self._config.per_tenant_max,
                },
            )
            return False

        return True

    async def release(self, tenant_id: str) -> None:
        """Release a concurrency slot for the given tenant.

        Must be called in a finally block after ``acquire()`` returns True.

        Parameters
        ----------
        tenant_id:
            The tenant whose slot is being released.
        """
        r = await self._get_redis()
        tenant_key = f"{_TENANT_KEY_PREFIX}{tenant_id}"

        # Decrement both counters (floor at 0 to prevent negative drift)
        global_val = await r.decr(_GLOBAL_KEY)
        if global_val < 0:
            await r.set(_GLOBAL_KEY, 0)

        tenant_val = await r.decr(tenant_key)
        if tenant_val < 0:
            await r.set(tenant_key, 0)

    async def current_global(self) -> int:
        """Return the current global concurrency count."""
        r = await self._get_redis()
        val = await r.get(_GLOBAL_KEY)
        return int(val) if val else 0

    async def current_tenant(self, tenant_id: str) -> int:
        """Return the current concurrency count for a specific tenant."""
        r = await self._get_redis()
        val = await r.get(f"{_TENANT_KEY_PREFIX}{tenant_id}")
        return int(val) if val else 0

    async def close(self) -> None:
        """Close the underlying Redis connection."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
