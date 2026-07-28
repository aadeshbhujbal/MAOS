"""Per-Requester and per-Tenant rate limiting for the MAOS API surface.

Implements token-bucket rate limiting backed by Redis using INCR + EXPIRE
for a sliding window. Both per-Requester and per-Tenant limits are enforced;
exceeding either limit rejects the request with HTTP 429 and a Retry-After
header until the window resets.

Requirements: 15.2, 15.3
"""

from __future__ import annotations

from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request, status

from maos.api.auth import RequesterContext, get_authenticated_requester


class RateLimiter:
    """Token-bucket rate limiter backed by Redis (INCR + EXPIRE sliding window).

    Each unique key is tracked in Redis as a counter with an expiration equal
    to the configured window. When the counter exceeds ``max_requests`` within
    the window the request is denied.

    Args:
        redis: An async Redis client instance.
        max_requests: Maximum allowed requests within the window.
        window_seconds: Duration of the rate-limit window in seconds.
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        max_requests: int,
        window_seconds: int,
    ) -> None:
        self._redis = redis
        self._max_requests = max_requests
        self._window_seconds = window_seconds

    @property
    def max_requests(self) -> int:
        """The configured maximum requests per window."""
        return self._max_requests

    @property
    def window_seconds(self) -> int:
        """The configured window duration in seconds."""
        return self._window_seconds

    async def check(self, key: str) -> bool:
        """Check whether a request identified by *key* is within the rate limit.

        Uses Redis INCR + EXPIRE to implement a fixed-window counter. Returns
        True if the request is allowed (counter ≤ max_requests), False if the
        rate limit is exceeded.

        Args:
            key: A unique identifier for the rate-limit bucket (e.g.
                ``"rl:requester:<id>"`` or ``"rl:tenant:<id>"``).

        Returns:
            True if the request is allowed, False if rate-limited.
        """
        current = await self._redis.incr(key)
        if current == 1:
            # First request in this window — set the expiration.
            await self._redis.expire(key, self._window_seconds)
        return current <= self._max_requests


# ---------------------------------------------------------------------------
# Default configuration constants (overridable via settings in production)
# ---------------------------------------------------------------------------

_DEFAULT_REQUESTER_MAX_REQUESTS: int = 60
_DEFAULT_REQUESTER_WINDOW_SECONDS: int = 60
_DEFAULT_TENANT_MAX_REQUESTS: int = 300
_DEFAULT_TENANT_WINDOW_SECONDS: int = 60


def _get_redis(request: Request) -> aioredis.Redis:
    """Extract the Redis client from the application state.

    The Redis client is expected to be attached to ``app.state.redis`` during
    application startup (wired in the app factory or lifespan).
    """
    redis_client: aioredis.Redis | None = getattr(request.app.state, "redis", None)
    if redis_client is None:
        raise RuntimeError(
            "Redis client not available on app.state.redis. "
            "Ensure the application lifespan initializes the Redis connection."
        )
    return redis_client


async def rate_limit_dependency(
    request: Request,
    ctx: Annotated[RequesterContext, Depends(get_authenticated_requester)],
) -> RequesterContext:
    """FastAPI dependency enforcing per-Requester and per-Tenant rate limits.

    Extracts ``tenant_id`` and ``requester_id`` from the authenticated context,
    checks both rate limits against Redis, and raises HTTP 429 with a
    ``Retry-After`` header if either limit is exceeded.

    This dependency depends on ``get_authenticated_requester`` so that
    authentication is enforced before rate limiting.

    Returns:
        The authenticated ``RequesterContext`` if both limits pass.

    Raises:
        HTTPException (429): If either per-Requester or per-Tenant limit is
            exceeded. Includes a ``Retry-After`` header indicating seconds
            until the window resets.
    """
    redis_client = _get_redis(request)

    # Build per-requester and per-tenant limiters from app state or defaults.
    requester_limiter = _get_requester_limiter(request, redis_client)
    tenant_limiter = _get_tenant_limiter(request, redis_client)

    requester_key = f"rl:requester:{ctx.requester_id}"
    tenant_key = f"rl:tenant:{ctx.tenant_id}"

    # Check requester limit
    requester_allowed = await requester_limiter.check(requester_key)
    if not requester_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for requester.",
            headers={"Retry-After": str(requester_limiter.window_seconds)},
        )

    # Check tenant limit
    tenant_allowed = await tenant_limiter.check(tenant_key)
    if not tenant_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for tenant.",
            headers={"Retry-After": str(tenant_limiter.window_seconds)},
        )

    return ctx


def _get_requester_limiter(request: Request, redis_client: aioredis.Redis) -> RateLimiter:
    """Retrieve or create the per-Requester RateLimiter."""
    limiter: RateLimiter | None = getattr(request.app.state, "requester_rate_limiter", None)
    if limiter is not None:
        return limiter
    return RateLimiter(
        redis=redis_client,
        max_requests=_DEFAULT_REQUESTER_MAX_REQUESTS,
        window_seconds=_DEFAULT_REQUESTER_WINDOW_SECONDS,
    )


def _get_tenant_limiter(request: Request, redis_client: aioredis.Redis) -> RateLimiter:
    """Retrieve or create the per-Tenant RateLimiter."""
    limiter: RateLimiter | None = getattr(request.app.state, "tenant_rate_limiter", None)
    if limiter is not None:
        return limiter
    return RateLimiter(
        redis=redis_client,
        max_requests=_DEFAULT_TENANT_MAX_REQUESTS,
        window_seconds=_DEFAULT_TENANT_WINDOW_SECONDS,
    )
