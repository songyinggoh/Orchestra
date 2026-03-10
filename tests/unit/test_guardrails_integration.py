"""Integration tests for guardrails in CompiledGraph."""

from __future__ import annotations

import pytest

from orchestra.core.agent import agent
from orchestra.core.graph import WorkflowGraph
from orchestra.core.types import END
from orchestra.security.guardrails import ContentFilter
from orchestra.testing import ScriptedLLM


from orchestra.core.state import WorkflowState

class State(WorkflowState):
    input: str = ""
    output: str = ""
    guardrails: dict = {}

@pytest.mark.asyncio
async def test_compiled_graph_invokes_input_guardrail():
    # Setup
    g = WorkflowGraph(name="test_guardrails", state_schema=State)
    
    @agent(name="bob")
    async def bob(input_text: str) -> str:
        return f"Bob heard: {input_text}"

    g.add_node("bob", bob, output_key="output")
    g.set_entry_point("bob")
    g.add_edge("bob", END)
    
    compiled = g.compile()
    
    # Configure guardrail in context
    from orchestra.core.context import ExecutionContext
    
    # We need a provider even if it's not called
    provider = ScriptedLLM(["Bob heard: ..."])
    
    ctx = ExecutionContext(run_id="test_run", provider=provider)
    ctx.config["guardrails"] = [ContentFilter(banned_words=["apple"])]
    ctx.config["guardrails_fail"] = "refuse"
    
    # Act: Run with banned word in input
    result = await compiled.run(input="I want an apple", context=ctx)
    
    # Assert
    assert result["output"] == "Guardrail rejected input"
    assert "violations" in result["guardrails"]
    assert "apple" in result["guardrails"]["violations"][0].lower()


@pytest.mark.asyncio
async def test_compiled_graph_invokes_output_guardrail():
    # Setup
    g = WorkflowGraph(name="test_guardrails_output", state_schema=State)
    
    @agent(name="alice")
    async def alice(input_text: str) -> str:
        return "Here is your secret: 123-45-6789"

    g.add_node("alice", alice, output_key="output")
    g.set_entry_point("alice")
    g.add_edge("alice", END)
    
    compiled = g.compile()
    
    # Configure provider to return the sensitive data
    provider = ScriptedLLM(["Here is your secret: 123-45-6789"])
    
    from orchestra.core.context import ExecutionContext
    ctx = ExecutionContext(run_id="test_run_output", provider=provider)
    ctx.config["guardrails"] = [ContentFilter(patterns=[r"\d{3}-\d{2}-\d{4}"])]
    ctx.config["guardrails_fail"] = "refuse"
    
    # Act: Run
    result = await compiled.run(input="Tell me a secret", context=ctx)
    
    # Assert
    assert result["output"] == "Guardrail rejected output"
    assert "violations" in result["guardrails"]
    assert "pattern" in result["guardrails"]["violations"][0].lower()


@pytest.mark.asyncio
async def test_compiled_graph_raises_on_guardrail_failure():
    # Setup
    g = WorkflowGraph(name="test_guardrails_raise")
    
    @agent(name="charlie")
    async def charlie(input_text: str) -> str:
        return "banned"

    g.add_node("charlie", charlie)
    g.set_entry_point("charlie")
    g.add_edge("charlie", END)
    
    compiled = g.compile()
    
    provider = ScriptedLLM(["banned"])
    
    # Configure guardrail to raise
    from orchestra.core.context import ExecutionContext
    from orchestra.core.errors import AgentError
    
    ctx = ExecutionContext(run_id="test_run_raise", provider=provider)
    ctx.config["guardrails"] = [ContentFilter(banned_words=["banned"])]
    ctx.config["guardrails_fail"] = "raise"
    
    # Act & Assert
    with pytest.raises(AgentError, match="Guardrail rejected output"):
        await compiled.run(input="hi", context=ctx)
