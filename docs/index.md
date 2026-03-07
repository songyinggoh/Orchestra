# Orchestra

**Python-first multi-agent orchestration framework.**

Orchestra lets you define AI agents, compose them into typed graph workflows, and run them against real LLMs — with deterministic testing built in.

## Key Features

- **Graph-based workflows** — Compose agents into sequential, parallel, conditional, and loop patterns using a fluent API
- **Typed state** — Pydantic-based state with `Annotated` reducers for safe parallel fan-in
- **Provider-agnostic** — Built-in adapters for OpenAI and Anthropic, with a protocol for custom providers
- **Deterministic testing** — `ScriptedLLM` mock enables fast, reproducible tests without API calls
- **CLI included** — `orchestra run` executes workflows with structured logging out of the box

## Quick Example

```python
from orchestra import WorkflowGraph, WorkflowState, run_sync
from typing import Annotated, Any
from orchestra.core.state import merge_list

class ArticleState(WorkflowState):
    topic: str = ""
    draft: str = ""
    log: Annotated[list[str], merge_list] = []

async def research(state: dict[str, Any]) -> dict[str, Any]:
    return {"draft": f"Research on {state['topic']}", "log": ["researched"]}

async def write(state: dict[str, Any]) -> dict[str, Any]:
    return {"draft": f"Article: {state['draft']}", "log": ["wrote"]}

graph = WorkflowGraph(state_schema=ArticleState).then(research).then(write)
result = run_sync(graph, initial_state={"topic": "AI agents"})
print(result.state["draft"])
```

## Next Steps

- [Getting Started](getting-started.md) — Install and build your first workflow
- [Concepts](concepts/agents.md) — Learn about agents, graphs, state, and testing
- [API Reference](api/core.md) — Full API documentation
