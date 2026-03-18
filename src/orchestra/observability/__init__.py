"""Orchestra observability: logging, tracing, metrics."""

from orchestra.observability.logging import get_logger, setup_logging

__all__ = ["get_logger", "setup_logging"]

# Optional OTel exports — only available when opentelemetry is installed
try:
    from orchestra.observability._otel_setup import setup_telemetry, shutdown_telemetry

    __all__ += ["setup_telemetry", "shutdown_telemetry"]
except ImportError:
    pass

try:
    from orchestra.observability.tracing import OTelTraceSubscriber

    __all__ += ["OTelTraceSubscriber"]
except ImportError:
    pass

try:
    from orchestra.observability.metrics import OTelMetricsSubscriber

    __all__ += ["OTelMetricsSubscriber"]
except ImportError:
    pass
