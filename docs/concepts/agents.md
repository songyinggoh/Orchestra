# Agents

Agents are the core building blocks in Orchestra. An agent wraps an LLM with a system prompt, tools, and configuration. Orchestra supports two styles of agent definition.

## Class-Based Agents

Subclass `BaseAgent` for production agents with full control:

```python
from orchestra import BaseAgent
from orchestra.core.context import ExecutionContext
from orchestra.core.types import AgentResult

class Researcher(BaseAgent):
    name: str = "researcher"
    model: str = "gpt-4o-mini"
    system_prompt: str = "You are a research analyst. Find key facts."
    temperature: float = 0.3

    async def run(self, input, context: ExecutionContext) -> AgentResult:
        # Custom logic before/after LLM call
        result = await super().run(input, context)
        return result
```

### Configuration Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | `"agent"` | Identifier used in logs and graph |
| `model` | `str` | `"gpt-4o-mini"` | Model name passed to the LLM provider |
| `system_prompt` | `str` | `"You are a helpful assistant."` | System message prepended to all calls |
| `tools` | `list` | `[]` | Tools the agent can call |
| `max_iterations` | `int` | `10` | Max tool-call loops before raising an error |
| `temperature` | `float` | `0.7` | LLM sampling temperature |
| `output_type` | `type` | `None` | Pydantic model for structured output validation |

## Decorator-Based Agents

Use `@agent` for rapid prototyping. The function's docstring becomes the system prompt:

```python
from orchestra import agent

@agent(model="gpt-4o-mini", temperature=0.3)
async def researcher(topic: str) -> str:
    """You are a research analyst. Find key facts about the given topic."""
```

The decorator returns a `DecoratedAgent` instance (a `BaseAgent` subclass) that you can wire into graphs like any other agent.

## Agents with Tools

Attach tools to agents so they can call functions during their reasoning loop:

```python
from orchestra import BaseAgent, tool

@tool
async def web_search(query: str) -> str:
    """Search the web for information."""
    return f"Results for: {query}"

researcher = BaseAgent(
    name="researcher",
    system_prompt="Research the topic. Use web_search for information.",
    tools=[web_search],
)
```

When the LLM requests a tool call, the agent executes it automatically and feeds the result back to the LLM. This loop continues until the LLM responds without tool calls or `max_iterations` is reached.

## Using Agents in Graphs

Agents can be added to graphs directly — Orchestra wraps them in `AgentNode` automatically:

```python
from orchestra import WorkflowGraph

graph = WorkflowGraph().then(researcher).then(writer)
```

When an agent node executes, it:

1. Reads input from the state (checking `messages` first, then `input`, then `output`)
2. Calls the agent's `run()` method with an `ExecutionContext`
3. Writes the agent's output back to the state's `output` field

## Structured Output

Validate agent responses against a Pydantic model:

```python
from pydantic import BaseModel

class Analysis(BaseModel):
    summary: str
    confidence: float
    key_points: list[str]

analyst = BaseAgent(
    name="analyst",
    system_prompt="Analyze the topic and return structured JSON.",
    output_type=Analysis,
)
```

The agent will attempt to parse the LLM's response as JSON and validate it against `Analysis`. If validation fails, a warning is logged and `structured_output` is `None` on the result.
