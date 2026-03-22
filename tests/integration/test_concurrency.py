"""Concurrency tests for the graph execution engine."""

from __future__ import annotations

import asyncio
from typing import Annotated

import pytest

from orchestra.core.graph import WorkflowGraph
from orchestra.core.runner import run
from orchestra.core.state import WorkflowState, sum_numbers


class ConcurrencyState(WorkflowState):
    count: Annotated[int, sum_numbers] = 0
    items: list[str] = []  # Reducer is merge_list by default


async def counter_node(state: dict) -> dict:
    """Plain graph node — no LLM provider needed."""
    await asyncio.sleep(0.01)
    return {"count": 1}


@pytest.mark.asyncio
async def test_concurrent_runs_no_state_corruption():
    """Run the same compiled graph concurrently and check for correct state aggregation."""
    # Setup
    g = WorkflowGraph(state_schema=ConcurrencyState)
    g.add_node("c1", counter_node)
    g.add_node("c2", counter_node)
    g.add_edge("c1", "c2")
    g.set_entry_point("c1")
    compiled_graph = g.compile()

    # Act: Run the compiled graph 5 times concurrently
    num_concurrent_runs = 5
    tasks = [run(compiled_graph, input={}, persist=False) for _ in range(num_concurrent_runs)]
    results = await asyncio.gather(*tasks)

    # Assert: Check if the final state of one of the runs is correct.
    # Note: In a real scenario, you might want to inspect the state store
    # if it's external, but for in-memory stores, this is tricky.
    # We check if each run produced the correct result *for itself*.
    # A true race condition would likely corrupt the internal state of the
    # reducers, leading to an incorrect final count.

    for result in results:
        # Each run consists of two agents, each incrementing the count by 1.
        # So the final count for each independent run should be 2.
        assert result.state["count"] == 2
