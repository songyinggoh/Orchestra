# Task 2.1 Audit: Event-Sourced Persistence Layer

**Audited:** 2026-03-08
**Auditor:** backup-planner agent
**Source files read:** ROADMAP.md (lines 347-370), 02-CONTEXT.md, PLAN.md (Plan 01), BACKUP-STRATEGY.md, compiled.py, agent.py, context.py, state.py, types.py, protocols.py, errors.py, runner.py, nodes.py
**Status:** Pre-implementation (plan exists, no code written yet)

---

## Executive Summary

Task 2.1 is well-conceived but contains seven concrete defects in the current plan that will cause incorrect behavior, test failures, or unsafe runtime conditions if implemented as written. Three are blocking risks (marked CRITICAL), two are significant gaps (marked HIGH), and two are lower-priority design questions (marked MEDIUM). None are fatal to the approach — all are fixable before implementation begins.

---

## Finding 1: EventBus Sync Dispatch Blocks the Async Event Loop (CRITICAL)

### What the plan says

PLAN.md Task 1.2 defines `EventBus.emit()` as synchronous dispatch:

> Synchronous, in-process dispatch (no async overhead for event delivery)
> Subscribers are `Callable[[WorkflowEvent], None]` (sync) or `Callable[[WorkflowEvent], Awaitable[None]]` (async)

BACKUP-STRATEGY.md section "Files Requiring Special Care" also states:

> The hooks are fire-and-forget (no `await` of the event store in the hot path; use `asyncio.ensure_future()` to avoid blocking the agent loop).

### The defect

The plan allows async subscribers but uses a synchronous `emit()` signature. There is no mechanism in a synchronous function to await a coroutine. The plan does not explain how `emit()` handles an async subscriber. There are two possible implementations, both of which create serious problems:

**Option A: `emit()` calls `asyncio.ensure_future(callback(event))`**

This schedules the coroutine as a background task on the running event loop. The subscriber (i.e., `EventStore.append()`) runs after the current `await` yields. This means:
- Events are persisted asynchronously and out of order relative to when they were emitted. Two events emitted in sequence are not guaranteed to be persisted in that sequence.
- If the workflow completes and returns before the background tasks finish, `ExecutionCompleted` may be written to the store before `NodeCompleted` events from the last node.
- `asyncio.ensure_future()` requires a running event loop. Calling it from within a synchronous function that is called from an async function works only as long as the outer context is always an asyncio context. `runner.run_sync()` uses `asyncio.run()`, which creates a new event loop — `ensure_future()` called before or after the loop is running will raise `RuntimeError: no running event loop`.

**Option B: `emit()` runs `asyncio.get_event_loop().run_until_complete(callback(event))`**

This is a blocking call from within an async context, which raises `RuntimeError: This event loop is already running`. This is the classic nested event loop problem.

**Option C: `emit()` skips awaiting and just calls async subscribers as if they were sync (missing the await)**

This creates a coroutine object that is never awaited. Python will issue a `RuntimeWarning: coroutine was never awaited`. The subscriber does nothing.

The BACKUP-STRATEGY.md recommendation (`asyncio.ensure_future()`) partially addresses this but introduces event ordering non-determinism and the no-running-loop risk.

### Root cause in the codebase

`CompiledGraph.run()` is `async`. `BaseAgent.run()` is `async`. Both are the proposed emission sites. `EventBus.emit()` would be called from within these async functions, so a running loop exists. However, the EventStore is async (`async def append()`). The correct pattern for fire-and-forget async work from async context is `asyncio.create_task()`, not `asyncio.ensure_future()` — `create_task()` requires a running loop (guaranteed in async context), schedules the task on the current loop, and is the idiomatic approach.

### Required fix

Define `EventBus.emit()` as `async`. This is a one-character change to the signature but has cascading effects: all emission sites in `compiled.py` and `agent.py` must `await event_bus.emit(event)`. The emission is not "synchronous" but it is "lightweight" — the overhead is a single coroutine frame, not a database write. The database write happens inside the async subscriber.

