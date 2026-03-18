"""Reliability tests for the graph execution engine, including chaos testing."""

from __future__ import annotations

import pytest

from orchestra.core.agent import agent
from orchestra.core.graph import WorkflowGraph
from orchestra.core.runner import run
from orchestra.core.errors import AgentError
from orchestra.core.types import LLMResponse, TokenUsage
from orchestra.core.protocols import LLMProvider


class FailingLLM:
    """A mock LLM provider that fails on the nth call."""

    provider_name = "failing-llm"
    default_model = "default"

    def __init__(self, fail_on_call: int, success_response: LLMResponse):
        self.fail_on_call = fail_on_call
        self.success_response = success_response
        self.call_count = 0

    async def complete(self, *args, **kwargs) -> LLMResponse:
        self.call_count += 1
        if self.call_count >= self.fail_on_call:
            raise RuntimeError("Simulated LLM API failure")
        return self.success_response


class AlwaysFailLLM:
    """A mock LLM provider that always fails."""

    provider_name = "always-fail-llm"
    default_model = "default"

    async def complete(self, *args, **kwargs) -> LLMResponse:
        raise RuntimeError("Simulated LLM API failure")


@agent(name="simple-agent")
async def simple_agent(state):
    """You are a simple test agent."""


@pytest.mark.asyncio
async def test_workflow_handles_llm_failure_gracefully():
    """Workflow run propagates an exception when the LLM provider fails on first call."""
    g = WorkflowGraph().then(simple_agent, name="a")
    llm = AlwaysFailLLM()

    with pytest.raises((AgentError, RuntimeError), match="Simulated LLM API failure"):
        await run(g, provider=llm, persist=False)


@pytest.mark.asyncio
async def test_workflow_succeeds_when_llm_succeeds():
    """Workflow run completes successfully when LLM provider works."""
    g = WorkflowGraph().then(simple_agent, name="a")
    success_response = LLMResponse(content="done", usage=TokenUsage(cost_usd=0.001))
    llm = FailingLLM(fail_on_call=999, success_response=success_response)

    result = await run(g, provider=llm, persist=False)

    assert result is not None
    assert llm.call_count >= 1


@pytest.mark.asyncio
async def test_multi_node_workflow_failure_in_second_node():
    """Failure in the second node propagates and stops the workflow."""

    @agent(name="node-a")
    async def node_a(state):
        """Node A."""

    @agent(name="node-b")
    async def node_b(state):
        """Node B."""

    g = WorkflowGraph().then(node_a, name="a").then(node_b, name="b")

    # Fails on second call (node-b's LLM call)
    success_response = LLMResponse(content="ok", usage=TokenUsage(cost_usd=0.001))
    llm = FailingLLM(fail_on_call=2, success_response=success_response)

    with pytest.raises((AgentError, RuntimeError), match="Simulated LLM API failure"):
        await run(g, provider=llm, persist=False)

    assert llm.call_count == 2  # First node succeeded, second failed
