# Phase 2: Differentiation - Context

**Gathered:** 2026-03-07
**Status:** Ready for planning

<domain>
## Phase Boundary

Orchestra becomes visibly distinct from LangGraph through event-sourced persistence, time-travel debugging with a rich console renderer, first-class handoff protocol, MCP tool integration, and additional LLM provider adapters. All execution is local (no cloud agent hosting) -- developers download and run the framework on their machines, calling external LLM APIs for agent reasoning.

Tasks 2.1-2.11 from ROADMAP.md: event sourcing, SQLite backend, PostgreSQL backend, HITL interrupt/resume, time-travel debugging, Rich console trace, handoff protocol, MCP client, tool ACLs, Google/Ollama providers, advanced examples.

</domain>

<decisions>
## Implementation Decisions

### Persistence Model
- Event sourcing with periodic snapshots (hybrid approach)
- Events are the source of truth -- immutable, append-only records of every state transition (NodeStarted, StateUpdated, ToolCalled, LLMCalled, etc.)
- Snapshots are a performance optimization -- periodic full-state captures so restoration doesn't require replaying the entire event log
- Every workflow run is persisted automatically by default (batteries-included). Developer can disable with `persist=False`
- SQLite is the zero-config default backend; PostgreSQL is the production option

### Database Location
- Default SQLite database lives at `.orchestra/runs.db` in the project root
- `.orchestra/` directory auto-created on first run (like `.git/`)
- `.orchestra/` added to generated `.gitignore` template from `orchestra init`
- One database per project -- run history is project-scoped

### HITL (Human-in-the-Loop)
- Node-level interrupt parameters: `interrupt_before=True` and `interrupt_after=True` on `add_node()`
- No dedicated HITL node type -- interrupt mechanism + state modification on resume covers all use cases (approval gates, human input, quality checks)
- When interrupted, CLI shows a Rich-formatted panel with: paused node name, current state fields/values, and prompts for resume/modify/abort
- Resume API is programmatic first (`await workflow.resume(run_id, state_updates)`), CLI is one consumer. This enables Phase 3's FastAPI to expose resume endpoints
- Both `interrupt_before` and `interrupt_after` supported from day one

### Rich Console Trace
- On by default in dev environment. Production mode (`ORCHESTRA_ENV=prod`) disables it. Developer can override with `ORCHESTRA_TRACE=off`
- Live updating -- tree builds in real-time as nodes execute using Rich Live display. Spinner on active nodes, checkmark on completed
- Default is summary view per node: agent name, model, duration, token count, LLM API cost (e.g. '$0.003')
- Verbose mode available with `ORCHESTRA_TRACE=verbose` showing tool arguments, results, LLM snippets
- Per-node LLM API cost displayed inline, total cost at bottom of trace
- Color coding: green for success, yellow for HITL interrupts, red for errors

### MCP Integration
- Code-first API with optional config file override: `mcp = MCPClient('npx @modelcontextprotocol/server-filesystem')` in code, or `.orchestra/mcp.json` config file discovered automatically
- stdio transport is the priority (subprocess communication). SSE as a second transport
- MCP servers registered at workflow level. Agents opt-in to which tools they use (keeps agent boundaries clear)
- MCP tools are transparent to agents -- they look identical to native `@tool`-decorated tools. Agent sees name, description, and schema without knowing the source

### Claude's Discretion
- Event serialization format (JSON vs MessagePack)
- SQLite schema design (tables, indexes, WAL mode)
- PostgreSQL advisory lock and LISTEN/NOTIFY strategy
- Snapshot frequency (roadmap suggests every 50 events -- Claude can adjust)
- Time-travel CLI UX details (interactive command design)
- Handoff protocol internal data structures
- Tool ACL enforcement mechanism
- Google and Ollama provider adapter implementation details
- Rich trace tree layout specifics (indentation, truncation lengths)
- MCP config file schema

</decisions>

<specifics>
## Specific Ideas

- Framework runs locally -- developers download and run on their machines, calling LLM APIs externally. No cloud-hosted agent execution. Cost tracking is about LLM API spend, not compute costs.
- `.orchestra/` directory pattern mirrors `.git/` -- developers already understand this mental model
- Rich trace is the flagship DX feature -- "LangSmith in your terminal" positioning
- HITL resume must work both from terminal and programmatically to support Phase 3's FastAPI server

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ExecutionContext` (src/orchestra/core/context.py): Natural place to inject event emitter, HITL signals, and loop counters. Already carries `run_id`, `provider`, `config`.
- `LLMProvider` protocol (src/orchestra/core/protocols.py): Google and Ollama adapters must satisfy this. `@runtime_checkable` so conformance is verifiable.
- `HttpProvider` (src/orchestra/providers/http.py): Ollama adapter can extend or reuse this (Ollama is OpenAI-compatible). Google needs a new adapter.
- `AnthropicProvider` (src/orchestra/providers/anthropic.py): Reference for building non-OpenAI adapters (384 lines, full Messages API handling).
- `ToolRegistry` (src/orchestra/tools/registry.py): MCP tools register here. ACLs extend this with per-agent access control.
- `@tool` decorator and `ToolWrapper` (src/orchestra/tools/base.py): MCP tools should produce `ToolWrapper`-compatible objects so agents can't distinguish them.
- `structlog` logging (src/orchestra/observability/logging.py): Rich trace renderer subscribes to the same event stream, runs alongside structured logging.
- `TokenUsage` and cost tracking (src/orchestra/core/types.py, providers): Already computed per-agent-turn. Rich trace just displays what's already tracked.
- Error hierarchy (src/orchestra/core/errors.py): `UnreachableNodeError` exists but isn't raised yet -- can be wired up as part of this phase.

### Established Patterns
- Protocol-based extensibility: new backends (EventStore, CacheStore) should be `@runtime_checkable Protocol` classes
- Pydantic for all data models: events, checkpoints, HITL signals should be Pydantic `BaseModel` subclasses
- Frozen dataclasses for immutable structures: events are immutable -- `@dataclass(frozen=True)` is the right pattern
- Three-part error messages: new error types (PersistenceError, HITLError, MCPError) follow "what/where/fix" format
- `__init__.py` barrel files with explicit `__all__` exports

### Integration Points
- `CompiledGraph.run()` (src/orchestra/core/compiled.py): Event emission hooks go here -- emit events at node start, completion, state update, error
- `BaseAgent.run()` (src/orchestra/core/agent.py): LLMCalled and ToolCalled events emitted from the agent's tool-calling loop
- `runner.run()` (src/orchestra/core/runner.py): Top-level orchestration -- initializes event store, creates Rich trace renderer, handles HITL interrupt signals
- `WorkflowGraph.add_node()` (src/orchestra/core/graph.py): Accepts new `interrupt_before`/`interrupt_after` parameters
- `pyproject.toml`: New dependencies -- `aiosqlite`, `asyncpg` (optional), `rich` (already present via typer)

</code_context>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope.

</deferred>

---

*Phase: 02-differentiation*
*Context gathered: 2026-03-07*
