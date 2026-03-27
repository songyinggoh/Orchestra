# Orchestra — Claude Code Guide

Orchestra is a Python multi-agent orchestration framework. If you already
use a cloud agentic provider — Claude Code, Gemini CLI, or OpenAI Codex
CLI — Orchestra works out of the box. No API keys, no env vars, no
separate billing.

## Quick start

```python
from orchestra.providers import auto_provider
from orchestra.core.agent import BaseAgent
from orchestra.core.context import ExecutionContext

provider = auto_provider()  # detects your CLI automatically

agent = BaseAgent(name="assistant", system_prompt="You are helpful.")
ctx = ExecutionContext(provider=provider)
result = await agent.run("your task here", ctx)
print(result.output)
```

## How `auto_provider()` picks a backend

It checks these in order and returns the first one found:

| # | What it looks for | Provider | Setup needed |
|---|---|---|---|
| 1 | `ORCHESTRA_BASE_URL` or `ORCHESTRA_API_KEY` env var | `HttpProvider` | Custom endpoint |
| 2 | `claude` CLI on PATH | `ClaudeCodeProvider` | **None** (uses subscription) |
| 3 | `gemini` CLI on PATH | `GeminiCliProvider` | **None** (uses subscription) |
| 4 | `codex` CLI on PATH | `CodexCliProvider` | **None** (uses subscription) |
| 5 | `ANTHROPIC_API_KEY` env var | `AnthropicProvider` | API key |
| 6 | `OPENAI_API_KEY` env var | `HttpProvider` | API key |
| 7 | `GOOGLE_API_KEY` env var | `GoogleProvider` | API key |
| 8 | Ollama on localhost:11434 | `OllamaProvider` | Install + run Ollama |

Options 2–4 use your existing cloud subscription — no separate billing.
If you already use Claude Code, Gemini CLI, or Codex CLI, just install
Orchestra and go.

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

## Pick a specific provider

Usually `auto_provider()` is all you need. To use a specific one:

```python
# Cloud agentic providers — use your existing subscription, no API key:
from orchestra.providers.claude_code import ClaudeCodeProvider
provider = ClaudeCodeProvider()  # default: sonnet

from orchestra.providers.gemini_cli import GeminiCliProvider
provider = GeminiCliProvider(model="gemini-2.5-pro")

from orchestra.providers.codex_cli import CodexCliProvider
provider = CodexCliProvider(model="o4-mini")

# Local (free):
from orchestra.providers.ollama import OllamaProvider
provider = OllamaProvider(default_model="llama3.1")

# Direct API access (requires API key):
from orchestra.providers.anthropic import AnthropicProvider
provider = AnthropicProvider()  # needs ANTHROPIC_API_KEY

from orchestra.providers.google import GoogleProvider
provider = GoogleProvider()  # needs GOOGLE_API_KEY

from orchestra.providers.http import HttpProvider
provider = HttpProvider()  # needs OPENAI_API_KEY or ORCHESTRA_API_KEY
```

## Source layout

```
src/orchestra/
  cache/         — in-memory and disk cache backends
  cli/           — CLI entry points
  core/          — agent, graph, runner, state, types, context
  cost/          — cost aggregator, tenant billing, persistent budget
  debugging/     — time-travel replay
  discovery/     — auto-discovery of agents, tools, and workflows
  identity/      — agent identity, DID, UCAN, delegation
  interop/       — A2A protocol, ZKP state commitments
  memory/        — tiered memory, embeddings, vector store, Redis backend
  messaging/     — NATS JetStream, DIDComm v2 E2EE
  observability/ — OpenTelemetry tracing and metrics
  providers/     — ClaudeCode, GeminiCli, CodexCli, Anthropic, Http, Google, Ollama, Callable, Failover
  reasoning/     — Tree of Thoughts structured reasoning
  reliability/   — SelfCheckGPT, FActScore hallucination detection
  routing/       — cost-aware router with Thompson Sampling
  security/      — guardrails, circuit breaker, rate limiter, PromptShield, ACL
  server/        — FastAPI HTTP server with SSE streaming
  storage/       — SQLite and Postgres run persistence
  testing/       — scripted test helpers
  tools/         — @tool decorator, built-in tools
tests/
  unit/          — 1069 tests, all mocked
  live/          — real-API tests (pytest tests/live/ -m live -v)
```
