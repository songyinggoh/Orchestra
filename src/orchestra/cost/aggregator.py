"""CostAggregator: EventBus subscriber that accumulates per-run costs.

Subscribes to LLMCalled events and tracks cost breakdowns by model
and agent. Produces RunCostSummary on demand or at execution completion.
Follows the same on_event(event) pattern as OTelTraceSubscriber.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from orchestra.cost.registry import ModelCostRegistry

logger = structlog.get_logger(__name__)


@dataclass
class RunCostSummary:
    """Summary of costs for a single workflow run.

    Attributes:
        run_id: The workflow run identifier.
        total_cost_usd: Total cost in USD across all LLM calls.
        total_input_tokens: Total input tokens across all calls.
        total_output_tokens: Total output tokens across all calls.
        total_tokens: Total tokens (input + output).
        call_count: Number of LLM calls made.
        by_model: Cost breakdown per model name.
        by_agent: Cost breakdown per agent name.
    """

    run_id: str = ""
    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 0
    by_model: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_agent: dict[str, dict[str, Any]] = field(default_factory=dict)


class CostAggregator:
    """EventBus subscriber that tracks LLM costs per workflow run.

    Subscribes to LLMCalled events using the on_event() callback pattern.
    Maintains per-run cost accumulators with breakdowns by model and agent.

    Usage:
        aggregator = CostAggregator()
        event_bus.subscribe(aggregator.on_event)
        # ... run workflow ...
        summary = aggregator.get_summary(run_id)
    """

    def __init__(self, registry: ModelCostRegistry | None = None) -> None:
        """Initialize with an optional custom registry.

        Args:
            registry: ModelCostRegistry for pricing lookups. If None,
                      creates a default registry from bundled prices.
        """
        self._registry = registry or ModelCostRegistry()
        self._runs: dict[str, RunCostSummary] = {}

    def on_event(self, event: Any) -> None:
        """EventBus callback. Dispatches LLMCalled events to accumulation.

        Never raises -- errors are logged and swallowed to avoid
        crashing the workflow.
        """
        try:
            self._dispatch(event)
        except Exception:
            logger.debug("CostAggregator error", exc_info=True)

    def _dispatch(self, event: Any) -> None:
        """Route event to the appropriate handler."""
        from orchestra.storage.events import LLMCalled, ExecutionCompleted

        if isinstance(event, LLMCalled):
            self._on_llm_called(event)
        elif isinstance(event, ExecutionCompleted):
            self._on_execution_completed(event)

    def _on_llm_called(self, event: Any) -> None:
        """Accumulate cost from an LLMCalled event."""
        run_id = event.run_id
        summary = self._runs.get(run_id)
        if summary is None:
            summary = RunCostSummary(run_id=run_id)
            self._runs[run_id] = summary

        model = getattr(event, "model", "") or ""
        agent_name = getattr(event, "agent_name", "") or ""
        input_tokens = getattr(event, "input_tokens", 0) or 0
        output_tokens = getattr(event, "output_tokens", 0) or 0

        # Calculate cost using the registry
        cost = self._registry.calculate_cost(model, input_tokens, output_tokens)

        # Update totals
        summary.total_cost_usd += cost
        summary.total_input_tokens += input_tokens
        summary.total_output_tokens += output_tokens
        summary.total_tokens += input_tokens + output_tokens
        summary.call_count += 1

        # Update per-model breakdown
        if model:
            if model not in summary.by_model:
                summary.by_model[model] = {
                    "cost_usd": 0.0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "call_count": 0,
                }
            model_data = summary.by_model[model]
            model_data["cost_usd"] += cost
            model_data["input_tokens"] += input_tokens
            model_data["output_tokens"] += output_tokens
            model_data["call_count"] += 1

        # Update per-agent breakdown
        if agent_name:
            if agent_name not in summary.by_agent:
                summary.by_agent[agent_name] = {
                    "cost_usd": 0.0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "call_count": 0,
                }
            agent_data = summary.by_agent[agent_name]
            agent_data["cost_usd"] += cost
            agent_data["input_tokens"] += input_tokens
            agent_data["output_tokens"] += output_tokens
            agent_data["call_count"] += 1

    def _on_execution_completed(self, event: Any) -> None:
        """Log final cost summary when execution completes."""
        run_id = event.run_id
        summary = self._runs.get(run_id)
        if summary is not None:
            logger.info(
                "run_cost_summary",
                run_id=run_id,
                total_cost_usd=summary.total_cost_usd,
                total_tokens=summary.total_tokens,
                call_count=summary.call_count,
            )

    def get_summary(self, run_id: str) -> RunCostSummary | None:
        """Get the cost summary for a completed or in-progress run.

        Args:
            run_id: The workflow run identifier.

        Returns:
            RunCostSummary or None if no data for this run.
        """
        return self._runs.get(run_id)

    def get_totals(self, run_id: str) -> dict[str, Any]:
        """Get total cost and tokens for a run as a simple dict.

        Returns dict with total_cost_usd and total_tokens keys.
        Returns zeros if run not found.
        """
        summary = self._runs.get(run_id)
        if summary is None:
            return {"total_cost_usd": 0.0, "total_tokens": 0}
        return {
            "total_cost_usd": summary.total_cost_usd,
            "total_tokens": summary.total_tokens,
        }

    @property
    def registry(self) -> ModelCostRegistry:
        """Access the underlying cost registry."""
        return self._registry
