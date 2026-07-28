"""Observability: structured logging, distributed tracing, and metrics.

Call ``setup_observability()`` once at service startup to initialise all
telemetry providers. Then use ``instrument_fastapi(app)`` to attach middleware
to the FastAPI application instance.

Requirements: 10.5, TC-10
"""

from __future__ import annotations

import os

from maos.observability.agent_tracing import (
    AgentTracer,
    AgentTracingCallbackHandler,
    add_sub_subtask_breadcrumb,
    add_subtask_breadcrumb,
    add_task_breadcrumb,
    capture_exception,
    configure_sentry,
    get_agent_tracing_handler,
    init_agent_tracing,
    init_sentry,
    phi_scrubber,
    set_sentry_task_context,
)
from maos.observability.logging import (
    clear_correlation_ids,
    configure_logging,
    get_logger,
    set_task_id,
    set_tenant_id,
)
from maos.observability.metrics import (
    configure_metrics,
    get_meter,
    mcp_invocations_total,
    model_call_duration,
    model_calls_total,
    routing_decisions_total,
    shutdown_metrics,
    tasks_completed,
    tasks_failed,
    tasks_submitted,
)
from maos.observability.middleware import instrument_fastapi
from maos.observability.tracing import (
    configure_tracing,
    get_tracer,
    shutdown_tracing,
)


def setup_observability(
    *,
    service_name: str = "maos",
    environment: str = "development",
    release: str = "maos@0.1.0",
    log_level: str = "INFO",
    json_logs: bool = True,
    otlp_endpoint: str | None = None,
    otlp_insecure: bool = True,
) -> None:
    """Initialise all observability providers (logging, tracing, metrics).

    This function reads optional environment variables as overrides:
    - ``OTEL_EXPORTER_OTLP_ENDPOINT`` — OTLP collector endpoint
    - ``OTEL_EXPORTER_OTLP_INSECURE`` — whether gRPC uses TLS (``true``/``false``)
    - ``MAOS_LOG_LEVEL`` — log level override
    - ``MAOS_JSON_LOGS`` — ``true``/``false`` for JSON vs console output
    - ``SENTRY_DSN`` — if set, Sentry error capture is initialised
    - ``LANGSMITH_API_KEY`` — if set, LangSmith agent tracing is initialised
    - ``LANGFUSE_HOST`` — if set (and no LangSmith key), Langfuse tracing is
      initialised

    Args:
        service_name: Logical service name for all telemetry.
        environment: Deployment environment label.
        release: Release identifier for Sentry.
        log_level: Minimum log level.
        json_logs: Whether to emit JSON-formatted logs.
        otlp_endpoint: OTLP gRPC endpoint. Falls back to env var.
        otlp_insecure: gRPC TLS toggle.
    """
    # Environment overrides
    endpoint = otlp_endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    insecure_env = os.environ.get("OTEL_EXPORTER_OTLP_INSECURE", "").lower()
    if insecure_env in ("true", "1"):
        otlp_insecure = True
    elif insecure_env in ("false", "0"):
        otlp_insecure = False

    level = os.environ.get("MAOS_LOG_LEVEL", log_level)
    json_env = os.environ.get("MAOS_JSON_LOGS", "").lower()
    if json_env in ("true", "1"):
        json_logs = True
    elif json_env in ("false", "0"):
        json_logs = False

    # 1. Structured logging
    configure_logging(log_level=level, json_output=json_logs)

    # 2. Distributed tracing (OpenTelemetry)
    configure_tracing(
        service_name=service_name,
        environment=environment,
        otlp_endpoint=endpoint,
        insecure=otlp_insecure,
    )

    # 3. Metrics (OpenTelemetry)
    configure_metrics(
        service_name=service_name,
        environment=environment,
        otlp_endpoint=endpoint,
        insecure=otlp_insecure,
    )

    # 4. Sentry error capture — only if SENTRY_DSN is configured (TC-10)
    if os.environ.get("SENTRY_DSN"):
        configure_sentry(
            environment=environment,
            release=release,
        )

    # 5. Agent tracing (LangSmith/Langfuse) — if API keys are configured (TC-10)
    if os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGFUSE_HOST"):
        init_agent_tracing()


def shutdown_observability() -> None:
    """Flush and shut down all telemetry providers. Call on service shutdown."""
    shutdown_tracing()
    shutdown_metrics()


__all__ = [
    "AgentTracer",
    "AgentTracingCallbackHandler",
    "add_sub_subtask_breadcrumb",
    "add_subtask_breadcrumb",
    "add_task_breadcrumb",
    "capture_exception",
    "clear_correlation_ids",
    "configure_logging",
    "configure_metrics",
    "configure_sentry",
    "configure_tracing",
    "get_agent_tracing_handler",
    "get_logger",
    "get_meter",
    "get_tracer",
    "init_agent_tracing",
    "init_sentry",
    "instrument_fastapi",
    "mcp_invocations_total",
    "model_call_duration",
    "model_calls_total",
    "phi_scrubber",
    "routing_decisions_total",
    "set_sentry_task_context",
    "set_task_id",
    "set_tenant_id",
    "setup_observability",
    "shutdown_metrics",
    "shutdown_observability",
    "shutdown_tracing",
    "tasks_completed",
    "tasks_failed",
    "tasks_submitted",
]
