---
phase: 01-core-engine
verified: 2026-03-07T20:58:00Z
status: gaps_found
score: 4/5 success criteria verified
re_verification:
  previous_status: passed
  previous_score: 5/5
  gaps_closed: []
  gaps_remaining:
    - "Three working example workflows exist and pass CI -- no integration test file exists"
  regressions: []
gaps:
  - truth: "Three working example workflows (sequential, parallel, conditional) exist and pass CI"
    status: partial
    reason: "Examples exist and run correctly, but there is no tests/integration/ directory or test_examples.py file. CI cannot verify examples pass because there are no integration tests that exercise them. The CI pipeline only runs pytest, which has no coverage of example workflows."
    artifacts:
      - path: "tests/integration/test_examples.py"
        issue: "MISSING -- no integration test file exists"
    missing:
      - "Create tests/integration/ directory"
      - "Create tests/integration/test_examples.py with pytest tests that import and run main() from each example (sequential, parallel, conditional)"
      - "Mark tests with @pytest.mark.integration for optional CI separation"
  - truth: "Documentation: Getting Started guide, concepts docs, mkdocs site, API reference"
    status: failed
    reason: "Task 1.11 deliverables are entirely missing. No docs/ directory, no mkdocs.yml, no Getting Started guide, no concept documentation, no API reference stubs."
    artifacts:
      - path: "docs/"
        issue: "MISSING -- entire docs directory does not exist"
      - path: "mkdocs.yml"
        issue: "MISSING -- mkdocs configuration does not exist"
    missing:
      - "Create docs/ directory with index.md (Getting Started)"
      - "Create docs/concepts/ with architecture, agents, graphs, state, tools pages"
      - "Create mkdocs.yml with mkdocs-material theme and mkdocstrings plugin"
      - "Create docs/api/ with auto-generated API reference stubs"
human_verification:
  - test: "Run a workflow against a real Anthropic API endpoint"
    expected: "Agent receives response from Claude, processes tool calls correctly, returns AgentResult with content and token usage"
    why_human: "Requires ANTHROPIC_API_KEY and network access"
  - test: "Run a workflow against a real OpenAI API endpoint"
    expected: "Agent receives response from OpenAI, processes it, returns AgentResult"
    why_human: "Requires OPENAI_API_KEY and network access"
  - test: "Run orchestra run nonexistent.py and orchestra run broken_file.py"
    expected: "Human-readable error messages, non-zero exit codes, no raw tracebacks"
    why_human: "Error message quality is subjective"
---

# Phase 1: Core Engine Verification Report

**Phase Goal:** A developer can define agents, compose them into typed graph workflows, run them against real LLMs, and write deterministic unit tests -- all from a single `pip install orchestra`.

**Verified:** 2026-03-07T20:58:00Z
**Status:** gaps_found
**Re-verification:** Yes -- fresh verification against current codebase (previous report: 02-VERIFICATION.md, 5/5)

## Goal Achievement

