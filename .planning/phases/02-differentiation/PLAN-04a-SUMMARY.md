---
phase: "02-differentiation"
plan: "04a"
subsystem: "storage"
tags: ["sqlite", "event-store", "persistence", "aiosqlite", "workflow-events"]
dependency_graph:
  requires: ["01-core-engine (EventBus, AnyEvent, EventStore protocol, serialization.py)"]
  provides: ["SQLiteEventStore", "SnapshotManager", "CompiledGraph persist= param"]
  affects: ["CompiledGraph.run()", "src/orchestra/storage/sqlite.py"]
tech_stack:
  added: ["aiosqlite>=0.19"]
  patterns:
    - "WAL mode SQLite via PRAGMA journal_mode = WAL"
    - "Pydantic discriminated-union serialization (serialization.py)"
    - "Async context manager (aenter/aexit) for store lifecycle"
    - "Direct async EventBus callback (no fire-and-forget ensure_future)"
key_files:
  created:
    - "src/orchestra/storage/sqlite.py"
    - "tests/unit/test_sqlite_store.py"
  modified:
    - "src/orchestra/core/compiled.py"
    - "pyproject.toml"
decisions:
  - "Used direct async callback for EventBus subscription (not asyncio.ensure_future) to avoid dangling tasks on loop close"
  - "SQLiteEventStore.close() called explicitly in both success and failure paths when store_owner=True"
  - "WAL mode test uses tmp_path file DB (WAL is not applicable to :memory: SQLite)"
  - "EventStore.close() is not in the Protocol -- only SQLiteEventStore has it; called via type:ignore in compiled.py"
metrics:
  duration: "~45 minutes"
  completed_date: "2026-03-09"
  tasks_completed: 4
  files_changed: 4
  tests_added: 18
  tests_total: 174
---

# Phase 02 Plan 04a: SQLite Event Store Summary

SQLite-backed zero-config persistence for Orchestra workflows using aiosqlite with WAL mode, 3-table schema, and full lifecycle event emission in CompiledGraph.run().

## Tasks Completed

| Task   | Name                                     | Commit  | Key Files                                  |
|--------|------------------------------------------|---------|--------------------------------------------|
| 4a.1   | SQLiteEventStore                         | 9e95814 | src/orchestra/storage/sqlite.py (created)  |
| 4a.2   | SnapshotManager                          | 9e95814 | src/orchestra/storage/sqlite.py (same file)|
| 4a.3   | Wire SQLite into CompiledGraph.run()     | c9d91a0 | src/orchestra/core/compiled.py, pyproject.toml |
| 4a.4   | Tests (18 tests)                         | a9d335d | tests/unit/test_sqlite_store.py (created)  |

## What Was Built

### SQLiteEventStore (`src/orchestra/storage/sqlite.py`)

Zero-config SQLite backend conforming to the `EventStore` protocol:

- **3-table schema:** `workflow_runs`, `workflow_events`, `workflow_checkpoints`
- **WAL mode** enabled via `PRAGMA journal_mode = WAL` on every `initialize()`
- **Indexes** on `(run_id, sequence)` and `event_type` for efficient queries
- `append()` — persists any `WorkflowEvent` via Pydantic JSON serialization
- `get_events()` — retrieves events with `after_sequence` and `event_types` filters
- `save_checkpoint()` / `get_latest_checkpoint()` — checkpoint roundtrip
- `list_runs()` — returns `RunSummary` list with optional status filter
- `create_run()` / `update_run_status()` — run lifecycle helpers
- Async context manager (`async with SQLiteEventStore() as store:`)
- Auto-creates `.orchestra/` directory on first use

### SnapshotManager (`src/orchestra/storage/sqlite.py`)

EventBus subscriber that checkpoints state every N events:

- Maintains per-run event counters
- `on_event()` is a sync callback compatible with `EventBus.subscribe()`
- When `CheckpointCreated` event is received at the interval boundary, schedules `save_checkpoint()` via `asyncio.ensure_future`

### CompiledGraph.run() wiring (`src/orchestra/core/compiled.py`)

New parameters added to `CompiledGraph.run()`:

