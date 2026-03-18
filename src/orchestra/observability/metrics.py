"""OpenTelemetry metrics subscriber for Orchestra EventBus.

Tracks the 4 Golden Signal metrics for LLM operations:
- gen_ai.client.operation.duration (Histogram)
- gen_ai.client.token.usage (Counter)
- gen_ai.client.operation.errors (Counter)
- orchestra.cost_usd (Counter)

All OTel imports are guarded with try/except.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Guard OTel imports
try:
    from opentelemetry import metrics

    _OTEL_METRICS_AVAILABLE = True
except ImportError:
    _OTEL_METRICS_AVAILABLE = False


class OTelMetricsSubscriber:
    """EventBus subscriber that records OTel metrics from WorkflowEvents.

    Uses bounded cardinality labels: only model, provider, operation,
    status, workflow_name. Never uses high-cardinality values like
    run_id or node_id as metric attributes.
    """

    def __init__(self, meter_name: str = "orchestra") -> None:
        if not _OTEL_METRICS_AVAILABLE:
            raise ImportError(
                "opentelemetry-api and opentelemetry-sdk are required for metrics. "
                "Install with: pip install orchestra-agents[telemetry]"
            )
        meter = metrics.get_meter(meter_name)

        self._duration_histogram = meter.create_histogram(
            name="gen_ai.client.operation.duration",
            description="Duration of LLM calls in milliseconds",
            unit="ms",
        )
        self._token_counter = meter.create_counter(
            name="gen_ai.client.token.usage",
            description="Token consumption by type",
            unit="tokens",
        )
        self._error_counter = meter.create_counter(
            name="gen_ai.client.operation.errors",
            description="Error count by type",
            unit="errors",
        )
        self._cost_counter = meter.create_counter(
            name="orchestra.cost_usd",
            description="Cost in USD",
            unit="USD",
        )

    def on_event(self, event: Any) -> None:
        """Main EventBus callback. Dispatches by event type.

        Never raises — errors are logged and swallowed.
        """
        try:
            self._dispatch(event)
        except Exception:
            logger.debug("OTelMetricsSubscriber error", exc_info=True)

    def _dispatch(self, event: Any) -> None:
        """Route event to the appropriate handler."""
        from orchestra.storage.events import ErrorOccurred, LLMCalled

        if isinstance(event, LLMCalled):
            self._on_llm_called(event)
        elif isinstance(event, ErrorOccurred):
            self._on_error_occurred(event)

    def _on_llm_called(self, event: Any) -> None:
        """Record duration, token usage, and cost metrics."""
        from orchestra.observability._span_attributes import extract_provider

        model = getattr(event, "model", "") or ""
        provider = extract_provider(model)
        duration_ms = getattr(event, "duration_ms", 0.0) or 0.0
        input_tokens = getattr(event, "input_tokens", 0) or 0
        output_tokens = getattr(event, "output_tokens", 0) or 0
        cost_usd = getattr(event, "cost_usd", 0.0) or 0.0

        common_attrs = {
            "gen_ai.system": provider,
            "gen_ai.request.model": model,
            "gen_ai.operation.name": "chat",
        }

        # Duration
        self._duration_histogram.record(duration_ms, attributes=common_attrs)

        # Tokens
        self._token_counter.add(
            input_tokens,
            attributes={**common_attrs, "gen_ai.token.type": "input"},
        )
        self._token_counter.add(
            output_tokens,
            attributes={**common_attrs, "gen_ai.token.type": "output"},
        )

        # Cost
        if cost_usd > 0:
            self._cost_counter.add(cost_usd, attributes=common_attrs)

    def _on_error_occurred(self, event: Any) -> None:
        """Record error count."""
        error_type = getattr(event, "error_type", "unknown") or "unknown"
        self._error_counter.add(
            1,
            attributes={
                "error.type": error_type,
            },
        )
