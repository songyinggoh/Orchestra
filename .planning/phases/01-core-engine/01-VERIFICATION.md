---
phase: 01-core-engine
verified: 2026-03-07T03:35:00Z
status: gaps_found
score: 3/5 success criteria verified
gaps:
  - truth: "A user can define an agent (class-based or decorator), wire it into a WorkflowGraph with sequential/parallel/conditional edges, compile, and run -- producing correct output against a real OpenAI or Anthropic model"
    status: partial
    reason: "No dedicated Anthropic adapter exists. Only a generic OpenAI-compatible HttpProvider is implemented. While it can work with OpenAI endpoints, running against Anthropic requires a separate adapter due to different API format. Additionally, no real LLM integration test exists."
    artifacts:
      - path: "src/orchestra/providers/anthropic.py"
        issue: "MISSING - Task 1.5 deliverable (Anthropic adapter) does not exist"
      - path: "src/orchestra/providers/openai.py"
        issue: "MISSING - Task 1.5 deliverable (OpenAI adapter) replaced by generic http.py"
    missing:
      - "Dedicated AnthropicProvider adapter (Anthropic API uses a different format than OpenAI)"
      - "Integration test demonstrating end-to-end agent workflow against a real LLM (even if gated by API key availability)"
  - truth: "All unit tests pass, all type checks pass, and linting is clean"
    status: failed
    reason: "4 out of 58 tests fail (loop/parallel fluent API bugs), 2 ruff lint errors, 10 mypy type errors"
    artifacts:
      - path: "src/orchestra/core/graph.py"
        issue: "loop() fluent method injects __loop_*_count__ key into state updates but typed WorkflowState rejects unknown fields"
      - path: "tests/unit/test_core.py"
        issue: "TestFluentAPI::test_fluent_parallel_join uses non-async function causing 'await' error; 3 loop tests fail due to state validation"
      - path: "src/orchestra/core/agent.py"
        issue: "Ruff E402: module-level import not at top of file (line 24)"
      - path: "tests/unit/test_core.py"
        issue: "Ruff E501: line too long at line 477"
    missing:
      - "Fix loop() to handle internal counter state without violating typed state validation"
      - "Fix test_fluent_parallel_join to use async function"
      - "Fix ruff lint errors (import ordering in agent.py, line length in test)"
      - "Fix 10 mypy type errors across 6 files"
---

# Phase 1: Core Engine Verification Report

**Phase Goal:** A developer can define agents, compose them into typed graph workflows, run them against real LLMs, and write deterministic unit tests -- all from a single `pip install orchestra`.

**Verified:** 2026-03-07T03:35:00Z
**Status:** gaps_found
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths (Success Criteria from ROADMAP.md)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A user can `pip install -e .` the project from source with zero errors and import `orchestra` | VERIFIED | `python -c "import orchestra; print(orchestra.__version__)"` outputs `0.1.0`. pyproject.toml is well-formed with hatchling build system, src layout, PEP 561 py.typed marker present. |
| 2 | A user can define an agent (class-based or decorator), wire it into a WorkflowGraph with sequential/parallel/conditional edges, compile, and run -- producing correct output against a real OpenAI or Anthropic model | PARTIAL | Class-based (BaseAgent) and decorator (@agent) agent definitions work. WorkflowGraph supports sequential, parallel, conditional edges via both explicit and fluent APIs. Execution engine works with ScriptedLLM. However: no dedicated Anthropic adapter exists (only generic OpenAI-compatible HttpProvider), and no integration test demonstrates real LLM execution. |
| 3 | A user can write a pytest test using ScriptedLLM that completes in under 5 seconds with fully deterministic, reproducible results | VERIFIED | ScriptedLLM implemented at `src/orchestra/testing/scripted.py`. Full test suite (54 passing tests) completes in 0.38s. Tests including ScriptedLLM-based agent integration tests are deterministic. |
| 4 | A user can run `orchestra run examples/sequential.py` from the CLI and see structured log output tracing each node execution | VERIFIED | `orchestra run examples/sequential.py` produces timestamped structlog output showing each node execution (researcher turn=1, writer turn=2, editor turn=3) plus workflow results. CLI is registered in pyproject.toml and installed as a console script. |
| 5 | Three working example workflows (sequential, parallel, conditional) exist and pass CI | PARTIAL | Three examples exist (sequential.py, parallel.py, conditional.py) plus a bonus handoff_basic.py. All execute successfully when run directly. However, no `tests/integration/test_examples.py` exists, so they are not tested in CI. Also, 4 unit tests fail and linting/type-checking are not clean, so CI would fail. |

