---
phase: "02-differentiation"
plan: "07"
subsystem: "debugging"
tags: ["time-travel", "state-reconstruction", "forking", "replay", "side-effect-safe"]
dependency_graph:
  requires: ["Plan 01 (EventBus, project_state)", "Plan 04a (SQLiteEventStore)", "Plan 06 (Checkpoint infrastructure)"]
  provides: ["TimeTravelController", "CompiledGraph.fork()", "ReplayProvider", "side-effect-safe replay"]
  affects: ["CompiledGraph", "ExecutionContext"]
tech_stack:
  added: []
  patterns:
    - "Event projection via project_state() for historical reconstruction"
    - "Fork-on-write: new run_id emitting ForkCreated event before diverging"
    - "Replay safety via context.replay_history — agent checks history before real API calls"
key_files:
  created:
    - "src/orchestra/debugging/timetravel.py"
    - "src/orchestra/providers/replay.py"
    - "tests/unit/test_timetravel.py"
  modified:
    - "src/orchestra/core/compiled.py"
    - "src/orchestra/core/context.py"
decisions:
  - "fork() placed on CompiledGraph (not TimeTravelController) to reuse the existing _run_loop and event wiring"
  - "TimeTravelController.get_state_at() uses project_state() — same projection function as the event store, ensuring consistency"
  - "replay_mode check uses getattr(context, 'replay_mode', False) — forward-compatible without requiring a field migration"
  - "Side-effect safety: agent checks context.replay_history first; if a matching LLMCalled event exists, returns recorded response without calling API"
metrics:
  completed_date: "2026-03-09"
  tasks_completed: 4
  files_created: 3
  files_modified: 2
  tests_added: 3
  commit: "438c434"
---

# Phase 02 Plan 07: Time-Travel Debugging Summary

**One-liner:** State reconstruction at any historical sequence number, deterministic branching via fork(), and side-effect-safe replay using recorded LLM responses.

## What Was Built

### TimeTravelController (`src/orchestra/debugging/timetravel.py`)

- `get_state_at(run_id, sequence_number) -> HistoricalState` — loads all events for the run, filters to `sequence_number`, calls `project_state()` to reconstruct state, identifies the active node and turn count from event types
- `HistoricalState` frozen dataclass: `run_id`, `sequence_number`, `state`, `node_id`, `turn_number`

### CompiledGraph.fork() (`src/orchestra/core/compiled.py`)

- `fork(parent_run_id, sequence_number, *, state_overrides, event_store)` — reconstructs historical state via `TimeTravelController`, generates a new `fork_run_id`, applies `state_overrides`, emits `ForkCreated` event, returns `(new_run_id, initial_state, start_node_id)` ready to pass to `run()`

### ReplayProvider / Side-Effect Safety (`src/orchestra/providers/replay.py`, `src/orchestra/core/context.py`)

- `ReplayProvider` wraps a historical event log; when an agent calls the LLM, it checks `context.replay_history` first and returns the recorded `LLMResponse` if a matching `LLMCalled` event exists
- `ExecutionContext.replay_history` field added — populated during fork replay to suppress real API calls in the historical phase

### Tests (`tests/unit/test_timetravel.py`)

3 tests, all passing:
1. `test_state_reconstruction` — reconstruct state at turn 3 of a multi-step run
2. `test_fork_and_diverge` — fork at turn 5, verify new run diverges with state overrides
3. `test_side_effect_safe_replay` — tool calls in forked historical phase use mocks, not real provider

## Test Results

| Suite | Tests | Result |
|-------|-------|--------|
| test_timetravel.py | 3 | PASS |
| Full regression | 244 | PASS |

## Commits

| Hash | Message |
|------|---------|
| 438c434 | feat(phase-02): complete Phase 2 differentiation — waves 1-3 |
