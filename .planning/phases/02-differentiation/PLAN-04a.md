# Task 04a: SQLite Event Store -- Detailed Execution Plan

**Phase:** 02-differentiation
**Task:** 04a (split from original Plan 04, DIFF-02)
**Created:** 2026-03-09
**Status:** Ready for execution
**Wave:** 2a
**Dependencies:** Plan 01 (EventBus, AnyEvent, EventStore protocol -- all delivered)
**Estimated effort:** 3 days
**Autonomous:** Yes

---

## Objective

Implement `SQLiteEventStore` as the zero-config default persistence backend for Orchestra workflows.
Subscribes to the `EventBus` (already wired into `ExecutionContext.event_bus` from Plan 01).
Wire the store into `CompiledGraph.run()` so that every workflow run is persisted automatically.

This plan does NOT touch Rich trace rendering or handoff protocol (those are Plan 04b).

---

## Context: What Plan 01 Already Delivered

Before starting, verify these exist:

```bash
ls src/orchestra/storage/events.py      # AnyEvent discriminated union
ls src/orchestra/storage/store.py       # EventBus, EventStore Protocol, InMemoryEventStore
ls src/orchestra/storage/serialization.py
ls src/orchestra/storage/contracts.py
```

`ExecutionContext` in `src/orchestra/core/context.py` already has:
```python
event_bus: Any = None          # EventBus instance (added by Plan 01)
loop_counters: ...
node_execution_order: ...
```

The `EventStore` Protocol in `store.py` defines the interface to implement.

---

## Task 4a.1: SQLiteEventStore

**File:** `src/orchestra/storage/sqlite.py`

**Action:**

Implement `SQLiteEventStore` conforming to the `EventStore` protocol from `store.py`.

**Schema (auto-created on first use):**

```sql
-- WAL mode for concurrent read/write
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id TEXT PRIMARY KEY,
    workflow_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',  -- running, completed, failed, interrupted
    started_at TEXT NOT NULL,
    completed_at TEXT,
    entry_point TEXT,
    metadata TEXT  -- JSON
);

CREATE TABLE IF NOT EXISTS workflow_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    timestamp_iso TEXT NOT NULL,
    data TEXT NOT NULL,  -- JSON serialized event via serialization.py
    FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_events_run_seq ON workflow_events(run_id, sequence);
CREATE INDEX IF NOT EXISTS idx_events_type ON workflow_events(event_type);

CREATE TABLE IF NOT EXISTS workflow_checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL UNIQUE,
    node_id TEXT NOT NULL,
    sequence_at INTEGER NOT NULL,
    state_snapshot TEXT NOT NULL,  -- JSON
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_run ON workflow_checkpoints(run_id);
```

**Implementation:**

```python
class SQLiteEventStore:
    """SQLite-backed event store. Zero-config default backend.

    Database location: .orchestra/runs.db (auto-created on first use).
    Uses WAL mode for concurrent access from parallel nodes.

    Usage:
        store = SQLiteEventStore()  # Uses .orchestra/runs.db
        store = SQLiteEventStore("path/to/custom.db")
        await store.initialize()  # Creates tables if needed
        # Or use as async context manager:
        async with SQLiteEventStore() as store:
            ...
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or ".orchestra/runs.db"
        self._conn: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Create .orchestra/ dir and tables if needed.""" ...

    async def __aenter__(self) -> "SQLiteEventStore": ...
    async def __aexit__(self, *args: Any) -> None: ...

    async def append(self, event: AnyEvent) -> None:
        """Persist one event. Uses serialization.py for JSON encoding.""" ...

    async def get_events(
        self,
        run_id: str,
        after_sequence: int = 0,
        event_types: list[str] | None = None,
    ) -> list[AnyEvent]: ...

    async def get_latest_checkpoint(self, run_id: str) -> dict[str, Any] | None: ...
    async def save_checkpoint(self, run_id: str, node_id: str, sequence_at: int, state_snapshot: dict[str, Any]) -> None: ...
    async def list_runs(self, limit: int = 50, status: str | None = None) -> list[dict[str, Any]]: ...
    async def create_run(self, run_id: str, workflow_name: str, entry_point: str) -> None: ...
    async def update_run_status(self, run_id: str, status: str, completed_at: str | None = None) -> None: ...
```

Use `aiosqlite` for async SQLite access. Use `serialization.py`'s existing `serialize_event()` / `deserialize_event()` (or equivalent) for JSON encoding.

Add `aiosqlite` to `pyproject.toml` under `[project.optional-dependencies]` `storage` group.

---

## Task 4a.2: SnapshotManager

**File:** `src/orchestra/storage/sqlite.py` (same file, additional class)

**Action:**

```python
class SnapshotManager:
    """Periodically creates state snapshots to speed up restoration.

    Subscribes to EventBus as a sync callback. After every N events (default 50),
    saves a checkpoint via the EventStore.

    Usage:
        snapshot_mgr = SnapshotManager(store, interval=50)
        event_bus.subscribe(snapshot_mgr.on_event)
    """

    def __init__(self, store: SQLiteEventStore, interval: int = 50) -> None: ...

    def on_event(self, event: AnyEvent) -> None:
        """EventBus subscriber callback (sync). Schedules snapshot if interval reached.""" ...
```

