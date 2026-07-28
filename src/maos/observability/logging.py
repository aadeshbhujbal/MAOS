"""Structured logging configuration for MAOS.

Uses structlog configured for JSON output with correlation IDs injected from
the OpenTelemetry trace context. Every log event automatically includes:
- trace_id, span_id (from OTel)
- task_id, tenant_id (from contextvars, when set by middleware / orchestration)

PHI and secrets are NEVER logged. Field names that could contain sensitive data
are filtered at the processor level (Req 9.5, 9.10).

Requirements: 10.5
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any

import structlog
from opentelemetry import trace

# ---------------------------------------------------------------------------
# Context variables for correlation IDs injected during request/task handling
# ---------------------------------------------------------------------------
_task_id_ctx: ContextVar[str | None] = ContextVar("task_id", default=None)
_tenant_id_ctx: ContextVar[str | None] = ContextVar("tenant_id", default=None)


def set_task_id(task_id: str) -> None:
    """Set the current task_id in context for log correlation."""
    _task_id_ctx.set(task_id)


def set_tenant_id(tenant_id: str) -> None:
    """Set the current tenant_id in context for log correlation."""
    _tenant_id_ctx.set(tenant_id)


def clear_correlation_ids() -> None:
    """Clear correlation IDs (e.g. at request end)."""
    _task_id_ctx.set(None)
    _tenant_id_ctx.set(None)


# ---------------------------------------------------------------------------
# Sensitive field filter — ensures NO PHI/secrets appear in logs
# ---------------------------------------------------------------------------
_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "secret",
        "token",
        "api_key",
        "authorization",
        "phi",
        "ssn",
        "dob",
        "patient_name",
        "medical_record",
        "credit_card",
    }
)


def _redact_sensitive(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Remove or redact any sensitive fields from log events."""
    for key in list(event_dict.keys()):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = "[REDACTED]"
    return event_dict


# ---------------------------------------------------------------------------
# Inject OTel trace context and MAOS correlation IDs
# ---------------------------------------------------------------------------
def _inject_trace_context(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Inject OpenTelemetry trace_id and span_id into every log event."""
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx and ctx.trace_id:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    else:
        event_dict["trace_id"] = None
        event_dict["span_id"] = None

    # MAOS-level correlation IDs
    event_dict["task_id"] = _task_id_ctx.get()
    event_dict["tenant_id"] = _tenant_id_ctx.get()

    return event_dict


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def configure_logging(*, log_level: str = "INFO", json_output: bool = True) -> None:
    """Configure structlog with JSON rendering and OTel correlation.

    Call once at service startup (from ``setup_observability``).
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        _inject_trace_context,
        _redact_sensitive,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_output:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure the stdlib root logger so third-party libraries also emit
    # structured output through structlog's formatter.
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            *shared_processors,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger. Use throughout MAOS instead of stdlib."""
    return structlog.get_logger(name)  # type: ignore[no-any-return]
