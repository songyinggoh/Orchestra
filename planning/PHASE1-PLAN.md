# Phase 1: Core Engine -- Executable Plan

**Phase:** 01-core-engine
**Timeline:** Weeks 1-6
**Goal:** A working graph-based agent orchestration framework that can define agents, build workflows, execute them with typed state, and test them deterministically.

**Outcome:** `pip install orchestra` gives you agent definition (class + decorator), a graph engine (sequential, parallel, conditional), typed state with reducers, OpenAI/Anthropic LLM adapters, a tool system, ScriptedLLM for testing, and a CLI -- all with zero external infrastructure.

---

## Task 1: Project Scaffolding

**Wave:** 1 (no dependencies)
**Estimated effort:** ~20 min Claude execution
**Files created:**

```
orchestra/
  pyproject.toml
  Makefile
  .gitignore
  LICENSE
  README.md
  src/orchestra/__init__.py
  src/orchestra/py.typed
  tests/__init__.py
  tests/conftest.py
  .github/workflows/ci.yml
```

### 1.1 `pyproject.toml`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "orchestra"
version = "0.1.0"
description = "Python-first multi-agent orchestration framework"
readme = "README.md"
license = "MIT"
requires-python = ">=3.11"
authors = [
    { name = "Orchestra Contributors" },
]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Framework :: AsyncIO",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Scientific/Engineering :: Artificial Intelligence",
    "Typing :: Typed",
]

dependencies = [
    "pydantic>=2.5",
    "httpx>=0.26",
    "structlog>=24.0",
    "rich>=13.0",
    "typer>=0.12",
    "anyio>=4.0",
]

[project.optional-dependencies]
openai = ["openai>=1.12"]
anthropic = ["anthropic>=0.20"]
all-providers = ["orchestra[openai,anthropic]"]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=4.1",
    "ruff>=0.3",
    "mypy>=1.8",
    "pre-commit>=3.6",
]
docs = [
    "mkdocs>=1.5",
    "mkdocs-material>=9.5",
    "mkdocstrings[python]>=0.24",
]

[project.scripts]
orchestra = "orchestra.cli:app"

[project.urls]
Homepage = "https://github.com/orchestra-framework/orchestra"
Documentation = "https://orchestra.dev"
Repository = "https://github.com/orchestra-framework/orchestra"

[tool.hatch.build.targets.wheel]
packages = ["src/orchestra"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
    "slow: marks tests as slow (deselect with '-m \"not slow\"')",
    "integration: marks integration tests",
]

[tool.ruff]
target-version = "py311"
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = [
    "E", "W",    # pycodestyle
    "F",         # pyflakes
    "I",         # isort
    "UP",        # pyupgrade
    "B",         # bugbear
    "SIM",       # simplify
    "TCH",       # type-checking imports
    "RUF",       # ruff-specific
]

[tool.mypy]
python_version = "3.11"
strict = true
warn_return_any = true
warn_unused_configs = true
plugins = ["pydantic.mypy"]

[tool.coverage.run]
source = ["orchestra"]
omit = ["tests/*"]

[tool.coverage.report]
fail_under = 80
show_missing = true
```

### 1.2 `Makefile`

```makefile
.PHONY: install lint type-check test test-cov fmt clean

install:
	pip install -e ".[dev,openai,anthropic]"

lint:
	ruff check src/ tests/

fmt:
	ruff format src/ tests/
	ruff check --fix src/ tests/

type-check:
	mypy src/orchestra/

test:
	pytest tests/ -x -q

test-cov:
	pytest tests/ --cov=orchestra --cov-report=term-missing

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .mypy_cache -exec rm -rf {} +
	rm -rf dist/ build/ *.egg-info
```

### 1.3 `.github/workflows/ci.yml`

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: ruff check src/ tests/
      - run: ruff format --check src/ tests/

  type-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev,openai,anthropic]"
      - run: mypy src/orchestra/

  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -e ".[dev,openai,anthropic]"
      - run: pytest tests/ --cov=orchestra --cov-report=xml -x
      - uses: codecov/codecov-action@v4
        if: matrix.python-version == '3.12'
```

### 1.4 `src/orchestra/__init__.py`

```python
"""Orchestra: Python-first multi-agent orchestration framework."""

__version__ = "0.1.0"

# Core public API -- populated as modules are built
```

### 1.5 `.gitignore`

Standard Python .gitignore: `__pycache__`, `.venv`, `dist/`, `*.egg-info`, `.env`, `.mypy_cache`, `.pytest_cache`, `.coverage`, `htmlcov/`, `*.pyc`.

### 1.6 `LICENSE`

MIT license.

### 1.7 `README.md`

Minimal README with: project name, one-line description, install instructions (`pip install orchestra`), a 10-line quickstart code example, and links to docs.

### 1.8 `tests/conftest.py`

```python
"""Shared test fixtures for Orchestra test suite."""

import pytest

# Re-export fixtures from fixture modules as they are created
```

### 1.9 `src/orchestra/py.typed`

Empty marker file for PEP 561 typed package support.

**Test cases:**
- `pip install -e ".[dev]"` succeeds
- `ruff check src/ tests/` passes
- `mypy src/orchestra/` passes
- `pytest tests/` passes (no tests yet, exits 0 with no-tests-ok or a trivial smoke test)

**Definition of done:**
- Project installs cleanly with `pip install -e ".[dev]"`
- All three CI jobs (lint, type-check, test) would pass
- Package structure follows src-layout convention
- `orchestra` CLI entry point is registered

---

## Task 2: Core Protocols & Types

**Wave:** 1 (no dependencies, parallel with Task 1)
**Estimated effort:** ~30 min Claude execution
**Files created:**

```
src/orchestra/core/__init__.py
src/orchestra/core/types.py
src/orchestra/core/protocols.py
```

### 2.1 `src/orchestra/core/types.py`

All foundational types as Pydantic models and dataclasses:

```python
"""Core types for Orchestra framework."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    """Roles for messages in agent conversations."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Message(BaseModel):
    """A single message in an agent conversation."""
    role: MessageRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}


class ToolCall(BaseModel):
    """A tool invocation requested by an LLM."""
    id: str = Field(default_factory=lambda: f"call_{uuid.uuid4().hex[:12]}")
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Result of executing a tool."""
    tool_call_id: str
    name: str
    content: str
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    """Result returned by an agent after execution."""
    agent_name: str
    messages: list[Message] = Field(default_factory=list)
    output: Any = None
    tool_calls_made: list[ToolCall] = Field(default_factory=list)
    handoff_to: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    """Response from an LLM provider."""
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: Literal["stop", "tool_calls", "length", "error"] = "stop"
    usage: TokenUsage | None = None
    model: str = ""
    raw_response: Any = None


class TokenUsage(BaseModel):
    """Token usage from an LLM call."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class NodeStatus(str, Enum):
    """Status of a graph node during execution."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowStatus(str, Enum):
    """Status of an entire workflow run."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Sentinel for graph termination
END = "__end__"
START = "__start__"
```

### 2.2 `src/orchestra/core/protocols.py`

Python Protocol classes defining the contracts:

```python
"""Core protocols (interfaces) for Orchestra framework.

All major components are defined as Protocols (structural subtyping).
Implementations do not need to inherit from these -- they just need
to implement the methods.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Protocol, runtime_checkable

from orchestra.core.types import (
    AgentResult,
    LLMResponse,
    Message,
    ToolCall,
    ToolResult,
)


@runtime_checkable
class Agent(Protocol):
    """Protocol for all agent implementations."""

    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def system_prompt(self) -> str: ...

    @property
    def tools(self) -> list[Tool]: ...

    async def run(
        self,
        messages: list[Message],
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentResult: ...


@runtime_checkable
class Tool(Protocol):
    """Protocol for tool implementations."""

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
        context: dict[str, Any] | None = None,
    ) -> ToolResult: ...


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM provider adapters."""

    async def chat(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
    ) -> LLMResponse: ...

    async def chat_stream(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
    ) -> AsyncIterator[LLMResponse]: ...


@runtime_checkable
class StateReducer(Protocol):
    """Protocol for state field reducers.

    Reducers define how state fields merge when multiple
    nodes produce updates to the same field (e.g., during
    parallel fan-in).
    """

    def __call__(self, existing: Any, new: Any) -> Any: ...


@runtime_checkable
class Executor(Protocol):
    """Protocol for workflow executors.

    The executor controls HOW a compiled graph runs.
    Default: AsyncioExecutor (single process, asyncio).
    Future: RayExecutor (distributed).
    """

    async def execute_node(
        self,
        node_id: str,
        node_fn: Any,
        state: dict[str, Any],
        *,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    async def execute_parallel(
        self,
        nodes: list[tuple[str, Any]],
        state: dict[str, Any],
        *,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...
```

### 2.3 `src/orchestra/core/__init__.py`

```python
"""Orchestra core: types, protocols, and engine."""

from orchestra.core.types import (
    END,
    START,
    AgentResult,
    LLMResponse,
    Message,
    MessageRole,
    NodeStatus,
    ToolCall,
    ToolResult,
    TokenUsage,
    WorkflowStatus,
)
from orchestra.core.protocols import Agent, Executor, LLMProvider, StateReducer, Tool

__all__ = [
    "END",
    "START",
    "Agent",
    "AgentResult",
    "Executor",
    "LLMProvider",
    "LLMResponse",
    "Message",
    "MessageRole",
    "NodeStatus",
    "StateReducer",
    "Tool",
    "ToolCall",
    "ToolResult",
    "TokenUsage",
    "WorkflowStatus",
]
```

**Dependencies on other tasks:** None.

**Test cases:**
- All types can be instantiated with valid data
- Pydantic validation rejects invalid data (e.g., invalid role)
- Message is immutable (frozen=True)
- Protocol runtime checks work: `isinstance(my_agent, Agent)` returns True for valid implementations
- ToolCall generates unique IDs
- Serialization round-trip: `Message.model_dump()` -> `Message.model_validate()` preserves data

**Definition of done:**
- All types importable from `orchestra.core`
- `mypy` passes with strict mode on both files
- At least 15 unit tests covering construction, validation, serialization, and protocol checks

---

## Task 3: State Management

**Wave:** 2 (depends on Task 2: uses types and protocols)
**Estimated effort:** ~40 min Claude execution
**Files created:**

```
src/orchestra/core/state.py
tests/unit/__init__.py
tests/unit/test_state.py
```

### 3.1 `src/orchestra/core/state.py`

