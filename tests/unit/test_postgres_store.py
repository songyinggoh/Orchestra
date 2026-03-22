"""Unit tests for PostgresEventStore using mocked asyncpg.

All tests mock asyncpg at the connection/pool level — no real PostgreSQL
instance is required. Tests verify:
- Protocol conformance (all 5 EventStore methods)
- Advisory lock usage on append
- LISTEN/NOTIFY notification on append
- JSONB round-trip (dict passthrough from asyncpg rows)
- Connection pool lifecycle (initialize / close)
- Error handling (no-pool guard, missing DSN guard)
- subscribe_events wiring

Uses pytest-asyncio with asyncio_mode = 'auto' (configured in pyproject.toml).
"""

from __future__ import annotations

import json
import sys
import types
import uuid
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Bootstrap asyncpg mock BEFORE importing postgres module
# ---------------------------------------------------------------------------


def _make_asyncpg_mock() -> types.ModuleType:
    """Build a minimal asyncpg stub sufficient for PostgresEventStore tests."""
    mod = types.ModuleType("asyncpg")
    pool_mod = types.ModuleType("asyncpg.pool")

    class FakePool:
        """Minimal asyncpg Pool stub."""

        def __init__(self) -> None:
            self._conn = FakeConnection()
            self._closed = False

        def acquire(self) -> FakeAcquireContext:
            return FakeAcquireContext(self._conn)

        async def release(self, conn: Any) -> None:
            pass

        async def fetch(self, query: str, *args: Any) -> list[Any]:
            return self._conn._fetch_results

        async def fetchrow(self, query: str, *args: Any) -> Any:
            return self._conn._fetchrow_result

        async def execute(self, query: str, *args: Any) -> None:
            self._conn._executed.append((query, args))

        async def close(self) -> None:
            self._closed = True

    class FakeAcquireContext:
        """Async context manager returned by pool.acquire()."""

        def __init__(self, conn: FakeConnection) -> None:
            self._conn = conn

        async def __aenter__(self) -> FakeConnection:
            return self._conn

        async def __aexit__(self, *args: Any) -> None:
            pass

        # Allow direct await (pool.acquire() used in subscribe_events)
        def __await__(self):  # type: ignore[override]
            async def _inner() -> FakeConnection:
                return self._conn

            return _inner().__await__()

    class FakeTransactionContext:
        async def __aenter__(self) -> FakeTransactionContext:
            return self

        async def __aexit__(self, *args: Any) -> None:
            pass

    class FakeConnection:
        """Minimal asyncpg Connection stub."""

        def __init__(self) -> None:
            self._executed: list[tuple[str, Any]] = []
            self._fetch_results: list[Any] = []
            self._fetchrow_result: Any = None
            self._listeners: dict[str, Any] = {}

        def transaction(self) -> FakeTransactionContext:
            return FakeTransactionContext()

        async def execute(self, query: str, *args: Any) -> None:
            self._executed.append((query, args))

        async def fetch(self, query: str, *args: Any) -> list[Any]:
            return self._fetch_results

        async def fetchrow(self, query: str, *args: Any) -> Any:
            return self._fetchrow_result

        async def add_listener(self, channel: str, callback: Any) -> None:
            self._listeners[channel] = callback

        async def remove_listener(self, channel: str, callback: Any) -> None:
            self._listeners.pop(channel, None)

    async def create_pool(dsn: str, *, min_size: int = 4, max_size: int = 20) -> FakePool:
        pool = FakePool()
        return pool

    mod.create_pool = create_pool  # type: ignore[attr-defined]
    mod.pool = pool_mod  # type: ignore[attr-defined]
    pool_mod.Pool = FakePool  # type: ignore[attr-defined]

    # Expose the classes so tests can reference them
    mod._FakePool = FakePool  # type: ignore[attr-defined]
    mod._FakeConnection = FakeConnection  # type: ignore[attr-defined]

    return mod


