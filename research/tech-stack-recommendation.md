# Technology Stack Recommendation: Multi-Agent Orchestration Framework

**Document Version:** 1.0
**Date:** 2026-03-05
**Status:** Final Recommendation

---

## Executive Summary

**The recommended stack at a glance:**

| Dimension | Recommendation |
|---|---|
| Primary Language | Python 3.11+ (core) + TypeScript (SDK/UI) |
| Runtime | asyncio with optional Ray for distributed scale |
| State Management | Event sourcing on SQLite/PostgreSQL + Redis hot cache |
| Message Passing | asyncio.Queue (local) + NATS JetStream (distributed) |
| Serialization | JSON (default) + MessagePack (internal performance paths) |
| Workflow Engine | Custom graph engine (LangGraph-inspired, no monolithic dep) |
| Observability | OpenTelemetry + structlog + Rich console renderer |
| Storage | SQLite (dev) / PostgreSQL + pgvector (prod) + Redis |
| API Layer | FastAPI + SSE streaming + optional gRPC |
| Testing | pytest-asyncio + ScriptedLLM + SimulatedLLM harness |

---

## Context: Synthesizing From Existing Frameworks

Before evaluating each dimension, here are the key lessons from existing frameworks:

**Take from each framework:**
- **LangGraph:** Explicit state graph, reducers, checkpointing, resumability
- **AutoGen:** Conversational threading, human-in-the-loop patterns
- **CrewAI:** Role-based DX, simple crew configuration
- **Swarm:** Lightweight handoff routing concept
- **MetaGPT:** Structured agent communication protocols

**Avoid from each framework:**
- LangGraph/LangChain's heavy monolithic dependency tree
- AutoGen's implicit state and weak async model
- CrewAI's shallow workflow engine
- MetaGPT's narrow domain scope
- Swarm's lack of any production infrastructure

---

## Dimension 1: Primary Language

### Recommendation: Python 3.11+ (core) + TypeScript (client SDK + UI)

**Python wins decisively** because the entire LLM ecosystem is Python-first. Every provider SDK (OpenAI, Anthropic, Google Gemini, Cohere, HuggingFace transformers) ships Python first. Every ML library is Python. The AI practitioner community writes Python. The GIL concern is a red herring — agent execution is almost entirely I/O-bound (waiting on LLM API calls, tool HTTP calls, database reads), which asyncio handles perfectly.

**TypeScript** should be a first-class client SDK. This is the pattern used by Temporal (Go core, TypeScript/Java/Python SDKs), Prefect (Python core, React UI), and LangSmith. It gives TypeScript developers a path to integrate without requiring a full framework rewrite.

**Why not Rust or Go:** Both are excellent languages, but have near-zero LLM SDK ecosystems and would require Python FFI for all LLM calls anyway, eliminating the performance justification.

**Minimum Python version:** 3.11 (required for `asyncio.TaskGroup`, `ExceptionGroup`, improved `tomllib`). Target 3.12 for `typing.override` and the experimental free-threaded (no-GIL) build.

**Key library choices:**
- `pydantic` v2 — data validation and serialization (Rust-backed, fast)
- `httpx` — async HTTP (not `requests`)
- `anyio` — async compatibility shim (asyncio + trio)
- `structlog` — structured logging
- `rich` — developer-facing terminal output
- `typer` — CLI interface

---

## Dimension 2: Runtime Model

### Recommendation: asyncio (default) + Ray (optional distributed backend)

**Mode 1 - asyncio (default):** All agents run as asyncio coroutines. `asyncio.TaskGroup` (Python 3.11+) handles parallel agent execution with proper structured concurrency and error propagation. Zero additional infrastructure. Fully debuggable with standard Python tools. Sufficient for 90% of use cases (2-20 agents in a single workflow).

**Mode 2 - Ray (optional):** Enabled via configuration for large-scale agent fleets, long-running batch workflows, or multi-machine deployments. Each Ray Actor is a stateful, fault-tolerant agent unit with built-in resource management (GPU allocation for local models).