Alternatively, keep `emit()` synchronous but restrict subscribers to sync-only callables, and have the EventStore subscriber enqueue events into an `asyncio.Queue`. A separate background task drains the queue and persists events. This is architecturally cleaner for performance but adds the ordering complexity described in Finding 3.

The BACKUP-STRATEGY.md note about `asyncio.ensure_future()` in agent.py should be updated to `asyncio.create_task()` and the event_bus emission should be directly awaited in compiled.py.

---

## Finding 2: State Projection Cannot Reconstruct State — Missing Initial State Event (CRITICAL)

### What the plan says

PLAN.md defines `project_state()`:

```python
def project_state(
    events: list[WorkflowEvent],
    initial_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Rebuild current state from event sequence.
    Applies StateUpdated events in sequence order.
    If a CheckpointCreated event is found, starts from that snapshot.
    """
```

The function signature accepts `initial_state` as an optional parameter. The plan also defines `ExecutionStarted` which carries `initial_state: dict[str, Any]`.

### The defect

There are two sub-problems:

**Sub-problem A: `initial_state` in `project_state()` must come from somewhere.**

When `project_state()` is called during HITL resume (Task 2.4) or time-travel (Task 2.7), the caller must pass `initial_state`. But the only place that knows the initial state is the `ExecutionStarted` event in the event log. If `project_state()` is given a raw event list without an explicit `initial_state`, and no `CheckpointCreated` event exists, the function will project on top of `None` or `{}`, which is wrong for any state that has non-empty defaults.

Example: A state with `messages: list = []` and `count: int = 0` starts with those values. If `StateUpdated(field_updates={"count": 1})` is the first event, `project_state([state_updated_event])` would produce `{"count": 1}` — but the `messages` field would be missing entirely from the returned dict unless the function extracts the initial state from `ExecutionStarted` first.

**Sub-problem B: Pydantic reducer semantics are not reproducible from raw dicts.**

`apply_state_update()` uses reducers extracted from the `WorkflowState` subclass. The projection function operates on `dict[str, Any]`, not on a `WorkflowState` instance. This means reducers are bypassed during projection. Consider `messages: Annotated[list[Message], merge_list]`: during live execution, `StateUpdated(field_updates={"messages": [new_msg]})` causes `merge_list(existing_messages, [new_msg])` to run, appending to the list. During projection, if `project_state()` simply does `state[field] = new_value`, it replaces the list rather than appending.

The projection will produce a different state than the live execution produced. Time-travel and HITL resume will resume from wrong state.

### Correct implementation requirement

`project_state()` must:
1. Scan the event list for `ExecutionStarted` first and use its `initial_state` as the base. The `initial_state` parameter should be a fallback, not the primary source.
2. Accept an optional `state_class: type[WorkflowState] | None` parameter. When provided, apply reducers during projection by calling `apply_state_update()` instead of naive dict assignment.
3. Handle the `CheckpointCreated` optimization: find the latest checkpoint in the event list, start from its `state_snapshot`, then replay only events after `checkpoint.event_sequence`.

Without item 2, projection correctness is broken for any workflow using `merge_list`, `sum_numbers`, `merge_dict`, or any other non-last-write-wins reducer.

---

## Finding 3: Parallel Node Event Ordering — Sequence Numbers Are Racy (CRITICAL)

### What the plan says

PLAN.md Task 1.2 defines:

```python
def next_sequence(self, run_id: str) -> int:
    """Get next monotonic sequence number for a run."""
    ...
```

`_sequence_counters` is a `dict[str, int]` on the EventBus. The plan requires: "Event ordering is guaranteed (monotonic sequence numbers per workflow)."

BACKUP-STRATEGY.md notes that `PRAGMA busy_timeout = 5000` handles concurrent SQLite writes.

### The defect

`CompiledGraph._execute_parallel()` calls `asyncio.gather(*tasks)`. Each task is `_execute_node()`, which will call `event_bus.emit()`. If `emit()` is synchronous (or even `async` with `create_task()`), the sequence number is assigned at emit time, not at persistence time.

