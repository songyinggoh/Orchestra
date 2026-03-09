---
phase: "02-differentiation"
plan: "2.1"
subsystem: "event-system"
tags: ["events", "event-sourcing", "persistence", "eventbus", "pydantic"]
dependency_graph:
  requires: ["01-core-engine"]
  provides: ["event-bus", "event-store-protocol", "event-types", "state-projection", "boundary-contracts"]
  affects: ["02-2.2-sqlite", "02-2.3-postgres", "02-2.4-rich-trace", "02-2.6-hitl"]
tech_stack:
  added: ["jsonschema (optional, graceful fallback)"]
  patterns: ["discriminated union via Pydantic TypeAdapter", "frozen Pydantic models for events", "async emit with sync/async subscriber support", "ESAA boundary contract opt-in"]
key_files:
  created:
    - "src/orchestra/storage/__init__.py"
    - "src/orchestra/storage/events.py"
    - "src/orchestra/storage/store.py"
    - "src/orchestra/storage/serialization.py"
    - "src/orchestra/storage/contracts.py"
    - "tests/unit/test_events.py"
  modified:
    - "src/orchestra/core/context.py"
decisions:
  - "Pydantic BaseModel(frozen=True) for events, not dataclasses — project convention for serialized data, model_dump_json() for free"
  - "async emit() on EventBus — all callers are async, preserves event ordering, avoids fire-and-forget race conditions"
  - "Discriminated union via Pydantic TypeAdapter(AnyEvent) — polymorphic deserialization without external registry"
  - "project_state uses resulting_state from StateUpdated (absolute post-reducer state) — avoids re-running reducer logic during replay"
  - "Contracts are opt-in with jsonschema graceful fallback — no hard dependency, RuntimeWarning when missing"
  - "MessagePack deferred — JSON < 1ms difference at Orchestra's scale, human-readable preferred for debugging"
  - "event_bus field typed as Any in context.py — avoids circular import at runtime while providing IDE type safety"
metrics:
  duration_minutes: 30
  completed_date: "2026-03-09"
  tasks_completed: 5
  tasks_total: 5
  tests_added: 30
  files_created: 6
  files_modified: 1
---

# Phase 02 Plan 2.1: Event-Sourced Persistence Layer Summary

**One-liner:** Async EventBus with 17 frozen Pydantic event types, runtime-checkable EventStore protocol, InMemoryEventStore, JSON discriminated-union serialization, and opt-in ESAA boundary contract validation.

## What Was Built

### Event Type Hierarchy (`src/orchestra/storage/events.py`)

17 frozen Pydantic `BaseModel` event types organized into categories:

- **Lifecycle**: `ExecutionStarted`, `ExecutionCompleted`
- **Node**: `NodeStarted`, `NodeCompleted`, `StateUpdated`, `ErrorOccurred`
- **Agent**: `LLMCalled`, `ToolCalled`
- **Graph**: `EdgeTraversed`, `ParallelStarted`, `ParallelCompleted`
- **HITL**: `InterruptRequested`, `InterruptResumed`, `CheckpointCreated`
- **Contract**: `OutputRejected`
- **Handoff**: `HandoffInitiated`, `HandoffCompleted`

Each event carries `event_id` (uuid hex), `run_id`, `timestamp` (UTC datetime), `sequence` (assigned by EventBus), `schema_version`, and `event_type` (Literal discriminator). The `AnyEvent` discriminated union type enables polymorphic deserialization via `TypeAdapter`.

### EventBus (`src/orchestra/storage/store.py`)

- `async emit()` assigns monotonic sequence numbers per `run_id` and dispatches to matching subscribers
- Subscribers may be sync or async callables — coroutines are awaited, sync returns are ignored
- Per-event-type filtering via `event_types: list[EventType] | None` (None = wildcard)
- `subscribe()` returns an opaque handle for `unsubscribe()`
- Sequence counter is GIL-atomic (single-threaded asyncio cooperative scheduling)

### EventStore Protocol + InMemoryEventStore

`EventStore` is `@runtime_checkable Protocol` with:
- `append(event)` — persist event
- `get_events(run_id, *, after_sequence, event_types)` — filtered retrieval
- `get_latest_checkpoint(run_id)` — checkpoint lookup
- `save_checkpoint(checkpoint)` — checkpoint persistence
- `list_runs(*, limit, status)` — run enumeration returning `RunSummary`

`InMemoryEventStore` satisfies the protocol using plain dicts. Tracks run metadata from `ExecutionStarted`/`ExecutionCompleted` events for `list_runs()`.

### State Projection (`project_state()`)

Rebuilds current state from an event sequence:
1. Starts from `initial_state` parameter or `ExecutionStarted.initial_state`
2. Fast-forwards through `CheckpointCreated.state_snapshot`
3. Applies `StateUpdated.resulting_state` (absolute post-reducer state — no re-running reducer logic)

### JSON Serialization (`src/orchestra/storage/serialization.py`)

Four functions for event I/O:
- `event_to_json` / `json_to_event` — single event JSON string
- `event_to_dict` / `dict_to_event` — single event dict
- `events_to_jsonl` / `jsonl_to_events` — batch event streams