The key architectural decision is to define an `AgentExecutor` Protocol with two implementations:
- `AsyncioExecutor` — the default, zero-infrastructure mode
- `RayExecutor` — opt-in distributed mode

Switching between them requires only a configuration change, not code changes. This mirrors how Temporal has both in-process test workers and real distributed workers behind the same API.

**CPU-bound work** (embedding generation, local model inference) always dispatches to `asyncio.run_in_executor(ProcessPoolExecutor(...))` to keep the event loop unblocked.

**Threading** is not recommended as a primary model — the GIL prevents true parallelism, async LLM SDKs expect coroutines, and race conditions are hard to debug.

---

## Dimension 3: State Management

### The Five Layers of Agent State

State in a multi-agent framework has five distinct layers requiring different strategies:
1. **Working memory** — active context window content during an agent turn
2. **Agent state** — current task, goals, ephemeral in-flight data
3. **Conversation history** — full message log for a session
4. **Workflow state** — current node, completed steps, branching decisions
5. **Long-term memory** — cross-session knowledge, tool results, learned facts

### Recommendation: Hybrid three-tier model with event sourcing semantics

**Tier 1 - Hot Path:** Working memory and active agent state live in-memory during execution. Redis serves as the shared hot cache for distributed coordination, pub/sub notifications, and ephemeral session state (Redis Streams for event broadcasting between agents). TTL-based expiry handles cleanup.

**Tier 2 - Workflow State (Event-Sourced SQL):** All workflow state transitions are written as immutable events to a `workflow_events` table. Current state is a projection over the event log. Benefits:
- Full audit trail of every agent decision and state transition
- Workflow resumability after failure (replay from last checkpoint)
- Time-travel debugging (reconstruct state at any point in time)
- Natural fit for the turn-by-turn nature of agent execution

Use SQLite for local development (zero infrastructure), PostgreSQL for production.

**Tier 3 - Long-term Memory:** Conversation history and cross-session memory in PostgreSQL + pgvector for semantic similarity search.

**State schema pattern (LangGraph-inspired, decoupled):**

```python
from pydantic import BaseModel
from typing import Annotated

def merge_list(existing: list, new: list) -> list:
    """Reducer: append new items."""
    return existing + new

def last_write_wins(existing, new):
    """Reducer: new value replaces existing."""
    return new

class WorkflowState(BaseModel):
    messages: Annotated[list[Message], merge_list] = []
    current_task: Annotated[str | None, last_write_wins] = None
    agent_outputs: Annotated[dict[str, AgentResult], merge_dict] = {}
    metadata: dict[str, Any] = {}
```

This provides type safety, explicit merge semantics (critical for parallel agent fan-in), and decouples state definition from storage backend.

---

## Dimension 4: Message Passing

### Recommendation: asyncio.Queue (in-process) + NATS JetStream (distributed)

**In-process communication (default):**
Agents communicate via direct async calls (sequential edges) and `asyncio.Queue` (fan-out/fan-in patterns). Zero overhead, full Python stack traces, no serialization cost.

```python
# Direct sequential call
result = await agent_b.run(input=agent_a_output)

# Buffered async queue for parallel patterns
queue: asyncio.Queue[AgentMessage] = asyncio.Queue(maxsize=100)
async with asyncio.TaskGroup() as tg:
    tg.create_task(orchestrator.produce(queue))
    tg.create_task(researcher.consume(queue))
    tg.create_task(critic.consume(queue))
```

**Distributed communication (NATS JetStream):**
NATS is the correct choice over RabbitMQ and Kafka for distributed agent messaging:
1. Single binary, no JVM, trivial Docker setup
2. JetStream adds durable persistence without AMQP complexity
3. 10-50x lower latency than RabbitMQ/Kafka for small messages
4. Native request/reply maps perfectly to agent handoffs
5. Used at scale by production AI platforms

Subject naming convention:
```
agents.{workflow_id}.{agent_name}.input
agents.{workflow_id}.{agent_name}.output
workflows.{workflow_id}.events
```

