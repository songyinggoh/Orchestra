"""Integration tests for Phase 2 advanced examples."""

from __future__ import annotations

import pytest
from examples.handoff import triage_agent, billing_agent, technical_agent
from examples.hitl_review import writer_agent, editor_agent
from examples.time_travel import planner_agent, researcher_agent

from orchestra.core.graph import WorkflowGraph
from orchestra.core.types import LLMResponse, WorkflowStatus
from orchestra.testing.scripted import ScriptedLLM
from orchestra.storage.store import InMemoryEventStore


class TestAdvancedExamples:
    @pytest.mark.asyncio
    async def test_handoff_integration(self) -> None:
        """Verify triage correctly hands off to technical specialist."""
        graph = WorkflowGraph()
        graph.add_node("triage", triage_agent)
        graph.add_node("billing", billing_agent)
        graph.add_node("technical", technical_agent)
        
        def is_technical(state: dict) -> bool:
            return "technical" in state.get("triage_output", "").lower()
            
        graph.add_handoff("triage", "technical", condition=is_technical)
        graph.set_entry_point("triage")
        
        provider = ScriptedLLM([
            LLMResponse(content="technical issue"),
            LLMResponse(content="fixed")
        ])
        
        state = await graph.compile().run(input="help", provider=provider)
        assert "fixed" in state["technical_output"]

    @pytest.mark.asyncio
    async def test_hitl_integration(self) -> None:
        """Verify HITL interrupt and resume with manual state update."""
        graph = WorkflowGraph()
        graph.add_node("writer", writer_agent, interrupt_after=True)
        graph.add_node("editor", editor_agent)
        graph.add_edge("writer", "editor")
        graph.set_entry_point("writer")
        
        store = InMemoryEventStore()
        provider = ScriptedLLM([
            LLMResponse(content="draft"),
            LLMResponse(content="polished")
        ])
        
        compiled = graph.compile()
        
        # 1. Run to interrupt
        state = await compiled.run(input="start", provider=provider, event_store=store)
        assert state["__metadata__"]["status"] == WorkflowStatus.INTERRUPTED
        run_id = state["__metadata__"]["run_id"]
        
        # 2. Resume
        final_state = await compiled.resume(run_id, state_updates={"feedback": "ok"}, event_store=store, provider=provider)
        assert final_state["editor_output"] == "polished"

    @pytest.mark.asyncio
    async def test_time_travel_fork_integration(self) -> None:
        """Verify forking from history Diverges correctly."""
        graph = WorkflowGraph()
        graph.then(planner_agent).then(researcher_agent)
        compiled = graph.compile()
        store = InMemoryEventStore()
        
        # Original: A -> B
        p1 = ScriptedLLM([LLMResponse(content="plan A"), LLMResponse(content="facts A")])
        await compiled.run(input="Topic A", provider=p1, event_store=store, run_id="orig")
        
        # Fork after planner (SEQ 2)
        new_id, fork_state, start_node = await compiled.fork("orig", 2, state_overrides={"input": "Topic B"}, event_store=store)
        print(f"FORK START NODE: {start_node}")
        
        # Run fork: should use plan A (from state) but Topic B for researcher
        p2 = ScriptedLLM([LLMResponse(content="facts B")])
        final_fork = await compiled.run(fork_state, run_id=new_id, provider=p2, event_store=store, start_at=start_node)
        
        assert final_fork["researcher_output"] == "facts B"
        assert final_fork["input"] == "Topic B"
