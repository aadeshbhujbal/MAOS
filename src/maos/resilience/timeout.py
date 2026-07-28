"""Timeout wrapper that marks non-responsive units as ``timed_out`` (Req 11.4).

Provides an async context manager wrapping ``asyncio.timeout``.  On timeout the
manager invokes a user-supplied callback so the orchestrator can mark the
affected work unit's state to ``timed_out`` and treat it as a failed attempt.

Requirements: 11.4.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

# Re-export the stdlib TimeoutError so consumers can import from this module.
TimeoutExpired = asyncio.TimeoutError

# Type alias for the timeout callback.
# Called with no arguments when a timeout occurs.  May be an async or sync
# function — we normalise below.
TimeoutCallback = Callable[[], Awaitable[None] | None]


@asynccontextmanager
async def with_timeout(
    seconds: float,
    *,
    on_timeout: TimeoutCallback | None = None,
) -> AsyncIterator[None]:
    """Async context manager that enforces a wall-clock timeout.

    Usage::

        async with with_timeout(5.0, on_timeout=mark_timed_out):
            result = await long_running_call()

    Args:
        seconds: Maximum wall-clock seconds to allow the wrapped block.
        on_timeout: Optional callback invoked when the timeout fires.
            If the callback is a coroutine function, it is awaited.
            The callback is responsible for marking the work unit as
            ``timed_out`` via the state machine.

    Raises:
        asyncio.TimeoutError: Propagated after the callback runs so the
            caller sees the timeout.
    """
    try:
        async with asyncio.timeout(seconds):
            yield
    except TimeoutError:
        if on_timeout is not None:
            result = on_timeout()
            if asyncio.iscoroutine(result):
                await result
        raise
