---
phase: 02-differentiation-wave3
verified: 2026-03-09T00:00:00Z
status: gaps_found
score: 9/11 must-haves verified
gaps:
  - truth: "orchestra resume <run_id> CLI command exists"
    status: failed
    reason: "cli/main.py has no 'resume' command. Task 6.5 was not implemented."
    artifacts:
      - path: "src/orchestra/cli/main.py"
        issue: "Only 'version', 'init', and 'run' commands present. No 'resume' command."
    missing:
      - "Add @app.command() def resume(run_id: str, ...) to cli/main.py that calls CompiledGraph.resume() via auto-loaded SQLiteEventStore"

  - truth: "Pre-existing store tests pass without regression"
    status: failed
    reason: "Wave 3 changed the Checkpoint type from CheckpointCreated (event) to Checkpoint (Pydantic model), but pre-Wave-3 test fixtures still instantiate CheckpointCreated and pass it to save_checkpoint(). Four test failures result."
    artifacts:
      - path: "tests/unit/test_sqlite_store.py"
        issue: "make_checkpoint() factory returns CheckpointCreated (line 61-67); test_checkpoint_roundtrip passes it to SQLiteEventStore.save_checkpoint() which now expects Checkpoint — raises AttributeError on checkpoint.loop_counters"
      - path: "tests/unit/test_postgres_store.py"
        issue: "_make_checkpoint() factory returns CheckpointCreated (line 175-182); test_save_checkpoint_executes_upsert raises same AttributeError; test_get_latest_checkpoint_returns_checkpoint fake row dict missing interrupt_type, execution_context, created_at keys"
      - path: "tests/unit/test_events.py"
        issue: "test_event_type_enum_completeness asserts len(EventType) == 17 (line 90), but Wave 3 added INTERRUPT_REQUESTED, INTERRUPT_RESUMED, CHECKPOINT_CREATED, SECURITY_VIOLATION — enum now has 18 members"
    missing:
      - "Update make_checkpoint() in test_sqlite_store.py to return storage.checkpoint.Checkpoint instead of CheckpointCreated"
      - "Update _make_checkpoint() in test_postgres_store.py to return storage.checkpoint.Checkpoint instead of CheckpointCreated"
      - "Update fake_row in test_get_latest_checkpoint_returns_checkpoint to include interrupt_type, execution_context (as dict), and created_at keys"
      - "Update test_event_type_enum_completeness to assert len(EventType) == 18"
---

# Phase 02 Wave 3 Verification Report

**Phase Goal:** Enable Human-in-the-Loop (HITL) pause/resume of workflows at node boundaries, and enforce per-agent tool access control lists (ACLs).
**Verified:** 2026-03-09
**Status:** gaps_found — core implementations are complete and correct; one planned deliverable (CLI resume command) is absent; four pre-existing tests break due to a type change in save_checkpoint()
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | interrupt_before/interrupt_after params on all three node types | VERIFIED | nodes.py lines 32-33, 46-47, 64-65: all three dataclasses carry both flags |
| 2 | WorkflowGraph.add_node() accepts interrupt_before= and interrupt_after= | VERIFIED | graph.py lines 129-130: keyword params forwarded to _wrap_as_node() |
| 3 | CompiledGraph._run_loop() pauses before a node when interrupt_before=True | VERIFIED | compiled.py lines 347-380: emits InterruptRequested, saves Checkpoint, returns state with __metadata__ |
| 4 | CompiledGraph._run_loop() pauses after a node when interrupt_after=True | VERIFIED | compiled.py lines 424-463: determines next node first, saves Checkpoint at next_node, returns state with __metadata__.next_node |
| 5 | Checkpoint Pydantic model captures run_id, node_id, state, loop_counters, execution_order | VERIFIED | storage/checkpoint.py: frozen Pydantic model with all required fields and factory method |
| 6 | SQLiteEventStore.save_checkpoint() and get_latest_checkpoint() are implemented | VERIFIED | sqlite.py lines 288-313, 226-256: full SQL upsert and SELECT with execution_context JSON column |
| 7 | CompiledGraph.resume() loads checkpoint, applies state_updates, continues loop | VERIFIED | compiled.py lines 207-287: loads via event_store.get_latest_checkpoint(), merges state_updates, reconstructs ExecutionContext, delegates to _run_loop with bypass flag |
| 8 | ToolACL with is_authorized(), allow_list(), deny_list(), open() factory methods | VERIFIED | security/acl.py: frozen dataclass, fnmatch pattern support, all four methods present |
| 9 | BaseAgent._execute_tool() checks ACL before executing; emits SecurityViolation on denial | VERIFIED | agent.py lines 228-249: acl.is_authorized() guard, SecurityViolation emitted via event_bus |
| 10 | test_hitl.py and test_acl.py all pass | VERIFIED | 6/6 tests pass (3 HITL + 3 ACL) |
| 11 | orchestra resume CLI command exists | FAILED | cli/main.py only has version, init, run — no resume command |

