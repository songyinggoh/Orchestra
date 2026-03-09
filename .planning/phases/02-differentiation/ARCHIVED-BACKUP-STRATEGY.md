# Phase 2 Backup and Rollback Strategy

**Phase:** 02-Differentiation
**Written:** 2026-03-08
**Author:** backup-planner agent
**Scope:** Tasks 2.1-2.11 across 6 weeks of development

---

## 1. Git Branching Strategy

### Recommended Structure: Task Branches off a Phase Integration Branch

```
master
└── phase-2/integration          (long-lived integration branch for Phase 2)
    ├── task/2.1-event-sourcing  (closed after merge)
    ├── task/2.2-sqlite-backend  (closed after merge)
    ├── task/2.3-postgres-backend
    ├── task/2.4-hitl-interrupt
    ├── task/2.5-time-travel
    ├── task/2.6-rich-trace
    ├── task/2.7-handoff-protocol
    ├── task/2.8-mcp-client
    ├── task/2.9-tool-acls
    ├── task/2.10-google-ollama-providers
    └── task/2.11-advanced-examples
```

### Rationale

A single `phase-2/integration` branch acts as the stable rollback target for the entire phase. Task branches isolate in-progress work so a partially-complete task can be abandoned without affecting other tasks. The integration branch is only updated when a task passes its regression gate (see Section 4).

Do not work directly on `master` until Phase 2 is complete and all 11 tasks have passed their gates. This preserves `master` as the known-good Phase 1 baseline for the full duration of Phase 2 development.

### Tagging Checkpoints

Create an annotated git tag before each task begins:

```bash
git tag -a phase2-pre-task-2.1 -m "Checkpoint before task 2.1: Event Sourcing"
git tag -a phase2-pre-task-2.4 -m "Checkpoint before task 2.4: HITL (first core engine touch)"
git tag -a phase2-pre-task-2.5 -m "Checkpoint before task 2.5: Time Travel (modifies compiled.py)"
```

Tags on the integration branch serve as named rollback points that survive branch operations. Push tags immediately after creation:

```bash
git push origin --tags
```

### Hard Rollback Protocol

If a task branch breaks the integration branch beyond quick repair:

1. Do not attempt to fix forward under pressure. Stop and assess.
2. Identify the last passing tag on the integration branch.
3. Create a salvage branch from the broken state before discarding anything:
   ```bash
   git checkout -b salvage/task-2.X-broken phase-2/integration
   ```
4. Reset the integration branch to the last known-good tag:
   ```bash
   git checkout phase-2/integration
   git reset --hard phase2-pre-task-2.X
   git push origin phase-2/integration --force-with-lease
   ```
5. Reopen the task with the salvage branch available for diffing.

---

## 2. Checkpoint and Rollback Points Between Tasks

Phase 2 has three natural risk tiers. The rollback strategy differs by tier.

### Tier 1: Additive-Only Tasks (Low Risk)

These tasks add new modules without modifying existing Phase 1 source files. A rollback is simply reverting the merge.

| Task | New Modules | Phase 1 Files Touched |
|------|-------------|----------------------|
| 2.1 Event Sourcing (layer) | `src/orchestra/storage/events.py`, `store.py`, `serialization.py`, `contracts.py` | None |
| 2.2 SQLite Backend | `src/orchestra/storage/sqlite.py` | None |
| 2.3 PostgreSQL Backend | `src/orchestra/storage/postgres.py` | None |
| 2.6 Rich Trace Renderer | `src/orchestra/observability/console.py` | `observability/logging.py` (minor) |
| 2.7 Handoff Protocol | `src/orchestra/core/handoff.py` | `compiled.py` (reads `handoff_to` already in `AgentResult`) |
| 2.9 Tool ACLs | `src/orchestra/tools/acls.py` | `tools/registry.py` (additive) |
| 2.10 Google/Ollama Providers | `src/orchestra/providers/google.py`, `ollama.py` | `providers/__init__.py` (additive) |
| 2.11 Advanced Examples | `examples/` | None |

