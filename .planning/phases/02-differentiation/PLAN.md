# Phase 2: Differentiation -- Execution Plan

**Phase:** 02-differentiation
**Created:** 2026-03-08
**Status:** Ready for execution
**Plans:** 8 plans across 5 waves
**Estimated effort:** 37 days (Claude execution time)

---

## Table of Contents

1. [Wave Structure](#wave-structure)
2. [Dependency Graph](#dependency-graph)
3. [Plan 01: Event System Foundation (Wave 1)](#plan-01-event-system-foundation)
4. [Plan 02: MCP Client Integration (Wave 1)](#plan-02-mcp-client-integration)
5. [Plan 03: LLM Provider Adapters (Wave 1)](#plan-03-llm-provider-adapters)
6. [Plan 04: SQLite Backend + Rich Trace + Handoff (Wave 2)](#plan-04-sqlite-backend--rich-trace--handoff)
7. [Plan 05: PostgreSQL Backend (Wave 2)](#plan-05-postgresql-backend)
8. [Plan 06: HITL Interrupt/Resume + Tool ACLs (Wave 3)](#plan-06-hitl-interruptresume--tool-acls)
9. [Plan 07: Time-Travel Debugging (Wave 4)](#plan-07-time-travel-debugging)
10. [Plan 08: Advanced Examples (Wave 5)](#plan-08-advanced-examples)
11. [Testing Strategy](#testing-strategy)
12. [Verification Matrix](#verification-matrix)
13. [Risk Register](#risk-register)

---

## Wave Structure

```
Wave 1 (parallel):
  Plan 01: Event System Foundation (DIFF-01)     -- no dependencies
  Plan 02: MCP Client Integration (DIFF-08)      -- no dependencies (uses existing tool system)
  Plan 03: LLM Provider Adapters (DIFF-10)        -- no dependencies (uses existing LLMProvider protocol)

Wave 2 (parallel, depends on Plan 01):
  Plan 04a: SQLite Event Store (DIFF-02)                    -- split from original Plan 04
  Plan 04b: Rich Trace Renderer + Handoff Protocol (DIFF-06, DIFF-07)  -- split from original Plan 04
  Plan 05: PostgreSQL Backend (DIFF-03)

  NOTE: Plan 04 was split before Wave 2 execution to reduce blast radius.
  04a and 04b both depend on Plan 01 but not on each other.

Wave 3 (depends on Plan 04):
  Plan 06: HITL + Tool ACLs (DIFF-04, DIFF-09)

Wave 4 (depends on Plan 06):
  Plan 07: Time-Travel Debugging (DIFF-05)

Wave 5 (depends on all):
  Plan 08: Advanced Examples (DIFF-11)
```

| Wave | Plans | Parallel? | Autonomous |
|------|-------|-----------|------------|
| 1 | 01, 02, 03 | Yes (all 3) | Yes, Yes, Yes |
| 2 | 04, 05 | Yes (both) | Yes, Yes |
| 3 | 06 | Single | No (HITL needs manual verify) |
| 4 | 07 | Single | No (time-travel needs manual verify) |
| 5 | 08 | Single | No (examples need manual verify) |

---

## Dependency Graph

```
Phase 1 (complete)
    |
    +---> Plan 01 (Events) ----+---> Plan 04 (SQLite + Trace + Handoff) ---> Plan 06 (HITL + ACLs) ---> Plan 07 (Time-Travel) ---+
    |                          |                                                                                                  |
    |                          +---> Plan 05 (PostgreSQL) ---------------------------------------- (optional, not on critical path) |
    |                                                                                                                             |
    +---> Plan 02 (MCP) -------+---> Plan 06 (ACLs depend on MCP tools being registered)                                         |
    |                                                                                                                             |
    +---> Plan 03 (Providers)  ---------------------------------------------------------------- (independent) ---+                |
                                                                                                                 |                |
                                                                                                                 v                v
                                                                                                              Plan 08 (Examples)
```

### File Ownership Map (No Conflicts Between Parallel Plans)

| Plan | Files Created | Files Modified |
|------|--------------|----------------|
| 01 | `src/orchestra/storage/events.py`, `storage/store.py`, `storage/serialization.py`, `storage/contracts.py`, `storage/__init__.py` | `src/orchestra/core/errors.py` (add PersistenceError) |
| 02 | `src/orchestra/tools/mcp.py` | `pyproject.toml` (add mcp dep), `src/orchestra/tools/__init__.py` |
| 03 | `src/orchestra/providers/google.py`, `src/orchestra/providers/ollama.py` | `pyproject.toml` (add optional deps), `src/orchestra/providers/__init__.py` |
| 04 | `src/orchestra/storage/sqlite.py`, `src/orchestra/observability/console.py`, `src/orchestra/core/handoff.py`, `src/orchestra/core/context_distill.py` | `src/orchestra/core/graph.py`, `src/orchestra/core/compiled.py`, `src/orchestra/core/context.py` |
| 05 | `src/orchestra/storage/postgres.py` | `pyproject.toml` (add asyncpg) |
| 06 | `src/orchestra/core/hitl.py`, `src/orchestra/core/resume.py`, `src/orchestra/tools/acl.py` | `src/orchestra/core/compiled.py`, `src/orchestra/core/graph.py`, `src/orchestra/tools/registry.py`, `src/orchestra/cli/main.py` |
| 07 | `src/orchestra/debugging/timetravel.py`, `src/orchestra/debugging/replay.py`, `src/orchestra/debugging/__init__.py` | `src/orchestra/cli/main.py` |
| 08 | `examples/handoff.py`, `examples/hitl_review.py`, `examples/time_travel.py` | `tests/integration/test_advanced_examples.py` |

---

## Plan 01: Event System Foundation

**Roadmap task:** DIFF-01 (Event-Sourced Persistence Layer)
**Wave:** 1
**Dependencies:** Phase 1 complete
**Estimated effort:** 5 days
**Autonomous:** Yes

### Objective

Build the storage-agnostic event sourcing infrastructure: event type hierarchy, EventBus for in-process pub/sub, EventStore protocol, JSON/MessagePack serialization, state projection from events, and boundary contract validation per ESAA pattern.

### Architecture: EventBus

The EventBus is the central nervous system for Phase 2. It decouples event producers (CompiledGraph, BaseAgent) from consumers (EventStore, RichTraceRenderer, OTelExporter).

```
                CompiledGraph.run()
                      |
                      v
                 EventBus.emit(event)
                 /       |        \
                v        v         v
          EventStore  TraceRenderer  (future: OTelExporter)
          (persists)  (renders)       (exports spans)
```

**Design:**
- Synchronous, in-process dispatch (no async overhead for event delivery)
- Subscribers are `Callable[[WorkflowEvent], None]` (sync) or `Callable[[WorkflowEvent], Awaitable[None]]` (async)
- Topic-based filtering: subscribers register for specific event types or all events
- EventBus is attached to `ExecutionContext` so all nodes/agents can emit events

### Task 1.1: Event Type Hierarchy

**Files:** `src/orchestra/storage/__init__.py`, `src/orchestra/storage/events.py`

**Action:**

Create the `src/orchestra/storage/` package. Define the event type hierarchy as frozen dataclasses (immutable events). Each event type captures a specific workflow state transition.

```python
# src/orchestra/storage/events.py

@dataclass(frozen=True)
class WorkflowEvent:
    """Base event type. All events are immutable."""
    event_id: str           # UUID
    run_id: str             # Workflow run ID
    timestamp: float        # time.monotonic() for ordering, plus ISO datetime for display
    timestamp_iso: str      # ISO 8601 for human-readable display
    sequence: int           # Monotonic sequence number per run (0, 1, 2, ...)

# Execution lifecycle events
@dataclass(frozen=True)
class ExecutionStarted(WorkflowEvent):
    workflow_name: str
    initial_state: dict[str, Any]
    entry_point: str

@dataclass(frozen=True)
class ExecutionCompleted(WorkflowEvent):
    final_state: dict[str, Any]
    duration_ms: float
    total_tokens: int
    total_cost_usd: float

@dataclass(frozen=True)
class ExecutionFailed(WorkflowEvent):
    error_type: str
    error_message: str
    node_id: str | None

# Node lifecycle events
@dataclass(frozen=True)
class NodeStarted(WorkflowEvent):
    node_id: str
    node_type: str          # "agent", "function", "subgraph"
    input_state: dict[str, Any]

@dataclass(frozen=True)
class NodeCompleted(WorkflowEvent):
    node_id: str
    node_type: str
    output_update: dict[str, Any]
    duration_ms: float

@dataclass(frozen=True)
class NodeFailed(WorkflowEvent):
    node_id: str
    error_type: str
    error_message: str

# State events
@dataclass(frozen=True)
class StateUpdated(WorkflowEvent):
    node_id: str
    field_updates: dict[str, Any]
    state_version: int

@dataclass(frozen=True)
class CheckpointCreated(WorkflowEvent):
    checkpoint_id: str
    node_id: str
    state_snapshot: dict[str, Any]
    event_sequence: int     # Sequence number at checkpoint time

# Agent events
@dataclass(frozen=True)
class LLMCalled(WorkflowEvent):
    node_id: str
    agent_name: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_ms: float
    finish_reason: str

@dataclass(frozen=True)
class ToolCalled(WorkflowEvent):
    node_id: str
    agent_name: str
    tool_name: str
    arguments: dict[str, Any]
    result: str
    error: str | None
    duration_ms: float

# Handoff events (used by Plan 04)
@dataclass(frozen=True)
class HandoffInitiated(WorkflowEvent):
    from_agent: str
    to_agent: str
    reason: str
    context_tokens: int

@dataclass(frozen=True)
class HandoffCompleted(WorkflowEvent):
    from_agent: str
    to_agent: str

# HITL events (used by Plan 06)
@dataclass(frozen=True)
class InterruptRequested(WorkflowEvent):
    node_id: str
    interrupt_type: str     # "before" or "after"

@dataclass(frozen=True)
class InterruptResumed(WorkflowEvent):
    node_id: str
    state_modifications: dict[str, Any]

# Validation events (ESAA pattern)
@dataclass(frozen=True)
class OutputValidated(WorkflowEvent):
    node_id: str
    agent_name: str
    schema_name: str

@dataclass(frozen=True)
class OutputRejected(WorkflowEvent):
    node_id: str
    agent_name: str
    schema_name: str
    validation_errors: list[str]
```

Also define an `EventType` enum mapping each class to a string discriminator for serialization:

```python
class EventType(str, Enum):
    EXECUTION_STARTED = "execution.started"
    EXECUTION_COMPLETED = "execution.completed"
    EXECUTION_FAILED = "execution.failed"
    NODE_STARTED = "node.started"
    NODE_COMPLETED = "node.completed"
    NODE_FAILED = "node.failed"
    STATE_UPDATED = "state.updated"
    CHECKPOINT_CREATED = "checkpoint.created"
    LLM_CALLED = "llm.called"
    TOOL_CALLED = "tool.called"
    HANDOFF_INITIATED = "handoff.initiated"
    HANDOFF_COMPLETED = "handoff.completed"
    INTERRUPT_REQUESTED = "interrupt.requested"
    INTERRUPT_RESUMED = "interrupt.resumed"
    OUTPUT_VALIDATED = "output.validated"
    OUTPUT_REJECTED = "output.rejected"
```

Create `__init__.py` with `__all__` exports for all event types.

**Verify:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -c "from orchestra.storage.events import WorkflowEvent, ExecutionStarted, NodeStarted, EventType; print('OK')"
```

**Done:** All 16 event types importable. Each is frozen dataclass. EventType enum covers all types.

---

### Task 1.2: EventBus and EventStore Protocol

**Files:** `src/orchestra/storage/store.py`

**Action:**

Define the `EventBus` (in-process pub/sub) and `EventStore` Protocol (persistence interface).

**EventBus:**

```python
class EventBus:
    """In-process event dispatcher.

    Synchronous dispatch to subscribers. Subscribers registered
    by event type or wildcard (all events).
    """

    def __init__(self) -> None:
        self._subscribers: dict[type[WorkflowEvent] | None, list[Callable]] = {}
        self._sequence_counters: dict[str, int] = {}  # per run_id

    def subscribe(
        self,
        callback: Callable[[WorkflowEvent], None | Awaitable[None]],
        event_types: list[type[WorkflowEvent]] | None = None,
    ) -> None:
        """Register a subscriber. None event_types = all events."""
        ...

    def emit(self, event: WorkflowEvent) -> None:
        """Dispatch event to matching subscribers. Sync dispatch."""
        ...

    def next_sequence(self, run_id: str) -> int:
        """Get next monotonic sequence number for a run."""
        ...
```

**EventStore Protocol:**

```python
@runtime_checkable
class EventStore(Protocol):
    """Protocol for event persistence backends."""

    async def append(self, event: WorkflowEvent) -> None:
        """Append an event. Must be idempotent on event_id."""
        ...

    async def get_events(
        self,
        run_id: str,
        after_sequence: int = 0,
        event_types: list[EventType] | None = None,
    ) -> list[WorkflowEvent]:
        """Get events for a run, optionally filtered."""
        ...

    async def get_latest_checkpoint(
        self, run_id: str
    ) -> CheckpointCreated | None:
        """Get the most recent checkpoint for a run."""
        ...

    async def save_checkpoint(
        self, run_id: str, checkpoint: CheckpointCreated
    ) -> None:
        """Save a state checkpoint."""
        ...

    async def list_runs(
        self, limit: int = 50, status: str | None = None
    ) -> list[dict[str, Any]]:
        """List workflow runs with metadata."""
        ...
```

**State Projection:**

```python
def project_state(
    events: list[WorkflowEvent],
    initial_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Rebuild current state from event sequence.

    Applies StateUpdated events in sequence order.
    If a CheckpointCreated event is found, starts from that snapshot.
    """
    ...
```

**InMemoryEventStore** (for testing):

```python
class InMemoryEventStore:
    """Non-persistent event store for testing."""

    def __init__(self) -> None:
        self._events: dict[str, list[WorkflowEvent]] = {}
        self._checkpoints: dict[str, list[CheckpointCreated]] = {}

    async def append(self, event: WorkflowEvent) -> None: ...
    async def get_events(self, run_id: str, ...) -> list[WorkflowEvent]: ...
    async def get_latest_checkpoint(self, run_id: str) -> CheckpointCreated | None: ...
    async def save_checkpoint(self, run_id: str, checkpoint: CheckpointCreated) -> None: ...
    async def list_runs(self, limit: int = 50, status: str | None = None) -> list[dict[str, Any]]: ...
```

Add `EventBus` field to `ExecutionContext` (modify `src/orchestra/core/context.py`):

```python
# Add to ExecutionContext:
event_bus: EventBus | None = None
```

**Verify:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -c "
from orchestra.storage.store import EventBus, EventStore, InMemoryEventStore, project_state
bus = EventBus()
store = InMemoryEventStore()
assert isinstance(store, EventStore)
print('OK')
"
```

**Done:** EventBus dispatches events. EventStore protocol defined. InMemoryEventStore works. project_state rebuilds state from events.

---

### Task 1.3: Event Serialization

**Files:** `src/orchestra/storage/serialization.py`

**Action:**

Implement JSON and MessagePack serialization for events. Events must round-trip perfectly (serialize -> deserialize produces identical event).

```python
def event_to_dict(event: WorkflowEvent) -> dict[str, Any]:
    """Convert event to a plain dict with type discriminator."""
    ...

def dict_to_event(data: dict[str, Any]) -> WorkflowEvent:
    """Reconstruct event from dict using type discriminator."""
    ...

def event_to_json(event: WorkflowEvent) -> str:
    """Serialize event to JSON string."""
    ...

def json_to_event(json_str: str) -> WorkflowEvent:
    """Deserialize event from JSON string."""
    ...

def event_to_msgpack(event: WorkflowEvent) -> bytes:
    """Serialize event to MessagePack bytes."""
    ...

def msgpack_to_event(data: bytes) -> WorkflowEvent:
    """Deserialize event from MessagePack bytes."""
    ...
```

Use a type registry mapping `EventType` enum -> event class for deserialization.

Add `msgpack` to pyproject.toml optional dependencies (under a `storage` extra).

Handle special types in serialization:
- `dict[str, Any]` -> JSON-safe (already)
- `float` timestamps -> preserved exactly
- `None` values -> preserved

**Verify:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -c "
from orchestra.storage.events import ExecutionStarted
from orchestra.storage.serialization import event_to_json, json_to_event
import time, uuid
event = ExecutionStarted(
    event_id=uuid.uuid4().hex, run_id='test', timestamp=time.monotonic(),
    timestamp_iso='2026-03-08T00:00:00Z', sequence=0,
    workflow_name='test', initial_state={'x': 1}, entry_point='start'
)
roundtrip = json_to_event(event_to_json(event))
assert roundtrip == event
print('OK')
"
```

**Done:** JSON and MessagePack serialization round-trips all 16 event types.

---

### Task 1.4: Boundary Contract Validation (ESAA Pattern)

**Files:** `src/orchestra/storage/contracts.py`

**Action:**

Implement boundary contract validation: agent outputs are validated against JSON Schema before events are persisted. Invalid outputs produce `OutputRejected` events instead of corrupting the event log.

```python
class BoundaryContract:
    """Validates agent output against a JSON Schema before persistence.

    Per ESAA pattern (arXiv:2602.23193): cleanly separates
    probabilistic LLM cognition from deterministic state mutation.
    """

    def __init__(self, schema: dict[str, Any], name: str = "") -> None:
        self._schema = schema
        self._name = name

    def validate(self, output: dict[str, Any]) -> list[str]:
        """Validate output against schema. Returns list of errors (empty = valid)."""
        ...

    @classmethod
    def from_pydantic(cls, model: type[BaseModel]) -> BoundaryContract:
        """Create contract from a Pydantic model's JSON Schema."""
        ...


class ContractRegistry:
    """Maps agent names to their boundary contracts."""

    def register(self, agent_name: str, contract: BoundaryContract) -> None: ...
    def validate(self, agent_name: str, output: dict[str, Any]) -> list[str]: ...
    def has_contract(self, agent_name: str) -> bool: ...
```

Use `jsonschema` library for validation (add to dependencies). Keep validation fast -- contracts are checked on every state update.

**Verify:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -c "
from orchestra.storage.contracts import BoundaryContract
from pydantic import BaseModel

class MyOutput(BaseModel):
    summary: str
    score: int

contract = BoundaryContract.from_pydantic(MyOutput)
errors = contract.validate({'summary': 'test', 'score': 5})
assert errors == []
errors = contract.validate({'summary': 'test', 'score': 'not_int'})
assert len(errors) > 0
print('OK')
"
```

**Done:** Boundary contracts validate agent outputs. Invalid outputs are caught before event persistence.

---

### Task 1.5: Unit Tests for Event System

**Files:** `tests/unit/test_events.py`

**Action:**

Write comprehensive tests. Minimum 15 tests covering:

1. Event creation (each type, frozen immutability)
2. EventBus subscribe/emit (type-filtered and wildcard)
3. EventBus sequence numbering (monotonic per run_id)
4. InMemoryEventStore append/get_events
5. InMemoryEventStore checkpoint save/restore
6. State projection from events
7. State projection with checkpoint shortcut
8. JSON serialization round-trip (all 16 types)
9. MessagePack serialization round-trip
10. Boundary contract validation (valid output)
11. Boundary contract validation (invalid output -> errors)
12. Contract from Pydantic model
13. Event ordering guarantees (sequence numbers)
14. EventStore Protocol conformance (isinstance check)
15. Empty event list projection returns initial state

Follow existing test patterns: `class TestEvents:`, `class TestEventBus:`, `class TestEventStore:`, `class TestSerialization:`, `class TestContracts:`.

**Verify:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -m pytest tests/unit/test_events.py -v --tb=short
```

**Done:** All 15+ tests pass. Event system is fully tested.

---

### Error Types

Add to `src/orchestra/core/errors.py`:

```python
# --- Persistence Errors ---

class PersistenceError(OrchestraError):
    """Base for storage/persistence errors."""

class EventStoreError(PersistenceError):
    """Raised when event store operations fail."""

class CheckpointError(PersistenceError):
    """Raised when checkpoint operations fail."""

class ContractValidationError(PersistenceError):
    """Raised when agent output fails boundary contract validation."""
```

---

## Plan 02: MCP Client Integration

**Roadmap task:** DIFF-08 (MCP Client Integration)
**Wave:** 1
**Dependencies:** Phase 1 complete (tool system exists)
**Estimated effort:** 5 days
**Autonomous:** Yes

### Objective

Implement MCP client that discovers and invokes tools from MCP servers. MCP tools look identical to native `@tool`-decorated tools. Support stdio and Streamable HTTP transports per MCP 2025-11-25 spec.

### Task 2.1: MCP Client Core

**Files:** `src/orchestra/tools/mcp.py`

**Action:**

Implement the MCP client with transport abstraction and tool adapter.

**Transport Layer:**

```python
class MCPTransport(Protocol):
    """Transport for MCP JSON-RPC communication."""
    async def send(self, message: dict[str, Any]) -> None: ...
    async def receive(self) -> dict[str, Any]: ...
    async def close(self) -> None: ...

class StdioTransport:
    """stdio transport -- communicates with MCP server via subprocess stdin/stdout."""
    def __init__(self, command: str, args: list[str] | None = None, env: dict[str, str] | None = None) -> None: ...
    async def start(self) -> None:
        """Launch subprocess.""" ...
    async def send(self, message: dict[str, Any]) -> None:
        """Write JSON-RPC message to subprocess stdin.""" ...
    async def receive(self) -> dict[str, Any]:
        """Read JSON-RPC response from subprocess stdout.""" ...
    async def close(self) -> None:
        """Terminate subprocess.""" ...

class StreamableHTTPTransport:
    """Streamable HTTP transport -- single /mcp endpoint with GET/POST/DELETE.
    Supports stream resumption via Last-Event-ID header."""
    def __init__(self, url: str, headers: dict[str, str] | None = None) -> None: ...
    async def send(self, message: dict[str, Any]) -> None: ...
    async def receive(self) -> dict[str, Any]: ...
    async def close(self) -> None: ...
```

**MCP Client:**

```python
class MCPClient:
    """Client for MCP (Model Context Protocol) servers.

    Discovers tools via tools/list, invokes via tools/call.
    Tools are adapted to look like native Orchestra tools.

    Usage:
        mcp = MCPClient("npx @modelcontextprotocol/server-filesystem")
        await mcp.connect()
        tools = mcp.get_tools()  # Returns list[ToolWrapper]
        # These tools work identically to @tool-decorated functions
    """

    def __init__(
        self,
        command_or_url: str,
        *,
        transport: str = "auto",  # "stdio", "http", or "auto" (detect from input)
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None: ...

    async def connect(self) -> None:
        """Initialize connection: handshake, capability negotiation.""" ...

    async def disconnect(self) -> None:
        """Clean shutdown.""" ...

    async def discover_tools(self) -> list[dict[str, Any]]:
        """Send tools/list, return tool schemas.""" ...

    def get_tools(self) -> list[MCPToolAdapter]:
        """Get discovered tools as Orchestra-compatible ToolWrappers.""" ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Send tools/call, return result.""" ...

    async def __aenter__(self) -> MCPClient: ...
    async def __aexit__(self, *args: Any) -> None: ...
```

**MCPToolAdapter (transparent to agents):**

```python
class MCPToolAdapter:
    """Adapts an MCP tool to look like a native Orchestra tool.

    Agents cannot distinguish MCPToolAdapter from ToolWrapper.
    Satisfies the Tool protocol.
    """

    def __init__(self, client: MCPClient, tool_schema: dict[str, Any]) -> None: ...

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def parameters_schema(self) -> dict[str, Any]: ...

    async def execute(
        self,
        arguments: dict[str, Any],
        *,
        context: ExecutionContext | None = None,
    ) -> ToolResult:
        """Execute tool via MCP tools/call. Produces ToolResult identical to native tools."""
        ...
```

**JSON-RPC helpers:**

```python
def _jsonrpc_request(method: str, params: dict[str, Any] | None = None, id: int | str | None = None) -> dict[str, Any]: ...
def _jsonrpc_notification(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]: ...
```

**MCP config file discovery:**

```python
def load_mcp_config(config_path: str | None = None) -> list[dict[str, Any]]:
    """Load MCP server configs from .orchestra/mcp.json if it exists."""
    ...
```

Config file format (`.orchestra/mcp.json`):
```json
{
  "servers": [
    {
      "name": "filesystem",
      "command": "npx",
      "args": ["@modelcontextprotocol/server-filesystem", "/path/to/dir"],
      "transport": "stdio"
    },
    {
      "name": "remote-api",
      "url": "https://api.example.com/mcp",
      "transport": "http",
      "headers": {"Authorization": "Bearer ${MCP_TOKEN}"}
    }
  ]
}
```

Add `MCPError` to errors.py:

```python
class MCPError(OrchestraError):
    """Base for MCP-related errors."""

class MCPConnectionError(MCPError):
    """Raised when MCP server connection fails."""

class MCPToolError(MCPError):
    """Raised when MCP tool execution fails."""

class MCPTimeoutError(MCPError):
    """Raised when MCP server times out."""
```

Update `src/orchestra/tools/__init__.py` to export `MCPClient`, `MCPToolAdapter`.

**Verify:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -c "
from orchestra.tools.mcp import MCPClient, MCPToolAdapter, StdioTransport, StreamableHTTPTransport
from orchestra.core.protocols import Tool
print('imports OK')
"
```

**Done:** MCPClient connects, discovers tools, and adapts them to Orchestra's Tool protocol. Both stdio and Streamable HTTP transports work.

---

### Task 2.2: MCP Tests with Mock Server

**Files:** `tests/unit/test_mcp.py`

**Action:**

Build a mock MCP server (in-process, no subprocess) and test all MCP client functionality.

```python
class MockMCPServer:
    """In-process mock MCP server for testing.

    Responds to JSON-RPC initialize, tools/list, and tools/call.
    """
    def __init__(self, tools: list[dict[str, Any]]) -> None: ...
    async def handle(self, request: dict[str, Any]) -> dict[str, Any]: ...
```

Tests (minimum 10):
1. Initialize handshake (capability negotiation)
2. tools/list discovery returns tool schemas
3. tools/call invocation returns results
4. MCPToolAdapter satisfies Tool protocol (`isinstance` check)
5. MCPToolAdapter.execute returns ToolResult
6. Error handling: tool execution failure
7. Error handling: server timeout
8. Error handling: server disconnection
9. Streamable HTTP transport Last-Event-ID resumption
10. Config file loading from `.orchestra/mcp.json`

**Verify:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -m pytest tests/unit/test_mcp.py -v --tb=short
```

**Done:** All 10+ MCP tests pass using mock server.

---

## Plan 03: LLM Provider Adapters

**Roadmap task:** DIFF-10 (Google and Ollama Providers)
**Wave:** 1
**Dependencies:** Phase 1 complete (LLMProvider protocol exists)
**Estimated effort:** 4 days
**Autonomous:** Yes

### Objective

Implement GoogleProvider (Gemini) and OllamaProvider (OpenAI-compatible local) adapters conforming to the existing `LLMProvider` Protocol.

### Task 3.1: Google Gemini Provider

**Files:** `src/orchestra/providers/google.py`

**Action:**

Implement GoogleProvider using `httpx` directly (same pattern as AnthropicProvider -- no SDK dependency required). The Gemini API uses a different message format and tool calling schema than OpenAI.

Key implementation details:
- Gemini API endpoint: `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`
- API key auth via query parameter `?key={API_KEY}` or `x-goog-api-key` header
- Message format: `contents[].parts[].text` (not `messages[].content`)
- Tool calling: `tools[].functionDeclarations[]` (not `tools[].function`)
- Streaming: Server-sent events via `streamGenerateContent?alt=sse`
- Token counting: Response includes `usageMetadata.promptTokenCount`, `candidatesTokenCount`
- Supports function calling with `toolConfig.functionCallingConfig`

Reference `src/orchestra/providers/anthropic.py` (384 lines) for the adapter pattern:
- `_messages_to_gemini_format()` converter
- `_gemini_tool_to_orchestra()` converter
- Error mapping to Orchestra error hierarchy
- Cost tracking using `_MODEL_COSTS` dict

Model costs (per 1K tokens):
```python
_MODEL_COSTS = {
    "gemini-2.0-flash": (0.0001, 0.0004),
    "gemini-2.0-flash-lite": (0.000075, 0.0003),
    "gemini-2.5-pro-preview-06-05": (0.00125, 0.01),
    "gemini-2.5-flash-preview-05-20": (0.00015, 0.0035),
}
```

The provider must:
- Implement all 4 methods of `LLMProvider`: `complete()`, `stream()`, `count_tokens()`, `get_model_cost()`
- Handle Gemini-specific error codes (400 bad request, 403 permission denied, 429 rate limit, 500 server error)
- Support `output_type` via Gemini's JSON mode (`response_mime_type: "application/json"`)

**Verify:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -c "
from orchestra.providers.google import GoogleProvider
from orchestra.core.protocols import LLMProvider
p = GoogleProvider(api_key='test')
assert isinstance(p, LLMProvider)
print('protocol conformance OK')
"
```

**Done:** GoogleProvider implements LLMProvider protocol. All 4 methods present. Error mapping correct.

---

### Task 3.2: Ollama Provider

**Files:** `src/orchestra/providers/ollama.py`

**Action:**

Implement OllamaProvider. Ollama exposes an OpenAI-compatible API at `http://localhost:11434/v1/`, so this adapter can be simpler -- it extends the HTTP-based approach similar to HttpProvider but with Ollama-specific defaults.

Key implementation details:
- Default base URL: `http://localhost:11434/v1/`
- No API key required (local)
- OpenAI-compatible chat completions endpoint: `/chat/completions`
- Supports tool calling for models that support it (llama3.1+, mistral, etc.)
- Streaming via SSE like OpenAI
- No built-in cost tracking (local models have no API cost), but track token counts
- Model listing via `GET /api/tags` (Ollama-native endpoint, not OpenAI-compatible)
- Health check via `GET /` (returns "Ollama is running")

The provider must handle:
- Connection refused (Ollama not running) -> `ProviderUnavailableError` with helpful message
- Model not found -> descriptive error with `ollama pull <model>` suggestion
- Models without tool support -> graceful degradation (ignore tools parameter)

```python
class OllamaProvider:
    """Local LLM provider using Ollama.

    Usage:
        provider = OllamaProvider()  # Uses localhost:11434
        provider = OllamaProvider(base_url="http://gpu-server:11434")
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        default_model: str = "llama3.1",
        timeout: float = 120.0,
    ) -> None: ...
```

**Verify:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -c "
from orchestra.providers.ollama import OllamaProvider
from orchestra.core.protocols import LLMProvider
p = OllamaProvider()
assert isinstance(p, LLMProvider)
print('protocol conformance OK')
"
```

**Done:** OllamaProvider implements LLMProvider protocol. Works with any Ollama model.

---

### Task 3.3: Provider Tests

**Files:** `tests/unit/test_providers.py`

**Action:**

Write tests for both providers using mocked HTTP responses (httpx mock transport). Minimum 16 tests (8 per provider).

**Google tests:**
1. Complete (chat, no tools) -> LLMResponse
2. Complete with tool calling -> LLMResponse with tool_calls
3. Streaming -> yields StreamChunks
4. Error: invalid API key -> AuthenticationError
5. Error: rate limit -> RateLimitError
6. Error: context window exceeded -> ContextWindowError
7. Token counting -> int
8. Model cost lookup -> ModelCost

**Ollama tests:**
1. Complete (chat, no tools) -> LLMResponse
2. Complete with tool calling -> LLMResponse with tool_calls
3. Streaming -> yields StreamChunks
4. Error: connection refused -> ProviderUnavailableError
5. Error: model not found -> ProviderError with pull suggestion
6. Token counting -> int (from response usage)
7. Model cost -> ModelCost(0.0, 0.0) (local = free)
8. Health check

**Verify:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -m pytest tests/unit/test_providers.py -v --tb=short
```

**Done:** All 16 provider tests pass. Both adapters conform to LLMProvider protocol.

---

### Update pyproject.toml

Add optional dependencies:

```toml
[project.optional-dependencies]
anthropic = ["anthropic>=0.20"]
google = ["google-generativeai>=0.5"]
ollama = []  # No SDK needed, uses httpx
storage = ["aiosqlite>=0.19", "msgpack>=1.0"]
postgres = ["asyncpg>=0.29"]
all-providers = ["orchestra-agents[anthropic,google]"]
all = ["orchestra-agents[anthropic,google,storage,postgres]"]
```

Update `src/orchestra/providers/__init__.py`:

```python
from orchestra.providers.http import HttpProvider

__all__ = ["HttpProvider"]

# Lazy imports for optional providers
def __getattr__(name: str):
    if name == "AnthropicProvider":
        from orchestra.providers.anthropic import AnthropicProvider
        return AnthropicProvider
    if name == "GoogleProvider":
        from orchestra.providers.google import GoogleProvider
        return GoogleProvider
    if name == "OllamaProvider":
        from orchestra.providers.ollama import OllamaProvider
        return OllamaProvider
    raise AttributeError(f"module 'orchestra.providers' has no attribute {name}")
```

---

## Plan 04: SQLite Backend + Rich Trace + Handoff

**Roadmap tasks:** DIFF-02 (SQLite), DIFF-06 (Rich Trace), DIFF-07 (Handoff)
**Wave:** 2
**Dependencies:** Plan 01 (event system)
**Estimated effort:** 7 days (combined -- shared integration into compiled.py)
**Autonomous:** Yes

### Rationale for Grouping

SQLite, Rich Trace, and Handoff are grouped because they all:
1. Depend on Plan 01's EventBus and event types
2. Require modifications to the same files (`compiled.py`, `context.py`, `graph.py`)
3. Are EventBus subscribers (SQLite persists events, Rich renders events, Handoff emits events)

Doing them together avoids three sequential edits to `compiled.py`.

### Task 4.1: SQLite Storage Backend

**Files:** `src/orchestra/storage/sqlite.py`

**Action:**

Implement `SQLiteEventStore` conforming to the `EventStore` protocol.

**Schema (auto-created on first use):**

```sql
-- WAL mode for concurrent read/write
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id TEXT PRIMARY KEY,
    workflow_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',  -- running, completed, failed, interrupted
    started_at TEXT NOT NULL,
    completed_at TEXT,
    entry_point TEXT,
    metadata TEXT  -- JSON
);

CREATE TABLE IF NOT EXISTS workflow_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    timestamp_iso TEXT NOT NULL,
    data TEXT NOT NULL,  -- JSON serialized event
    FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_events_run_seq ON workflow_events(run_id, sequence);
CREATE INDEX IF NOT EXISTS idx_events_type ON workflow_events(event_type);

CREATE TABLE IF NOT EXISTS workflow_checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL UNIQUE,
    node_id TEXT NOT NULL,
    sequence_at INTEGER NOT NULL,
    state_snapshot TEXT NOT NULL,  -- JSON
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_run ON workflow_checkpoints(run_id);
```

**Implementation:**

```python
class SQLiteEventStore:
    """SQLite-backed event store. Zero-config default backend.

    Database location: .orchestra/runs.db (auto-created on first use).
    Uses WAL mode for concurrent access from parallel nodes.

    Usage:
        store = SQLiteEventStore()  # Uses .orchestra/runs.db
        store = SQLiteEventStore("path/to/custom.db")
        await store.initialize()  # Creates tables if needed
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or ".orchestra/runs.db"

    async def initialize(self) -> None:
        """Create .orchestra/ dir and tables if needed.""" ...

    async def append(self, event: WorkflowEvent) -> None: ...
    async def get_events(self, run_id: str, ...) -> list[WorkflowEvent]: ...
    async def get_latest_checkpoint(self, run_id: str) -> CheckpointCreated | None: ...
    async def save_checkpoint(self, run_id: str, checkpoint: CheckpointCreated) -> None: ...
    async def list_runs(self, limit: int = 50, ...) -> list[dict[str, Any]]: ...

    async def create_run(self, run_id: str, workflow_name: str, entry_point: str) -> None: ...
    async def update_run_status(self, run_id: str, status: str) -> None: ...
```

**Snapshotting (every 50 events by default):**

```python
class SnapshotManager:
    """Periodically creates state snapshots to speed up restoration.

    Subscribes to EventBus. After every N events (default 50),
    projects current state and saves a checkpoint.
    """

    def __init__(self, store: EventStore, interval: int = 50) -> None: ...

    def on_event(self, event: WorkflowEvent) -> None:
        """EventBus subscriber callback.""" ...
```

Add `aiosqlite` to dependencies (storage extra group).

**Verify:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -m pytest tests/unit/test_sqlite_store.py -v --tb=short
```

**Done:** SQLiteEventStore passes all EventStore protocol tests. Database auto-initializes. WAL mode enabled. Snapshots created every 50 events.

---

### Task 4.2: Rich Console Trace Renderer

**Files:** `src/orchestra/observability/console.py`

**Action:**

Implement the Rich-based real-time trace renderer. This is an EventBus subscriber that builds a live-updating tree as workflow events stream in.

```python
class RichTraceRenderer:
    """Real-time terminal trace renderer using Rich.

    Subscribes to EventBus and renders a live-updating tree:

      Workflow: customer_support [3.2s]
      +-- triage (gpt-4o-mini) [1.1s] 150 tok $0.001 OK
      |   +-- LLM call [0.8s] 100 in / 50 out
      |   +-- tool: classify_ticket({priority: "high"}) -> "billing" [0.3s]
      +-- billing_agent (gpt-4o) [2.1s] 500 tok $0.015 OK
      |   +-- LLM call [1.8s] 350 in / 150 out
      |   +-- tool: lookup_account({id: "123"}) -> "{balance: 50}" [0.3s]
      +-- TOTAL: 650 tokens, $0.016, 3.2s

    Controlled by environment variables:
    - ORCHESTRA_TRACE=rich (default in dev) / off / verbose
    - ORCHESTRA_ENV=dev (default) / prod (disables trace)
    """

    def __init__(self, verbose: bool = False) -> None:
        self._tree = Tree("Workflow")
        self._live: Live | None = None
        self._node_branches: dict[str, Any] = {}  # node_id -> Rich Tree branch
        self._verbose = verbose

    def start(self) -> None:
        """Start Rich Live display.""" ...

    def stop(self) -> None:
        """Stop Rich Live display, render final tree.""" ...

    def on_event(self, event: WorkflowEvent) -> None:
        """EventBus subscriber. Updates tree based on event type."""
        ...
```

**Event-to-rendering mapping:**

| Event Type | Rendering |
|------------|-----------|
| ExecutionStarted | Create root tree node: "Workflow: {name}" |
| NodeStarted | Add branch with spinner: "{node_id} ({model}) ..." |
| LLMCalled | Add leaf: "LLM call [{duration}] {in_tok} in / {out_tok} out ${cost}" |
| ToolCalled | Add leaf: "tool: {name}({args}) -> {result} [{duration}]" |
| NodeCompleted | Update branch: replace spinner with checkmark, add totals |
| NodeFailed | Update branch: red X with error message |
| InterruptRequested | Yellow "PAUSED - awaiting human input" |
| HandoffInitiated | "handoff: {from} -> {to} ({reason})" |
| ExecutionCompleted | Add total line: "TOTAL: {tokens} tokens, ${cost}, {duration}" |
| ExecutionFailed | Red error summary |

**Color coding:**
- Green: success (`style="green"`)
- Yellow: HITL interrupts (`style="yellow"`)
- Red: errors (`style="red"`)
- Cyan: tool calls (`style="cyan"`)
- Dim: verbose details (`style="dim"`)

**Verbose mode (`ORCHESTRA_TRACE=verbose`):** Shows tool arguments (full, not truncated), LLM response snippets (first 200 chars), state field changes.

**Performance:** The renderer must not slow down execution by more than 5%. Use Rich's `Live` with a reasonable refresh rate (4 Hz = 250ms interval).

**Verify:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -c "
from orchestra.observability.console import RichTraceRenderer
from orchestra.storage.events import NodeStarted, NodeCompleted
import time, uuid
renderer = RichTraceRenderer()
# Verify it handles events without crashing
renderer.on_event(NodeStarted(
    event_id=uuid.uuid4().hex, run_id='test', timestamp=time.monotonic(),
    timestamp_iso='2026-03-08T00:00:00Z', sequence=0,
    node_id='agent1', node_type='agent', input_state={}
))
print('renderer OK')
"
```

**Done:** Rich trace renderer displays live tree. Color coding correct. Verbose mode shows details. Performance overhead under 5%.

---

### Task 4.3: Handoff Protocol

**Files:** `src/orchestra/core/handoff.py`, `src/orchestra/core/context_distill.py`

**Action:**

Implement Swarm-style agent handoffs as a first-class edge type with context distillation.

**Handoff Edge (in handoff.py):**

```python
@dataclass(frozen=True)
class HandoffPayload:
    """Context transferred during handoff."""
    from_agent: str
    to_agent: str
    reason: str
    conversation_history: list[Message]
    metadata: dict[str, Any]
    distilled: bool  # Whether context was distilled

@dataclass(frozen=True)
class HandoffEdge:
    """Edge type for agent handoffs.

    Created via graph.add_handoff(). Transfers execution context
    from one agent to another with optional context distillation.
    """
    source: str
    target: str
    condition: EdgeCondition | None = None
    distill: bool = True  # Use context distillation by default
```

**add_handoff on WorkflowGraph (modify graph.py):**

```python
def add_handoff(
    self,
    from_agent: str,
    to_agent: str,
    *,
    condition: EdgeCondition | None = None,
    distill: bool = True,
) -> WorkflowGraph:
    """Add a handoff edge between agents.

    Usage:
        graph.add_handoff("triage", "specialist", condition=needs_expert)
        graph.add_handoff("researcher", "writer")  # Unconditional
    """
    ...
```

**Context Distillation (in context_distill.py):**

Three-zone model per CONTEXT.md decision:
1. **Stable prefix:** System instructions, objective, agent identities (kept intact)
2. **Compacted middleware:** Summarized intermediate reasoning and tool history (compressed)
3. **Variable suffix:** Latest turn, current tool outputs (kept intact)

```python
def distill_context(
    messages: list[Message],
    *,
    max_middleware_tokens: int = 500,
    keep_last_n_turns: int = 3,
) -> list[Message]:
    """Distill conversation history for handoff.

    Reduces token count while preserving task-relevant information.

    Three-zone partitioning:
    1. Stable prefix (system messages) -- kept intact
    2. Compacted middleware (intermediate messages) -- summarized
    3. Variable suffix (last N turns) -- kept intact
    """
    ...

def full_passthrough(messages: list[Message]) -> list[Message]:
    """No distillation -- pass all messages as-is."""
    return list(messages)
```

**Integration with CompiledGraph (modify compiled.py):**

In `_resolve_next()`, when a `HandoffEdge` is encountered:
1. Build `HandoffPayload` from current agent's conversation history
2. Optionally distill context
3. Emit `HandoffInitiated` event via EventBus
4. Set up target agent's input with the handoff payload
5. After target completes, emit `HandoffCompleted` event

**Verify:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -m pytest tests/unit/test_handoff.py -v --tb=short
```

**Done:** add_handoff creates valid edges. Context distillation reduces tokens. Handoff events emitted. Conditional handoffs route correctly.

---

### Task 4.4: Integration -- Wire EventBus into CompiledGraph

**Files:** `src/orchestra/core/compiled.py` (modify), `src/orchestra/core/context.py` (modify)

**Action:**

This is the critical wiring task. Modify `CompiledGraph.run()` to emit events at key points.

**Modifications to CompiledGraph.run():**

```python
async def run(self, ..., persist: bool = True, event_store: EventStore | None = None) -> dict[str, Any]:
    # 1. Create EventBus, attach to context
    event_bus = EventBus()
    context.event_bus = event_bus

    # 2. If persistence enabled, set up SQLite store and subscribe
    if persist and event_store is None:
        from orchestra.storage.sqlite import SQLiteEventStore
        event_store = SQLiteEventStore()
        await event_store.initialize()
    if event_store:
        event_bus.subscribe(lambda e: asyncio.ensure_future(event_store.append(e)))

    # 3. Set up Rich trace if enabled
    trace_mode = os.environ.get("ORCHESTRA_TRACE", "rich" if os.environ.get("ORCHESTRA_ENV", "dev") == "dev" else "off")
    if trace_mode != "off":
        renderer = RichTraceRenderer(verbose=(trace_mode == "verbose"))
        event_bus.subscribe(renderer.on_event)
        renderer.start()

    # 4. Emit ExecutionStarted
    event_bus.emit(ExecutionStarted(...))

    # 5. In the main loop, wrap node execution:
    #    Before: event_bus.emit(NodeStarted(...))
    #    After:  event_bus.emit(NodeCompleted(...))
    #    Error:  event_bus.emit(NodeFailed(...))
    #    State:  event_bus.emit(StateUpdated(...))

    # 6. After loop, emit ExecutionCompleted or ExecutionFailed

    # 7. Stop renderer if started
```

**Modifications to BaseAgent.run() (agent.py):**

After each LLM call, emit `LLMCalled` event via `context.event_bus`.
After each tool call, emit `ToolCalled` event via `context.event_bus`.
Check event_bus is not None before emitting (backwards-compatible).

**Modifications to ExecutionContext (context.py):**

Add fields:
```python
event_bus: Any = None          # EventBus instance
replay_mode: bool = False      # True during time-travel replay (suppresses side effects)
interrupt_signal: Any = None   # Set by HITL interrupt
```

**Verify:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -m pytest tests/unit/test_core.py -v --tb=short && python -m pytest tests/unit/test_events.py tests/unit/test_sqlite_store.py tests/unit/test_handoff.py -v --tb=short
```

**Done:** Existing tests still pass. Events emitted during workflow execution. SQLite store persists events. Rich trace renders live tree. Handoffs work end-to-end.

---

### Task 4.5: Tests for Plan 04

**Files:** `tests/unit/test_sqlite_store.py`, `tests/unit/test_handoff.py`, `tests/unit/test_trace.py`

**Action:**

Write tests for SQLite store, handoff, and trace integration.

**SQLite tests (10 minimum):**
1. Auto-creates .orchestra/ directory and database
2. Append event and retrieve
3. Append multiple events, verify ordering
4. Save checkpoint, retrieve latest
5. State restoration from events
6. State restoration from checkpoint + remaining events
7. Snapshot manager creates checkpoint at interval
8. WAL mode enabled (concurrent read/write)
9. In-memory SQLite works (`:memory:`)
10. list_runs returns run metadata

**Handoff tests (10 minimum):**
1. add_handoff creates HandoffEdge
2. Unconditional handoff transfers execution
3. Conditional handoff routes based on state
4. Context distillation reduces message count
5. Full passthrough preserves all messages
6. HandoffInitiated event emitted
7. HandoffCompleted event emitted
8. Handoff preserves state across transfer
9. Multiple handoffs in sequence
10. Handoff with context distillation reduces tokens vs passthrough

**Trace tests (5 minimum):**
1. RichTraceRenderer handles ExecutionStarted
2. RichTraceRenderer handles NodeStarted/Completed
3. RichTraceRenderer handles errors (NodeFailed)
4. RichTraceRenderer handles ToolCalled
5. Verbose mode shows additional details

**Verify:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -m pytest tests/unit/test_sqlite_store.py tests/unit/test_handoff.py tests/unit/test_trace.py -v --tb=short
```

**Done:** All 25+ tests pass.

---

## Plan 05: PostgreSQL Backend

**Roadmap task:** DIFF-03 (PostgreSQL Storage Backend)
**Wave:** 2
**Dependencies:** Plan 01 (EventStore protocol)
**Estimated effort:** 4 days
**Autonomous:** Yes

### Objective

Implement PostgreSQL-backed EventStore using asyncpg. Same protocol as SQLite but with PostgreSQL features: advisory locks, LISTEN/NOTIFY, JSONB, connection pooling.

### Task 5.1: PostgreSQL EventStore

**Files:** `src/orchestra/storage/postgres.py`

**Action:**

```python
class PostgresEventStore:
    """PostgreSQL-backed event store for production deployments.

    Features beyond SQLite:
    - Advisory locks for workflow-level concurrency
    - LISTEN/NOTIFY for real-time event streaming
    - JSONB for efficient event payload queries
    - Connection pooling via asyncpg.create_pool

    Usage:
        store = PostgresEventStore("postgresql://user:pass@localhost/orchestra")
        await store.initialize()
    """

    def __init__(
        self,
        dsn: str | None = None,  # Falls back to DATABASE_URL env var
        min_pool_size: int = 4,
        max_pool_size: int = 20,
    ) -> None: ...

    async def initialize(self) -> None:
        """Create connection pool and tables.""" ...

    async def close(self) -> None:
        """Close connection pool.""" ...

    # All EventStore protocol methods...

    async def subscribe_events(
        self, run_id: str, callback: Callable[[WorkflowEvent], Awaitable[None]]
    ) -> None:
        """Subscribe to real-time events via LISTEN/NOTIFY.
        Requires a dedicated connection (listener must remain idle).
        """
        ...
```

**SQL Schema (using JSONB):**

```sql
CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id UUID PRIMARY KEY,
    workflow_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    entry_point TEXT,
    metadata JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS workflow_events (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES workflow_runs(run_id),
    event_id UUID NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    timestamp_iso TIMESTAMPTZ NOT NULL,
    data JSONB NOT NULL,
    UNIQUE(run_id, sequence)
);

CREATE INDEX idx_events_run_seq ON workflow_events(run_id, sequence);
CREATE INDEX idx_events_type ON workflow_events(event_type);

CREATE TABLE IF NOT EXISTS workflow_checkpoints (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES workflow_runs(run_id),
    checkpoint_id UUID NOT NULL UNIQUE,
    node_id TEXT NOT NULL,
    sequence_at INTEGER NOT NULL,
    state_snapshot JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Advisory lock function for workflow-level concurrency
-- pg_advisory_xact_lock(hashtext(run_id)) within transactions
```

**Advisory locks:**

```python
async def _with_workflow_lock(self, run_id: str) -> AsyncContextManager:
    """Acquire advisory lock for a workflow run.
    Prevents concurrent writes to the same workflow.
    """
    lock_id = hash(run_id) & 0x7FFFFFFF  # Positive int for pg_advisory_xact_lock
    ...
```

**LISTEN/NOTIFY:**

```python
# On event append:
await conn.execute("NOTIFY workflow_events, $1", json.dumps({"run_id": run_id, "event_type": event_type}))

# Listener:
async def _listen_events(self, run_id: str):
    conn = await self._pool.acquire()
    await conn.add_listener("workflow_events", self._on_notification)
```

Add `asyncpg` to pyproject.toml `postgres` optional dependency group.

**Verify:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -c "
from orchestra.storage.postgres import PostgresEventStore
from orchestra.storage.store import EventStore
print('import OK')
"
```

**Done:** PostgresEventStore implements EventStore protocol. Advisory locks, LISTEN/NOTIFY, connection pooling all implemented.

---

### Task 5.2: PostgreSQL Integration Tests

**Files:** `tests/integration/test_postgres_store.py`

**Action:**

Write integration tests that run against a real PostgreSQL instance. Tests are skipped if PostgreSQL is not available (conditional on `POSTGRES_DSN` env var or local availability).

```python
import pytest

pytestmark = pytest.mark.integration

POSTGRES_DSN = os.environ.get("POSTGRES_DSN", "postgresql://localhost:5432/orchestra_test")

@pytest.fixture
async def pg_store():
    """Create a PostgresEventStore for testing, clean up after."""
    try:
        store = PostgresEventStore(POSTGRES_DSN)
        await store.initialize()
        yield store
        # Clean up test data
        await store._pool.execute("DELETE FROM workflow_events")
        await store._pool.execute("DELETE FROM workflow_checkpoints")
        await store._pool.execute("DELETE FROM workflow_runs")
        await store.close()
    except Exception:
        pytest.skip("PostgreSQL not available")
```

**Tests (8 minimum):**
1. Append and retrieve events
2. Event ordering (sequence numbers)
3. Checkpoint save and restore
4. State projection from events
5. Advisory lock prevents concurrent writes
6. LISTEN/NOTIFY delivers events
7. Connection pool handles concurrent workflows
8. Same test suite as SQLite passes (protocol conformance)

**Verify:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -m pytest tests/integration/test_postgres_store.py -v --tb=short -m integration 2>/dev/null || echo "PostgreSQL tests skipped (no database available)"
```

**Done:** All 8 PostgreSQL integration tests pass when database available. Tests skip gracefully otherwise.

---

## Plan 06: HITL Interrupt/Resume + Tool ACLs

**Roadmap tasks:** DIFF-04 (HITL), DIFF-09 (Tool ACLs)
**Wave:** 3
**Dependencies:** Plan 04 (SQLite store must exist for checkpoint persistence)
**Estimated effort:** 5 days
**Autonomous:** No (HITL requires manual verification)

### Rationale for Grouping

HITL and Tool ACLs are grouped because:
1. Both modify the execution pipeline in `compiled.py`
2. Tool ACLs use the HITL interrupt mechanism for approval gates on sensitive tools
3. Combined they represent the "safety" layer of Phase 2

### Task 6.1: HITL Core Implementation

**Files:** `src/orchestra/core/hitl.py`, `src/orchestra/core/resume.py`

**Action:**

Implement interrupt/resume mechanism.

**InterruptSignal (in hitl.py):**

```python
class InterruptSignal(Exception):
    """Raised to pause workflow execution at a HITL point.

    Not a real error -- caught by CompiledGraph.run() to return
    control to the caller with checkpoint information.
    """
    def __init__(
        self,
        node_id: str,
        interrupt_type: str,  # "before" or "after"
        state: dict[str, Any],
        run_id: str,
        checkpoint_id: str,
    ) -> None: ...

class InterruptResult:
    """Returned when a workflow is interrupted.

    Contains everything needed to inspect state and resume.
    """
    run_id: str
    checkpoint_id: str
    node_id: str
    interrupt_type: str
    state: dict[str, Any]

    def display(self) -> None:
        """Rich-formatted panel showing paused state."""
        ...
```

**Interrupt injection in CompiledGraph (modify compiled.py):**

Modify `add_node()` in `WorkflowGraph` to accept `interrupt_before` and `interrupt_after` parameters:

```python
def add_node(
    self,
    node_id: str,
    node: GraphNode | NodeFunction | Any,
    *,
    output_key: str | None = None,
    interrupt_before: bool = False,
    interrupt_after: bool = False,
) -> WorkflowGraph:
```

Store interrupt flags on a new `InterruptableNode` wrapper or in node metadata.

In `CompiledGraph.run()`, before executing each node:
1. Check if node has `interrupt_before=True`
2. If yes: save checkpoint to EventStore, emit `InterruptRequested` event, raise `InterruptSignal`

After executing each node:
1. Check if node has `interrupt_after=True`
2. If yes: save checkpoint to EventStore, emit `InterruptRequested` event, raise `InterruptSignal`

The `run()` method catches `InterruptSignal` and returns `InterruptResult` instead of the final state.

**Resume logic (in resume.py):**

```python
async def resume(
    run_id: str,
    *,
    state_updates: dict[str, Any] | None = None,
    event_store: EventStore | None = None,
) -> dict[str, Any]:
    """Resume a paused workflow from its last checkpoint.

    Args:
        run_id: The run ID to resume.
        state_updates: Optional state modifications before resuming.
        event_store: Event store to load checkpoint from.

    Returns:
        Final state after workflow completion (or next InterruptResult).
    """
    # 1. Load latest checkpoint from event store
    # 2. If state_updates provided, apply them and emit InterruptResumed event
    # 3. Reconstruct CompiledGraph execution position (which node to run next)
    # 4. Continue execution from that point
    ...
```

**Key design decision (from CONTEXT.md):** Resume API is programmatic first. CLI is one consumer. This enables Phase 3's FastAPI to expose resume endpoints.

**Verify:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -m pytest tests/unit/test_hitl.py -v --tb=short
```

**Done:** interrupt_before pauses before node. interrupt_after pauses after node. State persisted. Resume continues from checkpoint. State modification between interrupt/resume works.

---

### Task 6.2: Tool ACLs

**Files:** `src/orchestra/tools/acl.py`, modify `src/orchestra/tools/registry.py`

**Action:**

Implement access control for tools.

```python
# src/orchestra/tools/acl.py

class ToolACL:
    """Access control for tools.

    Dev mode (ORCHESTRA_ENV=dev): all agents access all tools (zero friction).
    Prod mode (ORCHESTRA_ENV=prod): explicit grants required.
    """

    def __init__(self) -> None:
        self._grants: dict[str, set[str]] = {}  # agent_name -> {tool_names}
        self._denials: dict[str, set[str]] = {}  # agent_name -> {denied_tool_names}

    def grant(self, agent_name: str, tool_names: str | list[str]) -> None:
        """Grant an agent access to tool(s).""" ...

    def deny(self, agent_name: str, tool_names: str | list[str]) -> None:
        """Explicitly deny an agent access to tool(s).""" ...

    def check(self, agent_name: str, tool_name: str) -> bool:
        """Check if agent can use tool. In dev mode, always True.""" ...

    def get_allowed_tools(self, agent_name: str, available_tools: list[str]) -> list[str]:
        """Filter tools to only those the agent can access.""" ...
```

**Modify ToolRegistry (registry.py):**

```python
class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Any] = {}
        self._acl: ToolACL = ToolACL()  # Add ACL

    @property
    def acl(self) -> ToolACL:
        return self._acl

    def get_tools_for(self, agent_name: str) -> list[Any]:
        """Get tools filtered by ACL for a specific agent."""
        allowed = self._acl.get_allowed_tools(agent_name, list(self._tools.keys()))
        return [self._tools[name] for name in allowed]

    def get_schemas_for(self, agent_name: str) -> list[dict[str, Any]]:
        """Get tool schemas filtered by ACL."""
        tools = self.get_tools_for(agent_name)
        return [self._tool_to_schema(t) for t in tools]
```

**Integration with agent execution:**

In `BaseAgent.run()`, when building tool schemas, filter through ACL:
```python
# Before: tool_schemas = [self._tool_to_schema(t) for t in self.tools]
# After:
if context.tool_registry and os.environ.get("ORCHESTRA_ENV") == "prod":
    allowed_tools = context.tool_registry.get_tools_for(self.name)
    tool_schemas = [self._tool_to_schema(t) for t in allowed_tools]
else:
    tool_schemas = [self._tool_to_schema(t) for t in self.tools]
```

When an agent tries to execute a tool it's not allowed to use, raise `ToolPermissionError` (already exists in errors.py).

**Verify:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -m pytest tests/unit/test_acl.py -v --tb=short
```

**Done:** Dev mode allows all tools. Prod mode requires explicit grants. PermissionDenied raised on unauthorized access.

---

### Task 6.3: CLI Integration + Tests

**Files:** `src/orchestra/cli/main.py` (modify), `tests/unit/test_hitl.py`, `tests/unit/test_acl.py`

**Action:**

Add CLI commands for HITL:

```python
@app.command()
def resume(
    run_id: str = typer.Argument(..., help="Run ID to resume"),
    modify: list[str] = typer.Option([], help="State modifications as key=value"),
):
    """Resume an interrupted workflow."""
    ...
```

The CLI `resume` command:
1. Loads checkpoint from SQLite store
2. Displays Rich-formatted panel with current state
3. Applies any `--modify key=value` arguments
4. Calls `resume()` function
5. Displays result or next interrupt

**HITL Tests (10 minimum):**
1. interrupt_before pauses before node execution
2. interrupt_after pauses after node execution
3. InterruptSignal contains correct state
4. Interrupted state persisted to event store
5. resume() loads checkpoint and continues
6. State modification between interrupt and resume
7. Multiple interrupt points in single workflow
8. Process restart resume (load from SQLite)
9. InterruptRequested event emitted
10. InterruptResumed event emitted with modifications

**ACL Tests (8 minimum):**
1. Dev mode: all agents access all tools
2. Prod mode: granted agent can use tool
3. Prod mode: non-granted agent gets PermissionDenied
4. Grant multiple tools at once
5. Deny specific tools
6. get_tools_for returns filtered list
7. get_schemas_for returns filtered schemas
8. ACL with MCP tools (MCPToolAdapter works with ACLs)

**Verify:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -m pytest tests/unit/test_hitl.py tests/unit/test_acl.py -v --tb=short
```

**Done:** All 18+ tests pass. CLI resume command works.

---

### Task 6.4: Manual Verification Checkpoint

**Type:** checkpoint:human-verify

**What was built:** HITL interrupt/resume system with state inspection and modification.

**How to verify:**

1. Run the test workflow with an interrupt point:
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework"
python -c "
import asyncio
from orchestra.core.graph import WorkflowGraph
from orchestra.testing import ScriptedLLM
from orchestra.core.agent import BaseAgent
from orchestra.core.runner import run

agent = BaseAgent(name='writer', system_prompt='Write a draft.')
graph = WorkflowGraph()
graph.add_node('writer', agent, interrupt_after=True)
graph.set_entry_point('writer')

provider = ScriptedLLM(responses=['Draft content here.'])
result = asyncio.run(run(graph, input='Write about AI', provider=provider))
print('Result:', result)
"
```

2. Verify the workflow pauses and returns an InterruptResult (not final state)
3. Verify the Rich panel displays the paused state clearly
4. Verify `orchestra resume <run_id>` continues execution

**Resume signal:** Type "approved" or describe issues.

---

## Plan 07: Time-Travel Debugging

**Roadmap task:** DIFF-05 (Time-Travel Debugging)
**Wave:** 4
**Dependencies:** Plan 06 (checkpoints must exist for time-travel)
**Estimated effort:** 4 days
**Autonomous:** No (needs manual verification of interactive debugging)

### Objective

Implement time-travel debugging: list checkpoints, inspect state at any point, diff between checkpoints, fork execution from historical state. Replay must be side-effect-safe.

### Task 7.1: Time-Travel Core

**Files:** `src/orchestra/debugging/timetravel.py`, `src/orchestra/debugging/replay.py`, `src/orchestra/debugging/__init__.py`

**Action:**

**Time-travel operations (timetravel.py):**

```python
async def list_checkpoints(
    run_id: str,
    event_store: EventStore | None = None,
) -> list[dict[str, Any]]:
    """List all checkpoints for a run with timestamps and node IDs.

    Returns:
        [{"checkpoint_id": "...", "node_id": "...", "timestamp": "...", "sequence": N}, ...]
    """
    ...

async def get_state_at(
    run_id: str,
    checkpoint_id: str,
    event_store: EventStore | None = None,
) -> dict[str, Any]:
    """Get full state at a specific checkpoint."""
    ...

def diff_states(
    state_a: dict[str, Any],
    state_b: dict[str, Any],
) -> dict[str, Any]:
    """Diff two states. Returns {added: {}, removed: {}, changed: {field: {old, new}}}."""
    ...

async def fork_from(
    run_id: str,
    checkpoint_id: str,
    *,
    state_overrides: dict[str, Any] | None = None,
    event_store: EventStore | None = None,
) -> str:
    """Fork a new run from a historical checkpoint.

    Creates a new run_id with the historical state.
    Does NOT affect the original run's event log.

    Returns:
        New run_id for the forked execution.
    """
    ...
```

**Replay-safe tool gateway (replay.py):**

```python
class ReplayToolGateway:
    """Wraps tool execution to suppress external side effects during replay/fork.

    During replay mode (context.replay_mode=True):
    - External tools (HTTP calls, file writes, etc.) are NOT re-executed
    - Cached results from the event log are returned instead
    - Only tools marked as "pure" (no side effects) are executed

    This prevents duplicate API calls, double payments, etc. during time-travel.
    """

    def __init__(self, event_store: EventStore, run_id: str) -> None:
        self._event_store = event_store
        self._run_id = run_id
        self._cached_results: dict[str, str] = {}  # tool_call_id -> result

    async def load_cache(self) -> None:
        """Load tool results from event log for replay."""
        events = await self._event_store.get_events(
            self._run_id, event_types=[EventType.TOOL_CALLED]
        )
        for event in events:
            if isinstance(event, ToolCalled):
                cache_key = f"{event.tool_name}:{json.dumps(event.arguments, sort_keys=True)}"
                self._cached_results[cache_key] = event.result

    async def execute_or_replay(
        self,
        tool: Any,
        arguments: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Execute tool normally or return cached result during replay."""
        if context.replay_mode:
            cache_key = f"{tool.name}:{json.dumps(arguments, sort_keys=True)}"
            if cache_key in self._cached_results:
                return ToolResult(
                    tool_call_id="",
                    name=tool.name,
                    content=self._cached_results[cache_key],
                )
            # Tool not in cache -- skip (new tool call during fork)
            return ToolResult(
                tool_call_id="",
                name=tool.name,
                content="",
                error="Tool result not available during replay (new invocation)",
            )
        else:
            return await tool.execute(arguments, context=context)
```

**State diff rendering:**

```python
def render_state_diff(diff: dict[str, Any]) -> None:
    """Render state diff using Rich.

    Shows:
    - Added fields (green +)
    - Removed fields (red -)
    - Changed fields (yellow ~ with old/new values)
    """
    ...
```

**Verify:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -m pytest tests/unit/test_timetravel.py -v --tb=short
```

**Done:** All time-travel operations work. Replay-safe gateway suppresses side effects.

---

### Task 7.2: CLI Integration + Tests

**Files:** `src/orchestra/cli/main.py` (modify), `tests/unit/test_timetravel.py`

**Action:**

Add CLI commands:

```python
@app.command()
def debug(run_id: str = typer.Argument(...)):
    """Interactive time-travel debugger for a workflow run."""
    # Lists checkpoints, allows user to:
    # - inspect state at any checkpoint
    # - diff between two checkpoints
    # - fork from a checkpoint
    ...

@app.command()
def checkpoints(run_id: str = typer.Argument(...)):
    """List all checkpoints for a workflow run."""
    ...

@app.command()
def inspect(run_id: str, checkpoint_id: str):
    """Inspect full state at a checkpoint."""
    ...

@app.command()
def diff(run_id: str, checkpoint_a: str, checkpoint_b: str):
    """Show state changes between two checkpoints."""
    ...

@app.command()
def fork(run_id: str, checkpoint_id: str):
    """Fork a new run from a historical checkpoint."""
    ...
```

**Tests (12 minimum):**
1. list_checkpoints returns all checkpoints
2. list_checkpoints returns timestamps and node IDs
3. get_state_at returns correct state
4. diff_states shows added fields
5. diff_states shows removed fields
6. diff_states shows changed fields
7. fork_from creates new run_id
8. fork_from preserves historical state
9. Forked run is independent (doesn't affect original)
10. ReplayToolGateway returns cached results in replay mode
11. ReplayToolGateway executes normally in live mode
12. Replay mode suppresses external tool calls

**Verify:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -m pytest tests/unit/test_timetravel.py -v --tb=short
```

**Done:** All 12 tests pass. CLI commands work.

---

### Task 7.3: Manual Verification Checkpoint

**Type:** checkpoint:human-verify

**What was built:** Time-travel debugging with checkpoint listing, state inspection, diffing, and forking.

**How to verify:**

1. Run a multi-step workflow to generate checkpoints
2. Run `orchestra checkpoints <run_id>` -- verify checkpoint list appears
3. Run `orchestra inspect <run_id> <checkpoint_id>` -- verify state displayed
4. Run `orchestra diff <run_id> <cp1> <cp2>` -- verify diff shows changes
5. Run `orchestra fork <run_id> <checkpoint_id>` -- verify new run created
6. Verify original run's event log is unchanged after fork

**Resume signal:** Type "approved" or describe issues.

---

## Plan 08: Advanced Examples

**Roadmap task:** DIFF-11 (Advanced Examples)
**Wave:** 5
**Dependencies:** Plans 04, 06, 07 (HITL, time-travel, handoff all implemented)
**Estimated effort:** 3 days
**Autonomous:** No (examples need manual verification)

### Objective

Create three end-to-end example workflows demonstrating Phase 2 features. Each must work with ScriptedLLM in CI.

### Task 8.1: Example Workflows

**Files:** `examples/handoff.py`, `examples/hitl_review.py`, `examples/time_travel.py`

**Action:**

**Example 1: Customer Support with Handoff (`examples/handoff.py`):**

```python
"""Customer support workflow with agent handoff.

Demonstrates:
- Triage agent classifies incoming requests
- Handoff to specialist agent (billing, technical, general)
- Context distillation preserves relevant history
- Rich trace shows handoff flow

Usage:
    python examples/handoff.py
    # Or with ScriptedLLM for testing:
    python examples/handoff.py --test
"""

# Agents: triage_agent, billing_agent, technical_agent, general_agent
# Graph: triage -> (conditional handoff) -> specialist -> END
# Features demonstrated: add_handoff(), conditional routing, context distillation
```

**Example 2: Content Review with HITL (`examples/hitl_review.py`):**

```python
"""Content generation with human approval checkpoint.

Demonstrates:
- Writer agent generates content
- HITL interrupt_after for human review
- State inspection and modification
- Resume after approval or revision request

Usage:
    python examples/hitl_review.py
"""

# Agents: writer_agent, editor_agent
# Graph: writer -> (interrupt_after) -> editor -> END
# Features demonstrated: interrupt_after, state modification, resume()
```

**Example 3: Research with Time-Travel (`examples/time_travel.py`):**

```python
"""Research workflow demonstrating time-travel debugging.

Demonstrates:
- Multi-step research workflow
- Event log inspection
- Checkpoint listing and state inspection
- Forking from historical checkpoint with modified parameters

Usage:
    python examples/time_travel.py
"""

# Agents: planner_agent, researcher_agent, summarizer_agent
# Graph: planner -> researcher -> summarizer -> END
# Features demonstrated: list_checkpoints, get_state_at, diff_states, fork_from
```

Each example:
- Has a detailed module docstring explaining the pattern
- Defines a `main()` function and a `test_main()` function
- `main()` runs with real LLM (for interactive use)
- `test_main()` runs with ScriptedLLM (for CI)
- Includes `if __name__ == "__main__":` block

**Verify:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -m pytest tests/integration/test_advanced_examples.py -v --tb=short
```

**Done:** All three examples run successfully.

---

### Task 8.2: Integration Tests

**Files:** `tests/integration/test_advanced_examples.py`

**Action:**

```python
"""Integration tests for Phase 2 advanced examples.

All tests use ScriptedLLM -- no real LLM calls.
Target: complete in under 15 seconds total.
"""

class TestHandoffExample:
    async def test_triage_to_billing(self): ...
    async def test_triage_to_technical(self): ...
    async def test_context_preserved_across_handoff(self): ...

class TestHITLExample:
    async def test_interrupt_and_resume(self): ...
    async def test_state_modification_on_resume(self): ...
    async def test_multiple_interrupts(self): ...

class TestTimeTravelExample:
    async def test_checkpoint_listing(self): ...
    async def test_state_inspection(self): ...
    async def test_fork_execution(self): ...
```

**Verify:**
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -m pytest tests/integration/test_advanced_examples.py -v --tb=short --timeout=15
```

**Done:** All 9 integration tests pass in under 15 seconds.

---

### Task 8.3: Manual Verification Checkpoint

**Type:** checkpoint:human-verify

**What was built:** Three advanced example workflows demonstrating handoff, HITL, and time-travel.

**How to verify:**

1. Run `python examples/handoff.py --test` -- verify it completes with handoff trace
2. Run `python examples/hitl_review.py --test` -- verify interrupt and resume
3. Run `python examples/time_travel.py --test` -- verify time-travel operations
4. Check that Rich trace output is readable and informative
5. Verify all examples have comprehensive docstrings

**Resume signal:** Type "approved" or describe issues.

---

## Testing Strategy

### Test Pyramid

```
                     /\
                    /  \    3 examples with
                   / E2E\   ScriptedLLM
                  /------\  (tests/integration/)
                 /  Integ  \  PostgreSQL tests
                /  ration   \  (conditional on DB)
               /-----------  \
              /     Unit      \   80+ unit tests
             /   Tests (fast)  \  (tests/unit/)
            /___________________\
```

### Test File Map

| Test File | Plan | Tests | Target |
|-----------|------|-------|--------|
| `tests/unit/test_events.py` | 01 | 15+ | Event types, bus, store, serialization |
| `tests/unit/test_mcp.py` | 02 | 10+ | MCP client with mock server |
| `tests/unit/test_providers.py` | 03 | 16+ | Google + Ollama with mocked HTTP |
| `tests/unit/test_sqlite_store.py` | 04 | 10+ | SQLite storage backend |
| `tests/unit/test_handoff.py` | 04 | 10+ | Handoff edges and distillation |
| `tests/unit/test_trace.py` | 04 | 5+ | Rich trace renderer |
| `tests/integration/test_postgres_store.py` | 05 | 8+ | PostgreSQL (conditional) |
| `tests/unit/test_hitl.py` | 06 | 10+ | Interrupt and resume |
| `tests/unit/test_acl.py` | 06 | 8+ | Tool ACLs |
| `tests/unit/test_timetravel.py` | 07 | 12+ | Time-travel operations |
| `tests/integration/test_advanced_examples.py` | 08 | 9+ | Example workflows |

**Total: 113+ tests**

### Test Commands

```bash
# All unit tests (should pass in under 60 seconds)
python -m pytest tests/unit/ -v --tb=short

# All integration tests (may need PostgreSQL)
python -m pytest tests/integration/ -v --tb=short

# Full suite
python -m pytest tests/ -v --tb=short

# Coverage
python -m pytest tests/ --cov=orchestra --cov-report=term-missing
```

### Test Conventions (from existing codebase)

- `asyncio_mode = "auto"` (no need for `@pytest.mark.asyncio`)
- Class-based grouping: `class TestFeature:`
- Three-part error messages in assertions
- ScriptedLLM for deterministic agent testing
- In-memory SQLite (`:memory:`) for storage tests
- Mocked httpx for provider tests

---

## Verification Matrix

Maps each roadmap success criterion to the plans/tests that verify it.

| # | Success Criterion | Plans | Verification |
|---|-------------------|-------|--------------|
| 1 | Run workflow, kill process, restart, resume from checkpoint with no data loss | 01, 04, 06 | `test_hitl.py::test_process_restart_resume` -- run workflow, stop, reload from SQLite, verify state matches |
| 2 | Interrupt at HITL node, inspect state, modify it, resume | 06 | `test_hitl.py::test_interrupt_modify_resume` -- interrupt, modify state dict, resume, verify modified state used |
| 3 | Time-travel to any checkpoint, inspect state, fork execution | 07 | `test_timetravel.py::test_fork_from_checkpoint` -- list checkpoints, inspect, fork, verify independent execution |
| 4 | Real-time Rich trace showing turns, tools, tokens, timing | 04 | `test_trace.py::test_live_rendering` -- run workflow, verify tree nodes match execution + manual checkpoint |
| 5 | Handoff between agents with context preservation | 04 | `test_handoff.py::test_context_preserved` -- handoff from A to B, verify B receives A's conversation history |

### Automated Verification Script

After all plans execute, run this comprehensive check:

```bash
#!/bin/bash
set -e

echo "=== Phase 2 Verification ==="

echo "1. Running full test suite..."
python -m pytest tests/ -v --tb=short -x

echo "2. Checking imports..."
python -c "
from orchestra.storage.events import WorkflowEvent, ExecutionStarted, NodeCompleted
from orchestra.storage.store import EventBus, EventStore, InMemoryEventStore
from orchestra.storage.sqlite import SQLiteEventStore
from orchestra.storage.serialization import event_to_json, json_to_event
from orchestra.storage.contracts import BoundaryContract
from orchestra.tools.mcp import MCPClient, MCPToolAdapter
from orchestra.tools.acl import ToolACL
from orchestra.providers.google import GoogleProvider
from orchestra.providers.ollama import OllamaProvider
from orchestra.core.hitl import InterruptSignal, InterruptResult
from orchestra.core.resume import resume
from orchestra.core.handoff import HandoffEdge, HandoffPayload
from orchestra.core.context_distill import distill_context
from orchestra.observability.console import RichTraceRenderer
from orchestra.debugging.timetravel import list_checkpoints, get_state_at, diff_states, fork_from
from orchestra.debugging.replay import ReplayToolGateway
print('All Phase 2 imports OK')
"

echo "3. Protocol conformance..."
python -c "
from orchestra.storage.store import EventStore
from orchestra.storage.sqlite import SQLiteEventStore
from orchestra.core.protocols import LLMProvider, Tool
from orchestra.providers.google import GoogleProvider
from orchestra.providers.ollama import OllamaProvider
from orchestra.tools.mcp import MCPToolAdapter
# isinstance checks
assert isinstance(GoogleProvider(api_key='x'), LLMProvider)
assert isinstance(OllamaProvider(), LLMProvider)
print('Protocol conformance OK')
"

echo "4. Running examples..."
python examples/handoff.py --test
python examples/hitl_review.py --test
python examples/time_travel.py --test

echo "=== Phase 2 Verification PASSED ==="
```

---

## Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|------------|--------|------------|
| R1 | Event serialization breaks on schema evolution (new event types added in future) | Medium | High | Use type discriminator field in serialized JSON. Unknown event types deserialize to a generic `WorkflowEvent` with raw data preserved. Add `schema_version` field to event envelope. |
| R2 | Rich Live rendering blocks async event loop | Medium | Medium | Run Rich Live in a separate thread with a queue. Use `Console(force_terminal=True)` to avoid terminal detection issues. Set refresh rate to 4Hz max. |
| R3 | SQLite WAL mode contention under heavy parallel node execution | Low | Medium | SQLite handles WAL well for single-writer workloads. If contention occurs, batch event writes (emit to queue, flush periodically). Monitor with `PRAGMA wal_checkpoint` in tests. |
| R4 | MCP spec changes break client | Medium | Medium | Pin to 2025-11-25 spec. Implement capability negotiation fully so client adapts to server capabilities. Abstract transport layer so new transports can be added without core changes. |
| R5 | HITL resume reconstructs incorrect execution position | Medium | High | Store `next_node_id` in checkpoint metadata (not just state). Test extensively with multi-branch graphs. The checkpoint contains: state + position + event sequence number. |
| R6 | Time-travel replay re-executes external tools | High (if not handled) | Critical | ReplayToolGateway is mandatory during fork/replay. Context.replay_mode flag gates all tool execution. Test with tools that assert they were NOT called during replay. |
| R7 | Context distillation loses critical information during handoff | Low | Medium | Keep last 3 turns intact (variable suffix). Only compress middleware zone. Provide `distill=False` escape hatch for full passthrough. Compare token counts in tests. |
| R8 | asyncpg pool exhaustion under concurrent workflows | Low | Medium | Default pool size 4-20 connections. Document tuning. Add pool health check to `list_runs` response. Test with 50 concurrent workflows. |
| R9 | Boundary contract validation overhead on hot path | Low | Low | Contracts are optional (only validated if registered). JSON Schema validation is fast (~1ms). Profile and cache compiled schemas if needed. |
| R10 | Existing Phase 1 tests break after compiled.py modifications | Medium | High | Run Phase 1 tests after every compiled.py change. Event emission is additive (new code paths, not modified existing ones). Guard all new code with `if event_bus:` checks. |

### Risk Mitigation Priorities

1. **R6 (replay safety):** Most critical. Implement and test ReplayToolGateway before time-travel features. Add assertion tests that tools are NOT executed during replay.
2. **R10 (backwards compatibility):** Run `pytest tests/unit/test_core.py` after every compiled.py modification. No event bus = no behavior change.
3. **R5 (HITL resume):** Store full execution position in checkpoint. Test with branching, looping, and parallel graphs.
4. **R1 (schema evolution):** Add `schema_version: 1` to event envelope. Document migration strategy in code comments.

---

## New Dependencies Summary

| Package | Version | Optional Group | Used By |
|---------|---------|---------------|---------|
| `aiosqlite` | >=0.19 | `storage` | SQLiteEventStore |
| `msgpack` | >=1.0 | `storage` | Event serialization |
| `asyncpg` | >=0.29 | `postgres` | PostgresEventStore |
| `jsonschema` | >=4.20 | (core) | Boundary contracts |

Note: `rich` is already a core dependency (used by typer). No new core dependencies needed for trace rendering.

---

## File Creation Summary

### New Files (28)

```
src/orchestra/storage/__init__.py
src/orchestra/storage/events.py
src/orchestra/storage/store.py
src/orchestra/storage/serialization.py
src/orchestra/storage/contracts.py
src/orchestra/storage/sqlite.py
src/orchestra/storage/postgres.py
src/orchestra/tools/mcp.py
src/orchestra/tools/acl.py
src/orchestra/providers/google.py
src/orchestra/providers/ollama.py
src/orchestra/core/hitl.py
src/orchestra/core/resume.py
src/orchestra/core/handoff.py
src/orchestra/core/context_distill.py
src/orchestra/observability/console.py
src/orchestra/debugging/__init__.py
src/orchestra/debugging/timetravel.py
src/orchestra/debugging/replay.py
examples/handoff.py
examples/hitl_review.py
examples/time_travel.py
tests/unit/test_events.py
tests/unit/test_mcp.py
tests/unit/test_providers.py
tests/unit/test_sqlite_store.py
tests/unit/test_handoff.py
tests/unit/test_trace.py
tests/unit/test_hitl.py
tests/unit/test_acl.py
tests/unit/test_timetravel.py
tests/integration/test_postgres_store.py
tests/integration/test_advanced_examples.py
```

### Modified Files (10)

```
src/orchestra/core/errors.py         (add PersistenceError, MCPError hierarchies)
src/orchestra/core/context.py        (add event_bus, replay_mode, interrupt_signal)
src/orchestra/core/compiled.py       (emit events, handle interrupts, handoffs)
src/orchestra/core/graph.py          (add_node interrupt params, add_handoff)
src/orchestra/core/agent.py          (emit LLMCalled/ToolCalled events, ACL check)
src/orchestra/tools/registry.py      (add ACL, get_tools_for, get_schemas_for)
src/orchestra/tools/__init__.py      (export MCPClient, MCPToolAdapter)
src/orchestra/providers/__init__.py   (lazy imports for Google, Ollama)
src/orchestra/cli/main.py            (resume, debug, checkpoints, inspect, diff, fork commands)
pyproject.toml                        (new optional dependencies)
```

---

## Execution Checklist

- [ ] **Wave 1:** Plans 01, 02, 03 (parallel)
  - [ ] Plan 01: Event system + tests (15+ tests pass)
  - [ ] Plan 02: MCP client + tests (10+ tests pass)
  - [ ] Plan 03: Providers + tests (16+ tests pass)
  - [ ] Phase 1 tests still pass (`pytest tests/unit/test_core.py`)

- [ ] **Wave 2:** Plans 04, 05 (parallel, after Wave 1)
  - [ ] Plan 04: SQLite + Trace + Handoff + integration (25+ tests pass)
  - [ ] Plan 05: PostgreSQL (8+ tests, conditional)
  - [ ] All Wave 1 tests still pass

- [ ] **Wave 3:** Plan 06 (after Wave 2)
  - [ ] Plan 06: HITL + ACLs (18+ tests pass)
  - [ ] Manual verification: interrupt/resume works
  - [ ] All prior tests still pass

- [ ] **Wave 4:** Plan 07 (after Wave 3)
  - [ ] Plan 07: Time-travel (12+ tests pass)
  - [ ] Manual verification: debug commands work
  - [ ] All prior tests still pass

- [ ] **Wave 5:** Plan 08 (after Wave 4)
  - [ ] Plan 08: Examples (9+ integration tests pass)
  - [ ] Manual verification: examples run correctly
  - [ ] Full test suite passes

- [ ] **Final Verification:**
  - [ ] All 113+ tests pass
  - [ ] All 5 success criteria verified
  - [ ] All imports work
  - [ ] Protocol conformance verified
  - [ ] Coverage >= 80%
