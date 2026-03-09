# Task 07: Time-Travel Debugging -- Detailed Execution Plan

**Phase:** 02-differentiation
**Task:** 07 (DIFF-05)
**Created:** 2026-03-09
**Status:** In Execution
**Wave:** 4
**Dependencies:** Wave 1 (Events), Wave 2 (Persistence), Wave 3 (Checkpoints)
**Estimated effort:** 4 days

---

## Objective

Enable "Time-Travel" capabilities: the ability to jump to any historical event in a workflow run, reconstruct the exact state at that moment, and optionally "fork" a new execution path from that point while maintaining side-effect safety.

---

## Task 7.1: Time-Travel Controller (Reconstruction)

**Files:**
- `src/orchestra/debugging/timetravel.py` (Create)

**Action:**
1. Implement `TimeTravelController` class.
2. Method `get_state_at(run_id, sequence_number)`:
   - Load all events for `run_id` up to `sequence_number`.
   - Use `project_state()` to reconstruct the state.
   - Return the state dict + the `node_id` that was active at that sequence.

---

## Task 7.2: Branching Infrastructure (Forking)

**Files:**
- `src/orchestra/core/compiled.py` (Modify)
- `src/orchestra/storage/events.py` (Modify)

**Action:**
1. Implement `CompiledGraph.fork(run_id, sequence_number, state_overrides=None)`:
   - Generate a new `fork_run_id`.
   - Reconstruct state from original run at `sequence_number`.
   - Apply `state_overrides`.
   - Emit `ForkCreated(original_run_id, sequence_number, new_run_id)`.
   - Return a "ready-to-run" state that can be passed to `run()`.

---

## Task 7.3: Side-Effect Safety (Shadow Replay)

**Files:**
- `src/orchestra/providers/replay.py` (Create)
- `src/orchestra/core/context.py` (Modify)

**Action:**
1. Create `ReplayProvider`: A wrapper that takes a historical event log and returns recorded `LLMResponse` and `ToolResult` objects instead of calling APIs.
2. Update `ExecutionContext` to include a `replay_history` field.
3. Update `BaseAgent` to check `context.replay_history` before making real calls. (Done in Task 6.4/Wave 3 partially, but needs full implementation).

---

## Task 7.4: Tests

**Files:**
- `tests/unit/test_timetravel.py` (Create)

**Scenarios:**
1. Reconstruct state at turn 3 of a 10-turn run.
2. Fork a run at turn 5, modify state, and verify it diverges correctly.
3. Verify that tool calls in a forked run (during the "history" phase) are mocks and don't trigger the real provider.

---

## File Inventory

| Action | File |
|--------|------|
| Create | `src/orchestra/debugging/timetravel.py` |
| Create | `src/orchestra/providers/replay.py` |
| Modify | `src/orchestra/core/compiled.py` |
| Modify | `src/orchestra/storage/events.py` |
| Create | `tests/unit/test_timetravel.py` |

---
*Plan created: 2026-03-09*
*Executor: Gemini CLI*
