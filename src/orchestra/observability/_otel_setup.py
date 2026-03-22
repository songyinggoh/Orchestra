"""OpenTelemetry SDK setup for Orchestra.

Configures TracerProvider and MeterProvider with OTLP/HTTP exporters.
All OTel imports are guarded — returns False if dependencies are missing.

Environment variables:
    OTEL_EXPORTER_OTLP_ENDPOINT: OTLP endpoint (default: http://localhost:4318)
    OTEL_SERVICE_NAME: Override service name
    ORCHESTRA_OTEL_CAPTURE_CONTENT: Enable PII capture (default: false)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Module-level references for shutdown
_tracer_provider: Any = None
_meter_provider: Any = None


def setup_telemetry(
    service_name: str = "orchestra",
    endpoint: str | None = None,
    capture_content: bool = False,
) -> bool:
    """Initialize OpenTelemetry tracing and metrics.

    Args:
        service_name: Service name for OTel resource (default: "orchestra").
        endpoint: OTLP HTTP endpoint. Falls back to OTEL_EXPORTER_OTLP_ENDPOINT
            env var, then http://localhost:4318.
        capture_content: Whether to capture LLM prompt/completion content.

    Returns:
        True if setup succeeded, False if OTel SDK is not installed.
    """
    global _tracer_provider, _meter_provider

    try:
        import os

        from opentelemetry import metrics as metrics_api
        from opentelemetry import trace as trace_api
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.debug("OpenTelemetry SDK not installed — telemetry disabled")
        return False

    try:
        # Resolve endpoint
        resolved_endpoint = (
            endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "http://localhost:4318"
        )

        # Resolve service name
        resolved_service = os.environ.get("OTEL_SERVICE_NAME", service_name)

        # Set capture content env var if requested programmatically
        if capture_content:
            os.environ.setdefault("ORCHESTRA_OTEL_CAPTURE_CONTENT", "true")

        # Resource
        resource = Resource.create({"service.name": resolved_service})

        # Tracer provider
        tracer_provider = TracerProvider(resource=resource)
        span_exporter = OTLPSpanExporter(endpoint=f"{resolved_endpoint}/v1/traces")
        tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
        trace_api.set_tracer_provider(tracer_provider)
        _tracer_provider = tracer_provider

        # Meter provider
        metric_exporter = OTLPMetricExporter(endpoint=f"{resolved_endpoint}/v1/metrics")
        metric_reader = PeriodicExportingMetricReader(metric_exporter)
        meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
        metrics_api.set_meter_provider(meter_provider)
        _meter_provider = meter_provider

        logger.info(
            "OpenTelemetry initialized: service=%s endpoint=%s",
            resolved_service,
            resolved_endpoint,
        )
        return True

    except Exception:
        logger.exception("Failed to initialize OpenTelemetry")
        return False


def shutdown_telemetry() -> None:
    """Flush and shut down OTel providers."""
    global _tracer_provider, _meter_provider
    if _tracer_provider is not None:
        try:
            _tracer_provider.shutdown()
        except Exception:
            pass
        _tracer_provider = None
    if _meter_provider is not None:
        try:
            _meter_provider.shutdown()
        except Exception:
            pass
        _meter_provider = None