**Score:** 10/11 truths verified (CLI resume absent)

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/orchestra/core/nodes.py` | interrupt_before/interrupt_after on all node types | VERIFIED | 74 lines; AgentNode, FunctionNode, SubgraphNode all updated |
| `src/orchestra/core/compiled.py` | _run_loop() with HITL checks; resume() method | VERIFIED | 831 lines; interrupt_before block at line 347, interrupt_after block at line 424, resume() at line 207 |
| `src/orchestra/storage/checkpoint.py` | Checkpoint Pydantic model | VERIFIED | 56 lines; frozen model with all required fields |
| `src/orchestra/storage/events.py` | InterruptRequested, InterruptResumed, SecurityViolation, CheckpointCreated event types | VERIFIED | lines 173-205: all four HITL/security events present with correct fields |
| `src/orchestra/storage/sqlite.py` | save_checkpoint(), get_latest_checkpoint(), get_checkpoint() | VERIFIED | lines 226-313: full implementation with workflow_checkpoints table already in DDL |
| `src/orchestra/security/acl.py` | ToolACL + UnauthorizedToolError | VERIFIED | 73 lines; frozen dataclass with fnmatch, three factory classmethods |
| `src/orchestra/core/agent.py` | acl field on BaseAgent; ACL check in _execute_tool | VERIFIED | lines 52, 228-249: acl field (lazy default open), guard + SecurityViolation emission |
| `tests/unit/test_hitl.py` | 3+ HITL tests | VERIFIED | 3 tests: interrupt_before, interrupt_after, resume_with_state_updates — all pass |
| `tests/unit/test_acl.py` | 3+ ACL tests | VERIFIED | 3 tests: allow_list, patterns, security event emission — all pass |
| `src/orchestra/cli/main.py` | orchestra resume command | MISSING | File exists but no resume command defined |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| CompiledGraph._run_loop() | Checkpoint | Checkpoint.create() factory | WIRED | lines 359-367: creates Checkpoint before saving |
| CompiledGraph._run_loop() | event_store.save_checkpoint() | direct await | WIRED | lines 368-369 (before) and 450-451 (after) |
| CompiledGraph.resume() | event_store.get_latest_checkpoint() | direct await | WIRED | line 239: loads checkpoint, raises AgentError if None |
| CompiledGraph.resume() | _run_loop() | bypass_interrupt_on_start flag | WIRED | line 280-287: correct bypass=True for "before" interrupt type |
| BaseAgent._execute_tool() | ToolACL.is_authorized() | self.acl guard | WIRED | lines 228-232: lazy-init to ToolACL.open() then is_authorized() check |
| BaseAgent._execute_tool() | SecurityViolation event | context.event_bus.emit | WIRED | lines 234-243: emits if event_bus is not None |
| InterruptRequested event | events.py | imported in _run_loop | WIRED | line 304: imported at top of _run_loop |
| InterruptResumed event | events.py | imported in resume() | WIRED | line 226: imported at top of resume() |

---

## Test Suite Results

```
Wave 3 tests only:
  test_hitl.py   3 tests — 3 PASSED
  test_acl.py    3 tests — 3 PASSED
  Wave 3 subtotal: 6 tests — 6 PASSED

Full test suite:
  241 tests collected — 237 PASSED — 4 FAILED
  Runtime: 27.50s

FAILURES (all regressions from Wave 3 type changes):
  test_events.py::TestEventTypes::test_event_type_enum_completeness
    assert len(EventType) == 17  # now 18 (HITL + security events added)

  test_sqlite_store.py::test_checkpoint_roundtrip
    make_checkpoint() returns CheckpointCreated; save_checkpoint() now expects Checkpoint
    AttributeError: 'CheckpointCreated' object has no attribute 'loop_counters'

  test_postgres_store.py::test_save_checkpoint_executes_upsert
    _make_checkpoint() returns CheckpointCreated; same type mismatch
    AttributeError: 'CheckpointCreated' object has no attribute 'loop_counters'

  test_postgres_store.py::test_get_latest_checkpoint_returns_checkpoint
    FakeRow missing keys: interrupt_type, execution_context, created_at
    KeyError: 'execution_context'
