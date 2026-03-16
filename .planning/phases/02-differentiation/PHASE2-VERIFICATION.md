---
phase: 02-differentiation
verified: 2026-03-09T00:00:00Z
status: gaps_found
score: 14/17 must-haves verified
gaps:
  - truth: "CLI resume command exists for interrupted workflows"
    status: failed
    reason: "cli/main.py has only version, init, run commands. No 'resume' command. Plan 06 Task 6.5 was not implemented."
    artifacts:
      - path: "src/orchestra/cli/main.py"
        issue: "Only 3 commands (version, init, run). No resume command for HITL workflows."
    missing:
      - "Add @app.command() def resume(run_id: str, ...) to cli/main.py that calls CompiledGraph.resume()"

  - truth: "Plan 08 (Advanced Examples) is delivered"
    status: failed
    reason: "Plan 08 was never created. No PLAN-08.md or PLAN-08-SUMMARY.md exists. However, example files DO exist in examples/ directory (handoff.py, hitl_review.py, time_travel.py) with substantive content (79-103 lines each). The examples exist but were delivered ad-hoc without a formal plan."
    artifacts:
      - path: ".planning/phases/02-differentiation/PLAN-08.md"
        issue: "File does not exist - plan was never created"
    missing:
      - "If formal plan tracking is required, create PLAN-08.md and PLAN-08-SUMMARY.md documenting the existing examples"

  - truth: "TimeTravelController has fork() method for side-effect-safe replay"
    status: partial
    reason: "fork() exists on CompiledGraph (not TimeTravelController). TimeTravelController only has get_state_at(). The Plan 07 specification called for fork() on CompiledGraph anyway, and it IS implemented there (lines 293-360). However, side-effect-safe replay (Plan 07 Task 7.3) is implemented via replay_events on ExecutionContext with tool-call matching in agent.py, which is functional but minimal (88 lines total in timetravel.py). No PLAN-07-SUMMARY.md exists."
    artifacts:
      - path: "src/orchestra/debugging/timetravel.py"
        issue: "Only 88 lines. Has TimeTravelController.get_state_at() but no dedicated fork() or replay methods - those live in CompiledGraph"
      - path: ".planning/phases/02-differentiation/PLAN-07-SUMMARY.md"
        issue: "File does not exist - no summary was written"
    missing:
      - "PLAN-07-SUMMARY.md documenting what was delivered vs planned"
---

# Phase 02: Differentiation - Full Phase Verification Report

**Phase Goal:** Differentiate Orchestra from competitors via event-sourced persistence, MCP integration, multi-provider LLM support, rich tracing, handoff protocol, HITL workflows, tool ACLs, and time-travel debugging.
**Verified:** 2026-03-09
**Status:** gaps_found
**Re-verification:** No -- initial full-phase verification

---

## Executive Summary

Phase 2 has delivered the majority of its ambitious 8-plan roadmap. Waves 1-4 are substantially complete with 244 passing tests (0 failures), all protocol conformances verified, and all key wiring in place. The remaining gaps are:

1. **Missing CLI resume command** (Plan 06 Task 6.5) -- the underlying `CompiledGraph.resume()` is fully implemented and tested, but no CLI surface exists.
2. **No formal Plan 08** -- advanced examples exist ad-hoc in `examples/` but were never tracked as a plan.
3. **No PLAN-06-SUMMARY.md or PLAN-07-SUMMARY.md** -- work was done but not formally documented.

No production code is missing or stubbed. All 244 unit tests pass.

---

## Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | EventBus dispatches 17+ typed events to subscribers | VERIFIED | `storage/events.py` (285 lines): 18 event types as frozen Pydantic models; `EventBus` in `store.py` with async emit, sequence tracking, per-type filtering |
| 2 | EventStore protocol is runtime-checkable with InMemoryEventStore | VERIFIED | `store.py`: `@runtime_checkable Protocol` with append/get_events/get_latest_checkpoint/save_checkpoint/list_runs; `InMemoryEventStore` satisfies it |
| 3 | MCPClient supports stdio and HTTP transports | VERIFIED | `tools/mcp.py` (431 lines): `MCPClient.stdio()` and `MCPClient.http()` factory methods, async context manager lifecycle, `MCPToolAdapter` satisfies Tool protocol |
| 4 | GoogleProvider and OllamaProvider conform to LLMProvider protocol | VERIFIED | `isinstance(GoogleProvider(api_key='test'), LLMProvider)` = True; `isinstance(OllamaProvider(), LLMProvider)` = True. Both have complete(), stream(), count_tokens(), get_model_cost() |
| 5 | SQLiteEventStore persists events with WAL mode and 3-table schema | VERIFIED | `storage/sqlite.py` (444 lines): WAL pragma, workflow_runs/workflow_events/workflow_checkpoints tables, full EventStore protocol implementation |
| 6 | PostgresEventStore with advisory locks, LISTEN/NOTIFY, JSONB | VERIFIED | `storage/postgres.py` (576 lines): asyncpg pool, pg_advisory_xact_lock, pg_notify, JSONB columns, subscribe_events() |
| 7 | CompiledGraph.run() has persist/event_store/run_id params | VERIFIED | `compiled.py` line 84-87: `persist: bool = True`, `event_store: EventStore | None = None`, `run_id: str | None = None` |
| 8 | CompiledGraph.run() emits lifecycle events (Started, NodeStarted, NodeCompleted, Error, Completed) | VERIFIED | `compiled.py` lines 188-196 (ExecutionStarted), 459-466 (NodeStarted), 485-494 (NodeCompleted), 555-572 (ErrorOccurred+ExecutionCompleted), 588-596 (ExecutionCompleted) |
| 9 | BaseAgent.run() emits LLMCalled and ToolCalled events | VERIFIED | `agent.py` lines 113-121 (LLMCalled with token counts, cost, duration), lines 168-172 (ToolCalled with args, result); both guarded by event_bus and replay_mode |
| 10 | RichTraceRenderer subscribes to EventBus and renders live tree | VERIFIED | `observability/console.py` (261 lines): Rich Live tree at 4fps, all event handlers, ORCHESTRA_TRACE env var wiring in compiled.py |
| 11 | HandoffEdge + context distillation + add_handoff() API | VERIFIED | `core/handoff.py` (87 lines): frozen dataclass; `core/context_distill.py` (137 lines): three-zone partitioning; `graph.py` lines 197-217: `add_handoff()` method; `compiled.py` lines 752-806: handoff execution in `_resolve_next()` |
| 12 | HITL interrupt_before/after on nodes, checkpoint, resume | VERIFIED | `nodes.py`: all 3 node types have interrupt_before/after; `compiled.py` lines 420-456 (before), 497-536 (after); `resume()` at lines 211-291; `checkpoint.py` (56 lines): frozen Pydantic model |
| 13 | ToolACL with is_authorized(), allow_list(), deny_list(), open() | VERIFIED | `security/acl.py` (72 lines): frozen dataclass, fnmatch patterns, deny-takes-precedence logic, 3 factory classmethods |
| 14 | BaseAgent._execute_tool() enforces ACL and emits SecurityViolation | VERIFIED | `agent.py` lines 228-249: `acl.is_authorized()` guard, `SecurityViolation` event emission |
| 15 | CLI resume command for interrupted workflows | FAILED | `cli/main.py` has only version, init, run commands |
| 16 | TimeTravelController reconstructs state; CompiledGraph.fork() creates branches | PARTIAL | `timetravel.py` (88 lines): `get_state_at()` works; `compiled.py` lines 293-360: `fork()` implemented. Side-effect replay uses `replay_events` on ExecutionContext. Missing formal PLAN-07-SUMMARY. |
| 17 | Plan 08 Advanced Examples delivered | PARTIAL | Example files exist: `examples/handoff.py` (92 lines), `examples/hitl_review.py` (79 lines), `examples/time_travel.py` (85 lines). Substantive implementations but no formal plan/summary. |