**Rollback procedure:** `git revert <merge-commit-sha>` on the integration branch. All Phase 1 tests continue to pass.

### Tier 2: Instrumentation Tasks (Medium Risk)

These tasks add event emission hooks and trace wiring into Phase 1 execution paths. The hooks must be additive — existing behavior must be preserved when no event store is configured.

| Task | Phase 1 Files Modified | Change Nature |
|------|------------------------|---------------|
| 2.1 (wiring) | `compiled.py` — emit NodeStarted/NodeCompleted around `_execute_node` | Hook calls wrapped in `if self._event_emitter` guard |
| 2.1 (wiring) | `agent.py` — emit LLMCalled/ToolCalled in `BaseAgent.run()` | Same guard pattern |
| 2.1 (wiring) | `runner.py` — initialize event store, pass emitter to context | Optional initialization |
| 2.1 (wiring) | `context.py` — add `event_emitter: Any = None` field | Additive, backward compatible |

**Rollback procedure:** Because these are all guarded behind `if self._event_emitter`, removing the guard blocks and the `event_emitter` field from `ExecutionContext` cleanly restores Phase 1 behavior. Keep the wiring changes as a single commit per file so each can be reverted independently.

**Explicit commit discipline:** Each file's instrumentation wiring should be its own commit, with a subject line starting `feat(event-hooks):`. This allows `git revert <sha>` to undo a single file's hooks without touching others.

### Tier 3: Behavioral-Change Tasks (High Risk)

These tasks change the execution flow of `CompiledGraph.run()` fundamentally. They require the most careful rollback preparation.

| Task | Phase 1 Files Modified | Risk |
|------|------------------------|------|
| 2.4 HITL | `compiled.py` — interrupt check in the main execution loop | Loop control flow changes |
| 2.4 HITL | `graph.py` — `interrupt_before`/`interrupt_after` params on `add_node()` | Signature change |
| 2.4 HITL | `runner.py` — `resume()` entry point, checkpoint hydration | New code path |
| 2.5 Time Travel | `compiled.py` — replay-mode flag, side-effect suppression | Execution branching |

**Rollback procedure for Tier 3:** These changes cannot be cleanly reverted with a single `git revert` because they interleave with the existing execution loop logic. The only reliable rollback is returning to the pre-task tag:

```bash
git checkout phase-2/integration
git reset --hard phase2-pre-task-2.4   # or 2.5
```

For this reason, the integration branch must have a tag immediately before each Tier 3 task starts, and the task must be developed on an isolated `task/` branch that is never directly pushed to the integration branch until all its regression gates pass.

### HITL Interrupt: Surgical Implementation Plan

The HITL interrupt in `CompiledGraph.run()` is the single highest-risk change. The correct implementation preserves the existing loop invariant by raising a dedicated internal exception (`HITLInterrupt`) that is caught at the `run()` level:

```
BEFORE each node execution:
  if node_id in self._interrupt_before and not context.resuming:
      raise HITLInterrupt(node_id=node_id, state=state, run_id=context.run_id)

catch HITLInterrupt at compiled.run() level:
  persist checkpoint
  return InterruptedResult (not a normal state dict)
```

This keeps the core loop body unchanged. The interrupt signal travels out of the loop via exception, not via a flag that the loop checks mid-iteration. Rollback: remove the pre-node check and the exception class. The loop body is untouched.

---

## 3. Data Backup Strategy for `.orchestra/runs.db`

### Directory Structure

```
.orchestra/
  runs.db          (SQLite event store — primary data)
  runs.db-wal      (SQLite WAL log — in-flight transactions)
  runs.db-shm      (SQLite shared memory — WAL coordination)
  backups/
    runs.db.2026-03-08T12-00-00.bak   (manual snapshots)
  mcp.json         (MCP server configuration — version control this)
```

The `.orchestra/` directory must be in `.gitignore`. The SQLite database contains run history that is specific to each developer's local environment and grows unboundedly. It is not repository content.

Exception: `.orchestra/mcp.json` should be committed to version control since it defines which MCP servers the project uses.

### SQLite WAL Mode Configuration

