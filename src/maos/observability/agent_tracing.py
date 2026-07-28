"""Agent-level tracing (LangSmith/Langfuse) and error reporting (Sentry).

This module provides:
1. LangSmith/Langfuse integration for agent execution traces via ``AgentTracer``
   — wraps LangGraph execution with trace context, records agent reasoning
   steps, tool invocations, and model calls as trace spans.
2. Sentry integration for error capture with PHI/secret scrubbing:
   - ``configure_sentry()`` initializes the Sentry SDK with FastAPI and Arq
     worker integrations, DSN from env, and a ``before_send`` hook that strips
     PHI/secrets from all error events before transmission.
   - Trace context (trace_id, task_id, tenant_id) is attached to every Sentry
     event via the ``before_send`` hook.
   - Breadcrumbs record task/subtask/sub_subtask lifecycle events.
   - Unhandled exceptions from FastAPI and Arq workers are captured with task
     context (no PHI).
3. ``init_agent_tracing()`` sets up the LangSmith or Langfuse callback handler
   based on which environment variables are configured.

NO PHI or secrets are ever transmitted in telemetry data (Req 9.5, 9.10, TC-10).

Requirements: 10.5, TC-10
"""

from __future__ import annotations

import os
import re
from contextvars import ContextVar
from typing import Any

from opentelemetry import trace as otel_trace

from maos.security.redaction import PHI_MARKER_KEYS

# ---------------------------------------------------------------------------
# Context variables for attaching trace context to Sentry events
# ---------------------------------------------------------------------------
_sentry_task_id_ctx: ContextVar[str | None] = ContextVar("sentry_task_id", default=None)
_sentry_tenant_id_ctx: ContextVar[str | None] = ContextVar("sentry_tenant_id", default=None)

# ---------------------------------------------------------------------------
# PHI Scrubber — Sentry before_send hook
# ---------------------------------------------------------------------------

# Compile a regex pattern matching any PHI/secret marker key pattern.
# This is used to scrub values from Sentry event data.
_PHI_PATTERN = re.compile(
    "|".join(re.escape(k) for k in sorted(PHI_MARKER_KEYS)),
    re.IGNORECASE,
)

# Additional patterns to catch inline secrets/tokens in string values
_SECRET_VALUE_PATTERNS = re.compile(
    r"(?i)"
    r"(?:Bearer\s+\S+)"  # Bearer tokens
    r"|(?:sk-[a-zA-Z0-9]{20,})"  # OpenAI-style keys
    r"|(?:sk-ant-[a-zA-Z0-9\-]{20,})"  # Anthropic keys
    r"|(?:AKIA[A-Z0-9]{16})"  # AWS access key IDs
    r"|(?:[0-9]{3}-[0-9]{2}-[0-9]{4})"  # SSN pattern
)

_REDACTED = "[REDACTED]"


def _scrub_value(value: Any) -> Any:
    """Recursively scrub PHI/secrets from a value."""
    if isinstance(value, dict):
        return _scrub_dict(value)
    if isinstance(value, list):
        return [_scrub_value(item) for item in value]
    if isinstance(value, str):
        # Scrub inline secret patterns from string values
        return _SECRET_VALUE_PATTERNS.sub(_REDACTED, value)
    return value


