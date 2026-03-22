"""OpenTelemetry trace subscriber for Orchestra EventBus.

Converts WorkflowEvents into OpenTelemetry spans, creating a
4-level hierarchy: workflow.run > node.{name} > gen_ai.chat > tool.{name}

Subscribes to EventBus using the same on_event(event) pattern as
RichTraceRenderer. All OTel imports are guarded with try/except.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Guard all OTel imports
try:
    from opentelemetry import trace
    from opentelemetry.trace import Span, StatusCode, Tracer  # noqa: F401

    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False


class OTelTraceSubscriber:
    """Converts WorkflowEvents into OpenTelemetry spans.

    Subscribes to EventBus and maintains a span stack to create
    the 4-level hierarchy: workflow.run > node.{name} > gen_ai.chat > tool.{name}
    """

    def __init__(self, tracer_name: str = "orchestra") -> None:
        if not _OTEL_AVAILABLE:
            raise ImportError(
                "opentelemetry-api and opentelemetry-sdk are required for tracing. "
                "Install with: pip install orchestra-agents[telemetry]"
            )
        self._tracer: Tracer = trace.get_tracer(tracer_name)

        # Span tracking: run_id -> span context
        self._spans: dict[str, dict[str, Any]] = {}
        # {
        #   run_id: {
        #     "workflow": (span, context),
        #     "nodes": {node_id: (span, context)},
        #     "parallel": (span, context),
        #   }
        # }

    def on_event(self, event: Any) -> None:
        """Main EventBus callback. Dispatches by event type.

        Never raises — errors are logged and swallowed to avoid
        crashing the workflow.
        """
        try:
            self._dispatch(event)
        except Exception:
            logger.debug("OTelTraceSubscriber error", exc_info=True)

    def _dispatch(self, event: Any) -> None:
        """Route event to the appropriate handler."""
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

        if isinstance(event, ExecutionStarted):
            self._on_execution_started(event)
        elif isinstance(event, NodeStarted):
            self._on_node_started(event)
        elif isinstance(event, LLMCalled):
            self._on_llm_called(event)
        elif isinstance(event, ToolCalled):
            self._on_tool_called(event)
        elif isinstance(event, NodeCompleted):
            self._on_node_completed(event)
        elif isinstance(event, ExecutionCompleted):
            self._on_execution_completed(event)
        elif isinstance(event, ParallelStarted):
            self._on_parallel_started(event)
        elif isinstance(event, ParallelCompleted):
            self._on_parallel_completed(event)
        elif isinstance(event, ErrorOccurred):
            self._on_error_occurred(event)

    # ------------------------------------------------------------------
    # Per-event handlers
    # ------------------------------------------------------------------

    def _on_execution_started(self, event: Any) -> None:
        """Create root span for the workflow run."""
        workflow_name = getattr(event, "workflow_name", "workflow") or "workflow"
        span = self._tracer.start_span(
            "workflow.run",
            attributes={
                "workflow.name": workflow_name,
                "workflow.run_id": event.run_id,
            },
        )
        ctx = trace.set_span_in_context(span)
        self._spans[event.run_id] = {
            "workflow": (span, ctx),
            "nodes": {},
            "parallel": None,
        }

    def _on_node_started(self, event: Any) -> None:
        """Create child span under the workflow span for a node."""
        run_data = self._spans.get(event.run_id)
        if run_data is None:
            return

        parent_ctx = run_data["workflow"][1]
        node_id = event.node_id
        span = self._tracer.start_span(
            f"node.{node_id}",
            context=parent_ctx,
            attributes={
                "node.id": node_id,
                "node.type": getattr(event, "node_type", "") or "",
            },
        )
        node_ctx = trace.set_span_in_context(span)
        run_data["nodes"][node_id] = (span, node_ctx)

    def _on_llm_called(self, event: Any) -> None:
        """Create a gen_ai.chat span under the current node span.

        Uses backdate pattern: start_time = event.timestamp - duration_ms.
        Span is ended immediately since LLMCalled is a complete event.
        """
        from orchestra.observability._span_attributes import llm_event_to_attributes

        run_data = self._spans.get(event.run_id)
        if run_data is None:
            return

        node_id = event.node_id
        node_entry = run_data["nodes"].get(node_id)
        parent_ctx = node_entry[1] if node_entry else run_data["workflow"][1]

        # Backdate: compute start time from event timestamp and duration
        duration_ms = getattr(event, "duration_ms", 0.0) or 0.0
        end_time_ns = int(event.timestamp.timestamp() * 1e9)
        start_time_ns = end_time_ns - int(duration_ms * 1e6)

        attrs = llm_event_to_attributes(event)
        attrs["node.id"] = node_id

        span = self._tracer.start_span(
            "gen_ai.chat",
            context=parent_ctx,
            attributes=attrs,
            start_time=start_time_ns,
        )
        span.end(end_time=end_time_ns)

    def _on_tool_called(self, event: Any) -> None:
        """Create a tool.{name} span under the current node span.

        Uses backdate pattern like LLMCalled.
        """
        run_data = self._spans.get(event.run_id)
        if run_data is None:
            return

        node_id = event.node_id
        node_entry = run_data["nodes"].get(node_id)
        parent_ctx = node_entry[1] if node_entry else run_data["workflow"][1]

        tool_name = getattr(event, "tool_name", "") or ""
        duration_ms = getattr(event, "duration_ms", 0.0) or 0.0
        end_time_ns = int(event.timestamp.timestamp() * 1e9)
        start_time_ns = end_time_ns - int(duration_ms * 1e6)

        error = getattr(event, "error", None)
        attrs: dict[str, Any] = {
            "tool.name": tool_name,
            "node.id": node_id,
        }
        if error:
            attrs["tool.error"] = error

        span = self._tracer.start_span(
            f"tool.{tool_name}",
            context=parent_ctx,
            attributes=attrs,
            start_time=start_time_ns,
        )
        if error:
            span.set_status(StatusCode.ERROR, error)
        span.end(end_time=end_time_ns)

    def _on_node_completed(self, event: Any) -> None:
        """End the node span."""
        run_data = self._spans.get(event.run_id)
        if run_data is None:
            return

        node_id = event.node_id
        node_entry = run_data["nodes"].pop(node_id, None)
        if node_entry is not None:
            span = node_entry[0]
            duration_ms = getattr(event, "duration_ms", 0.0) or 0.0
            span.set_attribute("node.duration_ms", duration_ms)
            span.end()

    def _on_execution_completed(self, event: Any) -> None:
        """End the root workflow span."""
        run_data = self._spans.pop(event.run_id, None)
        if run_data is None:
            return

        span = run_data["workflow"][0]
        status = getattr(event, "status", "completed") or "completed"
        duration_ms = getattr(event, "duration_ms", 0.0) or 0.0
        total_tokens = getattr(event, "total_tokens", 0) or 0
        total_cost = getattr(event, "total_cost_usd", 0.0) or 0.0

        span.set_attribute("workflow.duration_ms", duration_ms)
        span.set_attribute("workflow.total_tokens", total_tokens)
        span.set_attribute("workflow.total_cost_usd", total_cost)
        span.set_attribute("workflow.status", status)

        if status == "failed":
            span.set_status(StatusCode.ERROR, "Workflow failed")
        else:
            span.set_status(StatusCode.OK)

        # End any remaining node spans (shouldn't happen, but be safe)
        for _node_id, node_entry in run_data["nodes"].items():
            try:
                node_entry[0].end()
            except Exception:
                pass

        # End parallel span if still open
        if run_data.get("parallel") is not None:
            try:
                run_data["parallel"][0].end()
            except Exception:
                pass

        span.end()

    def _on_parallel_started(self, event: Any) -> None:
        """Create a grouping span for parallel fan-out."""
        run_data = self._spans.get(event.run_id)
        if run_data is None:
            return

        parent_ctx = run_data["workflow"][1]
        source = getattr(event, "source_node", "") or ""
        targets = getattr(event, "target_nodes", ()) or ()

        span = self._tracer.start_span(
            "parallel.fan_out",
            context=parent_ctx,
            attributes={
                "parallel.source_node": source,
                "parallel.target_nodes": list(targets),
            },
        )
        ctx = trace.set_span_in_context(span)
        run_data["parallel"] = (span, ctx)

    def _on_parallel_completed(self, event: Any) -> None:
        """End the parallel grouping span."""
        run_data = self._spans.get(event.run_id)
        if run_data is None:
            return

        parallel_entry = run_data.get("parallel")
        if parallel_entry is not None:
            span = parallel_entry[0]
            duration_ms = getattr(event, "duration_ms", 0.0) or 0.0
            span.set_attribute("parallel.duration_ms", duration_ms)
            span.end()
            run_data["parallel"] = None

    def _on_error_occurred(self, event: Any) -> None:
        """Record an exception on the current active span."""
        run_data = self._spans.get(event.run_id)
        if run_data is None:
            return

        error_type = getattr(event, "error_type", "") or ""
        error_message = getattr(event, "error_message", "") or ""
        node_id = getattr(event, "node_id", "") or ""

        # Find the most specific active span: node > parallel > workflow
        target_span = None
        if node_id and node_id in run_data.get("nodes", {}):
            target_span = run_data["nodes"][node_id][0]
        elif run_data.get("parallel") is not None:
            target_span = run_data["parallel"][0]
        else:
            target_span = run_data["workflow"][0]

        if target_span is not None:
            target_span.set_status(StatusCode.ERROR, error_message)
            target_span.record_exception(
                Exception(error_message),
                attributes={"exception.type": error_type},
            )