The race condition:

```
Task A (node_branch_1) calls next_sequence() -> gets sequence=5
Task B (node_branch_2) calls next_sequence() -> gets sequence=6
Task B persists sequence=6 BEFORE Task A persists sequence=5
```

The sequence counter increment is not atomic with the persistence write. Within a single asyncio event loop (single-threaded), `next_sequence()` itself is safe from data races — only one coroutine runs at a time between `await` points. But the gap between `next_sequence()` call and `EventStore.append()` call spans at least one `await` (the persistence write itself). In that gap, another task can call `next_sequence()`.

The result: events arrive at the store with sequence numbers that do not reflect actual persistence order. `project_state()` sorting by `sequence` will replay events in the wrong interleaving order.

Specific case: two parallel nodes both emit `StateUpdated` events. Node B's `StateUpdated(count=10)` arrives at the store with sequence=6, but Node A's `StateUpdated(count=5)` arrives with sequence=5. If Node B actually finished first, the projection will compute the wrong final `count` because it replays sequence=5 (count=5) after sequence=6 (count=10) — which is backward relative to actual execution order.

### Severity

This is CRITICAL for time-travel correctness and HITL resume correctness. It is acceptable to tolerate approximate ordering for observability (Rich trace) but not for state reconstruction.

### Required fix

The sequence number must be assigned inside the EventStore.append() implementation under a database-level lock, not in the EventBus. For SQLite, this means:

```sql
INSERT INTO events (...) VALUES (...);
-- sequence is auto-assigned by the DB as autoincrement
```

The `sequence` field on the event should be nullable/0 at emit time and filled by the store on write. Or: events are sorted by `timestamp` for projection, with sequence as a tiebreaker only for events within the same millisecond. The PLAN.md approach of assigning sequence in-process is insufficient for parallel execution.

---

## Finding 4: ESAA Boundary Contracts Are Applied to the Wrong Object (HIGH)

### What the plan says

ROADMAP.md:

> Following the ESAA pattern (arXiv:2602.23193), agent outputs must be validated against JSON Schema before events are persisted -- cleanly separating probabilistic LLM cognition from deterministic state mutation.

PLAN.md Task 1.4:

> Implement boundary contract validation: agent outputs are validated against JSON Schema before events are persisted. Invalid outputs produce `OutputRejected` events instead of corrupting the event log.
> `contract.validate(output: dict[str, Any]) -> list[str]`

### The defect

`BaseAgent.run()` returns an `AgentResult` (a Pydantic `BaseModel`). By the time a `NodeCompleted` or `StateUpdated` event is emitted, the `AgentResult` has already been:
1. Pydantic-validated (by the `AgentResult` model itself on construction)
2. Processed through the 3-layer merge strategy in `_execute_agent_node()`
3. Converted to a `dict[str, Any]` state update

What reaches the event emission point is already a sanitized dict of state field updates, not the raw LLM text output. Validating a dict like `{"count": 1, "messages": [...]}` against a JSON Schema that was designed to validate LLM output structure is category confusion.

The ESAA paper validates the agent's JSON output (the structured `agent.result` blob before it is merged into state). The correct validation point is inside `BaseAgent.run()` — specifically, at the point where `self.output_type.model_validate_json(output_text)` is called. If the LLM output fails to parse as the expected structure, that is where `OutputRejected` should be emitted.

For agents without `output_type`, there is no structured schema to validate — the output is free-form text. Applying JSON Schema to free-form text output is undefined.

### Practical consequence

As designed, the `ContractRegistry.validate()` call in the event emission path would validate state update dicts, not LLM outputs. Most state dicts will pass any reasonable schema because they contain merged state fields, not agent cognition outputs. The validation would be a no-op in practice and would not catch the actual failure mode the ESAA pattern is designed to prevent (LLM generating invalid structured output).

### Required fix

Move boundary contract validation into `BaseAgent.run()`, specifically after `output_type.model_validate_json(output_text)`. The contract validates `output_text` (the raw LLM JSON string) against the schema before it is parsed into a Pydantic model. If validation fails, emit `OutputRejected` and do not merge the output into state. This is what ESAA actually specifies.

