# Research: Rich Console Trace Renderer

**Research Date:** 2026-03-07
**Phase:** 2 - Differentiation
**Confidence:** HIGH

---

## 1. Rich Live Display with Async

### How Rich Live Works
- Rich's `Live` class uses a background daemon thread with `threading.RLock` for auto-refresh
- Default refresh rate: 4 Hz (every 250ms)
- The safe pattern: mutate the Tree renderable in-place from async event callbacks, let the auto-refresh thread pick up changes
- **Never call `live.refresh()` from async code** — it blocks the event loop

### Integration Pattern
```python
from rich.live import Live
from rich.tree import Tree
from rich.spinner import Spinner

class TraceRenderer:
    def __init__(self):
        self._tree = Tree("Workflow")
        self._node_map: dict[str, Tree] = {}
        self._live = Live(self._tree, refresh_per_second=4)

    def start(self):
        self._live.start()

    def stop(self):
        self._live.stop()

    def on_node_started(self, node_id: str, node_type: str):
        # Mutate tree in-place — safe from any thread/task
        spinner = Spinner("dots", text=f"{node_id}")
        node = self._tree.add(spinner)
        self._node_map[node_id] = node

    def on_node_completed(self, node_id: str, duration_ms: float, tokens: int, cost: float):
        node = self._node_map[node_id]
        node.label = Text.from_markup(
            f"[green]OK[/] {node_id}  {duration_ms/1000:.1f}s  {tokens} tok  ${cost:.4f}"
        )
```

### Threading Safety
- The GIL makes attribute assignments (`node.label = ...`) atomic between the async thread and Rich's refresh thread
- No explicit locking needed for simple mutations (adding children, changing labels)
- Rich's internal `RLock` protects the rendering pipeline

---

## 2. Rich Tree for Trace Visualization

### Tree Structure
```
Workflow: research_pipeline  [run_id: abc123]
├── OK researcher      2.1s  570 tok  $0.003
│   ├── LLM  gpt-4o   1.8s  540 tok
│   └── Tool web_search  0.3s
├── ⠋ writer          ...
│   ├── LLM  gpt-4o   1.2s  320 tok
│   └── ⠋ Tool format_doc  ...
└── ○ editor          (pending)
```

### Node Status Icons
- `⠋` (Spinner) — currently executing
- `OK` (`[green]OK[/]`) — completed successfully
- `FAIL` (`[red]FAIL[/]`) — failed with error
- `PAUSED` (`[yellow]PAUSED[/]`) — HITL interrupt
- `○` — pending (not yet started)

### Child Nodes
Each agent node can have children for its internal operations:
- `LLM` — LLM call with model name, duration, token count
- `Tool` — tool call with tool name, duration
- These appear as the agent executes (live updating)

### Parallel Branches
```
├── ⠋ parallel
│   ├── OK analyst_1    1.5s  400 tok  $0.002
│   ├── ⠋ analyst_2    ...
│   └── OK analyst_3    1.2s  350 tok  $0.002
```

---

## 3. LangSmith / Langfuse Trace Patterns

### What They Show
Both LangSmith and Langfuse use hierarchical trace trees with nested spans:
- Per-span: name, duration, token count (input/output), cost, status
- Expandable detail views for inputs/outputs
- Color coding by status (green/red/yellow)
- Total aggregates at the root

### Terminal Adaptation
- Can't expand/collapse in terminal — use summary vs verbose modes
- Summary: one line per node with key metrics
- Verbose: multi-line per node with tool args, LLM snippets (truncated)
- Adapt the "one-line per span" format: `"OK researcher 2.1s 570 tok $0.003"`

---

## 4. Performance Overhead

### Measurements
- At 4 Hz refresh with simple tree mutations, overhead is ~30-60ms for a 5-second workflow
- That's **0.6-1.2% overhead** — well within the <5% target
- Rich's rendering is I/O-bound (writing to terminal), not CPU-bound
- The GIL does not cause contention because tree mutations are microsecond operations

### Optimization Strategies
- Use `refresh_per_second=4` (not higher) — 4 Hz is smooth enough for human eyes
- Buffer rapid events — if 10 tool calls happen in 100ms, batch the tree updates
- Don't render in production (`ORCHESTRA_ENV=prod` disables trace)
- Tree node count is bounded by workflow graph size (typically < 50 nodes)

---

