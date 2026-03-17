# Orchestra — Claude Code Guide

Orchestra is a Python multi-agent orchestration framework installed in this project.
`ANTHROPIC_API_KEY` is already in your environment, so you can use Orchestra immediately
with no extra configuration.

## Zero-config start

```python
from orchestra.providers import auto_provider
from orchestra.core.agent import BaseAgent
from orchestra.core.context import ExecutionContext

provider = auto_provider()  # picks up ANTHROPIC_API_KEY automatically

agent = BaseAgent(name="assistant", system_prompt="You are helpful.")
ctx = ExecutionContext(provider=provider)
result = await agent.run("your task here", ctx)
print(result.output)
```

## Build a multi-agent graph

```python
from orchestra.core.graph import WorkflowGraph
from orchestra.core.runner import run
from orchestra.core.state import WorkflowState
from orchestra.core.types import END

class State(WorkflowState):
    input: str = ""
    output: str = ""

graph = WorkflowGraph(state_schema=State)
graph.add_node("agent", BaseAgent(name="agent"), output_key="output")
graph.set_entry_point("agent")
graph.add_edge("agent", END)

result = await run(graph, input={"input": "task"}, provider=provider, persist=False)
print(result.state["output"])
```

## Conditional routing

```python
graph.add_node("classifier", classifier, output_key="category")
graph.add_node("path_a", agent_a, output_key="output")
graph.add_node("path_b", agent_b, output_key="output")
graph.set_entry_point("classifier")
graph.add_conditional_edge(
    "classifier",
    lambda state: state["category"],          # routing function
    path_map={"a": "path_a", "b": "path_b"},
)
graph.add_edge("path_a", END)
graph.add_edge("path_b", END)
```

## Parallel fan-out

```python
from orchestra.core.state import merge_dict
from typing import Annotated

class State(WorkflowState):
    findings: Annotated[dict[str, str], merge_dict] = {}

graph.add_node("dispatch", lambda s: {})
graph.add_node("worker_a", worker_a)
graph.add_node("worker_b", worker_b)
graph.add_node("join", joiner)
graph.set_entry_point("dispatch")
graph.add_parallel("dispatch", ["worker_a", "worker_b"], join_node="join")
graph.add_edge("join", END)
```

## Tool calling

```python
from orchestra.tools.base import tool

@tool
async def search(query: str) -> str:
    """Search for information."""
    return f"results for: {query}"

agent = BaseAgent(
    name="researcher",
    tools=[search],
    max_iterations=3,
)
```

## Switch backends

`auto_provider()` checks env vars in this order — set whichever applies:

```bash
# Any OpenAI-compatible API (Groq, Together, Mistral, vLLM, LiteLLM, Azure, ...)
export ORCHESTRA_BASE_URL=https://api.groq.com/openai/v1
export ORCHESTRA_API_KEY=gsk_...
export ORCHESTRA_MODEL=llama-3.3-70b-versatile

# Anthropic (default when ANTHROPIC_API_KEY is set — already the case in Claude Code)
export ANTHROPIC_API_KEY=sk-ant-...

# OpenAI
export OPENAI_API_KEY=sk-...

# Google
export GOOGLE_API_KEY=AIza...

# Local — no key needed
ollama serve && ollama pull llama3.1
```

## Source layout

```
src/orchestra/
  core/          — agent, graph, runner, state, types, context
  providers/     — AnthropicProvider, HttpProvider, GoogleProvider, OllamaProvider, CallableProvider
  tools/         — @tool decorator, built-in tools
  observability/ — OpenTelemetry tracing and metrics
  reliability/   — circuit breaker, rate limiter, failover
  storage/       — SQLite and Postgres run persistence
tests/
  unit/          — 696 tests, all mocked
  live/          — real-API tests (pytest tests/live/ -m live -v)
```