The `BoundaryContract.from_pydantic(model)` constructor correctly derives the JSON Schema from the Pydantic model class. The validation point is wrong, not the contract mechanism itself.

---

## Finding 5: MessagePack Has No Concrete Downstream Consumer (MEDIUM)

### What the plan says

PLAN.md Task 1.3 and ROADMAP.md success criteria both require MessagePack serialization alongside JSON. MessagePack is listed as an optional dependency under a `storage` extra.

### The analysis

No downstream task in the Phase 2 plan (Tasks 2.2 through 2.11) requires MessagePack. The SQLite backend (Task 2.2) stores events as JSON in a `TEXT` column — SQLite's JSON functions work on text, not binary blobs. The PostgreSQL backend (Task 2.3) uses JSONB columns, not binary columns. The Rich trace renderer (Task 2.6) consumes `WorkflowEvent` objects directly from the EventBus, not serialized bytes. Time-travel (Task 2.7) reads from the EventStore via `get_events()`, which returns `WorkflowEvent` objects.

There is no identified consumer that needs binary serialization. The performance argument for MessagePack (smaller payloads, faster deserialization) applies primarily to network transmission or high-frequency IPC — neither of which occurs in Phase 2's local-first architecture.

The risk of including MessagePack now:
- Adds a dependency (`msgpack`) that must be maintained and kept in sync with the event schema as it evolves.
- The MessagePack serialization code must be tested alongside JSON, doubling test surface for serialization round-trips.
- If the event schema later diverges in how MessagePack vs JSON handles certain types (e.g., binary vs string encoding of UUIDs, float precision), subtle bugs appear only in the MessagePack path.

### Recommendation

Defer MessagePack to a future task when a concrete consumer is identified (e.g., a Redis pub/sub integration, or a high-throughput streaming scenario). For Task 2.1, implement JSON serialization only. The `serialization.py` module should have a clean internal abstraction (`Serializer` Protocol) so a MessagePack implementation can be added later without touching the EventStore.

If the roadmap success criterion "Events serialize to JSON and MessagePack" is hard, note that it was set before the Phase 2 architecture was fully specified, and the PLAN.md correctly lists MessagePack under an optional `storage` extra — meaning it is already acknowledged as not-required-by-default.

---

## Finding 6: Missing Events for Downstream Tasks (HIGH)

### Gap analysis

Several downstream tasks depend on events that are not defined in Task 2.1 but need to be designed now because event schema changes after the store is deployed are expensive (see BACKUP-STRATEGY.md Section 6).

**Missing for Task 2.5 (Time Travel):**

Time-travel replay must suppress tool side-effects and return cached results. This requires `ToolCalled` events to store the complete tool result so replay can return it without re-executing the tool. The current `ToolCalled` event definition stores `result: str`, which covers simple string results. However, tool results from MCP tools (Task 2.8) may be structured data. The `result: str` field should be `result: Any` with a note that it must be JSON-serializable. If the field is `str` only, time-travel for MCP tool results will be lossy.

**Missing for Task 2.4 (HITL):**

The plan defines `InterruptRequested` and `InterruptResumed`. These are correct. However, there is no `WorkflowPaused` event that records the `run_id` -> paused state mapping for persistent resume after process restart. `InterruptRequested` captures the interrupt but not the durable "this run is waiting for human input" state that the CLI needs to list paused runs. Consider adding a `RunStatus` field to `ExecutionStarted` or a separate `WorkflowStatusChanged` event.

**Missing for Task 2.6 (Rich Trace):**

