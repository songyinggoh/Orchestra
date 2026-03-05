# Orchestra: Comprehensive Architectural Plan

**Framework Name:** Orchestra
**Target:** Python 3.11+
**Date:** 2026-03-05
**Status:** Detailed Implementation Plan

---

## 1. Project Structure

```
orchestra/
src/orchestra/
    __init__.py
    _version.py
    core/
        __init__.py
        agent.py              # Agent Protocol, BaseAgent, @agent decorator
        graph.py              # WorkflowGraph, CompiledGraph
        nodes.py              # AgentNode, FunctionNode, DynamicNode, SubgraphNode
        edges.py              # Edge, ConditionalEdge, HandoffEdge, ParallelEdge
        state.py              # WorkflowState, StateReducer, reducer functions
        context.py            # ExecutionContext, RunContext
        runner.py             # AgentExecutor Protocol, AsyncioExecutor, RayExecutor
        types.py              # Shared type definitions, Message, AgentResult, END sentinel
        errors.py             # OrchestraError hierarchy
    providers/
        __init__.py
        base.py               # LLMProvider Protocol, LLMResponse, StreamChunk
        openai.py             # OpenAIProvider
        anthropic.py          # AnthropicProvider
        google.py             # GoogleProvider
        ollama.py             # OllamaProvider
        router.py             # CostRouter (intelligent model routing)
    tools/
        __init__.py
        base.py               # Tool Protocol, @tool decorator, ToolResult
        registry.py           # ToolRegistry
        mcp.py                # MCPClient, MCPToolProvider
        acl.py                # ToolACL, PermissionChecker
        builtin/
            __init__.py
            web_search.py
            code_exec.py
            file_io.py
    memory/
        __init__.py
        base.py               # MemoryStore Protocol
        working.py            # WorkingMemory (in-process)
        short_term.py         # ShortTermMemory (session-scoped, SQL)
        long_term.py          # LongTermMemory (semantic, pgvector)
        entity.py             # EntityMemory (structured facts)
        manager.py            # MemoryManager (coordinates all tiers)
    storage/
        __init__.py
        base.py               # StorageBackend Protocol, CheckpointStore Protocol
        sqlite.py             # SQLiteBackend (dev)
        postgres.py           # PostgresBackend (prod)
        redis.py              # RedisCache (hot state)
        events.py             # EventStore, AgentEvent, event sourcing
    observability/
        __init__.py
        tracing.py            # OTel span management, TracingManager
        logging.py            # structlog configuration
        metrics.py            # OTel metrics, CostTracker
        console.py            # RichConsoleTracer (terminal trace renderer)
    security/
        __init__.py
        identity.py           # AgentIdentity, Capability, CapabilityGrant
        acl.py                # ACLEngine, PermissionPolicy
        guardrails.py         # GuardrailsMiddleware, ContentFilter, PIIDetector, CostLimiter
        secrets.py            # ScopedSecretProvider
    api/
        __init__.py
        app.py                # FastAPI application factory
        routes/
            __init__.py
            workflows.py      # /v1/workflows
            runs.py           # /v1/runs, SSE streaming
            agents.py         # /v1/agents
            tools.py          # /v1/tools
            health.py         # /v1/health, /v1/metrics
        schemas.py            # Pydantic request/response models
        websocket.py          # WebSocket handler for HITL
    testing/
        __init__.py
        scripted.py           # ScriptedLLM
        simulated.py          # SimulatedLLM
        flaky.py              # FlakyLLM
        assertions.py         # WorkflowAssertions, checkpoint-based assertions
        fixtures.py           # pytest fixtures for Orchestra
    cli/
        __init__.py
        main.py               # Typer CLI: orchestra init, run, test, serve
tests/
    unit/
    integration/
    simulation/
    conftest.py
examples/
    quickstart.py
    research_pipeline.py
    customer_support_handoff.py
    parallel_debate.py
pyproject.toml
```

---

## 2. Module Dependency Map

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
    +-------+ +------+ +------+ +-------+ +---------+------+
                                                     |
                                              +------v------+
                                              |  testing/   |
                                              +-------------+
