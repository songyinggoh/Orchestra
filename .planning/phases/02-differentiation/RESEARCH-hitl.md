# Research: HITL Interrupt/Resume and Time-Travel Debugging

**Research Date:** 2026-03-07
**Phase:** 2 - Differentiation
**Confidence:** HIGH

---

## 1. LangGraph HITL Patterns

### interrupt_before / interrupt_after
- LangGraph supports `interrupt_before` and `interrupt_after` as parameters on node definitions
- When execution reaches an interrupt point, the graph saves a checkpoint and returns an `Interrupt` object
- The checkpoint contains the full state dict at that point
- Resume via `Command(resume=value)` passed as input to `graph.invoke()`

### Resume API
```python
# LangGraph pattern
config = {"configurable": {"thread_id": "my-thread"}}

# Run until interrupt
result = graph.invoke(input, config)
# result contains interrupt info

# Resume with modifications
graph.invoke(Command(resume={"approved": True}), config)
```

### Known Issues
- **No built-in terminal UI** — developers must build their own state inspection/modification interface
- **Community pain point** — multiple blog posts document the pattern of wrapping LangGraph HITL in a FastAPI server just to present state to humans
- **State modification is indirect** — you pass a `Command` with resume values, not directly editing state fields
- LangGraph bugs: interrupt + parallel branches can cause double-execution in some versions

### Lessons for Orchestra
- `interrupt_before`/`interrupt_after` parameter pattern is correct and familiar
- Orchestra should provide the terminal UI that LangGraph lacks
- Resume API should allow direct state modification, not just passing resume values
- Test parallel branch + interrupt interaction thoroughly

---

## 2. Other Framework HITL Patterns

