# Task 04b: Rich Trace Renderer + Handoff Protocol -- Detailed Execution Plan

**Phase:** 02-differentiation
**Task:** 04b (split from original Plan 04, DIFF-06 + DIFF-07)
**Created:** 2026-03-09
**Status:** Ready for execution
**Wave:** 2b (after Plan 04a)
**Dependencies:** Plan 01 (EventBus wired), Plan 04a (CompiledGraph.run() has event_bus + lifecycle events)
**Estimated effort:** 4 days
**Autonomous:** Yes

---

## Objective

Two independent deliverables sharing a wave slot:

1. **Rich Trace Renderer** — real-time terminal tree rendering via EventBus subscription
2. **Handoff Protocol** — Swarm-style agent handoffs as a first-class edge type with context distillation

Both subscribe to the EventBus that Plan 04a wired into `CompiledGraph.run()`.
Plan 04b also wires LLM/tool event emission into `agent.py` (the last piece of compiled.py integration).

---

## Context: What Plans 01 and 04a Already Delivered

- `EventBus` with `subscribe()` / `emit()` — `store.py`
- `AnyEvent` discriminated union with all event types — `events.py`
- `ExecutionContext.event_bus: Any` — wired in `compiled.py` by Plan 04a
- `RunStarted`, `RunCompleted`, `RunFailed`, `NodeEntered`, `NodeCompleted`, `NodeFailed` — emitted by `compiled.py` (Plan 04a)
- `SQLiteEventStore` subscribed in `compiled.py` — Plan 04a

**Not yet emitted:** `ToolCalled`, `ToolReturned`, `LLMCalled` (these come from `agent.py` -- this plan adds them).

---

## Task 4b.1: Rich Console Trace Renderer

**File:** `src/orchestra/observability/console.py`

**Action:**

Implement the Rich-based real-time trace renderer as a standalone EventBus subscriber.

```python
from rich.tree import Tree
from rich.live import Live
from rich import print as rprint

class RichTraceRenderer:
    """Real-time terminal trace renderer using Rich.

    Subscribes to EventBus and renders a live-updating tree:

      Workflow: customer_support [3.2s]
      +-- triage (gpt-4o-mini) [1.1s] 150 tok $0.001 OK
      |   +-- LLM call [0.8s] 100 in / 50 out
      |   +-- tool: classify_ticket({priority: "high"}) -> "billing" [0.3s]
      +-- billing_agent (gpt-4o) [2.1s] 500 tok $0.015 OK
      |   +-- LLM call [1.8s] 350 in / 150 out
      |   +-- tool: lookup_account({id: "123"}) -> "{balance: 50}" [0.3s]
      +-- TOTAL: 650 tokens, $0.016, 3.2s

    Controlled by environment variables:
    - ORCHESTRA_TRACE=rich (default in dev) / off / verbose
    - ORCHESTRA_ENV=dev (default) / prod (disables trace)
    """

    def __init__(self, verbose: bool = False) -> None:
        self._tree = Tree("Workflow")
        self._live: Live | None = None
        self._node_branches: dict[str, Any] = {}  # node_id -> Rich Tree branch
        self._verbose = verbose
        self._start_time: float | None = None
        self._total_tokens: int = 0
        self._total_cost: float = 0.0

    def start(self) -> None:
        """Start Rich Live display.""" ...

    def stop(self) -> None:
        """Stop Rich Live display, render final tree.""" ...

    def on_event(self, event: AnyEvent) -> None:
        """Sync EventBus subscriber. Updates tree based on event type.""" ...
```

**Event-to-rendering mapping:**

| Event | Rendering |
|-------|-----------|
| `RunStarted` | Root label: `"Workflow: {graph_name}"` |
| `NodeEntered` | Add branch with spinner: `"{node_id} ..."` |
| `LLMCalled` | Add leaf: `"LLM [{duration:.1f}s] {in_tok} in / {out_tok} out ${cost:.4f}"` |
| `ToolCalled` | Add leaf (cyan): `"tool: {name}({args_truncated}) -> {result_truncated} [{duration:.2f}s]"` |
| `NodeCompleted` | Update branch: replace spinner with `"✓ {node_id} [{duration:.1f}s] {total_tok} tok ${cost:.4f}"` |
| `NodeFailed` | Update branch (red): `"✗ {node_id} [{duration:.1f}s] {error}"` |
| `RunCompleted` | Add totals line: `"TOTAL: {tokens} tokens, ${cost:.4f}, {duration:.1f}s"` |
| `RunFailed` | Add red error summary |

