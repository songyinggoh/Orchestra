# Orchestra -- Project Roadmap

**Project:** Orchestra - Python-first Multi-Agent Orchestration Framework
**Created:** 2026-03-05
**Timeline:** 26 weeks (4 phases)
**Status:** Draft

---

## Phases

- [ ] **Phase 1: Core Engine (Weeks 1-6)** - Graph engine, agent protocol, typed state, LLM adapters, testing harness, CLI, and example workflows
- [ ] **Phase 2: Differentiation (Weeks 7-12)** - Event-sourced persistence, HITL, time-travel debugging, handoff protocol, MCP integration, and rich tracing
- [ ] **Phase 3: Production Readiness (Weeks 13-18)** - FastAPI server, OpenTelemetry, Redis cache, multi-tier memory, advanced test harnesses, guardrails, and cost tracking
- [ ] **Phase 4: Enterprise & Scale (Weeks 19-26)** - Cost router, agent IAM, Ray executor, NATS messaging, dynamic subgraphs, TypeScript SDK, and Kubernetes deployment

---

## Phase Details

---

### Phase 1: Core Engine

**Goal:** A developer can define agents, compose them into typed graph workflows, run them against real LLMs, and write deterministic unit tests -- all from a single `pip install orchestra`.

**Depends on:** Nothing (foundation phase)

**Requirements:** SETUP-01 through SETUP-11 (all Phase 1 tasks below)

**Success Criteria** (what must be TRUE when this phase completes):
1. A user can `pip install -e .` the project from source with zero errors and import `orchestra`
2. A user can define an agent (class-based or decorator), wire it into a WorkflowGraph with sequential/parallel/conditional edges, compile, and run -- producing correct output against a real OpenAI or Anthropic model
3. A user can write a pytest test using ScriptedLLM that completes in under 5 seconds with fully deterministic, reproducible results
4. A user can run `orchestra run examples/sequential.py` from the CLI and see structured log output tracing each node execution
5. Three working example workflows (sequential, parallel, conditional) exist and pass CI

**Plans:** TBD

#### Task 1.1: Project Scaffolding

**Description:** Initialize the repository with pyproject.toml (PEP 621), src layout, dev tooling (ruff, mypy, pytest), pre-commit hooks, GitHub Actions CI pipeline, and the directory structure defined in the tech stack recommendation.

**Dependencies:** None -- first task

**Estimated Effort:** 2 days

**Deliverables:**
- `pyproject.toml` with all core and optional dependency groups
- `src/orchestra/__init__.py` with version
- `src/orchestra/core/`, `providers/`, `memory/`, `tools/`, `transport/`, `storage/`, `observability/`, `api/` package stubs
- `tests/unit/`, `tests/integration/`, `tests/simulation/`, `tests/fixtures/` directories
- `examples/` directory
- `.github/workflows/ci.yml` running lint + type check + tests on Python 3.11 and 3.12
- `ruff.toml`, `mypy.ini` or pyproject sections
- Pre-commit config with ruff, mypy

**Success Criteria / Definition of Done:**
- `pip install -e ".[dev]"` succeeds on a clean venv
- `ruff check src/` passes with zero errors
- `mypy src/orchestra/` passes with zero errors
- `pytest` runs and collects 0 tests (no failures)
- CI pipeline triggers on push and completes green

**Risk Level:** Low

---

#### Task 1.2: Agent Protocol and Base Classes

**Description:** Define the `Agent` Protocol (structural subtyping), `AgentSpec` internal representation, class-based `Agent` base class, `@agent` decorator for function-based definition, `AgentNode` and `FunctionNode` graph node types, and the `ExecutionContext` that agents receive at runtime.

**Dependencies:** Task 1.1 (project scaffolding must exist)

**Estimated Effort:** 4 days

**Deliverables:**
- `src/orchestra/core/agent.py` -- Agent Protocol, BaseAgent class, @agent decorator
- `src/orchestra/core/node.py` -- AgentNode, FunctionNode, GraphNode Protocol
- `src/orchestra/core/context.py` -- ExecutionContext (carries state, config, logger)
- Unit tests covering both definition styles and ExecutionContext injection

**Success Criteria / Definition of Done:**
- A class-based agent and a decorator-based agent both produce equivalent AgentSpec instances
- Agents receive ExecutionContext and can read/write state through it
- Type checking passes: mypy validates Protocol conformance
- At least 10 unit tests pass covering agent creation, invocation, and context access

**Risk Level:** Low

---

#### Task 1.3: Graph Engine (WorkflowGraph and CompiledGraph)

**Description:** Implement the core graph engine: `WorkflowGraph` builder with `add_node`, `add_edge`, `add_conditional_edge`, `add_parallel`, `set_entry_point`, and `compile()`. `CompiledGraph` performs validation (unreachable nodes, type mismatches, cycle detection with max_turns guard) and provides an async `run(state)` method using an `AsyncioExecutor`.

**Dependencies:** Task 1.2 (node types must be defined)

**Estimated Effort:** 6 days

**Deliverables:**
- `src/orchestra/core/graph.py` -- WorkflowGraph builder
- `src/orchestra/core/compiled.py` -- CompiledGraph with validation and execution
- `src/orchestra/core/executor.py` -- AsyncioExecutor using asyncio.TaskGroup for parallel nodes
- `src/orchestra/core/errors.py` -- GraphCompilationError, UnreachableNodeError, CycleDetectedError
- Unit tests for graph building, compilation validation, and execution

**Success Criteria / Definition of Done:**
- A graph with sequential edges executes nodes in declared order
- A graph with parallel nodes executes them concurrently (verified by timing)
- A graph with conditional edges routes based on state values
- Compilation rejects graphs with unreachable nodes (raises GraphCompilationError)
- Compilation detects cycles and requires max_turns to be set (raises CycleDetectedError)
- At least 15 unit tests covering builder API, validation, sequential/parallel/conditional execution, and error cases

**Risk Level:** Medium -- The graph engine is the architectural foundation. Getting the execution model and error handling right is critical. Parallel fan-in with reducer semantics is the hardest part.

---

#### Task 1.4: Reducer-Based Typed State (Pydantic)

**Description:** Implement the `WorkflowState` base class using Pydantic v2 with `Annotated` reducer functions for merge semantics. Provide built-in reducers: `last_write_wins`, `merge_list`, `merge_dict`, `merge_set`. State must be serializable to JSON and support immutable snapshots for checkpoint comparison.

**Dependencies:** Task 1.1 (Pydantic dependency must be available)

**Estimated Effort:** 3 days

**Deliverables:**
- `src/orchestra/core/state.py` -- WorkflowState base, reducer annotations, built-in reducers
- `src/orchestra/core/reducers.py` -- Reducer Protocol and implementations
- Unit tests for each reducer, state merge operations, serialization round-trips

**Success Criteria / Definition of Done:**
- A custom state class with `Annotated[list[str], merge_list]` correctly appends when two agents write concurrently
- `last_write_wins` correctly resolves conflicting scalar updates
- State serializes to JSON and deserializes back to an identical Pydantic model
- State can produce an immutable snapshot (frozen copy) for comparison
- At least 12 unit tests covering all built-in reducers, merge conflicts, serialization, and type validation errors

**Risk Level:** Low

---

#### Task 1.5: LLM Provider Protocol + OpenAI Adapter + Anthropic Adapter

**Description:** Define the `LLMProvider` Protocol with methods for `chat_completion` (with streaming support), `count_tokens`, and `get_model_info`. Implement `OpenAIProvider` and `AnthropicProvider` adapters. Include rate limiting, retry with exponential backoff, and structured error types. All providers must be async-first and accept an `httpx.AsyncClient` for testability.

**Dependencies:** Task 1.1 (httpx, provider SDKs as optional deps)

**Estimated Effort:** 5 days

**Deliverables:**
- `src/orchestra/providers/base.py` -- LLMProvider Protocol, LLMResponse model, UsageInfo model
- `src/orchestra/providers/openai.py` -- OpenAI adapter with function calling support
- `src/orchestra/providers/anthropic.py` -- Anthropic adapter with tool use support
- `src/orchestra/providers/errors.py` -- RateLimitError, ProviderTimeoutError, AuthenticationError
- Unit tests with mocked HTTP responses for both providers

**Success Criteria / Definition of Done:**
- Both adapters implement the LLMProvider Protocol (mypy validates conformance)
- Calling `chat_completion` with a simple prompt returns an LLMResponse with content and usage info
- Function calling / tool use works through both adapters with identical interface
- Rate limit responses trigger automatic retry with backoff (tested with mocked 429 responses)
- Streaming yields incremental token chunks via async iterator
- At least 15 unit tests covering happy path, error handling, retries, streaming, and function calling

