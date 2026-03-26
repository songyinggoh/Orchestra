"""Content generation with human approval checkpoint.

Demonstrates:
- Writer agent generates content
- HITL interrupt_after for human review
- State inspection and modification
- Resume after approval or revision request

Usage:
    python examples/hitl_review.py
"""

import asyncio

from orchestra.core.agent import agent
from orchestra.core.graph import WorkflowGraph
from orchestra.core.types import LLMResponse
from orchestra.storage.store import InMemoryEventStore
from orchestra.testing.scripted import ScriptedLLM


@agent(name="writer")
async def writer_agent(input: str) -> str:
    """You are a creative writer. Generate a short story based on the input."""
    return "Once upon a time..."


@agent(name="editor")
async def editor_agent(input: str) -> str:
    """You are an editor. Polishing the writer's work."""
    return "The story was improved."


async def main() -> None:
    # 1. Build graph with HITL interrupt
    graph = WorkflowGraph()
    graph.add_node("writer", writer_agent, interrupt_after=True)
    graph.add_node("editor", editor_agent)
    graph.add_edge("writer", "editor")
    graph.set_entry_point("writer")

    compiled = graph.compile()
    store = InMemoryEventStore()

    # 2. Setup mock responses
    writer_resp = LLMResponse(content="The quick brown fox jumps over the lazy dog.")
    editor_resp = LLMResponse(content="The final polished version of the fox story.")
    provider = ScriptedLLM([writer_resp, editor_resp])

    # 3. Initial Run - will interrupt after 'writer'
    print("\n--- Phase 1: Writing ---")
    state = await compiled.run(
        input="Write a story about a fox.", provider=provider, event_store=store
    )

    run_id = state["__metadata__"]["run_id"]
    print(f"Status: {state['__metadata__']['status']}")
    print(f"Interrupted at: {state['__metadata__']['interrupted_at']}")
    print(f"Draft Content: {state['writer_output']}")

    # 4. Simulate Human Review & Resume
    print("\n--- Phase 2: Human Review & Resume ---")
    print("Human adds feedback: 'Make it more dramatic.'")

    # We modify the state to include human feedback before resuming
    resumed_state = await compiled.resume(
        run_id,
        state_updates={"human_feedback": "Make it more dramatic."},
        event_store=store,
        provider=provider,
    )

    print("Status: Completed")
    print(f"Final Polished Content: {resumed_state['editor_output']}")


if __name__ == "__main__":
    asyncio.run(main())
