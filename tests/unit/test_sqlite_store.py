"""Unit tests for SQLiteEventStore and SnapshotManager.

All tests use ':memory:' -- no filesystem writes during the test suite.
Uses pytest-asyncio with asyncio_mode = 'auto' (configured in pyproject.toml).
"""

from __future__ import annotations

import asyncio
import os

import pytest_asyncio

from orchestra.storage.checkpoint import Checkpoint
from orchestra.storage.events import (
    CheckpointCreated,
    EventType,
    ExecutionStarted,
    NodeCompleted,
    NodeStarted,
)
from orchestra.storage.sqlite import SnapshotManager, SQLiteEventStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_execution_started(run_id: str = "run-1", sequence: int = 0) -> ExecutionStarted:
    return ExecutionStarted(
        run_id=run_id,
        sequence=sequence,
        workflow_name="test-workflow",
        initial_state={"x": 1},
        entry_point="start",
    )


def make_node_started(
    run_id: str = "run-1", sequence: int = 1, node_id: str = "node-a"
) -> NodeStarted:
    return NodeStarted(
        run_id=run_id,
        sequence=sequence,
        node_id=node_id,
        node_type="FunctionNode",
    )


def make_node_completed(
    run_id: str = "run-1", sequence: int = 2, node_id: str = "node-a"
) -> NodeCompleted:
    return NodeCompleted(
        run_id=run_id,
        sequence=sequence,
        node_id=node_id,
        node_type="FunctionNode",
        duration_ms=42.0,
        state_update={"result": "done"},
    )


