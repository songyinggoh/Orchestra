"""Full-stack integration test: all Phase 3 components wired together.

Covers:
  - Cost tracking (CostAggregator / BudgetPolicy)
  - Caching (CachedProvider + InMemoryCacheBackend)
  - Guardrails (GuardrailChain + MaxLengthGuardrail)
  - Workflow execution (WorkflowGraph + @agent decorator + run())

All tests use persist=False to avoid SQLite dependency in CI.
"""

from __future__ import annotations

import pytest

from orchestra.cache.backends import InMemoryCacheBackend
from orchestra.core.agent import agent
from orchestra.core.graph import WorkflowGraph
from orchestra.core.runner import run
from orchestra.core.types import LLMResponse, TokenUsage
from orchestra.cost import BudgetPolicy
from orchestra.providers.cached import CachedProvider
from orchestra.security.guardrails import GuardrailChain, OnFail
from orchestra.security.validators import MaxLengthGuardrail

# ---------------------------------------------------------------------------
# Inline ScriptedLLM (independent of conftest — tests are self-contained)
# ---------------------------------------------------------------------------


class ScriptedLLM:
    """Minimal scripted LLM used for full-stack tests.

    Returns a fixed canned response on each call and tracks the total number
    of actual provider invocations so cache-hit assertions remain precise.
    """

    provider_name: str = "scripted"
    default_model: str = "test-model"

    def __init__(self, response: str = "ok") -> None:
        self.response = response
        self.call_count = 0

    async def complete(self, *args, **kwargs) -> LLMResponse:
        self.call_count += 1
        return LLMResponse(
            content=self.response,
            usage=TokenUsage(
                input_tokens=10,
                output_tokens=5,
                total_tokens=15,
                estimated_cost_usd=0.001,
            ),
        )

    def count_tokens(self, *args, **kwargs) -> int:
        return 10

    def get_model_cost(self, *args, **kwargs):
        return None


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _simple_graph(agent_name: str) -> WorkflowGraph:
    """Build a one-node WorkflowGraph whose single node is a BaseAgent."""

    @agent(name=agent_name)
    async def _node(state):
        """You are a helpful assistant."""

    return WorkflowGraph().then(_node, name="a")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_with_scripted_llm():
    """Basic smoke test: a workflow run completes and the LLM is called."""
    scripted = ScriptedLLM()
    g = _simple_graph("smoke-agent")

    result = await run(g, provider=scripted, persist=False)

    assert result is not None
    assert scripted.call_count >= 1


@pytest.mark.asyncio
async def test_cached_provider_avoids_second_llm_call():
    """Second identical workflow run should be served entirely from cache.

    The ScriptedLLM call count must not increase between the first and second
    run because the CachedProvider intercepts the second request.
    """
    scripted = ScriptedLLM()
    cache = InMemoryCacheBackend(maxsize=128, default_ttl=60)
    cached = CachedProvider(
        provider=scripted,
        cache=cache,
        max_cacheable_temperature=0.7,  # cache at the default temperature
    )

    # Build a stable graph (same node name => same cache key)
    g = _simple_graph("cached-agent")

    # First run — provider must be called
    await run(g, provider=cached, persist=False)
    count_after_first = scripted.call_count
    assert count_after_first >= 1, "First run should call the provider"

    # Second run — cache should intercept; provider call count must not grow
    await run(g, provider=cached, persist=False)
    count_after_second = scripted.call_count

    assert count_after_second == count_after_first, (
        f"Expected cache to serve second run without new LLM calls, "
        f"but provider was called {count_after_second - count_after_first} extra time(s)."
    )


@pytest.mark.asyncio
async def test_guardrails_block_long_input():
    """MaxLengthGuardrail with OnFail.BLOCK rejects text that is too long."""
    chain = GuardrailChain(
        guardrails=[MaxLengthGuardrail(max_length=10, on_fail=OnFail.BLOCK)],
    )

    result = await chain.run("this is way too long for the configured limit")

    assert not result.passed, "Long input should be blocked by MaxLengthGuardrail"
    assert result.violation is not None
    assert len(result.violations) >= 1


@pytest.mark.asyncio
async def test_guardrails_pass_short_input():
    """MaxLengthGuardrail passes text within the length limit."""
    chain = GuardrailChain(
        guardrails=[MaxLengthGuardrail(max_length=100, on_fail=OnFail.BLOCK)],
    )

    result = await chain.run("short")

    assert result.passed, "Short input should pass MaxLengthGuardrail"


@pytest.mark.asyncio
async def test_guardrails_fix_truncates_long_input():
    """MaxLengthGuardrail with OnFail.FIX truncates text instead of blocking."""
    chain = GuardrailChain(
        guardrails=[MaxLengthGuardrail(max_length=5, on_fail=OnFail.FIX)],
    )

    result = await chain.run("hello world")

    # FIX mode: chain succeeds (output fixed) but violation is recorded
    assert result.output is not None
    assert len(result.output) <= 5


@pytest.mark.asyncio
async def test_budget_policy_allows_run_under_hard_limit():
    """BudgetPolicy.check() returns allowed=True when cost is under the hard limit."""
    policy = BudgetPolicy(hard_limit_usd=10.0)

    result = policy.check(current_cost_usd=0.001, current_tokens=15)

    assert result.allowed, "Run well below hard limit should be allowed"
    assert not result.hard_limit_hit


@pytest.mark.asyncio
async def test_budget_policy_blocks_run_at_hard_limit():
    """BudgetPolicy.check() returns allowed=False when cost meets the hard limit."""
    policy = BudgetPolicy(hard_limit_usd=1.00)

    result = policy.check(current_cost_usd=1.00, current_tokens=1000)

    assert not result.allowed, "Run at hard limit should be blocked"
    assert result.hard_limit_hit


@pytest.mark.asyncio
async def test_budget_policy_warns_at_soft_limit():
    """BudgetPolicy.check() sets soft_limit_hit when cost exceeds the soft limit."""
    policy = BudgetPolicy(soft_limit_usd=0.50, hard_limit_usd=5.00)

    result = policy.check(current_cost_usd=0.75, current_tokens=100)

    assert result.allowed, "Run above soft limit but below hard limit should still be allowed"
    assert result.soft_limit_hit, "Soft limit flag should be set"
    assert not result.hard_limit_hit


@pytest.mark.asyncio
async def test_full_stack_cost_plus_cache():
    """End-to-end: CachedProvider + ScriptedLLM run twice.

    Verifies that the framework plumbing for cost-tracked and cached runs works
    end-to-end without errors. The second run must not invoke the provider.
    """
    scripted = ScriptedLLM(response="cached answer")
    cache = InMemoryCacheBackend(maxsize=64, default_ttl=300)
    cached = CachedProvider(
        provider=scripted,
        cache=cache,
        max_cacheable_temperature=0.7,
    )

    g = _simple_graph("full-stack-agent")

    result1 = await run(g, provider=cached, persist=False)
    calls_after_first = scripted.call_count

    result2 = await run(g, provider=cached, persist=False)
    calls_after_second = scripted.call_count

    assert result1 is not None
    assert result2 is not None
    assert calls_after_first >= 1
    assert calls_after_second == calls_after_first, (
        "Second run should be served from cache with no additional LLM calls"
    )
