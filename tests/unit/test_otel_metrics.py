"""Tests for OTelMetricsSubscriber — OpenTelemetry metrics from EventBus events."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

# Try to import OTel SDK for real-metric tests; skip if not installed
try:
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader

    _OTEL_SDK_AVAILABLE = True
except ImportError:
    _OTEL_SDK_AVAILABLE = False

from orchestra.storage.events import (
    ErrorOccurred,
    LLMCalled,
)

pytestmark = pytest.mark.skipif(
    not _OTEL_SDK_AVAILABLE,
    reason="opentelemetry-sdk not installed",
)


NOW = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
RUN_ID = "test-metrics-001"


@pytest.fixture()
def metrics_env():
    """Set up an in-memory MeterProvider and patch get_meter to use it."""
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])

    # Patch metrics.get_meter to use our test provider
    with patch("orchestra.observability.metrics.metrics") as mock_metrics:
        mock_metrics.get_meter = provider.get_meter

        from orchestra.observability.metrics import OTelMetricsSubscriber

        sub = OTelMetricsSubscriber()
        yield sub, reader

    provider.shutdown()


def _llm_event(
    model: str = "gpt-4o-mini",
    duration_ms: float = 800.0,
    input_tokens: int = 100,
    output_tokens: int = 50,
    cost_usd: float = 0.001,
) -> LLMCalled:
    return LLMCalled(
        run_id=RUN_ID,
        node_id="triage",
        model=model,
        duration_ms=duration_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        timestamp=NOW,
    )


def _error_event(
    error_type: str = "AgentError",
    error_message: str = "Rate limit exceeded",
) -> ErrorOccurred:
    return ErrorOccurred(
        run_id=RUN_ID,
        node_id="triage",
        error_type=error_type,
        error_message=error_message,
        timestamp=NOW,
    )


def _get_metrics_by_name(reader, name: str):
    """Extract metric data points by metric name."""
    data = reader.get_metrics_data()
    if data is None:
        return None
    for resource_metric in data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                if metric.name == name:
                    return metric
    return None


class TestLLMDuration:
    """Test duration histogram recording."""

    def test_llm_called_records_duration(self, metrics_env):
        subscriber, reader = metrics_env
        subscriber.on_event(_llm_event(duration_ms=800.0))

        metric = _get_metrics_by_name(reader, "gen_ai.client.operation.duration")
        assert metric is not None

        data_points = list(metric.data.data_points)
        assert len(data_points) == 1
        assert data_points[0].sum == 800.0


class TestTokenUsage:
    """Test token counter recording."""

    def test_llm_called_records_tokens(self, metrics_env):
        subscriber, reader = metrics_env
        subscriber.on_event(_llm_event(input_tokens=100, output_tokens=50))

        metric = _get_metrics_by_name(reader, "gen_ai.client.token.usage")
        assert metric is not None

        data_points = list(metric.data.data_points)
        assert len(data_points) == 2

        token_values = {}
        for dp in data_points:
            token_type = dp.attributes.get("gen_ai.token.type", "unknown")
            token_values[token_type] = dp.value

        assert token_values["input"] == 100
        assert token_values["output"] == 50


class TestCostTracking:
    """Test cost counter recording."""

    def test_llm_called_records_cost(self, metrics_env):
        subscriber, reader = metrics_env
        subscriber.on_event(_llm_event(cost_usd=0.015))

        metric = _get_metrics_by_name(reader, "orchestra.cost_usd")
        assert metric is not None

        data_points = list(metric.data.data_points)
        assert len(data_points) == 1
        assert data_points[0].value == pytest.approx(0.015, abs=1e-6)


class TestErrorCounter:
    """Test error counter recording."""

    def test_error_records_counter(self, metrics_env):
        subscriber, reader = metrics_env
        subscriber.on_event(_error_event(error_type="RateLimitError"))

        metric = _get_metrics_by_name(reader, "gen_ai.client.operation.errors")
        assert metric is not None

        data_points = list(metric.data.data_points)
        assert len(data_points) == 1
        assert data_points[0].value == 1
        assert data_points[0].attributes["error.type"] == "RateLimitError"


class TestBoundedCardinality:
    """Test that metric labels use bounded cardinality."""

    def test_metric_labels_bounded_cardinality(self, metrics_env):
        """Ensure no high-cardinality labels like run_id or node_id."""
        subscriber, reader = metrics_env
        subscriber.on_event(_llm_event())

        metric = _get_metrics_by_name(reader, "gen_ai.client.operation.duration")
        assert metric is not None

        data_points = list(metric.data.data_points)
        for dp in data_points:
            attrs = dict(dp.attributes)
            assert "run_id" not in attrs
            assert "node_id" not in attrs
            assert "workflow.run_id" not in attrs
            assert "gen_ai.system" in attrs
            assert "gen_ai.request.model" in attrs


class TestGracefulDegradation:
    """Test behavior when OTel is not installed."""

    def test_no_crash_without_otel_installed(self):
        """Importing and creating subscriber should raise ImportError
        when opentelemetry is not available."""
        hidden = {}
        for mod_name in list(sys.modules):
            if "opentelemetry" in mod_name:
                hidden[mod_name] = sys.modules.pop(mod_name)

        try:
            with patch.dict(
                sys.modules,
                {"opentelemetry": None, "opentelemetry.metrics": None},
            ):
                if "orchestra.observability.metrics" in sys.modules:
                    del sys.modules["orchestra.observability.metrics"]

                with pytest.raises(ImportError, match="opentelemetry"):
                    from orchestra.observability.metrics import OTelMetricsSubscriber

                    OTelMetricsSubscriber()
        finally:
            sys.modules.update(hidden)