**Score:** 3/5 success criteria fully verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `pyproject.toml` | Package configuration with PEP 621 | VERIFIED | Complete with build system, dependencies, optional deps, CLI entry point, dev tooling config |
| `src/orchestra/__init__.py` | Public API exports with version | VERIFIED | Exports BaseAgent, agent, WorkflowGraph, WorkflowState, run, run_sync, tool, END, START, etc. |
| `src/orchestra/core/agent.py` | Agent protocol, BaseAgent, @agent decorator | VERIFIED | 260 lines. Full agent reasoning loop with tool calling, structured output, token tracking |
| `src/orchestra/core/graph.py` | WorkflowGraph builder | VERIFIED | 458 lines. Both explicit API (add_node/add_edge) and fluent API (.then/.parallel/.branch/.loop) |
| `src/orchestra/core/compiled.py` | CompiledGraph execution engine | VERIFIED | 382 lines. Sequential, parallel, conditional execution with state merging |
| `src/orchestra/core/state.py` | WorkflowState with Annotated reducers | VERIFIED | 172 lines. 9 built-in reducers, extract_reducers, apply_state_update, merge_parallel_updates |
| `src/orchestra/core/types.py` | Core type definitions | VERIFIED | Message, ToolCall, AgentResult, LLMResponse, StreamChunk, TokenUsage, END sentinel |
| `src/orchestra/core/errors.py` | Error hierarchy | VERIFIED | 25 error types organized by domain (graph, agent, provider, tool, state) |
| `src/orchestra/core/context.py` | ExecutionContext | VERIFIED | Dataclass with run_id, state, provider, tool_registry, config |
| `src/orchestra/core/edges.py` | Edge types | VERIFIED | Edge, ConditionalEdge (with resolve), ParallelEdge |
| `src/orchestra/core/nodes.py` | Node types | VERIFIED | AgentNode, FunctionNode, SubgraphNode |
| `src/orchestra/core/runner.py` | run() and run_sync() | VERIFIED | RunResult model, async run with timing/metrics, sync wrapper |
| `src/orchestra/core/protocols.py` | Protocol definitions | VERIFIED | Agent, Tool, LLMProvider, StateReducer -- all @runtime_checkable |
| `src/orchestra/providers/openai.py` | OpenAI adapter | MISSING | Replaced by generic `http.py` (OpenAI-compatible). Works for OpenAI but not for Anthropic API format. |
| `src/orchestra/providers/anthropic.py` | Anthropic adapter | MISSING | Not implemented. pyproject.toml lists anthropic as optional dep but no adapter exists. |
| `src/orchestra/providers/http.py` | Generic HTTP provider | VERIFIED | 358 lines. Full OpenAI-compatible HTTP provider with retry, error handling, streaming, cost estimation |
| `src/orchestra/testing/scripted.py` | ScriptedLLM mock | VERIFIED | 121 lines. Returns scripted responses, call logging, reset. Missing `assert_all_consumed()` and `assert_prompt_received()` helpers. |
| `src/orchestra/tools/base.py` | @tool decorator and ToolWrapper | VERIFIED | 162 lines. Auto JSON schema from type hints, execute with error handling |
| `src/orchestra/tools/registry.py` | ToolRegistry | VERIFIED | 71 lines. Register, get, list, schemas, unregister |
| `src/orchestra/cli/main.py` | CLI with Typer | VERIFIED | 114 lines. `version`, `init`, `run` commands. All functional. |
| `src/orchestra/observability/logging.py` | structlog configuration | VERIFIED | 62 lines. setup_logging with console/JSON modes |
| `examples/sequential.py` | Sequential pipeline example | VERIFIED | 77 lines. Researcher -> Writer -> Editor with typed state |
| `examples/parallel.py` | Parallel fan-out example | VERIFIED | 87 lines. 3 parallel researchers -> synthesizer with merge_dict reducer |
| `examples/conditional.py` | Conditional routing example | VERIFIED | 93 lines. Classifier -> technical/creative writer with conditional edge |
| `.github/workflows/ci.yml` | CI pipeline | VERIFIED | Lint, type-check, test jobs. Matrix: 3 OS x 3 Python versions |
| `tests/integration/test_examples.py` | Example integration tests | MISSING | No integration test directory exists |
| `docs/` | Documentation site | MISSING | No docs directory exists (Task 1.11 not started) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `orchestra.__init__` | Core modules | imports | WIRED | All key classes exported: BaseAgent, agent, WorkflowGraph, WorkflowState, run, run_sync, tool |
| `BaseAgent.run()` | LLM provider | `context.provider.complete()` | WIRED | Full tool-calling loop implemented |
| `CompiledGraph.run()` | Node execution | `_execute_node()` -> `_execute_agent_node()` / `FunctionNode.__call__()` | WIRED | Dispatches by node type, handles state updates |
| `CompiledGraph.run()` | State reducers | `apply_state_update()` with `extract_reducers()` | WIRED | Annotated reducers extracted at compile time, applied on each state update |
| `WorkflowGraph.compile()` | CompiledGraph | `_validate()` then constructor | WIRED | Validation checks entry point, node existence, edge targets |
| `pyproject.toml` | CLI | `orchestra.cli.main:app` entry point | WIRED | `orchestra` command installed and functional on PATH |
| `ScriptedLLM` | LLMProvider protocol | structural subtyping | WIRED | Implements complete(), stream(), count_tokens(), get_model_cost() |
| `HttpProvider` | LLMProvider protocol | structural subtyping | WIRED | Implements complete(), stream(), count_tokens(), get_model_cost() |
| `@tool` decorator | ToolWrapper | `_generate_parameters_schema()` | WIRED | JSON schema auto-generated from function signatures |
| `Agent` | Tool execution | `BaseAgent._execute_tool()` | WIRED | Looks up tool by name, calls tool.execute(), returns ToolResult |

