# Phase 5: No-Code Auto-Discovery Layer

**Status:** PLANNED
**Created:** 2026-03-20
**Research:** `research/RESEARCH.md`, `../../autodiscovery-research.md`

## Goal

Users drop Orchestra into any repo, define agents/tools/workflows via YAML + `@tool` Python functions, and run `orchestra up` — no Python wiring code needed.

## Committed Design Decisions

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 1 | Tool discovery | Dynamic import (glob `tools/**/*.py`, import, filter for `ToolWrapper`) | Reuses existing `@tool` mechanism; AST pre-scan too brittle for decorator variants |
| 2 | Agent-tool binding | By function name; dotted-path as override (detected by `.` in string) | Simple, readable, covers 90% of cases |
| 3 | State schema | Python `state.py` file (optional); auto-infer from `output_key`s as fallback | Full Python power when needed, zero-config for simple workflows |
| 4 | Escape hatch | `ref: python.dotted.path` in any YAML node | One uniform mechanism; greppable; uses existing `importlib` |
| 5 | Configuration | Layered (`orchestra.yaml` defaults + per-file overrides), but ship only root config for MVP | Standard pattern (eslint, webpack); per-file deferred |
| 6 | Hot-reload | YAML only (agents, workflows); Python changes require restart | `importlib.reload()` not thread-safe (CPython #126548) |

## Pruned (Do NOT Build)

- AST-only tool discovery (brittle against decorator variants)
- Tag/category tool binding (needs a tagging DSL that doesn't exist)
- YAML type strings for state (can't represent generics or reducers)
- Inline Python in YAML (no IDE support, escaping hell)
- `custom/` directory with self-registration (`ref:` is strictly better)
- Per-file config overrides (defer to post-MVP)
- Python hot-reload (not thread-safe)

## Convention Structure

```
my-project/
  orchestra.yaml          # project config (optional)
  .env                    # API keys (auto-loaded)
  agents/                 # agent YAML definitions
    researcher.yaml
    writer.yaml
  tools/                  # Python files with @tool functions
    search.py
  workflows/              # YAML graph definitions
    pipeline.yaml
  state.py                # optional WorkflowState subclass
  lib/                    # Python escape hatch (routing fns, custom nodes)
    routing.py
```

## New Source Files

```
src/orchestra/discovery/
  __init__.py             # Public API: ProjectScanner, discover_tools, load_agent
  scanner.py              # ProjectScanner: orchestrates full discovery pipeline
  tool_discovery.py       # Glob + import + ToolWrapper collection
  agent_loader.py         # YAML -> BaseAgent with tool resolution
  workflow_loader.py      # Enhanced YAML -> CompiledGraph (name-based refs)
  config.py               # ProjectConfig Pydantic model (orchestra.yaml schema)
  validation.py           # Cross-reference checks, did-you-mean errors
  errors.py               # DiscoveryError, ToolNotFoundError, etc.
```

Plus: `orchestra up` command added to `src/orchestra/cli/main.py`.

## Task Breakdown

### Wave 1: Core Discovery (~300 LOC)

**T-5.1: ProjectConfig schema** (`discovery/config.py`)
- Pydantic model with `extra="forbid"` for `orchestra.yaml`
- Fields: `project.name`, `defaults.model/temperature/max_iterations`, `directories.*`, `server.*`, `security.allowed_imports`
- All fields optional with sensible defaults
- Load from YAML using `ruamel.yaml`

**T-5.2: Tool discovery** (`discovery/tool_discovery.py`)
- `discover_tools(tools_dir: Path) -> dict[str, ToolWrapper]`
- Glob `**/*.py`, skip `_`-prefixed files
- Import each, scan `__dict__` for `ToolWrapper` instances
- Error on duplicate tool names (with both file paths in message)
- Wrap individual imports in try/except (continue on failure, report all)

**T-5.3: Agent loader** (`discovery/agent_loader.py`)
- `load_agent(yaml_path, tool_registry, defaults) -> BaseAgent`
- Parse YAML, resolve tool names against registry
- Clear error on missing tool: "Agent 'X' references tool 'Y' not found. Available: [...]"
- Cascade: agent YAML fields > orchestra.yaml defaults > BaseAgent defaults

**T-5.4: Workflow loader** (`discovery/workflow_loader.py`)
- `load_workflow(yaml_path, agent_registry, tool_registry, builder) -> CompiledGraph`
- Extend `SubgraphBuilder` or wrap `load_graph_yaml()` to check agent registry before dotted-path resolution
- Support `state:` section in YAML (dynamic WorkflowState generation)
- Support `state_ref:` for Python class escape hatch

### Wave 2: CLI + Server Integration (~150 LOC)

**T-5.5: ProjectScanner** (`discovery/scanner.py`)
- `scan(project_dir: Path) -> ScanResult`
- Orchestrates: load config -> discover tools -> load agents -> load workflows
- `ScanResult` dataclass: tools, agents, workflows, errors, warnings
- Validation pass: check all cross-references, collect all errors before failing

**T-5.6: `orchestra up` command** (`cli/main.py`)
- Load `.env` via `pydantic-settings`
- Call `ProjectScanner.scan()`
- Register workflows in `GraphRegistry`
- Start server + `GraphHotReloader`
- Options: `--host`, `--port`, `--reload`, `--dir`

**T-5.7: Enhanced `orchestra init`** (`cli/main.py`)
- Generate full convention structure: `agents/`, `tools/`, `workflows/`, `orchestra.yaml`
- Include example agent YAML, tool file, and workflow YAML

### Wave 3: Validation + Polish (~100 LOC)

**T-5.8: Validation & error reporting** (`discovery/validation.py`)
- `orchestra validate` CLI command (no server start)
- Did-you-mean suggestions (Levenshtein on tool/agent names)
- Report all discovered agents, tools, workflows in a table
- Exit non-zero on any error

**T-5.9: Hot-reload extension**
- Extend `GraphHotReloader` to also watch `agents/` directory
- On agent YAML change: reload agent, re-compile affected workflows
- On tool Python change: log "restart required" warning

## Test Plan

| Test File | Covers | Count (est.) |
|-----------|--------|------|
| `tests/unit/test_tool_discovery.py` | T-5.2: glob, import, ToolWrapper scan, duplicates, failures | ~15 |
| `tests/unit/test_agent_loader.py` | T-5.3: YAML parse, tool resolution, missing tool errors, defaults cascade | ~12 |
| `tests/unit/test_workflow_loader.py` | T-5.4: name-based refs, state from YAML, state_ref escape hatch | ~10 |
| `tests/unit/test_project_config.py` | T-5.1: schema validation, defaults, extra="forbid" | ~8 |
| `tests/unit/test_scanner.py` | T-5.5: full scan, cross-reference validation | ~8 |
| `tests/unit/test_cli_up.py` | T-5.6: command integration, server start | ~5 |
| `tests/unit/test_validation.py` | T-5.8: did-you-mean, error messages | ~8 |
| `tests/fixtures/discovery/` | Sample agents, tools, workflows for test fixtures | — |

**Total: ~66 tests**

## Success Criteria

1. `orchestra init my-project && cd my-project && orchestra up` works end-to-end
2. Adding a new agent YAML + tool file + workflow YAML requires zero Python wiring
3. `orchestra validate` catches all reference errors before server start
4. YAML hot-reload updates running system without restart
5. `ref:` escape hatch allows dropping to Python for any node
6. All existing tests continue to pass (no regressions)

## Estimated Scope

- **New code:** ~550 LOC across 8 files in `src/orchestra/discovery/` + CLI changes
- **New tests:** ~66 tests across 7 test files
- **New dependencies:** None (pydantic-settings already handles .env)
- **Risk:** Low — all runtime primitives exist; this is a wiring layer
