# Research: Event-Sourced Persistence Layer

**Research Date:** 2026-03-07
**Phase:** 2 - Differentiation
**Confidence:** HIGH

---

## 1. Event Sourcing Library Decision

**Recommendation: Do NOT use the `eventsourcing` library (v9.5.3).**

The `eventsourcing` package is a full DDD (Domain-Driven Design) framework with aggregates, applications, and its own persistence layer. It would force Orchestra to adopt the library's aggregate lifecycle model, which conflicts with the existing graph execution engine architecture.

**Instead: Roll your own event types as frozen Pydantic models.** Orchestra already uses Pydantic for all data models and frozen dataclasses for graph structures. Event types should follow the same pattern:

```python
class WorkflowEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    event_id: str           # UUID
    run_id: str             # Which workflow run
    sequence_number: int    # Monotonic within a run
    timestamp: datetime     # UTC ISO 8601
    event_type: str         # Discriminator

class NodeStarted(WorkflowEvent):
    event_type: Literal["node_started"] = "node_started"
    node_id: str
    node_type: str          # "agent" | "function" | "subgraph"

class NodeCompleted(WorkflowEvent):
    event_type: Literal["node_completed"] = "node_completed"
    node_id: str
    duration_ms: float
    state_update: dict[str, Any]

class LLMCalled(WorkflowEvent):
    event_type: Literal["llm_called"] = "llm_called"
    node_id: str
    model: str
    input_tokens: int
    output_tokens: int
    duration_ms: float
    cost_usd: float

class ToolCalled(WorkflowEvent):
    event_type: Literal["tool_called"] = "tool_called"
    node_id: str
    tool_name: str
    arguments: dict[str, Any]
    result: str | None
    error: str | None
    duration_ms: float

class StateUpdated(WorkflowEvent):
    event_type: Literal["state_updated"] = "state_updated"
    node_id: str
    changes: dict[str, Any]   # Partial state update applied

class ErrorOccurred(WorkflowEvent):
    event_type: Literal["error_occurred"] = "error_occurred"
    node_id: str | None
    error_type: str
    error_message: str
    traceback: str | None
```

Use Pydantic discriminated unions for deserialization:
```python
Event = Annotated[
    NodeStarted | NodeCompleted | LLMCalled | ToolCalled | StateUpdated | ErrorOccurred,
    Field(discriminator="event_type")
]
```

---

## 2. SQLite Backend (aiosqlite)

### Version
- **aiosqlite v0.22.1** (latest stable, Python 3.11+ compatible)

### Critical: Single-Writer Constraint

SQLite has a fundamental single-writer constraint. WAL mode allows concurrent reads with a single writer but does **NOT** allow concurrent writes. Multiple connections from parallel asyncio tasks will cause `SQLITE_BUSY` errors.

**Solution: Use a single shared aiosqlite connection.** aiosqlite's internal request queue naturally serializes operations through one shared thread. All event writes from parallel agent nodes go through this single connection.

```python
# Single connection, shared across all tasks
self._conn = await aiosqlite.connect(
    db_path,
    timeout=30.0,
)
await self._conn.execute("PRAGMA journal_mode=WAL")
await self._conn.execute("PRAGMA synchronous=NORMAL")
await self._conn.execute("PRAGMA busy_timeout=5000")
```

### Schema Design

```sql
-- Run metadata
CREATE TABLE workflow_runs (
    run_id TEXT PRIMARY KEY,
    workflow_name TEXT,
    status TEXT DEFAULT 'running',  -- running | completed | failed | interrupted
    created_at TEXT NOT NULL,       -- ISO 8601
    completed_at TEXT,
    initial_state TEXT,             -- JSON
    final_state TEXT,               -- JSON
    metadata TEXT                   -- JSON (arbitrary user metadata)
);

-- Append-only event log
CREATE TABLE workflow_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    sequence_number INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,         -- ISO 8601
    payload TEXT NOT NULL,           -- JSON (full Pydantic model_dump_json)
    UNIQUE(run_id, sequence_number),
    FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id)
);
CREATE INDEX idx_events_run_id ON workflow_events(run_id);
CREATE INDEX idx_events_run_seq ON workflow_events(run_id, sequence_number);

-- Periodic state snapshots for fast restoration
CREATE TABLE workflow_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    sequence_number INTEGER NOT NULL,  -- Event seq# this snapshot was taken at
    state TEXT NOT NULL,               -- JSON (full state dict)
    timestamp TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id)
);
CREATE INDEX idx_snapshots_run_id ON workflow_snapshots(run_id, sequence_number DESC);
```

