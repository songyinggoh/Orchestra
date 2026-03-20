# Phase 5: No-Code Auto-Discovery Layer Summary

**One-liner:** Convention-based project scanning that discovers @tool functions, YAML agents, and YAML workflows, wired into `orchestra up` and `orchestra validate` CLI commands with hot-reload support.

## Completed Tasks

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| T-5.1 | ProjectConfig schema | 535d2d3 | `discovery/config.py`, `discovery/errors.py` |
| T-5.2 | Tool discovery | 67dc5ee | `discovery/tool_discovery.py` |
| T-5.3 | Agent loader | a6f36e9 | `discovery/agent_loader.py` |
| T-5.4 | Workflow loader | 1ef2be6 | `discovery/workflow_loader.py` |
| T-5.5 | ProjectScanner | 0ef1d11 | `discovery/scanner.py` |
| T-5.6 | `orchestra up` command | f5c89e5 | `cli/main.py` (up command) |
| T-5.7 | Enhanced `orchestra init` | c29d314 | `cli/main.py` (init rewrite) |
| T-5.8 | Validation & error reporting | 50e1acb | `discovery/validation.py`, `cli/main.py` (validate) |
| T-5.9 | Hot-reload extension | 5047efa | `discovery/hotreload.py` |

## Files Created

- `src/orchestra/discovery/__init__.py` -- Public API exports
- `src/orchestra/discovery/errors.py` -- DiscoveryError hierarchy
- `src/orchestra/discovery/config.py` -- ProjectConfig Pydantic model for orchestra.yaml
- `src/orchestra/discovery/tool_discovery.py` -- AST scan + importlib tool collection
- `src/orchestra/discovery/agent_loader.py` -- YAML -> BaseAgent with tool resolution
- `src/orchestra/discovery/workflow_loader.py` -- YAML -> CompiledGraph with name-based refs
- `src/orchestra/discovery/scanner.py` -- ProjectScanner orchestrating full pipeline
- `src/orchestra/discovery/validation.py` -- Cross-ref checks, did-you-mean, CLI reporting
- `src/orchestra/discovery/hotreload.py` -- DiscoveryHotReloader for agent/workflow YAML

## Files Modified

- `src/orchestra/cli/main.py` -- Added `up`, `validate` commands; rewrote `init`

## Test Files

- `tests/unit/test_project_config.py` -- 10 tests
- `tests/unit/test_tool_discovery.py` -- 14 tests (+ linter-added tests)
- `tests/unit/test_agent_loader.py` -- 10 tests (+ linter-added tests)
- `tests/unit/test_workflow_loader.py` -- 11 tests (+ linter-added tests)
- `tests/unit/test_scanner.py` -- 19 tests (linter-generated, all passing)
- `tests/unit/test_cli_up.py` -- 5 tests
- `tests/unit/test_cli_init.py` -- 7 tests
- `tests/unit/test_validation.py` -- 16 tests
- `tests/unit/test_hotreload_discovery.py` -- 6 tests

**Total: 119 tests passing**

## Metrics

- **Duration:** ~95 minutes
- **New code:** ~1060 LOC in `src/orchestra/discovery/` (9 files)
- **CLI changes:** ~120 LOC added to `src/orchestra/cli/main.py`
- **Tests:** 119 tests across 9 test files
- **Dependencies added:** 0 (all libraries already in project)
- **Regressions:** 0 (957 existing tests still passing)

## Decisions Made

1. **__end__ mapping:** YAML `__end__` string mapped to runtime `END` sentinel object (required by WorkflowGraph edge validation)
2. **Two-pass tool discovery confirmed:** AST pre-scan + importlib import. Files without @tool decorator are never executed.
3. **Defaults cascade:** agent YAML > orchestra.yaml defaults > BaseAgent class defaults (matches CSS specificity model)
4. **Python hot-reload NOT supported:** Only YAML files (agents, workflows) are hot-reloaded. Tool Python changes emit a "restart required" log warning.
5. **Error collection strategy:** Scanner collects all errors before returning so users see every problem at once.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed __end__ edge resolution**
- **Found during:** Task T-5.4
- **Issue:** Workflow YAML uses `__end__` string but WorkflowGraph.compile() validates against the `END` sentinel object, causing GraphCompileError
- **Fix:** Added `_resolve_target()` helper that maps `"__end__"` to the `END` sentinel
- **Files modified:** `src/orchestra/discovery/workflow_loader.py`
- **Commit:** 1ef2be6

No other deviations. Plan executed as written.

## Architecture

```
orchestra up [--dir .] [--host 0.0.0.0] [--port 8000]
  |
  v
ProjectScanner.scan(project_dir)
  |
  +-- load_config() -> ProjectConfig (orchestra.yaml)
  +-- discover_tools(tools_dir) -> dict[name, ToolWrapper]
  +-- load_agent(yaml, tool_registry, defaults) -> BaseAgent (per file)
  +-- load_workflow(yaml, agent_registry) -> CompiledGraph (per file)
  |
  v
ScanResult(tools, agents, workflows, errors, warnings)
  |
  +-- Register workflows in GraphRegistry
  +-- Start uvicorn server
  +-- Start DiscoveryHotReloader (watches agents/, workflows/, tools/)
```

## Self-Check: PASSED

All 9 source files verified present. All 10 commits verified in git log. 119 tests passing. 957 existing tests still passing (0 regressions).