```

Every module depends on `core/types.py` and `core/errors.py` for shared types. The `core/` module has zero upward dependencies -- it depends only on `providers/base.py`, `tools/base.py`, `storage/base.py`, and `memory/base.py` via Protocol interfaces.

---

## 3. Agent Protocol and Base Classes

**File:** `src/orchestra/core/agent.py`
**External deps:** `pydantic>=2.5`
**Internal deps:** `core.types`, `core.context`, `tools.base`, `providers.base`

```python
from __future__ import annotations
from typing import Any, Protocol, runtime_checkable, Sequence, Callable, TypeVar
from pydantic import BaseModel, Field
from orchestra.core.types import Message, AgentResult, AgentSpec
from orchestra.core.context import ExecutionContext
from orchestra.tools.base import Tool
from orchestra.providers.base import LLMProvider

@runtime_checkable
class Agent(Protocol):
    """Core Agent Protocol. Any class implementing these methods is an Agent."""
    @property
    def name(self) -> str: ...
    @property
    def model(self) -> str: ...
    @property
    def instructions(self) -> str | Callable[[dict[str, Any]], str]: ...
    @property
    def tools(self) -> Sequence[Tool]: ...
    async def run(self, input: str | list[Message], context: ExecutionContext) -> AgentResult: ...
    def to_spec(self) -> AgentSpec: ...

class BaseAgent(BaseModel):
    """Concrete base class implementing Agent protocol. CrewAI-inspired DX."""
    name: str
    role: str = ""
    goal: str = ""
    backstory: str = ""
    model: str = "gpt-4o"
    instructions: str | Callable[[dict[str, Any]], str] = ""
    tools: list[Tool] = Field(default_factory=list)
    output_type: type[BaseModel] | None = None
    max_iter: int = 25
    memory_enabled: bool = True
    model_config = {"arbitrary_types_allowed": True}

    async def run(self, input: str | list[Message], context: ExecutionContext) -> AgentResult:
        """Execute the agent's reasoning loop."""
        ...

def agent(name: str, model: str = "gpt-4o", tools: list[Tool] | None = None,
          output_type: type[BaseModel] | None = None, max_iter: int = 25) -> Callable:
    """Decorator that turns a function into an Agent. Docstring becomes system prompt."""
    def decorator(func: Callable) -> DecoratorAgent:
        return DecoratorAgent(name=name, func=func, instructions=func.__doc__ or "",
                              model=model, tools=tools or [], output_type=output_type, max_iter=max_iter)
    return decorator
```

---

## 4. Core Types

**File:** `src/orchestra/core/types.py`

```python
from enum import Enum
from pydantic import BaseModel, Field
import uuid
from datetime import datetime
from typing import Any

class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"

class Message(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: MessageRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCallRequest] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class ToolCallRequest(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]

class AgentResult(BaseModel):
    agent_name: str
    output: str
    structured_output: BaseModel | None = None
    messages: list[Message] = Field(default_factory=list)
    tool_calls_made: list[ToolCallRecord] = Field(default_factory=list)
    handoff_to: str | None = None
    context_updates: dict[str, Any] = Field(default_factory=dict)
    token_usage: TokenUsage | None = None

class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0

class _EndSentinel:
    def __repr__(self) -> str: return "END"
END = _EndSentinel()
```

---

## 5. Graph Engine

**File:** `src/orchestra/core/graph.py`

```python
class WorkflowGraph:
    """Builder for constructing agent workflow graphs."""
    def __init__(self, state_schema: type[S]): ...
    def add_node(self, node_id: str, node: GraphNode | Callable | Agent) -> WorkflowGraph: ...
    def add_edge(self, from_id: str, to_id: str | _EndSentinel) -> WorkflowGraph: ...
    def add_conditional_edge(self, from_id: str, condition: Callable[[S], str], path_map: dict | None = None) -> WorkflowGraph: ...
    def add_handoff(self, from_id: str, to_id: str, condition: Callable | None = None) -> WorkflowGraph: ...
    def add_parallel(self, node_ids: Sequence[str], join_node: str, join_strategy: str = "wait_all") -> WorkflowGraph: ...
    def add_loop(self, body_nodes: Sequence[str], exit_condition: Callable[[S], bool], max_iterations: int = 10) -> WorkflowGraph: ...
    def set_entry_point(self, node_id: str) -> WorkflowGraph: ...
    def interrupt_before(self, *node_ids: str) -> WorkflowGraph: ...
    def interrupt_after(self, *node_ids: str) -> WorkflowGraph: ...
    def compile(self, checkpointer=None, executor=None) -> CompiledGraph[S]: ...

