# Task 06: HITL (Interrupt/Resume) + Tool ACLs -- Detailed Execution Plan

**Phase:** 02-differentiation
**Task:** 06 (DIFF-04 + DIFF-09)
**Created:** 2026-03-09
**Status:** In Execution
**Wave:** 3
**Dependencies:** Wave 2 (SQLite Event Store, Handoff Protocol)
**Estimated effort:** 5 days

---

## Objective

1. **Human-in-the-Loop (HITL)** — Enable pausing workflows at node boundaries for human approval or state modification. Includes checkpointing and cross-process resume.
2. **Tool ACLs** — Implementation of granular access control lists for tool execution, ensuring agents can only call authorized tools.

---

## Task 6.1: HITL Foundation (Nodes & CompiledGraph)

**Files:**
- `src/orchestra/core/nodes.py` (Modify)
- `src/orchestra/core/compiled.py` (Modify)
- `src/orchestra/storage/events.py` (Modify)

**Action:**
1. Add `interrupt_before: bool = False` and `interrupt_after: bool = False` to `AgentNode`, `FunctionNode`, and `SubgraphNode`.
2. Update `CompiledGraph.run()` loop to check for interrupts.
3. Add `InterruptRequested` and `InterruptResumed` events to `events.py`.

**CompiledGraph Logic:**
- Before executing a node: if `node.interrupt_before`, save a checkpoint and return the current state + `run_id`.
- After executing a node: if `node.interrupt_after`, save a checkpoint and return.

---

## Task 6.2: Checkpointing Infrastructure

**Files:**
- `src/orchestra/storage/checkpoint.py` (Create)
- `src/orchestra/storage/sqlite.py` (Modify)
- `src/orchestra/storage/postgres.py` (Modify)

**Action:**
1. Define `Checkpoint` Pydantic model capturing state, node_id, loop_counters, and execution_order.
2. Implement `save_checkpoint(checkpoint)` and `get_checkpoint(run_id)` in `SQLiteEventStore` and `PostgresEventStore`.
3. Add `workflow_checkpoints` table to both databases.

---

## Task 6.3: Resume API & State Modification

**Files:**
- `src/orchestra/core/compiled.py` (Add `resume()` method)
- `src/orchestra/core/context.py` (Update `ExecutionContext` serialization)

**Action:**
1. Implement `CompiledGraph.resume(run_id, state_updates=None)`:
   - Load latest checkpoint from store.
   - Apply `state_updates` to checkpoint state.
   - Reconstruct `ExecutionContext` (loop counters, etc.).
   - Continue `run()` loop from the interrupted node.

---

## Task 6.4: Tool Access Control Lists (ACLs)

**Files:**
- `src/orchestra/security/acl.py` (Create)
- `src/orchestra/core/agent.py` (Modify)

**Action:**
1. Implement `ToolACL` which defines allowed/denied tool names or patterns.
2. Implement `ToolRegistry` that wraps a collection of tools and enforces a `ToolACL`.
3. Update `BaseAgent` to accept an optional `acl` parameter.
4. In `BaseAgent._execute_tool`, check if the tool is authorized by the ACL before calling it.
5. Emit `SecurityViolation` event if a denied tool is requested.

---

## Task 6.5: CLI Interactive HITL

**Files:**
- `src/orchestra/cli/main.py` (Modify)

**Action:**
1. Add `orchestra resume <run_id>` command.
2. If `ORCHESTRA_INTERACTIVE=true`, provide a Rich-based menu on interrupt to inspect/modify state.

---

## Task 6.6: Tests

**Files:**
- `tests/unit/test_hitl.py`
- `tests/unit/test_acl.py`

**HITL Tests:**
- `interrupt_before` stops execution correctly.
- `resume()` continues from the right node with updated state.
- Checkpoints survive process restart (test with fresh `CompiledGraph`).
- Parallel nodes + interrupt behavior (ensure other branches finish).

**ACL Tests:**
- Agent can call allowed tools.
- Agent is blocked from calling denied tools.
- Pattern-based ACLs (e.g., `read_*` allowed, `write_*` denied).
- Security events are emitted correctly.

---

## File Inventory

| Action | File |
|--------|------|
| Modify | `src/orchestra/core/nodes.py` |
| Modify | `src/orchestra/core/compiled.py` |
| Modify | `src/orchestra/core/agent.py` |
| Modify | `src/orchestra/storage/events.py` |
| Modify | `src/orchestra/storage/sqlite.py` |
| Modify | `src/orchestra/storage/postgres.py` |
| Create | `src/orchestra/storage/checkpoint.py` |
| Create | `src/orchestra/security/acl.py` |
| Create | `tests/unit/test_hitl.py` |
| Create | `tests/unit/test_acl.py` |

---
*Plan created: 2026-03-09*
*Executor: Gemini CLI*