```

---

## Root Cause of Regressions

Wave 3 introduced `storage/checkpoint.py` with a dedicated `Checkpoint` Pydantic model. The `save_checkpoint()` signatures in both SQLiteEventStore and PostgresEventStore were updated to accept `Checkpoint`. However, the pre-existing test fixtures in `test_sqlite_store.py` and `test_postgres_store.py` still create `CheckpointCreated` event objects (the old pattern) and pass them to `save_checkpoint()`. The `Checkpoint` model has `loop_counters` and `node_execution_order` fields; `CheckpointCreated` does not.

Additionally, `test_get_latest_checkpoint_returns_checkpoint` in `test_postgres_store.py` uses a hand-crafted fake row dict that matches the old column layout. The PostgresEventStore now reads `interrupt_type`, `execution_context`, and `created_at` columns that are absent from the fake row.

The `test_event_type_enum_completeness` test hardcoded `17` before HITL events were added; the count is now `18`.

**None of these failures indicate broken production code.** The actual `save_checkpoint()` implementations are correct and used properly by `CompiledGraph`. The new HITL tests that exercise the real path all pass. These are stale test helpers that were not updated when the `Checkpoint` type was introduced.

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|---------|--------|
| `src/orchestra/cli/main.py` | — | Task 6.5 not implemented: no `orchestra resume` command | Warning | Users cannot resume interrupted runs from CLI; must call `compiled.resume()` programmatically |
| `tests/unit/test_sqlite_store.py` | 61-67 | `make_checkpoint()` returns wrong type (`CheckpointCreated` not `Checkpoint`) | Blocker | `test_checkpoint_roundtrip` fails with AttributeError |
| `tests/unit/test_postgres_store.py` | 175-182 | `_make_checkpoint()` returns wrong type (`CheckpointCreated` not `Checkpoint`) | Blocker | Two postgres checkpoint tests fail |
| `tests/unit/test_events.py` | 90 | Hardcoded count `assert len(EventType) == 17` | Blocker | Fails because EventType now has 18 members |

---

## Human Verification Required

None. All failures are definitively identified and mechanically verifiable.

---

## Gaps Summary

### Gap 1 — CLI resume command not implemented (Task 6.5)

`cli/main.py` has three commands: `version`, `init`, `run`. The `orchestra resume <run_id>` command specified in Task 6.5 is absent. The underlying `CompiledGraph.resume()` method is fully implemented and tested, so this is a CLI surface gap only. The plan also specified a Rich-based interactive menu under `ORCHESTRA_INTERACTIVE=true` — that too is absent.

**Fix:** Add `@app.command() def resume(run_id: str, ...)` to `cli/main.py` that loads a `CompiledGraph` and calls `.resume(run_id, event_store=SQLiteEventStore())`. The interactive menu can come in a follow-up.

### Gap 2 — Four test regressions from type mismatch (stale test helpers)

Three test files were written before `Checkpoint` was separated from `CheckpointCreated`. The `save_checkpoint()` interface changed to accept `Checkpoint` (the storage model) rather than `CheckpointCreated` (the event). Test helpers were not updated.

**Fix 1 — test_sqlite_store.py line 61:** Change `make_checkpoint()` to return `Checkpoint.create(run_id=..., node_id=..., interrupt_type="before", state={"x": 42, "step": 1}, sequence_number=sequence, loop_counters={}, node_execution_order=[])`. Update `assert retrieved.state_snapshot` to `assert retrieved.state` (field renamed).

**Fix 2 — test_postgres_store.py line 175:** Same change for `_make_checkpoint()`.

**Fix 3 — test_postgres_store.py line 362:** Add `interrupt_type="before"`, `execution_context={"loop_counters": {}, "node_execution_order": []}`, and `created_at=datetime.now(timezone.utc)` to the `FakeRow` dict. Update assertions to match `Checkpoint` field names.

**Fix 4 — test_events.py line 90:** Change `assert len(EventType) == 17` to `assert len(EventType) == 18`.

---

_Verified: 2026-03-09_
_Verifier: Claude (gsd-verifier)_
