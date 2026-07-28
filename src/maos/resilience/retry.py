"""Bounded exponential backoff retry with jitter (Req 15.4).

Provides an async decorator/utility that retries a failing async operation with:
- Exponential backoff: delay doubles each attempt from ``base_delay``.
- Full jitter: actual sleep = uniform(0, computed_delay).
- Bounded delay: capped at ``max_delay``.
- Bounded attempts: raises ``RetryExhaustedError`` after ``max_attempts``.

Requirements: 15.4.
"""

from __future__ import annotations

import asyncio
import functools
import random
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class RetryConfig(BaseModel):
    """Configuration for the retry-with-backoff decorator.

    Attributes:
        max_attempts: Total number of attempts (including the initial call).
        base_delay: Initial delay in seconds before the first retry.
        max_delay: Maximum delay in seconds (caps exponential growth).
        jitter: Whether to apply full jitter (uniform random [0, delay]).
    """

    max_attempts: int = Field(default=3, gt=0)
    base_delay: float = Field(default=1.0, gt=0)
    max_delay: float = Field(default=30.0, gt=0)
    jitter: bool = True


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class RetryExhaustedError(Exception):
    """Raised when all retry attempts have been exhausted.

    Attributes:
        attempts: Total attempts made.
        last_exception: The last exception encountered.
    """

    def __init__(self, attempts: int, last_exception: Exception) -> None:
        self.attempts = attempts
        self.last_exception = last_exception
        super().__init__(
            f"Retry exhausted after {attempts} attempts; "
            f"last error: {last_exception!r}"
        )


# ---------------------------------------------------------------------------
# Core retry logic
# ---------------------------------------------------------------------------


def _compute_delay(attempt: int, config: RetryConfig) -> float:
    """Compute the sleep duration for the given attempt number.

    Uses exponential backoff: ``base_delay * 2^(attempt - 1)`` capped at
    ``max_delay``, then applies full jitter if enabled.
    """
    exp_delay: float = min(config.base_delay * (2 ** (attempt - 1)), config.max_delay)
    if config.jitter:
        return random.uniform(0, exp_delay)
    return exp_delay


async def execute_with_retry(
    fn: Callable[..., Awaitable[T]],
    *args: Any,
    config: RetryConfig | None = None,
    retryable: Callable[[Exception], bool] | None = None,
    **kwargs: Any,
) -> T:
    """Execute an async callable with bounded exponential backoff retry.

    Args:
        fn: The async function to invoke.
        *args: Positional arguments forwarded to ``fn``.
        config: Retry configuration. Defaults to ``RetryConfig()``.
        retryable: Optional predicate; if provided only exceptions for which
            ``retryable(exc)`` returns ``True`` are retried. Others propagate
            immediately.
        **kwargs: Keyword arguments forwarded to ``fn``.

    Returns:
        The return value of ``fn`` on the first successful attempt.

    Raises:
        RetryExhaustedError: When all attempts fail.
    """
    cfg = config or RetryConfig()
    last_exc: Exception | None = None

    for attempt in range(1, cfg.max_attempts + 1):
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if retryable is not None and not retryable(exc):
                raise
            if attempt == cfg.max_attempts:
                break
            delay = _compute_delay(attempt, cfg)
            await asyncio.sleep(delay)

    # Should always be set by the loop, but satisfy type-checker.
    assert last_exc is not None
    raise RetryExhaustedError(attempts=cfg.max_attempts, last_exception=last_exc)


# ---------------------------------------------------------------------------
# Decorator form
# ---------------------------------------------------------------------------


def retry_with_backoff(
    config: RetryConfig | None = None,
    retryable: Callable[[Exception], bool] | None = None,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator applying bounded exponential backoff retry to an async function.

    Usage::

        @retry_with_backoff(RetryConfig(max_attempts=4, base_delay=0.5))
        async def call_llm(prompt: str) -> str: ...

    Args:
        config: Retry configuration.
        retryable: Optional predicate filtering which exceptions to retry.

    Returns:
        A decorator wrapping the target function.
    """

    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            return await execute_with_retry(
                fn, *args, config=config, retryable=retryable, **kwargs
            )

        return wrapper

    return decorator
