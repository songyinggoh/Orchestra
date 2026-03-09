---
phase: 02-differentiation-wave2
verified: 2026-03-09T00:00:00Z
status: gaps_found
score: 17/19 must-haves verified
gaps:
  - truth: "SQLiteEventStore is importable from the public storage package"
    status: failed
    reason: "SQLiteEventStore and SnapshotManager are not imported or listed in src/orchestra/storage/__init__.py. Users must import directly from orchestra.storage.sqlite."
    artifacts:
      - path: "src/orchestra/storage/__init__.py"
        issue: "SQLiteEventStore and SnapshotManager absent from imports and __all__"
    missing:
      - "Add 'from orchestra.storage.sqlite import SQLiteEventStore, SnapshotManager' (guarded with try/except for aiosqlite) to storage/__init__.py"
      - "Add 'SQLiteEventStore' and 'SnapshotManager' to __all__"

  - truth: "PostgresEventStore is importable from the public storage package"
    status: partial
    reason: "PostgresEventStore is listed in __all__ but the name is not bound in the module namespace when asyncpg is absent. 'from orchestra.storage import PostgresEventStore' raises ImportError. The try/except block only sets _postgres_available = False without creating a sentinel or conditional __all__ entry."
    artifacts:
      - path: "src/orchestra/storage/__init__.py"
        issue: "try/except ImportError suppresses binding; PostgresEventStore in __all__ but not in namespace"
    missing:
      - "Either: remove PostgresEventStore from __all__ when asyncpg is absent, OR re-raise with a helpful message inside __getattr__, OR create a lazy-import stub so the name is always present"
---

# Phase 02 Wave 2 Verification Report

**Phase Goal:** Deliver durable event persistence (SQLite + PostgreSQL), rich terminal tracing, and a first-class handoff protocol — the three features that differentiate Orchestra from basic LLM wrappers.
**Verified:** 2026-03-09
**Status:** gaps_found — implementation is excellent; two public-API export gaps found
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | SQLiteEventStore exists with WAL mode and 3-table schema | VERIFIED | sqlite.py lines 36-75: PRAGMA WAL, workflow_runs, workflow_events, workflow_checkpoints DDL |
| 2 | SQLiteEventStore implements append/get_events/get_latest_checkpoint/save_checkpoint/list_runs | VERIFIED | sqlite.py lines 149-315: all five protocol methods fully implemented |
| 3 | SnapshotManager subscribes to EventBus and checkpoints every N events | VERIFIED | sqlite.py lines 366-399: on_event() counts per-run, triggers save_checkpoint at interval |
| 4 | CompiledGraph.run() accepts persist=, event_store=, run_id= params | VERIFIED | compiled.py line 75-85: signature confirmed; auto-creates SQLiteEventStore when persist=True |
| 5 | Lifecycle events emitted: RunStarted, RunCompleted, RunFailed, NodeEntered, NodeCompleted | VERIFIED | compiled.py lines 182-316: ExecutionStarted, NodeStarted, NodeCompleted, ErrorOccurred, ExecutionCompleted all emitted |
| 6 | aiosqlite added to pyproject.toml storage extras | VERIFIED | pyproject.toml line 41: storage = ["aiosqlite>=0.19"] |
| 7 | test_sqlite_store.py has 12+ tests covering core behavior | VERIFIED | 18 tests collected and passing (includes WAL mode, checkpoint roundtrip, SnapshotManager, lifecycle events) |
| 8 | RichTraceRenderer is an EventBus subscriber rendering a live terminal tree | VERIFIED | console.py: full implementation with per-node branches, LLM/tool sub-rows, token/cost totals; degrades gracefully when no terminal |
| 9 | HandoffEdge and HandoffPayload are frozen dataclasses | VERIFIED | handoff.py lines 25-87: both use @dataclass(frozen=True) with all required fields |
| 10 | distill_context() implements three-zone model; full_passthrough() exists | VERIFIED | context_distill.py lines 25-101: prefix/middleware/suffix zones, word-truncation, summary message construction |
| 11 | graph.add_handoff() method exists and stores HandoffEdge | VERIFIED | graph.py lines 153-173: add_handoff() creates HandoffEdge, appends to _handoff_edges, returns self |
| 12 | agent.py emits LLMCalled and ToolCalled events via context.event_bus | VERIFIED | agent.py lines 109-164: both events emitted with full token/cost/duration data |
| 13 | compiled.py wires RichTraceRenderer via ORCHESTRA_TRACE env var | VERIFIED | compiled.py lines 168-179: checks ORCHESTRA_TRACE, instantiates RichTraceRenderer, subscribes on_event |
| 14 | test_trace.py has 8+ tests | VERIFIED | 18 tests collected and passing |
| 15 | test_handoff.py has 10+ tests | VERIFIED | 27 tests collected and passing |
| 16 | PostgresEventStore exists with 3-table schema matching SQLite | VERIFIED | postgres.py lines 48-95: same three tables, JSONB columns, UUID primary keys, advisory lock, LISTEN/NOTIFY |
| 17 | asyncpg added to pyproject.toml postgres extras | VERIFIED | pyproject.toml line 42: postgres = ["asyncpg>=0.29"] |
| 18 | test_postgres_store.py has 10+ tests using mocked asyncpg | VERIFIED | 16 tests collected and passing; uses FakePool/FakeConnection stubs |
| 19 | SQLiteEventStore and PostgresEventStore exported from storage/__init__.py | FAILED | SQLiteEventStore/SnapshotManager not in __init__.py at all; PostgresEventStore listed in __all__ but name unbound when asyncpg absent |

