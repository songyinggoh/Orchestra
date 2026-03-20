# Phase 5: No-Code Auto-Discovery Layer - Research

**Researched:** 2026-03-20
**Domain:** Convention-based project scanning, YAML-driven agent/workflow definition, CLI orchestration
**Confidence:** HIGH

## Summary

The Orchestra framework already has strong building blocks: `load_graph_yaml()` for YAML-to-graph hydration, `GraphHotReloader` for file watching, `@tool` decorator with auto-schema, `auto_provider()` for zero-config LLM setup, and a Typer-based CLI. The auto-discovery layer needs to connect these pieces with a convention-based scanner that finds tools, agents, and workflows from a standard directory structure, then wires them together and starts the server.

The core technical challenge is **tool discovery** -- safely finding `@tool`-decorated functions in user Python files. AST parsing (no execution) is the right first pass for discovery, with targeted `importlib` loading of only the files that contain `@tool` decorations. Agent YAML schemas map directly to `BaseAgent` constructor fields. Workflow YAML already works via `load_graph_yaml()` but needs extension to resolve agent names (not just dotted paths). State schemas can be expressed as simple YAML for the common case (string/int/dict/list fields with named reducers), with a Python escape hatch for complex types.

**Primary recommendation:** Build a `ProjectScanner` class that discovers tools via AST pre-scan + import, agents via YAML parsing, and workflows via existing YAML loading. Wire into a new `orchestra up` CLI command that calls `ProjectScanner.scan()`, populates `GraphRegistry`, and starts the server with hot-reload.

## Standard Stack

### Core (already in project)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| typer | >=0.12 | CLI framework | Already used for `orchestra` CLI |
| ruamel.yaml | >=0.18 | YAML parsing with round-trip | Already used in `load_graph_yaml` |
| watchfiles | (installed) | Async file watching | Already used in `GraphHotReloader` |
| pydantic | >=2.5 | Schema validation | Already used for `BaseAgent`, `WorkflowState` |
| pydantic-settings | >=2.0 | Env-based config | Already used in `ServerConfig` |
| structlog | (installed) | Structured logging | Already used throughout |

### New Dependencies

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| python-dotenv | >=1.0 | `.env` file loading | Auto-load `.env` on `orchestra up` |

**Note:** `python-dotenv` is the only new dependency. Everything else is already in the project. Add it to pyproject.toml core dependencies.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| python-dotenv | pydantic-settings `.env` | pydantic-settings already supports `.env` via `SettingsConfigDict(env_file=".env")` -- could extend `ServerConfig` instead of adding python-dotenv. **Recommendation: Use pydantic-settings** since it is already a dependency. |
| AST pre-scan for tools | Direct importlib of all `.py` files | Unsafe -- executes arbitrary code. AST scan first, import only decorated files. |
| YAML for state schema | Python-only state classes | YAML covers 90% of use cases. Escape hatch via `ref:` to a Python class for complex types. |

**Installation:**
```bash
# No new packages needed -- pydantic-settings already handles .env loading
```

## Architecture Patterns

### Recommended Project Structure (User-Facing Convention)

```
my-project/
  orchestra.yaml            # Project config (optional -- defaults work)
  .env                      # API keys (loaded automatically)
  agents/                   # Agent YAML definitions
    researcher.yaml
    writer.yaml
  tools/                    # Python files with @tool functions
    search.py
    database.py
    utils/                  # Subdirectories supported
      formatting.py
  workflows/                # YAML graph definitions
    pipeline.yaml
    review_loop.yaml
  lib/                      # Python escape hatch (custom nodes, reducers, state classes)
    custom_state.py
    validators.py
```

### Internal Architecture (New Modules)

```
src/orchestra/
  discovery/                # NEW package
    __init__.py
    scanner.py              # ProjectScanner: orchestrates all discovery
    tool_discovery.py       # AST scan + import for @tool functions
    agent_loader.py         # YAML -> BaseAgent instances
    workflow_loader.py      # Enhanced YAML -> CompiledGraph (name-based refs)
    state_builder.py        # YAML -> WorkflowState subclass (dynamic)
    config.py               # orchestra.yaml schema (ProjectConfig)
    validation.py           # Cross-references, error reporting
    errors.py               # Discovery-specific error types
  cli/
    main.py                 # Add `orchestra up` command
```