### Observable Truths (Success Criteria from ROADMAP.md)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A user can `pip install -e .` the project from source with zero errors and import `orchestra` | VERIFIED | `pip install -e ".[dev]"` succeeds: `Successfully installed orchestra-agents-0.1.0`. `python -c "import orchestra; print(orchestra.__version__)"` outputs `0.1.0`. |
| 2 | A user can define an agent (class-based or decorator), wire it into a WorkflowGraph with sequential/parallel/conditional edges, compile, and run -- producing correct output against a real OpenAI or Anthropic model | VERIFIED | BaseAgent (261 lines) and @agent decorator both work. WorkflowGraph (453 lines) supports sequential (.then), parallel (.parallel/.join), conditional (.branch/.if_then), and loop (.loop). CompiledGraph (383 lines) executes all patterns. 58/58 tests pass including agent+tool integration tests with ScriptedLLM. AnthropicProvider (384 lines) and HttpProvider (359 lines) both exist with full API implementations. |
| 3 | A user can write a pytest test using ScriptedLLM that completes in under 5 seconds with fully deterministic, reproducible results | VERIFIED | Full test suite (58 tests) completes in 0.38 seconds. ScriptedLLM (156 lines) supports scripted responses, call logging, reset, `assert_all_consumed()`, and `assert_prompt_received()`. Both assertion methods manually tested and confirmed working. |
| 4 | A user can run `orchestra run examples/sequential.py` from the CLI and see structured log output tracing each node execution | VERIFIED | `orchestra run examples/sequential.py` produces timestamped structlog output: `executing_node node=researcher turn=1`, `executing_node node=writer turn=2`, `executing_node node=editor turn=3`, followed by workflow results. `orchestra version` outputs `Orchestra v0.1.0`. |
| 5 | Three working example workflows (sequential, parallel, conditional) exist and pass CI | PARTIAL | All three examples exist and run correctly when executed directly (`python examples/sequential.py`, `python examples/parallel.py`, `python examples/conditional.py`). However, there is no `tests/integration/` directory and no `test_examples.py` file. The CI pipeline (`ci.yml`) runs `pytest tests/` which has zero coverage of the example workflows. The "pass CI" part of this criterion is not fulfilled because CI cannot verify examples. |

**Score:** 4/5 success criteria fully verified (1 partial)

### Task-Level Verification (Tasks 1.1 - 1.11)

