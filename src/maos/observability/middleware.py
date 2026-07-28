"""FastAPI observability middleware for MAOS.

Injects OpenTelemetry trace context into every request, logs structured
request/response information, and records request duration metrics.

NO PHI or secrets are included in any logged or traced data (Req 9.5, 9.10).
Request/response bodies are never captured in telemetry.

Requirements: 10.5
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI, Request, Response
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from maos.observability.logging import (
    clear_correlation_ids,
    get_logger,
    set_task_id,
    set_tenant_id,
)
from maos.observability.metrics import tasks_submitted

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Custom middleware: correlation IDs + structured request logging
# ---------------------------------------------------------------------------
class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Middleware that injects trace context, sets correlation IDs, and logs
    every request/response with timing information.

    Sensitive headers (Authorization, Cookie) are never logged.
    """

    _SENSITIVE_HEADERS: frozenset[str] = frozenset(
        {"authorization", "cookie", "x-api-key"}
    )

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.perf_counter()

        # Extract tenant/task from headers if available (set by API layer)
        tenant_id = request.headers.get("x-tenant-id")
        task_id = request.headers.get("x-task-id")

        if tenant_id:
            set_tenant_id(tenant_id)
        if task_id:
            set_task_id(task_id)

        # Build safe header dict (strip sensitive values)
        safe_headers = self._safe_headers(request.headers)

        # Get current trace/span context
        span = trace.get_current_span()
        span_ctx = span.get_span_context()
        trace_id = format(span_ctx.trace_id, "032x") if span_ctx.trace_id else None

        logger.info(
            "request.start",
            method=request.method,
            path=request.url.path,
            query=str(request.url.query) if request.url.query else None,
            trace_id=trace_id,
            headers=safe_headers,
        )

        # Track task submissions
        if request.method == "POST" and request.url.path.rstrip("/").endswith("/tasks"):
            tasks_submitted.add(1, {"tenant_id": tenant_id or "unknown"})

        response: Response
        try:
            response = await call_next(request)
        except Exception:
            duration = time.perf_counter() - start
            logger.exception(
                "request.error",
                method=request.method,
                path=request.url.path,
                duration_s=round(duration, 4),
            )
            raise

        duration = time.perf_counter() - start

        logger.info(
            "request.end",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_s=round(duration, 4),
        )

        # Inject trace ID into response headers for client correlation
        if trace_id:
            response.headers["x-trace-id"] = trace_id

        # Clear correlation IDs at end of request lifecycle
        clear_correlation_ids()

        return response

    @staticmethod
    def _safe_headers(headers: Any) -> dict[str, str]:
        """Return headers with sensitive values redacted."""
        result: dict[str, str] = {}
        for key, value in headers.items():
            if key.lower() in ObservabilityMiddleware._SENSITIVE_HEADERS:
                result[key] = "[REDACTED]"
            else:
                result[key] = value
        return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def instrument_fastapi(app: FastAPI) -> None:
    """Attach OTel auto-instrumentation and custom middleware to a FastAPI app.

    Call after ``setup_observability()`` has configured providers.
    """
    # OTel auto-instrumentation creates spans for every HTTP request.
    FastAPIInstrumentor.instrument_app(app)

    # Custom middleware adds correlation IDs and structured logging.
    app.add_middleware(ObservabilityMiddleware)