### Pattern 1: Two-Pass Tool Discovery (AST + Import)

**What:** First pass uses `ast.parse()` to find files containing `@tool` decorators without executing code. Second pass uses `importlib` to load only those files.

**When to use:** Always -- this is the only safe approach for scanning user directories.

**Example:**
```python
import ast
import importlib.util
import sys
from pathlib import Path
from orchestra.tools.base import ToolWrapper

def _ast_has_tool_decorator(source: str) -> bool:
    """Check if source contains @tool decorator without executing it."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                # @tool
                if isinstance(decorator, ast.Name) and decorator.id == "tool":
                    return True
                # @tool(name="...")
                if isinstance(decorator, ast.Call):
                    func = decorator.func
                    if isinstance(func, ast.Name) and func.id == "tool":
                        return True
    return False

def discover_tools(tools_dir: Path) -> dict[str, ToolWrapper]:
    """Discover @tool functions from a directory tree."""
    tools: dict[str, ToolWrapper] = {}

    for py_file in sorted(tools_dir.rglob("*.py")):
        if py_file.name.startswith("_"):
            continue
        source = py_file.read_text(encoding="utf-8")
        if not _ast_has_tool_decorator(source):
            continue

        # Safe to import -- we know it has @tool decorators
        module_name = f"orchestra_user_tools.{py_file.stem}"
        spec = importlib.util.spec_from_file_location(module_name, py_file)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        # Collect ToolWrapper instances
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if isinstance(obj, ToolWrapper):
                tools[obj.name] = obj

    return tools
```

### Pattern 2: Agent YAML Loading

**What:** Parse agent YAML files into `BaseAgent` instances, resolving tool references by name against the discovered tool registry.

**When to use:** For each `.yaml` file in the `agents/` directory.

**Example:**
```python
from ruamel.yaml import YAML
from orchestra.core.agent import BaseAgent

def load_agent_yaml(
    yaml_path: Path,
    tool_registry: dict[str, ToolWrapper],
) -> BaseAgent:
    """Load an agent definition from YAML."""
    yaml = YAML(typ="safe")
    data = yaml.load(yaml_path.read_text(encoding="utf-8"))

    # Resolve tool references by name
    tool_names = data.get("tools", [])
    resolved_tools = []
    for name in tool_names:
        if name not in tool_registry:
            raise DiscoveryError(
                f"Agent '{data['name']}' references tool '{name}' "
                f"which was not found. Available: {list(tool_registry.keys())}"
            )
        resolved_tools.append(tool_registry[name])

    return BaseAgent(
        name=data.get("name", yaml_path.stem),
        model=data.get("model", "gpt-4o-mini"),
        system_prompt=data.get("system_prompt", "You are a helpful assistant."),
        tools=resolved_tools,
        max_iterations=data.get("max_iterations", 10),
        temperature=data.get("temperature", 0.7),
    )
```

### Pattern 3: Name-Based Workflow Resolution

**What:** Extend `load_graph_yaml()` to resolve node refs by name (matching agent YAML filenames) in addition to dotted paths.

**When to use:** For all workflow YAML files when an agent registry is available.

**Example:**
```python
# In workflow YAML, users write:
# nodes:
#   research:
#     type: agent
#     ref: researcher        # <-- name, not dotted path
#     config:
#       output_key: findings
#
# The enhanced loader checks agent_registry first, falls back to dotted-path

def resolve_node_ref(
    ref: str,
    agent_registry: dict[str, BaseAgent],
    builder: SubgraphBuilder,
) -> Any:
    """Resolve a ref string to an agent or Python object."""
    # Try name-based lookup first
    if ref in agent_registry:
        return agent_registry[ref]
    # Fall back to dotted-path resolution
    return builder.resolve_ref(ref)
```

### Pattern 4: Dynamic State Schema from YAML

**What:** Generate a `WorkflowState` subclass at runtime from YAML field definitions.

**When to use:** When a workflow YAML defines a `state` section.

