"""OpenTelemetry metrics configuration for MAOS.

Defines counters and histograms covering the key operational signals:
- tasks_submitted / tasks_completed / tasks_failed
- model_calls_total / model_call_duration
- mcp_invocations_total
- routing_decisions_total

NO PHI or secrets are emitted as metric attributes (Req 9.5, 9.10).

Requirements: 10.5
"""

from __future__ import annotations

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    InMemoryMetricReader,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------
_meter_provider: MeterProvider | None = None

# Default no-op meter used before configure_metrics() is called.
_default_meter: metrics.Meter = metrics.get_meter("maos")

# Instruments — initialised with no-op defaults so they can be imported at
# module load time. Replaced with real instruments by configure_metrics().
tasks_submitted: metrics.Counter = _default_meter.create_counter(
    name="maos.tasks.submitted",
    description="Total tasks submitted to the orchestrator",
    unit="1",
)
tasks_completed: metrics.Counter = _default_meter.create_counter(
    name="maos.tasks.completed",
    description="Total tasks that reached completed state",
    unit="1",
)
tasks_failed: metrics.Counter = _default_meter.create_counter(
    name="maos.tasks.failed",
    description="Total tasks that reached permanently_failed state",
    unit="1",
)
model_calls_total: metrics.Counter = _default_meter.create_counter(
    name="maos.model_calls.total",
    description="Total LLM model invocations",
    unit="1",
)
model_call_duration: metrics.Histogram = _default_meter.create_histogram(
    name="maos.model_calls.duration",
    description="Duration of LLM model calls in seconds",
    unit="s",
)
mcp_invocations_total: metrics.Counter = _default_meter.create_counter(
    name="maos.mcp_invocations.total",
    description="Total MCP tool invocations",
    unit="1",
)
routing_decisions_total: metrics.Counter = _default_meter.create_counter(
    name="maos.routing_decisions.total",
    description="Total routing decisions made by orchestrators",
    unit="1",
)


def configure_metrics(
    *,
    service_name: str = "maos",
    environment: str = "development",
    otlp_endpoint: str | None = None,
    insecure: bool = True,
    export_interval_ms: int = 30_000,
) -> MeterProvider:
    """Initialise and register the global OTel MeterProvider.

    Args:
        service_name: Logical service name for resource identification.
        environment: Deployment environment label.
        otlp_endpoint: OTLP gRPC collector endpoint. If ``None``, uses an
            in-memory reader (suitable for tests).
        insecure: gRPC TLS toggle.
        export_interval_ms: Periodic export interval in milliseconds.

    Returns:
        The configured ``MeterProvider`` (also globally registered).
    """
    global _meter_provider
    global tasks_submitted, tasks_completed, tasks_failed
    global model_calls_total, model_call_duration
    global mcp_invocations_total, routing_decisions_total

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": "0.1.0",
            "deployment.environment": environment,
        }
    )

    if otlp_endpoint:
        exporter = OTLPMetricExporter(endpoint=otlp_endpoint, insecure=insecure)
        reader: PeriodicExportingMetricReader | InMemoryMetricReader = (
            PeriodicExportingMetricReader(
                exporter, export_interval_millis=export_interval_ms
            )
        )
    else:
        reader = InMemoryMetricReader()

    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)
    _meter_provider = provider

    meter = provider.get_meter("maos", "0.1.0")

    # Re-create instruments under the configured provider
    tasks_submitted = meter.create_counter(
        name="maos.tasks.submitted",
        description="Total tasks submitted to the orchestrator",
        unit="1",
    )
    tasks_completed = meter.create_counter(
        name="maos.tasks.completed",
        description="Total tasks that reached completed state",
        unit="1",
    )
    tasks_failed = meter.create_counter(
        name="maos.tasks.failed",
        description="Total tasks that reached permanently_failed state",
        unit="1",
    )
    model_calls_total = meter.create_counter(
        name="maos.model_calls.total",
        description="Total LLM model invocations",
        unit="1",
    )
    model_call_duration = meter.create_histogram(
        name="maos.model_calls.duration",
        description="Duration of LLM model calls in seconds",
        unit="s",
    )
    mcp_invocations_total = meter.create_counter(
        name="maos.mcp_invocations.total",
        description="Total MCP tool invocations",
        unit="1",
    )
    routing_decisions_total = meter.create_counter(
        name="maos.routing_decisions.total",
        description="Total routing decisions made by orchestrators",
        unit="1",
    )

    return provider


def get_meter(name: str = "maos") -> metrics.Meter:
    """Return a named meter from the global provider."""
    if _meter_provider is None:
        return metrics.get_meter(name)
    return _meter_provider.get_meter(name)


def shutdown_metrics() -> None:
    """Flush and shut down the meter provider (call on service shutdown)."""
    global _meter_provider
    if _meter_provider is not None:
        _meter_provider.shutdown()
        _meter_provider = None