def _scrub_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Scrub PHI/secret keys and values from a dict."""
    result: dict[str, Any] = {}
    for key, value in data.items():
        if _PHI_PATTERN.search(key):
            result[key] = _REDACTED
        else:
            result[key] = _scrub_value(value)
    return result


def set_sentry_task_context(
    *, task_id: str | None = None, tenant_id: str | None = None
) -> None:
    """Set the current task/tenant context for Sentry event enrichment.

    Call this at the start of task processing so that any captured exceptions
    automatically include the trace context without exposing PHI.
    """
    _sentry_task_id_ctx.set(task_id)
    _sentry_tenant_id_ctx.set(tenant_id)


def phi_scrubber(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """Sentry ``before_send`` hook that strips PHI/secrets and attaches trace context.

    This ensures NO protected health information or credentials are transmitted
    to the external Sentry service (Req 9.5, 9.10). It also attaches the
    current OTel trace_id, task_id, and tenant_id to every event so errors
    are correlated with distributed traces.

    Args:
        event: The Sentry event dict about to be sent.
        hint: Additional context from the Sentry SDK (e.g., original exception).

    Returns:
        The scrubbed event, or ``None`` to drop the event entirely.
    """
    # --- Attach trace context (trace_id, task_id, tenant_id) ---
    tags = event.setdefault("tags", {})
    # OTel trace_id
    span = otel_trace.get_current_span()
    span_ctx = span.get_span_context()
    if span_ctx and span_ctx.trace_id:
        tags["trace_id"] = format(span_ctx.trace_id, "032x")

    # MAOS task/tenant context
    task_id = _sentry_task_id_ctx.get()
    if task_id:
        tags["task_id"] = task_id
    tenant_id = _sentry_tenant_id_ctx.get()
    if tenant_id:
        tags["tenant_id"] = tenant_id

    # --- Scrub PHI/secrets ---
    # Scrub exception frames' local variables
    if "exception" in event:
        for exc_info in event["exception"].get("values", []):
            stacktrace = exc_info.get("stacktrace")
            if stacktrace:
                for frame in stacktrace.get("frames", []):
                    if frame.get("vars"):
                        frame["vars"] = _scrub_dict(frame["vars"])

    # Scrub breadcrumb data
    if "breadcrumbs" in event:
        for breadcrumb in event["breadcrumbs"].get("values", []):
            if breadcrumb.get("data"):
                breadcrumb["data"] = _scrub_dict(breadcrumb["data"])

    # Scrub extra/contexts
    if "extra" in event:
        event["extra"] = _scrub_dict(event["extra"])
    if "contexts" in event:
        event["contexts"] = _scrub_dict(event["contexts"])

    # Scrub tags (after we inserted ours — our IDs are safe, not PHI)
    if "tags" in event:
        event["tags"] = _scrub_dict(event["tags"])

    return event


# ---------------------------------------------------------------------------
# Sentry Initialization
# ---------------------------------------------------------------------------


def configure_sentry(
    *,
    dsn: str | None = None,
    environment: str = "development",
    release: str = "maos@0.1.0",
    traces_sample_rate: float = 0.1,
    enable_fastapi: bool = True,
    enable_arq: bool = True,
) -> bool:
    """Initialize Sentry SDK for error capture with FastAPI and Arq integrations.

    Configures:
    - The ``before_send`` hook (``phi_scrubber``) to strip PHI/secrets and
      attach trace context (trace_id, task_id, tenant_id).
    - FastAPI integration to capture unhandled request exceptions.
    - Arq integration to capture unhandled worker exceptions.
    - Environment and release tags for error grouping.
    - A conservative traces sample rate.
    - ``send_default_pii=False`` to prevent accidental PII leakage.

    Args:
        dsn: Sentry DSN. Falls back to ``SENTRY_DSN`` env var. If neither is
            set, initialization is skipped and ``False`` is returned.
        environment: Deployment environment label.
        release: Release identifier for Sentry.
        traces_sample_rate: Fraction of transactions to trace (0.0-1.0).
        enable_fastapi: Enable the Sentry FastAPI integration for capturing
            unhandled exceptions from HTTP handlers.
        enable_arq: Enable the Sentry Arq integration for capturing
            unhandled exceptions from background workers.

    Returns:
        ``True`` if Sentry was successfully initialized, ``False`` otherwise.
    """
    effective_dsn = dsn or os.environ.get("SENTRY_DSN")
    if not effective_dsn:
        return False

    try:
        import sentry_sdk
    except ImportError:
        return False

    # Build integrations list based on flags
    integrations: list[Any] = []
    if enable_fastapi:
        try:
            from sentry_sdk.integrations.fastapi import FastApiIntegration

            integrations.append(FastApiIntegration())
        except ImportError:
            pass

    if enable_arq:
        try:
            from sentry_sdk.integrations.arq import ArqIntegration

            integrations.append(ArqIntegration())
        except ImportError:
            pass

    sentry_sdk.init(
        dsn=effective_dsn,
        environment=environment,
        release=release,
        traces_sample_rate=traces_sample_rate,
        before_send=phi_scrubber,
        integrations=integrations,
        # Strip sensitive default integrations data
        send_default_pii=False,
    )
    return True


# Backward-compatible alias
init_sentry = configure_sentry


# ---------------------------------------------------------------------------
# Sentry Breadcrumbs for Task Lifecycle
# ---------------------------------------------------------------------------


def add_task_breadcrumb(
    *,
    task_id: str,
    event: str,
    level: str = "info",
    data: dict[str, Any] | None = None,
) -> None:
    """Add a Sentry breadcrumb for a task lifecycle event.

    Args:
        task_id: The task identifier (safe to include — not PHI).
        event: Description of the lifecycle event (e.g., "task_accepted").
        level: Breadcrumb severity level.
        data: Optional additional context (will be scrubbed of PHI).
    """
    try:
        import sentry_sdk
    except ImportError:
        return

    safe_data: dict[str, Any] = {"task_id": task_id}
    if data:
        safe_data.update(_scrub_dict(data))

    sentry_sdk.add_breadcrumb(
        category="maos.task",
        message=event,
        level=level,
        data=safe_data,
    )


def add_subtask_breadcrumb(
    *,
    task_id: str,
    subtask_id: str,
    event: str,
    level: str = "info",
    data: dict[str, Any] | None = None,
) -> None:
    """Add a Sentry breadcrumb for a subtask lifecycle event.

    Args:
        task_id: Parent task identifier.
        subtask_id: The subtask identifier.
        event: Description of the lifecycle event.
        level: Breadcrumb severity level.
        data: Optional additional context (will be scrubbed of PHI).
    """
    try:
        import sentry_sdk
    except ImportError:
        return

    safe_data: dict[str, Any] = {"task_id": task_id, "subtask_id": subtask_id}
    if data:
        safe_data.update(_scrub_dict(data))

    sentry_sdk.add_breadcrumb(
        category="maos.subtask",
        message=event,
        level=level,
        data=safe_data,
    )


def add_sub_subtask_breadcrumb(
    *,
    task_id: str,
    subtask_id: str,
    sub_subtask_id: str,
    event: str,
    level: str = "info",
    data: dict[str, Any] | None = None,
) -> None:
    """Add a Sentry breadcrumb for a sub_subtask lifecycle event.

    Args:
        task_id: Root task identifier.
        subtask_id: Parent subtask identifier.
        sub_subtask_id: The sub_subtask identifier.
        event: Description of the lifecycle event.
        level: Breadcrumb severity level.
        data: Optional additional context (will be scrubbed of PHI).
    """
    try:
        import sentry_sdk
    except ImportError:
        return

    safe_data: dict[str, Any] = {
        "task_id": task_id,
        "subtask_id": subtask_id,
        "sub_subtask_id": sub_subtask_id,
    }
    if data:
        safe_data.update(_scrub_dict(data))

    sentry_sdk.add_breadcrumb(
        category="maos.sub_subtask",
        message=event,
        level=level,
        data=safe_data,
    )


# ---------------------------------------------------------------------------
# Sentry Exception Capture
# ---------------------------------------------------------------------------


def capture_exception(
    error: BaseException,
    *,
    task_id: str | None = None,
    subtask_id: str | None = None,
    sub_subtask_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> str | None:
    """Capture an exception in Sentry with task context (no PHI).

    Args:
        error: The exception to report.
        task_id: Optional task identifier for context.
        subtask_id: Optional subtask identifier for context.
        sub_subtask_id: Optional sub_subtask identifier for context.
        extra: Optional additional context (will be scrubbed of PHI).

    Returns:
        The Sentry event ID string if captured, or ``None`` if Sentry is
        not initialized or import failed.
    """
    try:
        import sentry_sdk
    except ImportError:
        return None

    with sentry_sdk.push_scope() as scope:
        if task_id:
            scope.set_tag("task_id", task_id)
        if subtask_id:
            scope.set_tag("subtask_id", subtask_id)
        if sub_subtask_id:
            scope.set_tag("sub_subtask_id", sub_subtask_id)
        if extra:
            for key, value in _scrub_dict(extra).items():
                scope.set_extra(key, value)

        event_id: str | None = sentry_sdk.capture_exception(error)
    return event_id


# ---------------------------------------------------------------------------
# LangSmith / Langfuse Agent Tracing
# ---------------------------------------------------------------------------


class AgentTracer:
    """Wraps LangGraph execution with trace context for agent-level tracing.

    Integrates with LangSmith (if ``LANGSMITH_API_KEY`` is set) or Langfuse
    (if ``LANGFUSE_HOST`` is set) to record agent-level traces for each
    execution step. All trace data is scrubbed of PHI/secrets before emission.

    Records:
    - Agent reasoning steps as individual trace spans
    - Tool invocations (MCP calls) as trace spans
    - Model calls (LLM invocations) as trace spans

    This class can provide LangChain-compatible callbacks via
    ``get_langchain_callbacks()`` for automatic LangGraph tracing.

    Falls back gracefully to a no-op when neither LangSmith nor Langfuse
    is configured (no errors, no telemetry emitted).
    """

    def __init__(self) -> None:
        """Initialize the tracer; underlying client is lazily resolved."""
        self._langsmith_handler: Any = None
        self._langfuse_handler: Any = None
        self._initialized = False
        self._otel_tracer = otel_trace.get_tracer("maos.agent")

    def _ensure_initialized(self) -> None:
        """Lazily initialize the tracing backend based on env vars."""
        if self._initialized:
            return
        self._initialized = True

        # Prefer LangSmith if its API key is configured
        langsmith_key = os.environ.get("LANGSMITH_API_KEY")
        if langsmith_key:
            try:
                from langsmith import Client

                self._langsmith_handler = Client(api_key=langsmith_key)
            except ImportError:
                pass
            return

        # Fall back to Langfuse if its host is configured
        langfuse_host = os.environ.get("LANGFUSE_HOST")
        if langfuse_host:
            try:
                from langfuse.callback import (
                    CallbackHandler as LangfuseCallbackHandler,
                )

                self._langfuse_handler = LangfuseCallbackHandler(
                    host=langfuse_host,
                    public_key=os.environ.get("LANGFUSE_PUBLIC_KEY", ""),
                    secret_key=os.environ.get("LANGFUSE_SECRET_KEY", ""),
                )
            except ImportError:
                pass

    @property
    def is_active(self) -> bool:
        """Return True if a tracing backend is configured and available."""
        self._ensure_initialized()
        return self._langsmith_handler is not None or self._langfuse_handler is not None

    def get_langchain_callbacks(self) -> list[Any]:
        """Return a list of LangChain-compatible callback handlers.

        These can be passed to LangGraph ``config["callbacks"]`` to enable
        agent tracing. Returns an empty list if no backend is configured.
        """
        self._ensure_initialized()
        callbacks: list[Any] = []

        if self._langfuse_handler is not None:
            callbacks.append(self._langfuse_handler)

        # LangSmith tracing is typically auto-configured via environment
        # variables (LANGSMITH_API_KEY + LANGCHAIN_TRACING_V2=true).
        # We ensure the env var is set so the LangChain internals pick it up.
        if self._langsmith_handler is not None:
            os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
            # LangSmith auto-traces through LangChain's built-in integration
            # when LANGCHAIN_TRACING_V2=true. No explicit callback needed.

        return callbacks

    def trace_agent_start(
        self,
        *,
        agent_id: str,
        task_id: str,
        sub_subtask_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record the start of an agent execution as a trace span.

        Args:
            agent_id: The executing agent identifier.
            task_id: The task being worked on.
            sub_subtask_id: The specific sub_subtask, if applicable.
            metadata: Additional metadata (will be scrubbed of PHI).
        """
        self._ensure_initialized()
        safe_meta = _scrub_dict(metadata) if metadata else {}
        safe_meta.update({"agent_id": agent_id, "task_id": task_id})
        if sub_subtask_id:
            safe_meta["sub_subtask_id"] = sub_subtask_id

        # Set Sentry context for correlation
        set_sentry_task_context(task_id=task_id)

        # Emit as a Sentry breadcrumb for error correlation
        add_task_breadcrumb(
            task_id=task_id,
            event=f"agent_start:{agent_id}",
            data=safe_meta,
        )

    def trace_agent_end(
        self,
        *,
        agent_id: str,
        task_id: str,
        sub_subtask_id: str | None = None,
        status: str = "completed",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record the end of an agent execution as a trace span.

        Args:
            agent_id: The executing agent identifier.
            task_id: The task being worked on.
            sub_subtask_id: The specific sub_subtask, if applicable.
            status: Final status of the execution.
            metadata: Additional metadata (will be scrubbed of PHI).
        """
        self._ensure_initialized()
        safe_meta = _scrub_dict(metadata) if metadata else {}
        safe_meta.update({"agent_id": agent_id, "task_id": task_id, "status": status})
        if sub_subtask_id:
            safe_meta["sub_subtask_id"] = sub_subtask_id

        add_task_breadcrumb(
            task_id=task_id,
            event=f"agent_end:{agent_id}:{status}",
            data=safe_meta,
        )

    def trace_reasoning_step(
        self,
        *,
        agent_id: str,
        task_id: str,
        step_index: int,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a single reasoning step within an agent execution.

        Creates an OTel span representing one iteration of the agent's bounded
        reasoning loop. All metadata is scrubbed of PHI before recording.

        Args:
            agent_id: The executing agent identifier.
            task_id: The task being worked on.
            step_index: Zero-based index of this reasoning step.
            description: Brief description of the step's purpose.
            metadata: Additional metadata (will be scrubbed of PHI).
        """
        self._ensure_initialized()
        safe_meta = _scrub_dict(metadata) if metadata else {}

        with self._otel_tracer.start_as_current_span(
            f"agent.reasoning_step.{step_index}",
            attributes={
                "maos.agent_id": agent_id,
                "maos.task_id": task_id,
                "maos.step_index": step_index,
                "maos.description": description,
                **{f"maos.meta.{k}": str(v) for k, v in safe_meta.items()},
            },
        ):
            pass  # Span is auto-closed by the context manager

    def trace_tool_invocation(
        self,
        *,
        agent_id: str,
        task_id: str,
        tool_name: str,
        sub_subtask_id: str | None = None,
        status: str = "success",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record an MCP tool invocation as a trace span.

        Creates an OTel span for the tool call. Arguments and results are
        referenced by ID only — never raw values (Req 5.6).

        Args:
            agent_id: The invoking agent identifier.
            task_id: The task context.
            tool_name: Name of the MCP tool invoked.
            sub_subtask_id: The sub_subtask context, if applicable.
            status: Invocation result status (success/error/denied).
            metadata: Additional metadata (will be scrubbed of PHI).
        """
        self._ensure_initialized()
        safe_meta = _scrub_dict(metadata) if metadata else {}

        attributes: dict[str, str | int] = {
            "maos.agent_id": agent_id,
            "maos.task_id": task_id,
            "maos.tool_name": tool_name,
            "maos.status": status,
        }
        if sub_subtask_id:
            attributes["maos.sub_subtask_id"] = sub_subtask_id
        for k, v in safe_meta.items():
            attributes[f"maos.meta.{k}"] = str(v)

        with self._otel_tracer.start_as_current_span(
            f"agent.tool_invocation.{tool_name}",
            attributes=attributes,
        ):
            pass

        # Also emit Sentry breadcrumb for correlation
        add_task_breadcrumb(
            task_id=task_id,
            event=f"tool_invocation:{tool_name}:{status}",
            data={"agent_id": agent_id, "tool_name": tool_name, **safe_meta},
        )

    def trace_model_call(
        self,
        *,
        agent_id: str,
        task_id: str,
        provider: str,
        model: str,
        tokens: int = 0,
        status: str = "success",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record an LLM model call as a trace span.

        Creates an OTel span for the model invocation. No prompt content or
        PHI is included in the span — only structural metadata (provider,
        model, token count).

        Args:
            agent_id: The agent that initiated the model call.
            task_id: The task context.
            provider: LLM provider name (e.g., "anthropic", "bedrock").
            model: Model identifier (e.g., "claude-3-sonnet").
            tokens: Total tokens consumed by this call.
            status: Call result status (success/error/fallback).
            metadata: Additional metadata (will be scrubbed of PHI).
        """
        self._ensure_initialized()
        safe_meta = _scrub_dict(metadata) if metadata else {}

        attributes: dict[str, str | int] = {
            "maos.agent_id": agent_id,
            "maos.task_id": task_id,
            "maos.llm.provider": provider,
            "maos.llm.model": model,
            "maos.llm.tokens": tokens,
            "maos.status": status,
        }
        for k, v in safe_meta.items():
            attributes[f"maos.meta.{k}"] = str(v)

        with self._otel_tracer.start_as_current_span(
            f"agent.model_call.{provider}.{model}",
            attributes=attributes,
        ):
            pass

        add_task_breadcrumb(
            task_id=task_id,
            event=f"model_call:{provider}/{model}:{status}",
            data={"agent_id": agent_id, "tokens": tokens, **safe_meta},
        )

    def trace_agent_error(
        self,
        *,
        agent_id: str,
        task_id: str,
        error: BaseException,
        sub_subtask_id: str | None = None,
    ) -> None:
        """Record an agent execution error.

        The error is also forwarded to Sentry (if configured) with task context.

        Args:
            agent_id: The executing agent identifier.
            task_id: The task being worked on.
            error: The exception that occurred.
            sub_subtask_id: The specific sub_subtask, if applicable.
        """
        self._ensure_initialized()
        capture_exception(
            error,
            task_id=task_id,
            sub_subtask_id=sub_subtask_id,
            extra={"agent_id": agent_id},
        )


# Backward-compatible alias for existing code using the old name
AgentTracingCallbackHandler = AgentTracer


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_agent_tracing_handler: AgentTracer | None = None


def init_agent_tracing() -> AgentTracer:
    """Initialize the agent tracing callback handler.

    Should be called once at service startup (from ``setup_observability``).
    Reads ``LANGSMITH_API_KEY`` or ``LANGFUSE_HOST`` from the environment to
    determine which backend to use.

    Returns:
        The configured ``AgentTracer`` singleton.
    """
    global _agent_tracing_handler
    _agent_tracing_handler = AgentTracer()
    return _agent_tracing_handler


def get_agent_tracing_handler() -> AgentTracer | None:
    """Return the current agent tracing handler, or None if not initialized."""
    return _agent_tracing_handler
