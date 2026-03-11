"""Chaos tests: storage and EventStore fault handling.

Tests that the workflow engine operates correctly when storage is
unavailable or when persist=False is used.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from orchestra.core.graph import WorkflowGraph
from orchestra.core.runner import run


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_simple_graph(name: str = "storage-test") -> Any:
    """Build a minimal one-node graph that returns a fixed output."""
    from orchestra.core.graph import WorkflowGraph

    async def echo(state: dict[str, Any]) -> dict[str, Any]:
        return {"output": state.get("input", "default")}

    graph = WorkflowGraph(name=name)
    graph.add_node("echo", echo)
    graph.set_entry_point("echo")
    return graph.compile()


# ---------------------------------------------------------------------------
# Storage fault tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_with_persist_false_skips_storage():
    """run(graph, persist=False) succeeds without any storage backend."""
    compiled = _make_simple_graph()

    result = await run(compiled, input={"input": "hello"}, persist=False)

    assert result is not None
    assert result.output == "hello"


@pytest.mark.asyncio
async def test_sqlite_event_store_in_memory(tmp_path):
    """SQLiteEventStore with ':memory:' path works without filesystem access."""
    try:
        from orchestra.storage.sqlite import SQLiteEventStore
    except ImportError:
        pytest.skip("aiosqlite not installed")

    compiled = _make_simple_graph("sqlite-memory")
    store = SQLiteEventStore(":memory:")
    await store.initialize()

    result = await compiled.run(
        input={"input": "world"},
        persist=False,
        event_store=store,
    )

    assert result.get("output") == "world"
    await store.close()


@pytest.mark.asyncio
async def test_multiple_runs_no_state_bleed():
    """Running the same compiled graph twice yields independent results."""
    compiled = _make_simple_graph("no-bleed")

    result_a = await run(compiled, input={"input": "run-a"}, persist=False)
    result_b = await run(compiled, input={"input": "run-b"}, persist=False)

    # Each run produces its own output — no state leaks between runs
    assert result_a.output == "run-a"
    assert result_b.output == "run-b"
    assert result_a.run_id != result_b.run_id


@pytest.mark.asyncio
async def test_in_memory_event_store_can_be_injected():
    """Explicit InMemoryEventStore can be passed as event_store override."""
    from orchestra.storage.store import InMemoryEventStore

    compiled = _make_simple_graph("in-memory")
    store = InMemoryEventStore()

    result = await compiled.run(
        input={"input": "stored"},
        persist=False,
        event_store=store,
    )

    assert result.get("output") == "stored"
    # Events should be stored for the run
    runs = await store.list_runs()
    assert len(runs) >= 1
