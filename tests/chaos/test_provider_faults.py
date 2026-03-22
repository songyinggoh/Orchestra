"""Chaos tests: fault injection for LLM provider failures.

Tests that the workflow engine handles provider faults gracefully:
timeouts, rate-limit errors, and malformed responses.
"""

from __future__ import annotations

import pytest

from orchestra.core.agent import agent
from orchestra.core.errors import AgentError
from orchestra.core.graph import WorkflowGraph
from orchestra.core.runner import run
from tests.chaos.fault_injectors import FaultInjector

# ---------------------------------------------------------------------------
# Shared test agent
# ---------------------------------------------------------------------------


@agent(name="chaos-agent")
async def chaos_agent(state):
    """A minimal agent used for chaos injection tests."""


# ---------------------------------------------------------------------------
# Provider fault tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_always_error_raises_exception():
    """FaultInjector with error_rate=1.0 causes run() to propagate a RuntimeError."""
    g = WorkflowGraph().then(chaos_agent, name="node")
    injector = FaultInjector(error_rate=1.0)

    with pytest.raises((AgentError, RuntimeError)):
        await run(g, provider=injector, persist=False)


@pytest.mark.asyncio
async def test_always_timeout_raises_exception():
    """FaultInjector with timeout_rate=1.0 causes run() to raise TimeoutError."""
    g = WorkflowGraph().then(chaos_agent, name="node")
    injector = FaultInjector(timeout_rate=1.0)

    with pytest.raises((AgentError, RuntimeError, TimeoutError)):
        await run(g, provider=injector, persist=False)


@pytest.mark.asyncio
async def test_malformed_response_returns_empty_content():
    """FaultInjector with malformed_rate=1.0 returns empty content without crashing."""
    g = WorkflowGraph().then(chaos_agent, name="node")
    injector = FaultInjector(malformed_rate=1.0)

    # Should complete — the engine must not crash on empty content
    result = await run(g, provider=injector, persist=False)
    assert result is not None


@pytest.mark.asyncio
async def test_zero_fault_rate_succeeds():
    """FaultInjector with all rates at 0.0 completes successfully."""
    g = WorkflowGraph().then(chaos_agent, name="node")
    injector = FaultInjector(error_rate=0.0, timeout_rate=0.0, malformed_rate=0.0)

    result = await run(g, provider=injector, persist=False)
    assert result is not None


@pytest.mark.asyncio
async def test_fault_injector_call_count():
    """FaultInjector.call_count increments with each provider call."""
    g = WorkflowGraph().then(chaos_agent, name="node")
    injector = FaultInjector(error_rate=0.0)

    await run(g, provider=injector, persist=False)

    # At least one complete() call was made for the agent node
    assert injector.call_count >= 1


@pytest.mark.asyncio
async def test_fault_injector_records_fault_count_on_error():
    """FaultInjector.fault_count increments when a fault fires."""
    g = WorkflowGraph().then(chaos_agent, name="node")
    injector = FaultInjector(error_rate=1.0)

    with pytest.raises((AgentError, RuntimeError)):
        await run(g, provider=injector, persist=False)

    # At least one fault was recorded before the error propagated
    assert injector.fault_count >= 1