### PRAGMA Optimizations
- `journal_mode=WAL` — allows concurrent reads during writes
- `synchronous=NORMAL` — good durability without fsync on every commit (acceptable for dev tooling)
- `busy_timeout=5000` — wait up to 5s if database is locked (shouldn't happen with single writer)
- `cache_size=-64000` — 64MB page cache

---

## 3. PostgreSQL Backend (asyncpg)

### Version
- **asyncpg v0.31.0** (latest stable)

### Connection Pooling

```python
self._pool = await asyncpg.create_pool(
    dsn=connection_string,
    min_size=2,
    max_size=10,
    command_timeout=30,
)
```

### Advisory Locks for Workflow-Level Concurrency

Use **transaction-scoped** advisory locks (`pg_advisory_xact_lock`), not session-scoped. With connection pools, session-scoped locks can leak if a connection is returned to the pool before the lock is released.

```python
async with self._pool.acquire() as conn:
    async with conn.transaction():
        # Lock on hashed run_id -- only one writer per run
        lock_id = int(hashlib.sha256(run_id.encode()).hexdigest()[:15], 16)
        await conn.execute("SELECT pg_advisory_xact_lock($1)", lock_id)

        # Write events within the transaction
        await conn.executemany(
            "INSERT INTO workflow_events ...",
            event_rows
        )
        # Lock auto-releases when transaction commits
```

Different runs can write concurrently; same run is serialized.

### LISTEN/NOTIFY for Real-Time Event Streaming

PostgreSQL's NOTIFY has an **8KB payload limit**. Send lightweight signals, not full event JSON:

```python
# Publisher (after inserting events)
await conn.execute(
    "NOTIFY workflow_events, $1",
    f"{run_id}:{event_type}:{sequence_number}"
)

# Subscriber
async def listen_for_events(pool, run_id, callback):
    conn = await pool.acquire()
    await conn.add_listener("workflow_events", callback)
    # callback receives (connection, pid, channel, payload)
    # Parse payload, then query for full event data if needed
```

### Schema Adaptations from SQLite

- `TEXT` -> `TEXT` (same)
- `INTEGER PRIMARY KEY AUTOINCREMENT` -> `BIGSERIAL PRIMARY KEY`
- JSON payload stored as `JSONB` (indexable, queryable)
- Timestamps as `TIMESTAMPTZ` (not TEXT)
- Add `created_at TIMESTAMPTZ DEFAULT now()` server-side defaults

---

## 4. Event Serialization

**Recommendation: JSON only for v1.** MessagePack deferred.

### Rationale
- Pydantic's `model_dump_json()` / `model_validate_json()` is the natural fit for the existing codebase
- JSON stores as native `TEXT` in SQLite and `JSONB` in PostgreSQL, both debuggable with standard tools
- MessagePack (via `msgspec`) is ~10x faster for serialization, but the difference is **< 1ms total** at Orchestra's scale (hundreds of events per run, not millions)
- JSON is human-readable — critical for debugging during development
- Add msgspec-based MessagePack as an optional optimization later if profiling shows need

### Schema Evolution
- Use `event_type` discriminator field for forward compatibility
- New event types can be added without breaking old logs (unknown types are skipped or stored as raw JSON)
- Never remove or rename fields — only add new optional fields
- Version the event schema with a `schema_version: int = 1` field on the base class

---

## 5. State Projection (Rebuilding State from Events)

### Algorithm
1. Find the latest snapshot for the run: `SELECT * FROM workflow_snapshots WHERE run_id = ? ORDER BY sequence_number DESC LIMIT 1`
2. Load all events after the snapshot: `SELECT * FROM workflow_events WHERE run_id = ? AND sequence_number > ? ORDER BY sequence_number`
3. Start from snapshot state (or empty state if no snapshot)
4. Apply each `StateUpdated` event using `apply_state_update()` with reducers
5. Result is the current state

### Snapshot Frequency

**Recommendation: Snapshot every 100 events (not 50 as roadmap suggested).**

- Typical workflows produce 20-200 events
- At 50-event intervals, most runs snapshot only once and many short runs never benefit
- At 100 events, replay takes < 50ms which is acceptable
- Snapshots kick in for longer-running workflows where they actually matter
- Make frequency configurable: `EventStore(snapshot_interval=100)`

### Snapshot Trigger
- After every Nth event, take a snapshot
- Also snapshot on HITL interrupt (ensures fast resume)
- Also snapshot on workflow completion (final state)

---

## 6. EventStore Protocol

```python
@runtime_checkable
class EventStore(Protocol):
    async def append_events(self, run_id: str, events: list[WorkflowEvent]) -> None: ...
    async def get_events(self, run_id: str, after_sequence: int = 0) -> list[WorkflowEvent]: ...
    async def get_latest_snapshot(self, run_id: str) -> tuple[dict[str, Any], int] | None: ...
    async def save_snapshot(self, run_id: str, state: dict[str, Any], sequence_number: int) -> None: ...
    async def create_run(self, run_id: str, workflow_name: str, initial_state: dict[str, Any]) -> None: ...
    async def complete_run(self, run_id: str, status: str, final_state: dict[str, Any]) -> None: ...
    async def get_run(self, run_id: str) -> dict[str, Any] | None: ...
    async def list_runs(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]: ...
```

---

## 7. Integration Points in Existing Codebase

### Event Emission Hooks
- `CompiledGraph.run()` — emit `NodeStarted`/`NodeCompleted`/`StateUpdated` at node boundaries
- `BaseAgent.run()` — emit `LLMCalled` and `ToolCalled` from the agent's tool-calling loop
- `runner.run()` — initialize event store, create run record, handle final state snapshot
- Error handlers — emit `ErrorOccurred` on exceptions

### Dependencies to Add
- `aiosqlite>=0.22` (core dependency — SQLite is the default)
- `asyncpg>=0.29` (optional dependency for PostgreSQL)

---

## 8. Open Questions

1. **Event retention policy** — recommend indefinite for v1 (let users manage storage)
2. **Event ordering across parallel nodes** — does not affect state projection because reducers are commutative by design. Sequence numbers are assigned at write time, not execution time
3. **Database migration strategy** — simple version table for v1, not Alembic. Auto-create tables on first use.

---

*Research: 2026-03-07*
*Researcher: gsd-phase-researcher agent*