class CompiledGraph(Generic[S]):
    """Immutable, validated, executable workflow graph."""
    async def invoke(self, input: dict | S | None, config: RunConfig | None = None) -> S: ...
    async def stream(self, input: dict | S | None, config: RunConfig | None = None) -> AsyncIterator[StreamEvent]: ...
    async def resume(self, config: RunConfig, input: dict | None = None) -> S: ...
    def get_state(self, config: RunConfig) -> S: ...
    def update_state(self, config: RunConfig, updates: dict) -> S: ...
    def get_state_history(self, config: RunConfig) -> list[StateSnapshot]: ...

class RunConfig(BaseModel):
    thread_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    max_turns: int = 50
    timeout_seconds: float = 300.0
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

---

## 6. Node Types

**File:** `src/orchestra/core/nodes.py`

```python
@runtime_checkable
class GraphNode(Protocol):
    @property
    def node_id(self) -> str: ...
    async def execute(self, state: dict, context: ExecutionContext) -> dict: ...

class AgentNode:       # Wraps an Agent
class FunctionNode:    # Wraps a plain function
class DynamicNode:     # Generates subgraph at runtime (novel to Orchestra)
class SubgraphNode:    # Embeds a pre-compiled graph
```

---

## 7. State Management

**File:** `src/orchestra/core/state.py`

```python
# Built-in reducers
def merge_list(existing: list, new: list) -> list: return existing + new
def merge_dict(existing: dict, new: dict) -> dict: return {**existing, **new}
def last_write_wins(existing, new): return new
def increment(existing: int, new: int) -> int: return existing + new

class StateReducer:
    """Extracts reducer functions from Annotated type hints."""
    def __init__(self, state_schema: type[BaseModel]): ...
    def apply(self, current_state: dict, updates: dict) -> dict: ...

# Usage:
class MyState(BaseModel):
    messages: Annotated[list[Message], merge_list] = []
    current_agent: str = ""
    results: Annotated[dict[str, str], merge_dict] = {}
    iteration: Annotated[int, increment] = 0
```

---

## 8. Event Sourcing

**File:** `src/orchestra/storage/events.py`

```python
class EventType(str, Enum):
    WORKFLOW_STARTED = "workflow.started"
    NODE_STARTED = "node.started"
    NODE_COMPLETED = "node.completed"
    STATE_UPDATED = "state.updated"
    LLM_CALLED = "llm.called"
    TOOL_CALLED = "tool.called"
    HANDOFF = "handoff"
    CHECKPOINT_CREATED = "checkpoint.created"
    ERROR = "error"

class AgentEvent(BaseModel):
    id: str
    type: EventType
    workflow_id: str
    thread_id: str
    node_id: str | None
    sequence_number: int
    timestamp: datetime
    data: dict[str, Any]

class EventStore(Protocol):
    async def append(self, event: AgentEvent) -> None: ...
    async def get_events(self, workflow_id, thread_id, ...) -> list[AgentEvent]: ...
    async def replay(self, workflow_id, thread_id, ...) -> dict: ...
    async def create_snapshot(self, ...) -> None: ...

class SQLiteEventStore: ...   # Dev backend
class PostgresEventStore: ... # Prod backend
```

---

## 9. Execution Engine

**File:** `src/orchestra/core/runner.py`