Enable WAL mode immediately on database initialization. This is non-negotiable for concurrent parallel node writes:

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;    -- Safe with WAL; FULL is unnecessary overhead
PRAGMA wal_autocheckpoint = 1000;  -- Checkpoint every 1000 pages
PRAGMA busy_timeout = 5000;     -- 5-second retry on lock contention
```

WAL mode allows concurrent readers during writes, and multiple writers serialize automatically without deadlock. Without WAL, parallel node execution (via `asyncio.gather()` in `_execute_parallel()`) will hit SQLite locking errors when two nodes try to append events simultaneously.

The `-wal` and `-shm` sidecar files must be treated as part of the database. Never copy `runs.db` without also copying its `-wal` and `-shm` files — doing so can corrupt the database. The safe copy procedure is:

```bash
# Safe SQLite backup using the backup API (not file copy)
sqlite3 .orchestra/runs.db ".backup .orchestra/backups/runs.db.$(date +%Y-%m-%dT%H-%M-%S).bak"
```

The SQLite `.backup` command uses the backup API which is safe during live writes.

### Developer Backup Workflow

Before each Tier 3 task begins, take a manual SQLite backup:

```bash
# Before task 2.4 (HITL — modifies schema indirectly via checkpoint tables)
sqlite3 .orchestra/runs.db ".backup .orchestra/backups/pre-task-2.4.bak"

# Before task 2.5 (time-travel — adds checkpoint history queries)
sqlite3 .orchestra/runs.db ".backup .orchestra/backups/pre-task-2.5.bak"
```

This is in addition to the git tag. The git tag protects the code; the SQLite backup protects the run history data accumulated during development testing.

### Schema Version Table

Add a `schema_version` table on first database initialization:

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now')),
    description TEXT
);
INSERT INTO schema_version (version, description) VALUES (1, 'Initial Phase 2 schema');
```

Every subsequent schema migration increments the version and inserts a row. Code reads the current version on startup and refuses to run if the code version is older than the database version, preventing silent data corruption from a rollback.

### Graceful Handling of Missing or Corrupt Database

If the database file is missing, corrupted, or locked beyond the `busy_timeout`:

1. Log a warning at `WARN` level with the error details.
2. Continue workflow execution without persistence (in-memory only).
3. Set `context.persistence_available = False` so downstream code (HITL, time-travel) can raise `PersistenceRequiredError` if they need the store.
4. Do not raise an exception that kills the workflow. Losing persistence is undesirable but not a reason to fail a workflow that was otherwise going to complete successfully.

This is the graceful degradation contract: the event store is a feature enhancement, not a runtime dependency of core execution.

---

## 4. Regression Testing Gates Between Tasks

Each task branch must pass its gate before merging to `phase-2/integration`. The gate is automated (run in CI) and manual (human sign-off on DX features).

### Gate Structure

**Gate 0: Phase 1 Baseline (permanent, every task)**

This gate runs on every PR to `phase-2/integration`. It is non-negotiable.

```bash
pytest tests/ -x -q --ignore=tests/integration/  # All Phase 1 tests pass
mypy src/orchestra/                                # No new type errors
ruff check src/                                   # No new lint errors
```

If this gate fails, the task branch is not merged regardless of whether its own tests pass. Phase 1 regression is a blocking defect.

**Gate 1 (Task 2.1 — Event Sourcing Layer)**

```bash
pytest tests/unit/test_events.py -v           # Event types, serialization, projection
pytest tests/unit/test_core.py -v             # MUST still pass — no regression
# Manual: confirm compiled.run() with no event_emitter produces identical output to Phase 1
```

**Gate 2 (Task 2.2 — SQLite Backend)**

```bash
pytest tests/unit/test_storage_sqlite.py -v  # In-memory SQLite tests
# Benchmark: 1000 event append/read cycle under 100ms
python -c "
import asyncio, time
from orchestra.storage.sqlite import SQLiteEventStore
async def bench():
    store = SQLiteEventStore(':memory:')
    await store.initialize()
    t = time.monotonic()
    for i in range(1000):
        await store.append(make_test_event(i))
    elapsed = (time.monotonic() - t) * 1000
    print(f'1000 events: {elapsed:.1f}ms')
asyncio.run(bench())
"
# Manual: verify .orchestra/runs.db is created on first workflow run
# Manual: verify runs.db survives process restart and events are readable
```