**Example:**
```python
from orchestra.core.state import (
    WorkflowState, merge_list, merge_dict, sum_numbers,
    last_write_wins, merge_set, concat_str, keep_first,
    max_value, min_value,
)
from typing import Annotated, Any

REDUCER_MAP = {
    "merge_list": merge_list,
    "merge_dict": merge_dict,
    "sum": sum_numbers,
    "last_write_wins": last_write_wins,
    "merge_set": merge_set,
    "concat": concat_str,
    "keep_first": keep_first,
    "max": max_value,
    "min": min_value,
}

TYPE_MAP = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
    "set": set,
}

def build_state_class(state_def: dict[str, Any]) -> type[WorkflowState]:
    """Build a WorkflowState subclass from YAML state definition.

    YAML format:
        state:
          topic: str
          output: str
          findings:
            type: dict
            reducer: merge_dict
          step_count:
            type: int
            reducer: sum
            default: 0
    """
    annotations = {}
    defaults = {}

    for field_name, field_spec in state_def.items():
        if isinstance(field_spec, str):
            # Simple type: "str", "int", etc.
            py_type = TYPE_MAP.get(field_spec, str)
            annotations[field_name] = py_type
            defaults[field_name] = py_type()  # empty default
        elif isinstance(field_spec, dict):
            py_type = TYPE_MAP.get(field_spec.get("type", "str"), str)
            reducer_name = field_spec.get("reducer")
            if reducer_name and reducer_name in REDUCER_MAP:
                annotations[field_name] = Annotated[py_type, REDUCER_MAP[reducer_name]]
            else:
                annotations[field_name] = py_type
            defaults[field_name] = field_spec.get("default", py_type())

    # Dynamically create the class
    ns = {"__annotations__": annotations, **defaults}
    return type("DynamicState", (WorkflowState,), ns)
```

### Pattern 5: orchestra up Command Flow

**What:** Single command that orchestrates the full discovery and startup pipeline.

**When to use:** The primary user entry point.

**Example flow:**
```
orchestra up [--host 0.0.0.0] [--port 8000] [--reload] [--dir .]
  1. Load .env from project root (pydantic-settings or python-dotenv)
  2. Load orchestra.yaml if present (ProjectConfig)
  3. Discover tools from tools/ directory (AST scan + import)
  4. Load agent YAMLs from agents/ directory, resolve tools
  5. Load workflow YAMLs from workflows/ directory, resolve agents
  6. Compile all workflows, register in GraphRegistry
  7. Start server with uvicorn
  8. Start GraphHotReloader watching agents/, workflows/, tools/
```

### Anti-Patterns to Avoid

- **Executing all Python files blindly:** Never import all `.py` files in a directory. Use AST pre-scan to identify files that contain `@tool` decorators, then import only those.
- **Global mutable tool registry:** Use dependency injection. The `ProjectScanner` produces a result object that is threaded through agent loading and workflow compilation.
- **Implicit tool name collisions:** If two files define tools with the same name, fail loudly at startup rather than silently overwriting.
- **Magic __init__.py scanning:** Do not require `__init__.py` in user directories. Treat `tools/`, `agents/`, `workflows/` as plain directories, not Python packages.
- **Reloading Python tool modules on file change:** Hot-reloading Python is fragile (not thread-safe, stale references). Only hot-reload YAML files (agents and workflows). For tool changes, require a restart and log a clear message.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| .env loading | Custom `.env` parser | `pydantic-settings` with `env_file=".env"` | Already a dependency; handles quoting, comments, multiline |
| YAML parsing | Custom parser | `ruamel.yaml` (already used) | Round-trip support, safe loading, type detection |
| File watching | Custom `os.stat` polling | `watchfiles` (already used) | Rust-based, async-native, handles OS edge cases |
| CLI commands | argparse | `typer` (already used) | Rich help, type validation, subcommand routing |
| JSON schema from type hints | Manual schema building | `_generate_parameters_schema` (already exists in tools/base.py) | Handles all Python primitive types |
| Async server | Custom event loop | `uvicorn` + `FastAPI` (already used) | Production-grade ASGI |

**Key insight:** Nearly everything needed is already in the project. This phase is about wiring, not building new infrastructure.

## Common Pitfalls

### Pitfall 1: Circular Import During Tool Discovery

