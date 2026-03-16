# Wave 4 Research: Dynamic Subgraphs (T-4.12)

**Researched:** 2026-03-13
**Updated:** 2026-03-14
**Confidence:** HIGH
**Scope:** Current graph architecture, Send API pattern, SubgraphBuilder, YAML serialization, hot-reload

---

## 1. Current Graph Architecture (from source code)

### Core Types

| File | Class | Purpose |
|------|-------|---------|
| `core/nodes.py` | `AgentNode`, `FunctionNode`, `SubgraphNode` | Node wrappers (frozen dataclasses) |
| `core/edges.py` | `Edge`, `ConditionalEdge`, `ParallelEdge` | Edge types (frozen dataclasses) |
| `core/graph.py` | `WorkflowGraph` | Builder with fluent + explicit API |
| `core/compiled.py` | `CompiledGraph` | Immutable runtime execution engine |
| `core/handoff.py` | `HandoffEdge`, `HandoffPayload` | Agent-to-agent transfers |
| `server/lifecycle.py` | `GraphRegistry` | Thread-safe name→CompiledGraph registry |

### Existing Graph APIs

**Fluent API:**
```python
graph = WorkflowGraph().then(a).parallel(b, c).join(d).then(e)
```

**Explicit API:**
```python
graph = WorkflowGraph()
graph.add_node("a", agent_a)
graph.add_edge("a", "b")
graph.add_conditional_edge("b", condition, {"x": "c", "y": "d"})
graph.add_parallel("c", ["d", "e"], join_node="f")
```

### SubgraphNode Already Exists

`SubgraphNode` (`core/nodes.py:57-71`) wraps a `CompiledGraph` with input/output mappers:

```python
@dataclass(frozen=True)
class SubgraphNode:
    graph: Any  # CompiledGraph
    input_mapper: Callable[[dict], dict] | None = None
    output_mapper: Callable[[dict], dict] | None = None

    async def __call__(self, state: dict) -> dict:
        input_state = self.input_mapper(state) if self.input_mapper else state
        result = await self.graph.run(input_state)
        return self.output_mapper(result) if self.output_mapper else result
```

**Gap:** There is no builder API or fluent `.subgraph()` method. Users must manually construct and compile subgraphs, then wrap them in `SubgraphNode`.

### GraphRegistry

Thread-safe `dict[str, CompiledGraph]` with `register()`, `get()`, `list_graphs()`. Uses `threading.Lock`. Already supports atomic replacement (re-register overwrites).

### Key Execution Details

- `CompiledGraph` is effectively immutable after construction (nodes/edges are dicts/lists set in `__init__`)
- `_resolve_next()` handles edge routing: `Edge` → direct, `ConditionalEdge` → condition function, `ParallelEdge` → `asyncio.gather` with `merge_parallel_updates()`
- `ActiveRun` holds a reference to the `CompiledGraph` — in-flight runs are unaffected by registry changes

---

## 2. The Send API Pattern (T-4.12)

### Dynamic Fan-Out & Map-Reduce
The "Send API" enables **dynamic map-reduce** operations where the number of workers is determined at runtime.
- **Fan-Out:** A conditional edge returns a list of `Send("node_name", payload)` objects instead of a single node name.
- **JIT Resolution:** The graph runtime resolves these objects into parallel executions. Each execution receives a private state slice (the `payload`), ensuring isolation.
- **Aggregation:** Results are aggregated back into the shared state using the graph's designated reducers or an explicit join node.

### Orchestra Implementation Sketch

```python
# Proposed: src/orchestra/core/types.py
@dataclass(frozen=True)
class Send:
    """Dynamic fan-out target with per-item scoped state."""
    node: str
    state: dict[str, Any]
```

Modify `CompiledGraph._resolve_next()` to detect when a `ConditionalEdge.resolve()` returns `list[Send]`:

```python
# In _resolve_next(), after ConditionalEdge handling:
elif isinstance(edge, ConditionalEdge):
    result = edge.resolve(state_dict)

    # NEW: Handle Send API
    if isinstance(result, list) and result and isinstance(result[0], Send):
        updates = await self._execute_sends(result, context)
        merged = merge_parallel_updates(state, updates, self._reducers)
        return END, merged

    return result, state
```

---

## 3. SubgraphBuilder API Design

### Proposed API

```python
from orchestra.core.dynamic import SubgraphBuilder

# Method 1: Inline subgraph definition
graph = (
    WorkflowGraph()
    .then(planner)
    .subgraph(
        "research_team",
        lambda: (
            SubgraphBuilder()
            .then(researcher_a)
            .then(summarizer)
            .build()
        ),
        input_mapper=lambda s: {"query": s["plan"]},
        output_mapper=lambda s: {"research": s["output"]},
    )
    .then(writer)
)
```

---

## 4. YAML Serialization & Hydration

### Library: `ruamel.yaml >= 0.18`
- **Round-Tripping:** Selected for its ability to preserve comments, block styles, and AST metadata. This is critical for "human-in-the-loop" configuration editing where users modify YAML files that the system also writes to.
- **Security (CWE-502):** Avoid `pickle` or standard `yaml.load`.
- **Validation:** Use Pydantic to validate the hydrated graph structure against a strict allowlist. Hydration converts text-based `ref` strings into executable Python objects only after passing security checks.

---

## 5. Hot-Reloading: Atomic Registry Swapping

### Watchfiles Integration
Use `watchfiles` (Rust-backed, used by Uvicorn) for high-performance file change detection.

### Atomic Swapping Pattern
1. **Detect:** `watchfiles` identifies a change in a YAML or Python workflow file.
2. **Background Load:** The system loads and compiles the new graph definition in a background task.
3. **Atomic Swap:** Upon successful compilation, the `GraphRegistry` (thread-safe singleton) is updated to point to the new `CompiledGraph` instance.
4. **Persistence:** In-flight runs continue using the old `CompiledGraph` instance they captured at start-of-run. New requests immediately receive the updated definition.

---

## 6. Security: Dotted-Path Validation

### Dotted-Path Resolution
When loading logic from text (e.g., `ref: "myapp.agents.PlannerAgent"`), arbitrary code execution must be prevented.

### Validation Strategy
- **Import Allowlisting:** Maintain a strict dictionary or prefix list of allowed modules (e.g., `ALLOWED_PREFIXES = ["orchestra.tools.", "myapp.agents."]`).
- **Map vs. Import:** Prefer mapping string aliases to actual callables (e.g., `{"search": my_tool_func}`).
- **Strict Rejection:** Never use `importlib.import_module(user_input)` directly on unvalidated strings.
- **Nesting Limits:** Explicitly check and limit the depth of nested subgraphs during hydration (default: 10) to prevent stack overflow or resource exhaustion attacks.

---

## 9. Confidence Assessment

| Area | Level | Reason |
|------|-------|--------|
| Current architecture | HIGH | Direct source code reading of all core files. |
| Send API pattern | **HIGH** | Aligned with LangGraph/Map-Reduce industry standards. |
| YAML serialization | **HIGH** | `ruamel.yaml` is the established choice for round-tripping. |
| Hot-reload strategy | **HIGH** | watchfiles + atomic swap is the standard for modern Python servers. |
| Security Validation | **HIGH** | Dotted-path allowlisting is a proven defense-in-depth pattern. |

**Overall: ~90% ready for implementation.**