```python
"""Workflow state with Pydantic + Annotated reducers.

State fields can be annotated with reducer functions that control
how values merge during parallel fan-in. Without a reducer,
last-write-wins semantics apply.

Usage:
    from typing import Annotated

    class MyState(WorkflowState):
        messages: Annotated[list[Message], append_reducer] = []
        current_agent: str = ""
        step_count: Annotated[int, add_reducer] = 0
"""

from __future__ import annotations

import copy
from typing import Any, Annotated, get_type_hints, get_origin, get_args

from pydantic import BaseModel


# ---- Built-in Reducers ----

def append_reducer(existing: list, new: list) -> list:
    """Append new items to existing list."""
    return existing + new


def add_reducer(existing: int | float, new: int | float) -> int | float:
    """Add new value to existing."""
    return existing + new


def merge_dict_reducer(existing: dict, new: dict) -> dict:
    """Merge new dict into existing (shallow)."""
    return {**existing, **new}


def last_write_wins(existing: Any, new: Any) -> Any:
    """Replace existing with new value."""
    return new


def unique_append_reducer(existing: list, new: list) -> list:
    """Append only items not already in list."""
    seen = set(id(x) for x in existing)
    return existing + [x for x in new if id(x) not in seen]


# ---- State Engine ----

class WorkflowState(BaseModel):
    """Base class for typed workflow state with reducer support.

    Subclass this and annotate fields with reducers:

        class MyState(WorkflowState):
            messages: Annotated[list[Message], append_reducer] = []
            count: Annotated[int, add_reducer] = 0
            result: str = ""  # last-write-wins (no reducer)
    """

    model_config = {"arbitrary_types_allowed": True}


def extract_reducers(state_class: type[WorkflowState]) -> dict[str, Any]:
    """Extract reducer functions from Annotated type hints.

    For a field like `messages: Annotated[list[Message], append_reducer]`,
    this returns {"messages": append_reducer}.
    """
    reducers: dict[str, Any] = {}
    hints = get_type_hints(state_class, include_extras=True)

    for field_name, hint in hints.items():
        if get_origin(hint) is Annotated:
            args = get_args(hint)
            # args[0] is the actual type, args[1:] are metadata
            for metadata in args[1:]:
                if callable(metadata):
                    reducers[field_name] = metadata
                    break

    return reducers


def apply_state_update(
    state: WorkflowState,
    update: dict[str, Any],
    reducers: dict[str, Any],
) -> WorkflowState:
    """Apply a partial update to state using reducers.

    Fields with reducers: reducer(current_value, new_value)
    Fields without reducers: last-write-wins
    Fields not in update: preserved unchanged

    Returns a NEW state instance (immutable update).
    """
    current_data = state.model_dump()
    new_data = dict(current_data)

    for key, value in update.items():
        if key not in current_data:
            raise KeyError(f"Unknown state field: {key}")

        if key in reducers:
            new_data[key] = reducers[key](current_data[key], value)
        else:
            new_data[key] = value

    return state.__class__.model_validate(new_data)


def merge_parallel_updates(
    state: WorkflowState,
    updates: list[dict[str, Any]],
    reducers: dict[str, Any],
) -> WorkflowState:
    """Merge multiple parallel updates into state.

    Applies updates sequentially using reducers. For reducer fields,
    all updates accumulate. For non-reducer fields, last update wins.

    This is the key function for parallel fan-in: when multiple
    nodes run concurrently and each returns a partial state update,
    this function merges them all consistently.
    """
    result = state
    for update in updates:
        result = apply_state_update(result, update, reducers)
    return result
```

**Dependencies on other tasks:** Task 2 (uses `WorkflowState` base from Pydantic, references `Message` type).

**Test cases (tests/unit/test_state.py):**

```python
# Test: append_reducer appends lists
# Test: add_reducer sums integers
# Test: merge_dict_reducer merges dicts
# Test: last_write_wins replaces value
# Test: extract_reducers finds annotated reducers
# Test: extract_reducers ignores non-reducer annotations
# Test: apply_state_update with reducer field
# Test: apply_state_update with non-reducer field (last-write-wins)
# Test: apply_state_update preserves unmentioned fields
# Test: apply_state_update raises KeyError for unknown field
# Test: merge_parallel_updates merges multiple updates
# Test: merge_parallel_updates with mixed reducer/non-reducer fields
# Test: state is immutable (new instance returned)
# Test: round-trip serialization of state with complex types
# Test: empty update returns equivalent state
```

**Definition of done:**
- `WorkflowState` subclasses support `Annotated[type, reducer]` fields
- `extract_reducers` correctly parses type hints
- `apply_state_update` applies partial updates with reducer semantics
- `merge_parallel_updates` handles fan-in from parallel nodes
- All 15+ unit tests pass
- `mypy` strict passes

---

## Task 4: Graph Engine

**Wave:** 2 (depends on Task 2 for types; parallel with Task 3)
**Estimated effort:** ~60 min Claude execution
**Files created:**

```
src/orchestra/core/nodes.py
src/orchestra/core/edges.py
src/orchestra/core/graph.py
src/orchestra/core/compiled.py
tests/unit/test_graph.py
tests/unit/test_compiled.py
```

### 4.1 `src/orchestra/core/nodes.py`

```python
"""Graph node types.

Nodes are the processing units in a workflow graph. Each node
wraps a callable (agent, function, or subgraph) and executes
it with the current workflow state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Union

from orchestra.core.types import AgentResult


# Type alias for node functions
# A node function takes state dict and returns a partial state update dict
NodeFunction = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class AgentNode:
    """A node that runs an Agent.

    The agent receives the current state (or a projection of it)
    and returns an AgentResult which is converted to a state update.
    """
    agent: Any  # Agent protocol instance
    input_mapper: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    output_mapper: Callable[[AgentResult], dict[str, Any]] | None = None

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        from orchestra.core.types import Message

        # Map state to agent input
        if self.input_mapper:
            agent_input = self.input_mapper(state)
        else:
            agent_input = state

        messages = agent_input.get("messages", [])
        context = {k: v for k, v in agent_input.items() if k != "messages"}

        result: AgentResult = await self.agent.run(messages, context=context)

        # Map agent output to state update
        if self.output_mapper:
            return self.output_mapper(result)
        else:
            return {
                "messages": result.messages,
                "agent_outputs": {result.agent_name: result},
            }


@dataclass(frozen=True)
class FunctionNode:
    """A node that runs a plain async function.

    The function takes the full state dict and returns a partial
    state update dict. This is the simplest and most flexible node type.
    """
    func: NodeFunction
    name: str = ""

    def __post_init__(self):
        if not self.name:
            object.__setattr__(self, "name", self.func.__name__)

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.func(state)


@dataclass(frozen=True)
class SubgraphNode:
    """A node that runs a compiled subgraph.

    Enables composition: a node in one graph can be an entire
    compiled graph. The subgraph receives the parent state and
    returns its final state as the update.
    """
    graph: Any  # CompiledGraph instance
    input_mapper: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    output_mapper: Callable[[dict[str, Any]], dict[str, Any]] | None = None

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        input_state = self.input_mapper(state) if self.input_mapper else state
        result = await self.graph.run(input_state)
        return self.output_mapper(result) if self.output_mapper else result


# Union of all node types
GraphNode = Union[AgentNode, FunctionNode, SubgraphNode]
```

### 4.2 `src/orchestra/core/edges.py`

```python
"""Graph edge types.

Edges define transitions between nodes. Three types:
- Edge: unconditional A -> B
- ConditionalEdge: A -> B|C|D based on state
- ParallelEdge: A -> [B, C, D] fan-out with join strategy
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Union

from orchestra.core.types import END


# Condition function: takes state, returns next node ID
EdgeCondition = Callable[[dict[str, Any]], str | list[str]]


@dataclass(frozen=True)
class Edge:
    """Unconditional edge: source always transitions to target."""
    source: str
    target: str


@dataclass(frozen=True)
class ConditionalEdge:
    """Conditional edge: source transitions based on condition function.

    The condition function receives the current state and returns
    the ID of the next node (or END to terminate).

    path_map is optional -- if provided, the condition returns a key
    and path_map maps keys to node IDs. This enables readable routing:

        add_conditional_edge(
            "reviewer",
            lambda state: "approve" if state["approved"] else "revise",
            path_map={"approve": END, "revise": "writer"},
        )
    """
    source: str
    condition: EdgeCondition
    path_map: dict[str, str] | None = None

    def resolve(self, state: dict[str, Any]) -> str | list[str]:
        result = self.condition(state)
        if self.path_map and isinstance(result, str):
            return self.path_map.get(result, result)
        return result


@dataclass(frozen=True)
class ParallelEdge:
    """Parallel edge: source fans out to multiple targets.

    All targets execute concurrently. Results are merged using
    state reducers before proceeding to join_node.
    """
    source: str
    targets: list[str]
    join_node: str | None = None  # Node to proceed to after all targets complete
```

### 4.3 `src/orchestra/core/graph.py`