```python
@runtime_checkable
class AgentExecutor(Protocol):
    async def execute_node(self, node, state, context) -> dict: ...
    async def execute_parallel(self, nodes, state, context, reducer) -> dict: ...
    async def execute_graph(self, nodes, edges, entry_point, state, ...) -> dict: ...

class AsyncioExecutor:
    """Default: single-process, zero-infrastructure, asyncio.TaskGroup for parallelism."""

class RayExecutor:
    """Opt-in: distributed, fault-tolerant, GPU scheduling via Ray actors."""
```

---

## 10. LLM Provider Protocol

**File:** `src/orchestra/providers/base.py`

```python
@runtime_checkable
class LLMProvider(Protocol):
    @property
    def provider_name(self) -> str: ...
    @property
    def default_model(self) -> str: ...
    async def chat(self, messages, model=None, tools=None, temperature=0.7, ...) -> LLMResponse: ...
    async def stream_chat(self, messages, ...) -> AsyncIterator[StreamChunk]: ...
    def count_tokens(self, messages, model=None) -> int: ...
    def get_model_cost(self, model) -> tuple[float, float]: ...

# Implementations: OpenAIProvider, AnthropicProvider, GoogleProvider, OllamaProvider
# Plus CostRouter for intelligent model routing
```

---

## 11. Tool System

**File:** `src/orchestra/tools/base.py`

```python
@runtime_checkable
class Tool(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def description(self) -> str: ...
    @property
    def parameters_schema(self) -> dict: ...
    async def execute(self, **kwargs) -> ToolResult: ...
    def to_function_schema(self) -> dict: ...

def tool(func=None, *, name=None, description=None, args_schema=None):
    """Decorator to convert a function into a Tool with auto-schema generation."""

class ToolRegistry:
    """Centralized registry with ACLs, rate limiting, timeout, and audit logging."""

class MCPClient:
    """Client for MCP servers (stdio + SSE transports)."""

class ToolACL:
    """Tool-level access control: grant/deny per agent."""
```

---

## 12. Memory System

4-tier architecture:
- **WorkingMemory**: In-process, bounded deque, auto-summarization
- **ShortTermMemory**: Session-scoped SQL (SQLite/PostgreSQL)
- **LongTermMemory**: Cross-session semantic search (pgvector)
- **EntityMemory**: Structured entity-attribute-value triples
- **MemoryManager**: Unified interface coordinating all tiers

---

## 13. Observability

- **TracingManager**: OpenTelemetry spans (workflow → node → llm/tool)
- **CostTracker**: Per-agent, per-workflow, per-model cost attribution
- **RichConsoleTracer**: Live terminal trace tree with cost waterfall
- **Logging**: structlog with auto-detect (human in dev, JSON in prod)

---

## 14. Security Model

- **AgentIdentity**: Capability-based with 13 capability types (tool:use, state:read/write, network:access, code:exec, etc.)
- **ToolACL**: Per-agent tool permissions (allow_all in dev, deny_all in prod)
- **GuardrailsMiddleware**: Composable pre/post hooks (ContentFilter, PIIDetector, CostLimiter)
- **with_guardrails()**: Decorator for applying guardrails to agents

---

## 15. External Dependencies

**Core (always installed):** pydantic, anyio, httpx, fastapi, sse-starlette, uvicorn, opentelemetry-sdk, structlog, rich, typer, aiosqlite

**Optional extras:** openai, anthropic, google-generativeai, ray, nats-py, asyncpg, pgvector, redis

---

## 16. Key Architectural Decisions

1. **Pydantic BaseModel** for state (not TypedDict) -- validation + serialization for free
2. **Protocol-first** (not ABC) -- structural subtyping, zero inheritance, trivial testing
3. **Graph engine owns traversal, agents own reasoning** -- clean separation, independent testability
4. **Event sourcing is opt-in** -- zero-config in-memory default, durability when storage is configured
5. **Security is opt-in** -- dev_mode grants all capabilities, prod requires explicit grants
6. **AsyncioExecutor default, RayExecutor opt-in** -- zero infrastructure to start, scale when needed
7. **DynamicNode** -- novel first-class concept enabling runtime subgraph generation