**What goes wrong:** A tool file imports from `orchestra` which triggers the full import chain, causing circular imports or slow startup.
**Why it happens:** User tool files `from orchestra.tools.base import tool` which is normal, but if discovery imports these files during module initialization, it can conflict.
**How to avoid:** Import user tool modules into an isolated namespace (`orchestra_user_tools.*`) and ensure the discovery module itself does not import from `orchestra.tools.base` at module level.
**Warning signs:** `ImportError` or `AttributeError` during `orchestra up` that mentions circular imports.

### Pitfall 2: Tool Name Collisions

**What goes wrong:** Two different files define `@tool` functions with the same name. The second silently overwrites the first.
**Why it happens:** The `@tool` decorator uses `func.__name__` as the tool name by default. Two files could both have `async def search(...)`.
**How to avoid:** Detect duplicates during discovery and raise a clear error: "Tool 'search' defined in both tools/web.py and tools/db.py. Use @tool(name='web_search') to disambiguate."
**Warning signs:** Agent gets wrong tool, unexpected behavior.

### Pitfall 3: Missing Tool Dependencies at Import Time

**What goes wrong:** A tool file imports a library that is not installed (e.g., `import requests`). The entire discovery fails.
**Why it happens:** AST scan says file has `@tool`, but actual import fails due to missing dependency.
**How to avoid:** Wrap individual file imports in try/except, log the error with the specific file path, and continue discovering other files. Report all failures at the end.
**Warning signs:** `ModuleNotFoundError` during startup.

### Pitfall 4: YAML Agent References Non-Existent Tool

**What goes wrong:** An agent YAML lists `tools: [search]` but no tool named "search" was discovered.
**Why it happens:** Typo in YAML, tool file failed to load, or tool has a custom name via `@tool(name="...")`.
**How to avoid:** Validate all tool references during agent loading. Produce a clear error message listing available tools.
**Warning signs:** Agent YAML loads but agent fails at runtime with "tool not found".

### Pitfall 5: State Schema YAML Limitations

**What goes wrong:** User tries to express a complex state field in YAML (e.g., `list[Message]`, custom Pydantic model, nested Annotated types) and gets unhelpful errors.
**Why it happens:** YAML state builder only supports primitive types and built-in reducers.
**How to avoid:** Document the supported type subset clearly. For anything beyond primitives, provide the `ref:` escape hatch to a Python class: `state_ref: lib.custom_state.MyState`.
**Warning signs:** `KeyError` or `TypeError` when workflow starts.

### Pitfall 6: Hot-Reload Race Condition with In-Flight Runs

**What goes wrong:** A YAML file changes mid-run. The hot-reloader swaps the graph in the registry while a run is using the old graph.
**Why it happens:** `GraphRegistry.register()` replaces the graph reference, but `RunManager` already has the old `CompiledGraph` instance.
**How to avoid:** This is already handled correctly. `RunManager` holds a reference to the specific `CompiledGraph` instance passed to `start_run()`. Registry swap only affects new runs. Document this behavior.
**Warning signs:** None if implemented correctly. The existing pattern is safe.

## Code Examples

### Agent YAML Schema (Recommended)

```yaml
# agents/researcher.yaml
name: researcher
model: claude-sonnet-4-20250514
system_prompt: |
  You are a research analyst. Find key facts about the given topic.
  Be thorough and cite sources.
tools:
  - web_search
  - read_url
max_iterations: 5
temperature: 0.3
```

### Agent YAML with Structured Output

```yaml
# agents/classifier.yaml
name: classifier
model: claude-sonnet-4-20250514
system_prompt: Classify the input into one of the predefined categories.
output_type_ref: lib.models.ClassificationResult  # Python escape hatch
temperature: 0.0
max_iterations: 1
```

### Workflow YAML with Name-Based Refs

```yaml
# workflows/research_pipeline.yaml
name: research_pipeline

state:
  topic: str
  research: str
  draft: str
  output: str

nodes:
  researcher:
    type: agent
    ref: researcher          # Matches agents/researcher.yaml
    output_key: research
  writer:
    type: agent
    ref: writer              # Matches agents/writer.yaml
    output_key: draft
  editor:
    type: agent
    ref: editor
    output_key: output

edges:
  - source: researcher
    target: writer
  - source: writer
    target: editor
  - source: editor
    target: __end__

entry_point: researcher
```

### Workflow YAML with Parallel Fan-Out