**Why not Kafka:** Kafka's operational complexity and latency profile are wrong for interactive agent conversations. It excels at high-throughput event streaming where latency can be in the hundreds of milliseconds — the opposite of what real-time agent workflows need.

**Why not gRPC for messaging:** gRPC is recommended for the API layer (Dimension 9), not for internal agent-to-agent messaging. Schema management for dynamic agent messages is too rigid in protobuf.

---

## Dimension 5: Serialization

### Recommendation: JSON (default) + MessagePack (internal performance paths)

**JSON is non-negotiable as the primary format** because:
1. All LLM APIs (OpenAI, Anthropic, Gemini) use JSON natively — any conversion adds overhead and potential data loss
2. Human readability is critical for debugging agent conversations
3. Dynamic message structures (tool calls, function definitions) are awkward in schema-enforced formats like protobuf
4. Pydantic v2 serializes to/from JSON with excellent performance (Rust-backed core)

**MessagePack for internal high-throughput paths** where messages are not user-visible and not LLM-facing:
- State snapshots written to the event store (~30-50% smaller than JSON)
- NATS JetStream message payloads in distributed mode
- Large tool result caching

```python
class AgentMessage(BaseModel):
    id: str
    role: str
    content: str
    metadata: dict[str, Any]

    def to_json(self) -> str:
        """For LLM API calls and human-readable logging."""
        return self.model_dump_json()

    def to_msgpack(self) -> bytes:
        """For internal transport (NATS, state store)."""
        return msgpack.packb(self.model_dump(), use_bin_type=True)

    @classmethod
    def from_msgpack(cls, data: bytes) -> "AgentMessage":
        return cls(**msgpack.unpackb(data, raw=False))
```

**Protocol Buffers** are used only for the optional gRPC inter-service layer.

---

## Dimension 6: Workflow Engine

### Recommendation: Custom lightweight graph engine + optional Temporal for durable workflows

**Why not adopt LangGraph as a dependency:** The framework's core value proposition IS the graph engine. Making it a LangGraph wrapper means building a wrapper, not a novel framework. Additionally, LangGraph's LangChain dependency is a significant monolithic addition.

**Why not Temporal/Prefect as the default:** Both add infrastructure requirements that contradict the "zero-infrastructure local development" goal. Temporal requires a Temporal server. Prefect requires a Prefect server/cloud.

**The custom graph engine** should be inspired by LangGraph's best ideas, implemented independently:

```python
class WorkflowGraph:
    """
    Directed graph of agent nodes with conditional edges.
    Supports: sequential, parallel, conditional, cyclic, dynamic graphs.
    """

    def add_node(self, node_id: str, node: GraphNode) -> "WorkflowGraph": ...
    def add_edge(self, from_id: str, to_id: str) -> "WorkflowGraph": ...
    def add_conditional_edge(
        self, from_id: str, condition: EdgeCondition
    ) -> "WorkflowGraph": ...
    def set_entry_point(self, node_id: str) -> "WorkflowGraph": ...
    def compile(self) -> CompiledGraph: ...
```

**Dynamic task decomposition** is handled by `DynamicNode` — a node that generates new sub-nodes and edges at runtime. This enables the "plan-and-execute" pattern where a planner agent decomposes a task into dynamically determined subtasks.

**Optional Temporal backend:** For users who need production-grade workflow durability (long-running workflows, guaranteed exactly-once execution), Temporal is the right optional backend. The `CompiledGraph` interface maps to a Temporal Workflow, enabling the same graph definition to run locally or durably via a backend configuration switch.

---

## Dimension 7: Observability

### Recommendation: OpenTelemetry foundation + structlog + Rich console renderer

**OpenTelemetry** is the correct foundational choice: open standard, vendor-neutral, supported by every major observability backend (Jaeger, Grafana Tempo, Honeycomb, Datadog, New Relic).

**The observability stack:**