```python
"""WorkflowGraph builder.

Fluent API for constructing workflow graphs. The graph is validated
and compiled into a CompiledGraph for execution.

Usage:
    graph = WorkflowGraph(state_class=MyState)
    graph.add_node("researcher", FunctionNode(research_fn))
    graph.add_node("writer", FunctionNode(write_fn))
    graph.add_edge("researcher", "writer")
    graph.set_entry_point("researcher")
    compiled = graph.compile()
    result = await compiled.run(initial_state)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from orchestra.core.edges import ConditionalEdge, Edge, EdgeCondition, ParallelEdge
from orchestra.core.nodes import FunctionNode, GraphNode, NodeFunction
from orchestra.core.state import WorkflowState
from orchestra.core.types import END, START


class GraphValidationError(Exception):
    """Raised when graph structure is invalid."""
    pass


class WorkflowGraph:
    """Builder for workflow graphs.

    Provides a fluent API for adding nodes and edges, then
    compiles into an executable CompiledGraph.
    """

    def __init__(self, state_class: type[WorkflowState] | None = None):
        self._state_class = state_class
        self._nodes: dict[str, GraphNode] = {}
        self._edges: list[Edge | ConditionalEdge | ParallelEdge] = []
        self._entry_point: str | None = None

    def add_node(
        self,
        node_id: str,
        node: GraphNode | NodeFunction,
    ) -> WorkflowGraph:
        """Add a node to the graph.

        Args:
            node_id: Unique identifier for this node.
            node: A GraphNode instance, or an async function
                  (automatically wrapped in FunctionNode).

        Returns:
            self (for chaining).

        Raises:
            ValueError: If node_id already exists or is reserved.
        """
        if node_id in (END, START):
            raise ValueError(f"'{node_id}' is a reserved node ID")
        if node_id in self._nodes:
            raise ValueError(f"Node '{node_id}' already exists")

        if callable(node) and not isinstance(node, (GraphNode,)):
            # If it is a plain function but not already a GraphNode subclass,
            # wrap it. We check for GraphNode subclass instances by duck-typing.
            if not hasattr(node, "__call__") or hasattr(node, "func") or hasattr(node, "agent") or hasattr(node, "graph"):
                pass  # Already a node type
            else:
                node = FunctionNode(func=node, name=node_id)

        self._nodes[node_id] = node
        return self

    def add_edge(self, source: str, target: str) -> WorkflowGraph:
        """Add an unconditional edge: source -> target.

        After source completes, execution proceeds to target.
        Use END as target to terminate after source.
        """
        self._edges.append(Edge(source=source, target=target))
        return self

    def add_conditional_edge(
        self,
        source: str,
        condition: EdgeCondition,
        path_map: dict[str, str] | None = None,
    ) -> WorkflowGraph:
        """Add a conditional edge: source -> condition(state) -> target.

        The condition function receives the current state and returns
        the ID of the next node. If path_map is provided, condition
        returns a key and path_map maps to node IDs.

        Args:
            source: Node ID to branch from.
            condition: Function(state) -> next_node_id.
            path_map: Optional mapping of condition results to node IDs.
        """
        self._edges.append(
            ConditionalEdge(source=source, condition=condition, path_map=path_map)
        )
        return self

    def add_parallel(
        self,
        source: str,
        targets: list[str],
        join_node: str | None = None,
    ) -> WorkflowGraph:
        """Add parallel fan-out: source -> [targets] concurrently.

        All targets execute in parallel. Results are merged using
        state reducers. Execution then proceeds to join_node.

        Args:
            source: Node ID to fan out from.
            targets: List of node IDs to execute in parallel.
            join_node: Node to proceed to after all targets complete.
                       If None, targets must each have their own outgoing edges.
        """
        self._edges.append(
            ParallelEdge(source=source, targets=targets, join_node=join_node)
        )
        return self

    def set_entry_point(self, node_id: str) -> WorkflowGraph:
        """Set the starting node for execution."""
        self._entry_point = node_id
        return self

    def compile(self, *, max_turns: int = 50) -> "CompiledGraph":
        """Validate the graph and return a CompiledGraph for execution.

        Validates:
        - Entry point is set and exists
        - All edge endpoints reference existing nodes (or END)
        - No unreachable nodes (warning, not error)
        - Cycles have a max_turns guard

        Args:
            max_turns: Maximum node executions before forced termination.

        Returns:
            CompiledGraph ready for execution.

        Raises:
            GraphValidationError: If validation fails.
        """
        self._validate()

        from orchestra.core.compiled import CompiledGraph

        return CompiledGraph(
            nodes=dict(self._nodes),
            edges=list(self._edges),
            entry_point=self._entry_point,
            state_class=self._state_class,
            max_turns=max_turns,
        )

    def _validate(self) -> None:
        """Validate graph structure."""
        if not self._entry_point:
            raise GraphValidationError("No entry point set. Call set_entry_point().")

        if self._entry_point not in self._nodes:
            raise GraphValidationError(
                f"Entry point '{self._entry_point}' does not exist in nodes."
            )

        if not self._nodes:
            raise GraphValidationError("Graph has no nodes.")

        # Validate all edge endpoints reference existing nodes
        valid_targets = set(self._nodes.keys()) | {END}
        for edge in self._edges:
            if isinstance(edge, Edge):
                if edge.source not in self._nodes:
                    raise GraphValidationError(
                        f"Edge source '{edge.source}' not found in nodes."
                    )
                if edge.target not in valid_targets:
                    raise GraphValidationError(
                        f"Edge target '{edge.target}' not found in nodes."
                    )
            elif isinstance(edge, ConditionalEdge):
                if edge.source not in self._nodes:
                    raise GraphValidationError(
                        f"Conditional edge source '{edge.source}' not found."
                    )
                if edge.path_map:
                    for target in edge.path_map.values():
                        if target not in valid_targets:
                            raise GraphValidationError(
                                f"Conditional edge target '{target}' not found."
                            )
            elif isinstance(edge, ParallelEdge):
                if edge.source not in self._nodes:
                    raise GraphValidationError(
                        f"Parallel edge source '{edge.source}' not found."
                    )
                for target in edge.targets:
                    if target not in valid_targets:
                        raise GraphValidationError(
                            f"Parallel target '{target}' not found."
                        )
```

### 4.4 `src/orchestra/core/compiled.py`

```python
"""CompiledGraph execution engine.

The CompiledGraph is the runtime engine. It takes a validated graph
structure and executes it against a state instance, routing through
edges and applying state updates via reducers.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from orchestra.core.edges import ConditionalEdge, Edge, ParallelEdge
from orchestra.core.nodes import GraphNode
from orchestra.core.state import (
    WorkflowState,
    apply_state_update,
    extract_reducers,
    merge_parallel_updates,
)
from orchestra.core.types import END, NodeStatus, WorkflowStatus

logger = logging.getLogger(__name__)


class ExecutionError(Exception):
    """Raised when graph execution fails."""
    pass


class CompiledGraph:
    """Executable workflow graph.

    Created by WorkflowGraph.compile(). Runs the graph against
    a state instance, following edges and applying state updates.
    """

    def __init__(
        self,
        nodes: dict[str, GraphNode],
        edges: list[Edge | ConditionalEdge | ParallelEdge],
        entry_point: str,
        state_class: type[WorkflowState] | None = None,
        max_turns: int = 50,
    ):
        self._nodes = nodes
        self._edges = edges
        self._entry_point = entry_point
        self._state_class = state_class
        self._max_turns = max_turns

        # Pre-compute edge lookup: source -> list of edges from that source
        self._edge_map: dict[str, list[Edge | ConditionalEdge | ParallelEdge]] = {}
        for edge in edges:
            source = edge.source
            self._edge_map.setdefault(source, []).append(edge)

        # Extract reducers if state class is provided
        self._reducers: dict[str, Any] = {}
        if state_class:
            self._reducers = extract_reducers(state_class)

    async def run(
        self,
        initial_state: dict[str, Any] | WorkflowState,
        *,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute the graph from entry point to completion.

        Args:
            initial_state: Starting state (dict or WorkflowState instance).
            context: Optional execution context passed to all nodes.

        Returns:
            Final state as a dict.

        Raises:
            ExecutionError: If execution fails or exceeds max_turns.
        """
        # Normalize state to WorkflowState instance
        if isinstance(initial_state, dict):
            if self._state_class:
                state = self._state_class.model_validate(initial_state)
            else:
                # No state class -- use a dynamic approach
                state = initial_state
                # Work with dicts directly
                return await self._run_dict_mode(state, context)
        else:
            state = initial_state

        current_node_id = self._entry_point
        turns = 0
        execution_log: list[dict[str, Any]] = []

        while current_node_id != END and turns < self._max_turns:
            turns += 1
            node = self._nodes[current_node_id]

            logger.debug(f"Executing node: {current_node_id} (turn {turns})")

            # Execute the node
            try:
                state_dict = state.model_dump()
                update = await node(state_dict)
            except Exception as e:
                raise ExecutionError(
                    f"Node '{current_node_id}' failed: {e}"
                ) from e

            # Apply state update
            if update:
                state = apply_state_update(state, update, self._reducers)

            execution_log.append({
                "node": current_node_id,
                "turn": turns,
                "status": NodeStatus.COMPLETED,
            })

            # Determine next node
            current_node_id = await self._resolve_next(
                current_node_id, state.model_dump()
            )

        if turns >= self._max_turns and current_node_id != END:
            raise ExecutionError(
                f"Workflow exceeded max_turns ({self._max_turns}). "
                f"Last node: {current_node_id}"
            )

        return state.model_dump()

    async def _run_dict_mode(
        self,
        state: dict[str, Any],
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Execute graph with plain dict state (no state class)."""
        current_node_id = self._entry_point
        turns = 0

        while current_node_id != END and turns < self._max_turns:
            turns += 1
            node = self._nodes[current_node_id]

            try:
                update = await node(dict(state))
            except Exception as e:
                raise ExecutionError(
                    f"Node '{current_node_id}' failed: {e}"
                ) from e

            if update:
                state.update(update)

            current_node_id = await self._resolve_next(current_node_id, state)

        if turns >= self._max_turns and current_node_id != END:
            raise ExecutionError(
                f"Workflow exceeded max_turns ({self._max_turns})"
            )

        return state

    async def _resolve_next(
        self,
        current_node_id: str,
        state: dict[str, Any],
    ) -> str:
        """Determine the next node based on outgoing edges.

        For parallel edges, executes all targets concurrently
        and merges results before proceeding to the join node.
        """
        edges = self._edge_map.get(current_node_id, [])

        if not edges:
            return END

        for edge in edges:
            if isinstance(edge, Edge):
                return edge.target

            elif isinstance(edge, ConditionalEdge):
                result = edge.resolve(state)
                if isinstance(result, str):
                    return result
                # If result is a list, treat as parallel (fan-out from condition)
                # For Phase 1, we only support single string returns
                return result

            elif isinstance(edge, ParallelEdge):
                # Execute all targets in parallel
                await self._execute_parallel(edge, state)
                return edge.join_node or END

        return END

    async def _execute_parallel(
        self,
        edge: ParallelEdge,
        state: dict[str, Any],
    ) -> None:
        """Execute parallel targets concurrently and merge results."""
        tasks = []
        for target_id in edge.targets:
            node = self._nodes[target_id]
            tasks.append(node(dict(state)))  # Each gets a copy

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Check for errors
        errors = [r for r in results if isinstance(r, Exception)]
        if errors:
            raise ExecutionError(
                f"Parallel execution failed: {errors[0]}"
            ) from errors[0]

        # Merge results into state using reducers
        updates = [r for r in results if isinstance(r, dict)]
        if self._state_class:
            current_state = self._state_class.model_validate(state)
            merged = merge_parallel_updates(current_state, updates, self._reducers)
            state.update(merged.model_dump())
        else:
            for update in updates:
                state.update(update)
```

**Dependencies on other tasks:** Task 2 (types, protocols), Task 3 (state management -- `apply_state_update`, `merge_parallel_updates`, `extract_reducers`).

**Test cases (tests/unit/test_graph.py):**

```python
# Graph Builder Tests:
# Test: add_node stores node
# Test: add_node rejects duplicate node_id
# Test: add_node rejects reserved IDs (END, START)
# Test: add_node wraps plain async function in FunctionNode
# Test: add_edge stores edge
# Test: add_conditional_edge stores conditional edge
# Test: add_parallel stores parallel edge
# Test: set_entry_point sets entry
# Test: compile raises if no entry point
# Test: compile raises if entry point not in nodes
# Test: compile raises if edge references nonexistent node
# Test: compile returns CompiledGraph on valid graph
# Test: method chaining works (returns self)
```

**Test cases (tests/unit/test_compiled.py):**

```python
# Execution Tests (using async FunctionNodes):
# Test: sequential two-node graph executes A -> B -> END
# Test: three-node linear chain A -> B -> C -> END
# Test: conditional edge routes to correct branch
# Test: conditional edge with path_map
# Test: conditional edge routes to END
# Test: parallel fan-out executes all targets
# Test: parallel fan-out merges state with reducers
# Test: max_turns terminates infinite loop
# Test: node error raises ExecutionError
# Test: graph with no outgoing edge from node terminates at END
# Test: dict-mode execution (no state class)
# Test: state class mode with reducers
# Test: cyclic graph with exit condition terminates
```