The Rich trace needs to display per-node duration and per-LLM-call cost inline. `NodeCompleted` has `duration_ms` and `LLMCalled` has `cost_usd` — these are correct. However, `NodeStarted` does not carry a `start_timestamp_monotonic` field. The trace renderer needs to compute elapsed time for in-progress nodes (spinners). If `NodeStarted` only has `timestamp: float` (which the plan uses for `time.monotonic()`), this is actually fine — but the plan's comment says `timestamp: float` is `time.monotonic()` while `timestamp_iso: str` is ISO 8601. The two clocks are different: `time.monotonic()` cannot be correlated to wall clock time from a different process. If events are read back from the store (not from the live event bus), the monotonic timestamps will be meaningless. The duration fields on `NodeCompleted` and `LLMCalled` mitigate this but the base `WorkflowEvent` design is inconsistent.

**Fix:** Replace `timestamp: float` (monotonic) with a single `timestamp: datetime` (wall clock, UTC, timezone-aware). Compute durations at emit time using `time.monotonic()` internally but do not persist monotonic clocks. The `timestamp_iso: str` field is then redundant — `datetime` serializes to ISO 8601 natively via Pydantic.

**Missing for Task 2.3 (PostgreSQL):**

The EventStore Protocol's `list_runs()` returns `list[dict[str, Any]]`. The shape of this dict is unspecified. Task 2.3 will implement `list_runs()` for PostgreSQL; Task 2.2 implements it for SQLite. If the dict shape differs between backends (e.g., SQLite returns `{"run_id": ..., "status": ...}` but PostgreSQL returns `{"id": ..., "run_status": ...}`), the CLI commands in Task 2.4+ will be broken on one backend. Define a `RunSummary` typed dict or dataclass in Task 2.1 and make `list_runs()` return `list[RunSummary]`.

---

## Finding 7: Backwards Compatibility — `if self._event_emitter` Guard Is Inconsistent with the Plan (MEDIUM)

### What the plan says

BACKUP-STRATEGY.md Tier 2 instrumentation:

> `compiled.py` — emit NodeStarted/NodeCompleted around `_execute_node` — Hook calls wrapped in `if self._event_emitter` guard

PLAN.md Task 1.2:

> Add `EventBus` field to `ExecutionContext`

### The inconsistency

BACKUP-STRATEGY.md guards on `self._event_emitter` (a field on `CompiledGraph`). PLAN.md attaches the `EventBus` to `ExecutionContext`. These are different objects.

`CompiledGraph.__init__()` currently has no `_event_emitter` field. `ExecutionContext` would have `event_bus: EventBus | None = None`. The guard in compiled.py would need to be `if context.event_bus` — not `if self._event_emitter`.

This matters because `CompiledGraph` is a compiled, reusable object (it persists across multiple `run()` calls). `ExecutionContext` is per-run. If the EventBus is on `ExecutionContext`, different runs of the same compiled graph can have different event buses (e.g., one run persists, another run is in-memory). This is the correct design. If the EventBus is on `CompiledGraph`, all runs share the same bus — which means parallel workflow execution would interleave events incorrectly.

### Required fix

The guard must be `if context.event_bus` everywhere in `compiled.py` and `agent.py`. Remove any reference to `self._event_emitter` from BACKUP-STRATEGY.md guidance. The EventBus belongs on `ExecutionContext`, not on `CompiledGraph`.

Additionally, `ExecutionContext` is currently a `@dataclass`. PLAN.md says to add `event_bus: EventBus | None = None`. This is straightforward and backward compatible because the field has a default. However, `ExecutionContext` uses `from __future__ import annotations`, so the `EventBus` type import must be a forward reference or use `TYPE_CHECKING` guard to avoid a circular import (`context.py` → `storage/store.py` → `storage/events.py` → potentially `core/types.py`). Verify the import chain before adding the field.

---

## Finding 8: Schema Evolution — `schema_version` on Frozen Dataclass Is Correct but Incomplete (MEDIUM)

### What the plan says

BACKUP-STRATEGY.md Section 6 defines `schema_version: int` on `WorkflowEvent`. The upgrade function pattern is correct.

### The gap

The plan defines `schema_version` at the base class level. Subclasses (e.g., `LLMCalled`) inherit the field. When `LLMCalled` changes its schema, the `schema_version` on the event should change. But the base class and all sibling classes share the same `schema_version` attribute — there is no per-type version.