**Color coding:**
- Green: success nodes (`style="green"`)
- Red: failed nodes/runs (`style="red"`)
- Cyan: tool calls (`style="cyan"`)
- Yellow: HITL interrupts (`style="yellow"`) — future use
- Dim: verbose details (`style="dim"`)

**Verbose mode (`ORCHESTRA_TRACE=verbose`):**
- Tool args shown in full (not truncated to 50 chars)
- LLM response first 200 chars shown
- State field changes shown

**Performance:** Use `Live(refresh_per_second=4)` — 250ms refresh interval. Renderer must not block the event loop (all operations are sync and fast).

**Graceful degradation:** If `rich` is not installed, `RichTraceRenderer` should raise `ImportError` with a helpful message: `"pip install orchestra[observability]"`.

**Verify:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -c "
from orchestra.observability.console import RichTraceRenderer
r = RichTraceRenderer()
print('RichTraceRenderer OK')
"
```

---

## Task 4b.2: Wire Trace into CompiledGraph.run()

**File:** `src/orchestra/core/compiled.py` (modify — adds to Plan 04a's changes)

**Action:**

In `CompiledGraph.run()`, after the SQLite subscription (Plan 04a), add:

```python
# After SQLite subscription, add trace subscription
trace_mode = os.environ.get("ORCHESTRA_TRACE", "rich" if os.environ.get("ORCHESTRA_ENV", "dev") == "dev" else "off")
if trace_mode != "off":
    try:
        from orchestra.observability.console import RichTraceRenderer
        renderer = RichTraceRenderer(verbose=(trace_mode == "verbose"))
        event_bus.subscribe(renderer.on_event)
        renderer.start()
        # Store renderer reference to stop it after run
        _renderer = renderer
    except ImportError:
        _renderer = None
else:
    _renderer = None

# ... run the graph ...

# After run completes (in finally block):
if _renderer is not None:
    _renderer.stop()
```

**Important:** This is an additive change to Plan 04a's compiled.py modifications. Do not re-implement the SQLite wiring — only add the trace subscriber.

---

## Task 4b.3: Emit LLM and Tool Events from agent.py

**File:** `src/orchestra/core/agent.py` (modify)

**Action:**

In `BaseAgent.run()` (or wherever LLM calls and tool calls happen), emit events via `context.event_bus`:

```python
# After LLM call completes:
if context.event_bus is not None:
    await context.event_bus.emit(LLMCalled(
        run_id=context.run_id,
        node_id=self.node_id,
        model=response.model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        cost=...,
        duration=elapsed,
        ...
    ))

# After tool call completes:
if context.event_bus is not None:
    await context.event_bus.emit(ToolCalled(
        run_id=context.run_id,
        node_id=self.node_id,
        tool_name=tool_name,
        arguments=tool_args,
        result=tool_result,
        duration=elapsed,
        ...
    ))
```

Check `context.event_bus is not None` before every emit — fully backwards compatible with callers that don't use EventBus.

Use `context.replay_mode` to suppress side-effect emissions during time-travel replay (Plan 07).

---

## Task 4b.4: Handoff Protocol

**Files:** `src/orchestra/core/handoff.py`, `src/orchestra/core/context_distill.py`

**Action:**

Implement Swarm-style agent handoffs as a first-class edge type.

**handoff.py:**

```python
@dataclass(frozen=True)
class HandoffPayload:
    """Context transferred during handoff."""
    from_agent: str
    to_agent: str
    reason: str
    conversation_history: list[Message]
    metadata: dict[str, Any]
    distilled: bool  # Whether context was distilled

@dataclass(frozen=True)
class HandoffEdge:
    """Edge type for agent handoffs.

    Created via graph.add_handoff(). Transfers execution context
    from one agent to another with optional context distillation.
    """
    source: str
    target: str
    condition: EdgeCondition | None = None
    distill: bool = True  # Use context distillation by default
```

**WorkflowGraph.add_handoff() — modify graph.py:**

```python
def add_handoff(
    self,
    from_agent: str,
    to_agent: str,
    *,
    condition: EdgeCondition | None = None,
    distill: bool = True,
) -> "WorkflowGraph":
    """Add a handoff edge between agents.

    Usage:
        graph.add_handoff("triage", "specialist", condition=needs_expert)
        graph.add_handoff("researcher", "writer")  # Unconditional
    """
    edge = HandoffEdge(source=from_agent, target=to_agent, condition=condition, distill=distill)
    self._handoff_edges.append(edge)  # or integrate with existing edge storage
    return self