**Score:** 17/19 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/orchestra/storage/sqlite.py` | SQLiteEventStore + SnapshotManager | VERIFIED | 400 lines, substantive, fully wired via CompiledGraph |
| `src/orchestra/storage/postgres.py` | PostgresEventStore | VERIFIED | 529 lines, substantive, wired via __init__ try/except |
| `src/orchestra/observability/console.py` | RichTraceRenderer | VERIFIED | 262 lines, full event dispatch, subscribed by CompiledGraph |
| `src/orchestra/core/handoff.py` | HandoffEdge + HandoffPayload | VERIFIED | frozen dataclasses, wired in graph.py and compiled.py |
| `src/orchestra/core/context_distill.py` | distill_context + full_passthrough | VERIFIED | three-zone model complete, wired in compiled.py _resolve_next |
| `src/orchestra/storage/__init__.py` | All stores exported | PARTIAL | SQLiteEventStore/SnapshotManager absent; PostgresEventStore in __all__ but unbound when asyncpg missing |
| `tests/unit/test_sqlite_store.py` | 12+ tests | VERIFIED | 18 tests |
| `tests/unit/test_trace.py` | 8+ tests | VERIFIED | 18 tests |
| `tests/unit/test_handoff.py` | 10+ tests | VERIFIED | 27 tests |
| `tests/unit/test_postgres_store.py` | 10+ tests | VERIFIED | 16 tests |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| CompiledGraph.run() | SQLiteEventStore | persist=True auto-init | WIRED | Lines 138-156: auto-creates, create_run(), subscribes |
| CompiledGraph.run() | RichTraceRenderer | ORCHESTRA_TRACE env | WIRED | Lines 168-179: conditional instantiation + subscribe |
| CompiledGraph._resolve_next() | HandoffEdge | _handoff_edges list | WIRED | Lines 469-524: checks condition, distills, emits HandoffInitiated |
| HandoffEdge | distill_context / full_passthrough | edge.distill flag | WIRED | Lines 481-484: branches on edge.distill |
| agent.py | LLMCalled event | context.event_bus.emit | WIRED | Lines 111-117: emits with run_id, node_id, tokens, cost |
| agent.py | ToolCalled event | context.event_bus.emit | WIRED | Lines 161-164: emits with tool_name, args, result, duration |
| storage/__init__.py | PostgresEventStore | try/except ImportError | PARTIAL | Name in __all__ but not bound when asyncpg absent — import fails |
| storage/__init__.py | SQLiteEventStore | direct import | NOT_WIRED | No import statement or __all__ entry |

---

## Test Suite Results

```
Wave 2 tests only:
  test_sqlite_store.py   18 tests — 18 PASSED
  test_trace.py          18 tests — 18 PASSED
  test_handoff.py        27 tests — 27 PASSED
  test_postgres_store.py 16 tests — 16 PASSED
  Wave 2 subtotal:       79 tests — 79 PASSED