**Definition of done:**
- `WorkflowGraph` provides fluent API for building graphs
- `compile()` validates and returns `CompiledGraph`
- `CompiledGraph.run()` executes sequential, conditional, and parallel workflows
- State updates are applied through reducers correctly
- `max_turns` prevents infinite execution
- At least 25 unit tests pass
- `mypy` strict passes

---

## Task 5: Agent Definition

**Wave:** 2 (depends on Task 2 for protocols/types; parallel with Tasks 3-4)
**Estimated effort:** ~30 min Claude execution
**Files created:**

```
src/orchestra/core/agent.py
src/orchestra/core/decorators.py
tests/unit/test_agent.py
```

### 5.1 `src/orchestra/core/agent.py`

```python
"""BaseAgent: class-based agent implementation.

Provides the standard class-based agent definition pattern.
Subclass BaseAgent and override run() for custom behavior,
or use the default run loop which calls the LLM provider
and handles tool execution.

Usage:
    class ResearchAgent(BaseAgent):
        name = "researcher"
        model = "gpt-4o"
        system_prompt = "You are a research analyst..."
        tools = [web_search, doc_reader]
        output_type = ResearchReport  # Optional Pydantic model
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from orchestra.core.protocols import LLMProvider, Tool
from orchestra.core.types import (
    AgentResult,
    LLMResponse,
    Message,
    MessageRole,
    ToolCall,
    ToolResult,
)


class BaseAgent(BaseModel):
    """Base class for agent implementations.

    Class attributes define agent configuration.
    Instance can override via constructor.
    """

    name: str = "agent"
    model: str = "gpt-4o"
    system_prompt: str = "You are a helpful assistant."
    tools: list[Any] = Field(default_factory=list)  # list[Tool]
    max_iterations: int = 10
    temperature: float = 0.7
    output_type: Any = None  # Optional Pydantic model for structured output

    # Runtime dependency -- injected or set before run
    llm_provider: Any = Field(default=None, exclude=True)  # LLMProvider

    model_config = {"arbitrary_types_allowed": True}

    async def run(
        self,
        messages: list[Message],
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Execute the agent's reasoning loop.

        Default implementation:
        1. Prepend system prompt
        2. Call LLM
        3. If tool calls, execute tools and loop
        4. Return final response as AgentResult

        Override for custom behavior.
        """
        if not self.llm_provider:
            raise RuntimeError(
                f"Agent '{self.name}' has no LLM provider. "
                "Set agent.llm_provider before calling run()."
            )

        # Build message list with system prompt
        full_messages = [
            Message(role=MessageRole.SYSTEM, content=self.system_prompt)
        ] + list(messages)

        tool_schemas = [self._tool_to_schema(t) for t in self.tools] or None
        all_tool_calls: list[ToolCall] = []

        for iteration in range(self.max_iterations):
            response: LLMResponse = await self.llm_provider.chat(
                messages=full_messages,
                model=self.model,
                tools=tool_schemas,
                temperature=self.temperature,
            )

            if response.tool_calls:
                # Execute tool calls
                assistant_msg = Message(
                    role=MessageRole.ASSISTANT,
                    content=response.content or "",
                    tool_calls=response.tool_calls,
                )
                full_messages.append(assistant_msg)
                all_tool_calls.extend(response.tool_calls)

                for tool_call in response.tool_calls:
                    result = await self._execute_tool(tool_call, context)
                    tool_msg = Message(
                        role=MessageRole.TOOL,
                        content=result.content,
                        tool_call_id=tool_call.id,
                    )
                    full_messages.append(tool_msg)

                # Continue the loop for the LLM to process tool results
                continue

            # No tool calls -- we have a final response
            assistant_msg = Message(
                role=MessageRole.ASSISTANT,
                content=response.content or "",
                name=self.name,
            )

            return AgentResult(
                agent_name=self.name,
                messages=[assistant_msg],
                output=response.content,
                tool_calls_made=all_tool_calls,
                metadata={
                    "model": response.model,
                    "usage": response.usage.model_dump() if response.usage else {},
                    "iterations": iteration + 1,
                },
            )

        # Max iterations reached
        return AgentResult(
            agent_name=self.name,
            messages=[Message(
                role=MessageRole.ASSISTANT,
                content="Max iterations reached.",
                name=self.name,
            )],
            output="Max iterations reached.",
            tool_calls_made=all_tool_calls,
            metadata={"iterations": self.max_iterations, "max_reached": True},
        )

    async def _execute_tool(
        self,
        tool_call: ToolCall,
        context: dict[str, Any] | None,
    ) -> ToolResult:
        """Execute a single tool call."""
        tool = next(
            (t for t in self.tools if t.name == tool_call.name),
            None,
        )
        if not tool:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content="",
                error=f"Tool '{tool_call.name}' not found.",
            )

        try:
            return await tool.execute(tool_call.arguments, context=context)
        except Exception as e:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content="",
                error=str(e),
            )

    def _tool_to_schema(self, tool: Any) -> dict[str, Any]:
        """Convert a Tool to the OpenAI function-calling schema format."""
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters_schema,
            },
        }
```

### 5.2 `src/orchestra/core/decorators.py`

```python
"""Decorator-based agent definition.

The @agent decorator turns an async function into an agent.
The function's docstring becomes the system prompt.
The function's signature defines the expected input.

Usage:
    @agent(name="researcher", model="gpt-4o", tools=[web_search])
    async def research(query: str) -> str:
        '''You are a senior research analyst. Find accurate information.'''

    result = await research.run(messages=[...])
"""

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable, Awaitable

from orchestra.core.agent import BaseAgent
from orchestra.core.types import AgentResult, Message


class DecoratedAgent(BaseAgent):
    """Agent created from a decorated function."""

    _original_func: Callable | None = None

    model_config = {"arbitrary_types_allowed": True}


def agent(
    name: str | None = None,
    model: str = "gpt-4o",
    tools: list[Any] | None = None,
    temperature: float = 0.7,
    max_iterations: int = 10,
) -> Callable:
    """Decorator to create an agent from an async function.

    The function's docstring becomes the system prompt.
    The function is not called directly -- instead, the
    framework's agent execution loop handles it.

    Args:
        name: Agent name (defaults to function name).
        model: LLM model to use.
        tools: List of Tool instances.
        temperature: LLM temperature.
        max_iterations: Max tool-calling iterations.

    Returns:
        A DecoratedAgent instance with the function's metadata.
    """

    def decorator(func: Callable) -> DecoratedAgent:
        agent_name = name or func.__name__
        system_prompt = inspect.getdoc(func) or "You are a helpful assistant."

        agent_instance = DecoratedAgent(
            name=agent_name,
            model=model,
            system_prompt=system_prompt,
            tools=tools or [],
            temperature=temperature,
            max_iterations=max_iterations,
        )
        agent_instance._original_func = func

        # Preserve function metadata
        functools.update_wrapper(agent_instance, func)

        return agent_instance

    return decorator
```

**Dependencies on other tasks:** Task 2 (types, protocols).

**Test cases (tests/unit/test_agent.py):**

```python
# BaseAgent Tests:
# Test: BaseAgent can be instantiated with defaults
# Test: BaseAgent.run raises RuntimeError without llm_provider
# Test: BaseAgent.run returns AgentResult with correct structure
# Test: BaseAgent tool execution calls correct tool
# Test: BaseAgent handles missing tool gracefully (returns error ToolResult)
# Test: BaseAgent respects max_iterations
# Test: BaseAgent._tool_to_schema generates correct OpenAI schema
# Test: BaseAgent with no tools produces response without tool calls

# Decorator Tests:
# Test: @agent creates DecoratedAgent instance
# Test: @agent uses function name as default name
# Test: @agent uses docstring as system_prompt
# Test: @agent preserves function metadata (__name__, __doc__)
# Test: decorated agent has run() method
# Test: decorated agent accepts custom name, model, tools
```

**Definition of done:**
- `BaseAgent` implements the full agent reasoning loop (LLM call -> tool call -> loop)
- `@agent` decorator creates agents from functions
- Both styles produce objects satisfying the `Agent` protocol
- At least 14 unit tests pass (using mock LLM provider)
- `mypy` strict passes

---

## Task 6: Tool System

**Wave:** 2 (depends on Task 2 for protocols/types; parallel with Tasks 3-5)
**Estimated effort:** ~30 min Claude execution
**Files created:**

```
src/orchestra/tools/__init__.py
src/orchestra/tools/base.py
src/orchestra/tools/registry.py
tests/unit/test_tools.py
```

### 6.1 `src/orchestra/tools/base.py`

```python
"""Tool Protocol implementation and @tool decorator.

Tools are functions that agents can call. The @tool decorator
auto-generates JSON Schema from Python type hints.

Usage:
    @tool
    async def web_search(query: str, max_results: int = 5) -> str:
        '''Search the web for information.'''
        return f"Results for: {query}"

    # Tool properties:
    web_search.name          # "web_search"
    web_search.description   # "Search the web for information."
    web_search.parameters_schema  # Auto-generated JSON Schema
"""

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable, Awaitable, get_type_hints

from orchestra.core.types import ToolResult


def _python_type_to_json_schema(type_hint: Any) -> dict[str, Any]:
    """Convert a Python type hint to JSON Schema type."""
    type_map = {
        str: {"type": "string"},
        int: {"type": "integer"},
        float: {"type": "number"},
        bool: {"type": "boolean"},
        list: {"type": "array"},
        dict: {"type": "object"},
    }

    # Handle basic types
    if type_hint in type_map:
        return type_map[type_hint]

    # Handle Optional (Union with None)
    origin = getattr(type_hint, "__origin__", None)
    if origin is list:
        args = getattr(type_hint, "__args__", ())
        items = _python_type_to_json_schema(args[0]) if args else {}
        return {"type": "array", "items": items}

    if origin is dict:
        return {"type": "object"}

    # Default to string
    return {"type": "string"}


def _generate_parameters_schema(func: Callable) -> dict[str, Any]:
    """Generate JSON Schema for function parameters.

    Inspects the function signature and type hints to produce
    a JSON Schema compatible with OpenAI function calling.
    """
    sig = inspect.signature(func)
    hints = get_type_hints(func)

    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "context"):
            continue

        prop: dict[str, Any] = {}

        # Get type from hints
        if param_name in hints:
            prop = _python_type_to_json_schema(hints[param_name])
        else:
            prop = {"type": "string"}

        properties[param_name] = prop

        # Required if no default value
        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required

    return schema


class ToolWrapper:
    """Wraps an async function as a Tool protocol implementation."""

    def __init__(
        self,
        func: Callable[..., Awaitable[Any]],
        name: str | None = None,
        description: str | None = None,
    ):
        self._func = func
        self._name = name or func.__name__
        self._description = description or inspect.getdoc(func) or ""
        self._parameters_schema = _generate_parameters_schema(func)
        functools.update_wrapper(self, func)

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return self._parameters_schema

    async def execute(
        self,
        arguments: dict[str, Any],
        *,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Execute the wrapped function with given arguments."""
        try:
            # Inject context if function accepts it
            sig = inspect.signature(self._func)
            if "context" in sig.parameters:
                arguments = {**arguments, "context": context}

            result = await self._func(**arguments)
            return ToolResult(
                tool_call_id="",  # Set by caller
                name=self.name,
                content=str(result),
            )
        except Exception as e:
            return ToolResult(
                tool_call_id="",
                name=self.name,
                content="",
                error=str(e),
            )

    def __repr__(self) -> str:
        return f"Tool({self._name})"


def tool(
    func: Callable | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Any:
    """Decorator to create a Tool from an async function.

    Can be used with or without arguments:

        @tool
        async def search(query: str) -> str: ...

        @tool(name="custom_search", description="Custom search tool")
        async def search(query: str) -> str: ...
    """
    if func is not None:
        # Used without arguments: @tool
        return ToolWrapper(func)

    # Used with arguments: @tool(name="...")
    def wrapper(f: Callable) -> ToolWrapper:
        return ToolWrapper(f, name=name, description=description)

    return wrapper
```