If `LLMCalled` changes from schema_version=1 to schema_version=2, but `NodeCompleted` is still at version 1, an `LLMCalled` event with `schema_version=2` and a `NodeCompleted` event with `schema_version=1` both read as "version 1" for a reader that checks `event.schema_version` without also checking `event_type`. The upgrade lookup key `(event_type, schema_version)` in BACKUP-STRATEGY.md is correct — it uses both event type and version. This is fine, but the code must enforce that `schema_version` is per-type, not per-event instance. The current base class design allows any event to carry any `schema_version` — nothing enforces that `NodeCompleted` always has version 1 when `LLMCalled` is at version 2.

**Minor but real risk:** If the `schema_version` is accidentally passed through in a copy (e.g., an upgrade function copies a field from an old event and forgets to set `schema_version=2`), the upgraded event will still claim to be version 1 and the upgrade function will re-run on it. The upgrade lookup must check `event_type + schema_version` and apply the upgrade in-place, then verify the output has the target schema_version set. Document this invariant explicitly in `serialization.py`.

---

## Summary Table

| # | Finding | Severity | Affects | Fix Required Before Implementation |
|---|---------|----------|---------|-----------------------------------|
| 1 | EventBus.emit() sync/async mismatch blocks event loop or creates ordering bugs | CRITICAL | compiled.py, agent.py, store.py | Yes — change emit() to async or adopt queue pattern |
| 2 | project_state() cannot reconstruct reducer-computed state; missing initial state source | CRITICAL | store.py (projection) | Yes — projection must use ExecutionStarted event + state_class |
| 3 | Parallel node sequence numbers are racy; projection order is non-deterministic | CRITICAL | store.py, serialization.py, SQLite schema | Yes — assign sequence in DB, not EventBus |
| 4 | ESAA boundary validation applied to state update dicts, not LLM outputs | HIGH | contracts.py, agent.py | Yes — move validation inside BaseAgent.run() |
| 5 | MessagePack has no downstream consumer in Phase 2 | MEDIUM | serialization.py, pyproject.toml | No — defer, but add Serializer Protocol for future |
| 6 | Missing events for downstream tasks (tool result type, RunSummary, monotonic timestamp) | HIGH | events.py, store.py | Yes — fix event schema before SQLite backend starts |
| 7 | Guard inconsistency: self._event_emitter vs context.event_bus; circular import risk | MEDIUM | compiled.py, context.py | Yes — resolve before wiring |
| 8 | Schema_version not enforced per-type; upgrade function re-run risk | MEDIUM | serialization.py | Document and add assertion |

---

## Recommended Pre-Implementation Actions (Ordered by Priority)

### Before writing any Task 2.1 code:

1. **Resolve Finding 1 (async emit):** Choose one of two architectures:
   - **Architecture A (simpler):** `EventBus.emit()` is `async def`. Emission sites `await event_bus.emit(event)`. EventStore.append() is directly awaited inside the subscriber. Event ordering is serialized naturally.
   - **Architecture B (higher throughput):** `EventBus.emit()` is synchronous. Subscribers enqueue into `asyncio.Queue`. A background task drains the queue and calls `EventStore.append()`. Ordering within the queue is preserved. This adds complexity but avoids blocking the agent loop on each persistence write.
   Document the chosen architecture before implementation.

2. **Fix Finding 2 (projection):** Update `project_state()` signature to `project_state(events: list[WorkflowEvent], state_class: type[WorkflowState] | None = None) -> dict[str, Any]`. Extract `initial_state` from the `ExecutionStarted` event in the list. Apply `apply_state_update()` with the `state_class`'s reducers for each `StateUpdated` event.

3. **Fix Finding 3 (sequence numbers):** Remove `_sequence_counters` from EventBus. Assign sequence numbers in the EventStore backend (autoincrement in SQLite, sequence table in PostgreSQL). The `sequence` field on `WorkflowEvent` can be `0` at creation and filled by the store, or set to a local monotonic counter only for display ordering (not for projection correctness — use DB timestamp for projection ordering).

