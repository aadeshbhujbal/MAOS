"""Resilience primitives — circuit breakers, retry, timeout, and composed policies.

This module provides per-dependency resilience for external dependencies:
- **Circuit breakers** (closed/open/half-open) to prevent cascading failures (Req 11.5).
- **Bounded exponential backoff with jitter** capped at max attempts (Req 15.4).
- **Timeout wrappers** that mark non-responsive units as ``timed_out`` (Req 11.4).
- **Pre-configured policies** composing all three primitives into a single
  ``resilient_call()`` for each external dependency type.

Requirements: 11.4, 11.5, 15.4.
"""

from maos.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitState,
)
from maos.resilience.policies import (
    DependencyType,
    ResiliencePolicy,
    get_policy,
    resilient_call,
)
from maos.resilience.retry import RetryConfig, RetryExhaustedError, retry_with_backoff
from maos.resilience.timeout import TimeoutCallback, TimeoutExpired, with_timeout

__all__ = [
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerError",
    "CircuitState",
    "DependencyType",
    "ResiliencePolicy",
    "RetryConfig",
    "RetryExhaustedError",
    "TimeoutCallback",
    "TimeoutExpired",
    "get_policy",
    "resilient_call",
    "retry_with_backoff",
    "with_timeout",
]