```

**context_distill.py:**

Three-zone model:
1. **Stable prefix** — system messages (kept intact)
2. **Compacted middleware** — intermediate reasoning/tool history (summarized to N tokens)
3. **Variable suffix** — last K turns (kept intact)

```python
def distill_context(
    messages: list[Message],
    *,
    max_middleware_tokens: int = 500,
    keep_last_n_turns: int = 3,
) -> list[Message]:
    """Distill conversation history for handoff.

    Three-zone partitioning:
    1. Stable prefix (system messages) -- kept intact
    2. Compacted middleware (intermediate) -- summarized
    3. Variable suffix (last N turns) -- kept intact
    """
    ...

def full_passthrough(messages: list[Message]) -> list[Message]:
    """No distillation -- pass all messages as-is."""
    return list(messages)
```

Summarization strategy for middleware: concatenate content of intermediate messages, truncate to `max_middleware_tokens` words, wrap in a single `{"role": "assistant", "content": "[Context summary: ...]"}` message.

**Integration with CompiledGraph._resolve_next() — modify compiled.py:**

When resolving next node and a `HandoffEdge` matches:
1. Build `HandoffPayload` from current agent's conversation history
2. Apply `distill_context()` or `full_passthrough()` based on `HandoffEdge.distill`
3. Emit `HandoffInitiated` event (from events.py — check if it exists; add if not)
4. Pass payload to target agent's input state
5. After target node completes, emit `HandoffCompleted`

---

## Task 4b.5: Tests

**Files:**
- `tests/unit/test_trace.py`
- `tests/unit/test_handoff.py`

**Trace tests (8 minimum):**
1. `RichTraceRenderer` instantiates without error
2. `on_event()` handles `RunStarted` without crash
3. `on_event()` handles `NodeEntered` creates branch
4. `on_event()` handles `NodeCompleted` updates branch
5. `on_event()` handles `RunCompleted` adds totals
6. `on_event()` handles unknown event type gracefully (no crash)
7. `start()` / `stop()` lifecycle works without Rich Live running
8. Verbose mode flag propagates to truncation behavior

**Handoff tests (10 minimum):**
1. `add_handoff()` creates `HandoffEdge` and registers it
2. `HandoffEdge` is frozen (immutable)
3. `distill_context()` with only system messages returns them intact
4. `distill_context()` with many intermediate messages compresses middleware
5. `distill_context()` keeps last N turns intact
6. `full_passthrough()` returns identical list
7. `HandoffPayload` is frozen (immutable)
8. Conditional `HandoffEdge` stores condition correctly
9. `distill=False` uses full_passthrough
10. `distill_context()` with empty messages returns empty list

---

## File Inventory

| Action | File |
|--------|------|
| Create | `src/orchestra/observability/console.py` |
| Create | `src/orchestra/core/handoff.py` |
| Create | `src/orchestra/core/context_distill.py` |
| Modify | `src/orchestra/core/compiled.py` (add trace subscriber, handoff resolution) |
| Modify | `src/orchestra/core/agent.py` (emit LLMCalled, ToolCalled) |
| Modify | `src/orchestra/core/graph.py` (add add_handoff method) |
| Modify | `pyproject.toml` (add rich to observability extras) |
| Create | `tests/unit/test_trace.py` |
| Create | `tests/unit/test_handoff.py` |

**Does NOT touch:**
- `src/orchestra/storage/sqlite.py` (Plan 04a, already complete)

---

## Dependency Graph

```
Plan 01 (EventBus) + Plan 04a (CompiledGraph.run() wired)
    |
    +---> Task 4b.1 (RichTraceRenderer) --> Task 4b.2 (Wire trace into compiled.py)
    |
    +---> Task 4b.3 (LLM/Tool events from agent.py)
    |
    +---> Task 4b.4 (HandoffEdge + context_distill)
    |
    v
Task 4b.5 (Tests)
```

Tasks 4b.1–4b.4 can be implemented in any order; they touch different files.

---

## Testing Strategy

**Trace tests:** Mock Rich's `Live` with a no-op context manager so tests don't need a terminal.
**Handoff tests:** Unit-test dataclasses and distillation functions directly — no need for full workflow execution.

**Verification command:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -m pytest tests/unit/test_trace.py tests/unit/test_handoff.py -v --tb=short
```

**Regression guard:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -m pytest tests/unit/ -q --tb=no
```

All existing tests must still pass.