**Gate 3 (Task 2.3 — PostgreSQL Backend)**

```bash
# Only if ORCHESTRA_PG_DSN is set in environment
pytest tests/integration/test_storage_postgres.py -v -m integration
# Parity test: same test suite passes against both SQLite and PostgreSQL backends
pytest tests/unit/test_storage_sqlite.py -v  # Re-run SQLite suite (no regression)
```

**Gate 4 (Task 2.4 — HITL Interrupt/Resume) — HIGHEST RISK**

```bash
pytest tests/ -x -q                          # Full suite including Phase 1
pytest tests/unit/test_hitl.py -v            # HITL-specific tests
# Critical regression tests (must be written as part of this task):
pytest tests/unit/test_hitl.py::test_workflow_without_interrupt_unchanged -v
pytest tests/unit/test_hitl.py::test_interrupt_before_persists_checkpoint -v
pytest tests/unit/test_hitl.py::test_resume_reconstructs_state_correctly -v
pytest tests/unit/test_hitl.py::test_resume_after_process_restart -v
pytest tests/unit/test_hitl.py::test_multiple_interrupt_points -v
# Manual DX review:
# - Run sequential.py example with interrupt_before on second node
# - Inspect state in terminal
# - Modify one field
# - Resume and verify field change propagated correctly
```

A workflow that has no `interrupt_before`/`interrupt_after` configured must produce byte-identical output to the Phase 1 baseline. Write a parameterized test that runs the same workflow with and without interrupt configuration and asserts the outputs match.

**Gate 5 (Task 2.5 — Time Travel)**

```bash
pytest tests/ -x -q                          # Full suite
pytest tests/unit/test_timetravel.py -v
# Replay safety verification:
pytest tests/unit/test_timetravel.py::test_fork_does_not_execute_external_tools -v
pytest tests/unit/test_timetravel.py::test_replay_returns_cached_tool_results -v
```

**Gate 6 (Task 2.6 — Rich Trace Renderer)**

```bash
pytest tests/ -x -q                          # Full suite — no regression
pytest tests/unit/test_console.py -v         # Renderer-specific tests
# ORCHESTRA_TRACE=off must produce zero Rich library calls (test with monkeypatching)
# Manual DX review:
# - Run sequential.py with ORCHESTRA_TRACE=rich
# - Verify live tree updates, cost display, timing
# - Verify verbose mode with ORCHESTRA_TRACE=verbose
# - Verify production mode with ORCHESTRA_ENV=prod shows no Rich output
```

The Rich renderer must not import at the top level if Rich is not installed. Use lazy imports guarded by a try/except to allow the framework to run without Rich in environments where it is not installed.

**Gates 7-11 (Tasks 2.7-2.11)**

Follow the same pattern: full Phase 1 suite passes, task-specific tests pass, manual DX review of the feature's primary user-facing behavior.

For task 2.8 (MCP client), add a subprocess-safety gate: verify that MCP server subprocesses are cleaned up if the workflow raises an exception, and that they are not started at import time.

### Coverage Enforcement

The 80% coverage floor (`fail_under = 80`) in `pyproject.toml` must be maintained. Each task adds tests alongside its code. If a task's tests would drop coverage below 80%, the gate fails.

Track coverage per-module (not just overall) to prevent new modules from shipping with minimal coverage hidden by high coverage in other areas:

```bash
pytest tests/ --cov=orchestra --cov-report=term-missing --cov-fail-under=80
```

---

## 5. Graceful Degradation Patterns

The following table defines the degradation contract for each Phase 2 component. The core principle: the execution of a workflow must never fail because of an infrastructure component that was added in Phase 2. Phase 2 features enhance workflows; they do not become required for workflows to function.

### Event Store Failure Modes

