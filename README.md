# Orchestra

**The Python multi-agent framework that doesn't make you choose between simplicity and control.**

Production-grade graph workflows. Intuitive agent definition. Built-in observability, agent-level security, and a first-class testing framework. One `pip install`.

*More debuggable than CrewAI. Less verbose than LangGraph. More secure than both. Completely free.*

> **Status: v1.0 — Production Ready**
> All four phases of development are complete. Orchestra is installable, tested (comprehensive test suites across unit, integration, security, property, chaos, and load testing), and ready for production use. Code examples reflect the implemented API.

---

## Table of Contents

- [Why Orchestra?](#why-orchestra)
- [Key Features](#key-features)
- [Quick Start](#quick-start)
- [Core Concepts](#core-concepts)
  - [Agent Definition](#agent-definition)
  - [Workflow Graphs](#workflow-graphs)
  - [Typed State Management](#typed-state-management)
  - [Tool Integration](#tool-integration)
  - [Testing Framework](#testing-framework)
- [Architecture](#architecture)
- [Progressive Infrastructure](#progressive-infrastructure)
- [Observability](#observability)
- [Security Model](#security-model)
- [Memory System](#memory-system)
- [Cost Management](#cost-management)
- [LLM Provider Support](#llm-provider-support)
- [Competitive Comparison](#competitive-comparison)
- [Tech Stack](#tech-stack)
- [Contributing](#contributing)
- [License](#license)

---

## Why Orchestra?

Every multi-agent framework forces a tradeoff between simplicity and control:

```
                    SIMPLICITY
                        ^
                        |
          CrewAI ------+------ Swarm
          (hits ceiling)       (no persistence)
                        |
    Orchestra ==========#==========  <-- THE GAP
    (progressive        |
     complexity)        |
                        |
         AutoGen ------+------ LangGraph
         (steep learning)      (verbose)
                        |
                        v
                    CONTROL
```

Orchestra resolves this with **progressive complexity**: simple patterns stay simple, complex patterns stay possible, and the transition between them is smooth. You never outgrow the framework.

### The Problem with Every Other Framework

- **LangGraph** has the best architecture — explicit state graphs, reducers — but punishing DX. Fifty lines to do what Swarm does in five.
- **CrewAI** has the best DX (role/goal/backstory) but hides the graph entirely. Debugging is guesswork. Complex patterns are inexpressible.
- **AutoGen** has a sophisticated distributed model but a steep learning curve, made worse by the breaking 0.4 redesign.
- **None of them** offer a credible agent testing story, agent-level security, intelligent cost routing, or zero-infrastructure time-travel debugging.

Orchestra fills every one of these gaps.

---

## Key Features

| Feature | Phase | Description |
|---|---|---|
| **Graph Workflow Engine** | 1 | Full directed graph with sequential, parallel, conditional, loop, and handoff edges. Compile-time validation catches errors before runtime. |
| **Typed State with Reducers** | 1 | Pydantic-based state with `Annotated` reducer functions for deterministic concurrent state merges. |
| **First-Class Testing** | 1-3 | `ScriptedLLM` for deterministic, zero-API-call unit tests. No mocking boilerplate — pass it directly as a provider. |
| **Event-Sourced Persistence** | 2 | Every state transition is an immutable event. Enables time-travel debugging, audit trails, and workflow resumability. |
| **Zero-Infrastructure Observability** | 2-3 | Rich terminal trace tree and time-travel debugging (Phase 2). OpenTelemetry and cost waterfall (Phase 3). |
| **MCP + A2A Support** | 2, 4 | First-class MCP client integration (Phase 2). A2A Agent Cards for cross-framework interoperability (Phase 4). |
| **Multi-Tier Memory** | 3 | Working, short-term, long-term (semantic/pgvector), and entity memory with a unified manager. |
| **Guardrails Middleware** | 3 | Content filtering, PII detection, and cost limits as composable middleware on agent nodes. |
| **Progressive Infrastructure** | 3-4 | Same code runs on SQLite + asyncio locally, PostgreSQL + Redis + Kubernetes in production. |
| **Intelligent Cost Router** | 4 | Complexity profiling + auto-routing to cost-optimal models. Per-agent and per-workflow budget enforcement. |
| **Capability-Based Agent Security** | 4 | Agent identity with scoped permissions, tool-level ACLs, and circuit breakers. |
| **Dynamic Subgraphs** | 4 | `SubgraphBuilder` generates new sub-nodes and edges at runtime — no other framework supports runtime graph mutation. |

---

## Quick Start

### Installation

```bash
pip install orchestra-agents    # Requires Python 3.11+
```

### Zero-Config Setup in an AI Coding Assistant

Orchestra works with **any LLM backend** and needs **zero configuration** inside AI coding assistants. When you open this project in Claude Code, Gemini CLI, Cursor, or GitHub Copilot, the assistant's API key is already in the environment — `auto_provider()` picks it up automatically:

```python
from orchestra.providers import auto_provider

provider = auto_provider()  # reads whatever key is available — no setup needed
```

| Assistant | What it detects | Context file |
|---|---|---|
| Claude Code | `claude` CLI on PATH | `CLAUDE.md` |
| Gemini CLI | `gemini` CLI on PATH | `GEMINI.md` |
| OpenAI Codex | `codex` CLI on PATH | `AGENTS.md` |
| Cursor | any configured key | `.cursor/rules/orchestra.mdc` |
| GitHub Copilot | any configured key | `.github/copilot-instructions.md` |

### Manual Provider Configuration

`auto_provider()` checks in priority order:

```bash
# 1. Any OpenAI-compatible API — Groq, Together, Mistral, vLLM, LiteLLM, Azure, ...
export ORCHESTRA_BASE_URL=https://api.groq.com/openai/v1
export ORCHESTRA_API_KEY=gsk_...
export ORCHESTRA_MODEL=llama-3.3-70b-versatile

# 2. Named providers (auto-detected when their key is set)
export ANTHROPIC_API_KEY=sk-ant-...   # → AnthropicProvider
export OPENAI_API_KEY=sk-...          # → HttpProvider (OpenAI)
export GOOGLE_API_KEY=AIza...         # → GoogleProvider

# 3. Local — no key needed
ollama serve && ollama pull llama3.1  # → OllamaProvider
```

### Your First Agent

```python
import asyncio
from orchestra import BaseAgent, ExecutionContext
from orchestra.providers import auto_provider

provider = auto_provider()

agent = BaseAgent(
    name="greeter",
    system_prompt="You are a friendly assistant. Greet the user by name.",
)
ctx = ExecutionContext(provider=provider)
result = asyncio.run(agent.run("Alice", ctx))
print(result.output)   # AgentResult with .output, .messages, .token_usage, .tool_calls_made
```

### Your First Workflow

```python
import asyncio
from orchestra import BaseAgent, WorkflowGraph, WorkflowState, run, END
from orchestra.providers import auto_provider

class ResearchState(WorkflowState):
    query: str = ""
    research: str = ""
    report: str = ""

provider = auto_provider()

researcher = BaseAgent(name="researcher", system_prompt="You are a research analyst.")
writer = BaseAgent(name="writer", system_prompt="You are a technical writer.")

graph = WorkflowGraph(state_schema=ResearchState)
graph.add_node("research", researcher, output_key="research")
graph.add_node("write", writer, output_key="report")
graph.set_entry_point("research")
graph.add_edge("research", "write")
graph.add_edge("write", END)

result = asyncio.run(
    run(graph, input={"query": "Latest advances in multi-agent systems"}, provider=provider)
)
print(result.state["report"])
```

### Parallel Fan-Out with Conditional Routing

```python
import asyncio
from typing import Annotated, Any
from orchestra import BaseAgent, WorkflowGraph, WorkflowState, run, END
from orchestra.core.state import merge_dict
from orchestra.core.context import ExecutionContext
from orchestra.providers import auto_provider

class AnalysisState(WorkflowState):
    topic: str = ""
    findings: Annotated[dict[str, str], merge_dict] = {}
    synthesis: str = ""

provider = auto_provider()

tech = BaseAgent(name="tech", system_prompt="Identify 2-3 key technical trends. Be concise.")
market = BaseAgent(name="market", system_prompt="Identify 2-3 key market trends. Be concise.")
synthesizer = BaseAgent(name="synthesizer", system_prompt="Synthesize findings into a brief summary.")

# Fan-out using plain async functions to control state mapping
async def run_tech(state: dict[str, Any]) -> dict[str, Any]:
    ctx = ExecutionContext(provider=provider)
    result = await tech.run(state["topic"], ctx)
    return {"findings": {"technical": result.output}}

async def run_market(state: dict[str, Any]) -> dict[str, Any]:
    ctx = ExecutionContext(provider=provider)
    result = await market.run(state["topic"], ctx)
    return {"findings": {"market": result.output}}

async def run_synthesizer(state: dict[str, Any]) -> dict[str, Any]:
    ctx = ExecutionContext(provider=provider)
    findings = "\n".join(f"[{k}] {v}" for k, v in state["findings"].items())
    result = await synthesizer.run(findings, ctx)
    return {"synthesis": result.output}

graph = WorkflowGraph(state_schema=AnalysisState)
graph.add_node("dispatch", lambda s: {})   # fan-out root
graph.add_node("tech", run_tech)
graph.add_node("market", run_market)
graph.add_node("synthesizer", run_synthesizer)
graph.set_entry_point("dispatch")
graph.add_parallel("dispatch", ["tech", "market"], join_node="synthesizer")
graph.add_edge("synthesizer", END)

result = asyncio.run(
    run(graph, input={"topic": "AI agents in production"}, provider=provider)
)
print(result.state["synthesis"])
```

### Deterministic Unit Testing

```python
import pytest
from orchestra import BaseAgent, WorkflowGraph, WorkflowState, run, END
from orchestra.testing import ScriptedLLM

class MyState(WorkflowState):
    query: str = ""
    research: str = ""
    report: str = ""

researcher = BaseAgent(name="researcher", system_prompt="Research analyst.")
writer = BaseAgent(name="writer", system_prompt="Technical writer.")

graph = WorkflowGraph(state_schema=MyState)
graph.add_node("research", researcher, output_key="research")
graph.add_node("write", writer, output_key="report")
graph.set_entry_point("research")
graph.add_edge("research", "write")
graph.add_edge("write", END)

@pytest.mark.asyncio
async def test_research_workflow():
    # ScriptedLLM returns responses in order — no API calls, no mocking
    provider = ScriptedLLM([
        "Multi-agent systems have evolved significantly...",  # researcher
        "## Research Report\n\nKey findings include...",     # writer
    ])
    result = await run(graph, input={"query": "test query"}, provider=provider, persist=False)

    assert "Key findings" in result.state["report"]
    assert result.node_execution_order == ["research", "write"]
```

---

## Core Concepts

### Agent Definition

Define agents with `BaseAgent` — provide a name, system prompt, and optionally tools and model:

```python
from orchestra import BaseAgent, tool

@tool
async def web_search(query: str) -> str:
    """Search the web for information."""
    ...

researcher = BaseAgent(
    name="researcher",
    system_prompt="You are a senior research analyst. Find accurate, sourced information.",
    model="gpt-4o",          # defaults to gpt-4o-mini
    tools=[web_search],
    temperature=0.7,
    max_iterations=10,
)
```

Run an agent directly, outside a workflow:

```python
from orchestra import ExecutionContext
from orchestra.providers import auto_provider

ctx = ExecutionContext(provider=auto_provider())
result = await researcher.run("What are the latest AI safety techniques?", ctx)
print(result.output)
print(result.tool_calls_made)
print(result.token_usage)
```

### Workflow Graphs

The graph engine is Orchestra's core. It can express any orchestration pattern:

```python
from orchestra import WorkflowGraph, END

graph = WorkflowGraph(state_schema=MyState)

# Sequential
graph.add_edge("A", "B")

# Conditional branching
def route(state: dict) -> str:
    return "fast" if state.get("simple") else "thorough"

graph.add_conditional_edge("B", route, path_map={"fast": "C", "thorough": "D"})

# Parallel fan-out with join
graph.add_parallel("E", ["F", "G", "H"], join_node="I")

# Swarm-style handoff
graph.add_handoff("C", "D", condition=lambda s: s.get("needs_escalation"))

# Compile validates the graph (unreachable nodes, type mismatches, cycles)
compiled = graph.compile()
```

`run()` accepts both a `WorkflowGraph` and a `CompiledGraph` — it compiles automatically if needed.

**Node Types:**

| Node | Description |
|---|---|
| `AgentNode` | Wraps a `BaseAgent` — executes the agent's reasoning loop |
| `FunctionNode` | Wraps a plain async Python function — deterministic transformations |
| `SubgraphNode` | Embeds a pre-compiled graph — reusable workflow composition |
| `SubgraphBuilder` | Generates sub-nodes and edges at runtime (`core/dynamic.py`) — plan-and-execute, adaptive workflows |

### Typed State Management

State is defined as subclasses of `WorkflowState` (a Pydantic `BaseModel`) with `Annotated` reducer functions for deterministic concurrent merges:

```python
from typing import Annotated
from orchestra import WorkflowState
from orchestra.core.state import merge_list, merge_dict, sum_numbers

class MyState(WorkflowState):
    messages: Annotated[list[str], merge_list] = []
    results: Annotated[dict[str, str], merge_dict] = {}
    step_count: Annotated[int, sum_numbers] = 0
    current_agent: str = ""
```

**Built-in reducers:** `merge_list`, `merge_dict`, `merge_set`, `sum_numbers`, `last_write_wins`, `concat_str`, `keep_first`

When parallel agents write to the same state field, reducers guarantee deterministic, conflict-free merges.

### Tool Integration

Decorate any async function with `@tool` to make it available to agents:

```python
from orchestra import BaseAgent, tool

@tool
async def web_search(query: str) -> str:
    """Search the web for information."""
    ...

@tool
async def read_file(path: str) -> str:
    """Read a file from the filesystem."""
    ...

agent = BaseAgent(
    name="researcher",
    system_prompt="Research analyst with web access.",
    tools=[web_search, read_file],
)
```

Orchestra is **MCP-first** for external tool integration:

```python
from orchestra.tools import MCPClient

async with MCPClient.stdio("npx", ["@modelcontextprotocol/server-github"]) as client:
    github_tools = client.get_tools()
```

Tool-level ACLs restrict which agents can invoke which tools:

```python
from orchestra.security.acl import ToolACL

researcher_acl = ToolACL.allow_list(["web_search", "read_file"])
writer_acl = ToolACL.deny_list(["web_search"])  # allows all tools except web_search
```

### Testing Framework

`ScriptedLLM` is a drop-in provider that returns pre-scripted responses in sequence. Pass it wherever you'd pass a real provider — no monkeypatching, no context managers:

```python
from orchestra.testing import ScriptedLLM

provider = ScriptedLLM([
    "I'll research that now...",           # response 1 (researcher turn 1)
    "Here is the final report...",         # response 2 (writer turn 1)
])

result = await run(graph, input={"query": "test"}, provider=provider, persist=False)
```

For chaos and resilience testing, use `CallableProvider` to simulate failures:

```python
from orchestra.providers import CallableProvider
import random

async def flaky_model(prompt: str) -> str:
    if random.random() < 0.3:
        raise ConnectionError("Simulated timeout")
    return "Response"

provider = CallableProvider(flaky_model)
result = await run(graph, input={"query": "test"}, provider=provider, persist=False)
```

---

## Architecture

### Project Structure

```
src/orchestra/                  # installable package
  __init__.py                   # Public API: BaseAgent, WorkflowGraph, run, WorkflowState, ...
  core/                         # Graph engine, agents, state, execution
    agent.py                    # BaseAgent, @agent decorator
    graph.py                    # WorkflowGraph, fluent API (.then/.parallel/.branch)
    nodes.py                    # AgentNode, FunctionNode, SubgraphNode
    dynamic.py                  # SubgraphBuilder — runtime graph construction
    edges.py                    # Edge, ConditionalEdge, ParallelEdge
    handoff.py                  # HandoffEdge — swarm-style agent transfers
    compiled.py                 # CompiledGraph — validated execution plan
    state.py                    # WorkflowState, reducer functions
    context.py                  # ExecutionContext
    runner.py                   # run(), run_sync(), RunResult
    types.py                    # Message, AgentResult, TokenUsage, END, START
    errors.py                   # Framework exception hierarchy
    protocols.py                # LLMProvider and Tool protocols
    hotreload.py                # GraphHotReloader — live graph reload without restart
  providers/                    # LLM provider adapters
    __init__.py                 # auto_provider() factory
    http.py                     # HttpProvider — any OpenAI-compatible API
    anthropic.py                # AnthropicProvider
    google.py                   # GoogleProvider (Gemini)
    ollama.py                   # OllamaProvider (local)
    callable.py                 # CallableProvider — wrap any function as a provider
    claude_code.py              # ClaudeCodeProvider (CLI subscription)
    gemini_cli.py               # GeminiCliProvider (CLI subscription)
    codex_cli.py                # CodexCliProvider (CLI subscription)
  tools/                        # Tool system
    base.py                     # @tool decorator, Tool protocol
    registry.py                 # ToolRegistry
    mcp.py                      # MCPClient, MCPToolAdapter
  memory/                       # Memory backends and utilities
    manager.py                  # MemoryManager protocol + InMemoryMemoryManager
    backends.py                 # Storage backends
    tiers.py                    # Multi-tier memory (working / session / semantic)
    vector_store.py             # pgvector semantic search
    embeddings.py               # Embedding helpers
  storage/                      # Persistence layer
    store.py                    # Storage protocol
    events.py                   # EventStore, event sourcing
    checkpoint.py               # Checkpoint management
    sqlite.py                   # Dev backend
    postgres.py                 # Production backend
  cache/                        # Response and state caching
    backends.py                 # In-memory and Redis cache backends
  observability/                # Tracing, metrics, logging
    tracing.py                  # OpenTelemetry span management
    metrics.py                  # OTelMetricsSubscriber — token usage and cost metrics
    _otel_setup.py              # OTel exporter configuration
  security/                     # Guardrails and access control
    acl.py                      # ToolACL — per-tool allow/deny lists
    guardrails.py               # GuardedAgent, GuardrailChain, ContentFilter, PIIDetector
    circuit_breaker.py          # Agent-level circuit breakers
  identity/                     # Cryptographic agent identity
    agent_identity.py           # AgentIdentity (DID + UCAN)
    ucan.py                     # UCAN token issuance and verification
    delegation.py               # Capability delegation chain
    did.py                      # DID document helpers
  routing/                      # Cost-aware model routing
    router.py                   # CostAwareRouter, ThompsonModelSelector
    types.py                    # ModelOption, RoutingDecision, BudgetConstraint
  cost/                         # Budget enforcement and cost tracking
    budget.py                   # WorkflowBudget, per-agent limits
    aggregator.py               # Cost aggregation across runs
    persistent_budget.py        # Cross-session budget persistence
  messaging/                    # NATS-based E2EE messaging
    client.py                   # NATS client
    publisher.py / consumer.py  # Pub/sub helpers
  interop/                      # Cross-framework interoperability
    a2a.py                      # A2A Agent Cards protocol
  reliability/                  # Hallucination detection
    selfcheck.py                # SelfCheckGPT — stochastic consistency scoring
    factscore.py                # FActScore atomic-fact verification
    tools.py                    # Orchestra tool wrappers for reliability checks
  debugging/                    # Time-travel debugging
    timetravel.py               # State reconstruction and replay
  discovery/                    # Agent and tool auto-discovery
    scanner.py                  # File-system scanning
    hotreload.py                # Live hot-reload support
  reasoning/                    # Tree of Thoughts reasoning helpers
  server/                       # HTTP server (FastAPI + SSE)
    app.py
    routes/                     # graphs, runs, streams, health endpoints
  testing/                      # ScriptedLLM and test utilities
  cli/                          # orchestra init, run, test, serve
sdk/typescript/                 # TypeScript SDK
```

The `core/` module has **zero upward dependencies** — it depends only on Protocol interfaces, making it straightforward to test in isolation.

---

## Progressive Infrastructure

Orchestra scales from a laptop to a Kubernetes cluster without touching your agent or workflow code:

| Stage | Storage | Messaging | Observability | Execution |
|---|---|---|---|---|
| **Local Dev** | SQLite + in-memory | asyncio.Queue | Rich console | Single process |
| **Team Staging** | PostgreSQL | NATS JetStream | Jaeger / Grafana | Docker Compose |
| **Production** | PostgreSQL + Redis | NATS JetStream | OTel + Datadog/Honeycomb | Kubernetes / KEDA |

**Same code. Same graphs. Same agents. Only configuration changes.**

---

## Observability

- **Rich Console Tracer** — Live terminal trace tree showing agent execution, tool calls, handoffs, and state transitions in real time during development.
- **Time-Travel Debugging** — Reconstruct and inspect state at any checkpoint. Modify state and resume from any point. No external services required.
- **Cost Waterfall** — Visualize token usage and estimated cost per agent, per turn, directly in the terminal.
- **OpenTelemetry** — Vendor-neutral traces, metrics, and logs. Export to Jaeger, Datadog, Honeycomb, or any OTel-compatible backend.
- **Structured Logging** — structlog with auto-detection: human-readable in dev, JSON in production.

---

## Security Model

Orchestra provides a capability-based agent identity and access management system.

### Agent Identity

Each agent has a cryptographic identity (DID + UCAN delegation) for zero-trust cross-agent authorization. Identities are created via the factory method in `orchestra.identity`:

```python
from orchestra.identity.agent_identity import AgentIdentity

# AgentIdentity.create() generates signing + encryption keys automatically
identity = AgentIdentity.create()
```

Tool-level access control uses `ToolACL` — attach one to any `BaseAgent` via the `acl` parameter:

```python
from orchestra.security.acl import ToolACL
from orchestra import BaseAgent

researcher = BaseAgent(
    name="researcher",
    system_prompt="Research analyst.",
    acl=ToolACL.allow_list(["web_search", "read_file"]),
)
```

### Guardrails Middleware

Composable pre/post hooks applied via `GuardedAgent`. Pass `GuardrailChain` instances for input and/or output validation:

```python
from orchestra.security.guardrails import GuardedAgent, GuardrailChain, ContentFilter, PIIDetector

sensitive_agent = GuardedAgent(
    name="sensitive",
    system_prompt="You are a helpful assistant.",
    input_guardrails=GuardrailChain([ContentFilter(), PIIDetector()]),
    output_guardrails=GuardrailChain([PIIDetector()]),
)
```

### Two Security Modes

- **Dev mode** — All agents have all permissions. Zero friction during prototyping.
- **Prod mode** — Explicit grants required. Deny-by-default. Full audit trail.

---

## Memory System

Three-tier memory architecture:

| Tier | Latency | Backend | Use Case |
|---|---|---|---|
| **Hot** (in-process) | <0.01ms | In-process SLRU bounded cache | Active context window |
| **Warm** (L2 cache) | 0.5–2ms | Redis | Short-term session state |
| **Cold** (semantic) | 5–50ms | pgvector | Long-term semantic search |

`TieredMemoryManager` provides a unified interface that automatically promotes and demotes entries across tiers based on access patterns. `MemoryManager` is the simplified store/retrieve protocol for agents that don't need tier control.

---

## Cost Management

- **Complexity Profiling** — Analyze task complexity before dispatching to an LLM.
- **Intelligent Cost Router** — Route simple tasks to cheap models (GPT-4o-mini, Haiku) and complex reasoning to capable ones (GPT-4o, Opus) — automatically.
- **Budget Enforcement** — Per-workflow and per-agent token budgets with automatic degradation rather than hard failure.
- **Cost Attribution** — Track spend per agent, per workflow, per user.

```python
from orchestra.routing.router import CostAwareRouter, ModelOption
from orchestra.routing.types import BudgetConstraint

router = CostAwareRouter(cost_weight=0.7, capability_weight=0.3)

options = [
    ModelOption("gpt-4o-mini", "openai", input_cost_1k=0.00015, capability_score=2),
    ModelOption("claude-haiku-4-5", "anthropic", input_cost_1k=0.00025, capability_score=3),
    ModelOption("gpt-4o", "openai", input_cost_1k=0.005, capability_score=5),
]

budget = BudgetConstraint(max_cost_usd=0.01)
decision = await router.select_model(
    options,
    task_description="complex reasoning task",
    budget=budget,
)
# decision.model.model_name -> the selected model
```

---

## LLM Provider Support

Orchestra works with **any LLM backend** through a unified `LLMProvider` Protocol. Backend-agnosticism is a core design principle, not an afterthought.

### Built-in Providers

| Provider | Activated by | Models |
|---|---|---|
| `HttpProvider` | `ORCHESTRA_API_KEY` or `OPENAI_API_KEY` | GPT-4o, o1, o3, and any OpenAI-compatible model |
| `AnthropicProvider` | `ANTHROPIC_API_KEY` | Claude Opus 4, Sonnet, Haiku |
| `GoogleProvider` | `GOOGLE_API_KEY` | `gemini-2.0-flash`, `gemini-2.0-flash-lite`, `gemini-2.5-pro-preview-06-05`, `gemini-2.5-flash-preview-05-20` |
| `OllamaProvider` | Ollama running at localhost:11434 | Any `ollama pull` model — completely free |

### Any OpenAI-Compatible API

`HttpProvider` speaks the OpenAI chat completions format — the de facto industry standard. That covers Groq, Together, Mistral, vLLM, LiteLLM, Azure OpenAI, Perplexity, and any self-hosted endpoint:

```bash
export ORCHESTRA_BASE_URL=https://api.groq.com/openai/v1
export ORCHESTRA_API_KEY=gsk_...
export ORCHESTRA_MODEL=llama-3.3-70b-versatile
```

```python
provider = auto_provider()  # done
```

### Wrap Any Callable

```python
from orchestra.providers import CallableProvider

# Cohere, HuggingFace, a local model, a LangChain chain — anything callable
async def my_llm(prompt: str) -> str:
    return await my_custom_model.generate(prompt)

provider = CallableProvider(my_llm)
```

### Write a Custom Provider

Any object implementing `.complete()`, `.stream()`, `.count_tokens()`, and `.get_model_cost()` works as a provider. No base class registration required — pass it directly to `run()`.

---

## Competitive Comparison

| Capability | Orchestra | LangGraph | CrewAI | AutoGen | OpenAI SDK |
|---|---|---|---|---|---|
| Graph workflows | Full | Full | Basic | None | None |
| Dynamic subgraphs | Yes | No | No | No | No |
| Agent DX quality | High | Low | Highest | Medium | Medium |
| Multi-model support | **All backends** | All | All (LiteLLM) | All | OpenAI only |
| Time-travel debug | Built-in (free) | LangSmith (paid) | No | No | No |
| Testing framework | ScriptedLLM | Manual | train() only | Manual | Manual |
| Agent IAM/security | Capability-based | None | None | Docker only | Guardrails |
| Cost routing | Intelligent | None | None | None | None |
| HITL | Full + escalation | Best | Manager | Human input | None |
| Observability | OTel + Rich (free) | LangSmith (paid) | Logs | Basic OTel | Traces |
| MCP support | Client | Client | None | Client | None |
| Pricing | **100% Free** | Free + paid cloud | Free + paid enterprise | Free | Free |

---

## Tech Stack

| Dimension | Choice | Rationale |
|---|---|---|
| Language | Python 3.11+ | LLM ecosystem is Python-first |
| Async Runtime | asyncio | Zero-infrastructure default |
| Data Validation | Pydantic v2 | Rust-backed performance, type safety |
| State Storage | SQLite (dev) / PostgreSQL + pgvector (prod) | Event-sourced workflow state + semantic memory |
| Hot Cache | In-memory (dev) / Redis 7+ (prod) | Session state, tool result caching |
| API Layer | FastAPI + SSE | REST + real-time streaming |
| Observability | OpenTelemetry + structlog + Rich | Vendor-neutral + beautiful local DX |
| CLI | Typer | Clean command-line interface |
| Testing | pytest-asyncio | Native async test support |

**Core dependency count:** 6 required packages (`pydantic`, `httpx`, `structlog`, `rich`, `typer`, `mcp`). LLM providers, NATS, Redis, and pgvector are optional extras.

---

## Contributing

Orchestra is 100% free and open-source under Apache 2.0.

```bash
git clone https://github.com/songyinggoh/multi-agent-orchestration-framework.git
cd multi-agent-orchestration-framework
pip install -e ".[dev,server,security,storage]"
pytest
```

To run the live end-to-end demo against a real model:

```bash
python examples/live.py                           # auto-detect provider
python examples/live.py --provider ollama         # local, no API key needed
python examples/live.py --provider openai --model gpt-4o-mini
```

### Workflow

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Write tests using `ScriptedLLM` for deterministic assertions
4. Ensure all tests pass (`pytest`)
5. Submit a pull request

### Code Style

- Python 3.11+ with type annotations throughout
- `async/await` for all I/O-bound operations
- Pydantic models for data validation and serialization
- Protocol-first design (structural subtyping over inheritance)

---

## License

Orchestra is released under the **Apache License 2.0**. All features are free. No paid tiers. No proprietary lock-in.
