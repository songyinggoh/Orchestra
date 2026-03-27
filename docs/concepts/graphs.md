# Graphs

Workflows in Orchestra are directed graphs. You build them with `WorkflowGraph`, then compile them into an executable `CompiledGraph`.

## Building Graphs

Orchestra provides two APIs for graph construction:

### Fluent API

Chain methods for concise graph definitions:

```python
from orchestra import WorkflowGraph

graph = (
    WorkflowGraph(state_schema=MyState)
    .then(researcher)
    .then(writer)
    .then(editor)
)
compiled = graph.compile()
```

### Explicit API

Use `add_node` and `add_edge` for full control:

```python
from orchestra import WorkflowGraph
from orchestra.core.types import END

graph = WorkflowGraph(state_schema=MyState)
graph.add_node("researcher", researcher)
graph.add_node("writer", writer)
graph.add_node("editor", editor)

graph.set_entry_point("researcher")
graph.add_edge("researcher", "writer")
graph.add_edge("writer", "editor")
graph.add_edge("editor", END)

compiled = graph.compile()
```

## Workflow Patterns

### Sequential

Nodes execute one after another. Each node receives the state produced by the previous node.

```python
graph = WorkflowGraph().then(step_a).then(step_b).then(step_c)
```

### Parallel Fan-Out

Multiple nodes execute concurrently, then their state updates are merged:

```python
graph = (
    WorkflowGraph(state_schema=ResearchState)
    .then(planner)
    .parallel(researcher_a, researcher_b, researcher_c)
    .join(synthesizer)
)
```

State updates from parallel nodes are merged using the reducers defined on your state class. Fields with `merge_list` accumulate, fields with `merge_dict` merge, and fields without reducers use last-write-wins.

### Conditional Routing

Route to different nodes based on state values:

```python
graph = (
    WorkflowGraph()
    .then(classifier)
    .branch(
        lambda state: state.get("category"),
        {
            "technical": tech_writer,
            "creative": creative_writer,
        }
    )
)
```

The condition function receives the state dict and returns a key that maps to a target node.

### If/Then/Else

A simpler conditional for binary decisions:

```python
graph = (
    WorkflowGraph()
    .then(reviewer)
    .if_then(
        lambda state: state["approved"],
        then_agent=publisher,
        else_agent=reviser,
    )
)
```

### Loops

Repeat a node until a condition is met:

```python
graph = (
    WorkflowGraph()
    .then(writer)
    .loop(
        reviewer,
        condition=lambda state: not state["approved"],
        max_iterations=5,
    )
)
```

The node repeats while `condition` returns `True`, up to `max_iterations`.

## Compilation and Execution

Call `compile()` to validate the graph and produce an executable `CompiledGraph`:

```python
compiled = graph.compile(max_turns=50)
```

`compile()` validates:

- At least one node exists
- An entry point is set
- All edge sources and targets reference valid nodes
- Auto-appends an `END` edge to the last node if missing

Run the compiled graph. Note that `compiled.run()` returns a plain `dict[str, Any]` (the final state):

```python
result = await compiled.run(
    initial_state={"topic": "AI"},
    provider=my_llm_provider,
)
print(result["output"])  # result is a dict
```

Or use the top-level `run()` function from `orchestra.core.runner`, which handles compilation automatically and returns a `RunResult` with attribute access:

```python
from orchestra import run

result = await run(graph, initial_state={"topic": "AI"}, provider=llm)
print(result.output)      # RunResult has attribute access
print(result.state)        # underlying state dict
print(result.duration_ms)  # execution time
```

## Visualization

Generate a Mermaid diagram from a compiled graph:

```python
compiled = graph.compile()
print(compiled.to_mermaid())
```

This produces a Mermaid flowchart showing nodes, edges, and routing logic.

## Node Types

Orchestra supports three node types:

| Type | Description | Created from |
|------|-------------|--------------|
| `AgentNode` | Wraps a `BaseAgent` and runs its LLM reasoning loop | Agent instances |
| `FunctionNode` | Wraps an async function `(state) -> updates` | Plain async functions |
| `SubgraphNode` | Nests a compiled graph as a single node | `CompiledGraph` instances |