4. **Fix Finding 6 (event schema):** Before Task 2.2 (SQLite) begins, finalize the event schema:
   - Replace `timestamp: float` + `timestamp_iso: str` with a single `timestamp: datetime` (UTC-aware).
   - Change `ToolCalled.result` from `str` to `Any` (JSON-serializable).
   - Add `RunSummary` typed dataclass for `list_runs()` return type.
   - Keep `InterruptRequested`/`InterruptResumed` as-is.

5. **Fix Finding 4 (ESAA placement):** Move `ContractRegistry.validate()` call to inside `BaseAgent.run()`, after the LLM returns output, before `model_validate_json()`. Remove the contract validation from the event emission path.

6. **Fix Finding 7 (guard pattern):** Change all BACKUP-STRATEGY.md references from `self._event_emitter` to `context.event_bus`. Verify import chain for `EventBus` in `context.py` using `TYPE_CHECKING`.

---

## Regression Risk Assessment

The instrumentation changes to Phase 1 files are low-risk when guarded correctly:

- `context.py`: Adding `event_bus: EventBus | None = None` is additive. All existing tests pass `ExecutionContext()` without the field, which defaults to `None`. Zero regression risk.
- `compiled.py`: Guards on `if context.event_bus:` ensure the hook code is dead when no bus is configured. The existing test suite in `tests/unit/test_core.py` creates `ExecutionContext` without `event_bus`, so all hooks will be skipped. Zero regression risk if guards are correct.
- `agent.py`: Same guard pattern. Zero regression risk.
- `runner.py`: New keyword-only parameters with defaults. No regression risk.
- `errors.py`: Adding `PersistenceError` hierarchy. Additive, zero regression risk.

The one regression vector to watch: if `asyncio.create_task()` or `asyncio.ensure_future()` is used in compiled.py for fire-and-forget event emission, and a test runs the graph through `asyncio.run()`, the background task may not complete before `asyncio.run()` returns. This will cause `asyncio.run()` to log warnings about "Task was destroyed but it is pending!" — these are not test failures but they will pollute test output and may indicate events that were not persisted. Use `asyncio.shield()` or drain outstanding tasks before returning from `run()`.

---

## References

- asyncio event loop blocking pitfalls: [BBC CloudFit asyncio Part 5](https://bbc.github.io/cloudfit-public-docs/asyncio/asyncio-part-5.html), [Medium: Event Loop Blocking Explained](https://medium.com/@virtualik/python-asyncio-event-loop-blocking-explained-with-code-examples-0b2bba801426)
- asyncio.gather nondeterministic ordering: [GitHub asyncio issue #432](https://github.com/python/asyncio/issues/432), [SuperFastPython asyncio.gather](https://superfastpython.com/asyncio-gather/)
- Event sourcing state projection: [Deriving state from events — DEV Community](https://dev.to/jakub_zalas/deriving-state-from-events-1plj), [Event Sourcing Projections — Domain Centric](https://domaincentric.net/blog/event-sourcing-projections)
- ESAA paper: [arXiv:2602.23193](https://arxiv.org/abs/2602.23193)
- MessagePack vs JSON: [SitePoint comparison](https://www.sitepoint.com/data-serialization-comparison-json-yaml-bson-messagepack/), [Medium: When native JSON beat binary](https://smali-kazmi.medium.com/when-optimized-is-slower-why-we-stuck-with-native-json-for-our-10mb-context-object-2d7dd62e6982)
- Pydantic frozen dataclass serialization pitfalls: [Pydantic issue #4719](https://github.com/pydantic/pydantic/issues/4719), [Pydantic issue #2541](https://github.com/pydantic/pydantic/issues/2541)
- Optimistic concurrency in event sourcing: [SoftwareMill: Things I wish I knew — consistency](https://softwaremill.com/things-i-wish-i-knew-when-i-started-with-event-sourcing-part-2-consistency/)

---

*Audit complete. No implementation has been reviewed — this is a plan-level audit. Re-audit after Task 2.1 implementation is complete and before Task 2.2 begins.*