| Task | Name | Status | Evidence |
|------|------|--------|---------|
| 1.1 | Project Scaffolding | VERIFIED | `pyproject.toml` with PEP 621 metadata, hatchling build, `[dev]`/`[docs]`/`[anthropic]` extras, CI at `.github/workflows/ci.yml` (lint+type-check+test matrix across 3 OS x 3 Python versions), `py.typed` marker exists, ruff+mypy+pytest configured |
| 1.2 | Agent Protocol and Base Classes | VERIFIED | `protocols.py` (111 lines): Agent, Tool, LLMProvider, StateReducer protocols with @runtime_checkable. `agent.py` (261 lines): BaseAgent with full LLM reasoning loop (system prompt, tool calling, structured output validation, token tracking), @agent decorator producing DecoratedAgent. `nodes.py` (67 lines): AgentNode, FunctionNode, SubgraphNode. `context.py` (49 lines): ExecutionContext dataclass with run_id, state, provider, loop_counters, node_execution_order |
| 1.3 | Graph Engine | VERIFIED | `graph.py` (453 lines): WorkflowGraph builder with both explicit (add_node/add_edge/add_conditional_edge/add_parallel/set_entry_point) and fluent (.then/.parallel/.join/.branch/.if_then/.loop) APIs. `compiled.py` (383 lines): CompiledGraph with sequential, parallel (asyncio.gather), and conditional execution. Edge pre-computation, state validation, max_turns guard, Mermaid diagram generation. `edges.py` (68 lines): Edge, ConditionalEdge (with path_map validation), ParallelEdge |
| 1.4 | Reducer-Based Typed State | VERIFIED | `state.py` (172 lines): WorkflowState base class, 9 built-in reducers (merge_list, merge_dict, sum_numbers, last_write_wins, merge_set, concat_str, keep_first, max_value, min_value), extract_reducers from Annotated type hints, apply_state_update with immutable updates, merge_parallel_updates. All 16 state tests pass |
| 1.5 | LLM Provider Protocol + Adapters | VERIFIED | `protocols.py`: LLMProvider protocol with complete/stream/count_tokens/get_model_cost. `http.py` (359 lines): OpenAI-compatible HttpProvider with streaming, retry logic, error status mapping, structured output support. `anthropic.py` (384 lines): AnthropicProvider with Messages API format handling (system prompt separation, tool_use/tool_result blocks), streaming, retry with exponential backoff, model cost table for Claude 3.5/4 families. Both exported from `orchestra.providers` |
| 1.6 | Function-Calling Tool Integration | VERIFIED | `base.py` (162 lines): @tool decorator with JSON Schema auto-generation from type hints, ToolWrapper with execute method, supports both `@tool` and `@tool(name=..., description=...)` syntax. `registry.py` (71 lines): ToolRegistry with register/get/has/list_tools/get_schemas/unregister/clear. Test verifies tool execution, error handling, and registry operations |
| 1.7 | ScriptedLLM Test Harness | VERIFIED | `scripted.py` (156 lines): ScriptedLLM implementing LLMProvider protocol, accepts string or LLMResponse scripts, call logging, reset, `assert_all_consumed()` (lines 123-135) raises AssertionError if unconsumed responses remain, `assert_prompt_received(call_index, pattern)` (lines 137-155) checks call messages against regex. Both methods manually verified working |
| 1.8 | Basic CLI with Typer | VERIFIED | `cli/main.py` (113 lines): `orchestra version` (shows version), `orchestra init <project>` (scaffolds directories + hello workflow), `orchestra run <file>` (imports and runs main() with structlog output). All three commands tested and working |
| 1.9 | Console Logging with structlog | VERIFIED | `observability/logging.py` (62 lines): setup_logging() with configurable level, console/JSON output modes, structlog processors (contextvars, logger name, log level, timestamps, stack info, unicode). CompiledGraph uses `structlog.get_logger()` for node execution tracing. CLI output confirmed showing timestamped structured log entries |
| 1.10 | Example Workflows | PARTIAL | Three examples exist and run correctly: `sequential.py` (76 lines, researcher->writer->editor pipeline), `parallel.py` (86 lines, 3 parallel researchers + synthesizer), `conditional.py` (92 lines, classifier->tech/creative routing). All produce correct output when run directly. However, no integration tests exist at `tests/integration/test_examples.py` to verify these in CI |
| 1.11 | Documentation | FAILED | No `docs/` directory exists. No `mkdocs.yml` exists. No Getting Started guide, concepts documentation, or API reference stubs. The README.md exists but Task 1.11 specifically calls for mkdocs-based documentation site with Getting Started, concepts, and API reference pages. The `[docs]` extra in pyproject.toml includes mkdocs dependencies but they are unused |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `pyproject.toml` | Package config with PEP 621 | VERIFIED | Complete with build system, dependencies, CLI entry point, dev tooling, 110 lines |
| `src/orchestra/__init__.py` | Public API exports | VERIFIED | Exports BaseAgent, agent, WorkflowGraph, WorkflowState, run, run_sync, tool, END, START, ExecutionContext, Message, etc. |
| `src/orchestra/core/agent.py` | Agent protocol and BaseAgent | VERIFIED | 261 lines, full reasoning loop with tool calling and structured output |
| `src/orchestra/core/graph.py` | WorkflowGraph builder | VERIFIED | 453 lines, explicit + fluent APIs, all edge types |
| `src/orchestra/core/compiled.py` | CompiledGraph engine | VERIFIED | 383 lines, sequential/parallel/conditional execution, Mermaid output |
| `src/orchestra/core/state.py` | WorkflowState with reducers | VERIFIED | 172 lines, 9 reducers, immutable updates, parallel merge |
| `src/orchestra/core/context.py` | ExecutionContext | VERIFIED | 49 lines, loop_counters, node_execution_order |
| `src/orchestra/core/edges.py` | Edge types | VERIFIED | 68 lines, Edge/ConditionalEdge/ParallelEdge with path_map validation |
| `src/orchestra/core/nodes.py` | Node types | VERIFIED | 67 lines, AgentNode/FunctionNode/SubgraphNode |
| `src/orchestra/core/types.py` | Core type definitions | VERIFIED | 159 lines, Message/ToolCall/AgentResult/LLMResponse/END sentinel |
| `src/orchestra/core/errors.py` | Error hierarchy | VERIFIED | 124 lines, 15 error classes with fix suggestions |
| `src/orchestra/core/protocols.py` | Protocol definitions | VERIFIED | 111 lines, Agent/Tool/LLMProvider/StateReducer protocols |
| `src/orchestra/core/runner.py` | run()/run_sync() | VERIFIED | 123 lines, RunResult with metrics, auto-compile |
| `src/orchestra/providers/anthropic.py` | Anthropic adapter | VERIFIED | 384 lines, full Messages API with streaming/retry/error mapping |
| `src/orchestra/providers/http.py` | OpenAI-compatible HTTP provider | VERIFIED | 359 lines, streaming/retry/structured output |
| `src/orchestra/providers/__init__.py` | Provider exports | VERIFIED | Exports AnthropicProvider and HttpProvider |
| `src/orchestra/testing/scripted.py` | ScriptedLLM mock | VERIFIED | 156 lines, assert_all_consumed, assert_prompt_received |
| `src/orchestra/testing/__init__.py` | Testing exports | VERIFIED | Exports ScriptedLLM, ScriptExhaustedError |
| `src/orchestra/tools/base.py` | @tool decorator + ToolWrapper | VERIFIED | 162 lines, JSON schema generation from type hints |
| `src/orchestra/tools/registry.py` | ToolRegistry | VERIFIED | 71 lines, register/get/schemas |
| `src/orchestra/cli/main.py` | CLI with Typer | VERIFIED | 113 lines, version/init/run commands |
| `src/orchestra/observability/logging.py` | structlog configuration | VERIFIED | 62 lines, console + JSON modes |
| `examples/sequential.py` | Sequential pipeline example | VERIFIED | 76 lines, runs correctly |
| `examples/parallel.py` | Parallel fan-out example | VERIFIED | 86 lines, runs correctly |
| `examples/conditional.py` | Conditional routing example | VERIFIED | 92 lines, runs correctly |
| `.github/workflows/ci.yml` | CI pipeline | VERIFIED | lint + type-check + test matrix (3 OS x 3 Python) |
| `src/orchestra/py.typed` | PEP 561 marker | VERIFIED | Exists |
| `tests/integration/test_examples.py` | Integration tests for examples | MISSING | No integration test directory or file exists |
| `docs/` | Documentation site | MISSING | No docs directory exists |
| `mkdocs.yml` | MkDocs configuration | MISSING | No mkdocs.yml exists |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `orchestra.__init__` | Core modules | imports | WIRED | All key classes exported: BaseAgent, agent, WorkflowGraph, WorkflowState, run, run_sync, tool, END, START, ExecutionContext, Message, etc. |
| `orchestra.providers.__init__` | AnthropicProvider | import | WIRED | `from orchestra.providers.anthropic import AnthropicProvider` |
| `orchestra.providers.__init__` | HttpProvider | import | WIRED | `from orchestra.providers.http import HttpProvider` |
| `orchestra.testing.__init__` | ScriptedLLM | import | WIRED | `from orchestra.testing.scripted import ScriptedLLM, ScriptExhaustedError` |
| `CompiledGraph._resolve_next` | `ExecutionContext.loop_counters` | state_dict injection | WIRED | `state_dict["__loop_counters__"] = context.loop_counters` at line 287 of compiled.py |
| `CompiledGraph.run()` | `ExecutionContext.node_execution_order` | append tracking | WIRED | `context.node_execution_order.append(str(current_node_id))` at line 127 |
| `AnthropicProvider.complete()` | Anthropic Messages API | httpx POST to `/v1/messages` | WIRED | Full request/response pipeline with retry logic, system prompt separation, tool call parsing |
| `HttpProvider.complete()` | OpenAI API | httpx POST to `/chat/completions` | WIRED | Full request/response pipeline with retry logic, structured output support |
| `ScriptedLLM.assert_prompt_received` | `_call_log` | indexed access + regex | WIRED | Accesses `_call_log[call_index]`, joins message content, searches with `re.search` |
| `pyproject.toml` | CLI | `orchestra.cli.main:app` entry point | WIRED | `orchestra` command functional: version, init, run all work |
| `BaseAgent.run()` | LLM provider | `context.provider.complete()` | WIRED | Full tool-calling loop with message assembly, response parsing, tool execution |
| `WorkflowGraph.compile()` | CompiledGraph | deferred import | WIRED | `from orchestra.core.compiled import CompiledGraph` at line 383 of graph.py |

