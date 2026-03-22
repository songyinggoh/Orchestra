---
phase: "05-nocode-autodiscovery"
verified: "2026-03-22T00:00:00Z"
status: gaps_found
score: 4/6
---

# Phase 5: No-Code Auto-Discovery Layer — Verification Report

**Phase Goal:** Users drop Orchestra into any repo, define agents/tools/workflows via YAML + `@tool` Python functions, and run `orchestra up` — no Python wiring code needed.
**Verified:** 2026-03-22
**Status:** GAPS_FOUND

---

## Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `orchestra init my-project && orchestra up` works end-to-end | VERIFIED | `cli/main.py:31` creates full dir structure + example files; `cli/main.py:235` scans, registers, starts server; lifespan picks up `_discovery_registry` at `server/app.py:70` |
| 2 | New agent YAML + tool file + workflow YAML requires zero Python wiring | VERIFIED | `tool_discovery.py` globs `**/*.py`, imports, collects `ToolWrapper`; `agent_loader.py` resolves tool names by string; `workflow_loader.py` resolves agent names from registry — no user wiring required |
| 3 | `orchestra validate` catches all reference errors before server start | VERIFIED | `cli/main.py:321` → `validate_project()` → `ProjectScanner.scan()` collects all errors before failing; `did_you_mean()` (Levenshtein) at `validation.py:36`; missing-tool error tested at `test_agent_loader.py:78,92` and `test_scanner.py:215` |
| 4 | YAML hot-reload updates running system without restart | PARTIAL | `DiscoveryHotReloader` (`discovery/hotreload.py`) watches agents/ + tools/ + workflows/ via `watchfiles`; atomic stage-then-commit recompile at `hotreload.py:166`. **GAP: `watchfiles` is not declared in `pyproject.toml`** — relies on transitive dep from `uvicorn[standard]`; breaks silently if extras change |
| 5 | `ref:` escape hatch allows dropping to Python for any node | VERIFIED | `workflow_loader.py:169-237`: agent registry checked first, then `SubgraphBuilder.resolve_ref(dotted.path)` for Python fallback; `_check_lib_ref()` enforces `lib.` prefix guard; `state_ref:` for WorkflowState escape hatch also supported |
| 6 | All existing tests continue to pass (no regressions) | PARTIAL | 80+ dedicated Phase 5 tests across 8 test files (tool_discovery: 18, scanner: 18, agent_loader: 18, cli_up: 5, plus workflow_loader/project_config/discovery_config/discovery_validation). **GAP: `orchestra.discovery` is absent from `test_smoke.py::test_subpackages_importable`** — import errors in the new module would not be caught by the smoke gate. Cannot run suite to confirm CI pass from this branch. |

**Score: 4/6 truths fully verified**

---

## Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| `src/orchestra/discovery/__init__.py` | VERIFIED | 47 lines; clean public API, all exports present |
| `src/orchestra/discovery/scanner.py` | VERIFIED | 133 lines; full pipeline: config → tools → agents → workflows → cross-ref validation |
| `src/orchestra/discovery/tool_discovery.py` | VERIFIED | Exists; glob + import + ToolWrapper scan |
| `src/orchestra/discovery/agent_loader.py` | VERIFIED | Exists; YAML → BaseAgent with tool resolution and defaults cascade |
| `src/orchestra/discovery/workflow_loader.py` | VERIFIED | Exists; name-based refs, state from YAML, `ref:` dotted-path escape hatch |
| `src/orchestra/discovery/config.py` | VERIFIED | Exists; `ProjectConfig` Pydantic model |
| `src/orchestra/discovery/validation.py` | VERIFIED | 113 lines; `validate_project()` + `format_validation_report()` + `did_you_mean()` |
| `src/orchestra/discovery/hotreload.py` | VERIFIED | 226 lines; `DiscoveryHotReloader` with atomic stage-then-commit |
| `src/orchestra/discovery/errors.py` | VERIFIED | Exists; `DiscoveryError`, `ToolNotFoundError`, `DuplicateToolError`, `AgentLoadError`, `WorkflowLoadError`, `ConfigError` |
| `orchestra up` CLI command | VERIFIED | `cli/main.py:235` — `--host`, `--port`, `--reload`, `--dir` options |
| `orchestra validate` CLI command | VERIFIED | `cli/main.py:321` — calls `validate_project()`, exits non-zero on errors |
| `orchestra init` convention structure | VERIFIED | `cli/main.py:31` — generates agents/, tools/, workflows/, lib/, orchestra.yaml, .env, example agent/tool/workflow |

