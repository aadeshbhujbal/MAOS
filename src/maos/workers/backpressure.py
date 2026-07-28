"""Backpressure guard for MAOS task intake.

Checks the current queue depth and active job count against configured limits.
When over capacity, signals the FastAPI endpoint to return **429 Too Many
Requests** with a ``Retry-After`` header (Req 14.4).

The guard queries Redis for:
- Current queue depth (pending jobs in the Arq queue).
- Active concurrency count (from the ConcurrencyLimiter counters).

This allows the API layer to reject new submissions with backpressure before
they are enqueued, preventing unbounded queue growth.

Requirements: 14.4.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# Default Arq queue key — Arq stores pending jobs in a sorted set with this name.
_ARQ_QUEUE_KEY = "arq:queue"

# Key used by ConcurrencyLimiter for global active count
_GLOBAL_CONCURRENCY_KEY = "maos:concurrency:global"
_TENANT_CONCURRENCY_PREFIX = "maos:concurrency:tenant:"


class BackpressureError(Exception):
    """Raised when the system is over capacity and backpressure should be applied.

    The API layer converts this into an HTTP 429 response with Retry-After header.

    Attributes
    ----------
    retry_after:
        Recommended number of seconds before the client should retry.
    """

    def __init__(self, retry_after: int = 30, detail: str = "System at capacity") -> None:
        self.retry_after = retry_after
        self.detail = detail
        super().__init__(detail)


@dataclass
class BackpressureConfig:
    """Configuration for backpressure thresholds.

    Attributes
    ----------
    max_queue_depth:
        Maximum number of pending jobs in the broker queue before
        backpressure engages. Default: 200.
    max_global_active:
        Maximum active jobs (mirrors ConcurrencyConfig.global_max).
        Default: 50.
    max_per_tenant_active:
        Maximum active jobs per tenant (mirrors ConcurrencyConfig.per_tenant_max).
        Default: 10.
    retry_after_seconds:
        The value to return in the ``Retry-After`` header when backpressure
        is active. Default: 30 seconds.
    """

    max_queue_depth: int = field(default=200)
    max_global_active: int = field(default=100)
    max_per_tenant_active: int = field(default=10)
    retry_after_seconds: int = field(default=30)

    @classmethod
    def from_settings(cls) -> BackpressureConfig:
        """Create a BackpressureConfig from the application settings."""
        from maos.config.settings import get_settings

        s = get_settings().scalability
        return cls(
            max_queue_depth=s.max_queue_depth,
            max_global_active=s.global_concurrency_cap,
            max_per_tenant_active=s.tenant_concurrency_cap,
            retry_after_seconds=s.backpressure_retry_after,
        )


class BackpressureGuard:
    """Checks system capacity and signals when backpressure should be applied.

    Usage in a FastAPI endpoint::

        guard = BackpressureGuard(redis_url="redis://localhost:6379/1")

        @app.post("/v1/tasks")
        async def submit_task(...):
            can_accept = await guard.check_capacity(tenant_id=ctx.tenant_id)
            if not can_accept:
                raise BackpressureError(
                    retry_after=guard.config.retry_after_seconds,
                    detail="System at capacity. Retry later.",
                )
            ...

    Requirements: 14.4.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/1",
        config: BackpressureConfig | None = None,
    ) -> None:
        self._redis_url = redis_url
        self.config = config or BackpressureConfig()
        self._redis: aioredis.Redis | None = None

    @classmethod
    def from_settings(cls) -> BackpressureGuard:
        """Create a BackpressureGuard from the application settings."""
        from maos.config.settings import get_settings

        settings = get_settings()
        return cls(
            redis_url=settings.broker.url,
            config=BackpressureConfig.from_settings(),
        )

    async def _get_redis(self) -> aioredis.Redis:
        """Lazy-init Redis connection."""
        if self._redis is None:
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    async def check_capacity(self, tenant_id: str) -> bool:
        """Check whether the system can accept a new task.

        Returns True if the system has capacity, False if backpressure
        should be applied (caller should return 429).

        Checks:
        1. Global queue depth is below the configured threshold.
        2. Global active job count is below the configured cap.
        3. Per-tenant active job count is below the configured cap.

        Parameters
        ----------
        tenant_id:
            The tenant submitting the task.

        Returns
        -------
        bool:
            True if the system can accept the task, False otherwise.
        """
        r = await self._get_redis()

        # Check queue depth (Arq stores pending jobs in a sorted set)
        queue_depth = await r.zcard(_ARQ_QUEUE_KEY)
        if queue_depth >= self.config.max_queue_depth:
            logger.info(
                "Backpressure: queue depth exceeded",
                extra={"queue_depth": queue_depth, "max": self.config.max_queue_depth},
            )
            return False

        # Check global active count
        global_active_raw = await r.get(_GLOBAL_CONCURRENCY_KEY)
        global_active = int(global_active_raw) if global_active_raw else 0
        if global_active >= self.config.max_global_active:
            logger.info(
                "Backpressure: global concurrency cap reached",
                extra={"active": global_active, "max": self.config.max_global_active},
            )
            return False

        # Check per-tenant active count
        tenant_key = f"{_TENANT_CONCURRENCY_PREFIX}{tenant_id}"
        tenant_active_raw = await r.get(tenant_key)
        tenant_active = int(tenant_active_raw) if tenant_active_raw else 0
        if tenant_active >= self.config.max_per_tenant_active:
            logger.info(
                "Backpressure: per-tenant concurrency cap reached",
                extra={
                    "tenant_id": tenant_id,
                    "active": tenant_active,
                    "max": self.config.max_per_tenant_active,
                },
            )
            return False

        return True

    async def check_or_raise(self, tenant_id: str) -> None:
        """Check capacity and raise BackpressureError if over capacity.

        Convenience method for use in API handlers — raises BackpressureError
        (which the handler converts to 429 + Retry-After) when backpressure
        should be applied.

        Parameters
        ----------
        tenant_id:
            The tenant submitting the task.

        Raises
        ------
        BackpressureError:
            When the system is at or over capacity.
        """
        can_accept = await self.check_capacity(tenant_id)
        if not can_accept:
            raise BackpressureError(
                retry_after=self.config.retry_after_seconds,
                detail="System at capacity. Retry later.",
            )

    async def get_queue_depth(self) -> int:
        """Return the current queue depth (pending jobs)."""
        r = await self._get_redis()
        return int(await r.zcard(_ARQ_QUEUE_KEY))

    async def close(self) -> None:
        """Close the underlying Redis connection."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