| Failure | Detection | Degraded Behavior | User Signal |
|---------|-----------|-------------------|-------------|
| Database file not found | `FileNotFoundError` on open | In-memory execution, no persistence | `WARN` log: "Event store unavailable: <path> not found. Running without persistence." |
| Database locked (timeout) | `sqlite3.OperationalError: database is locked` after `busy_timeout` | In-memory execution for this run | `WARN` log with suggestion to check for competing processes |
| Database corrupt | `sqlite3.DatabaseError` | In-memory execution | `ERROR` log: "Event store corrupt. Run `orchestra db repair`." |
| Disk full on write | `sqlite3.OperationalError: disk I/O error` | Buffer events in memory, periodic retry | `WARN` log every 60 seconds |
| Schema version mismatch (code older than DB) | Version check on startup | Refuse to write new events; read-only mode | `ERROR` log: "Database schema version N requires code version M or later." |

The key pattern is: `EventStore.append()` must never raise an exception that propagates into `CompiledGraph.run()`. All exceptions from the event store are caught, logged, and the degraded behavior is applied silently from the execution engine's perspective.

Implement this with a `SafeEventStore` wrapper:

```python
class SafeEventStore:
    """Wraps an EventStore and swallows persistence errors gracefully."""

    def __init__(self, store: EventStore | None, logger: Any) -> None:
        self._store = store
        self._logger = logger
        self.available = store is not None

    async def append(self, event: WorkflowEvent) -> None:
        if self._store is None:
            return
        try:
            await self._store.append(event)
        except Exception as e:
            self._logger.warning("event_store_append_failed", error=str(e))
            self.available = False
```

### HITL Interrupt Without Event Store

If HITL is configured (`interrupt_before` or `interrupt_after` on a node) but the event store is unavailable, the framework must raise a `PersistenceRequiredError` immediately at workflow start — not at the moment of interrupt:

```
PersistenceRequiredError: HITL interrupts require an event store for checkpoint persistence.
  Node 'review_node' has interrupt_before=True.
  Fix: Ensure .orchestra/runs.db is writable, or disable HITL for this run.
```

Failing early with a clear message is preferable to reaching the interrupt point and then failing in a way that leaves the workflow in an indeterminate state.

### Rich Trace Renderer Failure Modes

| Failure | Detection | Degraded Behavior |
|---------|-----------|-------------------|
| `rich` not installed | `ImportError` | Fall back to plain structlog output |
| Terminal too narrow | Rich `MarkupError` on render | Fall back to single-line summary per node |
| Renderer blocks event loop | `asyncio.TimeoutError` in renderer callback | Drop rendering for that event, log at DEBUG |

The Rich renderer subscribes to workflow events via an in-process event bus. The subscription is fire-and-forget from the execution engine's perspective. If the renderer raises, the exception is caught by the event bus and logged, not propagated to the execution engine.

The renderer must use `asyncio.get_event_loop().call_soon()` or similar to schedule updates, never blocking `await` calls in the event handler. Rich's `Live` display must run on the event loop without blocking agent execution.

### MCP Client Failure Modes

| Failure | Detection | Degraded Behavior |
|---------|-----------|-------------------|
| MCP server process fails to start | `subprocess.CalledProcessError` | Skip that MCP server, log at `ERROR` |
| MCP server crashes during run | `BrokenPipeError` on stdio read | Mark MCP tools as unavailable, log at `ERROR` |
| MCP tool call times out | `asyncio.TimeoutError` | Return `ToolResult` with `error="MCP tool timeout"` |
| MCP server not in PATH | `FileNotFoundError` | Raise `MCPServerNotFoundError` at configuration time (fail-fast) |

MCP server subprocess management must use asyncio subprocess primitives (`asyncio.create_subprocess_exec`) so the subprocess is properly awaited and does not become a zombie. Register a cleanup handler via `atexit` and on graph completion to terminate subprocesses.

---

## 6. Migration Strategy for Event Schema Changes

Event schema changes are the most dangerous operation in Phase 2 because they affect persisted data that may be read by older code (rolling restarts, local development switching branches).

