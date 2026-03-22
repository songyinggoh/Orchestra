import pytest

from orchestra.routing.router import CostAwareRouter, ModelOption, ModelSelectionError
from orchestra.routing.types import BudgetConstraint, SelectionFallback, SLAConstraint


@pytest.mark.asyncio
async def test_select_model_within_budget_and_sla():
    router = CostAwareRouter()
    options = [
        ModelOption(
            "smart",
            "p1",
            input_cost_1k=0.01,
            output_cost_1k=0.03,
            latency_score=4,
            capability_score=5,
        ),
        ModelOption(
            "fast",
            "p2",
            input_cost_1k=0.001,
            output_cost_1k=0.002,
            latency_score=1,
            capability_score=3,
        ),
        ModelOption(
            "mid",
            "p3",
            input_cost_1k=0.005,
            output_cost_1k=0.01,
            latency_score=2,
            capability_score=4,
        ),
    ]

    # Request that only 'mid' or 'smart' can satisfy (capability >= 4)
    # but only 'mid' and 'fast' satisfy budget (cost < 0.01)
    # Result should be 'mid'
    decision = await router.select_model(
        options,
        estimated_tokens=500,
        sla=SLAConstraint(min_capability_score=4),
        budget=BudgetConstraint(max_cost_usd=0.01),
        fallback=SelectionFallback.FAIL_FAST,
    )
    assert decision.model.model_name == "mid"
    assert decision.fallback_used is None


@pytest.mark.asyncio
async def test_fail_fast_raises_on_conflict():
    router = CostAwareRouter()
    options = [
        ModelOption(
            "smart",
            "p1",
            input_cost_1k=0.1,
            output_cost_1k=0.3,
            latency_score=4,
            capability_score=5,
        ),
    ]

    # Budget too low for the only available model
    with pytest.raises(ModelSelectionError):
        await router.select_model(
            options,
            budget=BudgetConstraint(max_cost_usd=0.001),
            fallback=SelectionFallback.FAIL_FAST,
        )


@pytest.mark.asyncio
async def test_favor_cost_relaxes_sla():
    router = CostAwareRouter()
    options = [
        ModelOption(
            "smart",
            "p1",
            input_cost_1k=0.01,
            output_cost_1k=0.03,
            latency_score=4,
            capability_score=5,
        ),
        ModelOption(
            "cheap",
            "p2",
            input_cost_1k=0.001,
            output_cost_1k=0.001,
            latency_score=2,
            capability_score=2,
        ),
    ]

    # Request capability=5 but budget only allows 'cheap'
    decision = await router.select_model(
        options,
        sla=SLAConstraint(min_capability_score=5),
        budget=BudgetConstraint(max_cost_usd=0.005),
        fallback=SelectionFallback.FAVOR_COST,
    )
    assert decision.model.model_name == "cheap"
    assert decision.fallback_used == SelectionFallback.FAVOR_COST


@pytest.mark.asyncio
async def test_favor_latency_relaxes_budget():
    router = CostAwareRouter()
    options = [
        ModelOption(
            "fast-expensive",
            "p1",
            input_cost_1k=0.02,
            output_cost_1k=0.02,
            latency_score=1,
            capability_score=3,
        ),
        ModelOption(
            "slow-cheap",
            "p2",
            input_cost_1k=0.001,
            output_cost_1k=0.001,
            latency_score=5,
            capability_score=3,
        ),
    ]

    # Request latency_score=1 (fast) with budget 0.01
    # fast-expensive costs 0.02 (at 500 tokens = 0.02 * 0.5 + 0.02 * 0.5 = 0.02)
    # wait, est_cost = (500/1000) * (0.02 + 0.02) = 0.02.
    # 0.02 > 0.01. But FAVOR_LATENCY allows 1.5x budget (0.015).
    # Still 0.02 > 0.015. So it will fall back to just picking fastest among all options if empty.
    # Let's adjust budget to 0.015. 1.5x = 0.0225. Now 0.02 < 0.0225.

    decision = await router.select_model(
        options,
        estimated_tokens=500,
        sla=SLAConstraint(max_latency_ms=400),  # score 1
        budget=BudgetConstraint(max_cost_usd=0.015),
        fallback=SelectionFallback.FAVOR_LATENCY,
    )
    assert decision.model.model_name == "fast-expensive"
    assert decision.fallback_used == SelectionFallback.FAVOR_LATENCY


@pytest.mark.asyncio
async def test_empty_options_raises():
    router = CostAwareRouter()
    with pytest.raises(ValueError):
        await router.select_model([])


def test_report_outcome_updates_posteriors():
    router = CostAwareRouter()
    _opt = ModelOption("test", "p1")

    # Success
    router.report_outcome("test", "p1", True)
    assert router._selector._stats[("test", "p1")][0] == 2.0  # 1.0 init + 1.0

    # Failure
    router.report_outcome("test", "p1", False)
    assert router._selector._stats[("test", "p1")][1] == 2.0  # 1.0 init + 1.0


@pytest.mark.asyncio
async def test_thompson_sampling_exploration():
    # Verify that with uniform priors, different models are explored
    router = CostAwareRouter()
    options = [
        ModelOption("a", "p1", latency_score=3, capability_score=3),
        ModelOption("b", "p1", latency_score=3, capability_score=3),
    ]

    selections = {"a": 0, "b": 0}
    for _ in range(100):
        decision = await router.select_model(options)
        selections[decision.model.model_name] += 1

    # Both should be selected at least a few times (probabilistically very likely)
    assert selections["a"] > 5
    assert selections["b"] > 5


@pytest.mark.asyncio
async def test_backward_compatible_no_constraints():
    router = CostAwareRouter()
    options = [ModelOption("a", "p1")]

    # Should work without any optional args
    decision = await router.select_model(options)
    assert decision.model.model_name == "a"
    assert decision.fallback_used is None