### 6.2 `src/orchestra/tools/registry.py`

```python
"""Tool registry for registration, lookup, and management.

Usage:
    registry = ToolRegistry()
    registry.register(web_search_tool)
    registry.register(calculator_tool)

    tool = registry.get("web_search")
    all_tools = registry.list_tools()
    schemas = registry.get_schemas()  # For LLM function calling
"""

from __future__ import annotations

from typing import Any

from orchestra.tools.base import ToolWrapper, tool as tool_decorator


class ToolNotFoundError(Exception):
    """Raised when a tool is not found in the registry."""
    pass


class ToolRegistry:
    """Central registry for tools.

    Manages tool registration, lookup, and schema generation.
    Thread-safe for read operations (tools are registered at startup).
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolWrapper] = {}

    def register(self, tool_instance: Any) -> None:
        """Register a tool.

        Args:
            tool_instance: A ToolWrapper or any object satisfying Tool protocol.

        Raises:
            ValueError: If a tool with the same name is already registered.
        """
        name = tool_instance.name
        if name in self._tools:
            raise ValueError(f"Tool '{name}' is already registered.")
        self._tools[name] = tool_instance

    def get(self, name: str) -> Any:
        """Get a tool by name.

        Raises:
            ToolNotFoundError: If tool is not registered.
        """
        if name not in self._tools:
            raise ToolNotFoundError(f"Tool '{name}' not found in registry.")
        return self._tools[name]

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def list_tools(self) -> list[dict[str, str]]:
        """List all registered tools with name and description."""
        return [
            {"name": t.name, "description": t.description}
            for t in self._tools.values()
        ]

    def get_schemas(self, tool_names: list[str] | None = None) -> list[dict[str, Any]]:
        """Get OpenAI function-calling schemas for tools.

        Args:
            tool_names: Optional filter. If None, returns all schemas.
        """
        tools = self._tools.values()
        if tool_names:
            tools = [self._tools[n] for n in tool_names if n in self._tools]

        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters_schema,
                },
            }
            for t in tools
        ]

    def unregister(self, name: str) -> None:
        """Remove a tool from the registry."""
        self._tools.pop(name, None)

    def clear(self) -> None:
        """Remove all tools from the registry."""
        self._tools.clear()

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
```

### 6.3 `src/orchestra/tools/__init__.py`

```python
"""Orchestra tool system."""

from orchestra.tools.base import ToolWrapper, tool
from orchestra.tools.registry import ToolNotFoundError, ToolRegistry

__all__ = ["ToolWrapper", "tool", "ToolRegistry", "ToolNotFoundError"]
```

**Dependencies on other tasks:** Task 2 (types: `ToolResult`).

**Test cases (tests/unit/test_tools.py):**

```python
# @tool decorator tests:
# Test: @tool creates ToolWrapper from async function
# Test: @tool without args uses function name and docstring
# Test: @tool with args uses custom name and description
# Test: parameters_schema generated from type hints (str, int, float, bool, list)
# Test: required params vs optional params (with defaults) in schema
# Test: execute calls the wrapped function with arguments
# Test: execute returns ToolResult on success
# Test: execute returns ToolResult with error on exception
# Test: context injection when function accepts context parameter

# ToolRegistry tests:
# Test: register adds tool
# Test: register rejects duplicate name
# Test: get returns registered tool
# Test: get raises ToolNotFoundError for missing tool
# Test: has returns True/False correctly
# Test: list_tools returns names and descriptions
# Test: get_schemas returns OpenAI-compatible schemas
# Test: get_schemas filters by tool_names
# Test: unregister removes tool
# Test: clear removes all tools
# Test: __len__ returns count
# Test: __contains__ works with 'in' operator
```

**Definition of done:**
- `@tool` decorator auto-generates JSON Schema from function signatures
- `ToolWrapper` satisfies the `Tool` protocol
- `ToolRegistry` provides registration, lookup, and schema generation
- At least 20 unit tests pass
- `mypy` strict passes

---

## Task 7: LLM Providers

**Wave:** 3 (depends on Task 2 for protocols/types, Task 5 for agent integration)
**Estimated effort:** ~40 min Claude execution
**Files created:**

```
src/orchestra/providers/__init__.py
src/orchestra/providers/base.py
src/orchestra/providers/openai.py
src/orchestra/providers/anthropic.py
tests/unit/test_providers.py
```

### 7.1 `src/orchestra/providers/base.py`

```python
"""Base LLM provider utilities.

Provides common functionality shared by all LLM provider adapters:
retry logic, rate limiting, and message format conversion.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from orchestra.core.types import Message, MessageRole

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Base exception for LLM provider errors."""
    pass


class RateLimitError(LLMError):
    """Raised when rate limited by the provider."""
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class AuthenticationError(LLMError):
    """Raised when API key is invalid."""
    pass


async def retry_with_backoff(
    func,
    *args,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    **kwargs,
) -> Any:
    """Retry an async function with exponential backoff.

    Retries on rate limit and transient errors.
    Does NOT retry on authentication errors.
    """
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except RateLimitError as e:
            last_error = e
            delay = e.retry_after or min(base_delay * (2 ** attempt), max_delay)
            logger.warning(
                f"Rate limited. Retrying in {delay:.1f}s "
                f"(attempt {attempt + 1}/{max_retries + 1})"
            )
            await asyncio.sleep(delay)
        except AuthenticationError:
            raise
        except (httpx.TransportError, httpx.TimeoutException) as e:
            last_error = e
            delay = min(base_delay * (2 ** attempt), max_delay)
            logger.warning(
                f"Transport error: {e}. Retrying in {delay:.1f}s "
                f"(attempt {attempt + 1}/{max_retries + 1})"
            )
            await asyncio.sleep(delay)

    raise LLMError(f"Max retries exceeded. Last error: {last_error}") from last_error


def messages_to_openai_format(messages: list[Message]) -> list[dict[str, Any]]:
    """Convert Orchestra Messages to OpenAI API format."""
    result = []
    for msg in messages:
        entry: dict[str, Any] = {
            "role": msg.role.value,
            "content": msg.content,
        }
        if msg.name:
            entry["name"] = msg.name
        if msg.tool_call_id:
            entry["tool_call_id"] = msg.tool_call_id
        if msg.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": __import__("json").dumps(tc.arguments),
                    },
                }
                for tc in msg.tool_calls
            ]
        result.append(entry)
    return result


def messages_to_anthropic_format(
    messages: list[Message],
) -> tuple[str, list[dict[str, Any]]]:
    """Convert Orchestra Messages to Anthropic API format.

    Returns (system_prompt, messages) since Anthropic uses
    a separate system parameter.
    """
    system_prompt = ""
    converted = []

    for msg in messages:
        if msg.role == MessageRole.SYSTEM:
            system_prompt = msg.content
            continue

        if msg.role == MessageRole.TOOL:
            converted.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id,
                        "content": msg.content,
                    }
                ],
            })
            continue

        entry: dict[str, Any] = {
            "role": "assistant" if msg.role == MessageRole.ASSISTANT else "user",
            "content": msg.content,
        }

        if msg.tool_calls:
            entry["content"] = [
                {"type": "text", "text": msg.content or ""},
            ] + [
                {
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.arguments,
                }
                for tc in msg.tool_calls
            ]

        converted.append(entry)

    return system_prompt, converted
```

### 7.2 `src/orchestra/providers/openai.py`

```python
"""OpenAI LLM provider adapter.

Requires: pip install orchestra[openai]

Usage:
    from orchestra.providers.openai import OpenAIProvider

    provider = OpenAIProvider(api_key="sk-...")
    response = await provider.chat(messages, model="gpt-4o")
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from orchestra.core.types import LLMResponse, Message, TokenUsage, ToolCall
from orchestra.providers.base import (
    AuthenticationError,
    LLMError,
    RateLimitError,
    messages_to_openai_format,
    retry_with_backoff,
)


class OpenAIProvider:
    """OpenAI API adapter implementing LLMProvider protocol."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str = "gpt-4o",
        max_retries: int = 3,
    ):
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError(
                "openai package required. Install with: pip install orchestra[openai]"
            )

        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._default_model = default_model
        self._max_retries = max_retries

    async def chat(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
    ) -> LLMResponse:
        """Send a chat completion request to OpenAI."""

        async def _call() -> LLMResponse:
            kwargs: dict[str, Any] = {
                "model": model or self._default_model,
                "messages": messages_to_openai_format(messages),
                "temperature": temperature,
            }
            if tools:
                kwargs["tools"] = tools
            if max_tokens:
                kwargs["max_tokens"] = max_tokens
            if stop:
                kwargs["stop"] = stop

            try:
                response = await self._client.chat.completions.create(**kwargs)
            except Exception as e:
                error_str = str(e)
                if "401" in error_str or "invalid_api_key" in error_str:
                    raise AuthenticationError(f"OpenAI auth failed: {e}")
                if "429" in error_str or "rate_limit" in error_str:
                    raise RateLimitError(f"OpenAI rate limit: {e}")
                raise LLMError(f"OpenAI API error: {e}") from e

            choice = response.choices[0]
            tool_calls = []

            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    tool_calls.append(ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=json.loads(tc.function.arguments),
                    ))

            finish_reason = "stop"
            if choice.finish_reason == "tool_calls":
                finish_reason = "tool_calls"
            elif choice.finish_reason == "length":
                finish_reason = "length"

            usage = None
            if response.usage:
                usage = TokenUsage(
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    total_tokens=response.usage.total_tokens,
                )

            return LLMResponse(
                content=choice.message.content,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
                usage=usage,
                model=response.model,
                raw_response=response,
            )

        return await retry_with_backoff(_call, max_retries=self._max_retries)

    async def chat_stream(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
    ) -> AsyncIterator[LLMResponse]:
        """Stream chat completion responses from OpenAI."""
        kwargs: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": messages_to_openai_format(messages),
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if stop:
            kwargs["stop"] = stop

        response = await self._client.chat.completions.create(**kwargs)

        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield LLMResponse(
                    content=chunk.choices[0].delta.content,
                    finish_reason="stop",
                    model=chunk.model or model or self._default_model,
                )
```

