---
phase: "02-differentiation"
plan: "08"
subsystem: "examples"
tags: ["advanced-examples", "handoff", "hitl", "time-travel", "integration-tests", "ScriptedLLM"]
dependency_graph:
  requires: ["Plan 04b (HandoffEdge, add_handoff)", "Plan 06 (HITL interrupt/resume)", "Plan 07 (fork, time-travel)"]
  provides: ["examples/handoff.py", "examples/hitl_review.py", "examples/time_travel.py", "tests/integration/test_advanced_examples.py"]
  affects: []
tech_stack:
  added: []
  patterns:
    - "ScriptedLLM for CI-safe deterministic example execution"
    - "InMemoryEventStore for isolation in integration tests"
key_files:
  created:
    - "examples/handoff.py"
    - "examples/hitl_review.py"
    - "examples/time_travel.py"
    - "tests/integration/test_advanced_examples.py"
decisions:
  - "All examples use ScriptedLLM so they run in CI without LLM API keys"
  - "Integration tests use InMemoryEventStore to avoid file system writes"
  - "Examples include both test_main() (scripted, CI) and main() (real LLM, interactive) entry points"
metrics:
  completed_date: "2026-03-09"
  tasks_completed: 2
  files_created: 4
  tests_added: 3
  commits: ["251d497", "a724cc5"]
---

# Phase 02 Plan 08: Advanced Examples Summary

**One-liner:** Three end-to-end example workflows demonstrating Phase 2 features — handoff, HITL, and time-travel — all runnable in CI via ScriptedLLM.

## What Was Built

### Example 1: Customer Support Handoff (`examples/handoff.py`, 92 lines)

Demonstrates triage agent classifying incoming requests and handing off to specialist agents (billing, technical, general):
- `WorkflowGraph.add_handoff()` to wire triage → specialist edges
- `HandoffPayload` context transfer with `distill_context()`
- ScriptedLLM script for CI; real LLM for interactive use

### Example 2: HITL Content Review (`examples/hitl_review.py`, 79 lines)

Demonstrates writer agent generating content with a human approval checkpoint:
- `interrupt_after=True` on the writer node
- `CompiledGraph.resume()` with optional state modifications
- Shows HITL resume flow with modified state

### Example 3: Time-Travel Research (`examples/time_travel.py`, 85 lines)

Demonstrates multi-step research workflow with time-travel operations:
- Event log inspection via `SQLiteEventStore.get_events()`
- `CompiledGraph.fork()` branching from historical sequence
- Side-effect-safe replay in forked historical phase

### Integration Tests (`tests/integration/test_advanced_examples.py`)

3 tests, all passing in under 1 second total:
1. `test_handoff_integration` — verifies handoff example completes with correct routing
2. `test_hitl_integration` — verifies interrupt and resume flow
3. `test_time_travel_fork_integration` — verifies fork creates independent run

## Test Results

| Suite | Tests | Result |
|-------|-------|--------|
| test_advanced_examples.py | 3 | PASS |
| test_examples.py (prior examples) | 13 | PASS |
| Full regression | 260 (unit+integration) | PASS |

## Commits

| Hash | Message |
|------|---------|
| 251d497 | feat: add example workflows and clean up lint config |
| a724cc5 | test: add integration tests for example workflows |