```
Framework Core
    ├── OTel SDK (traces, metrics, logs)
    │       ├── Console exporter (local dev — zero config)
    │       ├── OTLP exporter → Jaeger / Grafana / Honeycomb / Datadog
    │       └── LangSmith-compatible exporter (optional)
    ├── structlog (structured JSON logging in prod, human-readable in dev)
    └── OTel Metrics → Prometheus scrape endpoint
```

**Span hierarchy for agent workflows:**
```
workflow.run [root span]
  ├── agent.turn: planner
  │     ├── llm.chat_completion
  │     │     ├── gen_ai.system: openai
  │     │     ├── gen_ai.request.model: gpt-4o
  │     │     ├── gen_ai.usage.input_tokens: 1204
  │     │     └── gen_ai.usage.output_tokens: 87
  │     └── tool.call: search_web
  │           ├── tool_input: {...}
  │           └── tool_output: {...}
  └── agent.turn: researcher
        └── ...
```

**The single highest-impact DX improvement:** A built-in `AgentTracer` that renders a beautiful real-time trace tree in the terminal during development using `rich`. No external infrastructure required.

---

## Dimension 8: Storage

### Storage Decision Matrix

| Layer | Development | Production | Driver |
|---|---|---|---|
| Conversation history | SQLite | PostgreSQL | asyncpg / aiosqlite |
| Workflow event store | SQLite | PostgreSQL | asyncpg / aiosqlite |
| Agent memory (semantic) | SQLite + sqlite-vss | PostgreSQL + pgvector | asyncpg / pgvector |
| Hot state cache | In-memory dict | Redis 7+ | redis[asyncio] |
| Tool result cache | In-memory LRU | Redis | redis[asyncio] |

**PostgreSQL + pgvector** eliminates the need for a separate vector database (Pinecone, Weaviate, Qdrant) for the vast majority of use cases.

---

## Dimension 9: API Layer

### Recommendation: FastAPI + SSE (streaming) + optional gRPC

**REST API design:**
```
POST   /v1/workflows             # Create workflow definition
GET    /v1/workflows/{id}        # Get workflow definition
POST   /v1/runs                  # Start a workflow run
GET    /v1/runs/{id}             # Get run status + result
DELETE /v1/runs/{id}             # Cancel a run
GET    /v1/runs/{id}/stream      # SSE stream of run events
POST   /v1/runs/{id}/resume      # Resume (human-in-the-loop)
GET    /v1/runs/{id}/trace       # Full execution trace
POST   /v1/agents                # Register agent definition
GET    /v1/tools                 # List available tools
GET    /v1/health                # Health check
GET    /v1/metrics               # Prometheus metrics
```

**SSE for streaming** (preferred over WebSocket for server-push): Agent execution is inherently server-initiated, which maps perfectly to SSE's server-to-client model.

**WebSocket** for bidirectional use cases: interactive human-in-the-loop sessions.

**gRPC** as optional inter-service protocol for polyglot architectures.

---

## Dimension 10: Testing Framework

### Recommendation: pytest-asyncio + layered test strategy with ScriptedLLM and SimulatedLLM

| Layer | When | Duration | Description |
|---|---|---|---|
| Unit tests | Every commit | < 30s | Individual nodes, reducers, tools with mocked LLMs |
| Workflow integration | Every commit | < 2 min | Complete graph workflows with ScriptedLLM |
| LLM simulation | PR merge gate | < 10 min | SimulatedLLM with cheap model (seed=42, temp=0) |
| Contract tests | Nightly | Varies | Verify each LLM provider adapter implements Protocol |
| Chaos / resilience | PR merge gate | Varies | Timeouts, tool errors, partial failures via FlakyLLM |
| Evaluation / quality | Weekly | Varies | LLM-as-judge evaluation against quality criteria |

---

## Complete Dependency Declaration