### Requirements Coverage

Based on ROADMAP.md Tasks 1.1 through 1.11:

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|----------|
| Task 1.1 | Project Scaffolding | SATISFIED | pyproject.toml, src layout, CI, dev tooling all present |
| Task 1.2 | Agent Protocol and Base Classes | SATISFIED | BaseAgent, @agent decorator, ExecutionContext, Protocol definitions |
| Task 1.3 | Graph Engine | MOSTLY SATISFIED | WorkflowGraph + CompiledGraph work for sequential/parallel/conditional. Loop fluent API has a bug with typed state. |
| Task 1.4 | Reducer-Based Typed State | SATISFIED | 9 reducers, Annotated extraction, apply_state_update, merge_parallel_updates |
| Task 1.5 | LLM Provider Protocol + Adapters | PARTIAL | LLMProvider Protocol defined. Generic HttpProvider works for OpenAI. Dedicated OpenAI and Anthropic adapters are missing per task spec. |
| Task 1.6 | Function-Calling Tool Integration | SATISFIED | @tool decorator, ToolWrapper, ToolRegistry, JSON schema generation, agent tool loop |
| Task 1.7 | ScriptedLLM Test Harness | MOSTLY SATISFIED | Core ScriptedLLM works. Missing `assert_all_consumed()` and `assert_prompt_received()` assertion helpers specified in task deliverables. |
| Task 1.8 | CLI with Typer | SATISFIED | `orchestra version`, `orchestra init`, `orchestra run` all work |
| Task 1.9 | Console Logging | SATISFIED | structlog with console/JSON modes, get_logger |
| Task 1.10 | Example Workflows | MOSTLY SATISFIED | 3 examples work (+ bonus handoff). Missing integration tests (`tests/integration/test_examples.py`) |
| Task 1.11 | Documentation | NOT STARTED | No `docs/` directory, no mkdocs.yml, no getting-started guide |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `src/orchestra/core/agent.py` | 24 | E402: import not at top of file | Warning | Lint failure in CI |
| `src/orchestra/core/graph.py` | 64 | E402: delayed import of SubgraphNode | Info | Intentional circular import avoidance, but lint error |
| `src/orchestra/core/compiled.py` | 216 | mypy no-redef: `agent_input` redefined | Warning | Type safety concern |
| `tests/unit/test_core.py` | 477 | E501: line too long (107 > 100) | Warning | Lint failure in CI |
| `src/orchestra/core/graph.py` | 342-368 | loop() method injects internal `__loop_*_count__` key | Blocker | Breaks typed state validation, causes 3 test failures |
| `tests/unit/test_core.py` | test_fluent_parallel_join | Non-async function wrapped as FunctionNode | Blocker | Causes "object dict can't be used in 'await' expression" failure |