### Schema Versioning Design

Every `WorkflowEvent` subtype carries a `schema_version: int` field:

```python
@dataclass(frozen=True)
class WorkflowEvent:
    event_id: str
    run_id: str
    event_type: str
    schema_version: int          # incremented when the event's fields change
    timestamp: datetime
    sequence: int                # monotonic per run_id
```

Events are serialized with their `schema_version`. Deserialization checks the version and applies upgrade transformations before returning the event to calling code.

### Three Levels of Schema Change

**Level 1: Additive Change (adding a field with a default)**

A new optional field with a default value does not break existing persisted events. Existing events deserialize with the default value for the new field. No migration required. No schema version bump for the database; bump the event's `schema_version` field.

Example: Adding `token_cost_usd: float = 0.0` to `LLMCalledEvent`.

**Level 2: Non-Breaking Rename or Restructure**

A field is renamed or its type changes in a backward-compatible way (e.g., `str` to `str | None`). This requires an upgrade function applied during deserialization:

```python
_UPGRADE_FUNCTIONS: dict[tuple[str, int], Callable] = {
    ("LLMCalledEvent", 1): _upgrade_llm_called_v1_to_v2,
}

def deserialize_event(data: dict) -> WorkflowEvent:
    event_type = data["event_type"]
    schema_version = data.get("schema_version", 1)
    upgrade_key = (event_type, schema_version)
    if upgrade_key in _UPGRADE_FUNCTIONS:
        data = _UPGRADE_FUNCTIONS[upgrade_key](data)
    return _EVENT_REGISTRY[event_type](**data)
```

Upgrade functions are pure: they take a dict and return a dict. They are composable: version 1 -> 2 -> 3.

This approach means old events stored in the database are upgraded transparently on read. No database migration is needed.

**Level 3: Breaking Change (removing a field, changing semantics)**

A field is removed or its semantics change in a way that cannot be expressed as a pure upgrade function. This is the only case that requires a database migration.

Before this happens mid-phase (which should be avoided by design), follow this protocol:

1. Add the new field alongside the old one (Level 1 change). Ship this in a task branch.
2. Mark the old field as deprecated in the event class docstring.
3. Write all new events with the new field; continue reading old field for old events.
4. At the phase end (or a dedicated migration task), write a migration script:
   ```python
   # migrate_schema_v1_to_v2.py
   async def migrate(db_path: str) -> None:
       """
       Migration: rename 'node_name' to 'node_id' in NodeStartedEvent.
       Reads all events of type NodeStartedEvent, rewrites with new field.
       Safe: reads from source, writes to temp table, swaps atomically.
       """
   ```
5. The migration script must be idempotent (running it twice is safe).
6. Test the migration script against a copy of the production database before running it.

### Migration Rules

- Never modify the `schema_version` in the database schema version table for a Level 1 change.
- Always bump `schema_version` for Level 2 and Level 3 changes.
- Never delete old event types from the codebase during Phase 2. They may be stored in existing `.orchestra/runs.db` databases. Mark them `deprecated` and retain deserialization support.
- Store the raw JSON of unknown or unrecognized event types rather than failing. This allows a downgraded code version to coexist with a database that has newer event types without crashing.

### Mid-Phase Schema Emergency Protocol

If a schema bug is discovered mid-phase (e.g., an event field was incorrectly typed and is storing garbage):

1. Do not delete the corrupt events. Append a corrective event: `SchemaCorruptionNoted(run_id, event_id, description)`.
2. Fix the event class and write an upgrade function that produces corrected values from the corrupt data.
3. Write a repair script that identifies affected runs and appends corrective snapshots to override the corrupt state.
4. Document in a `SCHEMA-INCIDENTS.md` file in `.planning/phases/02-differentiation/`.

The goal is always forward-only repair via event appends, not backward mutation of the event log. The event log is append-only by design; that invariant must be preserved even during error recovery.

---

## 7. Summary: Rollback Decision Tree

