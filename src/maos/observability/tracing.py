"""OpenTelemetry distributed tracing configuration for MAOS.

Sets up the OTel TracerProvider with a BatchSpanProcessor exporting to an
OTLP endpoint. Traces cover:
- Task intake and classification
- Routing decisions (Root → Sub-Orchestrator → Subagent)
- Subagent execution (bounded reasoning loops)
- LLM model calls (provider, model, tokens)
- MCP tool invocations

NO PHI or secrets are emitted as span attributes (Req 9.5, 9.10).

Requirements: 10.5
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# ---------------------------------------------------------------------------
# Module-level tracer cache
# ---------------------------------------------------------------------------
_tracer_provider: TracerProvider | None = None


def configure_tracing(
    *,
    service_name: str = "maos",
    environment: str = "development",
    otlp_endpoint: str | None = None,
    insecure: bool = True,
) -> TracerProvider:
    """Initialise and register the global OTel TracerProvider.

    Args:
        service_name: Logical service name attached to all spans.
        environment: Deployment environment (development/staging/production).
        otlp_endpoint: OTLP gRPC collector endpoint. If ``None``, uses an
            in-memory exporter (suitable for local dev / tests).
        insecure: Whether the gRPC connection uses TLS. Default ``True`` for
            local/dev; production should set this ``False``.

    Returns:
        The configured ``TracerProvider`` (also globally registered).
    """
    global _tracer_provider

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": "0.1.0",
            "deployment.environment": environment,
        }
    )

    provider = TracerProvider(resource=resource)

    if otlp_endpoint:
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=insecure)
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)
    # When no endpoint is set (local dev / tests), spans are recorded in the
    # provider but not exported. This avoids external dependencies while still
    # enabling in-process trace propagation.
    trace.set_tracer_provider(provider)
    _tracer_provider = provider
    return provider


def get_tracer(name: str = "maos") -> trace.Tracer:
    """Return a named tracer from the global provider."""
    return trace.get_tracer(name)


def shutdown_tracing() -> None:
    """Flush and shut down the tracer provider (call on service shutdown)."""
    global _tracer_provider
    if _tracer_provider is not None:
        _tracer_provider.shutdown()
        _tracer_provider = None