**Risk Level:** Medium -- LLM provider APIs evolve frequently. The abstraction must be flexible enough to accommodate API differences (OpenAI function_call vs Anthropic tool_use) without leaking provider-specific details.

---

#### Task 1.6: Function-Calling Tool Integration

**Description:** Implement the `Tool` Protocol and `@tool` decorator that auto-generates JSON schema from Python function signatures (using Pydantic). Build a basic `ToolExecutor` that validates inputs, executes tools, and returns structured results. Tools must integrate with the LLM providers' function-calling / tool-use interfaces.

**Dependencies:** Task 1.5 (LLM providers must support function calling)

**Estimated Effort:** 4 days

**Deliverables:**
- `src/orchestra/tools/base.py` -- Tool Protocol, @tool decorator, ToolResult model
- `src/orchestra/tools/executor.py` -- ToolExecutor with input validation and timeout
- `src/orchestra/tools/schema.py` -- Auto JSON schema generation from function signatures
- Integration with LLM provider function-calling interfaces
- Unit tests for schema generation, tool execution, and validation

**Success Criteria / Definition of Done:**
- A Python function decorated with `@tool` auto-generates a correct JSON schema matching the function's type hints
- ToolExecutor validates inputs against schema before execution (rejects invalid inputs with clear error)
- Tools with async and sync implementations both work
- An agent with tools can make a function call through the LLM provider, execute the tool, and return the result to the LLM
- Tool execution respects a configurable timeout (default 30s)
- At least 12 unit tests covering schema generation, sync/async execution, validation errors, and timeout behavior

**Risk Level:** Low

---

#### Task 1.7: ScriptedLLM Test Harness

**Description:** Implement `ScriptedLLM`, a deterministic mock that conforms to the `LLMProvider` Protocol and returns pre-defined responses in sequence. It must support function-call responses, multi-turn conversations, and assertion helpers (e.g., assert all scripted responses were consumed, assert expected prompts were received).

**Dependencies:** Task 1.5 (must conform to LLMProvider Protocol)

**Estimated Effort:** 3 days

**Deliverables:**
- `src/orchestra/testing/scripted.py` -- ScriptedLLM implementation
- `src/orchestra/testing/__init__.py` -- Public test utilities
- Pytest fixtures for easy ScriptedLLM setup
- Unit tests validating ScriptedLLM behavior

**Success Criteria / Definition of Done:**
- ScriptedLLM returns pre-defined responses in declared order
- ScriptedLLM supports function-call/tool-use responses (LLM requests a tool call, test provides the scripted tool result)
- `assert_all_consumed()` raises if scripted responses remain unused
- `assert_prompt_received(expected)` validates prompts sent to the mock
- A complete workflow test using ScriptedLLM runs in under 1 second with fully deterministic results
- At least 8 unit tests covering sequential responses, tool calls, assertion helpers, and edge cases (empty script, over-consumption)

**Risk Level:** Low

---

#### Task 1.8: Basic CLI with Typer

**Description:** Implement a CLI using Typer that supports: `orchestra run <workflow_file>` to execute a workflow from a Python file, `orchestra version` to print version info, and `orchestra init <project_name>` to scaffold a new Orchestra project from a template. The CLI must configure structlog output and handle errors gracefully.

**Dependencies:** Task 1.3 (graph engine must be runnable), Task 1.9 (logging must be configured)

**Estimated Effort:** 2 days

**Deliverables:**
- `src/orchestra/cli/__init__.py` -- Typer app
- `src/orchestra/cli/run.py` -- `orchestra run` command
- `src/orchestra/cli/init.py` -- `orchestra init` scaffolding command
- `src/orchestra/cli/templates/` -- Project scaffold templates
- Entry point registered in pyproject.toml (`[project.scripts]`)
- Unit tests for CLI commands

**Success Criteria / Definition of Done:**
- `orchestra --help` prints available commands
- `orchestra run examples/sequential.py` executes the workflow and prints structured output
- `orchestra init myproject` creates a directory with pyproject.toml, a sample agent, and a sample workflow
- Non-zero exit code on errors with human-readable error messages (not raw tracebacks)
- At least 5 unit tests using Typer's CliRunner

**Risk Level:** Low

---

#### Task 1.9: Console Logging with structlog

**Description:** Configure structlog for the framework with two output modes: human-readable colored console output for development (default) and JSON structured output for production. Integrate with the ExecutionContext so every log line includes workflow_id, node_id, and agent_name. Provide a `configure_logging(level, format)` public API.

**Dependencies:** Task 1.1 (structlog dependency)

**Estimated Effort:** 2 days

**Deliverables:**
- `src/orchestra/observability/logging.py` -- structlog configuration, dev/prod processors
- `src/orchestra/observability/__init__.py` -- `configure_logging` public API
- Integration with ExecutionContext for automatic context binding
- Unit tests for log output format

**Success Criteria / Definition of Done:**
- Dev mode: logs are colored, human-readable, include timestamp + level + workflow_id + node_id + message
- Prod mode: logs are JSON lines with all context fields
- `configure_logging("DEBUG", "dev")` and `configure_logging("INFO", "json")` both work
- Log context automatically includes workflow_id and node_id when called from within a running workflow
- At least 5 unit tests verifying output format and context binding

**Risk Level:** Low

---

#### Task 1.10: Example Workflows

**Description:** Create three complete, documented example workflows that demonstrate core capabilities: (1) sequential pipeline (research then summarize), (2) parallel fan-out with reducer join (multiple analysts producing a merged report), (3) conditional routing (triage agent routes to specialist agents based on input classification). Each example must work end-to-end with both real LLMs and ScriptedLLM.

**Dependencies:** Tasks 1.2-1.7 (full core engine + testing harness)

**Estimated Effort:** 3 days

**Deliverables:**
- `examples/sequential.py` -- Two-agent pipeline with typed state
- `examples/parallel.py` -- Fan-out to 3 agents, merge with list reducer
- `examples/conditional.py` -- Triage agent with conditional edges to specialists
- `tests/integration/test_examples.py` -- Each example tested with ScriptedLLM
- Each file includes docstring explaining the pattern

**Success Criteria / Definition of Done:**
- All three examples execute successfully with ScriptedLLM in CI
- All three examples execute successfully with a real LLM when API key is provided (manual verification)
- Each example is self-contained in a single file (copy-pasteable)
- Each example is under 80 lines of code (demonstrates conciseness)
- Integration tests for all three examples pass in CI in under 10 seconds total

**Risk Level:** Low

---

#### Task 1.11: Documentation (Getting Started + API Reference)

**Description:** Write a "Getting Started" guide that walks through installation, first agent, first workflow, and first test. Generate API reference documentation from docstrings using mkdocs + mkdocstrings. Set up a docs site that builds in CI.

**Dependencies:** Tasks 1.2-1.10 (all code must be written and stable)

**Estimated Effort:** 3 days

**Deliverables:**
- `docs/getting-started.md` -- Installation through first working test
- `docs/concepts/agents.md` -- Agent definition patterns
- `docs/concepts/graphs.md` -- Graph composition patterns
- `docs/concepts/state.md` -- Typed state and reducers
- `docs/concepts/testing.md` -- ScriptedLLM testing guide
- `mkdocs.yml` configuration with mkdocstrings
- API reference auto-generated from docstrings
- CI step that builds docs and fails on broken links

**Success Criteria / Definition of Done:**
- A new developer can follow the Getting Started guide and have a working agent workflow with a passing test in under 15 minutes
- All public classes and functions have docstrings with examples
- `mkdocs build` succeeds with zero warnings
- API reference covers all public modules in `orchestra.core`, `orchestra.providers`, `orchestra.tools`, and `orchestra.testing`

**Risk Level:** Low

---

### Phase 2: Differentiation

**Goal:** Orchestra becomes visibly distinct from LangGraph through event-sourced persistence, time-travel debugging with a rich console renderer, first-class handoff protocol, and MCP tool integration -- features no single competing framework combines.

**Depends on:** Phase 1 (complete core engine)

**Requirements:** DIFF-01 through DIFF-11 (all Phase 2 tasks below)

**Success Criteria** (what must be TRUE when this phase completes):
1. A user can run a workflow, kill the process, restart, and the workflow resumes from the last checkpoint with no data loss
2. A user can interrupt a workflow at a designated HITL node, inspect the state in the terminal, modify it, and resume execution
3. A user can "time-travel" to any previous checkpoint, inspect the full state at that point, and optionally fork execution from that point
4. A user can see a real-time Rich-rendered trace tree in the terminal showing agent turns, tool calls, token usage, and timing
5. A user can define a handoff between agents using `add_handoff()` and context is preserved across the transfer