### 7.3 `src/orchestra/providers/anthropic.py`

```python
"""Anthropic LLM provider adapter.

Requires: pip install orchestra[anthropic]

Usage:
    from orchestra.providers.anthropic import AnthropicProvider

    provider = AnthropicProvider(api_key="sk-ant-...")
    response = await provider.chat(messages, model="claude-sonnet-4-20250514")
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from orchestra.core.types import LLMResponse, Message, TokenUsage, ToolCall
from orchestra.providers.base import (
    AuthenticationError,
    LLMError,
    RateLimitError,
    messages_to_anthropic_format,
    retry_with_backoff,
)


class AnthropicProvider:
    """Anthropic API adapter implementing LLMProvider protocol."""

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = "claude-sonnet-4-20250514",
        max_retries: int = 3,
    ):
        try:
            from anthropic import AsyncAnthropic
        except ImportError:
            raise ImportError(
                "anthropic package required. Install with: pip install orchestra[anthropic]"
            )

        self._client = AsyncAnthropic(api_key=api_key)
        self._default_model = default_model
        self._max_retries = max_retries

    async def chat(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
    ) -> LLMResponse:
        """Send a chat completion request to Anthropic."""

        async def _call() -> LLMResponse:
            system_prompt, converted_messages = messages_to_anthropic_format(messages)

            kwargs: dict[str, Any] = {
                "model": model or self._default_model,
                "messages": converted_messages,
                "max_tokens": max_tokens or 4096,
                "temperature": temperature,
            }
            if system_prompt:
                kwargs["system"] = system_prompt
            if tools:
                # Convert OpenAI tool format to Anthropic format
                kwargs["tools"] = [
                    {
                        "name": t["function"]["name"],
                        "description": t["function"]["description"],
                        "input_schema": t["function"]["parameters"],
                    }
                    for t in tools
                ]
            if stop:
                kwargs["stop_sequences"] = stop

            try:
                response = await self._client.messages.create(**kwargs)
            except Exception as e:
                error_str = str(e)
                if "401" in error_str or "authentication" in error_str.lower():
                    raise AuthenticationError(f"Anthropic auth failed: {e}")
                if "429" in error_str or "rate_limit" in error_str:
                    raise RateLimitError(f"Anthropic rate limit: {e}")
                raise LLMError(f"Anthropic API error: {e}") from e

            # Parse response
            content_text = ""
            tool_calls = []

            for block in response.content:
                if block.type == "text":
                    content_text += block.text
                elif block.type == "tool_use":
                    tool_calls.append(ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input,
                    ))

            finish_reason = "stop"
            if response.stop_reason == "tool_use":
                finish_reason = "tool_calls"
            elif response.stop_reason == "max_tokens":
                finish_reason = "length"

            usage = TokenUsage(
                prompt_tokens=response.usage.input_tokens,
                completion_tokens=response.usage.output_tokens,
                total_tokens=response.usage.input_tokens + response.usage.output_tokens,
            )

            return LLMResponse(
                content=content_text or None,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
                usage=usage,
                model=response.model,
                raw_response=response,
            )

        return await retry_with_backoff(_call, max_retries=self._max_retries)

    async def chat_stream(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
    ) -> AsyncIterator[LLMResponse]:
        """Stream chat completion responses from Anthropic."""
        system_prompt, converted_messages = messages_to_anthropic_format(messages)

        kwargs: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": converted_messages,
            "max_tokens": max_tokens or 4096,
            "temperature": temperature,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if stop:
            kwargs["stop_sequences"] = stop

        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield LLMResponse(
                    content=text,
                    finish_reason="stop",
                    model=model or self._default_model,
                )
```

### 7.4 `src/orchestra/providers/__init__.py`

```python
"""Orchestra LLM providers.

Providers are optional dependencies:
    pip install orchestra[openai]
    pip install orchestra[anthropic]
"""

__all__: list[str] = []
```

**Dependencies on other tasks:** Task 2 (types: Message, LLMResponse, ToolCall, TokenUsage).

**Test cases (tests/unit/test_providers.py):**

```python
# Base utilities:
# Test: messages_to_openai_format converts all message roles
# Test: messages_to_openai_format handles tool_calls
# Test: messages_to_openai_format handles tool_call_id
# Test: messages_to_anthropic_format extracts system prompt
# Test: messages_to_anthropic_format converts tool results
# Test: messages_to_anthropic_format converts tool_calls to tool_use
# Test: retry_with_backoff retries on RateLimitError
# Test: retry_with_backoff does NOT retry on AuthenticationError
# Test: retry_with_backoff respects max_retries
# Test: retry_with_backoff uses exponential delay

# Provider construction (no API key needed):
# Test: OpenAIProvider raises ImportError if openai not installed (mock)
# Test: AnthropicProvider raises ImportError if anthropic not installed (mock)
```

**Definition of done:**
- OpenAI and Anthropic adapters implement the `LLMProvider` protocol
- Message format conversion works for all message types (system, user, assistant, tool)
- Retry with exponential backoff handles rate limits and transient errors
- Streaming support for both providers
- At least 12 unit tests pass (using mocked API clients)
- `mypy` strict passes

---

## Task 8: Testing Infrastructure

**Wave:** 3 (depends on Task 2 types, Task 4 graph engine, Task 5 agent)
**Estimated effort:** ~30 min Claude execution
**Files created:**

```
tests/fixtures/__init__.py
tests/fixtures/llm.py
tests/fixtures/tools.py
tests/fixtures/state.py
tests/conftest.py  (updated)
tests/unit/test_graph_integration.py
```

### 8.1 `tests/fixtures/llm.py`

```python
"""ScriptedLLM: deterministic mock LLM for testing.

ScriptedLLM returns pre-defined responses in order. This enables
fully deterministic, fast (<30s) unit tests for agent workflows
without making any API calls.

Usage:
    llm = ScriptedLLM([
        LLMResponse(content="I'll search for that."),
        LLMResponse(content="Here are the results.", tool_calls=[...]),
        LLMResponse(content="Final answer."),
    ])

    # Each call to chat() returns the next response in the script
    r1 = await llm.chat(messages)  # "I'll search for that."
    r2 = await llm.chat(messages)  # "Here are the results."
    r3 = await llm.chat(messages)  # "Final answer."
    r4 = await llm.chat(messages)  # Raises ScriptExhaustedError
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from orchestra.core.types import LLMResponse, Message, ToolCall, TokenUsage


class ScriptExhaustedError(Exception):
    """Raised when ScriptedLLM has no more scripted responses."""
    pass


class ScriptedLLM:
    """Deterministic mock LLM that returns pre-scripted responses.

    Implements the LLMProvider protocol for testing.
    """

    def __init__(self, responses: list[LLMResponse | str]):
        """Initialize with a list of responses to return in order.

        Args:
            responses: List of LLMResponse objects or strings.
                       Strings are auto-wrapped in LLMResponse.
        """
        self._responses: list[LLMResponse] = []
        for r in responses:
            if isinstance(r, str):
                self._responses.append(LLMResponse(content=r))
            else:
                self._responses.append(r)
        self._index = 0
        self._call_log: list[dict[str, Any]] = []

    async def chat(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
    ) -> LLMResponse:
        """Return the next scripted response."""
        self._call_log.append({
            "messages": messages,
            "model": model,
            "tools": tools,
            "temperature": temperature,
        })

        if self._index >= len(self._responses):
            raise ScriptExhaustedError(
                f"ScriptedLLM exhausted after {len(self._responses)} calls. "
                f"Add more responses to the script."
            )

        response = self._responses[self._index]
        self._index += 1
        return response

    async def chat_stream(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
    ) -> AsyncIterator[LLMResponse]:
        """Stream the next scripted response word by word."""
        response = await self.chat(
            messages, model=model, tools=tools,
            temperature=temperature, max_tokens=max_tokens, stop=stop,
        )

        if response.content:
            words = response.content.split()
            for word in words:
                yield LLMResponse(content=word + " ", model=model or "scripted")

    @property
    def call_count(self) -> int:
        """Number of times chat() was called."""
        return len(self._call_log)

    @property
    def call_log(self) -> list[dict[str, Any]]:
        """Log of all calls made to this mock."""
        return self._call_log

    def reset(self) -> None:
        """Reset the response index and call log."""
        self._index = 0
        self._call_log.clear()
```

### 8.2 `tests/fixtures/tools.py`

```python
"""Mock tools for testing."""

from __future__ import annotations

from orchestra.tools.base import tool


@tool
async def echo_tool(text: str) -> str:
    """Echo the input text back."""
    return f"Echo: {text}"


@tool
async def add_tool(a: int, b: int) -> str:
    """Add two numbers."""
    return str(a + b)


@tool
async def failing_tool(message: str) -> str:
    """A tool that always raises an error."""
    raise RuntimeError(f"Tool failed: {message}")


@tool
async def context_tool(key: str, context: dict | None = None) -> str:
    """A tool that reads from context."""
    if context and key in context:
        return str(context[key])
    return f"Key '{key}' not found in context"
```

### 8.3 `tests/fixtures/state.py`

```python
"""Test state classes."""

from __future__ import annotations

from typing import Annotated, Any

from orchestra.core.state import WorkflowState, append_reducer, add_reducer, merge_dict_reducer
from orchestra.core.types import Message


class SimpleState(WorkflowState):
    """Simple test state with append-only messages and a counter."""
    messages: Annotated[list[Message], append_reducer] = []
    count: Annotated[int, add_reducer] = 0
    result: str = ""


class ResearchState(WorkflowState):
    """Test state for research workflow."""
    messages: Annotated[list[Message], append_reducer] = []
    query: str = ""
    research_data: str = ""
    draft: str = ""
    approved: bool = False
    iterations: Annotated[int, add_reducer] = 0
    agent_outputs: Annotated[dict[str, Any], merge_dict_reducer] = {}
```

### 8.4 Updated `tests/conftest.py`

```python
"""Shared test fixtures."""

import pytest

from tests.fixtures.llm import ScriptedLLM
from tests.fixtures.tools import echo_tool, add_tool, failing_tool, context_tool
from tests.fixtures.state import SimpleState, ResearchState


@pytest.fixture
def scripted_llm():
    """Create a ScriptedLLM with no pre-loaded responses."""
    return ScriptedLLM([])


@pytest.fixture
def echo():
    return echo_tool


@pytest.fixture
def adder():
    return add_tool


@pytest.fixture
def simple_state_class():
    return SimpleState


@pytest.fixture
def research_state_class():
    return ResearchState
```