```yaml
# workflows/parallel_research.yaml
name: parallel_research

state:
  topic: str
  findings:
    type: dict
    reducer: merge_dict
  output: str

nodes:
  dispatcher:
    type: function
    ref: lib.helpers.dispatch  # Python escape hatch for function nodes
  web_researcher:
    type: agent
    ref: researcher
    output_key: findings
  db_researcher:
    type: agent
    ref: db_analyst
    output_key: findings
  synthesizer:
    type: agent
    ref: writer
    output_key: output

edges:
  - source: dispatcher
    target: [web_researcher, db_researcher]
    join: synthesizer
  - source: synthesizer
    target: __end__

entry_point: dispatcher
```

### Workflow YAML with Conditional Routing

```yaml
# workflows/triage.yaml
name: triage

state:
  input: str
  category: str
  output: str

nodes:
  classifier:
    type: agent
    ref: classifier
    output_key: category
  tech_agent:
    type: agent
    ref: tech_support
    output_key: output
  billing_agent:
    type: agent
    ref: billing_support
    output_key: output

edges:
  - source: classifier
    target: tech_agent
    type: conditional
    condition_ref: lib.routing.route_by_category  # Python function
    paths:
      technical: tech_agent
      billing: billing_agent
  - source: tech_agent
    target: __end__
  - source: billing_agent
    target: __end__

entry_point: classifier
```

### orchestra.yaml Schema

```yaml
# orchestra.yaml (all fields optional)
project:
  name: my-ai-project
  version: "1.0"

defaults:
  model: claude-sonnet-4-20250514
  temperature: 0.7
  max_iterations: 10
  provider: anthropic        # anthropic | openai | google | http

directories:
  agents: agents             # Override default directory names
  tools: tools
  workflows: workflows
  lib: lib                   # Python escape hatch directory

server:
  host: 0.0.0.0
  port: 8000
  cors_origins: ["http://localhost:3000"]

discovery:
  tool_patterns:             # Glob patterns for tool discovery
    - "tools/**/*.py"
  agent_patterns:
    - "agents/**/*.yaml"
    - "agents/**/*.yml"
  workflow_patterns:
    - "workflows/**/*.yaml"
    - "workflows/**/*.yml"
  exclude:
    - "**/__pycache__/**"
    - "**/test_*"
    - "**/*_test.py"

security:
  allowed_imports:           # Additional allowed prefixes for ref resolution
    - "lib."
  sandbox_tools: false       # Future: WASM sandbox for discovered tools

observability:
  tracing: true
  metrics: true
  log_level: INFO
```

### Tool File Example

