"""Tests for OTelTraceSubscriber — OpenTelemetry span creation from EventBus events."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

# Try to import OTel SDK for real-span tests; skip if not installed
try:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry import trace as trace_api

    _OTEL_SDK_AVAILABLE = True
except ImportError:
    _OTEL_SDK_AVAILABLE = False

from orchestra.storage.events import (
    ErrorOccurred,
    ExecutionCompleted,
    ExecutionStarted,
    LLMCalled,
    NodeCompleted,
    NodeStarted,
    ParallelCompleted,
    ParallelStarted,
    ToolCalled,
)

pytestmark = pytest.mark.skipif(
    not _OTEL_SDK_AVAILABLE,
    reason="opentelemetry-sdk not installed",
)


@pytest.fixture()
def otel_setup():
    """Set up an in-memory OTel TracerProvider for testing."""
    exporter = InMemorySpanExporter()
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    # Patch get_tracer to use our test provider instead of the global one
    original_get_tracer = trace_api.get_tracer
    trace_api.get_tracer = provider.get_tracer
    yield exporter
    trace_api.get_tracer = original_get_tracer
    provider.shutdown()


@pytest.fixture()
def subscriber(otel_setup):
    """Create a fresh OTelTraceSubscriber with test provider."""
    from orchestra.observability.tracing import OTelTraceSubscriber

    return OTelTraceSubscriber()


RUN_ID = "test-run-001"
NOW = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def _exec_started(run_id: str = RUN_ID) -> ExecutionStarted:
    return ExecutionStarted(
        run_id=run_id,
        workflow_name="test_workflow",
        timestamp=NOW,
    )


def _node_started(node_id: str = "triage", run_id: str = RUN_ID) -> NodeStarted:
    return NodeStarted(
        run_id=run_id,
        node_id=node_id,
        node_type="AgentNode",
        timestamp=NOW,
    )


def _llm_called(
    node_id: str = "triage",
    run_id: str = RUN_ID,
    model: str = "gpt-4o-mini",
    duration_ms: float = 800.0,
    input_tokens: int = 100,
    output_tokens: int = 50,
    cost_usd: float = 0.001,
    content: str | None = None,
) -> LLMCalled:
    return LLMCalled(
        run_id=run_id,
        node_id=node_id,
        model=model,
        duration_ms=duration_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        content=content,
        timestamp=NOW,
    )


def _tool_called(
    node_id: str = "triage",
    tool_name: str = "classify_ticket",
    run_id: str = RUN_ID,
    duration_ms: float = 200.0,
) -> ToolCalled:
    return ToolCalled(
        run_id=run_id,
        node_id=node_id,
        tool_name=tool_name,
        arguments={"priority": "high"},
        result="billing",
        duration_ms=duration_ms,
        timestamp=NOW,
    )


def _node_completed(node_id: str = "triage", run_id: str = RUN_ID) -> NodeCompleted:
    return NodeCompleted(
        run_id=run_id,
        node_id=node_id,
        node_type="AgentNode",
        duration_ms=1100.0,
        timestamp=NOW,
    )


def _exec_completed(run_id: str = RUN_ID, status: str = "completed") -> ExecutionCompleted:
    return ExecutionCompleted(
        run_id=run_id,
        duration_ms=3200.0,
        total_tokens=650,
        total_cost_usd=0.016,
        status=status,
        timestamp=NOW,
    )


class TestWorkflowSpan:
    """Test workflow-level span creation."""

    def test_workflow_creates_root_span(self, subscriber, otel_setup):
        subscriber.on_event(_exec_started())
        subscriber.on_event(_exec_completed())

        spans = otel_setup.get_finished_spans()
        workflow_spans = [s for s in spans if s.name == "workflow.run"]
        assert len(workflow_spans) == 1

        span = workflow_spans[0]
        assert span.attributes["workflow.name"] == "test_workflow"
        assert span.attributes["workflow.run_id"] == RUN_ID

    def test_workflow_completed_sets_status(self, subscriber, otel_setup):
        subscriber.on_event(_exec_started())
        subscriber.on_event(_exec_completed(status="completed"))

        spans = otel_setup.get_finished_spans()
        workflow_spans = [s for s in spans if s.name == "workflow.run"]
        assert len(workflow_spans) == 1
        assert workflow_spans[0].attributes["workflow.status"] == "completed"

    def test_workflow_failed_sets_error_status(self, subscriber, otel_setup):
        from opentelemetry.trace import StatusCode

        subscriber.on_event(_exec_started())
        subscriber.on_event(_exec_completed(status="failed"))

        spans = otel_setup.get_finished_spans()
        workflow_spans = [s for s in spans if s.name == "workflow.run"]
        assert workflow_spans[0].status.status_code == StatusCode.ERROR


class TestNodeSpan:
    """Test node-level span creation."""

    def test_node_creates_child_span(self, subscriber, otel_setup):
        subscriber.on_event(_exec_started())
        subscriber.on_event(_node_started("triage"))
        subscriber.on_event(_node_completed("triage"))
        subscriber.on_event(_exec_completed())

        spans = otel_setup.get_finished_spans()
        node_spans = [s for s in spans if s.name == "node.triage"]
        assert len(node_spans) == 1
        assert node_spans[0].attributes["node.id"] == "triage"

    def test_node_span_is_child_of_workflow(self, subscriber, otel_setup):
        subscriber.on_event(_exec_started())
        subscriber.on_event(_node_started("triage"))
        subscriber.on_event(_node_completed("triage"))
        subscriber.on_event(_exec_completed())

        spans = otel_setup.get_finished_spans()
        workflow_span = [s for s in spans if s.name == "workflow.run"][0]
        node_span = [s for s in spans if s.name == "node.triage"][0]

        # Node span's parent should be the workflow span
        assert node_span.parent is not None
        assert node_span.parent.span_id == workflow_span.context.span_id


class TestLLMSpan:
    """Test LLM call span creation."""

    def test_llm_called_creates_gen_ai_span_with_attributes(self, subscriber, otel_setup):
        subscriber.on_event(_exec_started())
        subscriber.on_event(_node_started("triage"))
        subscriber.on_event(_llm_called())
        subscriber.on_event(_node_completed("triage"))
        subscriber.on_event(_exec_completed())

        spans = otel_setup.get_finished_spans()
        llm_spans = [s for s in spans if s.name == "gen_ai.chat"]
        assert len(llm_spans) == 1

        span = llm_spans[0]
        assert span.attributes["gen_ai.system"] == "openai"
        assert span.attributes["gen_ai.request.model"] == "gpt-4o-mini"
        assert span.attributes["gen_ai.usage.input_tokens"] == 100
        assert span.attributes["gen_ai.usage.output_tokens"] == 50

    def test_llm_called_backdate_pattern(self, subscriber, otel_setup):
        """LLM span start_time should be event.timestamp - duration_ms."""
        subscriber.on_event(_exec_started())
        subscriber.on_event(_node_started("triage"))
        subscriber.on_event(_llm_called(duration_ms=800.0))
        subscriber.on_event(_node_completed("triage"))
        subscriber.on_event(_exec_completed())

        spans = otel_setup.get_finished_spans()
        llm_spans = [s for s in spans if s.name == "gen_ai.chat"]
        span = llm_spans[0]

        end_ns = int(NOW.timestamp() * 1e9)
        start_ns = end_ns - int(800.0 * 1e6)

        assert span.start_time == start_ns
        assert span.end_time == end_ns

    def test_llm_span_is_child_of_node(self, subscriber, otel_setup):
        subscriber.on_event(_exec_started())
        subscriber.on_event(_node_started("triage"))
        subscriber.on_event(_llm_called())
        subscriber.on_event(_node_completed("triage"))
        subscriber.on_event(_exec_completed())

        spans = otel_setup.get_finished_spans()
        node_span = [s for s in spans if s.name == "node.triage"][0]
        llm_span = [s for s in spans if s.name == "gen_ai.chat"][0]

        assert llm_span.parent is not None
        assert llm_span.parent.span_id == node_span.context.span_id

    def test_pii_not_captured_by_default(self, subscriber, otel_setup):
        """Content should NOT be in span attributes by default."""
        # Ensure env var is not set
        os.environ.pop("ORCHESTRA_OTEL_CAPTURE_CONTENT", None)

        subscriber.on_event(_exec_started())
        subscriber.on_event(_node_started("triage"))
        subscriber.on_event(_llm_called(content="secret prompt data"))
        subscriber.on_event(_node_completed("triage"))
        subscriber.on_event(_exec_completed())

        spans = otel_setup.get_finished_spans()
        llm_spans = [s for s in spans if s.name == "gen_ai.chat"]
        assert "gen_ai.completion" not in llm_spans[0].attributes

    def test_pii_captured_when_enabled(self, subscriber, otel_setup):
        """Content should be in span attributes when env var is set."""
        os.environ["ORCHESTRA_OTEL_CAPTURE_CONTENT"] = "true"
        try:
            subscriber.on_event(_exec_started())
            subscriber.on_event(_node_started("triage"))
            subscriber.on_event(_llm_called(content="secret prompt data"))
            subscriber.on_event(_node_completed("triage"))
            subscriber.on_event(_exec_completed())

            spans = otel_setup.get_finished_spans()
            llm_spans = [s for s in spans if s.name == "gen_ai.chat"]
            assert llm_spans[0].attributes["gen_ai.completion"] == "secret prompt data"
        finally:
            os.environ.pop("ORCHESTRA_OTEL_CAPTURE_CONTENT", None)


class TestToolSpan:
    """Test tool call span creation."""

    def test_tool_called_creates_tool_span(self, subscriber, otel_setup):
        subscriber.on_event(_exec_started())
        subscriber.on_event(_node_started("triage"))
        subscriber.on_event(_tool_called(tool_name="classify_ticket"))
        subscriber.on_event(_node_completed("triage"))
        subscriber.on_event(_exec_completed())

        spans = otel_setup.get_finished_spans()
        tool_spans = [s for s in spans if s.name == "tool.classify_ticket"]
        assert len(tool_spans) == 1
        assert tool_spans[0].attributes["tool.name"] == "classify_ticket"

    def test_tool_span_is_child_of_node(self, subscriber, otel_setup):
        subscriber.on_event(_exec_started())
        subscriber.on_event(_node_started("triage"))
        subscriber.on_event(_tool_called())
        subscriber.on_event(_node_completed("triage"))
        subscriber.on_event(_exec_completed())

        spans = otel_setup.get_finished_spans()
        node_span = [s for s in spans if s.name == "node.triage"][0]
        tool_span = [s for s in spans if s.name.startswith("tool.")][0]

        assert tool_span.parent is not None
        assert tool_span.parent.span_id == node_span.context.span_id


class TestParallelSpan:
    """Test parallel fan-out span creation."""

    def test_parallel_creates_grouping_span(self, subscriber, otel_setup):
        subscriber.on_event(_exec_started())
        subscriber.on_event(
            ParallelStarted(
                run_id=RUN_ID,
                source_node="router",
                target_nodes=("agent_a", "agent_b"),
                timestamp=NOW,
            )
        )
        subscriber.on_event(
            ParallelCompleted(
                run_id=RUN_ID,
                source_node="router",
                target_nodes=("agent_a", "agent_b"),
                duration_ms=500.0,
                timestamp=NOW,
            )
        )
        subscriber.on_event(_exec_completed())

        spans = otel_setup.get_finished_spans()
        par_spans = [s for s in spans if s.name == "parallel.fan_out"]
        assert len(par_spans) == 1
        assert par_spans[0].attributes["parallel.source_node"] == "router"


class TestErrorHandling:
    """Test error recording on spans."""

    def test_error_records_exception(self, subscriber, otel_setup):
        from opentelemetry.trace import StatusCode

        subscriber.on_event(_exec_started())
        subscriber.on_event(_node_started("triage"))
        subscriber.on_event(
            ErrorOccurred(
                run_id=RUN_ID,
                node_id="triage",
                error_type="AgentError",
                error_message="LLM rate limit exceeded",
                timestamp=NOW,
            )
        )
        subscriber.on_event(_node_completed("triage"))
        subscriber.on_event(_exec_completed())

        spans = otel_setup.get_finished_spans()
        node_span = [s for s in spans if s.name == "node.triage"][0]
        assert node_span.status.status_code == StatusCode.ERROR

        # Check that exception was recorded
        assert len(node_span.events) > 0
        exc_event = [e for e in node_span.events if e.name == "exception"]
        assert len(exc_event) == 1


class TestGracefulDegradation:
    """Test behavior when OTel is not installed."""

    def test_no_crash_without_otel_installed(self):
        """Importing the module and calling on_event should not crash
        when opentelemetry is not available."""
        import importlib
        import sys

        # Temporarily hide OTel modules
        hidden = {}
        for mod_name in list(sys.modules):
            if "opentelemetry" in mod_name:
                hidden[mod_name] = sys.modules.pop(mod_name)

        try:
            # Mock the import to raise ImportError
            with patch.dict(sys.modules, {"opentelemetry": None, "opentelemetry.trace": None}):
                # Force reimport
                if "orchestra.observability.tracing" in sys.modules:
                    del sys.modules["orchestra.observability.tracing"]

                with pytest.raises(ImportError, match="opentelemetry"):
                    from orchestra.observability.tracing import OTelTraceSubscriber

                    OTelTraceSubscriber()
        finally:
            # Restore modules
            sys.modules.update(hidden)


class TestAPIIntegration:
    """Verify integration with FastAPI instrumentation."""

    @pytest.fixture()
    def app(self):
        from orchestra.server.app import create_app
        from orchestra.server.config import ServerConfig

        config = ServerConfig()
        application = create_app(config)
        return application

    @pytest.fixture()
    def client(self, app):
        from fastapi.testclient import TestClient

        with TestClient(app, raise_server_exceptions=False) as c:
            graph = MagicMock()
            graph.name = "test-graph"
            app.state.graph_registry.register("test-graph", graph)
            yield c

    def test_api_request_creates_full_trace_hierarchy(self, client, subscriber, otel_setup):
        # Simulate the full event flow triggered by an API call.
        # OTelTraceSubscriber picks up the current OTel context automatically,
        # so workflow spans created here will have proper parent-child links.
        subscriber.on_event(_exec_started())
        subscriber.on_event(_node_started("triage"))
        subscriber.on_event(_llm_called())
        subscriber.on_event(_node_completed("triage"))
        subscriber.on_event(_exec_completed())

        spans = otel_setup.get_finished_spans()
        workflow_spans = [s for s in spans if s.name == "workflow.run"]
        node_spans = [s for s in spans if s.name == "node.triage"]
        assert len(workflow_spans) == 1
        assert len(node_spans) == 1
        # Node is a child of the workflow span
        assert node_spans[0].parent.span_id == workflow_spans[0].context.span_id