### 8.5 `tests/unit/test_graph_integration.py`

First real integration-level tests combining graph + state + nodes:

```python
# Test: sequential two-node workflow with SimpleState
#   - Node A sets result="hello", count=1
#   - Node B appends to result, count=1
#   - Final state: result="hello world", count=2

# Test: conditional routing workflow
#   - Node A checks state and routes to B or C
#   - Verify correct branch is taken

# Test: parallel fan-out with reducer merge
#   - Source fans out to Node B and Node C
#   - Both append to messages list
#   - Fan-in merges via append_reducer
#   - Final messages list has entries from both

# Test: cyclic workflow with exit condition
#   - Writer -> Reviewer -> Writer (loop)
#   - Reviewer sets approved=True after 2 iterations
#   - Verify terminates and iterations == 2

# Test: full three-node research workflow
#   - Researcher -> Writer -> Reviewer
#   - Uses ResearchState
#   - Scripted responses for each node
#   - Verify final state has all fields populated
```

**Dependencies on other tasks:** Task 2, Task 3, Task 4, Task 5, Task 6.

**Test cases:** All fixtures should be usable. The integration tests above should pass.

**Definition of done:**
- `ScriptedLLM` returns scripted responses deterministically
- Mock tools work for testing tool execution
- Test state classes demonstrate reducer patterns
- At least 5 integration tests pass exercising the full stack
- All fixtures importable from conftest

---

## Task 9: CLI & Logging

**Wave:** 3 (depends on Task 1 for entry point, Task 2 for types)
**Estimated effort:** ~20 min Claude execution
**Files created:**

```
src/orchestra/cli.py
src/orchestra/observability/__init__.py
src/orchestra/observability/logging.py
tests/unit/test_cli.py
```

### 9.1 `src/orchestra/cli.py`

```python
"""Orchestra CLI.

Usage:
    orchestra init my-project       # Scaffold a new project
    orchestra run workflow.py       # Run a workflow file
    orchestra list-agents           # List registered agents (future)
    orchestra list-tools            # List registered tools (future)
    orchestra version               # Show version
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from orchestra import __version__

app = typer.Typer(
    name="orchestra",
    help="Orchestra: Python-first multi-agent orchestration framework",
    no_args_is_help=True,
)
console = Console()


@app.command()
def version():
    """Show Orchestra version."""
    console.print(f"Orchestra v{__version__}")


@app.command()
def init(
    project_name: str = typer.Argument(..., help="Name of the project to create"),
    directory: str = typer.Option(".", help="Directory to create project in"),
):
    """Initialize a new Orchestra project with scaffolding."""
    import os
    from pathlib import Path

    project_dir = Path(directory) / project_name
    project_dir.mkdir(parents=True, exist_ok=True)

    # Create basic structure
    (project_dir / "agents").mkdir(exist_ok=True)
    (project_dir / "tools").mkdir(exist_ok=True)
    (project_dir / "workflows").mkdir(exist_ok=True)

    # Create a starter workflow
    workflow_file = project_dir / "workflows" / "hello.py"
    workflow_file.write_text('''\
"""Hello World Orchestra workflow."""

import asyncio
from orchestra.core.graph import WorkflowGraph
from orchestra.core.nodes import FunctionNode
from orchestra.core.state import WorkflowState


class HelloState(WorkflowState):
    greeting: str = ""


async def greet(state: dict) -> dict:
    return {"greeting": "Hello from Orchestra!"}


async def main():
    graph = WorkflowGraph(state_class=HelloState)
    graph.add_node("greeter", FunctionNode(func=greet))
    graph.set_entry_point("greeter")
    graph.add_edge("greeter", "__end__")

    compiled = graph.compile()
    result = await compiled.run({})
    print(result["greeting"])


if __name__ == "__main__":
    asyncio.run(main())
''')

    console.print(f"[green]Created project:[/green] {project_dir}")
    console.print(f"  agents/")
    console.print(f"  tools/")
    console.print(f"  workflows/hello.py")
    console.print(f"\nRun: [bold]cd {project_name} && python workflows/hello.py[/bold]")


@app.command()
def run(
    workflow_file: str = typer.Argument(..., help="Path to workflow Python file"),
):
    """Run a workflow file."""
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("workflow", workflow_file)
    if spec is None or spec.loader is None:
        console.print(f"[red]Error:[/red] Cannot load {workflow_file}")
        raise typer.Exit(1)

    module = importlib.util.module_from_spec(spec)
    sys.modules["workflow"] = module
    spec.loader.exec_module(module)

    if hasattr(module, "main"):
        import asyncio
        asyncio.run(module.main())
    else:
        console.print(f"[red]Error:[/red] {workflow_file} has no main() function")
        raise typer.Exit(1)


@app.command()
def list_tools():
    """List available tools (placeholder for future implementation)."""
    console.print("[yellow]Tool listing will be available in a future version.[/yellow]")


@app.command()
def list_agents():
    """List registered agents (placeholder for future implementation)."""
    console.print("[yellow]Agent listing will be available in a future version.[/yellow]")


if __name__ == "__main__":
    app()
```

### 9.2 `src/orchestra/observability/logging.py`

```python
"""Structured logging configuration using structlog.

Provides two modes:
- Development: human-readable, colorized console output
- Production: JSON-formatted structured logs

Usage:
    from orchestra.observability.logging import setup_logging

    setup_logging(level="DEBUG", json_output=False)  # Development
    setup_logging(level="INFO", json_output=True)    # Production
"""

from __future__ import annotations

import logging
import sys

import structlog


def setup_logging(
    level: str = "INFO",
    json_output: bool = False,
) -> None:
    """Configure structured logging for Orchestra.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR).
        json_output: If True, output JSON (production).
                     If False, human-readable (development).
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    # Shared processors
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if json_output:
        # Production: JSON output
        renderer = structlog.processors.JSONRenderer()
    else:
        # Development: colorized console output
        renderer = structlog.dev.ConsoleRenderer(
            colors=True,
            pad_event=40,
        )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Also configure the formatter for stdlib handlers
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    for handler in logging.root.handlers:
        handler.setFormatter(formatter)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance.

    Usage:
        logger = get_logger(__name__)
        logger.info("workflow.started", workflow_id="abc", nodes=5)
    """
    return structlog.get_logger(name)
```

### 9.3 `src/orchestra/observability/__init__.py`

```python
"""Orchestra observability: logging, tracing, metrics."""

from orchestra.observability.logging import setup_logging, get_logger

__all__ = ["setup_logging", "get_logger"]
```

**Dependencies on other tasks:** Task 1 (package structure, CLI entry point).

**Test cases (tests/unit/test_cli.py):**

```python
# Test: 'orchestra version' prints version string
# Test: 'orchestra init test-project' creates directory structure
# Test: 'orchestra init test-project' creates hello.py workflow
# Test: 'orchestra run' with missing file shows error
# Test: setup_logging(json_output=False) configures console output
# Test: setup_logging(json_output=True) configures JSON output
# Test: get_logger returns a bound logger
```

**Definition of done:**
- `orchestra version` prints version
- `orchestra init <name>` creates project scaffold with working hello.py
- `orchestra run <file>` executes a workflow file
- structlog is configured for both dev (console) and prod (JSON) modes
- At least 7 tests pass
- `mypy` strict passes

---

## Task 10: Examples & Documentation

**Wave:** 4 (depends on ALL previous tasks -- needs working framework)
**Estimated effort:** ~30 min Claude execution
**Files created:**

```
examples/sequential.py
examples/parallel.py
examples/conditional.py
examples/handoff_basic.py
```

### 10.1 `examples/sequential.py`

Demonstrates a basic three-step sequential workflow:

```python
"""Sequential workflow: Researcher -> Writer -> Editor.

This example shows the simplest orchestration pattern:
three agents running in sequence, each passing output to the next.
"""

import asyncio
from typing import Annotated, Any

from orchestra.core.graph import WorkflowGraph
from orchestra.core.nodes import FunctionNode
from orchestra.core.state import WorkflowState, append_reducer
from orchestra.core.types import END, Message, MessageRole


class ArticleState(WorkflowState):
    topic: str = ""
    research: str = ""
    draft: str = ""
    final: str = ""
    log: Annotated[list[str], append_reducer] = []


async def research_node(state: dict[str, Any]) -> dict[str, Any]:
    """Simulate research agent."""
    topic = state["topic"]
    return {
        "research": f"Key findings about {topic}: [simulated research data]",
        "log": [f"Researched: {topic}"],
    }


async def writer_node(state: dict[str, Any]) -> dict[str, Any]:
    """Simulate writer agent."""
    research = state["research"]
    return {
        "draft": f"Article draft based on: {research[:50]}...",
        "log": ["Wrote draft"],
    }


async def editor_node(state: dict[str, Any]) -> dict[str, Any]:
    """Simulate editor agent."""
    draft = state["draft"]
    return {
        "final": f"[Edited] {draft}",
        "log": ["Edited and polished"],
    }


async def main():
    # Build graph
    graph = WorkflowGraph(state_class=ArticleState)
    graph.add_node("researcher", FunctionNode(func=research_node))
    graph.add_node("writer", FunctionNode(func=writer_node))
    graph.add_node("editor", FunctionNode(func=editor_node))

    graph.set_entry_point("researcher")
    graph.add_edge("researcher", "writer")
    graph.add_edge("writer", "editor")
    graph.add_edge("editor", END)

    compiled = graph.compile()

    # Run
    result = await compiled.run({"topic": "Multi-Agent AI Systems"})

    print(f"Topic: {result['topic']}")
    print(f"Final: {result['final']}")
    print(f"Steps: {result['log']}")


if __name__ == "__main__":
    asyncio.run(main())
```

### 10.2 `examples/parallel.py`

Demonstrates parallel fan-out/fan-in:

```python
"""Parallel workflow: Fan-out to multiple researchers, fan-in to synthesizer.

Three research agents work in parallel on different aspects of a topic.
A synthesizer agent then combines their findings.
"""

import asyncio
from typing import Annotated, Any

from orchestra.core.graph import WorkflowGraph
from orchestra.core.nodes import FunctionNode
from orchestra.core.state import WorkflowState, append_reducer, merge_dict_reducer
from orchestra.core.types import END


class ParallelResearchState(WorkflowState):
    topic: str = ""
    findings: Annotated[dict[str, str], merge_dict_reducer] = {}
    summary: str = ""
    log: Annotated[list[str], append_reducer] = []


async def research_technical(state: dict[str, Any]) -> dict[str, Any]:
    topic = state["topic"]
    return {
        "findings": {"technical": f"Technical analysis of {topic}"},
        "log": ["Completed technical research"],
    }


async def research_market(state: dict[str, Any]) -> dict[str, Any]:
    topic = state["topic"]
    return {
        "findings": {"market": f"Market analysis of {topic}"},
        "log": ["Completed market research"],
    }


async def research_competitors(state: dict[str, Any]) -> dict[str, Any]:
    topic = state["topic"]
    return {
        "findings": {"competitors": f"Competitor analysis of {topic}"},
        "log": ["Completed competitor research"],
    }


async def synthesize(state: dict[str, Any]) -> dict[str, Any]:
    findings = state["findings"]
    combined = " | ".join(f"{k}: {v}" for k, v in findings.items())
    return {
        "summary": f"Synthesis: {combined}",
        "log": ["Synthesized all findings"],
    }


async def main():
    graph = WorkflowGraph(state_class=ParallelResearchState)

    graph.add_node("dispatch", FunctionNode(func=lambda s: {}))
    graph.add_node("tech", FunctionNode(func=research_technical))
    graph.add_node("market", FunctionNode(func=research_market))
    graph.add_node("competitors", FunctionNode(func=research_competitors))
    graph.add_node("synthesizer", FunctionNode(func=synthesize))

    graph.set_entry_point("dispatch")
    graph.add_parallel("dispatch", ["tech", "market", "competitors"], join_node="synthesizer")
    graph.add_edge("synthesizer", END)

    compiled = graph.compile()
    result = await compiled.run({"topic": "AI Orchestration Frameworks"})

    print(f"Topic: {result['topic']}")
    print(f"Findings: {result['findings']}")
    print(f"Summary: {result['summary']}")
    print(f"Steps: {result['log']}")


if __name__ == "__main__":
    asyncio.run(main())
```

### 10.3 `examples/conditional.py`

Demonstrates conditional routing:

```python
"""Conditional workflow: Route based on content analysis.

A classifier analyzes input and routes to the appropriate
specialist agent (technical writer vs. creative writer).
"""

import asyncio
from typing import Annotated, Any

from orchestra.core.graph import WorkflowGraph
from orchestra.core.nodes import FunctionNode
from orchestra.core.state import WorkflowState, append_reducer
from orchestra.core.types import END


class ContentState(WorkflowState):
    request: str = ""
    content_type: str = ""  # "technical" or "creative"
    output: str = ""
    log: Annotated[list[str], append_reducer] = []


async def classifier(state: dict[str, Any]) -> dict[str, Any]:
    """Classify the request type."""
    request = state["request"].lower()
    if any(word in request for word in ["api", "code", "technical", "docs"]):
        content_type = "technical"
    else:
        content_type = "creative"
    return {
        "content_type": content_type,
        "log": [f"Classified as: {content_type}"],
    }


async def technical_writer(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "output": f"[Technical Doc] {state['request']}",
        "log": ["Technical writer produced output"],
    }


async def creative_writer(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "output": f"[Creative Content] {state['request']}",
        "log": ["Creative writer produced output"],
    }


def route_by_type(state: dict[str, Any]) -> str:
    """Routing function for conditional edge."""
    return state["content_type"]


async def main():
    graph = WorkflowGraph(state_class=ContentState)

    graph.add_node("classifier", FunctionNode(func=classifier))
    graph.add_node("technical", FunctionNode(func=technical_writer))
    graph.add_node("creative", FunctionNode(func=creative_writer))

    graph.set_entry_point("classifier")
    graph.add_conditional_edge(
        "classifier",
        route_by_type,
        path_map={"technical": "technical", "creative": "creative"},
    )
    graph.add_edge("technical", END)
    graph.add_edge("creative", END)

    compiled = graph.compile()

    # Test with technical request
    result = await compiled.run({"request": "Write API documentation for user auth"})
    print(f"Request: {result['request']}")
    print(f"Type: {result['content_type']}")
    print(f"Output: {result['output']}")
    print(f"Steps: {result['log']}")
    print()

    # Test with creative request
    result = await compiled.run({"request": "Write a blog post about AI trends"})
    print(f"Request: {result['request']}")
    print(f"Type: {result['content_type']}")
    print(f"Output: {result['output']}")
    print(f"Steps: {result['log']}")


if __name__ == "__main__":
    asyncio.run(main())
```

### 10.4 `examples/handoff_basic.py`

Demonstrates simple agent handoff (Swarm-style, modeled as conditional edges):

```python
"""Basic handoff: Triage agent routes to specialist agents.

This demonstrates the Swarm-style handoff pattern using
Orchestra's conditional edges. The triage agent analyzes
the request and hands off to the appropriate specialist.
"""

import asyncio
from typing import Annotated, Any

from orchestra.core.graph import WorkflowGraph
from orchestra.core.nodes import FunctionNode
from orchestra.core.state import WorkflowState, append_reducer
from orchestra.core.types import END


class SupportState(WorkflowState):
    user_message: str = ""
    department: str = ""
    response: str = ""
    log: Annotated[list[str], append_reducer] = []


async def triage_agent(state: dict[str, Any]) -> dict[str, Any]:
    """Analyze user message and determine department."""
    message = state["user_message"].lower()
    if "bill" in message or "charge" in message or "payment" in message:
        department = "billing"
    elif "bug" in message or "error" in message or "broken" in message:
        department = "technical"
    else:
        department = "general"
    return {
        "department": department,
        "log": [f"Triage: routed to {department}"],
    }


async def billing_agent(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "response": f"[Billing] Looking into your billing concern: {state['user_message']}",
        "log": ["Billing agent handled request"],
    }


async def technical_agent(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "response": f"[Technical] Investigating your issue: {state['user_message']}",
        "log": ["Technical agent handled request"],
    }


async def general_agent(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "response": f"[General] Happy to help with: {state['user_message']}",
        "log": ["General agent handled request"],
    }


def route_to_department(state: dict[str, Any]) -> str:
    return state["department"]


async def main():
    graph = WorkflowGraph(state_class=SupportState)

    graph.add_node("triage", FunctionNode(func=triage_agent))
    graph.add_node("billing", FunctionNode(func=billing_agent))
    graph.add_node("technical", FunctionNode(func=technical_agent))
    graph.add_node("general", FunctionNode(func=general_agent))

    graph.set_entry_point("triage")
    graph.add_conditional_edge(
        "triage",
        route_to_department,
        path_map={
            "billing": "billing",
            "technical": "technical",
            "general": "general",
        },
    )
    graph.add_edge("billing", END)
    graph.add_edge("technical", END)
    graph.add_edge("general", END)

    compiled = graph.compile()

    # Test different routing
    for msg in [
        "I was charged twice on my bill",
        "The app crashes when I click submit",
        "How do I change my password?",
    ]:
        result = await compiled.run({"user_message": msg})
        print(f"User: {msg}")
        print(f"Routed to: {result['department']}")
        print(f"Response: {result['response']}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
```

**Dependencies on other tasks:** ALL previous tasks (1-9). Examples use the full framework.

**Test cases:**
- Each example runs without errors: `python examples/sequential.py`
- Each example produces expected output
- Examples can be used as templates for user projects

**Definition of done:**
- All four examples execute successfully
- Each example demonstrates a distinct orchestration pattern
- Examples are self-contained (no API keys needed -- simulated agents)
- Code is well-commented and readable

---

## Dependency Graph & Wave Structure

```
Wave 1 (parallel, no dependencies):
  Task 1: Project Scaffolding
  Task 2: Core Protocols & Types

Wave 2 (parallel, depends on Wave 1):
  Task 3: State Management      (depends: Task 2)
  Task 4: Graph Engine           (depends: Task 2, Task 3)
  Task 5: Agent Definition       (depends: Task 2)
  Task 6: Tool System            (depends: Task 2)

Wave 3 (parallel, depends on Wave 2):
  Task 7: LLM Providers          (depends: Task 2, Task 5)
  Task 8: Testing Infrastructure (depends: Task 2, Task 3, Task 4, Task 5, Task 6)
  Task 9: CLI & Logging          (depends: Task 1)

Wave 4 (depends on ALL):
  Task 10: Examples & Docs       (depends: Tasks 1-9)
```

```
Task 1 ─────────────────────────────────────────────── Task 9
Task 2 ──┬── Task 3 ──┐
         ├── Task 4 ──┼── Task 8 ──┐
         ├── Task 5 ──┤            ├── Task 10
         └── Task 6 ──┘            │
              Task 7 ──────────────┘
```

## Overall Definition of Done for Phase 1

- [ ] `pip install -e ".[dev,openai,anthropic]"` installs cleanly
- [ ] `ruff check src/ tests/` passes with zero errors
- [ ] `mypy src/orchestra/` passes in strict mode
- [ ] `pytest tests/` passes with 80%+ code coverage
- [ ] All four examples run successfully without API keys
- [ ] `orchestra version` prints version
- [ ] `orchestra init demo && cd demo && python workflows/hello.py` works end-to-end
- [ ] Graph engine supports sequential, conditional, and parallel workflows
- [ ] State reducers correctly merge parallel updates
- [ ] BaseAgent and @agent decorator both produce working agents
- [ ] @tool decorator auto-generates JSON Schema from type hints
- [ ] ScriptedLLM enables deterministic testing
- [ ] OpenAI and Anthropic adapters implement LLMProvider protocol
- [ ] structlog provides dev (console) and prod (JSON) logging modes

## File Manifest (All Files Created in Phase 1)

```
pyproject.toml
Makefile
.gitignore
LICENSE
README.md
.github/workflows/ci.yml

src/orchestra/__init__.py
src/orchestra/py.typed
src/orchestra/cli.py

src/orchestra/core/__init__.py
src/orchestra/core/types.py
src/orchestra/core/protocols.py
src/orchestra/core/state.py
src/orchestra/core/agent.py
src/orchestra/core/decorators.py
src/orchestra/core/graph.py
src/orchestra/core/compiled.py
src/orchestra/core/nodes.py
src/orchestra/core/edges.py

src/orchestra/providers/__init__.py
src/orchestra/providers/base.py
src/orchestra/providers/openai.py
src/orchestra/providers/anthropic.py

src/orchestra/tools/__init__.py
src/orchestra/tools/base.py
src/orchestra/tools/registry.py

src/orchestra/observability/__init__.py
src/orchestra/observability/logging.py

tests/__init__.py
tests/conftest.py
tests/fixtures/__init__.py
tests/fixtures/llm.py
tests/fixtures/tools.py
tests/fixtures/state.py
tests/unit/__init__.py
tests/unit/test_state.py
tests/unit/test_graph.py
tests/unit/test_compiled.py
tests/unit/test_agent.py
tests/unit/test_tools.py
tests/unit/test_providers.py
tests/unit/test_cli.py
tests/unit/test_graph_integration.py

examples/sequential.py
examples/parallel.py
examples/conditional.py
examples/handoff_basic.py
```

**Total: 42 files**
