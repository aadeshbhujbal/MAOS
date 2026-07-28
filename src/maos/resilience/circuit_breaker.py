"""Per-dependency circuit breaker with closed/open/half-open states (Req 11.5).

The circuit breaker prevents cascading failures by tracking consecutive failures
per external dependency and switching to an OPEN state after a configurable
threshold.  After a recovery timeout the breaker enters HALF_OPEN, allowing a
limited number of probe calls.  Success in HALF_OPEN resets the breaker to
CLOSED; failure reopens immediately.

Requirements: 11.5.
"""

from __future__ import annotations

import asyncio
import functools
import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# State enum
# ---------------------------------------------------------------------------


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class CircuitBreakerConfig(BaseModel):
    """Configuration for a single circuit breaker instance.

    Attributes:
        failure_threshold: Number of consecutive failures before opening.
        recovery_timeout: Seconds to wait in OPEN before transitioning to HALF_OPEN.
        half_open_max_calls: Maximum concurrent probe calls allowed in HALF_OPEN.
    """

    failure_threshold: int = Field(default=5, gt=0)
    recovery_timeout: float = Field(default=30.0, gt=0)
    half_open_max_calls: int = Field(default=1, gt=0)


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class CircuitBreakerError(Exception):
    """Raised when a call is rejected because the circuit is OPEN."""

    def __init__(self, dependency: str, retry_after: float) -> None:
        self.dependency = dependency
        self.retry_after = retry_after
        super().__init__(
            f"Circuit breaker OPEN for '{dependency}'; retry after {retry_after:.1f}s"
        )


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------


class CircuitBreaker:
    """Async circuit breaker tracking failures per dependency name.

    Usage as an async context manager::

        breaker = CircuitBreaker("postgres", config)
        async with breaker:
            result = await call_postgres(...)

    Or as a decorator::

        @breaker.decorate
        async def call_postgres(...): ...

    The breaker is thread-safe for single-threaded asyncio (GIL + cooperative
    scheduling). For multi-process deployments, consider a shared state store.
    """

    def __init__(self, dependency: str, config: CircuitBreakerConfig | None = None) -> None:
        self._dependency = dependency
        self._config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count: int = 0
        self._last_failure_time: float = 0.0
        self._half_open_calls: int = 0
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def dependency(self) -> str:
        """The dependency name this breaker protects."""
        return self._dependency

    @property
    def state(self) -> CircuitState:
        """Current breaker state (may transition on read if recovery elapsed)."""
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self._config.recovery_timeout:
                return CircuitState.HALF_OPEN
        return self._state

    @property
    def failure_count(self) -> int:
        """Number of consecutive failures recorded."""
        return self._failure_count

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> CircuitBreaker:
        await self._before_call()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> bool:
        if exc_type is None:
            await self._on_success()
        else:
            await self._on_failure()
        # Never suppress the exception — let it propagate.
        return False

    # ------------------------------------------------------------------
    # Decorator
    # ------------------------------------------------------------------

    def decorate(self, fn: Any) -> Any:
        """Wrap an async callable with this circuit breaker."""

        @functools.wraps(fn)
        async def _wrapper(*args: Any, **kwargs: Any) -> Any:
            async with self:
                return await fn(*args, **kwargs)

        return _wrapper

    # ------------------------------------------------------------------
    # Internal state transitions
    # ------------------------------------------------------------------

    async def _before_call(self) -> None:
        """Determine if a call is allowed; raise if the breaker is OPEN."""
        async with self._lock:
            current = self.state
            if current == CircuitState.OPEN:
                retry_after = self._config.recovery_timeout - (
                    time.monotonic() - self._last_failure_time
                )
                raise CircuitBreakerError(self._dependency, max(0.0, retry_after))

            if current == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self._config.half_open_max_calls:
                    raise CircuitBreakerError(self._dependency, self._config.recovery_timeout)
                self._half_open_calls += 1

            # Transition state if needed (OPEN -> HALF_OPEN on recovery timeout).
            if self._state == CircuitState.OPEN:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 1

    async def _on_success(self) -> None:
        """Record a successful call; reset the breaker to CLOSED."""
        async with self._lock:
            self._failure_count = 0
            self._half_open_calls = 0
            self._state = CircuitState.CLOSED

    async def _on_failure(self) -> None:
        """Record a failed call; open the breaker if threshold is exceeded."""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                # Single failure in half-open immediately reopens.
                self._state = CircuitState.OPEN
                self._half_open_calls = 0
            elif self._failure_count >= self._config.failure_threshold:
                self._state = CircuitState.OPEN
                self._half_open_calls = 0

    # ------------------------------------------------------------------
    # Manual controls (for testing / administrative use)
    # ------------------------------------------------------------------

    async def reset(self) -> None:
        """Force the breaker back to CLOSED (e.g., after manual recovery)."""
        async with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._half_open_calls = 0

    async def trip(self) -> None:
        """Force the breaker to OPEN (e.g., proactive protection)."""
        async with self._lock:
            self._state = CircuitState.OPEN
            self._last_failure_time = time.monotonic()
