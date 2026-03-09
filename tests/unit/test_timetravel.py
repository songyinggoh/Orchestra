"""Tests for Time-Travel Debugging (State Reconstruction, Forking, and Replay)."""

from __future__ import annotations

import pytest
from orchestra.core.graph import WorkflowGraph
from orchestra.core.agent import BaseAgent
from orchestra.core.context import ExecutionContext
from orchestra.core.types import ToolResult, ToolCall, LLMResponse
from orchestra.storage.store import InMemoryEventStore
from orchestra.debugging.timetravel import TimeTravelController


class MockTool:
    def __init__(self, name: str):
        self.name = name
        self.description = f"Test tool {name}"
        self.parameters_schema = {}
        self.call_count = 0

    async def execute(self, arguments: dict, context: ExecutionContext) -> ToolResult:
        self.call_count += 1
        return ToolResult(tool_call_id="123", name=self.name, content=f"real_exec_{self.name}")


@pytest.mark.asyncio
async def test_state_reconstruction() -> None:
    """Verify we can reconstruct state at any sequence point."""
    graph = WorkflowGraph()
    
    async def n1_fn(s: dict) -> dict:
        return {"a": 1}
        
    async def n2_fn(s: dict) -> dict:
        return {"b": 2}
        
    graph.add_node("n1", n1_fn)
    graph.add_node("n2", n2_fn)
    graph.add_edge("n1", "n2")
    graph.set_entry_point("n1")
    
    compiled = graph.compile()
    store = InMemoryEventStore()
    
    # Run workflow
    await compiled.run(event_store=store, run_id="r1")
    
    events = await store.get_events("r1")
    for e in events:
        print(f"SEQ {e.sequence}: {e.event_type} (node={getattr(e, 'node_id', 'N/A')})")
    
    tt = TimeTravelController(store)
    
    # Events: 0:Started, 1:NodeStarted(n1), 2:NodeCompleted(n1), 3:StateUpdated(n1), 
    # 4:EdgeTraversed, 5:NodeStarted(n2), 6:NodeCompleted(n2), 7:StateUpdated(n2), 8:Finished
    
    # State after n1 completes (sequence 2)
    h1 = await tt.get_state_at("r1", 2)
    assert h1.state["a"] == 1
    assert "b" not in h1.state
    assert h1.node_id == "n1"
    
    # State after n2 completes (sequence 4)
    h2 = await tt.get_state_at("r1", 4)
    assert h2.state["a"] == 1
    assert h2.state["b"] == 2
    assert h2.node_id == "n2"


@pytest.mark.asyncio
async def test_fork_and_diverge() -> None:
    """Verify forking a run creates a new path with overridden state."""
    graph = WorkflowGraph()
    
    async def step_fn(s: dict) -> dict:
        return {"val": s.get("val", 0) + 1}
        
    graph.add_node("step", step_fn)
    graph.set_entry_point("step")
    
    compiled = graph.compile()
    store = InMemoryEventStore()
    
    # Original run: val 0 -> 1
    await compiled.run({"val": 0}, run_id="orig", event_store=store)
    
    # Fork at the start (sequence 0 - ExecutionStarted) but with val=10
    new_run_id, fork_state, *_ = await compiled.fork("orig", 0, state_overrides={"val": 10}, event_store=store)
    
    assert new_run_id != "orig"
    assert fork_state["val"] == 10
    
    # Run the fork: val 10 -> 11
    final_fork_state = await compiled.run(fork_state, run_id=new_run_id, event_store=store)
    assert final_fork_state["val"] == 11


@pytest.mark.asyncio
async def test_side_effect_safe_replay() -> None:
    """Verify that tools are not re-executed during historical replay."""
    tool = MockTool("send_email")
    agent = BaseAgent(name="mailer", tools=[tool])
    
    graph = WorkflowGraph()
    graph.add_node("agent", agent)
    graph.set_entry_point("agent")
    
    # 1. Run originally
    store = InMemoryEventStore()
    from orchestra.testing.scripted import ScriptedLLM
    
    responses = [
        LLMResponse(content="I will send the email.", tool_calls=[ToolCall(id="c1", name="send_email", arguments={})]),
        LLMResponse(content="Email sent.")
    ]
    provider = ScriptedLLM(responses)
    
    await graph.compile().run(run_id="orig", event_store=store, provider=provider)
    assert tool.call_count == 1
    
    # 2. Re-run from history using manual replay setup
    events = await store.get_events("orig")
    
    # Manual setup of replay context
    context = ExecutionContext(run_id="replay", replay_events=events)
    
    # Agent execution should find the tool result in replay_events and SKIP MockTool.execute
    res = await agent._execute_tool(ToolCall(id="c1", name="send_email", arguments={}), context)
    
    assert res.content == "real_exec_send_email" # Result from history
    assert tool.call_count == 1 # Still 1! Mock was not called during replay phase.
