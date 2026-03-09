# Task 2.1: Event-Sourced Persistence Layer -- Detailed Execution Plan

**Phase:** 02-differentiation
**Task:** 2.1 (DIFF-01)
**Created:** 2026-03-08
**Status:** Ready for execution
**Estimated effort:** 5 subtasks across 3 waves

---

## Table of Contents

1. [Code Walkthrough and Event Emission Points](#1-code-walkthrough-and-event-emission-points)
2. [Logic Errors and Design Gaps](#2-logic-errors-and-design-gaps)
3. [Resolved Design Decisions](#3-resolved-design-decisions)
4. [Subtask Breakdown](#4-subtask-breakdown)
5. [Dependency Graph](#5-dependency-graph)
6. [File Inventory](#6-file-inventory)
7. [Testing Strategy](#7-testing-strategy)

---

## 1. Code Walkthrough and Event Emission Points

### 1.1 CompiledGraph.run() -- Line-by-Line Event Map

```
Location: src/orchestra/core/compiled.py, class CompiledGraph, method run()

Line 84-86: Resolve initial state
  -> No event here (pre-execution setup)

Line 88-94: Create or reuse ExecutionContext
  -> EVENT: ExecutionStarted (after context is ready, before entering loop)
     Fields: workflow_name=self._name, initial_state=raw_state,
             entry_point=self._entry_point, run_id=context.run_id

Line 97-102: Normalize state to WorkflowState
  -> No event (internal type coercion)

Line 107-108: while loop entry (current_node_id != END and turns < max_turns)
  -> No event (loop mechanics)

Line 113-118: node lookup, raise GraphCompileError if not found
  -> NodeStarted BEFORE _execute_node call (line 126)
     Fields: node_id, node_type=(AgentNode|FunctionNode|SubgraphNode),
             input_state=state_dict

Line 126: update = await self._execute_node(...)
  -> NodeCompleted AFTER _execute_node returns successfully
     Fields: node_id, node_type, output_update=update, duration_ms
  -> NodeFailed if _execute_node raises
     Fields: node_id, error_type, error_message

Line 130-134: Apply state update (reducer path)
  -> StateUpdated AFTER apply_state_update succeeds
     Fields: node_id, field_updates=update, state_version=turns

Line 138-140: _resolve_next (determine next node)
  -> No standalone event (edge traversal is implicit in next NodeStarted)

Line 142-148: MaxIterationsError
  -> ExecutionFailed
     Fields: error_type="MaxIterationsError", error_message, node_id=current_node_id

Line 150: return final state
  -> ExecutionCompleted (AFTER the while loop, BEFORE return)
     Fields: final_state, duration_ms, total_tokens, total_cost_usd
```

### 1.2 CompiledGraph._execute_parallel() -- Event Points

```
Location: src/orchestra/core/compiled.py, _execute_parallel()

Line 311-315: Create tasks for parallel targets
  -> NodeStarted for EACH parallel target (before asyncio.gather)

Line 318: results = await asyncio.gather(*tasks, return_exceptions=True)
  -> NodeCompleted/NodeFailed for each target (inside _execute_node, not here)

Line 320-325: Check for errors
  -> No separate event (errors bubble up as NodeFailed from _execute_node)

Line 329-335: Merge parallel updates
  -> StateUpdated with merged result (after merge_parallel_updates)
```

### 1.3 BaseAgent.run() -- Line-by-Line Event Map

```
Location: src/orchestra/core/agent.py, class BaseAgent, method run()

Line 67-73: Get LLM provider, raise if missing
  -> No event (pre-execution validation)

Line 76-83: Build messages (system prompt + user input)
  -> No event (message construction)

Line 90: for _iteration in range(self.max_iterations):
  -> Loop entry, no event

Line 91-97: response = await llm.complete(...)
  -> LLMCalled AFTER llm.complete returns
     Fields: node_id=context.node_id, agent_name=self.name,
             model=self.model, input_tokens, output_tokens, cost_usd,
             duration_ms, finish_reason=response.finish_reason
     NOTE: Must capture timing (time.monotonic() before/after call)
     NOTE: Must extract token counts from response.usage

Line 106-107: response.tool_calls detected
  -> No separate event here (tool calls handled below)

Line 116-131: for tool_call in response.tool_calls: execute tool
  -> ToolCalled AFTER each tool.execute() returns
     Fields: node_id=context.node_id, agent_name=self.name,
             tool_name=tool_call.name, arguments=tool_call.arguments,
             result=tool_result.content, error=tool_result.error,
             duration_ms (must capture timing around tool.execute())

Line 136-163: No tool calls -> final response
  -> No separate event (LLMCalled already emitted for this call)

Line 143-154: Structured output validation
  -> OutputValidated if validation succeeds (when output_type is set)
  -> OutputRejected if validation fails (when output_type is set)
     NOTE: This is the ESAA boundary contract application point

Line 165-168: MaxIterationsError
  -> This surfaces as NodeFailed at CompiledGraph level
```

### 1.4 runner.run() -- Event Points

```
Location: src/orchestra/core/runner.py, function run()

Line 74-79: Create context
  -> EventBus should be initialized here and attached to context
  -> EventStore (if configured) should be subscribed to EventBus

Line 82-87: compiled.run() call
  -> Events flow through EventBus during execution
  -> ExecutionStarted/ExecutionCompleted handled by CompiledGraph.run()

Line 91-102: Build and return RunResult
  -> No separate event (RunResult is the return value, not an event)
```

---

## 2. Logic Errors and Design Gaps

### GAP 1: EventBus sync dispatch vs. async execution engine (CRITICAL)

**The problem:** The existing PLAN.md (Task 1.2) specifies the EventBus as "synchronous, in-process dispatch." But `CompiledGraph.run()` and `BaseAgent.run()` are fully async. The EventBus's `emit()` method is called from async code. If subscribers include the `InMemoryEventStore` (whose methods are `async def`), the sync `emit()` cannot call `await store.append(event)`.

**Three subscriber categories:**
1. **InMemoryEventStore** -- `async def append()` (async)
2. **Rich TraceRenderer** (future, Plan 04) -- sync (just updates a Rich Live display)
3. **SQLiteEventStore** (future, Plan 04) -- `async def` (writes to aiosqlite)

**Resolution:** The EventBus must support BOTH sync and async subscribers. Implementation:

```python
def emit(self, event: WorkflowEvent) -> None:
    """Dispatch event. Sync subscribers called directly.
    Async subscribers scheduled on the running event loop."""
    for callback in matching_subscribers:
        result = callback(event)
        if inspect.isawaitable(result):
            # We are already inside an async context (CompiledGraph.run)
            # Schedule the coroutine as a task -- fire-and-forget
            # BUT: for event ordering guarantees, we need to await it
            asyncio.get_running_loop().create_task(result)
```

**BUT** `create_task` is fire-and-forget, breaking event ordering guarantees. The correct approach:

```python
async def emit(self, event: WorkflowEvent) -> None:
    """Async dispatch. Awaits async subscribers, calls sync subscribers directly."""
    for callback in matching_subscribers:
        result = callback(event)
        if inspect.isawaitable(result):
            await result
```

**Decision: Make `emit()` async.** This is the cleanest solution because:
- All callers (`CompiledGraph.run()`, `BaseAgent.run()`) are already async
- Preserves event ordering (await ensures subscriber finishes before next event)
- No fire-and-forget race conditions
- Sync subscribers still work (their return value is `None`, not awaitable)

The guarded emission pattern in `CompiledGraph` becomes:
```python
if context.event_bus:
    await context.event_bus.emit(NodeStarted(...))
```

### GAP 2: State projection with Pydantic WorkflowState + reducers (MEDIUM)

**The problem:** `project_state()` needs to rebuild `WorkflowState` from `StateUpdated` events. But `StateUpdated.field_updates` is a `dict[str, Any]`. To use `apply_state_update()`, we need:
1. The `WorkflowState` subclass (to call `model_validate`)
2. The reducers extracted from the schema

**But `project_state()` doesn't know the state schema.** Events are schema-agnostic.

**Resolution:** `project_state()` must accept the `state_schema` and `reducers` as parameters:

```python
def project_state(
    events: list[WorkflowEvent],
    state_schema: type[WorkflowState] | None = None,
    reducers: dict[str, Any] | None = None,
    initial_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
```

If `state_schema` is provided, it uses `apply_state_update()` with reducers. Otherwise, it does plain dict merging (for untyped workflows). This preserves backward compatibility.

### GAP 3: Missing events in existing PLAN.md event hierarchy

The existing plan defines 16 event types. After walking the code, these gaps exist:

**3a. No `EdgeTraversed` event.** The RESEARCH-notebooklm-synthesis suggests it (Section 1, "Agent Domain Events"). It's useful for time-travel debugging (seeing which edges were taken). However, for Task 2.1 scope, this is NOT blocking. Edge traversal is implicit in NodeStarted sequences. Defer to Task 2.5 (time-travel) if needed.

**3b. Parallel execution events.** When `_execute_parallel()` runs, individual nodes get NodeStarted/NodeCompleted. But there's no event marking the fan-out/fan-in boundary. For Task 2.1, this is acceptable -- the parallel nodes' events are individually tracked. A `ParallelFanOut` / `ParallelFanIn` event pair could be added later for richer tracing.

**3c. `OutputValidated` / `OutputRejected` placement.** The existing plan puts these in the event hierarchy but doesn't specify WHERE in `BaseAgent.run()` they get emitted. The validation happens at line 143-154 of agent.py (structured output validation). This is the natural emission point.

**3d. Handoff and Interrupt events are forward-looking.** `HandoffInitiated`, `HandoffCompleted`, `InterruptRequested`, `InterruptResumed` are defined but not emitted in Task 2.1. They're placeholders for Plans 04 and 06. This is correct -- define the types now, emit later.

### GAP 4: InMemoryEventStore is sufficient for testing BUT needs async def methods

**The problem:** `EventStore` Protocol methods are `async def`. The `InMemoryEventStore` must also use `async def` even though it's in-memory. This is correct -- the Protocol mandates the async interface. Python's `async def` with no `await` inside is perfectly fine (returns immediately). No gap here.

### GAP 5: Frozen dataclass vs. Pydantic for events (DESIGN CONFLICT)

**The existing PLAN.md uses `@dataclass(frozen=True)` for events.** But the RESEARCH-events.md recommends Pydantic models with `model_config = ConfigDict(frozen=True)` and Pydantic discriminated unions for deserialization.

**The project convention is Pydantic for all data models** (from 02-CONTEXT.md: "Pydantic for all data models"). The existing codebase uses:
- Pydantic `BaseModel` for: `Message`, `ToolCall`, `AgentResult`, `LLMResponse`, `TokenUsage`, `RunResult`
- Frozen dataclasses for: `AgentNode`, `FunctionNode`, `Edge`, `ConditionalEdge`, `ParallelEdge`

The pattern is: **Pydantic for data that gets serialized, dataclasses for internal graph structures.**

Events WILL be serialized (to JSON for storage, potentially MessagePack). Therefore:

**Decision: Use Pydantic `BaseModel` with `frozen=True` for events**, not `@dataclass(frozen=True)`. This gives us:
- `model_dump()` / `model_dump_json()` for free
- `model_validate()` / `model_validate_json()` for deserialization
- Discriminated unions via `Literal` type discriminator field
- Consistent with all other serialized types in the codebase

This contradicts the existing PLAN.md which uses `@dataclass(frozen=True)`. The existing PLAN.md should be overridden on this point.

### GAP 6: Boundary contract validation friction assessment

**Question from requirements:** "Does ESAA boundary contract validation fit naturally or create friction?"

**Assessment: It creates MODERATE friction that must be carefully managed.**

**Where it fits naturally:**
- Agents with `output_type` already have a Pydantic model defining the expected shape. Creating a `BoundaryContract.from_pydantic(model)` is trivial.
- The validation point (after LLM response, before state update) is a clean insertion point.

**Where it creates friction:**
1. **Most agents don't have `output_type`** -- they return free-form text. Forcing a contract on every agent would break the simple case. Solution: contracts are opt-in. No contract = no validation = raw state update events pass through.
2. **Validation on every tool-loop iteration is wasteful.** Only the FINAL agent output should be validated against the contract, not intermediate tool-call responses. The validation point must be after the agent's final LLM response, not in the tool loop.
3. **ContractRegistry adds ceremony.** Users must register contracts per agent. Solution: auto-generate contracts from `output_type` when set. Manual registration only needed for custom schemas.

**Decision:** Contracts are:
- **Automatic** when agent has `output_type` (Pydantic model) -- no user action needed
- **Optional manual** registration via `ContractRegistry` for custom schemas
- **Skipped** when no contract exists (majority of simple agents)
- **Applied once** at final output, not per-iteration

### GAP 7: Event sequence numbers during parallel execution

**The problem:** In `_execute_parallel()`, multiple nodes execute concurrently via `asyncio.gather()`. If each node emits events, the sequence counter must be thread-safe (well, coroutine-safe).

**Assessment:** Python's GIL + single-threaded asyncio means `asyncio.gather()` tasks interleave at `await` points, not in the middle of sync code. The `EventBus.emit()` method assigns sequence numbers. Since `emit()` will be `async`, two concurrent tasks could call `emit()` and interleave. BUT: the sequence counter assignment (`self._sequence_counters[run_id] += 1`) is a single dict operation, atomic under the GIL.

**Resolution:** No explicit lock needed. The GIL guarantees atomicity of the counter increment. Document this in the code comments.

### GAP 8: Missing timing instrumentation in BaseAgent.run()

**The problem:** `BaseAgent.run()` does not capture `duration_ms` for LLM calls or tool executions. The `LLMCalled` and `ToolCalled` events require `duration_ms`. The agent code must be instrumented with `time.monotonic()` before/after each call.

**Resolution:** Add timing around:
1. `await llm.complete(...)` -- for `LLMCalled.duration_ms`
2. `await tool.execute(...)` -- for `ToolCalled.duration_ms`

This is an additive change to `agent.py` (adding `import time` and wrapping calls).

### GAP 9: ExecutionContext.event_bus type annotation

**The problem:** `ExecutionContext` is a plain `@dataclass`. Adding `event_bus: EventBus | None = None` creates a circular import: `context.py` would import from `storage/store.py`, and `storage/store.py` imports `WorkflowEvent` types. Context should not depend on the storage layer.

**Resolution:** Use `Any` type with a docstring, or use `TYPE_CHECKING` conditional import:

```python
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orchestra.storage.store import EventBus

@dataclass
class ExecutionContext:
    event_bus: EventBus | None = None  # works because of `from __future__ import annotations`
```

This avoids the circular import at runtime while providing type safety for static checkers.

---

## 3. Resolved Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Event base class | Pydantic `BaseModel(frozen=True)` | Project convention: Pydantic for serialized data. Gives `model_dump_json()` for free. |
| EventBus.emit() | `async def emit()` | All callers are async. Preserves ordering. Avoids fire-and-forget race conditions. |
| Discriminated union | `Literal` field discriminator | Native Pydantic pattern. No external registry needed for deserialization. |
| Sequence numbers | GIL-atomic counter in EventBus | Single-threaded asyncio. No explicit lock needed. |
| State projection | Schema-aware (accepts `state_schema` + `reducers`) | Required to correctly apply Annotated reducers during replay. |
| Contracts | Opt-in. Auto from `output_type`. Applied at final output only. | Avoids friction for simple agents. Validates where it matters. |
| context.event_bus | `TYPE_CHECKING` import to avoid circular dep | Clean dependency direction: core -> storage at type-check time only. |
| MessagePack | JSON-only for v1 per RESEARCH-events.md | < 1ms difference at Orchestra's scale. Human-readable. Defer msgpack. |

---

## 4. Subtask Breakdown

### Wave 1 (Independent, parallel-safe)

#### Subtask 2.1.1: Event Type Hierarchy + EventType Enum

**Files created:**
- `src/orchestra/storage/__init__.py`
- `src/orchestra/storage/events.py`

**Files modified:**
- `src/orchestra/core/errors.py` (add persistence error types)

**Function signatures:**

```python
# src/orchestra/storage/events.py

from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Literal
from enum import Enum
import time
import uuid

class EventType(str, Enum):
    """Discriminator enum for event serialization."""
    EXECUTION_STARTED = "execution.started"
    EXECUTION_COMPLETED = "execution.completed"
    EXECUTION_FAILED = "execution.failed"
    NODE_STARTED = "node.started"
    NODE_COMPLETED = "node.completed"
    NODE_FAILED = "node.failed"
    STATE_UPDATED = "state.updated"
    CHECKPOINT_CREATED = "checkpoint.created"
    LLM_CALLED = "llm.called"
    TOOL_CALLED = "tool.called"
    HANDOFF_INITIATED = "handoff.initiated"
    HANDOFF_COMPLETED = "handoff.completed"
    INTERRUPT_REQUESTED = "interrupt.requested"
    INTERRUPT_RESUMED = "interrupt.resumed"
    OUTPUT_VALIDATED = "output.validated"
    OUTPUT_REJECTED = "output.rejected"

class WorkflowEvent(BaseModel):
    """Base event. All events are immutable Pydantic models."""
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    run_id: str
    timestamp: float = Field(default_factory=time.monotonic)
    timestamp_iso: str = ""  # Set by EventBus at emission time
    sequence: int = 0        # Set by EventBus at emission time
    event_type: str          # Discriminator (subclasses set via Literal)

class ExecutionStarted(WorkflowEvent):
    event_type: Literal["execution.started"] = "execution.started"
    workflow_name: str
    initial_state: dict[str, Any]
    entry_point: str

class ExecutionCompleted(WorkflowEvent):
    event_type: Literal["execution.completed"] = "execution.completed"
    final_state: dict[str, Any]
    duration_ms: float
    total_tokens: int = 0
    total_cost_usd: float = 0.0

class ExecutionFailed(WorkflowEvent):
    event_type: Literal["execution.failed"] = "execution.failed"
    error_type: str
    error_message: str
    node_id: str | None = None

class NodeStarted(WorkflowEvent):
    event_type: Literal["node.started"] = "node.started"
    node_id: str
    node_type: str   # "agent", "function", "subgraph"
    input_state: dict[str, Any] = Field(default_factory=dict)

class NodeCompleted(WorkflowEvent):
    event_type: Literal["node.completed"] = "node.completed"
    node_id: str
    node_type: str
    output_update: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float = 0.0

class NodeFailed(WorkflowEvent):
    event_type: Literal["node.failed"] = "node.failed"
    node_id: str
    error_type: str
    error_message: str

class StateUpdated(WorkflowEvent):
    event_type: Literal["state.updated"] = "state.updated"
    node_id: str
    field_updates: dict[str, Any] = Field(default_factory=dict)
    state_version: int = 0

class CheckpointCreated(WorkflowEvent):
    event_type: Literal["checkpoint.created"] = "checkpoint.created"
    checkpoint_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    node_id: str = ""
    state_snapshot: dict[str, Any] = Field(default_factory=dict)
    event_sequence: int = 0

class LLMCalled(WorkflowEvent):
    event_type: Literal["llm.called"] = "llm.called"
    node_id: str
    agent_name: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: float = 0.0
    finish_reason: str = "stop"

class ToolCalled(WorkflowEvent):
    event_type: Literal["tool.called"] = "tool.called"
    node_id: str
    agent_name: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: str = ""
    error: str | None = None
    duration_ms: float = 0.0

class HandoffInitiated(WorkflowEvent):
    event_type: Literal["handoff.initiated"] = "handoff.initiated"
    from_agent: str
    to_agent: str
    reason: str = ""
    context_tokens: int = 0

class HandoffCompleted(WorkflowEvent):
    event_type: Literal["handoff.completed"] = "handoff.completed"
    from_agent: str
    to_agent: str

class InterruptRequested(WorkflowEvent):
    event_type: Literal["interrupt.requested"] = "interrupt.requested"
    node_id: str
    interrupt_type: str  # "before" or "after"

class InterruptResumed(WorkflowEvent):
    event_type: Literal["interrupt.resumed"] = "interrupt.resumed"
    node_id: str
    state_modifications: dict[str, Any] = Field(default_factory=dict)

class OutputValidated(WorkflowEvent):
    event_type: Literal["output.validated"] = "output.validated"
    node_id: str
    agent_name: str
    schema_name: str = ""

class OutputRejected(WorkflowEvent):
    event_type: Literal["output.rejected"] = "output.rejected"
    node_id: str
    agent_name: str
    schema_name: str = ""
    validation_errors: list[str] = Field(default_factory=list)
```

**Also add to `src/orchestra/storage/events.py`:**

```python
# Type registry for deserialization (event_type string -> class)
EVENT_TYPE_REGISTRY: dict[str, type[WorkflowEvent]] = {
    "execution.started": ExecutionStarted,
    "execution.completed": ExecutionCompleted,
    "execution.failed": ExecutionFailed,
    "node.started": NodeStarted,
    "node.completed": NodeCompleted,
    "node.failed": NodeFailed,
    "state.updated": StateUpdated,
    "checkpoint.created": CheckpointCreated,
    "llm.called": LLMCalled,
    "tool.called": ToolCalled,
    "handoff.initiated": HandoffInitiated,
    "handoff.completed": HandoffCompleted,
    "interrupt.requested": InterruptRequested,
    "interrupt.resumed": InterruptResumed,
    "output.validated": OutputValidated,
    "output.rejected": OutputRejected,
}
```

**Add to `src/orchestra/core/errors.py`:**

```python
# --- Persistence Errors ---

class PersistenceError(OrchestraError):
    """Base for storage/persistence errors."""

class EventStoreError(PersistenceError):
    """Raised when event store operations fail."""

class CheckpointError(PersistenceError):
    """Raised when checkpoint operations fail."""

class ContractValidationError(PersistenceError):
    """Raised when agent output fails boundary contract validation."""
```

**`src/orchestra/storage/__init__.py`:**

```python
"""Event-sourced persistence layer for Orchestra."""

from orchestra.storage.events import (
    CheckpointCreated,
    EventType,
    ExecutionCompleted,
    ExecutionFailed,
    ExecutionStarted,
    HandoffCompleted,
    HandoffInitiated,
    InterruptRequested,
    InterruptResumed,
    LLMCalled,
    NodeCompleted,
    NodeFailed,
    NodeStarted,
    OutputRejected,
    OutputValidated,
    StateUpdated,
    ToolCalled,
    WorkflowEvent,
)

__all__ = [
    "WorkflowEvent",
    "EventType",
    "ExecutionStarted",
    "ExecutionCompleted",
    "ExecutionFailed",
    "NodeStarted",
    "NodeCompleted",
    "NodeFailed",
    "StateUpdated",
    "CheckpointCreated",
    "LLMCalled",
    "ToolCalled",
    "HandoffInitiated",
    "HandoffCompleted",
    "InterruptRequested",
    "InterruptResumed",
    "OutputValidated",
    "OutputRejected",
]
```

**Verification:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -c "
from orchestra.storage.events import (
    WorkflowEvent, ExecutionStarted, ExecutionCompleted, ExecutionFailed,
    NodeStarted, NodeCompleted, NodeFailed, StateUpdated, CheckpointCreated,
    LLMCalled, ToolCalled, HandoffInitiated, HandoffCompleted,
    InterruptRequested, InterruptResumed, OutputValidated, OutputRejected,
    EventType, EVENT_TYPE_REGISTRY,
)
# Verify frozen
import pytest
e = ExecutionStarted(run_id='test', workflow_name='w', initial_state={}, entry_point='start')
try:
    e.run_id = 'changed'
    assert False, 'Should have raised'
except Exception:
    pass
# Verify 16 event types
assert len(EventType) == 16
assert len(EVENT_TYPE_REGISTRY) == 16
# Verify discriminator
assert e.event_type == 'execution.started'
print('All 16 event types OK, frozen, discriminated')
"
```

**Done:** 16 event types as frozen Pydantic models with Literal discriminators. EventType enum. EVENT_TYPE_REGISTRY for deserialization. Persistence error types added.

---

#### Subtask 2.1.2: EventBus + EventStore Protocol + InMemoryEventStore + State Projection

**Files created:**
- `src/orchestra/storage/store.py`

**Files modified:**
- `src/orchestra/core/context.py` (add `event_bus` field)

**Function signatures:**

```python
# src/orchestra/storage/store.py

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from orchestra.storage.events import (
    CheckpointCreated,
    EventType,
    StateUpdated,
    WorkflowEvent,
)


class EventBus:
    """In-process async event dispatcher.

    Dispatches events to subscribers. Supports both sync and async callbacks.
    Assigns monotonic sequence numbers per run_id.

    IMPORTANT: emit() is async because EventStore subscribers (SQLite, Postgres)
    are async. All callers in Orchestra (CompiledGraph.run, BaseAgent.run) are
    already async, so this is seamless.
    """

    def __init__(self) -> None:
        self._subscribers: dict[type[WorkflowEvent] | None, list[Callable]] = {}
        self._sequence_counters: dict[str, int] = {}

    def subscribe(
        self,
        callback: Callable[[WorkflowEvent], None] | Callable[[WorkflowEvent], Awaitable[None]],
        event_types: list[type[WorkflowEvent]] | None = None,
    ) -> None:
        """Register a subscriber.

        Args:
            callback: Sync or async callable receiving WorkflowEvent.
            event_types: List of event types to filter. None = all events.
        """
        if event_types is None:
            self._subscribers.setdefault(None, []).append(callback)
        else:
            for et in event_types:
                self._subscribers.setdefault(et, []).append(callback)

    def unsubscribe(
        self,
        callback: Callable,
        event_types: list[type[WorkflowEvent]] | None = None,
    ) -> None:
        """Remove a subscriber."""
        ...

    def next_sequence(self, run_id: str) -> int:
        """Get next monotonic sequence number for a run.

        Thread-safe under GIL for single-threaded asyncio.
        Parallel asyncio.gather() tasks interleave at await points,
        not during this sync operation.
        """
        current = self._sequence_counters.get(run_id, -1)
        next_val = current + 1
        self._sequence_counters[run_id] = next_val
        return next_val

    async def emit(self, event: WorkflowEvent) -> None:
        """Assign sequence number, timestamp, and dispatch to subscribers.

        Async to support EventStore subscribers that write to databases.
        Sync subscribers are called directly (their non-awaitable return is fine).
        """
        # Assign sequence and ISO timestamp
        # Note: Pydantic frozen model -- must create new instance with updated fields
        # Use model_copy(update={...}) for frozen models
        seq = self.next_sequence(event.run_id)
        updated = event.model_copy(update={
            "sequence": seq,
            "timestamp_iso": datetime.now(timezone.utc).isoformat(),
        })

        # Dispatch to type-specific subscribers
        event_type = type(updated)
        callbacks = list(self._subscribers.get(event_type, []))
        # Also dispatch to wildcard subscribers
        callbacks.extend(self._subscribers.get(None, []))

        for callback in callbacks:
            result = callback(updated)
            if inspect.isawaitable(result):
                await result


@runtime_checkable
class EventStore(Protocol):
    """Protocol for event persistence backends.

    Implementations: InMemoryEventStore (testing), SQLiteEventStore (default),
    PostgresEventStore (production).
    """

    async def append(self, event: WorkflowEvent) -> None:
        """Append an event. Must be idempotent on event_id."""
        ...

    async def get_events(
        self,
        run_id: str,
        after_sequence: int = 0,
        event_types: list[str] | None = None,
    ) -> list[WorkflowEvent]:
        """Get events for a run, optionally filtered by type and sequence."""
        ...

    async def get_latest_checkpoint(
        self, run_id: str
    ) -> CheckpointCreated | None:
        """Get the most recent checkpoint for a run."""
        ...

    async def save_checkpoint(
        self, run_id: str, checkpoint: CheckpointCreated
    ) -> None:
        """Save a state checkpoint."""
        ...

    async def list_runs(
        self, limit: int = 50, status: str | None = None
    ) -> list[dict[str, Any]]:
        """List workflow runs with metadata."""
        ...


class InMemoryEventStore:
    """Non-persistent event store for testing.

    Satisfies the EventStore protocol. Stores events in dicts keyed by run_id.
    All methods are async def (Protocol requirement) but execute synchronously.
    """

    def __init__(self) -> None:
        self._events: dict[str, list[WorkflowEvent]] = {}
        self._checkpoints: dict[str, list[CheckpointCreated]] = {}
        self._runs: dict[str, dict[str, Any]] = {}

    async def append(self, event: WorkflowEvent) -> None:
        """Append event. Idempotent: skip if event_id already stored."""
        ...

    async def get_events(
        self,
        run_id: str,
        after_sequence: int = 0,
        event_types: list[str] | None = None,
    ) -> list[WorkflowEvent]:
        """Return events filtered by sequence and optionally by type."""
        ...

    async def get_latest_checkpoint(
        self, run_id: str
    ) -> CheckpointCreated | None:
        """Return most recent checkpoint or None."""
        ...

    async def save_checkpoint(
        self, run_id: str, checkpoint: CheckpointCreated
    ) -> None:
        """Store checkpoint."""
        ...

    async def list_runs(
        self, limit: int = 50, status: str | None = None
    ) -> list[dict[str, Any]]:
        """List runs, newest first."""
        ...


def project_state(
    events: list[WorkflowEvent],
    state_schema: type | None = None,
    reducers: dict[str, Any] | None = None,
    initial_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Rebuild current state from an event sequence.

    Algorithm:
    1. Find latest CheckpointCreated event (if any) -- start from its snapshot
    2. Apply all StateUpdated events after the checkpoint in sequence order
    3. If state_schema provided, use apply_state_update() with reducers
    4. Otherwise, plain dict merge (last-write-wins per field)

    Args:
        events: Ordered event list (by sequence number).
        state_schema: Optional WorkflowState subclass for typed projection.
        reducers: Optional reducer functions (from extract_reducers).
        initial_state: Starting state if no checkpoint found.

    Returns:
        Reconstructed state as dict.
    """
    ...
```

**Modifications to `src/orchestra/core/context.py`:**

```python
# Add at top of file:
from __future__ import annotations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from orchestra.storage.store import EventBus

# Add field to ExecutionContext dataclass:
    # Event system (Phase 2)
    event_bus: EventBus | None = None
```

NOTE: `from __future__ import annotations` is already present in context.py. The `TYPE_CHECKING` import is the only addition needed.

**Verification:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -c "
from orchestra.storage.store import EventBus, EventStore, InMemoryEventStore, project_state
import asyncio

# Test EventBus
bus = EventBus()
received = []
bus.subscribe(lambda e: received.append(e))

# Test InMemoryEventStore satisfies Protocol
store = InMemoryEventStore()
assert isinstance(store, EventStore), 'InMemoryEventStore must satisfy EventStore Protocol'

# Test EventBus emit (async)
from orchestra.storage.events import NodeStarted
async def test():
    event = NodeStarted(run_id='test-run', node_id='a', node_type='function')
    await bus.emit(event)
    assert len(received) == 1
    assert received[0].sequence == 0
    assert received[0].timestamp_iso != ''

asyncio.run(test())

# Test project_state with empty list
result = project_state([], initial_state={'x': 1})
assert result == {'x': 1}

print('EventBus, EventStore, InMemoryEventStore, project_state: OK')
"
```

Also verify existing tests still pass:
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -m pytest tests/unit/test_core.py -x -q
```

**Done:** EventBus with async emit. EventStore Protocol. InMemoryEventStore. project_state with schema-aware replay. ExecutionContext gains event_bus field. All existing tests pass.

---

#### Subtask 2.1.3: Event Serialization (JSON)

**Files created:**
- `src/orchestra/storage/serialization.py`

**Function signatures:**

```python
# src/orchestra/storage/serialization.py

from typing import Any
from orchestra.storage.events import WorkflowEvent, EVENT_TYPE_REGISTRY

def event_to_dict(event: WorkflowEvent) -> dict[str, Any]:
    """Convert event to a plain dict with type discriminator.

    Uses Pydantic model_dump(). The event_type field acts as discriminator.
    """
    return event.model_dump()

def dict_to_event(data: dict[str, Any]) -> WorkflowEvent:
    """Reconstruct event from dict using event_type discriminator.

    Looks up event class from EVENT_TYPE_REGISTRY, then calls model_validate().
    Raises KeyError if event_type is unknown (forward compat: could also
    return a generic WorkflowEvent with extra fields).
    """
    event_type_str = data.get("event_type", "")
    event_class = EVENT_TYPE_REGISTRY.get(event_type_str)
    if event_class is None:
        raise ValueError(
            f"Unknown event type: '{event_type_str}'.\n"
            f"  Known types: {list(EVENT_TYPE_REGISTRY.keys())}"
        )
    return event_class.model_validate(data)

def event_to_json(event: WorkflowEvent) -> str:
    """Serialize event to JSON string.

    Uses Pydantic model_dump_json() for performance.
    """
    return event.model_dump_json()

def json_to_event(json_str: str) -> WorkflowEvent:
    """Deserialize event from JSON string.

    Two-step: parse JSON to dict, then use dict_to_event for type dispatch.
    """
    import json
    data = json.loads(json_str)
    return dict_to_event(data)
```

**MessagePack: DEFERRED to future version.** Per RESEARCH-events.md recommendation, JSON-only for v1. The performance difference (< 1ms) is negligible at Orchestra's event volume. MessagePack can be added later via `msgspec` if profiling shows need.

**Rationale for not adding msgpack dependency:**
- Keeps `pyproject.toml` dependencies minimal
- JSON is human-readable (critical for debugging)
- Pydantic's `model_dump_json()` is already optimized
- SQLite stores TEXT, PostgreSQL stores JSONB -- both native JSON

**Update `src/orchestra/storage/__init__.py`:** Add serialization exports:

```python
from orchestra.storage.serialization import (
    dict_to_event,
    event_to_dict,
    event_to_json,
    json_to_event,
)
```

**Verification:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -c "
from orchestra.storage.events import (
    ExecutionStarted, NodeCompleted, LLMCalled, ToolCalled,
    StateUpdated, CheckpointCreated, OutputRejected,
)
from orchestra.storage.serialization import event_to_json, json_to_event, event_to_dict, dict_to_event
import time, uuid

# Test round-trip for each event category
events = [
    ExecutionStarted(run_id='r1', workflow_name='test', initial_state={'x': 1}, entry_point='start'),
    NodeCompleted(run_id='r1', node_id='a', node_type='function', output_update={'y': 2}, duration_ms=100.5),
    LLMCalled(run_id='r1', node_id='a', agent_name='bot', model='gpt-4o', input_tokens=100, output_tokens=50, cost_usd=0.003, duration_ms=500.0, finish_reason='stop'),
    ToolCalled(run_id='r1', node_id='a', agent_name='bot', tool_name='search', arguments={'q': 'test'}, result='found', error=None, duration_ms=200.0),
    StateUpdated(run_id='r1', node_id='a', field_updates={'count': 1}, state_version=1),
    CheckpointCreated(run_id='r1', state_snapshot={'x': 1, 'count': 1}, event_sequence=5),
    OutputRejected(run_id='r1', node_id='a', agent_name='bot', schema_name='MyOutput', validation_errors=['score must be int']),
]

for event in events:
    # JSON round-trip
    json_str = event_to_json(event)
    restored = json_to_event(json_str)
    assert restored.event_type == event.event_type, f'Type mismatch: {restored.event_type} != {event.event_type}'
    assert restored.run_id == event.run_id

    # Dict round-trip
    d = event_to_dict(event)
    restored2 = dict_to_event(d)
    assert restored2.event_type == event.event_type

print(f'All {len(events)} event types round-trip OK (JSON + dict)')
"
```

**Done:** JSON serialization round-trips all 16 event types. Deserialization uses EVENT_TYPE_REGISTRY for type dispatch. MessagePack deferred.

---

### Wave 2 (Depends on Wave 1: Subtasks 2.1.1 + 2.1.2)

#### Subtask 2.1.4: Boundary Contract Validation (ESAA Pattern)

**Files created:**
- `src/orchestra/storage/contracts.py`

**Files modified:** None (wiring into agent.py deferred to integration subtask)

**Function signatures:**

```python
# src/orchestra/storage/contracts.py

from typing import Any
from pydantic import BaseModel


class BoundaryContract:
    """Validates agent output against a JSON Schema before event persistence.

    Per ESAA pattern (arXiv:2602.23193): cleanly separates
    probabilistic LLM cognition from deterministic state mutation.

    Contracts are opt-in:
    - Automatic when agent has output_type (Pydantic model)
    - Manual registration via ContractRegistry for custom schemas
    - Skipped when no contract exists (simple agents pass through)
    """

    def __init__(self, schema: dict[str, Any], name: str = "") -> None:
        """
        Args:
            schema: JSON Schema dict (e.g., from Pydantic model.model_json_schema())
            name: Human-readable name for error messages
        """
        self._schema = schema
        self._name = name or "unnamed"

    @property
    def name(self) -> str:
        return self._name

    @property
    def schema(self) -> dict[str, Any]:
        return self._schema

    def validate(self, output: dict[str, Any]) -> list[str]:
        """Validate output against schema. Returns list of error strings (empty = valid).

        Uses jsonschema library for validation. Catches all validation errors
        and returns them as strings rather than raising.
        """
        ...

    @classmethod
    def from_pydantic(cls, model: type[BaseModel], name: str = "") -> "BoundaryContract":
        """Create contract from a Pydantic model's JSON Schema.

        Uses model.model_json_schema() to extract the schema.
        Name defaults to the model class name.
        """
        schema = model.model_json_schema()
        return cls(schema=schema, name=name or model.__name__)


class ContractRegistry:
    """Maps node_id or agent names to their boundary contracts.

    Auto-registers contracts for agents with output_type.
    Manual registration for custom schemas.
    """

    def __init__(self) -> None:
        self._contracts: dict[str, BoundaryContract] = {}

    def register(self, key: str, contract: BoundaryContract) -> None:
        """Register a contract for an agent name or node ID."""
        self._contracts[key] = contract

    def get(self, key: str) -> BoundaryContract | None:
        """Get contract for key, or None if not registered."""
        return self._contracts.get(key)

    def has_contract(self, key: str) -> bool:
        """Check if a contract exists for this key."""
        return key in self._contracts

    def validate(self, key: str, output: dict[str, Any]) -> list[str]:
        """Validate output against registered contract.

        Returns empty list if no contract registered (pass-through).
        Returns list of error strings if contract exists and validation fails.
        """
        contract = self._contracts.get(key)
        if contract is None:
            return []
        return contract.validate(output)

    def register_from_agent(self, agent_name: str, output_type: type[BaseModel]) -> None:
        """Auto-register a contract from an agent's output_type."""
        self.register(agent_name, BoundaryContract.from_pydantic(output_type))
```

**Dependency:** Requires `jsonschema` library. Add to `pyproject.toml`:

```toml
[project.optional-dependencies]
storage = ["jsonschema>=4.20"]
```

Also add `jsonschema` to the base dependencies since contract validation is core functionality:

```toml
dependencies = [
    "pydantic>=2.5",
    "httpx>=0.26",
    "structlog>=24.0",
    "rich>=13.0",
    "typer>=0.12",
    "jsonschema>=4.20",
]
```

**Update `src/orchestra/storage/__init__.py`:** Add contract exports:

```python
from orchestra.storage.contracts import BoundaryContract, ContractRegistry
```

**Verification:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -c "
from orchestra.storage.contracts import BoundaryContract, ContractRegistry
from pydantic import BaseModel

# Test from_pydantic
class MyOutput(BaseModel):
    summary: str
    score: int

contract = BoundaryContract.from_pydantic(MyOutput)
assert contract.name == 'MyOutput'

# Test valid output
errors = contract.validate({'summary': 'test', 'score': 5})
assert errors == [], f'Expected no errors, got: {errors}'

# Test invalid output (wrong type)
errors = contract.validate({'summary': 'test', 'score': 'not_int'})
assert len(errors) > 0, 'Expected validation errors for wrong type'

# Test missing required field
errors = contract.validate({'summary': 'test'})
assert len(errors) > 0, 'Expected validation errors for missing field'

# Test ContractRegistry
registry = ContractRegistry()
registry.register_from_agent('my_agent', MyOutput)
assert registry.has_contract('my_agent')
errors = registry.validate('my_agent', {'summary': 'ok', 'score': 10})
assert errors == []
errors = registry.validate('my_agent', {'summary': 'ok', 'score': 'bad'})
assert len(errors) > 0

# Test pass-through for unregistered agent
errors = registry.validate('unknown_agent', {'anything': True})
assert errors == [], 'Unregistered agents should pass through'

print('BoundaryContract + ContractRegistry: OK')
"
```

**Done:** Boundary contracts validate agent outputs. Auto-generation from Pydantic models. ContractRegistry with pass-through for unregistered agents.

---

### Wave 3 (Depends on Wave 2: All previous subtasks complete)

#### Subtask 2.1.5: Comprehensive Unit Tests

**Files created:**
- `tests/unit/test_events.py`

**Test inventory (minimum 15 tests, targeting 18):**

```python
# tests/unit/test_events.py

class TestEventTypes:
    def test_all_16_event_types_importable(self): ...
    def test_event_frozen_immutability(self): ...
    def test_event_type_discriminator(self): ...
    def test_event_default_fields(self): ...  # event_id auto-generated, etc.

class TestEventBus:
    @pytest.mark.asyncio
    async def test_emit_dispatches_to_wildcard_subscribers(self): ...
    @pytest.mark.asyncio
    async def test_emit_dispatches_to_type_filtered_subscribers(self): ...
    @pytest.mark.asyncio
    async def test_emit_assigns_monotonic_sequence(self): ...
    @pytest.mark.asyncio
    async def test_emit_assigns_iso_timestamp(self): ...
    @pytest.mark.asyncio
    async def test_emit_supports_async_subscribers(self): ...
    @pytest.mark.asyncio
    async def test_sequence_numbers_independent_per_run(self): ...

class TestInMemoryEventStore:
    @pytest.mark.asyncio
    async def test_append_and_get_events(self): ...
    @pytest.mark.asyncio
    async def test_get_events_after_sequence(self): ...
    @pytest.mark.asyncio
    async def test_get_events_filtered_by_type(self): ...
    @pytest.mark.asyncio
    async def test_checkpoint_save_and_restore(self): ...
    @pytest.mark.asyncio
    async def test_protocol_conformance(self): ...
        # assert isinstance(InMemoryEventStore(), EventStore)
    @pytest.mark.asyncio
    async def test_append_idempotent_on_event_id(self): ...

class TestStateProjection:
    def test_project_empty_returns_initial(self): ...
    def test_project_applies_state_updates(self): ...
    def test_project_with_checkpoint_shortcut(self): ...
    def test_project_with_schema_and_reducers(self): ...

class TestSerialization:
    def test_json_roundtrip_all_event_types(self): ...
    def test_dict_roundtrip(self): ...
    def test_unknown_event_type_raises(self): ...
    def test_preserves_none_values(self): ...
    def test_preserves_float_timestamps(self): ...

class TestContracts:
    def test_valid_output_passes(self): ...
    def test_invalid_output_returns_errors(self): ...
    def test_missing_field_returns_errors(self): ...
    def test_from_pydantic_creates_contract(self): ...
    def test_registry_passthrough_for_unregistered(self): ...
    def test_registry_auto_register_from_agent(self): ...
```

**Critical tests that verify bug-free integration:**

1. **test_project_with_schema_and_reducers:** Creates a `WorkflowState` subclass with `Annotated[list, merge_list]`, generates `StateUpdated` events, projects state, and verifies reducers are applied correctly. This directly tests GAP 2.

2. **test_emit_supports_async_subscribers:** Registers an `async def` subscriber, emits an event, verifies the subscriber received it. This tests GAP 1.

3. **test_sequence_numbers_independent_per_run:** Emits events for two different run_ids, verifies each gets its own monotonic sequence starting from 0.

4. **test_append_idempotent_on_event_id:** Appends the same event twice (same event_id), verifies only one copy stored.

**Verification:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -m pytest tests/unit/test_events.py -v --tb=short
```

Also verify existing tests still pass:
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -m pytest tests/unit/test_core.py -x -q
```

**Done:** 18+ tests pass. All event types, EventBus, InMemoryEventStore, serialization, projection, and contracts are fully tested. Existing test suite unbroken.

---

## 5. Dependency Graph

```
Subtask 2.1.1 (Event Types + Errors)
    |
    v
Subtask 2.1.2 (EventBus + EventStore + Projection + Context)  <-- depends on 2.1.1 (imports events)
    |
    v
Subtask 2.1.3 (Serialization)  <-- depends on 2.1.1 (imports events + registry)
    |                                 (can run parallel with 2.1.2 in theory,
    |                                  but sequencing is safer for review)
    v
Subtask 2.1.4 (Contracts)  <-- depends on 2.1.1 (imports event types for OutputValidated/Rejected)
    |                            (no dependency on 2.1.2 or 2.1.3)
    v
Subtask 2.1.5 (Tests)  <-- depends on ALL previous (tests all components)

Wave 1: 2.1.1 (foundation), then 2.1.2 + 2.1.3 (parallel-safe, different files)
Wave 2: 2.1.4 (contracts, uses events but not store/serialization)
Wave 3: 2.1.5 (tests everything)
```

**Revised wave assignment for maximal parallelism:**

```
Wave 1: Subtask 2.1.1 (must be first -- all others import from it)
Wave 2: Subtask 2.1.2, 2.1.3, 2.1.4 (all parallel -- different files, only depend on 2.1.1)
Wave 3: Subtask 2.1.5 (tests -- depends on all)
```

---

## 6. File Inventory

### Files Created (new)

| File | Subtask | Purpose |
|------|---------|---------|
| `src/orchestra/storage/__init__.py` | 2.1.1 | Package init with `__all__` exports |
| `src/orchestra/storage/events.py` | 2.1.1 | 16 event types + EventType enum + registry |
| `src/orchestra/storage/store.py` | 2.1.2 | EventBus, EventStore Protocol, InMemoryEventStore, project_state |
| `src/orchestra/storage/serialization.py` | 2.1.3 | JSON serialization/deserialization |
| `src/orchestra/storage/contracts.py` | 2.1.4 | BoundaryContract, ContractRegistry |
| `tests/unit/test_events.py` | 2.1.5 | 18+ unit tests |

### Files Modified (existing)

| File | Subtask | Change |
|------|---------|--------|
| `src/orchestra/core/errors.py` | 2.1.1 | Add PersistenceError, EventStoreError, CheckpointError, ContractValidationError |
| `src/orchestra/core/context.py` | 2.1.2 | Add `event_bus: EventBus | None = None` field with TYPE_CHECKING import |
| `pyproject.toml` | 2.1.4 | Add `jsonschema>=4.20` to dependencies |

### Files NOT Modified (confirmed no changes needed for Task 2.1)

| File | Reason |
|------|--------|
| `src/orchestra/core/compiled.py` | Event EMISSION hooks added in a LATER integration task (Plan 04 or a separate wiring task). Task 2.1 builds the infrastructure only. |
| `src/orchestra/core/agent.py` | Same as above -- emission hooks are wiring, not infrastructure. |
| `src/orchestra/core/runner.py` | Same -- EventBus initialization and event store subscription happen when the infrastructure is wired in. |
| `tests/unit/test_core.py` | No changes to core logic, existing tests must pass unchanged. |

**IMPORTANT NOTE:** The existing PLAN.md (Plan 01, BACKUP-STRATEGY.md Tier 1) correctly identifies Task 2.1 as "additive-only" -- it creates new modules in `src/orchestra/storage/` without modifying Phase 1 execution logic. The only Phase 1 files touched are `errors.py` (additive error types) and `context.py` (additive field). Neither change alters existing behavior.

---

## 7. Testing Strategy

### Test Pyramid for Task 2.1

```
Layer 1: Unit tests (test_events.py) -- 18+ tests
  - Event type creation and immutability
  - EventBus pub/sub and sequencing
  - InMemoryEventStore CRUD
  - State projection (with and without checkpoints, with and without reducers)
  - JSON serialization round-trips
  - Boundary contract validation

Layer 2: Integration tests (deferred to Plan 04 wiring)
  - CompiledGraph.run() emits correct events
  - BaseAgent.run() emits LLMCalled/ToolCalled events
  - End-to-end workflow produces correct event stream
  - Event stream can reconstruct final state via project_state()

Layer 3: Property tests (optional, time permitting)
  - Arbitrary event data round-trips through serialization
  - project_state(events) == final_state for any valid event sequence
```

### Regression Gate

Before Task 2.1 is considered complete:

```bash
# All new tests pass
python -m pytest tests/unit/test_events.py -v --tb=short

# All existing tests still pass (no regressions)
python -m pytest tests/unit/test_core.py -v --tb=short

# Import smoke test (all public API importable)
python -c "from orchestra.storage import *; print('OK')"
python -c "from orchestra.storage.store import EventBus, EventStore, InMemoryEventStore, project_state; print('OK')"
python -c "from orchestra.storage.serialization import event_to_json, json_to_event; print('OK')"
python -c "from orchestra.storage.contracts import BoundaryContract, ContractRegistry; print('OK')"

# Type check (if mypy is configured)
python -m mypy src/orchestra/storage/ --ignore-missing-imports
```

---

## Appendix A: What Task 2.1 Does NOT Include

These are explicitly deferred to later plans:

1. **Event emission hooks in compiled.py / agent.py** -- Plan 04 (wiring)
2. **SQLite backend** -- Task 2.2
3. **PostgreSQL backend** -- Task 2.3
4. **MessagePack serialization** -- Deferred per research recommendation
5. **Hash-chain event integrity** -- Future enhancement
6. **Replay-safe tool gateways** -- Task 2.5 (time-travel)
7. **Event retention/cleanup policies** -- Future enhancement
8. **Schema migration tooling** -- Future enhancement (Alembic-style)

## Appendix B: Downstream Consumer Notes

Plans that depend on Task 2.1's output:

| Plan | What it needs from 2.1 |
|------|----------------------|
| Plan 04 (SQLite + Rich Trace + Handoff) | EventStore Protocol to implement SQLiteEventStore. EventBus to subscribe TraceRenderer. Event types to emit from compiled.py/agent.py. |
| Plan 05 (PostgreSQL) | EventStore Protocol to implement PostgresEventStore. Serialization for JSONB storage. |
| Plan 06 (HITL) | InterruptRequested/InterruptResumed event types. EventBus for interrupt signaling. |
| Plan 07 (Time-Travel) | project_state() for state reconstruction. CheckpointCreated for snapshot navigation. get_events() for history retrieval. |