**Score:** 14/17 truths verified (1 failed, 2 partial)

---

## Required Artifacts

| Artifact | Status | Lines | Details |
|----------|--------|-------|---------|
| `src/orchestra/storage/events.py` | VERIFIED | 285 | 18 event types, AnyEvent union, create_event factory |
| `src/orchestra/storage/store.py` | VERIFIED | 221 | EventBus, EventStore protocol, InMemoryEventStore, project_state |
| `src/orchestra/storage/serialization.py` | VERIFIED | 51 | event_to_json, json_to_event, events_to_jsonl, jsonl_to_events |
| `src/orchestra/storage/contracts.py` | VERIFIED | 86 | BoundaryContract, ContractRegistry, graceful jsonschema fallback |
| `src/orchestra/storage/sqlite.py` | VERIFIED | 444 | SQLiteEventStore, SnapshotManager, WAL, 3-table schema |
| `src/orchestra/storage/postgres.py` | VERIFIED | 576 | PostgresEventStore, asyncpg pool, advisory locks, LISTEN/NOTIFY |
| `src/orchestra/storage/checkpoint.py` | VERIFIED | 56 | Checkpoint frozen Pydantic model with factory |
| `src/orchestra/storage/__init__.py` | VERIFIED | 93 | All events, stores, contracts exported; lazy imports for optional backends |
| `src/orchestra/tools/mcp.py` | VERIFIED | 431 | MCPClient, MCPToolAdapter, load_mcp_config |
| `src/orchestra/providers/google.py` | VERIFIED | 454 | GoogleProvider, Gemini API, SSE streaming, error mapping |
| `src/orchestra/providers/ollama.py` | VERIFIED | 384 | OllamaProvider, OpenAI-compat, health_check, list_models |
| `src/orchestra/providers/__init__.py` | VERIFIED | 19 | Lazy __getattr__ imports for Google, Ollama, Anthropic |
| `src/orchestra/observability/console.py` | VERIFIED | 261 | RichTraceRenderer, Live tree, event handler |
| `src/orchestra/core/handoff.py` | VERIFIED | 87 | HandoffEdge, HandoffPayload frozen dataclasses |
| `src/orchestra/core/context_distill.py` | VERIFIED | 137 | distill_context (three-zone), full_passthrough |
| `src/orchestra/core/nodes.py` | VERIFIED | 73 | interrupt_before/after on all 3 node types |
| `src/orchestra/core/compiled.py` | VERIFIED | 904 | run(), resume(), fork(), _run_loop(), HITL interrupt logic, handoff resolution, event emission |
| `src/orchestra/core/graph.py` | VERIFIED | 534 | add_handoff(), interrupt params on add_node()/then(), compile() passes handoff_edges |
| `src/orchestra/core/agent.py` | VERIFIED | ~260 | LLMCalled/ToolCalled emission, ACL enforcement, replay_events support |
| `src/orchestra/security/acl.py` | VERIFIED | 72 | ToolACL, UnauthorizedToolError |
| `src/orchestra/debugging/timetravel.py` | VERIFIED | 88 | TimeTravelController.get_state_at() |
| `src/orchestra/cli/main.py` | PARTIAL | 114 | Missing resume command |
| `examples/handoff.py` | VERIFIED | 92 | Substantive handoff example |
| `examples/hitl_review.py` | VERIFIED | 79 | Substantive HITL example |
| `examples/time_travel.py` | VERIFIED | 85 | Substantive time-travel example |

---

## Protocol Conformance