Full test suite:
  235 tests — 235 PASSED — 0 failures — 0 errors
  Runtime: 28.20s
```

No regressions from Wave 2 changes.

---

## Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|---------|--------|
| `src/orchestra/storage/__init__.py` | `PostgresEventStore` in `__all__` but name unbound when asyncpg absent | Warning | `from orchestra.storage import PostgresEventStore` raises ImportError; misleading `__all__` |
| `src/orchestra/storage/__init__.py` | `SQLiteEventStore` not exported | Warning | Users must know to import from submodule directly |

No blocker anti-patterns found. No TODO/placeholder/stub patterns in any Wave 2 implementation files.

---

## Implementation Quality Highlights

**SQLiteEventStore:** WAL mode confirmed in DDL, three-table schema with proper indexes, foreign keys, async context manager, correct `aiosqlite.Row` factory for column name access. The `create_run` / `update_run_status` helpers (beyond protocol) are correctly used by CompiledGraph.

**PostgresEventStore:** Advisory lock via `pg_advisory_xact_lock(hashtext(run_id))` prevents concurrent sequence corruption. LISTEN/NOTIFY streaming via `subscribe_events()` is a genuine bonus beyond the plan's scope. JSONB columns for efficient querying.

**RichTraceRenderer:** Full dispatch across all six event types. Graceful degradation when no terminal (catches exceptions from Rich Live). Token and cost accumulation correctly attributed per-node and in totals. Verbose mode toggles truncation length.

**HandoffEdge / distill_context:** Frozen dataclasses guarantee immutability. The three-zone distillation (system prefix + word-truncated middleware summary + last-N suffix) is correctly implemented and wired. HandoffInitiated event is emitted during _resolve_next.

**CompiledGraph.run():** `persist=`, `event_store=`, `run_id=` all present in signature and correctly handled. The store lifecycle (create_run on start, update_run_status on success and failure, close) is properly managed. ORCHESTRA_TRACE wiring is clean.

---

## Gaps Summary

Two gaps found, both in `src/orchestra/storage/__init__.py`. The implementations themselves are complete and correct. The gap is purely in the public API surface.

**Gap 1 — SQLiteEventStore not exported:** The plan specified that SQLiteEventStore should be accessible from `orchestra.storage`. Currently users must `from orchestra.storage.sqlite import SQLiteEventStore`. The fix is a guarded import line in `__init__.py` plus `__all__` entry.

**Gap 2 — PostgresEventStore partially exported:** It appears in `__all__` (giving false confidence) but the name is not bound in the module namespace when `asyncpg` is not installed. `from orchestra.storage import PostgresEventStore` raises `ImportError`. The plan noted "lazy import so orchestra.storage remains importable" — the module-level import is safe, but the name binding is dropped on failure. Fix options: (a) use `__getattr__` for lazy binding with a helpful error, (b) remove from `__all__` when unavailable, or (c) create a placeholder that raises on instantiation rather than import.

These gaps are minor in practice (the test suite works, the implementations are excellent) but they break the advertised public contract. Both can be fixed with 5-10 lines in `__init__.py`.

---

_Verified: 2026-03-09_
_Verifier: Claude (gsd-verifier)_