---

## Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| `orchestra up` | `ProjectScanner.scan()` | `cli/main.py:268-269` | WIRED |
| `ProjectScanner` | `discover_tools` → `load_agent` → `load_workflow` | `scanner.py:56-116` | WIRED |
| `orchestra up` | `GraphRegistry` | `cli/main.py:307-312` pre-registers; `server/app.py:67-70` lifespan picks up | WIRED |
| `DiscoveryHotReloader` | `GraphRegistry.register()` | `hotreload.py:160,217` | WIRED |
| `workflow_loader` | `SubgraphBuilder.resolve_ref()` | `workflow_loader.py:220` for `ref:` escape hatch | WIRED |
| `_check_lib_ref()` | sys.path guard | `workflow_loader.py:47` — enforces `lib.` prefix | WIRED |
| `orchestra validate` | `format_validation_report()` | `cli/main.py:330-333` | WIRED |

---

## Anti-Patterns Found

| File | Pattern | Severity | Notes |
|------|---------|----------|-------|
| `discovery/hotreload.py:110` | `change_type: Any` | LOW | Legitimate — `watchfiles.Change` enum type; acceptable at API boundary |
| None | TODO/FIXME/HACK | NONE | Clean |
| None | Empty catch blocks | NONE | All `except` blocks log and handle gracefully |

---

## Gaps Summary

### GAP-1 (BLOCKING for Truth 4): `watchfiles` undeclared in `pyproject.toml`

`discovery/hotreload.py` imports `from watchfiles import awatch, Change` at the top level, but `watchfiles` does not appear anywhere in `pyproject.toml` dependencies or extras. It is currently available transitively via `uvicorn[standard]`, but this is fragile:

- A user installing `orchestra-agents[server]` without `[standard]` uvicorn would get an `ImportError` on `DiscoveryHotReloader` instantiation.
- Any future change to uvicorn's transitive deps could silently break hot-reload.

**Fix:** Add `watchfiles>=0.21` to the `server` extra in `pyproject.toml` (it's already a uvicorn[standard] dep, so no new wheel is downloaded in practice).

### GAP-2 (MINOR for Truth 6): `orchestra.discovery` absent from smoke test

`tests/test_smoke.py::test_subpackages_importable` imports `orchestra.cli`, `orchestra.core`, `orchestra.observability`, `orchestra.providers`, `orchestra.testing`, `orchestra.tools` — but not `orchestra.discovery`. An import error introduced in the discovery layer would not be caught by the smoke gate and could silently pass CI.

**Fix:** Add `import orchestra.discovery` to `test_subpackages_importable()` in `test_smoke.py`.

---

## Human Verification Required

### 1. End-to-End `orchestra up` with real API key

**Test:** Run `orchestra init demo && cd demo && echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env && orchestra up`, then `curl -X POST http://localhost:8000/runs -d '{"workflow":"hello","input":{"input":"Alice"}}'`
**Expected:** Server starts, responds with `{"output": "Hello, Alice! Welcome to Orchestra."}` or similar
**Why human:** CLI → server → real LLM call chain cannot be verified by static analysis; requires a live API key and a running server process

### 2. YAML hot-reload in a live session

**Test:** Start `orchestra up --reload` in a project, then edit an agent YAML file (e.g., change `temperature: 0.7` to `temperature: 0.3`). Check server logs.
**Expected:** Log line `agent_reloaded` appears within ~1s; subsequent requests use the updated agent; no server restart needed
**Why human:** `awatch()` is an async file-watching loop that cannot be triggered in unit tests without real filesystem events

### 3. `orchestra validate` did-you-mean output

**Test:** In a project with a tool named `greet`, create an agent YAML with `tools: [grete]` (typo), then run `orchestra validate`
**Expected:** Error output includes something like `Did you mean: greet?`
**Why human:** The `did_you_mean` function is unit-tested but the CLI formatting of the suggestion is only in `format_validation_report()` — verify the terminal output actually renders the suggestion clearly