```python
# tools/search.py
from orchestra.tools.base import tool

@tool
async def web_search(query: str, max_results: int = 5) -> str:
    """Search the web for information about a topic."""
    # Implementation here
    return f"Results for: {query}"

@tool(name="read_url")
async def fetch_url(url: str) -> str:
    """Read and extract text content from a URL."""
    # Implementation here
    return f"Content from: {url}"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Dotted-path-only refs in YAML | Name-based refs (convention) | This phase | Users never write Python import paths |
| Python-only state classes | YAML state schemas (simple types) | This phase | 90% of workflows need no Python |
| Manual wiring in Python | Auto-discovery from directory structure | This phase | Drop-in, zero-code setup |
| `orchestra serve` (manual graph registration) | `orchestra up` (auto-discover + serve) | This phase | Single command for everything |

**Industry precedents:**
- **CrewAI:** Uses `config/agents.yaml` + `config/tasks.yaml` with `{variable}` interpolation. Their YAML schema is a good reference but tightly coupled to their Crew abstraction.
- **Next.js:** File-based routing is the gold standard for convention-over-configuration. Directory names are meaningful, file names become route segments.
- **Rails:** "Convention over configuration" coined here. Naming conventions eliminate boilerplate.
- **Docker Compose:** Single YAML file defines multi-service applications. `docker compose up` is the direct inspiration for `orchestra up`.

## Open Questions

1. **MCP tool integration in YAML workflows**
   - What we know: `MCPClient` and `load_mcp_config()` exist. MCP tools satisfy the Tool protocol.
   - What's unclear: Should `orchestra.yaml` have an `mcp` section that auto-connects MCP servers and makes their tools available by name alongside `@tool` functions?
   - Recommendation: Yes. Add `mcp` section to `orchestra.yaml` that mirrors `.orchestra/mcp.json` format. MCP tools get discovered alongside local tools and are available by name in agent YAML.

2. **Python file hot-reload safety**
   - What we know: `importlib.reload()` is not thread-safe (CPython issue #126548). Stale references persist for `from X import Y` style imports.
   - What's unclear: Can we safely reload tool Python files?
   - Recommendation: Do NOT hot-reload Python files. Only hot-reload YAML (agents, workflows). For Python tool changes, log "Tool file changed -- restart required" and optionally auto-restart the process (like uvicorn `--reload`).

3. **Structured output types from YAML**
   - What we know: `BaseAgent.output_type` expects a Pydantic BaseModel class.
   - What's unclear: Can we express Pydantic models in YAML?
   - Recommendation: No. Use `output_type_ref: dotted.path.to.Model` for structured output. This is the right escape hatch -- Pydantic models are fundamentally Python constructs.

4. **Default model override cascade**
   - What we know: `BaseAgent` defaults to `gpt-4o-mini`. `auto_provider()` picks provider from env.
   - What's unclear: When `orchestra.yaml` sets `defaults.model`, should it override agent-level YAML, or be a fallback?
   - Recommendation: Cascade: agent YAML > orchestra.yaml defaults > BaseAgent defaults. This matches CSS specificity and is most intuitive.

5. **Handling of `lib/` directory imports**
   - What we know: Workflow YAML can reference `lib.routing.route_by_category` via dotted path.
   - What's unclear: How to make `lib/` importable without requiring `__init__.py` or modifying `sys.path` permanently.
   - Recommendation: Temporarily add project root to `sys.path` during discovery. Use `allowed_prefixes` to whitelist `lib.` in the `SubgraphBuilder`. Require `__init__.py` in `lib/` (this is standard Python).

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/unit/test_discovery.py -x -q` |
| Full suite command | `pytest tests/unit/ -x -q` |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DISC-01 | AST scan finds @tool-decorated functions | unit | `pytest tests/unit/test_tool_discovery.py -x` | No -- Wave 0 |
| DISC-02 | Import only AST-matched files, collect ToolWrapper instances | unit | `pytest tests/unit/test_tool_discovery.py::test_import_tools -x` | No -- Wave 0 |
| DISC-03 | Duplicate tool name detection raises error | unit | `pytest tests/unit/test_tool_discovery.py::test_duplicate_names -x` | No -- Wave 0 |
| DISC-04 | Agent YAML parsed to BaseAgent with correct fields | unit | `pytest tests/unit/test_agent_loader.py -x` | No -- Wave 0 |
| DISC-05 | Agent tool references resolved from registry | unit | `pytest tests/unit/test_agent_loader.py::test_tool_resolution -x` | No -- Wave 0 |
| DISC-06 | Missing tool reference produces clear error | unit | `pytest tests/unit/test_agent_loader.py::test_missing_tool_error -x` | No -- Wave 0 |
| DISC-07 | Workflow YAML resolves name-based agent refs | unit | `pytest tests/unit/test_workflow_loader.py -x` | No -- Wave 0 |
| DISC-08 | Dynamic state class from YAML with reducers | unit | `pytest tests/unit/test_state_builder.py -x` | No -- Wave 0 |
| DISC-09 | ProjectScanner full scan produces populated registry | integration | `pytest tests/unit/test_scanner.py -x` | No -- Wave 0 |
| DISC-10 | `orchestra up` command starts server with discovered graphs | smoke | `pytest tests/unit/test_cli_up.py -x` | No -- Wave 0 |
| DISC-11 | orchestra.yaml config loading with defaults cascade | unit | `pytest tests/unit/test_project_config.py -x` | No -- Wave 0 |
| DISC-12 | Hot-reload of agent/workflow YAML updates registry | unit | `pytest tests/unit/test_hotreload_discovery.py -x` | No -- Wave 0 |
| DISC-13 | Validation: workflow refs non-existent agent -> clear error | unit | `pytest tests/unit/test_validation.py -x` | No -- Wave 0 |
| DISC-14 | `orchestra init` generates full convention structure | unit | `pytest tests/unit/test_cli_init.py -x` | No -- Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest tests/unit/test_discovery.py tests/unit/test_agent_loader.py tests/unit/test_workflow_loader.py -x -q`
- **Per wave merge:** `pytest tests/unit/ -x -q`
- **Phase gate:** Full suite green before verification

### Wave 0 Gaps

- [ ] `tests/unit/test_tool_discovery.py` -- covers DISC-01, DISC-02, DISC-03
- [ ] `tests/unit/test_agent_loader.py` -- covers DISC-04, DISC-05, DISC-06
- [ ] `tests/unit/test_workflow_loader.py` -- covers DISC-07
- [ ] `tests/unit/test_state_builder.py` -- covers DISC-08
- [ ] `tests/unit/test_scanner.py` -- covers DISC-09
- [ ] `tests/unit/test_project_config.py` -- covers DISC-11
- [ ] `tests/unit/test_validation.py` -- covers DISC-13
- [ ] `tests/unit/test_cli_up.py` -- covers DISC-10
- [ ] `tests/unit/test_cli_init.py` -- covers DISC-14
- [ ] `tests/unit/test_hotreload_discovery.py` -- covers DISC-12
- [ ] Test fixtures: sample tool files, agent YAMLs, workflow YAMLs in `tests/fixtures/discovery/`

## Sources

### Primary (HIGH confidence)

- **Python `ast` module docs** (https://docs.python.org/3/library/ast.html) -- AST parsing is safe, `ast.parse()` does not execute code, `decorator_list` attribute on `FunctionDef` nodes
- **watchfiles docs** (https://watchfiles.helpmanual.io/) -- `awatch` API, filter patterns, already used in project
- **python-dotenv** (https://pypi.org/project/python-dotenv/) -- `.env` loading conventions
- **CPython issue #126548** (https://github.com/python/cpython/issues/126548) -- `importlib.reload()` is not thread-safe, confirming our decision to NOT hot-reload Python files
- **Codebase analysis** -- All 10 key files read and analyzed:
  - `src/orchestra/core/dynamic.py` -- `load_graph_yaml()`, `SubgraphBuilder` with security allowlist
  - `src/orchestra/core/hotreload.py` -- `GraphHotReloader` using `watchfiles.awatch`
  - `src/orchestra/core/agent.py` -- `BaseAgent` Pydantic model (name, model, system_prompt, tools, max_iterations, temperature, output_type, provider)
  - `src/orchestra/core/state.py` -- `WorkflowState`, 9 built-in reducers, `extract_reducers()`
  - `src/orchestra/tools/base.py` -- `@tool` decorator, `ToolWrapper` class with name/description/parameters_schema
  - `src/orchestra/tools/mcp.py` -- `MCPClient`, `load_mcp_config()`, `MCPToolAdapter`
  - `src/orchestra/cli/main.py` -- Typer app, existing commands (version, init, run, resume, serve)
  - `src/orchestra/server/lifecycle.py` -- `GraphRegistry`, `RunManager`
  - `src/orchestra/server/app.py` -- `create_app()` with lifespan, middleware
  - `src/orchestra/core/graph.py` -- `WorkflowGraph` fluent + explicit API

### Secondary (MEDIUM confidence)

- **CrewAI YAML conventions** (https://docs.crewai.com/en/quickstart, https://deepwiki.com/crewAIInc/crewAI/8.2-yaml-configuration) -- agents.yaml/tasks.yaml pattern, `{variable}` interpolation, config/ directory layout
- **CrewAI project structure** (https://deepwiki.com/lymanzhang/crewAI/5.2-project-structure-and-configuration) -- CLI scaffolding, src/ layout conventions

### Tertiary (LOW confidence)

- None -- all findings verified against codebase or official documentation.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already in the project, no new dependencies needed
- Architecture: HIGH -- patterns directly extend existing codebase (SubgraphBuilder, GraphHotReloader, CLI)
- Pitfalls: HIGH -- verified against CPython source (reload thread safety), tested AST parsing behavior
- YAML schema design: MEDIUM -- inspired by CrewAI patterns but adapted for Orchestra's agent model; needs user feedback

**Research date:** 2026-03-20
**Valid until:** 2026-04-20 (stable domain, no fast-moving dependencies)