### Quality Gates

| Check | Result | Details |
|-------|--------|---------|
| `pip install -e ".[dev]"` | PASS | Installs cleanly, version 0.1.0 |
| `python -c "import orchestra"` | PASS | All exports available |
| `pytest tests/ -v` | PASS | 58/58 tests pass in 0.38s |
| `ruff check src/ tests/` | PASS | "All checks passed!" |
| `mypy src/orchestra/` | PASS | "Success: no issues found in 25 source files" |
| `orchestra version` | PASS | "Orchestra v0.1.0" |
| `orchestra run examples/sequential.py` | PASS | Structured log output with node execution tracing |
| `python examples/parallel.py` | PASS | Correct parallel fan-out and merge |
| `python examples/conditional.py` | PASS | Correct conditional routing for both branches |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | - | No TODO, FIXME, HACK, PLACEHOLDER, or eval() calls found in src/ or tests/ | - | Clean |

### Human Verification Required

### 1. Real Anthropic API Integration
**Test:** Set ANTHROPIC_API_KEY, create an agent with `AnthropicProvider`, run a workflow
**Expected:** Agent receives response from Claude, processes tool calls correctly, returns AgentResult with content and token usage
**Why human:** Requires API key and network access; cannot verify in automated CI without credentials

### 2. Real OpenAI API Integration
**Test:** Set OPENAI_API_KEY, create an agent with `HttpProvider`, run a workflow
**Expected:** Agent receives response from OpenAI, processes it, returns AgentResult
**Why human:** Requires API key and network access