**Plans:** TBD

#### Task 2.1: Event-Sourced Persistence Layer

**Description:** Implement the event sourcing infrastructure: `WorkflowEvent` base type with subtypes (NodeStarted, NodeCompleted, StateUpdated, ToolCalled, LLMCalled, ErrorOccurred), an `EventStore` Protocol, event serialization, and state projection (rebuilding current state from event log). This is the storage-agnostic layer that SQLite and PostgreSQL backends will implement.

**Dependencies:** Phase 1 complete (state and graph engine stable)

**Estimated Effort:** 5 days

**Deliverables:**
- `src/orchestra/storage/events.py` -- WorkflowEvent hierarchy, event types
- `src/orchestra/storage/store.py` -- EventStore Protocol, state projection logic
- `src/orchestra/storage/serialization.py` -- Event serialization/deserialization
- Unit tests for event creation, serialization round-trips, and state projection

**Success Criteria / Definition of Done:**
- All workflow state transitions produce typed, immutable events
- State can be fully reconstructed from an event sequence (projection)
- Events serialize to JSON and MessagePack
- Event ordering is guaranteed (monotonic sequence numbers per workflow)
- At least 12 unit tests covering event types, serialization, projection, and ordering

**Risk Level:** Medium -- Event sourcing adds complexity. The projection logic must be correct and performant. Schema evolution (adding new event types in future versions) must be considered from day one.

---

#### Task 2.2: SQLite Storage Backend

**Description:** Implement the `EventStore` Protocol for SQLite using aiosqlite. Design the schema for `workflow_events`, `workflow_checkpoints`, and `workflow_metadata` tables. Implement snapshotting (periodic state projections stored as checkpoints to avoid replaying the full event log on resume). This is the default zero-infrastructure backend.

**Dependencies:** Task 2.1 (EventStore Protocol defined)

**Estimated Effort:** 4 days

**Deliverables:**
- `src/orchestra/storage/sqlite.py` -- SQLiteEventStore implementation
- Database migration/initialization logic (auto-creates tables on first use)
- Snapshotting logic (configurable interval, default every 50 events)
- Unit tests using in-memory SQLite

**Success Criteria / Definition of Done:**
- Events are durably stored in SQLite (verified by process restart test)
- State can be restored from events + latest snapshot
- Snapshotting reduces restoration time (benchmark: 1000 events with snapshot restores in under 100ms)
- Database auto-initializes on first use (no manual migration step)
- Concurrent writes from parallel nodes do not corrupt data (SQLite WAL mode)
- At least 10 unit tests covering write, read, snapshot, restore, and concurrent access

**Risk Level:** Low

---

#### Task 2.3: PostgreSQL Storage Backend

**Description:** Implement the `EventStore` Protocol for PostgreSQL using asyncpg. Same schema as SQLite but leveraging PostgreSQL features: advisory locks for workflow-level concurrency, LISTEN/NOTIFY for event streaming, and JSONB for event payloads. Include connection pooling configuration.

**Dependencies:** Task 2.1 (EventStore Protocol defined)

**Estimated Effort:** 4 days

**Deliverables:**
- `src/orchestra/storage/postgres.py` -- PostgresEventStore implementation
- SQL migration files for schema creation
- Connection pool configuration (asyncpg pool)
- Integration tests (require PostgreSQL, skipped in CI unless configured)

**Success Criteria / Definition of Done:**
- All EventStore Protocol methods work identically to SQLite backend (same test suite passes against both)
- Advisory locks prevent concurrent writes to the same workflow
- LISTEN/NOTIFY enables real-time event streaming to subscribers
- Connection pooling handles at least 50 concurrent workflow executions without pool exhaustion
- At least 8 integration tests (conditional on PostgreSQL availability)

**Risk Level:** Medium -- Requires PostgreSQL for testing. Connection pool tuning may need iteration.

---

#### Task 2.4: Checkpoint-Based HITL (Interrupt/Resume)

**Description:** Implement human-in-the-loop via checkpoint interruption. Add an `interrupt_before` parameter to nodes that pauses execution before that node runs, persists current state to the event store, and returns control to the caller. The caller can inspect state, optionally modify it, and call `resume()` to continue execution. Integrate with the CLI for interactive use.

**Dependencies:** Task 2.1 + 2.2 (event store with persistence)

**Estimated Effort:** 5 days

**Deliverables:**
- `src/orchestra/core/hitl.py` -- InterruptSignal, interrupt_before support in CompiledGraph
- `src/orchestra/core/resume.py` -- Resume logic (load checkpoint, validate state, continue execution)
- CLI integration: `orchestra resume <run_id>` command
- State inspection and modification API
- Unit and integration tests

**Success Criteria / Definition of Done:**
- A workflow with `interrupt_before="review_node"` pauses before that node and returns an InterruptSignal
- The interrupted state is persisted (survives process restart)
- `resume(run_id)` loads the checkpoint and continues from the interrupted node
- State can be modified between interrupt and resume (e.g., human edits a field)
- Multiple interrupt points in a single workflow work correctly (pause, resume, pause again)
- At least 10 tests covering interrupt, resume, state modification, process restart resume, and multiple interrupts

**Risk Level:** Medium -- Resumption must correctly reconstruct the full execution context (not just state, but also the graph position and any in-flight parallel branches).

---

#### Task 2.5: Time-Travel Debugging

**Description:** Implement time-travel debugging: the ability to list all checkpoints for a workflow run, inspect the full state at any checkpoint, diff state between two checkpoints, and fork a new execution from any historical checkpoint. Build on the event store's event log and snapshots.

**Dependencies:** Task 2.4 (checkpoints must exist)

**Estimated Effort:** 4 days

**Deliverables:**
- `src/orchestra/debugging/timetravel.py` -- list_checkpoints, get_state_at, diff_states, fork_from
- CLI integration: `orchestra debug <run_id>` interactive command
- State diff rendering (show which fields changed between checkpoints)
- Unit tests for all time-travel operations

