"""Tests for HITL (Interrupt/Resume) functionality."""

from __future__ import annotations

import pytest
from orchestra.core.graph import WorkflowGraph
from orchestra.core.types import WorkflowStatus
from orchestra.storage.store import InMemoryEventStore


@pytest.mark.asyncio
async def test_interrupt_before() -> None:
    """Verify workflow pauses before an interrupted node."""
    graph = WorkflowGraph()
    
    async def step1(state: dict) -> dict:
        return {"count": 1}
        
    async def step2(state: dict) -> dict:
        return {"count": state["count"] + 1}
        
    graph.add_node("n1", step1)
    graph.add_node("n2", step2, interrupt_before=True)
    graph.add_edge("n1", "n2")
    graph.set_entry_point("n1")
    
    compiled = graph.compile()
    store = InMemoryEventStore()
    
    # Run until interrupt
    state = await compiled.run({"count": 0}, event_store=store)
    
    assert state["count"] == 1
    assert state["__metadata__"]["status"] == WorkflowStatus.INTERRUPTED
    assert state["__metadata__"]["interrupted_at"] == "n2"
    assert state["__metadata__"]["interrupt_type"] == "before"
    
    # Verify checkpoint exists
    checkpoint = await store.get_latest_checkpoint(state["__metadata__"]["run_id"])
    assert checkpoint is not None
    assert checkpoint.node_id == "n2"
    assert checkpoint.state["count"] == 1
    
    # Resume
    final_state = await compiled.resume(state["__metadata__"]["run_id"], event_store=store)
    assert final_state["count"] == 2
    assert final_state.get("__metadata__") is None or final_state["__metadata__"].get("status") == "completed"


@pytest.mark.asyncio
async def test_interrupt_after() -> None:
    """Verify workflow pauses after an interrupted node."""
    graph = WorkflowGraph()
    
    async def step1(state: dict) -> dict:
        return {"count": 1}
        
    async def step2(state: dict) -> dict:
        return {"count": 2}
        
    graph.add_node("n1", step1, interrupt_after=True)
    graph.add_node("n2", step2)
    graph.add_edge("n1", "n2")
    graph.set_entry_point("n1")
    
    compiled = graph.compile()
    store = InMemoryEventStore()
    
    state = await compiled.run(event_store=store)
    
    assert state["count"] == 1
    assert state["__metadata__"]["status"] == WorkflowStatus.INTERRUPTED
    assert state["__metadata__"]["interrupted_at"] == "n1"
    assert state["__metadata__"]["interrupt_type"] == "after"
    assert state["__metadata__"]["next_node"] == "n2"
    
    # Resume
    final_state = await compiled.resume(state["__metadata__"]["run_id"], event_store=store)
    assert final_state["count"] == 2


@pytest.mark.asyncio
async def test_resume_with_state_updates() -> None:
    """Verify state can be modified during resume."""
    graph = WorkflowGraph()
    
    async def node(state: dict) -> dict:
        return {"result": state["input"] * 2}
        
    graph.add_node("process", node, interrupt_before=True)
    graph.set_entry_point("process")
    
    compiled = graph.compile()
    store = InMemoryEventStore()
    
    # Interrupt before 'process'
    state = await compiled.run({"input": 10}, event_store=store)
    run_id = state["__metadata__"]["run_id"]
    
    # Resume with modified state
    final_state = await compiled.resume(
        run_id, 
        state_updates={"input": 50}, 
        event_store=store
    )
    
    assert final_state["result"] == 100