def make_checkpoint(
    run_id: str = "run-1", sequence: int = 3, node_id: str = "node-a"
) -> Checkpoint:
    return Checkpoint.create(
        run_id=run_id,
        node_id=node_id,
        interrupt_type="before",
        state={"x": 42, "step": 1},
        sequence_number=sequence,
        loop_counters={},
        node_execution_order=[],
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def store():
    """In-memory SQLiteEventStore, initialized and auto-closed."""
    s = SQLiteEventStore(":memory:")
    await s.initialize()
    yield s
    await s.close()


# ---------------------------------------------------------------------------
# Test 1: In-memory SQLite works
# ---------------------------------------------------------------------------


async def test_in_memory_initialize():
    """SQLiteEventStore(':memory:') initializes without errors."""
    async with SQLiteEventStore(":memory:") as s:
        assert s._conn is not None


# ---------------------------------------------------------------------------
# Test 2: Auto-creates directory and database on initialize (non-memory path)
# ---------------------------------------------------------------------------


async def test_auto_creates_orchestra_directory(tmp_path):
    """initialize() creates the .orchestra/ directory (or any directory)."""
    db_path = str(tmp_path / "subdir" / "test.db")
    s = SQLiteEventStore(db_path)
    await s.initialize()
    try:
        assert os.path.exists(db_path), f"Database not created at {db_path}"
    finally:
        await s.close()


# ---------------------------------------------------------------------------
# Test 3: append() stores event, get_events() retrieves it
# ---------------------------------------------------------------------------


async def test_append_and_retrieve_single_event(store: SQLiteEventStore):
    """A single appended event can be retrieved via get_events()."""
    event = make_execution_started()
    await store.append(event)

    results = await store.get_events("run-1")
    assert len(results) == 1
    assert results[0].event_id == event.event_id
    assert results[0].run_id == "run-1"


# ---------------------------------------------------------------------------
# Test 4: Multiple events returned in sequence order
# ---------------------------------------------------------------------------


async def test_multiple_events_sequence_order(store: SQLiteEventStore):
    """Multiple events are returned sorted by sequence ascending."""
    e1 = make_execution_started(sequence=0)
    e2 = make_node_started(sequence=1)
    e3 = make_node_completed(sequence=2)

    # Append out of order to verify sorting is by DB sequence column
    await store.append(e3)
    await store.append(e1)
    await store.append(e2)

    results = await store.get_events("run-1")
    assert len(results) == 3
    assert results[0].sequence == 0
    assert results[1].sequence == 1
    assert results[2].sequence == 2


# ---------------------------------------------------------------------------
# Test 5: event_types filter in get_events() works
# ---------------------------------------------------------------------------


async def test_get_events_event_type_filter(store: SQLiteEventStore):
    """get_events() with event_types filter returns only matching events."""
    await store.append(make_execution_started(sequence=0))
    await store.append(make_node_started(sequence=1))
    await store.append(make_node_completed(sequence=2))

    # Only fetch NodeStarted events
    results = await store.get_events("run-1", event_types=[EventType.NODE_STARTED])
    assert len(results) == 1
    assert results[0].event_type == EventType.NODE_STARTED

    # Only fetch ExecutionStarted events
    results2 = await store.get_events("run-1", event_types=[EventType.EXECUTION_STARTED])
    assert len(results2) == 1
    assert results2[0].event_type == EventType.EXECUTION_STARTED


# ---------------------------------------------------------------------------
# Test 6: after_sequence filter works
# ---------------------------------------------------------------------------


async def test_get_events_after_sequence(store: SQLiteEventStore):
    """get_events(after_sequence=N) returns only events with sequence > N."""
    await store.append(make_execution_started(sequence=0))
    await store.append(make_node_started(sequence=1))
    await store.append(make_node_completed(sequence=2))

    results = await store.get_events("run-1", after_sequence=0)
    assert len(results) == 2
    for e in results:
        assert e.sequence > 0


# ---------------------------------------------------------------------------
# Test 7: save_checkpoint() and get_latest_checkpoint() roundtrip
# ---------------------------------------------------------------------------


async def test_checkpoint_roundtrip(store: SQLiteEventStore):
    """save_checkpoint() persists a checkpoint; get_latest_checkpoint() retrieves it."""
    checkpoint = make_checkpoint(sequence=5, node_id="node-b")
    await store.save_checkpoint(checkpoint)

    retrieved = await store.get_latest_checkpoint("run-1")
    assert retrieved is not None
    assert retrieved.checkpoint_id == checkpoint.checkpoint_id
    assert retrieved.node_id == "node-b"
    assert retrieved.state == {"x": 42, "step": 1}


# ---------------------------------------------------------------------------
# Test 8: get_latest_checkpoint() returns None for unknown run
# ---------------------------------------------------------------------------


async def test_get_latest_checkpoint_none_for_unknown_run(store: SQLiteEventStore):
    """get_latest_checkpoint() returns None when no checkpoints exist."""
    result = await store.get_latest_checkpoint("nonexistent-run")
    assert result is None


# ---------------------------------------------------------------------------
# Test 9: list_runs() returns run metadata
# ---------------------------------------------------------------------------


async def test_list_runs_returns_run_metadata(store: SQLiteEventStore):
    """create_run() + list_runs() returns run summary data."""
    await store.create_run("run-1", "my-workflow", "start")
    await store.create_run("run-2", "other-workflow", "begin")

    runs = await store.list_runs()
    run_ids = {r.run_id for r in runs}
    assert "run-1" in run_ids
    assert "run-2" in run_ids

    run1 = next(r for r in runs if r.run_id == "run-1")
    assert run1.workflow_name == "my-workflow"
    assert run1.status == "running"


# ---------------------------------------------------------------------------
# Test 10: update_run_status() changes status
# ---------------------------------------------------------------------------


async def test_update_run_status(store: SQLiteEventStore):
    """update_run_status() correctly updates the run record."""
    await store.create_run("run-1", "wf", "entry")
    await store.update_run_status("run-1", "completed", "2026-03-09T00:00:00Z")

    runs = await store.list_runs()
    run1 = next(r for r in runs if r.run_id == "run-1")
    assert run1.status == "completed"


# ---------------------------------------------------------------------------
# Test 11: list_runs() status filter
# ---------------------------------------------------------------------------


async def test_list_runs_status_filter(store: SQLiteEventStore):
    """list_runs(status=...) filters correctly by status."""
    await store.create_run("run-ok", "wf", "entry")
    await store.create_run("run-fail", "wf", "entry")
    await store.update_run_status("run-fail", "failed")

    completed_runs = await store.list_runs(status="running")
    assert all(r.status == "running" for r in completed_runs)
    ids = {r.run_id for r in completed_runs}
    assert "run-ok" in ids
    assert "run-fail" not in ids


# ---------------------------------------------------------------------------
# Test 12: create_run() then get_events() returns empty list
# ---------------------------------------------------------------------------


async def test_get_events_empty_after_create_run(store: SQLiteEventStore):
    """get_events() for a newly created run returns an empty list."""
    await store.create_run("run-empty", "wf", "start")
    events = await store.get_events("run-empty")
    assert events == []


# ---------------------------------------------------------------------------
# Test 13: WAL mode enabled (file-based DB only -- WAL is N/A for :memory:)
# ---------------------------------------------------------------------------


async def test_wal_mode_enabled(tmp_path):
    """PRAGMA journal_mode returns 'wal' after initialization (file-based DB)."""
    db_path = str(tmp_path / "wal_test.db")
    async with SQLiteEventStore(db_path) as s:
        conn = s._conn
        assert conn is not None
        async with conn.execute("PRAGMA journal_mode") as cursor:
            row = await cursor.fetchone()
    assert row is not None
    assert row[0].lower() == "wal"


# ---------------------------------------------------------------------------
# Test 14: JSON roundtrip via serialization
# ---------------------------------------------------------------------------


async def test_json_roundtrip_serialization(store: SQLiteEventStore):
    """Events are stored as JSON and deserialized back to correct types."""
    original = ExecutionStarted(
        run_id="run-rt",
        sequence=0,
        workflow_name="roundtrip-wf",
        initial_state={"key": "value", "nested": {"a": 1}},
        entry_point="alpha",
    )
    await store.append(original)

    results = await store.get_events("run-rt")
    assert len(results) == 1
    restored = results[0]
    assert isinstance(restored, ExecutionStarted)
    assert restored.workflow_name == "roundtrip-wf"
    assert restored.initial_state == {"key": "value", "nested": {"a": 1}}
    assert restored.entry_point == "alpha"
    assert restored.event_id == original.event_id


# ---------------------------------------------------------------------------
# Test 15: SnapshotManager counts events and triggers at interval
# ---------------------------------------------------------------------------


async def test_snapshot_manager_counts_and_triggers(store: SQLiteEventStore):
    """SnapshotManager increments per-run counters correctly."""
    mgr = SnapshotManager(store, interval=3)

    events = [make_execution_started(run_id="run-sm", sequence=i) for i in range(5)]

    for event in events:
        mgr.on_event(event)

    # After 5 events the counter should be 5
    assert mgr._counters.get("run-sm", 0) == 5


async def test_snapshot_manager_triggers_at_interval():
    """SnapshotManager schedules save_checkpoint when interval is reached."""
    saved: list[CheckpointCreated] = []

    class MockStore:
        async def save_checkpoint(self, checkpoint: CheckpointCreated) -> None:
            saved.append(checkpoint)

    mgr = SnapshotManager(MockStore(), interval=2)  # type: ignore[arg-type]

    # SnapshotManager.on_event receives WorkflowEvent objects; it only snapshots
    # on CheckpointCreated events. Use the event type directly here.
    checkpoint_event = CheckpointCreated(
        run_id="run-trigger",
        sequence=2,
        node_id="node-a",
        state_snapshot={"x": 1},
    )
    # Fire enough events to reach the interval
    for _ in range(1):
        mgr.on_event(checkpoint_event)
    # The 2nd call crosses the interval (count=2, 2 % 2 == 0)
    mgr.on_event(checkpoint_event)

    # Let scheduled futures run
    await asyncio.sleep(0)
    # Give the event loop a couple of cycles
    await asyncio.sleep(0)

    assert len(saved) == 1
    assert saved[0].checkpoint_id == checkpoint_event.checkpoint_id


# ---------------------------------------------------------------------------
# Test 16: async context manager opens and closes connection
# ---------------------------------------------------------------------------


async def test_async_context_manager():
    """SQLiteEventStore can be used as an async context manager."""
    async with SQLiteEventStore(":memory:") as s:
        assert s._conn is not None
    # After __aexit__ the connection should be closed
    assert s._conn is None


# ---------------------------------------------------------------------------
# Test 17: CompiledGraph.run() emits lifecycle events (integration smoke)
# ---------------------------------------------------------------------------


async def test_compiled_graph_emits_lifecycle_events():
    """CompiledGraph.run() emits ExecutionStarted and ExecutionCompleted events
    when an explicit InMemoryEventStore is passed and persist=False."""
    from orchestra.core.context import ExecutionContext
    from orchestra.core.graph import WorkflowGraph
    from orchestra.storage.store import InMemoryEventStore

    mem_store = InMemoryEventStore()

    async def step_a(state: dict) -> dict:
        return {"result": "ok"}

    graph = WorkflowGraph()
    graph.add_node("step_a", step_a)
    graph.set_entry_point("step_a")
    compiled = graph.compile()

    # Use a fixed run_id so we can query the store directly
    fixed_run_id = "lifecycle-test-run"
    ctx = ExecutionContext(run_id=fixed_run_id)

    result = await compiled.run(
        {"input": "test"},
        context=ctx,
        persist=False,
        event_store=mem_store,
    )

    # The graph should have finished
    assert result.get("result") == "ok"

    # Allow any pending asyncio.ensure_future tasks to complete
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    events = await mem_store.get_events(fixed_run_id)
    event_types = [e.event_type for e in events]
    assert EventType.EXECUTION_STARTED in event_types, f"got types: {event_types}"
    assert EventType.EXECUTION_COMPLETED in event_types, f"got types: {event_types}"