```
A task branch is complete and ready to gate:
│
├── Does `pytest tests/unit/test_core.py` pass? (Phase 1 gate)
│   ├── NO  → Do NOT merge. Task branch is broken. Fix or abandon.
│   └── YES → Continue
│
├── Does the task's own test suite pass?
│   ├── NO  → Do NOT merge. Fix tests first.
│   └── YES → Continue
│
├── Does `mypy src/orchestra/` pass with no new errors?
│   ├── NO  → Fix type errors first (may require more thought on interfaces)
│   └── YES → Continue
│
├── Is this a Tier 3 task (HITL or Time Travel)?
│   ├── YES → Was an integration branch tag created before this task?
│   │          └── NO → Create the tag NOW before merging.
│   └── Continue
│
└── Merge to phase-2/integration. Create post-task tag.
    Tag format: phase2-post-task-2.X
```

### Rollback Triggers

Roll back (return to the pre-task tag) when:
- More than 2 hours spent fixing a Phase 1 regression with no clear path to resolution.
- The HITL interrupt changes the output of an existing workflow (even a single field difference).
- The SQLite write path causes data corruption in concurrent parallel node execution.
- An MCP subprocess leaks across test runs (test isolation failure).

Roll forward (fix on the task branch) when:
- The issue is confined to new code added by the task.
- The Phase 1 regression test suite still passes.
- The fix can be described in one sentence.

---

## 8. Files Requiring Special Care

These Phase 1 files are modified in Phase 2 and require the most attention during code review and testing:

**`src/orchestra/core/compiled.py` (382 LOC)**
Modification points: event emission hooks before/after `_execute_node`, interrupt check before node execution, replay-mode flag in `_execute_parallel`. All modifications must be guarded by `if self._event_emitter` and `if not context.replay_mode`. Any change that touches the `while` loop control flow in `run()` must be accompanied by a test that verifies the original sequential/parallel/conditional examples still produce identical output.

**`src/orchestra/core/agent.py` (260 LOC)**
Modification points: LLMCalled event before `await llm.complete()`, ToolCalled event before `await tool.execute()`. These are additions only — the existing loop structure is not changed. The hooks are fire-and-forget (no `await` of the event store in the hot path; use `asyncio.ensure_future()` to avoid blocking the agent loop).

**`src/orchestra/core/runner.py` (122 LOC)**
Modification points: event store initialization, SafeEventStore wrapping, context injection, `resume()` entry point. The existing `run()` and `run_sync()` signatures must not change. New parameters should be keyword-only with defaults that preserve current behavior.

**`src/orchestra/core/graph.py` (452 LOC)**
Modification points: `add_node()` gains `interrupt_before: bool = False` and `interrupt_after: bool = False` keyword-only parameters. The stored node representation must carry these flags to `CompiledGraph`. No existing callers are broken because the new parameters have defaults.

**`src/orchestra/tools/registry.py` (71 LOC)**
Modification points: ACL enforcement, MCP tool registration. The existing `register()` and `get()` methods must remain backward compatible. ACLs are additive: a tool without ACL configuration is accessible to all agents (current behavior preserved).

---

## 9. Pre-Phase Checklist

Before writing the first line of Phase 2 code:

- [ ] Create `phase-2/integration` branch from current `master`
- [ ] Run full test suite on the integration branch and confirm it is green
- [ ] Create tag `phase2-baseline` on the integration branch
- [ ] Confirm `.orchestra/` is in `.gitignore`
- [ ] Confirm SQLite is available in the dev environment (`python -c "import sqlite3; print(sqlite3.sqlite_version)"`)
- [ ] Add `aiosqlite` to `pyproject.toml` core dependencies (SQLite backend is the default)
- [ ] Add `asyncpg` to `pyproject.toml` optional dependencies under `[postgres]` extra
- [ ] Confirm Rich is available (`python -c "import rich; print(rich.__version__)"`) — already present via Typer
- [ ] Document the Phase 1 test count as the baseline regression floor

---

*Strategy authored: 2026-03-08*
*Next review: After Task 2.4 (HITL) completes — reassess if the interrupt mechanism required more invasive changes than anticipated*
