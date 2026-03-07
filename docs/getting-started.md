# Getting Started

This guide walks you through installation, creating your first agent workflow, running it, and writing a test — all in under 15 minutes.

## Installation

```bash
# From source
git clone https://github.com/orchestra-agents/orchestra.git
cd orchestra
pip install -e ".[dev]"

# Verify
python -c "import orchestra; print(orchestra.__version__)"
```

## Your First Workflow

Let's build a simple sequential pipeline: a researcher agent produces findings, then a writer agent turns them into an article.

### Step 1: Define Your State

Every workflow has a typed state that flows between nodes:

```python
from typing import Annotated, Any
from orchestra.core.state import WorkflowState, merge_list

class ArticleState(WorkflowState):
    topic: str = ""
    research: str = ""
    draft: str = ""
    log: Annotated[list[str], merge_list] = []
```

Fields annotated with reducers (like `merge_list`) accumulate values instead of overwriting them.

### Step 2: Define Node Functions

Each node is an async function that receives the current state dict and returns updates:

```python
async def research_node(state: dict[str, Any]) -> dict[str, Any]:
    topic = state["topic"]
    return {
        "research": f"Key findings about {topic}: [data here]",
        "log": [f"Researched: {topic}"],
    }

async def writer_node(state: dict[str, Any]) -> dict[str, Any]:
    research = state["research"]
    return {
        "draft": f"Article based on: {research}",
        "log": ["Wrote draft"],
    }
```

### Step 3: Build the Graph

Use the fluent API to connect nodes:

```python
from orchestra.core.graph import WorkflowGraph

graph = WorkflowGraph(state_schema=ArticleState)
graph = graph.then(research_node).then(writer_node)
```

Or use the explicit API for more control:

```python
from orchestra.core.types import END

graph = WorkflowGraph(state_schema=ArticleState)
graph.add_node("researcher", research_node)
graph.add_node("writer", writer_node)
graph.set_entry_point("researcher")
graph.add_edge("researcher", "writer")
graph.add_edge("writer", END)
```

### Step 4: Run It

```python
import asyncio
from orchestra import run

async def main():
    result = await run(graph, initial_state={"topic": "AI Agents"})
    print(result.state["draft"])
    print(result.state["log"])
    print(f"Completed in {result.duration_ms:.0f}ms")

asyncio.run(main())
```

Or use the sync wrapper:

```python
from orchestra import run_sync

result = run_sync(graph, initial_state={"topic": "AI Agents"})
```

### Step 5: Run from the CLI

Save your workflow as a Python file with a `main()` function and run it:

```bash
orchestra run my_workflow.py
```

## Your First Test

Orchestra includes `ScriptedLLM` for deterministic testing without API calls:

```python
import pytest
from orchestra.testing import ScriptedLLM
from orchestra import WorkflowGraph, BaseAgent, run

@pytest.mark.asyncio
async def test_research_workflow():
    # Create a mock LLM with scripted responses
    llm = ScriptedLLM([
        "Key findings about AI: transformers changed everything.",
        "Article: AI is transforming software development.",
    ])

    # Define agents that use the LLM
    researcher = BaseAgent(name="researcher", system_prompt="Research the topic.")
    writer = BaseAgent(name="writer", system_prompt="Write an article.")

    graph = WorkflowGraph().then(researcher).then(writer)
    result = await run(graph, input="AI Agents", provider=llm)

    assert "AI" in result.output
    llm.assert_all_consumed()  # Verify all responses were used
```

## Next Steps

- [Agents](concepts/agents.md) — Class-based and decorator-based agent patterns
- [Graphs](concepts/graphs.md) — Sequential, parallel, conditional, and loop patterns
- [State & Reducers](concepts/state.md) — Typed state with merge semantics
- [Testing](concepts/testing.md) — ScriptedLLM and assertion helpers