| Parameter      | Type                   | Default | Description                                  |
|----------------|------------------------|---------|----------------------------------------------|
| `persist`      | `bool`                 | `True`  | Enable auto SQLite persistence               |
| `event_store`  | `EventStore \| None`   | `None`  | Explicit store (overrides persist=True)      |
| `run_id`       | `str \| None`          | `None`  | Override auto-generated UUID                 |

Lifecycle events emitted per run:

- `ExecutionStarted` — at run start with `initial_state` and `entry_point`
- `NodeStarted` — before each node executes
- `NodeCompleted` — after each node with `duration_ms` and `state_update`
- `ErrorOccurred` + `ExecutionCompleted(status="failed")` — on any exception
- `ExecutionCompleted(status="completed")` — on successful finish

### pyproject.toml

Added `storage` optional-dependency group:
```toml
storage = ["aiosqlite>=0.19"]
```

Install with: `pip install orchestra-agents[storage]`

## Tests

18 tests in `tests/unit/test_sqlite_store.py`, all passing:

1. `test_in_memory_initialize` — in-memory SQLite works
2. `test_auto_creates_orchestra_directory` — directory auto-creation
3. `test_append_and_retrieve_single_event` — basic append/get roundtrip
4. `test_multiple_events_sequence_order` — sequence ordering
5. `test_get_events_event_type_filter` — event_type filter
6. `test_get_events_after_sequence` — after_sequence filter
7. `test_checkpoint_roundtrip` — save/get_latest checkpoint
8. `test_get_latest_checkpoint_none_for_unknown_run` — None for missing run
9. `test_list_runs_returns_run_metadata` — list_runs metadata
10. `test_update_run_status` — status update
11. `test_list_runs_status_filter` — status filter
12. `test_get_events_empty_after_create_run` — empty list on new run
13. `test_wal_mode_enabled` — WAL pragma (file-based DB)
14. `test_json_roundtrip_serialization` — Pydantic JSON roundtrip
15. `test_snapshot_manager_counts_and_triggers` — counter tracking
16. `test_snapshot_manager_triggers_at_interval` — interval trigger
17. `test_async_context_manager` — aenter/aexit lifecycle
18. `test_compiled_graph_emits_lifecycle_events` — integration smoke test

**Regression:** All 156 existing tests still pass. Total: 174 tests.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] WAL mode not applicable to :memory: SQLite**
- **Found during:** Task 4a.4 (test_wal_mode_enabled)
- **Issue:** SQLite in-memory databases do not support WAL mode; PRAGMA returns 'memory' not 'wal'
- **Fix:** Changed test to use `tmp_path` file-based DB for WAL verification
- **Files modified:** `tests/unit/test_sqlite_store.py`
- **Commit:** a9d335d

**2. [Rule 1 - Bug] Dangling aiosqlite thread on MaxIterationsError**
- **Found during:** Task 4a.3 (regression test run)
- **Issue:** `asyncio.ensure_future` for store.append() left pending futures that tried to run on a closed event loop after test teardown, producing `PytestUnhandledThreadExceptionWarning`
- **Fix:** Replaced fire-and-forget `ensure_future` with a direct `async def _store_callback` that EventBus.emit() awaits inline; also added explicit `store.close()` in both success and error paths when `_store_owner=True`
- **Files modified:** `src/orchestra/core/compiled.py`
- **Commit:** c9d91a0

**3. [Rule 1 - Bug] WorkflowGraph.node decorator does not exist**
- **Found during:** Task 4a.4 (test_compiled_graph_emits_lifecycle_events)
- **Issue:** Integration test used `@graph.node` decorator pattern that does not exist; API is `add_node()` + `set_entry_point()`
- **Fix:** Rewrote test to use correct API and fixed run_id tracking via `ExecutionContext`
- **Files modified:** `tests/unit/test_sqlite_store.py`
- **Commit:** a9d335d

## Self-Check: PASSED

Files created/modified:
- FOUND: src/orchestra/storage/sqlite.py
- FOUND: tests/unit/test_sqlite_store.py
- FOUND: src/orchestra/core/compiled.py
- FOUND: pyproject.toml

Commits:
- FOUND: 9e95814 (feat: SQLiteEventStore and SnapshotManager)
- FOUND: c9d91a0 (feat: wire SQLite into CompiledGraph.run())
- FOUND: a9d335d (test: 18 unit tests)

Test results: 174 passed, 0 failed.