---

## Task 4a.3: Wire SQLite into CompiledGraph.run()

**File:** `src/orchestra/core/compiled.py` (modify)

**Action:**

Add `persist` and `event_store` parameters to `CompiledGraph.run()`. When enabled, create an `EventBus`, attach it to context, subscribe the SQLite store, and emit lifecycle events.

Key changes:

```python
async def run(
    self,
    initial_state: dict[str, Any],
    *,
    persist: bool = True,
    event_store: "EventStore | None" = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    import uuid
    from orchestra.storage.store import EventBus
    from orchestra.storage.events import RunStarted, RunCompleted, RunFailed, NodeEntered, NodeCompleted

    run_id = run_id or str(uuid.uuid4())

    # 1. Create EventBus, attach to context
    event_bus = EventBus()
    # context.event_bus was already typed in Plan 01 -- just assign it
    # (context is created inside run() -- set event_bus right after creation)

    # 2. Set up persistence
    if persist and event_store is None:
        from orchestra.storage.sqlite import SQLiteEventStore
        event_store = SQLiteEventStore()
        await event_store.initialize()
        await event_store.create_run(run_id, self._graph.name or "workflow", self._graph.entry_point or "")

    if event_store is not None:
        import asyncio
        event_bus.subscribe(lambda e: asyncio.ensure_future(event_store.append(e)))

    # 3. Emit RunStarted
    await event_bus.emit(RunStarted(run_id=run_id, graph_name=self._graph.name or "workflow", initial_state=initial_state, ...))

    # 4. In the main execution loop, emit NodeEntered before each node and NodeCompleted/NodeFailed after

    # 5. At the end, emit RunCompleted or RunFailed, update store status
```

**Important:**
- `event_bus.emit()` in Plan 01 is async -- use `await event_bus.emit(...)` or check the actual signature
- Backwards compatible: `persist=True` is the default but only activates if aiosqlite is installed; if import fails, warn and continue without persistence
- Do NOT wire Rich trace here -- that is Plan 04b
- Do NOT modify agent.py here -- ToolCalled/LLMCalled events are Plan 04b's responsibility

**Verify:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -c "
import asyncio
from orchestra.storage.sqlite import SQLiteEventStore
async def test():
    store = SQLiteEventStore(':memory:')
    await store.initialize()
    print('SQLiteEventStore OK')
asyncio.run(test())
"
```

---

## Task 4a.4: Tests

**File:** `tests/unit/test_sqlite_store.py`

**Minimum 10 tests:**

1. Auto-creates `.orchestra/` directory and database on initialize
2. In-memory SQLite works (`:memory:`)
3. `append()` stores event, `get_events()` retrieves it
4. Multiple events returned in sequence order
5. `event_types` filter in `get_events()` works
6. `save_checkpoint()` and `get_latest_checkpoint()` roundtrip
7. `list_runs()` returns run metadata
8. `update_run_status()` changes status
9. `SnapshotManager.on_event()` counts and triggers at interval
10. WAL mode enabled (PRAGMA journal_mode returns WAL)
11. JSON roundtrip via serialization (event stored and deserialized correctly)
12. `create_run()` then `get_events()` for that run_id returns empty list

Use `pytest-asyncio` (already in dev deps) and `:memory:` database for all tests.

---

## File Inventory

| Action | File |
|--------|------|
| Create | `src/orchestra/storage/sqlite.py` |
| Modify | `src/orchestra/core/compiled.py` (add persist param, emit lifecycle events) |
| Modify | `pyproject.toml` (add aiosqlite to storage extras) |
| Create | `tests/unit/test_sqlite_store.py` |

**Does NOT touch:**
- `src/orchestra/observability/console.py` (Plan 04b)
- `src/orchestra/core/handoff.py` (Plan 04b)
- `src/orchestra/core/context_distill.py` (Plan 04b)
- `src/orchestra/core/agent.py` (Plan 04b)

---

## Dependency Graph

```
Plan 01 (EventBus, AnyEvent, EventStore protocol)
    |
    v
Task 4a.1 (SQLiteEventStore) --> Task 4a.2 (SnapshotManager)
    |
    v
Task 4a.3 (Wire into CompiledGraph.run())
    |
    v
Task 4a.4 (Tests)
```

---

## Testing Strategy

All tests use `:memory:` -- no file system writes during test suite.
Use `pytest-asyncio` with `asyncio_mode = "auto"` (already in pyproject.toml).
No mocking of aiosqlite -- test the real SQLite behavior in memory.

**Verification command:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -m pytest tests/unit/test_sqlite_store.py -v --tb=short
```

**Regression guard:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -m pytest tests/unit/ -q --tb=no
```

All 156 existing tests must still pass.