| Protocol | Implementor | isinstance Check | Status |
|----------|-------------|-----------------|--------|
| EventStore | SQLiteEventStore | True | VERIFIED |
| EventStore | PostgresEventStore | N/A (needs asyncpg) | VERIFIED via test mocks (16 tests pass) |
| EventStore | InMemoryEventStore | True | VERIFIED |
| LLMProvider | GoogleProvider | True | VERIFIED |
| LLMProvider | OllamaProvider | True | VERIFIED |
| Tool protocol | MCPToolAdapter | structural subtyping | VERIFIED via tests |

---

## Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| CompiledGraph.run() | EventBus | direct creation + context.event_bus | WIRED |
| CompiledGraph.run() | SQLiteEventStore | conditional import, persist=True | WIRED |
| CompiledGraph.run() | RichTraceRenderer | ORCHESTRA_TRACE env var | WIRED |
| CompiledGraph._run_loop() | InterruptRequested event | emit in interrupt_before/after blocks | WIRED |
| CompiledGraph._run_loop() | Checkpoint.create() | save_checkpoint() call | WIRED |
| CompiledGraph.resume() | event_store.get_latest_checkpoint() | direct await | WIRED |
| CompiledGraph.fork() | TimeTravelController.get_state_at() | instantiation + call | WIRED |
| CompiledGraph._resolve_next() | HandoffEdge | iteration over _handoff_edges | WIRED |
| CompiledGraph._resolve_next() | distill_context/full_passthrough | conditional call | WIRED |
| BaseAgent.run() | LLMCalled event | context.event_bus.emit | WIRED |
| BaseAgent.run() | ToolCalled event | context.event_bus.emit | WIRED |
| BaseAgent._execute_tool() | ToolACL.is_authorized() | self.acl guard | WIRED |
| WorkflowGraph.add_handoff() | HandoffEdge | stores in _handoff_edges list | WIRED |
| WorkflowGraph.compile() | CompiledGraph | passes handoff_edges | WIRED |
| storage/__init__.py | All event types, stores | direct + lazy imports | WIRED |
| providers/__init__.py | GoogleProvider, OllamaProvider | lazy __getattr__ | WIRED |

---

## Test Suite Results

```
python -m pytest tests/unit/ -q --tb=short
244 passed in 23.50s
```

| Test File | Tests | Status |
|-----------|-------|--------|
| test_core.py | ~55 | PASS |
| test_events.py | ~30 | PASS |
| test_mcp.py | 22 | PASS |
| test_providers.py | 19 | PASS |
| test_sqlite_store.py | 18 | PASS |
| test_postgres_store.py | 16 | PASS |
| test_trace.py | 18 | PASS |
| test_handoff.py | 27 | PASS |
| test_hitl.py | 3+ | PASS |
| test_acl.py | 3+ | PASS |
| test_timetravel.py | 3 | PASS |
| test_rebuff.py | varies | PASS |

All 244 tests pass with 0 failures. The 4 regressions identified in WAVE3-VERIFICATION.md have been fixed.

---

## Summary Files Status

| Plan | Summary File | Status |
|------|-------------|--------|
| Plan 01 (Event System) | PLAN-2.1-SUMMARY.md | EXISTS |
| Plan 02 (MCP Client) | PLAN-2.2-SUMMARY.md | EXISTS |
| Plan 03 (LLM Providers) | PLAN-03-SUMMARY.md | EXISTS |
| Plan 04a (SQLite Store) | PLAN-04a-SUMMARY.md | EXISTS |
| Plan 04b (Rich Trace + Handoff) | PLAN-04b-SUMMARY.md | EXISTS |
| Plan 05 (PostgreSQL) | PLAN-05-SUMMARY.md | EXISTS |
| Plan 06 (HITL + ACLs) | PLAN-06-SUMMARY.md | MISSING |
| Plan 07 (Time-Travel) | PLAN-07-SUMMARY.md | MISSING |
| Plan 08 (Examples) | PLAN-08.md + SUMMARY | MISSING |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `src/orchestra/tools/mcp.py` | 115 | `# TODO: add image/resource content handling` | Info | Documented Phase 3 deferral; text-only MCP results work correctly |
| `src/orchestra/cli/main.py` | -- | Missing `resume` command (Plan 06 Task 6.5) | Warning | Users cannot resume HITL workflows from CLI |