```toml
[project]
name = "orchestra"
requires-python = ">=3.11"

dependencies = [
    "anyio>=4.0",
    "pydantic>=2.5",
    "msgpack>=1.0",
    "httpx>=0.26",
    "fastapi>=0.110",
    "sse-starlette>=2.0",
    "uvicorn[standard]>=0.27",
    "opentelemetry-sdk>=1.22",
    "opentelemetry-instrumentation-httpx",
    "structlog>=24.0",
    "rich>=13.0",
    "typer>=0.12",
    "asyncpg>=0.29",
    "aiosqlite>=0.20",
    "redis[asyncio]>=5.0",
]

[project.optional-dependencies]
openai     = ["openai>=1.12"]
anthropic  = ["anthropic>=0.20"]
google     = ["google-generativeai>=0.4"]
ray        = ["ray[default]>=2.9"]
nats       = ["nats-py>=2.6"]
pgvector   = ["pgvector>=0.2"]
grpc       = ["grpcio>=1.62", "grpcio-tools>=1.62"]
all        = ["orchestra[openai,anthropic,google,ray,nats,pgvector,grpc]"]
```

---

## Recommended Project Structure

```
orchestra/
├── src/orchestra/
│   ├── core/
│   │   ├── agent.py          # Agent Protocol and base classes
│   │   ├── graph.py          # WorkflowGraph engine
│   │   ├── state.py          # WorkflowState + reducers
│   │   ├── context.py        # ExecutionContext
│   │   └── runner.py         # AsyncioExecutor + RayExecutor
│   ├── providers/
│   │   ├── base.py           # LLMProvider Protocol
│   │   ├── openai.py
│   │   ├── anthropic.py
│   │   ├── google.py
│   │   └── ollama.py         # local models
│   ├── memory/
│   │   ├── conversation.py   # conversation history store
│   │   ├── semantic.py       # pgvector semantic memory
│   │   └── cache.py          # tool result cache
│   ├── tools/
│   │   ├── base.py           # Tool Protocol + @tool decorator
│   │   ├── registry.py       # tool registration
│   │   └── builtin/          # web search, code exec, file I/O
│   ├── transport/
│   │   ├── local.py          # asyncio.Queue (default)
│   │   └── nats.py           # NATS JetStream (distributed)
│   ├── storage/
│   │   ├── sqlite.py         # dev backend
│   │   ├── postgres.py       # prod backend
│   │   └── redis.py          # hot cache
│   ├── observability/
│   │   ├── tracing.py        # OTel span management
│   │   ├── logging.py        # structlog config
│   │   ├── metrics.py        # OTel metrics
│   │   └── console.py        # Rich terminal trace renderer
│   └── api/
│       ├── app.py            # FastAPI application
│       ├── routes/
│       └── schemas.py
├── sdk/typescript/            # TypeScript client SDK
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── simulation/
│   └── fixtures/             # ScriptedLLM, FlakyLLM, SimulatedLLM
├── examples/
└── pyproject.toml
```

---

## Five Core Architectural Principles

1. **Protocol-First Design:** Every major component is a Python `Protocol` (structural subtyping). Implementations are pluggable.

2. **Zero-Infrastructure Default:** Works with zero external services out of the box. SQLite + in-memory queues + console logging + `fakeredis`.

3. **Progressive Complexity:** Simple use cases are simple. Complex use cases are possible.

4. **Async-First, Sync-Compatible:** All public APIs are async. Synchronous wrappers provided as convenience.

5. **Explicit Over Implicit:** State transitions, agent routing, and message flow are explicit in code.

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| asyncio complexity for new contributors | Medium | Medium | Extensive docs, sync wrappers, tutorials |
| LLM API rate limits in parallel execution | High | High | Built-in rate limiting and backpressure in LLMProvider |
| Non-determinism making tests flaky | High | Medium | ScriptedLLM for unit tests; seed+temp=0 for simulation |
| Graph cycles causing infinite loops | Medium | High | Cycle detection on compile; max_turns guard at runtime |
| OTel SDK version conflicts with user deps | Medium | Medium | Pin OTel SDK version ranges; document conflicts |
| Ray overhead for distributed mode | Medium | Low | Ray is opt-in; asyncio covers 90% of cases |
| pgvector not meeting scale needs | Low | Medium | Qdrant/Pinecone adapters available as escape hatch |
