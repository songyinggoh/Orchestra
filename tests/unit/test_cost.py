"""Tests for the cost management module.

Covers ModelCostRegistry, CostAggregator, and BudgetPolicy.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from orchestra.cost.registry import ModelCostRegistry
from orchestra.cost.aggregator import CostAggregator, RunCostSummary
from orchestra.cost.budget import BudgetPolicy, BudgetCheckResult
from orchestra.core.errors import BudgetExceededError


# ---------------------------------------------------------------------------
# ModelCostRegistry Tests
# ---------------------------------------------------------------------------


class TestModelCostRegistry:
    """Tests for ModelCostRegistry."""

    def test_loads_default_prices(self) -> None:
        """Registry loads bundled _default_prices.json on init."""
        registry = ModelCostRegistry()
        assert len(registry.models) > 0
        assert "gpt-4o" in registry.models
        assert "claude-3.5-sonnet" in registry.models
        assert "gemini-1.5-pro" in registry.models

    def test_exact_match(self) -> None:
        """Exact model name match returns correct pricing."""
        registry = ModelCostRegistry()
        pricing = registry.get_pricing("gpt-4o")
        assert pricing is not None
        assert "input_cost_per_token" in pricing
        assert "output_cost_per_token" in pricing
        assert pricing["input_cost_per_token"] > 0
        assert pricing["output_cost_per_token"] > 0

    def test_prefix_match(self) -> None:
        """Prefix-based matching works for versioned model names."""
        registry = ModelCostRegistry()
        # "gpt-4o-2024-08-06" should match "gpt-4o"
        pricing = registry.get_pricing("gpt-4o-2024-08-06")
        assert pricing is not None
        # Should match gpt-4o pricing
        gpt4o = registry.get_pricing("gpt-4o")
        assert pricing == gpt4o

    def test_prefix_match_longest_wins(self) -> None:
        """Longest prefix match takes priority over shorter ones."""
        registry = ModelCostRegistry()
        # "gpt-4-turbo-preview" should match "gpt-4-turbo" not "gpt-4"
        pricing = registry.get_pricing("gpt-4-turbo-preview")
        assert pricing is not None
        gpt4_turbo = registry.get_pricing("gpt-4-turbo")
        assert pricing == gpt4_turbo

    def test_unknown_model_returns_none(self) -> None:
        """Unknown model returns None from get_pricing."""
        registry = ModelCostRegistry()
        pricing = registry.get_pricing("totally-unknown-model-xyz")
        assert pricing is None

    def test_calculate_cost_known_model(self) -> None:
        """calculate_cost returns correct USD for known model."""
        registry = ModelCostRegistry(prices={
            "test-model": {
                "input_cost_per_token": 0.001,
                "output_cost_per_token": 0.002,
            }
        })
        cost = registry.calculate_cost("test-model", 100, 50)
        # 100 * 0.001 + 50 * 0.002 = 0.1 + 0.1 = 0.2
        assert cost == pytest.approx(0.2)

    def test_calculate_cost_unknown_model_zero(self) -> None:
        """calculate_cost returns 0.0 for unknown model (no crash)."""
        registry = ModelCostRegistry(prices={})
        cost = registry.calculate_cost("unknown-model", 1000, 500)
        assert cost == 0.0

    def test_calculate_cost_zero_tokens(self) -> None:
        """calculate_cost returns 0.0 with zero tokens."""
        registry = ModelCostRegistry()
        cost = registry.calculate_cost("gpt-4o", 0, 0)
        assert cost == 0.0

    def test_set_pricing_override(self) -> None:
        """Runtime pricing override works."""
        registry = ModelCostRegistry(prices={})
        registry.set_pricing("custom-model", 0.01, 0.02)
        pricing = registry.get_pricing("custom-model")
        assert pricing is not None
        assert pricing["input_cost_per_token"] == 0.01
        assert pricing["output_cost_per_token"] == 0.02

    def test_set_pricing_overrides_existing(self) -> None:
        """set_pricing overrides existing model pricing."""
        registry = ModelCostRegistry(prices={
            "my-model": {"input_cost_per_token": 0.001, "output_cost_per_token": 0.002}
        })
        registry.set_pricing("my-model", 0.01, 0.02)
        cost = registry.calculate_cost("my-model", 100, 100)
        # 100 * 0.01 + 100 * 0.02 = 1.0 + 2.0 = 3.0
        assert cost == pytest.approx(3.0)

    def test_custom_prices_dict(self) -> None:
        """Registry accepts custom prices dict on init."""
        custom = {
            "my-model": {
                "input_cost_per_token": 0.005,
                "output_cost_per_token": 0.01,
            }
        }
        registry = ModelCostRegistry(prices=custom)
        assert registry.models == ["my-model"]
        cost = registry.calculate_cost("my-model", 200, 100)
        assert cost == pytest.approx(200 * 0.005 + 100 * 0.01)

    def test_default_prices_file_exists(self) -> None:
        """The bundled _default_prices.json file exists and is valid JSON."""
        prices_file = Path(__file__).parent.parent.parent / "src" / "orchestra" / "cost" / "_default_prices.json"
        assert prices_file.exists()
        with open(prices_file) as f:
            data = json.load(f)
        assert isinstance(data, dict)
        assert len(data) > 0
        for model, pricing in data.items():
            assert "input_cost_per_token" in pricing
            assert "output_cost_per_token" in pricing


# ---------------------------------------------------------------------------
# CostAggregator Tests
# ---------------------------------------------------------------------------


class TestCostAggregator:
    """Tests for CostAggregator EventBus subscriber."""

    def _make_llm_event(
        self,
        run_id: str = "run-1",
        model: str = "gpt-4o",
        agent_name: str = "agent-1",
        input_tokens: int = 100,
        output_tokens: int = 50,
        node_id: str = "node-1",
    ) -> object:
        """Create a mock LLMCalled event."""
        from orchestra.storage.events import LLMCalled
        return LLMCalled(
            run_id=run_id,
            node_id=node_id,
            agent_name=agent_name,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def _make_execution_completed(self, run_id: str = "run-1") -> object:
        """Create a mock ExecutionCompleted event."""
        from orchestra.storage.events import ExecutionCompleted
        return ExecutionCompleted(
            run_id=run_id,
            final_state={},
            duration_ms=1000.0,
        )

    def test_accumulates_single_call(self) -> None:
        """Single LLMCalled event is accumulated correctly."""
        registry = ModelCostRegistry(prices={
            "gpt-4o": {"input_cost_per_token": 0.001, "output_cost_per_token": 0.002}
        })
        agg = CostAggregator(registry=registry)
        event = self._make_llm_event(input_tokens=100, output_tokens=50)
        agg.on_event(event)

        summary = agg.get_summary("run-1")
        assert summary is not None
        assert summary.total_input_tokens == 100
        assert summary.total_output_tokens == 50
        assert summary.total_tokens == 150
        assert summary.call_count == 1
        expected_cost = 100 * 0.001 + 50 * 0.002
        assert summary.total_cost_usd == pytest.approx(expected_cost)

    def test_accumulates_multiple_calls(self) -> None:
        """Multiple LLMCalled events accumulate correctly."""
        registry = ModelCostRegistry(prices={
            "gpt-4o": {"input_cost_per_token": 0.001, "output_cost_per_token": 0.002}
        })
        agg = CostAggregator(registry=registry)

        agg.on_event(self._make_llm_event(input_tokens=100, output_tokens=50))
        agg.on_event(self._make_llm_event(input_tokens=200, output_tokens=100))

        summary = agg.get_summary("run-1")
        assert summary is not None
        assert summary.total_input_tokens == 300
        assert summary.total_output_tokens == 150
        assert summary.total_tokens == 450
        assert summary.call_count == 2

    def test_per_model_breakdown(self) -> None:
        """Cost is tracked per model."""
        registry = ModelCostRegistry(prices={
            "gpt-4o": {"input_cost_per_token": 0.001, "output_cost_per_token": 0.002},
            "gpt-3.5-turbo": {"input_cost_per_token": 0.0001, "output_cost_per_token": 0.0002},
        })
        agg = CostAggregator(registry=registry)

        agg.on_event(self._make_llm_event(model="gpt-4o", input_tokens=100, output_tokens=50))
        agg.on_event(self._make_llm_event(model="gpt-3.5-turbo", input_tokens=200, output_tokens=100))

        summary = agg.get_summary("run-1")
        assert summary is not None
        assert "gpt-4o" in summary.by_model
        assert "gpt-3.5-turbo" in summary.by_model
        assert summary.by_model["gpt-4o"]["call_count"] == 1
        assert summary.by_model["gpt-3.5-turbo"]["call_count"] == 1
        assert summary.by_model["gpt-4o"]["input_tokens"] == 100
        assert summary.by_model["gpt-3.5-turbo"]["input_tokens"] == 200

    def test_per_agent_breakdown(self) -> None:
        """Cost is tracked per agent."""
        registry = ModelCostRegistry(prices={
            "gpt-4o": {"input_cost_per_token": 0.001, "output_cost_per_token": 0.002}
        })
        agg = CostAggregator(registry=registry)

        agg.on_event(self._make_llm_event(agent_name="researcher", input_tokens=100, output_tokens=50))
        agg.on_event(self._make_llm_event(agent_name="writer", input_tokens=200, output_tokens=100))

        summary = agg.get_summary("run-1")
        assert summary is not None
        assert "researcher" in summary.by_agent
        assert "writer" in summary.by_agent
        assert summary.by_agent["researcher"]["call_count"] == 1
        assert summary.by_agent["writer"]["call_count"] == 1
        assert summary.by_agent["researcher"]["input_tokens"] == 100
        assert summary.by_agent["writer"]["input_tokens"] == 200

    def test_separate_runs(self) -> None:
        """Different run_ids are tracked independently."""
        registry = ModelCostRegistry(prices={
            "gpt-4o": {"input_cost_per_token": 0.001, "output_cost_per_token": 0.002}
        })
        agg = CostAggregator(registry=registry)

        agg.on_event(self._make_llm_event(run_id="run-1", input_tokens=100, output_tokens=50))
        agg.on_event(self._make_llm_event(run_id="run-2", input_tokens=300, output_tokens=200))

        s1 = agg.get_summary("run-1")
        s2 = agg.get_summary("run-2")
        assert s1 is not None and s2 is not None
        assert s1.total_tokens == 150
        assert s2.total_tokens == 500

    def test_get_totals_missing_run(self) -> None:
        """get_totals returns zeros for unknown run."""
        agg = CostAggregator()
        totals = agg.get_totals("nonexistent")
        assert totals["total_cost_usd"] == 0.0
        assert totals["total_tokens"] == 0

    def test_get_summary_missing_run(self) -> None:
        """get_summary returns None for unknown run."""
        agg = CostAggregator()
        assert agg.get_summary("nonexistent") is None

    def test_unknown_model_zero_cost(self) -> None:
        """Unknown model produces zero cost but still tracks tokens."""
        registry = ModelCostRegistry(prices={})
        agg = CostAggregator(registry=registry)

        agg.on_event(self._make_llm_event(model="unknown-xyz", input_tokens=500, output_tokens=200))

        summary = agg.get_summary("run-1")
        assert summary is not None
        assert summary.total_cost_usd == 0.0
        assert summary.total_tokens == 700
        assert summary.call_count == 1

    def test_on_event_ignores_non_llm_events(self) -> None:
        """Non-LLMCalled events are silently ignored."""
        from orchestra.storage.events import NodeStarted
        agg = CostAggregator()
        event = NodeStarted(run_id="run-1", node_id="node-1")
        agg.on_event(event)  # Should not crash
        assert agg.get_summary("run-1") is None

    def test_on_event_never_raises(self) -> None:
        """on_event swallows exceptions (never crashes workflow)."""
        agg = CostAggregator()
        # Pass garbage — should not raise
        agg.on_event("not an event")
        agg.on_event(None)
        agg.on_event(42)

    def test_execution_completed_logs_summary(self) -> None:
        """ExecutionCompleted triggers summary logging."""
        registry = ModelCostRegistry(prices={
            "gpt-4o": {"input_cost_per_token": 0.001, "output_cost_per_token": 0.002}
        })
        agg = CostAggregator(registry=registry)
        agg.on_event(self._make_llm_event(input_tokens=100, output_tokens=50))
        # Should not crash
        agg.on_event(self._make_execution_completed())

    def test_parallel_attribution(self) -> None:
        """Multiple agents in same run accumulate correctly (parallel simulation)."""
        registry = ModelCostRegistry(prices={
            "gpt-4o": {"input_cost_per_token": 0.001, "output_cost_per_token": 0.002}
        })
        agg = CostAggregator(registry=registry)

        # Simulate parallel agents
        agg.on_event(self._make_llm_event(agent_name="agent-a", node_id="node-a", input_tokens=100, output_tokens=50))
        agg.on_event(self._make_llm_event(agent_name="agent-b", node_id="node-b", input_tokens=200, output_tokens=100))
        agg.on_event(self._make_llm_event(agent_name="agent-a", node_id="node-a", input_tokens=150, output_tokens=75))

        summary = agg.get_summary("run-1")
        assert summary is not None
        assert summary.call_count == 3
        assert summary.total_input_tokens == 450
        assert summary.total_output_tokens == 225
        assert summary.by_agent["agent-a"]["call_count"] == 2
        assert summary.by_agent["agent-b"]["call_count"] == 1
        assert summary.by_agent["agent-a"]["input_tokens"] == 250
        assert summary.by_agent["agent-b"]["input_tokens"] == 200

    def test_default_registry_used(self) -> None:
        """CostAggregator creates default registry if none provided."""
        agg = CostAggregator()
        assert agg.registry is not None
        assert len(agg.registry.models) > 0


# ---------------------------------------------------------------------------
# BudgetPolicy Tests
# ---------------------------------------------------------------------------


class TestBudgetPolicy:
    """Tests for BudgetPolicy."""

    def test_no_limits_always_allowed(self) -> None:
        """With no limits set, everything is allowed."""
        policy = BudgetPolicy()
        result = policy.check(999.99, 999999)
        assert result.allowed is True
        assert result.soft_limit_hit is False
        assert result.hard_limit_hit is False

    def test_under_soft_limit(self) -> None:
        """Usage below soft limit passes cleanly."""
        policy = BudgetPolicy(soft_limit_usd=1.0)
        result = policy.check(0.5, 0)
        assert result.allowed is True
        assert result.soft_limit_hit is False

    def test_soft_limit_usd_triggers_warning(self) -> None:
        """Exceeding soft USD limit triggers warning but allows call."""
        policy = BudgetPolicy(soft_limit_usd=1.0)
        result = policy.check(1.5, 0)
        assert result.allowed is True
        assert result.soft_limit_hit is True
        assert result.hard_limit_hit is False
        assert "Soft USD limit" in result.reason

    def test_soft_limit_tokens_triggers_warning(self) -> None:
        """Exceeding soft token limit triggers warning but allows call."""
        policy = BudgetPolicy(soft_limit_tokens=10000)
        result = policy.check(0.0, 15000)
        assert result.allowed is True
        assert result.soft_limit_hit is True
        assert "Soft token limit" in result.reason

    def test_hard_limit_usd_blocks(self) -> None:
        """Exceeding hard USD limit blocks the call."""
        policy = BudgetPolicy(hard_limit_usd=5.0)
        result = policy.check(5.0, 0)
        assert result.allowed is False
        assert result.hard_limit_hit is True
        assert "Hard USD limit" in result.reason

    def test_hard_limit_tokens_blocks(self) -> None:
        """Exceeding hard token limit blocks the call."""
        policy = BudgetPolicy(hard_limit_tokens=50000)
        result = policy.check(0.0, 60000)
        assert result.allowed is False
        assert result.hard_limit_hit is True
        assert "Hard token limit" in result.reason

    def test_soft_and_hard_both_usd(self) -> None:
        """Soft limit hit, hard limit not yet."""
        policy = BudgetPolicy(soft_limit_usd=1.0, hard_limit_usd=5.0)
        result = policy.check(2.0, 0)
        assert result.allowed is True
        assert result.soft_limit_hit is True
        assert result.hard_limit_hit is False

    def test_hard_limit_overrides_soft(self) -> None:
        """When hard limit is hit, soft limit state is not reported."""
        policy = BudgetPolicy(soft_limit_usd=1.0, hard_limit_usd=5.0)
        result = policy.check(6.0, 0)
        assert result.allowed is False
        assert result.hard_limit_hit is True
        # Soft is not checked when hard is hit
        assert result.soft_limit_hit is False

    def test_enforce_raises_budget_exceeded(self) -> None:
        """enforce() raises BudgetExceededError on hard limit."""
        policy = BudgetPolicy(hard_limit_usd=1.0)
        with pytest.raises(BudgetExceededError, match="Hard USD limit"):
            policy.enforce(2.0, 0)

    def test_enforce_returns_result_when_allowed(self) -> None:
        """enforce() returns BudgetCheckResult when within limits."""
        policy = BudgetPolicy(hard_limit_usd=10.0)
        result = policy.enforce(2.0, 0)
        assert result.allowed is True

    def test_downgrade_model_suggestion(self) -> None:
        """Soft limit with downgrade_model suggests cheaper model."""
        policy = BudgetPolicy(
            soft_limit_usd=1.0,
            downgrade_model="gpt-3.5-turbo",
        )
        result = policy.check(1.5, 0)
        assert result.allowed is True
        assert result.soft_limit_hit is True
        assert result.suggested_model == "gpt-3.5-turbo"

    def test_no_downgrade_when_under_limit(self) -> None:
        """No model suggestion when under limit."""
        policy = BudgetPolicy(
            soft_limit_usd=10.0,
            downgrade_model="gpt-3.5-turbo",
        )
        result = policy.check(1.0, 0)
        assert result.suggested_model is None

    def test_exact_soft_limit_triggers(self) -> None:
        """Exactly at soft limit triggers the warning."""
        policy = BudgetPolicy(soft_limit_usd=1.0)
        result = policy.check(1.0, 0)
        assert result.soft_limit_hit is True

    def test_exact_hard_limit_triggers(self) -> None:
        """Exactly at hard limit triggers blocking."""
        policy = BudgetPolicy(hard_limit_usd=1.0)
        result = policy.check(1.0, 0)
        assert result.hard_limit_hit is True
        assert result.allowed is False

    def test_budget_check_result_fields(self) -> None:
        """BudgetCheckResult carries current usage data."""
        policy = BudgetPolicy(soft_limit_usd=1.0)
        result = policy.check(1.5, 5000)
        assert result.current_cost_usd == 1.5
        assert result.current_tokens == 5000

    def test_combined_usd_and_token_limits(self) -> None:
        """Both USD and token limits can be set independently."""
        policy = BudgetPolicy(
            soft_limit_usd=1.0,
            hard_limit_usd=5.0,
            soft_limit_tokens=10000,
            hard_limit_tokens=50000,
        )
        # Under both soft limits
        result = policy.check(0.5, 5000)
        assert result.allowed is True
        assert result.soft_limit_hit is False

        # Over token soft, under USD soft
        result = policy.check(0.5, 15000)
        assert result.allowed is True
        assert result.soft_limit_hit is True

        # Over USD hard
        result = policy.check(6.0, 5000)
        assert result.allowed is False
        assert result.hard_limit_hit is True


# ---------------------------------------------------------------------------
# Integration: BudgetExceededError in errors module
# ---------------------------------------------------------------------------


class TestBudgetExceededError:
    """Tests for BudgetExceededError."""

    def test_is_orchestra_error(self) -> None:
        """BudgetExceededError inherits from OrchestraError."""
        from orchestra.core.errors import OrchestraError
        err = BudgetExceededError("test")
        assert isinstance(err, OrchestraError)

    def test_has_message(self) -> None:
        """BudgetExceededError carries the reason message."""
        err = BudgetExceededError("Budget exceeded: $5.00")
        assert "Budget exceeded" in str(err)


# ---------------------------------------------------------------------------
# Integration: Imports from cost.__init__
# ---------------------------------------------------------------------------


class TestCostModuleExports:
    """Tests that cost module exports are correct."""

    def test_imports_from_init(self) -> None:
        """All public classes are importable from orchestra.cost."""
        from orchestra.cost import (
            CostAggregator,
            BudgetCheckResult,
            BudgetPolicy,
            ModelCostRegistry,
            RunCostSummary,
        )
        assert CostAggregator is not None
        assert BudgetCheckResult is not None
        assert BudgetPolicy is not None
        assert ModelCostRegistry is not None
        assert RunCostSummary is not None