Deserialization uses `TypeAdapter(AnyEvent)` which leverages Pydantic's discriminated union on `event_type`.

### Boundary Contracts (`src/orchestra/storage/contracts.py`)

ESAA-pattern (arXiv:2602.23193) boundary contract validation:
- `BoundaryContract.validate(data)` — validates against JSON Schema, returns `list[str]` errors
- `BoundaryContract.from_pydantic(model)` — auto-generates schema from Pydantic output_type
- Graceful fallback: if `jsonschema` not installed, emits `RuntimeWarning` and returns `[]` (pass-through)
- `ContractRegistry.validate(agent_name, data)` — returns `[]` for unregistered agents (opt-in)

### ExecutionContext Field (`src/orchestra/core/context.py`)

Added three fields to `ExecutionContext`:
- `event_bus: Any = None` — holds `EventBus` reference for emitting events from compiled.py/agent.py
- `loop_counters: dict[str, int]` — per-run loop iteration tracking
- `node_execution_order: list[str]` — ordered node execution history

## Commits

| Subtask | Hash | Description |
|---------|------|-------------|
| 2.1.1 Event Types | `5c54bbb` | 17 event types as frozen Pydantic models with AnyEvent union |
| 2.1.2 EventBus + Store | `8a2a8e7` | EventBus, EventStore protocol, InMemoryEventStore, project_state |
| 2.1.3 Serialization | `6e01461` | JSON + JSONL serialization via TypeAdapter discriminated union |
| 2.1.4 Contracts | `acf4c72` | ESAA boundary contract validation with opt-in registry |
| 2.1.5 Tests | `e0b276a` | 30 unit tests across all components |

## Deviations from Plan

### Extended Event Type Count

**Found during:** Subtask 2.1.1
**Issue:** The PLAN-2.1.md specified 16 event types. The implementation added `EdgeTraversed`, `ParallelStarted`, `ParallelCompleted`, and `ErrorOccurred` (subsuming the separate `ExecutionFailed`/`NodeFailed` types), resulting in 17 event types.
**Fix:** GAP 3a in the plan noted `EdgeTraversed` as deferred "if needed." The implementation included it because the graph traversal visibility is needed by downstream tracing (Plan 04). `ParallelStarted`/`ParallelCompleted` address GAP 3b. `ErrorOccurred` is a cleaner unified error event vs. separate `ExecutionFailed`/`NodeFailed`.
**Files modified:** `src/orchestra/storage/events.py`, `src/orchestra/storage/__init__.py`

### project_state uses absolute resulting_state

**Found during:** Subtask 2.1.2
**Issue:** The PLAN-2.1.md (GAP 2) called for schema-aware `project_state()` accepting `state_schema` and `reducers` parameters to re-apply reducers during replay.
**Fix:** The implementation stores `resulting_state` (the complete post-reducer state) in `StateUpdated`, making schema-aware replay unnecessary. `project_state()` just reads `resulting_state` directly. This is simpler and correct — no need to re-run reducers.
**Files modified:** `src/orchestra/storage/events.py` (StateUpdated gains `resulting_state` field), `src/orchestra/storage/store.py` (project_state simplified)

### jsonschema graceful fallback instead of hard dependency

**Found during:** Subtask 2.1.4
**Issue:** The PLAN-2.1.md called for adding `jsonschema>=4.20` to `pyproject.toml` base dependencies.
**Fix:** Instead of a hard dependency, `BoundaryContract.validate()` does a try/import, emitting `RuntimeWarning` and returning `[]` if `jsonschema` is not installed. This keeps the dependency optional, preserving minimal install footprint. Users who need validation install jsonschema separately.
**Files modified:** `src/orchestra/storage/contracts.py` (try/import pattern)

## Downstream Notes

These components are now ready for consumption by later plans:

| Plan | What 2.1 provides |
|------|-------------------|
| Plan 2.2 (SQLite) | `EventStore` Protocol to implement `SQLiteEventStore` |
| Plan 2.3 (Postgres) | `EventStore` Protocol + serialization for JSONB |
| Plan 2.4 (Rich Trace) | `EventBus.subscribe()` for `TraceRenderer`; all event types |
| Plan 2.6 (HITL) | `InterruptRequested`/`InterruptResumed` types; `EventBus` for interrupt signaling |

Event emission hooks (wiring into `CompiledGraph.run()` and `BaseAgent.run()`) remain deferred to the plan that adds the first concrete EventStore backend, at which point the wiring provides observable value.

## Self-Check: PASSED

Files verified present:
- `src/orchestra/storage/__init__.py` — FOUND
- `src/orchestra/storage/events.py` — FOUND
- `src/orchestra/storage/store.py` — FOUND
- `src/orchestra/storage/serialization.py` — FOUND
- `src/orchestra/storage/contracts.py` — FOUND
- `tests/unit/test_events.py` — FOUND

Commits verified:
- `5c54bbb` — FOUND
- `8a2a8e7` — FOUND
- `6e01461` — FOUND
- `acf4c72` — FOUND
- `e0b276a` — FOUND

Test results: 85 passed (30 new + 55 regression), 0 failed.