### Human Verification Required

### 1. Real LLM Integration
**Test:** Set OPENAI_API_KEY, run a workflow with BaseAgent against actual OpenAI API
**Expected:** Agent receives response from OpenAI, processes it, returns AgentResult with content and token usage
**Why human:** Requires API key and network access, cannot verify programmatically in CI without credentials

### 2. Anthropic API Compatibility
**Test:** Verify whether HttpProvider can be configured to work with Anthropic's API endpoint
**Expected:** Anthropic uses a different API format (not OpenAI-compatible), so HttpProvider should fail or produce incorrect results
**Why human:** Requires Anthropic API key and understanding of API format differences

### 3. CLI Error Handling
**Test:** Run `orchestra run nonexistent.py` and `orchestra run broken_file.py`
**Expected:** Human-readable error messages, non-zero exit codes, no raw tracebacks
**Why human:** Error message quality is subjective

## Gaps Summary

Phase 1 has strong foundational implementation. The core graph engine, agent system, typed state with reducers, tool system, and ScriptedLLM testing harness are all substantive and functional. The 3 example workflows run correctly.

**Two gaps block the "passed" status:**

1. **Test/lint/type failures (Blocker):** 4 test failures (loop fluent API + parallel join test bug), 2 ruff errors, 10 mypy errors. Success Criterion #5 explicitly requires "all unit tests pass, all type checks pass, and linting is clean." This is a hard requirement.

2. **Missing Anthropic adapter (Partial):** Success Criterion #2 mentions "producing correct output against a real OpenAI or Anthropic model." While the generic HttpProvider covers OpenAI, there is no Anthropic adapter, and Anthropic's API format differs from OpenAI's, so the HttpProvider cannot serve as a drop-in replacement. The ROADMAP Task 1.5 explicitly lists `src/orchestra/providers/anthropic.py` as a deliverable.

**Additional gaps (lower severity):**
- ScriptedLLM missing `assert_all_consumed()` and `assert_prompt_received()` helpers (Task 1.7)
- No integration tests for examples (Task 1.10)
- Documentation not started (Task 1.11) -- though this may be acceptable as a "last task" that was planned but not yet executed
- pyproject.toml package name is "orchestra-agents" not "orchestra" (minor naming inconsistency with goal statement)

---

_Verified: 2026-03-07T03:35:00Z_
_Verifier: Claude (gsd-verifier)_