# Install mock before any import of the postgres module
_asyncpg_mock = _make_asyncpg_mock()
sys.modules["asyncpg"] = _asyncpg_mock
sys.modules["asyncpg.pool"] = _asyncpg_mock.pool  # type: ignore[attr-defined]

# Now import the module under test
from datetime import UTC  # noqa: E402

from orchestra.storage.checkpoint import Checkpoint  # noqa: E402
from orchestra.storage.events import (  # noqa: E402
    EventType,
    ExecutionStarted,
    NodeCompleted,
    NodeStarted,
)
from orchestra.storage.postgres import PostgresEventStore  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RUN_ID = "00000000-0000-0000-0000-000000000001"
_DSN = "postgresql://user:pass@localhost/orchestra_test"


def _make_started(run_id: str = _RUN_ID, sequence: int = 0) -> ExecutionStarted:
    return ExecutionStarted(
        run_id=run_id,
        sequence=sequence,
        workflow_name="test-wf",
        initial_state={"x": 1},
        entry_point="start",
    )


def _make_node_started(run_id: str = _RUN_ID, sequence: int = 1) -> NodeStarted:
    return NodeStarted(run_id=run_id, sequence=sequence, node_id="node-a")


def _make_node_completed(run_id: str = _RUN_ID, sequence: int = 2) -> NodeCompleted:
    return NodeCompleted(run_id=run_id, sequence=sequence, node_id="node-a", duration_ms=10.0)


