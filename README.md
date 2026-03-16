# Orchestra

**A Python-first multi-agent orchestration framework that combines production-grade graph workflows with intuitive agent definition, built-in observability, agent-level security, and a first-class testing framework — all from a single `pip install`.**

*More debuggable than CrewAI, less verbose than LangGraph, more secure than both, and completely free.*

> **Status: v1.0 — Production Ready**
> All four phases of development are complete. Orchestra is installable, tested (701 tests passing across unit, integration, security, property, chaos, and load suites), and ready for production use. Code examples reflect the implemented API.

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
  - [Project Structure](#project-structure)
  - [Module Dependency Map](#module-dependency-map)
- [Progressive Infrastructure](#progressive-infrastructure)
- [Observability](#observability)
- [Human-in-the-Loop (HITL)](#human-in-the-loop-hitl)
- [Security Model](#security-model)
- [Memory System](#memory-system)
- [Cost Management](#cost-management)
- [LLM Provider Support](#llm-provider-support)
- [Competitive Comparison](#competitive-comparison)
- [Tech Stack](#tech-stack)
- [Roadmap](#roadmap)
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

Orchestra resolves this with **progressive complexity**: simple patterns are simple, complex patterns are possible, and the transition between them is smooth. You never outgrow the framework.

### The Problem

- **LangGraph** has the best architecture (explicit state graphs, reducers) but the worst DX — 50 lines to do what Swarm does in 5.
- **CrewAI** has the best DX (role/goal/backstory) but hides the graph entirely, making debugging impossible and complex patterns inexpressible.
- **AutoGen** has the most sophisticated distributed model but a steep learning curve that was broken further by the 0.4 redesign.
- **No framework** offers a credible agent testing story, agent-level security, intelligent cost routing, or zero-infrastructure time-travel debugging.

Orchestra fills every one of these gaps.

---

## Key Features

| Feature | Phase | Description |
|---|---|---|
| **Graph Workflow Engine** | 1 | Full directed graph with sequential, parallel, conditional, loop, and handoff edges. Compile-time validation catches errors before runtime. |
| **Hybrid Agent Definition** | 1 | Class-based (CrewAI-style), decorator-based (Pythonic), or config-based (YAML). All produce the same internal `AgentSpec`. |
| **Typed State with Reducers** | 1 | Pydantic-based state with `Annotated` reducer functions for deterministic concurrent state merges. |
| **First-Class Testing** | 1-3 | `ScriptedLLM` for deterministic unit tests (Phase 1). `SimulatedLLM` and `FlakyLLM` for integration and chaos testing (Phase 3). |
| **Event-Sourced Persistence** | 2 | Every state transition is an immutable event. Enables time-travel debugging, audit trails, and workflow resumability. |
| **Zero-Infrastructure Observability** | 2-3 | Rich terminal trace tree and time-travel debugging (Phase 2). OpenTelemetry and cost waterfall (Phase 3). |
| **MCP + A2A Support** | 2, 4 | First-class MCP client integration (Phase 2). A2A Agent Cards for cross-framework interoperability (Phase 4). |
| **Multi-Tier Memory** | 3 | Working, short-term, long-term (semantic/pgvector), and entity memory with a unified manager. |
| **Guardrails Middleware** | 3 | Content filtering, PII detection, and cost limits as composable middleware on agent nodes. |
| **Progressive Infrastructure** | 3-4 | Same code runs on SQLite + asyncio locally, PostgreSQL + Redis + Kubernetes in production. |
| **Intelligent Cost Router** | 4 | Complexity profiling + auto-routing to cost-optimal models. Per-agent and per-workflow budget enforcement. |
| **Capability-Based Agent Security** | 4 | Agent identity with scoped permissions, tool-level ACLs, and circuit breakers. |
| **Dynamic Subgraphs** | 4 | `DynamicNode` generates new sub-nodes and edges at runtime — no other framework supports runtime graph mutation. |

---

## Quick Start

### Installation

```bash
pip install orchestra-agents    # Requires Python 3.11+
```

### Configuration

Orchestra reads LLM provider credentials from environment variables:

```bash
export OPENAI_API_KEY="sk-..."        # Required for OpenAI models
export ANTHROPIC_API_KEY="sk-ant-..."  # Required for Anthropic models
export GOOGLE_API_KEY="..."            # Required for Google Gemini models
```

No other configuration is needed to get started. All infrastructure (storage, caching, observability) defaults to zero-infrastructure local mode.

### Your First Agent (5 lines)

```python
import asyncio
from orchestra import agent, run

@agent(name="greeter", model="gpt-4o")
async def greet(name: str) -> str:
    """You are a friendly assistant. Greet the user by name."""
    # The docstring becomes the system prompt. No function body needed.

result = asyncio.run(run(greet, input={"name": "Alice"}))
print(result.output)  # result is an AgentResult with .output, .messages, .token_usage, etc.
```

`run()` is an async function — use `asyncio.run()` at the top level, or `await run(...)` inside async code. When called with a single agent, `run()` returns an `AgentResult`. When called with a compiled workflow graph, it returns the workflow's state object. All examples below follow this pattern.

### Your First Workflow (20 lines)

```python
import asyncio
from orchestra import Agent, WorkflowGraph, run
from pydantic import BaseModel

class ResearchState(BaseModel):
    query: str = ""
    research: str = ""
    report: str = ""

researcher = Agent(name="researcher", role="Research Analyst", model="gpt-4o")
writer = Agent(name="writer", role="Technical Writer", model="gpt-4o")

graph = WorkflowGraph(state_schema=ResearchState)
graph.add_node("research", researcher)
graph.add_node("write", writer)
graph.add_edge("research", "write")
graph.set_entry_point("research")

workflow = graph.compile()
state = asyncio.run(run(workflow, input={"query": "Latest advances in multi-agent systems"}))
print(state.report)  # state is a ResearchState instance — access any field directly
```

### Parallel Fan-Out with Conditional Routing

```python
from orchestra import WorkflowGraph, END
from pydantic import BaseModel

class AnalysisState(BaseModel):
    text: str = ""
    sentiment: str = ""
    entities: list[str] = []
    summary: str = ""
    confidence: float = 0.0

graph = WorkflowGraph(state_schema=AnalysisState)

graph.add_node("classifier", classifier_agent)
graph.add_node("sentiment", sentiment_agent)
graph.add_node("entity_extract", entity_agent)
graph.add_node("summarizer", summarizer_agent)

graph.set_entry_point("classifier")

# Fan out to parallel analysis
graph.add_parallel(["sentiment", "entity_extract"], join_node="summarizer")

# Conditional exit
graph.add_conditional_edge("summarizer", lambda s: "end" if s.confidence > 0.9 else "classifier",
                           {"end": END, "classifier": "classifier"})

workflow = graph.compile()
```

### Deterministic Testing

```python
import pytest
from orchestra import run
from orchestra.testing import ScriptedLLM, WorkflowAssertions

@pytest.mark.asyncio
async def test_research_workflow():
    workflow = graph.compile()

    # ScriptedLLM is a context manager that intercepts all LLM calls
    with ScriptedLLM(script={
        "researcher": ["Multi-agent systems have evolved significantly..."],
        "writer": ["## Research Report\n\nKey findings include..."],
    }):
        result = await run(workflow, input={"query": "test query"})

    assertions = WorkflowAssertions(result)
    assertions.assert_node_executed("researcher")
    assertions.assert_node_executed("writer")
    assertions.assert_output_contains("Key findings")
```

---

## Core Concepts

### Agent Definition

Orchestra supports three agent definition styles that all produce the same internal representation:

#### Class-Based (Production)

```python
from orchestra import BaseAgent, Tool

class ResearchAgent(BaseAgent):
    name = "researcher"
    role = "Senior Research Analyst"
    goal = "Find accurate, sourced information"
    backstory = "You have 20 years of experience in investigative research."
    model = "gpt-4o"
    tools = [web_search, document_reader]
    output_type = ResearchReport  # Pydantic model for structured output
```

#### Decorator-Based (Prototyping)

```python
from orchestra import agent

@agent(name="researcher", model="gpt-4o", tools=[web_search])
async def research(query: str) -> ResearchReport:
    """You are a senior research analyst. Find accurate information and cite sources."""
```

#### Config-Based (No-Code)

```yaml
# agents/researcher.yaml
name: researcher
role: Senior Research Analyst
goal: Find accurate, sourced information
model: gpt-4o
tools: [web_search, document_reader]
```

### Workflow Graphs

The graph engine is Orchestra's core. It can express any orchestration pattern:

```python
graph = WorkflowGraph(state_schema=MyState)

# Sequential
graph.add_edge("A", "B")

# Conditional branching
graph.add_conditional_edge("B", route_fn, {"option1": "C", "option2": "D"})

# Swarm-style handoff
graph.add_handoff("C", "D", condition=lambda s: s.needs_escalation)

# Parallel fan-out with join
graph.add_parallel(["E", "F", "G"], join_node="H", join_strategy="wait_all")

# Bounded loops
graph.add_loop(["I", "J"], exit_condition=lambda s: s.is_done, max_iterations=10)

# Human-in-the-loop interrupts
graph.interrupt_before("review_node")

# Compile validates the graph (unreachable nodes, type mismatches, cycles)
workflow = graph.compile()
```

**Node Types:**

| Node | Description |
|---|---|
| `AgentNode` | Wraps an Agent — executes the agent's reasoning loop |
| `FunctionNode` | Wraps a plain Python function — deterministic transformations |
| `DynamicNode` | Generates sub-nodes and edges at runtime — plan-and-execute, adaptive workflows |
| `SubgraphNode` | Embeds a pre-compiled graph — reusable workflow composition |

### Typed State Management

State is defined as Pydantic models with `Annotated` reducer functions for deterministic concurrent merges:

```python
from typing import Annotated
from pydantic import BaseModel
from orchestra.core.state import merge_list, merge_dict, increment

class MyState(BaseModel):
    messages: Annotated[list[Message], merge_list] = []
    current_agent: str = ""
    results: Annotated[dict[str, str], merge_dict] = {}
    iteration: Annotated[int, increment] = 0
```

**Built-in reducers:** `merge_list`, `merge_dict`, `last_write_wins`, `increment`

When parallel agents write to the same state field, reducers ensure deterministic, conflict-free merges.

### Tool Integration

Orchestra is **MCP-first** for tool integration, with function-calling and a centralized registry:

```python
from orchestra.tools import tool, ToolRegistry, MCPClient

# Decorator-based tool definition
@tool
async def web_search(query: str) -> str:
    """Search the web for information."""
    ...

# MCP server integration
mcp = MCPClient("npx @modelcontextprotocol/server-github")
github_tools = await mcp.list_tools()

# Centralized registry with ACLs
registry = ToolRegistry()
registry.register(web_search)
registry.register_mcp(mcp)
registry.set_acl("researcher", allow=["web_search", "github_*"])
registry.set_acl("writer", allow=["web_search"], deny=["github_*"])
```

### Testing Framework

Orchestra provides a dedicated agent testing framework built into the orchestration layer — "pytest for agents":

| Mock | Purpose | Speed |
|---|---|---|
| `ScriptedLLM` | Deterministic responses for unit tests. Fully reproducible. | < 30s |
| `SimulatedLLM` | Cheap model with seed + temp=0 for integration tests. | < 10 min |
| `FlakyLLM` | Chaos testing — simulates timeouts, errors, partial failures. | Variable |

```python
# Unit test with ScriptedLLM
@pytest.mark.asyncio
async def test_research_workflow():
    workflow = graph.compile()

    with ScriptedLLM(script={
        "researcher": ["Finding 1: ...", "Finding 2: ..."],
        "writer": ["Final report based on findings..."],
    }):
        result = await run(workflow, input={"query": "test"})

    assert "Final report" in result.report

# Chaos test with FlakyLLM
@pytest.mark.asyncio
async def test_resilience():
    workflow = graph.compile()

    with FlakyLLM(failure_rate=0.3, timeout_rate=0.1):
        result = await run(workflow, input={"query": "test"})

    assert result is not None  # Workflow recovers gracefully
```

**Workflow Assertions** allow checkpoint-based assertions on any intermediate state:

```python
assertions = WorkflowAssertions(result)
assertions.assert_node_executed("researcher")
assertions.assert_state_at("researcher", lambda s: len(s.messages) > 0)
assertions.assert_no_errors()
assertions.assert_total_cost_under(0.50)
```

---

## Architecture

### Project Structure

```
orchestra/                      # repository root
  src/
    orchestra/                  # installable package
    __init__.py
    core/                   # Graph engine, agents, state, execution
        agent.py            # Agent Protocol, BaseAgent, @agent decorator
        graph.py            # WorkflowGraph, CompiledGraph
        nodes.py            # AgentNode, FunctionNode, DynamicNode, SubgraphNode
        edges.py            # Edge, ConditionalEdge, HandoffEdge, ParallelEdge
        state.py            # WorkflowState, StateReducer, reducer functions
        context.py          # ExecutionContext, RunContext
        runner.py           # AgentExecutor Protocol, AsyncioExecutor, RayExecutor
        types.py            # Message, AgentResult, TokenUsage, END sentinel
        errors.py           # OrchestraError hierarchy
    providers/              # LLM provider adapters
        base.py             # LLMProvider Protocol
        openai.py           # OpenAI (GPT-4o, GPT-4o-mini)
        anthropic.py        # Anthropic (Claude Opus, Sonnet, Haiku)
        google.py           # Google (Gemini)
        ollama.py           # Ollama (local models)
        router.py           # CostRouter (intelligent model routing)
    tools/                  # Tool system
        base.py             # Tool Protocol, @tool decorator
        registry.py         # ToolRegistry with ACLs
        mcp.py              # MCPClient, MCPToolProvider
    memory/                 # Multi-tier memory
        working.py          # In-process bounded deque
        short_term.py       # Session-scoped (SQLite/PostgreSQL)
        long_term.py        # Semantic search (pgvector)
        entity.py           # Structured entity-attribute-value
        manager.py          # Unified MemoryManager
    storage/                # Persistence layer
        sqlite.py           # Dev backend
        postgres.py         # Production backend
        redis.py            # Hot state cache
        events.py           # EventStore, event sourcing
    observability/          # Tracing, metrics, logging
        tracing.py          # OpenTelemetry span management
        metrics.py          # CostTracker, token usage
        console.py          # Rich terminal trace renderer
        logging.py          # structlog configuration
    security/               # Agent IAM and guardrails
        identity.py         # AgentIdentity, Capability
        acl.py              # ACLEngine, PermissionPolicy
        guardrails.py       # ContentFilter, PIIDetector, CostLimiter
    api/                    # HTTP server
        app.py              # FastAPI application
        routes/             # /v1/workflows, /v1/runs, /v1/agents
        websocket.py        # WebSocket for HITL
    testing/                # Agent testing framework
        scripted.py         # ScriptedLLM
        simulated.py        # SimulatedLLM
        flaky.py            # FlakyLLM
        assertions.py       # WorkflowAssertions
        fixtures.py         # pytest fixtures
    cli/                    # Command-line interface
        main.py             # orchestra init, run, test, serve
```

### Module Dependency Map

```
                         +------------------+
                         |  api/            |
                         |  (FastAPI server) |
                         +--------+---------+
                                  |
                    +-------------+-------------+
                    |                           |
              +-----v------+          +--------v--------+
              |  cli/       |          |  observability/ |
              |  (Typer)    |          |  (OTel, Rich)   |
              +-----+------+          +--------+--------+
                    |                           |
        +-----------v---------------------------v-----------+
        |                   core/                           |
        |  agent.py  graph.py  nodes.py  edges.py          |
        |  state.py  context.py  runner.py  types.py       |
        +-+-------+-------+-------+--------+-------+------+
          |       |       |       |        |       |
    +-----v-+ +--v---+ +-v----+ +v------+ v------+v--------+
    |provid.| |tools/| |memry/| |storag.| |security/       |
    +-------+ +------+ +------+ +-------+ +--------+-------+
                                                    |
                                             +------v------+
                                             |  testing/   |
                                             +-------------+
```

The `core/` module has **zero upward dependencies** — it depends only on Protocol interfaces from `providers/base.py`, `tools/base.py`, `storage/base.py`, and `memory/base.py`.

---

## Progressive Infrastructure

Orchestra scales from a laptop to a Kubernetes cluster without changing your agent or workflow code:

| Stage | Storage | Messaging | Observability | Execution |
|---|---|---|---|---|
| **Local Dev** | SQLite + in-memory | asyncio.Queue | Rich console | Single process |
| **Team Staging** | PostgreSQL | NATS JetStream | Jaeger / Grafana | Docker Compose |
| **Production** | PostgreSQL + Redis | NATS JetStream | OTel + Datadog/Honeycomb | Kubernetes / Ray |

**Same code. Same graphs. Same agents. Only configuration changes.**

---

## Observability

Orchestra provides built-in, zero-infrastructure observability that works out of the box:

- **Rich Console Tracer** — Live terminal trace tree showing agent execution, tool calls, handoffs, and state transitions in real-time during development
- **Time-Travel Debugging** — Reconstruct and inspect state at any checkpoint. Modify state and resume execution from any point. No external services required.
- **Cost Waterfall** — Visualize token usage and estimated cost per agent, per turn, in the terminal
- **OpenTelemetry** — Vendor-neutral traces, metrics, and logs. Export to Jaeger, Datadog, Honeycomb, or any OTel-compatible backend
- **Structured Logging** — structlog with auto-detection: human-readable in dev, JSON in production

---

## Human-in-the-Loop (HITL)

Orchestra supports pausing workflows for human review and resuming with modified state:

```python
from orchestra import WorkflowGraph, run, resume

# Interrupt before a specific node
workflow = graph.compile(
    interrupt_before=["final_decision"],
)

# Run until the interrupt point
result = await run(workflow, input={"proposal": "..."})
# result.status == "interrupted"

# Human inspects the state
print(result.state.draft_decision)

# Resume with human feedback
final = await resume(
    run_id=result.run_id,
    state_override={"human_approved": True, "reviewer_notes": "Looks good"},
)
```

Escalation policies handle timeouts automatically — if a human does not respond within a configured window, the workflow can escalate to a different reviewer or proceed with a fallback.

---

## Security Model

Orchestra is the first multi-agent framework with a capability-based agent identity and access management system:

### Agent Identity

Each agent has a cryptographic identity with 13 scoped capability types:

```python
from orchestra.security import AgentIdentity, Capability

identity = AgentIdentity(
    agent_name="researcher",
    capabilities=[
        Capability.TOOL_USE,
        Capability.STATE_READ,
        Capability.NETWORK_ACCESS,
    ]
)
```

### Tool-Level ACLs

Agents can only invoke tools they are explicitly granted access to:

```python
registry.set_acl("researcher", allow=["web_search", "read_file"])
registry.set_acl("writer", allow=["write_file"], deny=["web_search"])
```

### Guardrails Middleware

Composable pre/post hooks applied as decorators:

```python
from orchestra.security import with_guardrails, ContentFilter, PIIDetector, CostLimiter

@with_guardrails(ContentFilter(), PIIDetector(), CostLimiter(max_usd=1.00))
class SensitiveAgent(BaseAgent):
    ...
```

### Security Modes

- **Dev mode**: All agents have all permissions. Zero friction during prototyping.
- **Prod mode**: Explicit grants required. Deny-by-default. Full audit trail.

---

## Memory System

Four-tier memory architecture adapted from the best patterns across frameworks:

| Tier | Scope | Backend | Use Case |
|---|---|---|---|
| **Working Memory** | Current execution | In-process bounded deque | Active context window with auto-summarization |
| **Short-Term Memory** | Session | SQLite / PostgreSQL | Conversation history within a session |
| **Long-Term Memory** | Cross-session | pgvector | Semantic search across all past interactions |
| **Entity Memory** | Persistent | PostgreSQL | Structured facts about people, projects, concepts |

The `MemoryManager` provides a unified interface that coordinates reads and writes across all tiers.

---

## Cost Management

Orchestra is the only framework that actively reduces your LLM bill:

- **Complexity Profiling** — Analyze task complexity before LLM dispatch
- **Intelligent Cost Router** — Automatically route simple tasks to cheap models (GPT-4o-mini, Haiku) and complex reasoning to expensive models (GPT-4o, Opus)
- **Budget Enforcement** — Per-workflow and per-agent token budgets. Automatic degradation to cheaper models rather than hard failure.
- **Cost Attribution** — Track costs per agent, per workflow, per user with real-time dashboards

```python
from orchestra import WorkflowGraph, run
from orchestra.providers import CostRouter

router = CostRouter(
    tiers={
        "simple": "gpt-4o-mini",     # Classification, extraction
        "moderate": "claude-sonnet-4-6", # Summarization, writing
        "complex": "gpt-4o",          # Reasoning, planning
    },
    budget_per_workflow=5.00,  # USD
)

# Agents in the workflow use the router as their LLM provider
analyst = Agent(name="analyst", role="Data Analyst", provider=router)
writer = Agent(name="writer", role="Report Writer", provider=router)
```

---

## LLM Provider Support

Orchestra supports all major LLM providers through a unified `LLMProvider` Protocol:

| Provider | Models | Status |
|---|---|---|
| **OpenAI** | GPT-4o, GPT-4o-mini, o1, o3 | Core |
| **Anthropic** | Claude 4 (Opus, Sonnet), Claude 3.5 (Haiku) | Core |
| **Google** | Gemini 2.0 Flash, Gemini 1.5 Pro | Optional |
| **Ollama** | Llama, Mistral, and all local models | Optional |
| **Any OpenAI-compatible** | Via base URL configuration | Optional |

Providers are optional extras — install only what you need:

```bash
pip install orchestra-agents[openai]       # OpenAI support
pip install orchestra-agents[anthropic]    # Anthropic support
pip install orchestra-agents[all]          # Everything
```

---

## Roadmap

Orchestra was built in four phases. All phases are complete.

### Phase 1: Core Engine ✅
Graph engine, agent protocol, typed state, LLM adapters, testing harness, CLI, and example workflows.

### Phase 2: Differentiation ✅
Event-sourced persistence, human-in-the-loop, time-travel debugging, handoff protocol, MCP integration, and Rich tracing.

### Phase 3: Production Readiness ✅
FastAPI server, OpenTelemetry, Redis cache, multi-tier memory, advanced test harnesses, guardrails, and cost tracking. All 14 critical security and concurrency issues resolved.

### Phase 4: Enterprise & Scale ✅
Cost router with failover, agent IAM (DID + UCAN + signed Agent Cards), NATS JetStream E2EE messaging, WebAssembly sandboxed tool execution, dynamic subgraphs, TypeScript SDK, Kubernetes + Helm + KEDA deployment, and HSM-backed 3-tier key management.

### Examples

The `examples/` directory contains end-to-end working examples:

- `quickstart.py` — Minimal agent and workflow setup
- `research_pipeline.py` — Multi-agent research with structured output
- `customer_support_handoff.py` — Swarm-style handoffs between support tiers
- `parallel_debate.py` — Parallel agents with adversarial review

---

## Competitive Comparison

| Capability | Orchestra | LangGraph | CrewAI | AutoGen | OpenAI SDK |
|---|---|---|---|---|---|
| Graph workflows | Full | Full | Basic | None | None |
| Dynamic subgraphs | Yes | No | No | No | No |
| Agent DX quality | High | Low | Highest | Medium | Medium |
| Multi-model support | All providers | All | All (LiteLLM) | All | OpenAI only |
| Time-travel debug | Built-in (free) | LangSmith (paid) | No | No | No |
| Testing framework | Full (3 modes) | Manual | train() only | Manual | Manual |
| Agent IAM/security | Capability-based | None | None | Docker only | Guardrails |
| Cost routing | Intelligent | None | None | None | None |
| HITL | Full + escalation | Best | Manager | Human input | None |
| Observability | OTel + Rich (free) | LangSmith (paid) | Logs | Basic OTel | Traces |
| MCP support | Client + Host + Server | Client | None | Client | None |
| Pricing | **100% Free** | Free + paid cloud | Free + paid enterprise | Free | Free |

---

## Tech Stack

| Dimension | Choice | Rationale |
|---|---|---|
| Language | Python 3.11+ | LLM ecosystem is Python-first |
| Async Runtime | asyncio (default), Ray (opt-in) | Zero-infrastructure default; Ray for scale |
| Data Validation | Pydantic v2 | Rust-backed performance, type safety |
| State Storage | SQLite (dev) / PostgreSQL + pgvector (prod) | Event-sourced workflow state + semantic memory |
| Hot Cache | In-memory (dev) / Redis 7+ (prod) | Session state, tool result caching |
| API Layer | FastAPI + SSE | REST + real-time streaming |
| Observability | OpenTelemetry + structlog + Rich | Vendor-neutral + beautiful local DX |
| CLI | Typer | Clean command-line interface |
| Testing | pytest-asyncio | Native async test support |

**Core dependency count:** ~15 required packages. LLM providers, Ray, NATS, and pgvector are optional extras.

---

## Contributing

Orchestra is 100% free and open-source under Apache 2.0. Contributions are welcome.

### Getting Started

```bash
git clone https://github.com/songyinggoh/multi-agent-orchestration-framework.git
cd multi-agent-orchestration-framework
pip install -e ".[dev,server,security,storage]"    # Install with dev dependencies
pytest                     # Run the test suite
```

### Workflow

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Write tests for your changes using `ScriptedLLM` for deterministic assertions
4. Ensure all tests pass (`pytest`)
5. Submit a pull request

### Project Layout

- **[planning/](./planning/)** — Architecture decisions, API design, and the detailed roadmap
- **[planning/API-DESIGN.md](./planning/API-DESIGN.md)** — Canonical API reference for all public interfaces
- **[planning/ROADMAP.md](./planning/ROADMAP.md)** — Phase-by-phase development plan with success criteria
- **[research/](./research/)** — Competitive analysis, tech stack rationale, and design research

### Code Style

- Python 3.11+ with type annotations throughout
- `async/await` for all I/O-bound operations
- Pydantic models for data validation and serialization
- Protocol-first design (structural subtyping over inheritance)

---

## License

Orchestra is released under the **Apache License 2.0**. All features are free. No paid tiers. No proprietary lock-in.