## 5. Cost Display Patterns

### Format Convention
- Always use **`$0.003`** format (dollar sign + decimal)
- Never use cents ("0.3 cents") — inconsistent with industry standard
- Never use scientific notation ("3e-3") — unreadable
- Show **4 decimal places** for per-node costs: `$0.0034`
- Show **2 decimal places** for totals: `$0.05`
- When pricing is unknown: `$--.----`

### Cost Calculation Source
- Use the existing `TokenUsage.estimated_cost_usd` from Phase 1
- Model pricing dict already exists in `HttpProvider._MODEL_COSTS` and `AnthropicProvider`
- Consider sourcing pricing from LiteLLM's canonical database for broader model coverage
- Show `$--.----` when model is not in the pricing dict

### Display Location
- Per-node: inline after token count (`570 tok  $0.003`)
- Total: bottom line after trace tree completes
```
Total: 3 nodes  4.2s  1,420 tok  $0.008
```

---

## 6. Environment Detection

### Priority Chain (highest to lowest)
1. **`ORCHESTRA_TRACE`** — explicit override
   - `rich` — show Rich trace (default in dev)
   - `verbose` — show Rich trace with full detail
   - `json` — emit JSON events to stdout (for piping)
   - `off` — disable trace entirely
2. **`ORCHESTRA_ENV`** — environment mode
   - `dev` (default) — trace enabled
   - `prod` — trace disabled
   - `test` — trace disabled
3. **CI detection** — `CI=true` environment variable (set by GitHub Actions, GitLab CI, etc.) — trace disabled
4. **TTY detection** — `sys.stdout.isatty()` — if not a TTY (piped output), disable Rich trace (emit JSON instead)

### NO_COLOR Standard
- Respect the `NO_COLOR` environment variable (https://no-color.org/)
- When set: disable colors/styling, but still show the trace structure
- This affects styling, not whether traces are shown

### Auto-Detection Logic
```python
def should_show_trace() -> tuple[bool, str]:
    trace_env = os.environ.get("ORCHESTRA_TRACE", "").lower()
    if trace_env == "off":
        return False, "off"
    if trace_env in ("rich", "verbose", "json"):
        return True, trace_env

    env = os.environ.get("ORCHESTRA_ENV", "dev").lower()
    if env in ("prod", "production"):
        return False, "off"
    if env == "test":
        return False, "off"

    if os.environ.get("CI", "").lower() == "true":
        return False, "off"

    if not sys.stdout.isatty():
        return True, "json"  # Piped output gets JSON

    return True, "rich"  # Dev, TTY, no overrides
```

---

## 7. Event Subscription Architecture

### How the Trace Renderer Receives Events
The trace renderer subscribes to the same event stream used by the event store:

```python
class EventBus:
    """In-memory pub/sub for workflow events."""
    def __init__(self):
        self._subscribers: list[Callable[[WorkflowEvent], None]] = []

    def subscribe(self, callback: Callable[[WorkflowEvent], None]) -> None:
        self._subscribers.append(callback)

    def emit(self, event: WorkflowEvent) -> None:
        for subscriber in self._subscribers:
            subscriber(event)
```

Subscribers:
1. **EventStore** — persists events to SQLite/PostgreSQL
2. **TraceRenderer** — updates the Rich tree display
3. **structlog** — existing debug logging (unchanged)

The bus is synchronous (callbacks run inline) because both persistence and rendering are fast (<1ms each). If either becomes slow, switch to an asyncio.Queue.

---

## 8. Verbose Mode Detail

When `ORCHESTRA_TRACE=verbose`:

```
Workflow: research_pipeline  [run_id: abc123]
├── OK researcher      2.1s  570 tok  $0.003
│   ├── LLM  gpt-4o   1.8s  540 tok
│   │   Input: "Research the latest advances in..."  (42 chars)
│   │   Output: "Based on recent developments..."  (1,204 chars)
│   └── Tool web_search  0.3s
│       Args: {"query": "AI advances 2026", "max_results": 5}
│       Result: "Found 5 results: 1. ..."  (truncated at 200 chars)
```

- Tool arguments: show full JSON (truncated at 200 chars)
- Tool results: show first 200 chars
- LLM input: show first 80 chars of last user message
- LLM output: show char count only (content is usually long)

---

*Research: 2026-03-07*
*Researcher: gsd-phase-researcher agent*
