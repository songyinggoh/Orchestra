"""Research workflow demonstrating time-travel debugging.

Demonstrates:
- Multi-step research workflow
- Event log inspection
- Forking from historical checkpoint with modified parameters

Usage:
    python examples/time_travel.py
"""

import asyncio

from orchestra.core.agent import agent
from orchestra.core.graph import WorkflowGraph
from orchestra.storage.store import InMemoryEventStore
from orchestra.testing.scripted import ScriptedLLM


@agent(name="planner")
async def planner_agent(input: str) -> str:
    """Create a research plan for the given topic."""
    return f"Plan for {input}"


@agent(name="researcher")
async def researcher_agent(input: str) -> str:
    """Find facts based on the plan."""
    return f"Facts for {input}"


async def main() -> None:
    # 1. Build graph
    graph = WorkflowGraph()
    graph.then(planner_agent).then(researcher_agent)
    compiled = graph.compile()
    store = InMemoryEventStore()

    # 2. Setup mock provider
    provider = ScriptedLLM(
        [
            "Plan: 1. History, 2. Tech, 3. Future.",
            "Facts: Here are some facts about quantum computing.",
        ]
    )

    # 3. Original Run: Researching Quantum Computing
    print("\n--- Original Run: Quantum Computing ---")
    state = await compiled.run(
        input="Quantum Computing", provider=provider, event_store=store, run_id="orig_run"
    )
    print(f"Final State: {state['researcher_output']}")

    # 4. Time Travel: Fork from turn 1 (after planner)
    # We want to change the topic to 'Fusion Energy' after the plan was already made
    # Sequence mapping (approx): 0:Started, 1:NodeStarted(planner), 2:NodeCompleted(planner)
    print("\n--- Time Travel: Forking from Plan ---")

    # Fork after planner completed (SEQ 2)
    new_run_id, fork_state = await compiled.fork(
        "orig_run",
        sequence_number=2,
        state_overrides={"input": "Fusion Energy", "planner_output": "Plan for Fusion"},
        event_store=store,
    )

    # 5. Run the fork with new provider responses
    fork_provider = ScriptedLLM(["Facts: Here are some facts about Fusion Energy."])

    print(f"Forked Run ID: {new_run_id}")
    final_fork_state = await compiled.run(
        fork_state, run_id=new_run_id, provider=fork_provider, event_store=store
    )

    print(f"Forked Final State: {final_fork_state['researcher_output']}")


if __name__ == "__main__":
    asyncio.run(main())
