"""Pre-configured resilience policies per external dependency (Req 11.4, 11.5, 15.4).

Each dependency type (LLM providers, Postgres, Redis, MCP servers) gets a
composed policy containing a circuit breaker, retry config, and timeout.
The ``resilient_call()`` utility executes an async callable through the full
resilience stack in the correct order: circuit breaker → retry → timeout.

Requirements: 11.4, 11.5, 15.4.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any, TypeVar

from pydantic import BaseModel, Field

from maos.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
)
from maos.resilience.retry import RetryConfig, execute_with_retry
from maos.resilience.timeout import with_timeout

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Dependency types
# ---------------------------------------------------------------------------


class DependencyType(str, Enum):
    """Supported external dependency types with pre-configured policies."""

    LLM_PROVIDER = "llm_provider"
    POSTGRES = "postgres"
    REDIS = "redis"
    MCP_SERVER = "mcp_server"


# ---------------------------------------------------------------------------
# Composed policy model
# ---------------------------------------------------------------------------


class ResiliencePolicy(BaseModel):
    """Composed resilience policy for a single external dependency.

    Attributes:
        dependency_type: The kind of external dependency.
        circuit_breaker: Circuit breaker configuration.
        retry: Retry configuration.
        timeout_seconds: Per-call timeout in seconds.
    """

    dependency_type: DependencyType
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    timeout_seconds: float = Field(default=30.0, gt=0)


# ---------------------------------------------------------------------------
# Default policies per dependency type
# ---------------------------------------------------------------------------

_DEFAULT_POLICIES: dict[DependencyType, ResiliencePolicy] = {
    DependencyType.LLM_PROVIDER: ResiliencePolicy(
        dependency_type=DependencyType.LLM_PROVIDER,
        circuit_breaker=CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout=60.0,
            half_open_max_calls=1,
        ),
        retry=RetryConfig(
            max_attempts=3,
            base_delay=1.0,
            max_delay=15.0,
            jitter=True,
        ),
        timeout_seconds=60.0,
    ),
    DependencyType.POSTGRES: ResiliencePolicy(
        dependency_type=DependencyType.POSTGRES,
        circuit_breaker=CircuitBreakerConfig(
            failure_threshold=5,
            recovery_timeout=30.0,
            half_open_max_calls=2,
        ),
        retry=RetryConfig(
            max_attempts=3,
            base_delay=0.5,
            max_delay=5.0,
            jitter=True,
        ),
        timeout_seconds=10.0,
    ),
    DependencyType.REDIS: ResiliencePolicy(
        dependency_type=DependencyType.REDIS,
        circuit_breaker=CircuitBreakerConfig(
            failure_threshold=5,
            recovery_timeout=15.0,
            half_open_max_calls=2,
        ),
        retry=RetryConfig(
            max_attempts=3,
            base_delay=0.25,
            max_delay=2.0,
            jitter=True,
        ),
        timeout_seconds=5.0,
    ),
    DependencyType.MCP_SERVER: ResiliencePolicy(
        dependency_type=DependencyType.MCP_SERVER,
        circuit_breaker=CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout=45.0,
            half_open_max_calls=1,
        ),
        retry=RetryConfig(
            max_attempts=2,
            base_delay=1.0,
            max_delay=10.0,
            jitter=True,
        ),
        timeout_seconds=30.0,
    ),
}


def get_policy(dependency_type: DependencyType) -> ResiliencePolicy:
    """Return the default resilience policy for a dependency type."""
    return _DEFAULT_POLICIES[dependency_type]


# ---------------------------------------------------------------------------
# Registry of circuit breakers — one instance per dependency name
# ---------------------------------------------------------------------------

_breakers: dict[str, CircuitBreaker] = {}


def _get_or_create_breaker(
    dependency_name: str, config: CircuitBreakerConfig
) -> CircuitBreaker:
    """Return (or create) a shared circuit breaker for the given dependency."""
    if dependency_name not in _breakers:
        _breakers[dependency_name] = CircuitBreaker(dependency_name, config)
    return _breakers[dependency_name]


def get_breaker(dependency_name: str) -> CircuitBreaker | None:
    """Return the circuit breaker for a dependency, or None if not yet created."""
    return _breakers.get(dependency_name)


def reset_breakers() -> None:
    """Clear all breakers (useful for testing)."""
    _breakers.clear()


# ---------------------------------------------------------------------------
# resilient_call — the composed utility
# ---------------------------------------------------------------------------


async def resilient_call(
    fn: Callable[..., Awaitable[T]],
    *args: Any,
    dependency_name: str,
    dependency_type: DependencyType,
    policy: ResiliencePolicy | None = None,
    on_timeout: Callable[[], Awaitable[None] | None] | None = None,
    retryable: Callable[[Exception], bool] | None = None,
    **kwargs: Any,
) -> T:
    """Execute an async callable through the full resilience stack.

    Order of protection (outermost → innermost):
        1. **Circuit breaker** — fast-fails if the dependency is OPEN.
        2. **Retry with backoff** — retries transient failures.
        3. **Timeout** — enforces wall-clock deadline per attempt.

    Args:
        fn: The async callable to protect.
        *args: Positional arguments forwarded to ``fn``.
        dependency_name: Unique name identifying the dependency instance
            (e.g., ``"postgres_primary"``, ``"anthropic_claude"``).
        dependency_type: The category of external dependency.
        policy: Override the default policy. If ``None``, the default for
            ``dependency_type`` is used.
        on_timeout: Callback invoked when a single attempt times out.
        retryable: Predicate determining whether an exception is retryable.
            Defaults to retrying all exceptions except ``CircuitBreakerError``.
        **kwargs: Keyword arguments forwarded to ``fn``.

    Returns:
        The result of ``fn`` on the first successful attempt.

    Raises:
        CircuitBreakerError: If the circuit is OPEN (graceful degradation).
        RetryExhaustedError: If all retry attempts fail.
        asyncio.TimeoutError: If the final attempt times out (wrapped in
            RetryExhaustedError if retries are exhausted).
    """
    pol = policy or get_policy(dependency_type)
    breaker = _get_or_create_breaker(dependency_name, pol.circuit_breaker)

    # Default retryable predicate: retry everything except CircuitBreakerError.
    def _default_retryable(exc: Exception) -> bool:
        return not isinstance(exc, CircuitBreakerError)

    effective_retryable = retryable or _default_retryable

    async def _single_attempt() -> T:
        """One attempt through circuit breaker + timeout."""
        async with breaker, with_timeout(pol.timeout_seconds, on_timeout=on_timeout):
            result: T = await fn(*args, **kwargs)
            return result
        raise AssertionError("unreachable")  # pragma: no cover

    return await execute_with_retry(
        _single_attempt,
        config=pol.retry,
        retryable=effective_retryable,
    )