def _make_checkpoint(run_id: str = _RUN_ID, sequence: int = 3) -> Checkpoint:
    return Checkpoint.create(
        run_id=run_id,
        node_id="node-a",
        interrupt_type="before",
        state={"x": 42},
        sequence_number=sequence,
        loop_counters={},
        node_execution_order=[],
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def store() -> PostgresEventStore:
    """Initialized PostgresEventStore backed by the asyncpg mock."""
    s = PostgresEventStore(_DSN)
    await s.initialize()
    return s


# ---------------------------------------------------------------------------
# Test 1: Constructor DSN fallback to env var
# ---------------------------------------------------------------------------


def test_dsn_from_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """PostgresEventStore falls back to DATABASE_URL when no dsn passed."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://env-host/db")
    s = PostgresEventStore()
    assert s._dsn == "postgresql://env-host/db"


# ---------------------------------------------------------------------------
# Test 2: Constructor raises when no DSN available
# ---------------------------------------------------------------------------


def test_missing_dsn_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """ValueError raised when neither dsn nor DATABASE_URL is set."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="DSN"):
        PostgresEventStore()


# ---------------------------------------------------------------------------
# Test 3: initialize() creates a pool
# ---------------------------------------------------------------------------


async def test_initialize_creates_pool() -> None:
    """initialize() calls asyncpg.create_pool and sets _pool."""
    s = PostgresEventStore(_DSN)
    assert s._pool is None
    await s.initialize()
    assert s._pool is not None


# ---------------------------------------------------------------------------
# Test 4: close() releases pool and sets _pool to None
# ---------------------------------------------------------------------------


async def test_close_releases_pool() -> None:
    """close() closes the pool and sets _pool = None."""
    s = PostgresEventStore(_DSN)
    await s.initialize()
    pool = s._pool
    await s.close()
    assert s._pool is None
    assert pool._closed is True  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Test 5: append() executes INSERT + NOTIFY
# ---------------------------------------------------------------------------


async def test_append_executes_insert_and_notify(store: PostgresEventStore) -> None:
    """append() runs an INSERT for the event and SELECT pg_notify."""
    event = _make_started()
    await store.append(event)

    conn = store._pool._conn  # type: ignore[union-attr]
    queries = [q for q, _ in conn._executed]

    # Should have: advisory lock, ensure_run INSERT, event INSERT, NOTIFY
    assert any("pg_advisory_xact_lock" in q for q in queries), "advisory lock not acquired"
    assert any("INSERT INTO workflow_events" in q for q in queries), "event INSERT not found"
    assert any("pg_notify" in q for q in queries), "NOTIFY not sent"


# ---------------------------------------------------------------------------
# Test 6: append() auto-creates run row (ON CONFLICT DO NOTHING)
# ---------------------------------------------------------------------------


async def test_append_auto_creates_run(store: PostgresEventStore) -> None:
    """append() inserts into workflow_runs if run does not exist."""
    event = _make_started()
    await store.append(event)

    conn = store._pool._conn  # type: ignore[union-attr]
    queries = [q for q, _ in conn._executed]
    assert any("INSERT INTO workflow_runs" in q for q in queries), (
        "run auto-create INSERT not found"
    )


# ---------------------------------------------------------------------------
# Test 7: get_events() returns deserialized events
# ---------------------------------------------------------------------------


async def test_get_events_deserializes_rows(store: PostgresEventStore) -> None:
    """get_events() converts raw JSONB dicts to WorkflowEvent objects."""
    event = _make_started()
    from orchestra.storage.serialization import event_to_dict

    raw_dict = event_to_dict(event)
    # asyncpg returns JSONB as a dict; simulate via a fake row
    fake_row = {"data": raw_dict}
    store._pool._conn._fetch_results = [fake_row]  # type: ignore[union-attr]

    result = await store.get_events(_RUN_ID)
    assert len(result) == 1
    assert result[0].run_id == _RUN_ID
    assert isinstance(result[0], ExecutionStarted)


# ---------------------------------------------------------------------------
# Test 8: get_events() with event_types filter uses IN clause
# ---------------------------------------------------------------------------


async def test_get_events_with_type_filter(store: PostgresEventStore) -> None:
    """get_events(event_types=...) builds a query with an IN clause."""
    store._pool._conn._fetch_results = []  # type: ignore[union-attr]

    # Patch pool.fetch to capture the query
    captured: list[str] = []

    original_fetch = store._pool.fetch  # type: ignore[union-attr]

    async def capturing_fetch(query: str, *args: Any) -> list[Any]:
        captured.append(query)
        return []

    store._pool.fetch = capturing_fetch  # type: ignore[union-attr]

    await store.get_events(_RUN_ID, event_types=[EventType.EXECUTION_STARTED])
    assert any("IN" in q for q in captured), "event_type IN clause not found"

    store._pool.fetch = original_fetch  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Test 9: get_latest_checkpoint() returns CheckpointCreated or None
# ---------------------------------------------------------------------------


async def test_get_latest_checkpoint_returns_none_when_empty(
    store: PostgresEventStore,
) -> None:
    """get_latest_checkpoint() returns None when no checkpoints exist."""
    store._pool._conn._fetchrow_result = None  # type: ignore[union-attr]
    result = await store.get_latest_checkpoint(_RUN_ID)
    assert result is None


async def test_get_latest_checkpoint_returns_checkpoint(
    store: PostgresEventStore,
) -> None:
    """get_latest_checkpoint() deserializes checkpoint row to CheckpointCreated."""
    checkpoint_id = uuid.uuid4().hex

    class FakeRow(dict):
        pass

    from datetime import datetime

    fake_row = FakeRow(
        checkpoint_id=checkpoint_id,
        node_id="node-a",
        sequence_at=5,
        state_snapshot=json.dumps({"x": 99}),
        interrupt_type="before",
        execution_context=json.dumps({"loop_counters": {}, "node_execution_order": []}),
        created_at=datetime.now(UTC).isoformat(),
    )
    store._pool._conn._fetchrow_result = fake_row  # type: ignore[union-attr]

    result = await store.get_latest_checkpoint(_RUN_ID)
    assert result is not None
    assert result.checkpoint_id == checkpoint_id
    assert result.node_id == "node-a"
    assert result.sequence_number == 5
    assert result.state == {"x": 99}


# ---------------------------------------------------------------------------
# Test 10: save_checkpoint() executes INSERT ON CONFLICT UPDATE
# ---------------------------------------------------------------------------


async def test_save_checkpoint_executes_upsert(store: PostgresEventStore) -> None:
    """save_checkpoint() runs an INSERT...ON CONFLICT upsert."""
    cp = _make_checkpoint()
    await store.save_checkpoint(cp)

    pool = store._pool  # type: ignore[union-attr]
    # pool.execute is the direct pool-level call for save_checkpoint
    # We need to check what was passed
    _conn = pool._conn
    # save_checkpoint uses pool.execute directly, not conn
    # Verify by inspecting the pool's execute was triggered (patching)
    executed: list[tuple[str, Any]] = []
    original_execute = pool.execute

    async def capturing_execute(query: str, *args: Any) -> None:
        executed.append((query, args))

    pool.execute = capturing_execute  # type: ignore[union-attr]

    await store.save_checkpoint(cp)

    assert any("INSERT INTO workflow_checkpoints" in q for q, _ in executed), (
        "checkpoint INSERT not found"
    )
    assert any("ON CONFLICT" in q for q, _ in executed), "ON CONFLICT upsert not found"

    pool.execute = original_execute  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Test 11: list_runs() with no status filter
# ---------------------------------------------------------------------------


async def test_list_runs_no_filter(store: PostgresEventStore) -> None:
    """list_runs() returns RunSummary objects from pool.fetch results."""
    from datetime import datetime

    now = datetime.now(UTC)

    class FakeRow(dict):
        pass

    fake_rows = [
        FakeRow(
            run_id=_RUN_ID,
            workflow_name="wf",
            status="running",
            started_at=now,
            completed_at=None,
            event_count=3,
        )
    ]
    store._pool._conn._fetch_results = fake_rows  # type: ignore[union-attr]

    original_fetch = store._pool.fetch  # type: ignore[union-attr]

    async def patched_fetch(query: str, *args: Any) -> list[Any]:
        return fake_rows

    store._pool.fetch = patched_fetch  # type: ignore[union-attr]

    results = await store.list_runs()
    assert len(results) == 1
    assert results[0].run_id == _RUN_ID
    assert results[0].status == "running"
    assert results[0].event_count == 3

    store._pool.fetch = original_fetch  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Test 12: list_runs() with status filter adds WHERE clause
# ---------------------------------------------------------------------------


async def test_list_runs_with_status_filter(store: PostgresEventStore) -> None:
    """list_runs(status='completed') passes status arg to pool.fetch."""
    captured_args: list[tuple[Any, ...]] = []

    async def capturing_fetch(query: str, *args: Any) -> list[Any]:
        captured_args.append((query, *args))
        return []

    store._pool.fetch = capturing_fetch  # type: ignore[union-attr]

    await store.list_runs(status="completed")
    assert len(captured_args) == 1
    query, *args = captured_args[0]
    assert "WHERE" in query
    assert "completed" in args


# ---------------------------------------------------------------------------
# Test 13: _require_pool() raises RuntimeError before initialize()
# ---------------------------------------------------------------------------


def test_require_pool_raises_before_init() -> None:
    """Calling any method before initialize() raises RuntimeError."""
    s = PostgresEventStore(_DSN)
    with pytest.raises(RuntimeError, match="not initialized"):
        s._require_pool()


# ---------------------------------------------------------------------------
# Test 14: Protocol structural conformance check
# ---------------------------------------------------------------------------


def test_protocol_conformance() -> None:
    """PostgresEventStore has all methods required by EventStore protocol."""
    for method in ("append", "get_events", "get_latest_checkpoint", "save_checkpoint", "list_runs"):
        assert hasattr(PostgresEventStore, method), f"Missing method: {method}"


# ---------------------------------------------------------------------------
# Test 15: Context manager lifecycle
# ---------------------------------------------------------------------------


async def test_context_manager_lifecycle() -> None:
    """async with PostgresEventStore creates and closes pool automatically."""
    async with PostgresEventStore(_DSN) as s:
        assert s._pool is not None
        pool = s._pool
    assert s._pool is None
    assert pool._closed is True