No blocker anti-patterns found. No placeholder implementations. No empty returns in production code.

---

## Export Surface Verification

```python
# All key imports succeed:
from orchestra.tools import MCPClient, MCPToolAdapter, load_mcp_config  # OK
from orchestra.storage import EventBus, EventStore, InMemoryEventStore, SQLiteEventStore, SnapshotManager  # OK
from orchestra.storage import PostgresEventStore  # OK (None if asyncpg absent)
from orchestra.security.acl import ToolACL, UnauthorizedToolError  # OK
from orchestra.providers import HttpProvider  # OK (direct)
# GoogleProvider, OllamaProvider available via lazy __getattr__
```

---

## Human Verification Required

### 1. Rich Trace Renderer Visual Output

**Test:** Set `ORCHESTRA_TRACE=rich` and run a multi-node workflow
**Expected:** Live-updating terminal tree with node names, token counts, costs, timing
**Why human:** Visual rendering quality cannot be verified programmatically

### 2. HITL Workflow End-to-End

**Test:** Run `examples/hitl_review.py` with a real LLM provider
**Expected:** Workflow pauses at review node, saves checkpoint, resumes with state modifications
**Why human:** Full interrupt/resume lifecycle requires interactive testing

### 3. MCP Server Integration

**Test:** Configure an MCP server in `.orchestra/mcp.json` and run an agent with MCP tools
**Expected:** Tools discovered from MCP server, executable via MCPToolAdapter
**Why human:** Requires real MCP server process

---

## Gaps Summary

### Gap 1: Missing CLI resume command (Plan 06 Task 6.5)

The `orchestra resume <run_id>` CLI command was specified in Plan 06 but never implemented. The underlying `CompiledGraph.resume()` method is fully functional and tested. This is a CLI surface gap only -- users can resume programmatically today.

**Severity:** Warning (not a blocker -- programmatic API works)
**Fix:** Add `@app.command() def resume(run_id: str)` to `cli/main.py`

### Gap 2: Missing PLAN-06-SUMMARY.md and PLAN-07-SUMMARY.md

Plans 06 and 07 were executed (implementations exist, tests pass) but no formal summaries were written. This affects traceability but not functionality.

**Severity:** Info (documentation gap only)
**Fix:** Create summary files documenting what was delivered

### Gap 3: No formal Plan 08 (Advanced Examples)

Plan 08 was never created as a formal plan document. However, substantive example files exist in `examples/` covering handoff, HITL, and time-travel scenarios (79-103 lines each). The examples appear to have been created during earlier plan execution.

**Severity:** Info (the work exists, just not formally tracked)
**Fix:** Create PLAN-08.md and PLAN-08-SUMMARY.md if formal tracking is needed

---

## Overall Assessment

Phase 2 has delivered a comprehensive differentiation layer:

- **Event System**: 18 typed events, EventBus, EventStore protocol, boundary contracts
- **Persistence**: SQLite (zero-config) and PostgreSQL (production) backends
- **MCP Integration**: Full client with stdio/HTTP transports
- **Multi-Provider LLM**: Google Gemini and Ollama providers with protocol conformance
- **Observability**: Rich terminal trace renderer wired to EventBus
- **Handoff Protocol**: Swarm-style agent-to-agent transfers with context distillation
- **HITL**: Interrupt/resume at node boundaries with checkpointing
- **Tool Security**: ACL enforcement with pattern matching
- **Time-Travel**: State reconstruction and forking from historical points
- **Examples**: Substantive example workflows for key features

All 244 tests pass. All protocol conformances verified. All key wiring verified. The 3 gaps identified are non-blocking (CLI convenience command, documentation, and plan tracking).

---

_Verified: 2026-03-09_
_Verifier: Claude (gsd-verifier)_