### CrewAI
- HITL for Flows launched January 2026
- Community GitHub issues (#2051) show rough DX and incomplete documentation
- Designed primarily for approval gates, not rich state inspection

### AutoGen / Microsoft Agent Framework
- `UserProxyAgent` pattern — a special agent type that proxies to human input
- Supported at API level, no terminal UI
- More conversational (human as a chat participant) than checkpoint-based

### Temporal
- Uses **signals** for human input — external events injected into running workflows
- Workflow blocks on `workflow.wait_condition()` until signal received
- Production-grade but requires Temporal server infrastructure

---

## 3. Checkpoint-Based Resume Design

### What Must Be Serialized
For Orchestra to resume a workflow after process restart, the checkpoint must capture:

1. **Workflow state** — the current Pydantic `WorkflowState` (already serializable via `model_dump_json()`)
2. **Graph position** — which node was about to execute (or just completed)
3. **Loop counters** — `ExecutionContext.loop_counters` dict (for loop edge state)
4. **Node execution order** — `ExecutionContext.node_execution_order` list (for observability)
5. **In-flight parallel branches** — if interrupted during parallel execution, which branches completed and their state updates

### Checkpoint Structure
```python
class Checkpoint(BaseModel):
    model_config = ConfigDict(frozen=True)
    run_id: str
    checkpoint_id: str          # UUID
    sequence_number: int        # Event sequence at checkpoint time
    current_node: str           # Node about to execute (interrupt_before) or just completed (interrupt_after)
    interrupt_type: str         # "before" | "after"
    state: dict[str, Any]       # Full state dict
    loop_counters: dict[str, int]
    node_execution_order: list[str]
    parallel_state: dict | None  # In-flight parallel branch data, if any
    timestamp: datetime
    metadata: dict[str, Any]    # User-provided context
```

### Resume After Code Change
- If workflow code changes between interrupt and resume (e.g., new nodes added), validation must check that the checkpoint's `current_node` still exists in the graph
- Raise a clear error: "Node 'review' was removed from the workflow since this run was interrupted. Cannot resume."
- Do NOT silently skip nodes or re-route

### Cross-Process Resume
- Checkpoint is persisted to SQLite/PostgreSQL (already handled by event store)
- Resume loads checkpoint, reconstructs `ExecutionContext`, and continues from `current_node`
- CLI: `orchestra resume <run_id>` loads the checkpoint and continues

---

## 4. Time-Travel Debugging

### Operations

**list_checkpoints(run_id):**
- Query event store for all checkpoints (or reconstruct from events)
- Return: list of `(checkpoint_id, sequence_number, node_id, timestamp)`
- Can be reconstructed from `StateUpdated` events at node boundaries

**get_state_at(run_id, checkpoint_id):**
- Load the snapshot at or before the checkpoint
- Replay events up to the checkpoint's sequence number
- Return the full state dict at that point

**diff_states(checkpoint_a, checkpoint_b):**
- Load state at both checkpoints
- Compute diff using `deepdiff` library or custom Pydantic diff
- Return structured diff: added fields, removed fields, changed fields with old/new values

**fork_from(run_id, checkpoint_id):**
- Load state at the checkpoint
- Create a new run record with a new `run_id`
- Set the new run's initial state to the checkpoint state
- Record the fork lineage: `forked_from_run_id`, `forked_from_checkpoint_id`
- Start execution from the checkpoint's `current_node`
- Forked runs are fully independent (separate event logs)

### Implementation Notes
- Time-travel does NOT require storing explicit checkpoints at every node — it can reconstruct state from the event log using projection
- However, explicit checkpoints at interrupt points speed up access
- The event log IS the time-travel data — no separate storage needed

---

## 5. State Diff Rendering

### Library: deepdiff
- `deepdiff` (v7+) provides `DeepDiff(state_a, state_b)` for comparing nested dicts
- Handles additions, removals, type changes, value changes
- Works with Pydantic model dicts

### Terminal Rendering
Use Rich for color-coded diff display:
```
State diff: checkpoint_3 -> checkpoint_4
  messages: [+2 items appended]
  output: "Initial draft..." -> "Revised draft with feedback..."
  review_count: 0 -> 1
  + reviewer_notes: "Looks good, minor edits needed"
```

- Green (`[green]+[/]`) for additions
- Red (`[red]-[/]`) for removals
- Yellow (`[yellow]~[/]`) for changes
- Truncate long values (show first 80 chars with `...`)

---

## 6. CLI Interactive Resume UX

### Rich Panel on Interrupt
When a workflow is interrupted, display:

```
┌─────────────────────────────────────────────┐
│  WORKFLOW PAUSED                            │
│  Node: review_agent (interrupt_before)      │
│  Run ID: abc123                             │
├─────────────────────────────────────────────┤
│  Current State:                             │
│    input: "Write a blog post about AI"      │
│    draft: "AI is transforming how we..."    │
│    word_count: 342                          │
│    quality_score: 0.78                      │
├─────────────────────────────────────────────┤
│  Actions:                                   │
│    [r] Resume                               │
│    [m] Modify state                         │
│    [i] Inspect full state (JSON)            │
│    [d] Show execution history               │
│    [a] Abort                                │
└─────────────────────────────────────────────┘
```

### State Modification Flow
1. User presses `[m]`
2. Show state fields as a numbered list
3. User selects field to edit
4. Show current value, prompt for new value (or open `$EDITOR` for long text)
5. Validate new value against Pydantic schema
6. Confirm changes before resuming

### Programmatic API
```python
# Programmatic resume (for FastAPI, tests, etc.)
result = await workflow.resume(
    run_id="abc123",
    state_updates={"approved": True, "reviewer_notes": "Ship it"},
)
```

---

## 7. SQLite Schema for Checkpoints

Checkpoints are stored alongside events (same database):

```sql
CREATE TABLE workflow_checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL UNIQUE,
    sequence_number INTEGER NOT NULL,
    current_node TEXT NOT NULL,
    interrupt_type TEXT NOT NULL,     -- "before" | "after"
    state TEXT NOT NULL,             -- JSON
    execution_context TEXT NOT NULL,  -- JSON (loop_counters, node_order, etc.)
    timestamp TEXT NOT NULL,
    metadata TEXT,                   -- JSON
    FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id)
);
CREATE INDEX idx_checkpoints_run ON workflow_checkpoints(run_id, sequence_number DESC);
```

---

## 8. Pain Points and Pitfalls

1. **Parallel branches + interrupt** — If `interrupt_before` is on a node that's part of a parallel group, the other branches may have already completed. Must save their results before pausing.
2. **Resume with stale state** — If a human takes hours to resume, the state may reference stale external data. Document this as a known limitation, not a bug.
3. **Graph code changes** — Always validate that the checkpoint's node still exists in the current graph before resuming.
4. **Nested subgraphs** — If an interrupt is inside a subgraph, the checkpoint must capture the full subgraph execution context.
5. **Multiple interrupt points** — A workflow can have many interrupt points. Each pause/resume cycle creates a new checkpoint. Test the "pause, resume, pause again" flow.

---

## 9. Dependencies

- `deepdiff>=7.0` — for state diff computation (optional, only needed for time-travel diff)
- `rich` — already available (dependency of typer)
- No additional dependencies for core HITL functionality

---

*Research: 2026-03-07*
*Researcher: gsd-phase-researcher agent*