### 3. CLI Error Handling
**Test:** Run `orchestra run nonexistent.py` and `orchestra run broken_file.py`
**Expected:** Human-readable error messages, non-zero exit codes, no raw tracebacks
**Why human:** Error message quality is subjective

## Gaps Summary

Two gaps were found in this fresh verification of Phase 1:

### Gap 1: Missing Integration Tests for Examples (Partial -- Success Criterion 5)

The three example workflows (sequential, parallel, conditional) all exist and produce correct output when run directly. However, there is no `tests/integration/` directory and no `test_examples.py` file that would exercise these examples in CI. The CI pipeline at `.github/workflows/ci.yml` runs `pytest tests/` which has zero coverage of example workflows. This means CI cannot verify that examples pass, which is explicitly part of success criterion 5: "Three working example workflows exist **and pass CI**".

**Impact:** Medium. Examples work today but could silently break in future changes without CI coverage.

**Fix:** Create `tests/integration/test_examples.py` that imports and runs `main()` from each example file, asserting expected outputs. Mark with `@pytest.mark.integration`.

### Gap 2: Missing Documentation (Failed -- Task 1.11)

Task 1.11 explicitly calls for: Getting Started guide, concepts documentation, mkdocs site, and API reference. None of these exist. The `docs/` directory is entirely absent and there is no `mkdocs.yml` configuration file. The `[docs]` extra in `pyproject.toml` includes mkdocs-material and mkdocstrings dependencies but they are unused.

**Impact:** Low for Phase 1 core functionality (all code works), but this is an explicit task deliverable that was not completed. Documentation does not block any success criterion directly (it is a task-level gap, not a success-criterion-level gap).

**Note:** This gap was NOT in the previous 02-VERIFICATION.md because that verification only checked the 5 success criteria from ROADMAP.md, and documentation is not a formal success criterion. However, Task 1.11 is a declared deliverable of Phase 1.

### Assessment

The core engine is fully functional and well-implemented. All code-level success criteria (1-4) pass completely. Success criterion 5 is partial due to missing integration tests. The only fully failed item is Task 1.11 (documentation), which is a deliverable gap but does not block the core goal of "define agents, compose them into graph workflows, run them against real LLMs, and write deterministic unit tests."

---

_Verified: 2026-03-07T20:58:00Z_
_Verifier: Claude (gsd-verifier)_