**Success Criteria / Definition of Done:**
- `list_checkpoints(run_id)` returns all checkpoints with timestamps and node IDs
- `get_state_at(run_id, checkpoint_id)` returns the full state at that point
- `diff_states(checkpoint_a, checkpoint_b)` shows added/removed/changed fields
- `fork_from(run_id, checkpoint_id)` creates a new run that starts from the historical state
- Forked runs are independent (do not affect the original run's event log)
- At least 8 tests covering list, inspect, diff, and fork operations

**Risk Level:** Medium -- Forking from a historical checkpoint while preserving correct event log lineage requires careful design.

---

#### Task 2.6: Rich Console Trace Renderer

**Description:** Build a real-time terminal trace renderer using the Rich library that visualizes workflow execution as it happens: a tree of agent turns, tool calls with arguments and results, LLM calls with token counts and latency, state changes, and errors. This is the flagship developer experience feature -- "LangSmith in your terminal."

**Dependencies:** Phase 1 complete (logging infrastructure), Task 2.1 (event types)

**Estimated Effort:** 5 days

**Deliverables:**
- `src/orchestra/observability/console.py` -- RichTraceRenderer
- Real-time tree rendering (updates as events stream in)
- Color coding: green for success, yellow for HITL interrupts, red for errors
- Token usage and cost display per node
- Timing display per node (wall clock and LLM latency)
- Integration with the event stream (subscribes to workflow events)
- Manual testing with example workflows

**Success Criteria / Definition of Done:**
- Running a workflow with `ORCHESTRA_TRACE=rich` shows a live-updating tree in the terminal
- Each agent turn shows: agent name, model used, input/output token count, latency, cost estimate
- Tool calls show: tool name, arguments (truncated if long), result (truncated if long), duration
- Errors display the exception type and message inline in the tree
- HITL interrupts display a clear "PAUSED - awaiting human input" indicator
- The renderer does not slow down workflow execution by more than 5% overhead

**Risk Level:** Medium -- Rich's Live rendering can be tricky with async code. Must ensure the renderer does not block the event loop.

---

#### Task 2.7: Handoff Protocol as First-Class Edge Type

**Description:** Implement Swarm-style agent handoffs as a first-class graph edge type. `add_handoff(from_agent, to_agent, condition)` creates an edge that transfers execution with full context preservation. Handoffs carry a typed payload (context, reason, conversation history). Unlike Swarm, handoffs are persistent (event-sourced) and observable (traced).

**Dependencies:** Phase 1 graph engine, Task 2.1 (events)

**Estimated Effort:** 4 days

**Deliverables:**
- `src/orchestra/core/handoff.py` -- HandoffEdge, HandoffPayload, add_handoff on WorkflowGraph
- Event types: HandoffInitiated, HandoffCompleted
- Context preservation across handoff (conversation history, metadata)
- Unit tests for handoff behavior

**Success Criteria / Definition of Done:**
- `graph.add_handoff("triage", "specialist", condition=needs_expert)` creates a valid handoff edge
- Handoff transfers the full conversation history and metadata to the target agent
- Handoff events appear in the event log (HandoffInitiated with reason, HandoffCompleted)
- Handoffs render correctly in the Rich trace (shows "handoff: triage -> specialist" with reason)
- Conditional handoffs route to different agents based on state
- At least 8 tests covering simple handoff, conditional handoff, context preservation, and event logging

**Risk Level:** Low

---

#### Task 2.8: MCP Client Integration

**Description:** Implement an MCP (Model Context Protocol) client that discovers and invokes tools from MCP servers. MCP tools should be usable as regular Orchestra tools (registered in the tool system, callable by agents, traced in events). Support both stdio and SSE transport for MCP server communication.

**Dependencies:** Task 1.6 (tool system), Task 2.1 (events for tracing)

**Estimated Effort:** 5 days

**Deliverables:**
- `src/orchestra/tools/mcp.py` -- MCPClient, MCPToolAdapter
- stdio and SSE transport implementations
- Auto-discovery of MCP server tools (list_tools -> register as Orchestra tools)
- MCP tool calls traced as regular tool events
- Integration tests with a mock MCP server

**Success Criteria / Definition of Done:**
- MCPClient connects to an MCP server via stdio transport and discovers available tools
- MCPClient connects to an MCP server via SSE transport and discovers available tools
- Discovered MCP tools are usable by agents through the standard tool interface (agents do not know they are MCP tools)
- MCP tool calls produce ToolCalled events with full input/output tracing
- Error handling: MCP server timeout, tool execution error, and server disconnection are handled gracefully
- At least 8 tests using a mock MCP server

**Risk Level:** Medium -- MCP specification is still evolving. The implementation must be flexible enough to handle spec updates without breaking changes.

---

#### Task 2.9: Tool Registry with Basic ACLs

**Description:** Implement a centralized ToolRegistry that manages tool registration, discovery, and basic access control. ACLs define which agents can invoke which tools. In development mode, all agents have access to all tools (zero friction). In production mode, agents must be explicitly granted tool access.

**Dependencies:** Task 1.6 (tool system), Task 2.8 (MCP tools registered here too)

**Estimated Effort:** 3 days

**Deliverables:**
- `src/orchestra/tools/registry.py` -- ToolRegistry with registration, discovery, ACL checks
- `src/orchestra/tools/acl.py` -- ToolACL, PermissionDenied error
- Dev mode: all-access default. Prod mode: explicit grants required
- Unit tests for registration, discovery, and ACL enforcement

**Success Criteria / Definition of Done:**
- Tools registered via `@tool` decorator are automatically added to the registry
- `registry.get_tools_for(agent)` returns only tools the agent has access to
- In dev mode (`ORCHESTRA_ENV=dev`), all agents see all tools
- In prod mode (`ORCHESTRA_ENV=prod`), agents without explicit grants get PermissionDenied on invocation
- At least 8 tests covering registration, discovery, dev mode, prod mode, and permission denial

**Risk Level:** Low

---

#### Task 2.10: Google and Ollama LLM Provider Adapters

**Description:** Implement `GoogleProvider` (Gemini) and `OllamaProvider` (local models) adapters conforming to the LLMProvider Protocol. Google adapter supports Gemini function calling. Ollama adapter supports local model execution for development and air-gapped environments.

**Dependencies:** Task 1.5 (LLMProvider Protocol)

**Estimated Effort:** 4 days

**Deliverables:**
- `src/orchestra/providers/google.py` -- Google Gemini adapter
- `src/orchestra/providers/ollama.py` -- Ollama adapter (OpenAI-compatible API)
- Unit tests with mocked HTTP responses
- Documentation for configuring each provider

**Success Criteria / Definition of Done:**
- Both adapters implement the LLMProvider Protocol (mypy validates conformance)
- Google adapter supports chat completion and function calling with Gemini models
- Ollama adapter works with any model available in a local Ollama instance
- Streaming works for both providers
- At least 8 unit tests per adapter covering happy path, error handling, and streaming

**Risk Level:** Low

---

#### Task 2.11: Advanced Examples (Handoff, HITL, Event Replay)

**Description:** Create three advanced example workflows: (1) customer support with handoff from triage to specialist agents, (2) content review with HITL approval step, (3) research workflow demonstrating time-travel debugging and event replay. Each example must work end-to-end with ScriptedLLM.

**Dependencies:** Tasks 2.4, 2.5, 2.7 (HITL, time-travel, handoff implemented)

**Estimated Effort:** 3 days

**Deliverables:**
- `examples/handoff.py` -- Customer support triage with handoff to billing/technical/general agents
- `examples/hitl_review.py` -- Content generation with human approval checkpoint
- `examples/time_travel.py` -- Research workflow with event replay demonstration
- `tests/integration/test_advanced_examples.py` -- ScriptedLLM integration tests
- Each file includes detailed docstring explaining the pattern

**Success Criteria / Definition of Done:**
- All three examples execute successfully with ScriptedLLM in CI
- Handoff example demonstrates context preservation across two agent transfers
- HITL example demonstrates interrupt, state inspection, modification, and resume
- Time-travel example demonstrates checkpoint listing, state inspection at a historical point, and forked execution
- Integration tests pass in CI in under 15 seconds total

**Risk Level:** Low

---

### Phase 3: Production Readiness

**Goal:** Orchestra is deployable as a production service with HTTP API, real-time streaming, vendor-neutral observability, multi-tier memory, cost tracking, and safety guardrails.

**Depends on:** Phase 2 (persistence and observability foundations)

**Requirements:** PROD-01 through PROD-10 (all Phase 3 tasks below)

**Success Criteria** (what must be TRUE when this phase completes):
1. A user can start an Orchestra server, submit a workflow via REST API, and stream execution events via SSE in real-time
2. A user can view distributed traces in Jaeger/Grafana showing the full workflow execution with per-agent spans, token usage, and tool call details
3. A user can query per-agent and per-workflow cost attribution showing token usage and dollar amounts
4. A user can add guardrails (content filtering, PII detection, cost limits) to any agent with a single decorator
5. A user can run `docker compose up` and have a fully working Orchestra development environment with PostgreSQL, Redis, and the API server

**Plans:** TBD

#### Task 3.1: FastAPI Server + SSE Streaming

**Description:** Build the Orchestra API server using FastAPI. Implement the REST API defined in the tech stack recommendation (workflow CRUD, run management, SSE streaming, resume endpoint, trace retrieval, health check). SSE streams workflow events in real-time as the workflow executes.

**Dependencies:** Phase 2 complete (event store provides the event stream)

**Estimated Effort:** 6 days

**Deliverables:**
- `src/orchestra/api/app.py` -- FastAPI application factory
- `src/orchestra/api/routes/workflows.py` -- Workflow CRUD endpoints
- `src/orchestra/api/routes/runs.py` -- Run management + SSE streaming + resume
- `src/orchestra/api/routes/agents.py` -- Agent registration
- `src/orchestra/api/routes/health.py` -- Health and readiness checks
- `src/orchestra/api/schemas.py` -- Request/response Pydantic models
- `src/orchestra/api/middleware.py` -- Error handling, request ID, CORS
- Integration tests using httpx.AsyncClient

**Success Criteria / Definition of Done:**
- `POST /v1/runs` starts a workflow execution and returns a run_id
- `GET /v1/runs/{id}/stream` returns an SSE stream of events as the workflow executes
- `POST /v1/runs/{id}/resume` resumes an interrupted HITL workflow
- `GET /v1/runs/{id}/trace` returns the complete execution trace
- `GET /v1/health` returns 200 with status info
- All endpoints have OpenAPI schema documentation (auto-generated by FastAPI)
- At least 15 integration tests covering all endpoints, error cases, and SSE streaming

**Risk Level:** Medium -- SSE streaming with async workflow execution requires careful lifecycle management (client disconnects, workflow errors mid-stream).

---

#### Task 3.2: OpenTelemetry Tracing + Metrics

**Description:** Instrument the framework with OpenTelemetry: create spans for workflow runs, agent turns, LLM calls, and tool executions following the semantic conventions from the tech stack recommendation. Export to console (dev), OTLP (prod). Add metrics: workflow duration histogram, agent turn count, token usage counters, error rate.

**Dependencies:** Task 1.9 (structlog), Phase 2 events (span context from events)

**Estimated Effort:** 5 days

**Deliverables:**
- `src/orchestra/observability/tracing.py` -- OTel span management, auto-instrumentation
- `src/orchestra/observability/metrics.py` -- OTel metrics (counters, histograms, gauges)
- `src/orchestra/observability/exporters.py` -- Console exporter (dev), OTLP exporter (prod)
- Span hierarchy: workflow.run -> agent.turn -> llm.chat_completion / tool.call
- Semantic attributes: gen_ai.system, gen_ai.request.model, gen_ai.usage.input_tokens, etc.
- Integration tests verifying span creation and hierarchy

**Success Criteria / Definition of Done:**
- Running a workflow produces correct OTel spans visible in Jaeger when OTLP exporter is configured
- Span hierarchy correctly nests: workflow -> agent -> llm/tool
- Token usage is recorded as span attributes on llm.chat_completion spans
- Metrics are exported: workflow_duration_seconds (histogram), agent_turns_total (counter), llm_tokens_total (counter by model), workflow_errors_total (counter)
- Console exporter shows readable span summaries in dev mode
- At least 10 tests verifying span creation, nesting, attributes, and metric recording

**Risk Level:** Medium -- OTel SDK version conflicts with user dependencies are a known issue. Must use flexible version pinning.

---

#### Task 3.3: Redis Hot Cache Integration

**Description:** Implement Redis integration for hot state caching: active workflow state, tool result caching (with TTL), and session data. Use `redis[asyncio]` for async access. In development, provide an in-memory fallback (no Redis required). Implement cache invalidation on state updates.

**Dependencies:** Phase 1 (state system), Phase 2 (event store)

**Estimated Effort:** 3 days

**Deliverables:**
- `src/orchestra/storage/redis.py` -- RedisCache implementation
- `src/orchestra/storage/memory_cache.py` -- InMemoryCache fallback for dev
- `src/orchestra/storage/cache.py` -- CacheProtocol, cache key strategies
- Tool result caching with configurable TTL
- Unit tests using fakeredis

**Success Criteria / Definition of Done:**
- Active workflow state is cached in Redis and read from cache on access (cache hit avoids event replay)
- Tool results are cached with configurable TTL (default 5 minutes)
- Cache invalidation occurs on state update events
- In-memory fallback works identically when Redis is not configured
- At least 8 tests covering cache read/write, TTL expiry, invalidation, and fallback mode

**Risk Level:** Low

---

#### Task 3.4: Multi-Tier Memory System

**Description:** Implement the four-tier memory system from the research synthesis: (1) working memory (active context window, in-memory), (2) short-term memory (current session conversation history, SQLite/PostgreSQL), (3) long-term memory (cross-session semantic memory using pgvector), (4) entity memory (structured facts about entities, PostgreSQL). Provide a `MemoryManager` that agents access through ExecutionContext.

**Dependencies:** Task 2.2 or 2.3 (storage backends), Task 3.3 (cache for working memory)

**Estimated Effort:** 6 days

**Deliverables:**
- `src/orchestra/memory/working.py` -- WorkingMemory (in-memory context window management)
- `src/orchestra/memory/conversation.py` -- ConversationMemory (session history with storage)
- `src/orchestra/memory/semantic.py` -- SemanticMemory (pgvector-backed cross-session search)
- `src/orchestra/memory/entity.py` -- EntityMemory (structured fact storage and retrieval)
- `src/orchestra/memory/manager.py` -- MemoryManager (unified access for agents)
- Integration with ExecutionContext
- Unit and integration tests

**Success Criteria / Definition of Done:**
- An agent can store and retrieve conversation history for the current session (short-term)
- An agent can perform semantic similarity search across all past sessions (long-term, requires pgvector)
- An agent can store and query structured facts about entities (e.g., "user John prefers formal tone")
- Working memory automatically manages context window size (truncates oldest messages when approaching limit)
- MemoryManager provides a unified interface: `ctx.memory.search("topic")` returns results from all relevant tiers
- At least 12 tests covering each memory tier and the unified search interface

**Risk Level:** High -- Semantic memory with pgvector requires PostgreSQL + pgvector extension. Embedding generation adds latency and cost. Context window management heuristics need tuning.

---

#### Task 3.5: SimulatedLLM + FlakyLLM Test Harnesses

**Description:** Implement two additional test harnesses: (1) `SimulatedLLM` -- uses a cheap model (e.g., GPT-4o-mini) with seed and temperature=0 for realistic but reproducible integration tests, (2) `FlakyLLM` -- chaos testing mock that randomly injects timeouts, rate limit errors, partial responses, and connection resets to validate error handling and retry logic.

**Dependencies:** Task 1.7 (ScriptedLLM pattern established)

**Estimated Effort:** 4 days

**Deliverables:**
- `src/orchestra/testing/simulated.py` -- SimulatedLLM (wraps a real provider with seed + temp=0)
- `src/orchestra/testing/flaky.py` -- FlakyLLM (configurable failure injection)
- Pytest fixtures for both harnesses
- Documentation for test strategy (when to use each harness)

**Success Criteria / Definition of Done:**
- SimulatedLLM produces consistent results across runs when using the same seed and temperature=0
- SimulatedLLM can be configured with any real provider + model as the backend
- FlakyLLM injects failures at a configurable rate (default 20%)
- FlakyLLM supports: timeout, rate_limit_429, connection_reset, partial_response, malformed_json failure types
- Workflows tested with FlakyLLM demonstrate correct retry behavior and graceful degradation
- At least 10 tests covering SimulatedLLM consistency, FlakyLLM failure injection, and retry validation

**Risk Level:** Low

---

#### Task 3.6: Cost Tracking and Attribution

**Description:** Implement per-agent and per-workflow cost tracking. Calculate cost from token usage using model pricing tables. Attribute costs to specific agents, workflows, and (optionally) users. Provide a cost query API and integrate cost data into OTel spans and the Rich trace renderer.

**Dependencies:** Task 1.5 (token usage from providers), Task 3.2 (OTel for span attributes)

**Estimated Effort:** 4 days

**Deliverables:**
- `src/orchestra/observability/cost.py` -- CostTracker, model pricing tables, cost calculation
- `src/orchestra/observability/attribution.py` -- Cost attribution per agent, workflow, user
- Cost data in OTel span attributes (gen_ai.usage.cost_usd)
- Cost summary in Rich trace renderer (per-node and total)
- API endpoint: `GET /v1/runs/{id}/cost` returning cost breakdown
- Unit tests for cost calculation and attribution

**Success Criteria / Definition of Done:**
- After a workflow completes, `cost_tracker.get_cost(run_id)` returns total cost in USD
- Cost breakdown by agent is available: `cost_tracker.get_cost_by_agent(run_id)` returns per-agent totals
- Model pricing is configurable (users can override default prices)
- Cost appears in OTel spans as `gen_ai.usage.cost_usd` attribute
- Rich trace shows cost per node and total cost at the end of execution
- At least 8 tests covering cost calculation for different models, attribution, and custom pricing

**Risk Level:** Low

---

#### Task 3.7: Guardrails Middleware

**Description:** Implement a composable guardrails system as middleware that wraps agent execution. Guardrails include: content filtering (block harmful content), PII detection (redact or block PII in agent outputs), cost limits (per-agent and per-workflow budget caps), rate limiting (max LLM calls per minute), and output validation (ensure agent output matches expected schema). Guardrails are applied via decorators or graph configuration.

**Dependencies:** Task 1.2 (agent execution), Task 3.6 (cost tracking for budget enforcement)

**Estimated Effort:** 5 days

**Deliverables:**
- `src/orchestra/guardrails/base.py` -- Guardrail Protocol, GuardrailChain
- `src/orchestra/guardrails/content.py` -- ContentFilter (keyword + pattern-based)
- `src/orchestra/guardrails/pii.py` -- PIIDetector (regex-based for common PII patterns)
- `src/orchestra/guardrails/budget.py` -- BudgetGuardrail (per-agent, per-workflow cost caps)
- `src/orchestra/guardrails/rate_limit.py` -- RateLimitGuardrail (token bucket)
- `src/orchestra/guardrails/validation.py` -- OutputValidation (Pydantic schema enforcement)
- Decorator syntax: `@guardrail(content_filter(), pii_detector(), budget(max_usd=1.0))`
- Unit tests for each guardrail type

**Success Criteria / Definition of Done:**
- Content filter blocks agent output containing configurable prohibited patterns
- PII detector identifies and redacts common PII (email, phone, SSN patterns) in agent output
- Budget guardrail stops agent execution when cost exceeds the configured limit
- Rate limiter throttles LLM calls to configured rate (e.g., 10 calls/minute)
- Output validation rejects agent output that does not match the declared Pydantic schema
- Guardrails compose: multiple guardrails run in order, first failure stops the chain
- At least 15 tests covering each guardrail type, composition, and edge cases

**Risk Level:** Medium -- PII detection with regex is inherently limited. Must set expectations correctly (not a compliance-grade PII system, but a useful first line of defense).

---

#### Task 3.8: WebSocket for Interactive HITL

**Description:** Add WebSocket support to the FastAPI server for interactive human-in-the-loop sessions. When a workflow hits an interrupt point, the WebSocket connection notifies the client with the current state and waits for human input. This enables real-time interactive workflows (chat-style HITL, approval workflows, collaborative editing).

**Dependencies:** Task 3.1 (FastAPI server), Task 2.4 (HITL)

**Estimated Effort:** 4 days

**Deliverables:**
- `src/orchestra/api/routes/ws.py` -- WebSocket endpoint for interactive sessions
- `src/orchestra/api/ws_manager.py` -- Connection manager, session tracking
- Protocol: server sends state + prompt, client sends response/approval/modification
- Heartbeat and reconnection handling
- Integration tests

**Success Criteria / Definition of Done:**
- Client connects via WebSocket to `/v1/runs/{id}/interactive`
- When a HITL interrupt occurs, the client receives the current state and a description of what input is needed
- Client sends a response (approval, rejection, modified state), and the workflow resumes
- Disconnection is handled gracefully (workflow remains paused, reconnection resumes the session)
- At least 8 tests covering connection, interrupt notification, response handling, and disconnection

**Risk Level:** Medium -- WebSocket lifecycle management with async workflows requires careful state synchronization.

---

#### Task 3.9: Docker Compose Development Environment

**Description:** Create a Docker Compose configuration that stands up the complete Orchestra development environment: Orchestra API server, PostgreSQL (with pgvector), Redis, Jaeger (for trace viewing), and Grafana (for metrics dashboards). Include a pre-configured Grafana dashboard for Orchestra metrics.

**Dependencies:** Tasks 3.1-3.3 (API server, OTel, Redis)

**Estimated Effort:** 3 days

**Deliverables:**
- `docker-compose.yml` -- Full development environment
- `Dockerfile` -- Orchestra API server image (multi-stage build)
- `docker/postgres/init.sql` -- PostgreSQL initialization with pgvector extension
- `docker/grafana/dashboards/orchestra.json` -- Pre-built Grafana dashboard
- `docker/jaeger/` -- Jaeger configuration
- Documentation: `docs/deployment/docker-compose.md`

**Success Criteria / Definition of Done:**
- `docker compose up` starts all services with zero manual configuration
- Orchestra API is accessible at `http://localhost:8000`
- Jaeger UI shows Orchestra traces at `http://localhost:16686`
- Grafana shows Orchestra metrics dashboard at `http://localhost:3000`
- PostgreSQL is initialized with pgvector extension and Orchestra schema
- Health check: `curl http://localhost:8000/v1/health` returns 200 within 30 seconds of `docker compose up`

**Risk Level:** Low

---

#### Task 3.10: Performance Benchmarks

**Description:** Create a benchmark suite that measures: workflow execution overhead (graph engine latency without LLM calls), event store throughput (events written/read per second), state serialization speed, parallel node execution scaling, and end-to-end workflow latency with ScriptedLLM. Publish results in documentation and set baseline thresholds for regression detection in CI.

**Dependencies:** Phases 1-2 complete, Task 3.5 (test harnesses)

**Estimated Effort:** 3 days

**Deliverables:**
- `benchmarks/` directory with benchmark scripts using pytest-benchmark
- `benchmarks/bench_graph_engine.py` -- Graph execution overhead
- `benchmarks/bench_event_store.py` -- Event store read/write throughput
- `benchmarks/bench_state.py` -- State serialization/deserialization
- `benchmarks/bench_parallel.py` -- Parallel node scaling (2, 4, 8, 16 nodes)
- Baseline thresholds documented
- CI integration (benchmark runs on merge to main, results stored)

**Success Criteria / Definition of Done:**
- Graph engine overhead for a 5-node sequential workflow is under 5ms (without LLM calls)
- Event store writes at least 1000 events/second to SQLite
- State serialization for a 10-field Pydantic model completes in under 1ms
- Parallel execution of 8 nodes shows near-linear scaling (at least 6x speedup vs sequential)
- Benchmarks run in CI and fail if performance regresses by more than 20%

**Risk Level:** Low

---

### Phase 4: Enterprise & Scale

**Goal:** Orchestra supports enterprise deployment with intelligent cost optimization, agent-level security, distributed execution across machines, and a TypeScript client SDK for polyglot teams.

**Depends on:** Phase 3 (production infrastructure)

**Requirements:** ENT-01 through ENT-09 (all Phase 4 tasks below)

**Success Criteria** (what must be TRUE when this phase completes):
1. A user can configure a cost router that automatically dispatches simple tasks to cheap models and complex reasoning to expensive models, reducing overall costs by at least 30% on mixed workloads
2. A user can define agent permissions (tool ACLs, secret scopes, resource limits) and a compromised agent cannot access tools or secrets outside its permission boundary
3. A user can run a workflow distributed across multiple machines using Ray with no code changes -- only configuration
4. A user can interact with an Orchestra server from TypeScript using a typed client SDK
5. A user can deploy Orchestra to Kubernetes using provided manifests with horizontal scaling

**Plans:** TBD

#### Task 4.1: Intelligent Cost Router

**Description:** Implement a cost router that analyzes task complexity and automatically routes LLM calls to cost-appropriate models. Complexity profiling considers: prompt length, required output structure, reasoning depth indicators, and historical accuracy per model tier. Budget enforcement caps spending per-agent and per-workflow with automatic fallback to cheaper models rather than failure.

**Dependencies:** Task 3.6 (cost tracking), Task 1.5 (LLM providers)

**Estimated Effort:** 6 days

**Deliverables:**
- `src/orchestra/routing/cost_router.py` -- CostRouter with complexity profiling
- `src/orchestra/routing/classifier.py` -- Task complexity classifier (rule-based + optional ML)
- `src/orchestra/routing/budget.py` -- Budget enforcement with automatic model degradation
- `src/orchestra/routing/config.py` -- Model tier configuration (which models are cheap/mid/expensive)
- Unit tests with mocked LLM calls at different complexity levels
- Documentation for configuring model tiers and budgets

**Success Criteria / Definition of Done:**
- Simple prompts (short, no reasoning, no structured output) route to the cheapest configured model
- Complex prompts (long, multi-step reasoning, structured output) route to the most capable configured model
- Budget enforcement triggers automatic model degradation when spending approaches the limit
- Cost router is transparent: the trace shows which model was selected and why
- Override: users can force a specific model per-agent or per-call
- On a mixed workload benchmark, cost router reduces total spending by at least 30% compared to using the expensive model for everything
- At least 10 tests covering routing decisions, budget enforcement, degradation, and override

**Risk Level:** High -- Complexity classification is inherently imprecise. The classifier must err on the side of quality (route ambiguous tasks to better models) rather than cost savings.

---

#### Task 4.2: Capability-Based Agent IAM

**Description:** Implement the agent identity and access management system. Each agent has an identity with scoped permissions: tool ACLs (which tools it can call), secret scopes (which credentials it can access), resource limits (max tokens, max cost, max tool calls), and audit attribution (every action attributed to agent identity). Security is opt-in: dev mode has no restrictions, production mode enforces all constraints.

**Dependencies:** Task 2.9 (tool ACLs foundation), Task 3.7 (guardrails for resource limits)

**Estimated Effort:** 7 days

**Deliverables:**
- `src/orchestra/security/identity.py` -- AgentIdentity, Permission, Scope
- `src/orchestra/security/policy.py` -- SecurityPolicy, PermissionGrant, PermissionDenied
- `src/orchestra/security/secrets.py` -- ScopedSecretManager (agents receive only secrets they are granted)
- `src/orchestra/security/audit.py` -- SecurityAuditLog (every permission check logged)
- `src/orchestra/security/enforcement.py` -- SecurityMiddleware (enforces policy on agent execution)
- Dev mode: all-access. Prod mode: explicit grants required
- Unit tests for permission checking, secret scoping, and audit logging

**Success Criteria / Definition of Done:**
- An agent with tool ACL `["web_search", "file_read"]` can call those tools but gets PermissionDenied on `code_execute`
- An agent with secret scope `["openai_api_key"]` can access that key but not `database_password`
- Resource limits halt agent execution when exceeded (e.g., max 1000 tokens per turn)
- Every permission check (granted or denied) is recorded in the audit log
- Dev mode bypasses all checks. Prod mode enforces all checks.
- Security policy is defined in configuration (YAML or Python), not hardcoded
- At least 15 tests covering tool ACLs, secret scoping, resource limits, audit logging, dev/prod mode toggle

**Risk Level:** High -- Security systems must be correct. A bug that allows permission bypass defeats the purpose. Needs thorough testing including adversarial scenarios (agent trying to access tools through indirect paths).

---

#### Task 4.3: Ray Distributed Executor

**Description:** Implement the `RayExecutor` that runs workflow nodes as Ray actors distributed across a Ray cluster. Same graph definition, same agent code -- only the executor changes. Ray actors provide fault tolerance (automatic restart on failure), resource management (GPU allocation for local models), and horizontal scaling.

**Dependencies:** Phase 1 graph engine, Phase 2 event store (events must work across machines)

**Estimated Effort:** 7 days

**Deliverables:**
- `src/orchestra/core/ray_executor.py` -- RayExecutor implementing the Executor Protocol
- `src/orchestra/core/ray_actor.py` -- RayAgentActor (wraps an agent as a Ray actor)
- State synchronization between Ray actors via event store
- Resource configuration (CPU, GPU, memory per agent actor)
- Fault tolerance: automatic actor restart on failure, workflow resumption from last checkpoint
- Integration tests (require Ray, conditional on availability)

**Success Criteria / Definition of Done:**
- The same workflow graph runs identically on AsyncioExecutor and RayExecutor (same outputs, same events)
- Switching executor requires only configuration change: `executor="ray"` in workflow config
- Parallel nodes run on separate Ray actors (verified by Ray dashboard showing multiple actors)
- If a Ray actor crashes, it restarts and resumes from the last checkpoint
- Resource allocation works: an agent configured with `gpu=1` gets a GPU-equipped Ray actor
- At least 10 integration tests (conditional on Ray availability) covering distributed execution, fault tolerance, and resource allocation

**Risk Level:** High -- Distributed systems are inherently complex. State synchronization, serialization across machines, and fault tolerance require extensive testing. Ray version compatibility is a concern.

---

#### Task 4.4: NATS JetStream Messaging

**Description:** Implement NATS JetStream as the distributed message passing backend. Agents communicate via durable, ordered message streams with subject-based routing. Replace asyncio.Queue with NATS for distributed mode. Support pub/sub patterns for event-driven workflows where agents react to events without tight coupling.

**Dependencies:** Phase 1 (transport/local.py pattern), Task 4.3 (distributed execution context)

**Estimated Effort:** 5 days

**Deliverables:**
- `src/orchestra/transport/nats.py` -- NATSTransport implementing the Transport Protocol
- Subject naming: `agents.{workflow_id}.{agent_name}.input/output`
- Durable message streams with JetStream
- Pub/sub event broadcasting: `workflows.{workflow_id}.events`
- Connection management (reconnection, backpressure)
- Integration tests (require NATS server, conditional on availability)

**Success Criteria / Definition of Done:**
- Agent-to-agent messages are delivered in order via NATS JetStream subjects
- Messages are durable: a consumer restart does not lose unprocessed messages
- Event broadcasting works: multiple subscribers receive all workflow events
- Backpressure: a slow consumer does not cause message loss (JetStream buffering)
- Reconnection: a transient NATS disconnection does not crash the workflow
- At least 8 integration tests (conditional on NATS availability)

**Risk Level:** Medium -- NATS JetStream is well-proven but adding distributed messaging introduces network partitioning concerns and message ordering challenges.

---

#### Task 4.5: Dynamic Subgraph Generation (DynamicNode)

**Description:** Implement `DynamicNode`, a node type that generates new sub-nodes and edges at runtime. This enables plan-and-execute patterns where a planner agent decomposes a task into subtasks, each becoming a dynamically created subgraph node. Subgraphs are compiled and validated at runtime before execution.

**Dependencies:** Phase 1 graph engine (CompiledGraph must support subgraph injection)

**Estimated Effort:** 6 days

**Deliverables:**
- `src/orchestra/core/dynamic.py` -- DynamicNode, SubgraphGenerator Protocol
- `src/orchestra/core/subgraph.py` -- SubgraphBuilder, runtime compilation and validation
- Runtime graph mutation: inject subgraph nodes and edges into a running workflow
- Event types: SubgraphGenerated, SubgraphCompleted
- Unit tests for dynamic subgraph generation and execution

**Success Criteria / Definition of Done:**
- A DynamicNode receives state and returns a SubgraphSpec (nodes + edges + entry/exit points)
- The generated subgraph is compiled and validated at runtime (invalid subgraphs raise errors)
- Subgraph nodes execute within the parent workflow's state and event context
- Subgraph execution is traced (SubgraphGenerated and SubgraphCompleted events)
- A planner agent can decompose "write a report" into [research, outline, draft, review] as dynamic subnodes
- At least 10 tests covering subgraph generation, validation, execution, error handling, and event tracing

**Risk Level:** High -- Runtime graph mutation is the most architecturally complex feature. Must ensure state consistency when dynamically injected nodes run in parallel with statically defined nodes.

---

#### Task 4.6: TypeScript Client SDK

**Description:** Build a TypeScript client SDK that provides typed access to the Orchestra REST API. Auto-generate types from the FastAPI OpenAPI schema. Support all API operations: workflow management, run execution, SSE streaming, HITL interaction via WebSocket, and trace retrieval.

**Dependencies:** Task 3.1 (FastAPI server with OpenAPI schema)

**Estimated Effort:** 6 days

**Deliverables:**
- `sdk/typescript/` -- npm package
- `sdk/typescript/src/client.ts` -- OrchestraClient class
- `sdk/typescript/src/types.ts` -- Auto-generated types from OpenAPI
- `sdk/typescript/src/streaming.ts` -- SSE event stream consumer
- `sdk/typescript/src/ws.ts` -- WebSocket HITL client
- Type generation script (openapi-typescript or similar)
- Unit tests (Jest/Vitest)
- README with usage examples

**Success Criteria / Definition of Done:**
- TypeScript developers can `npm install @orchestra/client` and interact with an Orchestra server
- All API endpoints are accessible through typed methods (compile-time type safety)
- SSE streaming works: `client.streamRun(runId)` yields typed events
- WebSocket HITL works: `client.interactive(runId)` enables interactive sessions
- Types are auto-generated from the OpenAPI schema (no manual sync required)
- At least 10 TypeScript tests covering API calls, streaming, and WebSocket

**Risk Level:** Medium -- Maintaining type parity between Python server and TypeScript client requires automation. Manual sync will drift.

---

#### Task 4.7: YAML/Config-Based Agent Definition

**Description:** Implement the third agent definition style: YAML configuration files. Agents, tools, workflows, and security policies can be defined in YAML without writing Python code. A loader parses YAML into the same internal AgentSpec and WorkflowGraph used by Python definitions. This enables no-code agent configuration and platform integration.

**Dependencies:** Task 1.2 (AgentSpec), Task 1.3 (WorkflowGraph), Task 4.2 (security policy in config)

**Estimated Effort:** 4 days

**Deliverables:**
- `src/orchestra/config/loader.py` -- YAML loader for agents, workflows, and policies
- `src/orchestra/config/schema.py` -- YAML schema validation (Pydantic models for config structure)
- `src/orchestra/config/templates/` -- Example YAML templates
- CLI integration: `orchestra run workflow.yaml`
- Unit tests for YAML loading and validation

**Success Criteria / Definition of Done:**
- An agent defined in YAML produces an identical AgentSpec to the equivalent Python class definition
- A workflow defined in YAML produces an identical CompiledGraph to the equivalent Python builder code
- YAML validation errors produce clear, actionable error messages (line number, expected type)
- `orchestra run workflow.yaml` executes a YAML-defined workflow identically to a Python-defined one
- At least 8 tests covering agent loading, workflow loading, validation errors, and equivalence with Python definitions

**Risk Level:** Low

---

#### Task 4.8: Kubernetes Deployment Manifests

**Description:** Create production-ready Kubernetes manifests for deploying Orchestra: API server Deployment with HPA, PostgreSQL StatefulSet (or external database config), Redis Deployment, NATS StatefulSet, Jaeger Deployment, and Grafana Deployment. Include Helm chart for configurable deployments. Include NetworkPolicies, PodDisruptionBudgets, and resource limits.

**Dependencies:** Task 3.9 (Docker Compose as foundation), Tasks 4.3-4.4 (Ray and NATS for distributed mode)

**Estimated Effort:** 5 days

**Deliverables:**
- `deploy/kubernetes/` -- Raw manifests
- `deploy/helm/orchestra/` -- Helm chart with values.yaml
- API server: Deployment + HPA + Service + Ingress
- PostgreSQL: StatefulSet + PVC + Secret (or external database config)
- Redis: Deployment + Service
- NATS: StatefulSet + Service (JetStream enabled)
- Jaeger: Deployment + Service
- Grafana: Deployment + Service + ConfigMap (dashboards)
- NetworkPolicies limiting inter-service communication
- PodDisruptionBudgets for high availability
- Resource limits and requests on all containers
- Documentation: `docs/deployment/kubernetes.md`

**Success Criteria / Definition of Done:**
- `helm install orchestra deploy/helm/orchestra/` deploys all components to a Kubernetes cluster
- API server scales horizontally via HPA based on CPU/request rate
- PostgreSQL data persists across pod restarts (PVC)
- NATS JetStream is configured with persistence
- NetworkPolicies restrict traffic: only API server can reach PostgreSQL, only API server and workers reach NATS
- PodDisruptionBudgets prevent all replicas from being evicted simultaneously
- Health checks and readiness probes are configured on all deployments
- At least manual verification on a local k8s cluster (minikube or kind)

**Risk Level:** Medium -- Kubernetes configuration has many subtle correctness issues (resource limits, PVC sizing, network policies). Requires real cluster testing.

---

#### Task 4.9: Enterprise Documentation

**Description:** Write comprehensive documentation for all Phase 4 features: cost router configuration guide, agent IAM and security policy guide, distributed execution with Ray guide, NATS messaging configuration, dynamic subgraph patterns, TypeScript SDK reference, YAML agent definition reference, and Kubernetes deployment guide. Include architecture decision records (ADRs) for major design choices.

**Dependencies:** Tasks 4.1-4.8 (all Phase 4 features implemented)

**Estimated Effort:** 5 days

**Deliverables:**
- `docs/guides/cost-routing.md` -- Configuration, model tiers, budget enforcement
- `docs/guides/security.md` -- Agent IAM, tool ACLs, secret management, audit
- `docs/guides/distributed.md` -- Ray executor setup, resource allocation, fault tolerance
- `docs/guides/messaging.md` -- NATS JetStream configuration, pub/sub patterns
- `docs/guides/dynamic-workflows.md` -- DynamicNode, plan-and-execute patterns
- `docs/guides/typescript-sdk.md` -- SDK installation, usage, type generation
- `docs/guides/yaml-agents.md` -- YAML agent and workflow definition reference
- `docs/deployment/kubernetes.md` -- Complete K8s deployment guide
- `docs/adr/` -- Architecture Decision Records for major design choices
- All documentation builds without warnings in mkdocs

**Success Criteria / Definition of Done:**
- Each guide includes at least one complete working example
- Cost routing guide walks through configuring model tiers, setting budgets, and interpreting cost reports
- Security guide walks through defining agent identities, setting tool ACLs, managing secrets, and reading audit logs
- Distributed guide walks through setting up a Ray cluster, configuring distributed execution, and monitoring with Ray dashboard
- Kubernetes guide walks through deployment from scratch to running workflow
- ADRs document the "why" behind: event sourcing vs checkpointing, NATS vs Kafka, Ray vs Celery, pgvector vs dedicated vector DB
- mkdocs build succeeds with zero warnings

**Risk Level:** Low

---

## Progress Table

| Phase | Tasks | Status | Completed |
|-------|-------|--------|-----------|
| 1. Core Engine | 0/11 | Not started | - |
| 2. Differentiation | 0/11 | Not started | - |
| 3. Production Readiness | 0/10 | Not started | - |
| 4. Enterprise & Scale | 0/9 | Not started | - |

---

## Timeline Summary

| Phase | Weeks | Total Effort (days) | Key Risk |
|-------|-------|---------------------|----------|
| 1. Core Engine | 1-6 | 37 days | Graph engine execution model (medium) |
| 2. Differentiation | 7-12 | 41 days | Event sourcing correctness, MCP spec stability (medium) |
| 3. Production Readiness | 13-18 | 43 days | Multi-tier memory complexity, pgvector dependency (high) |
| 4. Enterprise & Scale | 19-26 | 51 days | Cost classification accuracy, IAM correctness, distributed state sync (high) |

**Total estimated effort:** 172 days

---

## Dependency Graph (Cross-Phase)

```
Phase 1: Core Engine
  Task 1.1 (Scaffolding) -----> Task 1.2 (Agent Protocol)
                          \---> Task 1.4 (State)
                          \---> Task 1.5 (LLM Providers)
                          \---> Task 1.9 (Logging)
  Task 1.2 -----> Task 1.3 (Graph Engine)
  Task 1.5 -----> Task 1.6 (Tools)
  Task 1.5 -----> Task 1.7 (ScriptedLLM)
  Task 1.3 + 1.9 -----> Task 1.8 (CLI)
  Tasks 1.2-1.7 -----> Task 1.10 (Examples)
  Tasks 1.2-1.10 -----> Task 1.11 (Docs)

Phase 2: Differentiation
  Phase 1 -----> Task 2.1 (Event Sourcing)
  Task 2.1 -----> Task 2.2 (SQLite) + Task 2.3 (PostgreSQL)
  Task 2.1 + 2.2 -----> Task 2.4 (HITL)
  Task 2.4 -----> Task 2.5 (Time Travel)
  Phase 1 + 2.1 -----> Task 2.6 (Rich Trace)
  Phase 1 + 2.1 -----> Task 2.7 (Handoff)
  Task 1.6 + 2.1 -----> Task 2.8 (MCP)
  Task 1.6 + 2.8 -----> Task 2.9 (Tool Registry)
  Task 1.5 -----> Task 2.10 (Google/Ollama)
  Tasks 2.4-2.7 -----> Task 2.11 (Advanced Examples)

Phase 3: Production Readiness
  Phase 2 -----> Task 3.1 (FastAPI)
  Task 1.9 + Phase 2 -----> Task 3.2 (OTel)
  Phase 1-2 -----> Task 3.3 (Redis)
  Tasks 2.2-2.3 + 3.3 -----> Task 3.4 (Memory)
  Task 1.7 -----> Task 3.5 (SimulatedLLM/FlakyLLM)
  Tasks 1.5 + 3.2 -----> Task 3.6 (Cost Tracking)
  Tasks 1.2 + 3.6 -----> Task 3.7 (Guardrails)
  Tasks 3.1 + 2.4 -----> Task 3.8 (WebSocket HITL)
  Tasks 3.1-3.3 -----> Task 3.9 (Docker Compose)
  Phases 1-2 + 3.5 -----> Task 3.10 (Benchmarks)

Phase 4: Enterprise & Scale
  Tasks 3.6 + 1.5 -----> Task 4.1 (Cost Router)
  Tasks 2.9 + 3.7 -----> Task 4.2 (Agent IAM)
  Phase 1 + Phase 2 -----> Task 4.3 (Ray)
  Phase 1 + 4.3 -----> Task 4.4 (NATS)
  Phase 1 -----> Task 4.5 (DynamicNode)
  Task 3.1 -----> Task 4.6 (TypeScript SDK)
  Tasks 1.2 + 1.3 + 4.2 -----> Task 4.7 (YAML Config)
  Tasks 3.9 + 4.3 + 4.4 -----> Task 4.8 (Kubernetes)
  Tasks 4.1-4.8 -----> Task 4.9 (Enterprise Docs)
```

---

## Risk Summary

| Risk Level | Count | Tasks |
|------------|-------|-------|
| High | 4 | Task 3.4 (Memory), Task 4.1 (Cost Router), Task 4.2 (Agent IAM), Task 4.3 (Ray), Task 4.5 (DynamicNode) |
| Medium | 12 | Tasks 1.3, 1.5, 2.1, 2.3, 2.4, 2.5, 2.6, 2.8, 3.1, 3.2, 3.7, 3.8, 4.4, 4.6, 4.8 |
| Low | 25 | All remaining tasks |

---

## Decision Log

| Decision | Rationale | Date |
|----------|-----------|------|
| Python 3.11+ minimum | Required for asyncio.TaskGroup, ExceptionGroup, tomllib | 2026-03-05 |
| asyncio default, Ray opt-in | Zero-infrastructure default; Ray for production scale only | 2026-03-05 |
| SQLite dev, PostgreSQL prod | Event-sourced state + progressive infrastructure | 2026-03-05 |
| Custom graph engine (not LangGraph dep) | Core value proposition IS the graph engine | 2026-03-05 |
| Event sourcing + reducers (dual model) | Events for audit/replay, reducers for merge semantics | 2026-03-05 |
| MCP-first tool integration | Standards-based, avoids proprietary connector library | 2026-03-05 |
| Security opt-in (dev mode all-access) | Avoid friction in development, enforce in production | 2026-03-05 |
