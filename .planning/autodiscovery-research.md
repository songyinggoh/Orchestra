# Auto-Discovery Layer Research Report
# Convention-over-Configuration for Orchestra

**Date:** 2026-03-20
**Scope:** Designing `orchestra up` — YAML agents, decorated Python tools, YAML workflow graphs,
all auto-discovered and served without explicit wiring code.

---

## 1. Convention-over-Configuration Patterns in Developer Tools

### What the successful frameworks do

**Next.js (file-based routing)**
The canonical example. Every file under `app/` becomes a route. The filesystem IS the
configuration. Key insight: the convention is so tight that there is almost nothing to
configure — the rule is "file at path X → route at URL /X". The failure mode the team
discovered is that the convention needs a clear override story: `layout.tsx`, `loading.tsx`,
`error.tsx` are all reserved filenames with semantics. When users don't know the reserved
names, unexpected files silently become routes. Lesson: **publish a complete list of reserved
names up front and error if a file matches an unknown reserved pattern**.

**Django app discovery (`INSTALLED_APPS` + `autodiscover_modules`)**
Django's `AppConfig.ready()` + `autodiscover_modules('admin')` pattern: each installed app
module is scanned for a known submodule name. Registration happens as a side effect of import.
The anti-pattern Django later regretted: discovery is order-dependent and side-effectful.
If two apps register the same name, the second silently wins. Lesson: **registry collisions
must be loud errors, not silent overwrites**.

**Flask Blueprints**
Explicit registration (`app.register_blueprint(bp)`) rather than auto-registration. This is
intentional — Flask's philosophy is "explicit is better than implicit". But the community
built `Flask-AutoDiscover` and similar packages on top, showing the demand is real. The
lesson Flask's approach teaches: **auto-discovery should be opt-in and bounded** (a specific
directory, not the whole Python path). Scanning the whole path is too broad and has security
and performance implications.

**FastAPI (auto-docs)**
FastAPI auto-generates OpenAPI docs from decorated function signatures. No YAML needed to
describe APIs — the code IS the schema. Lesson for Orchestra: **the `@tool` decorator already
does this** — it reads type hints and docstrings. The auto-discovery layer should embrace this
and not require a separate YAML manifest for tools.

**Gatsby (filesystem → GraphQL)**
Gatsby's source plugin model: plugins add data sources, each contributing nodes to a unified
GraphQL layer. Heavy plugin ecosystem but notorious for "dependency hell" and slow cold starts
because every plugin import is eager. Lesson: **lazy-load discovered modules; don't import
everything at startup**.

### The three safe discovery zones

1. **Filesystem convention** — look in named directories (`agents/`, `tools/`, `workflows/`).
   Predictable, auditable, no package metadata needed.
2. **Decorator registration** — `@tool` registers into a module-level registry on import.
   The framework controls the registry; users never touch it directly.
3. **Package entry points** — `importlib.metadata.entry_points(group='orchestra.tools')`
   for installable plugins. Safe because packages are explicitly installed.

### Anti-patterns to avoid

- **Scanning `sys.modules` or `sys.path` globally.** Too broad. Picks up test files,
  vendored dependencies, CI fixtures.
- **Silent collision resolution.** If `tools/search.py` and an installed package both define
  `search`, error loudly with both paths.
- **Discovery that mutates global state without a clear lifecycle.** Register into an
  isolated `AppContext` object, not module-level globals, so tests can create isolated
  instances.
- **Order-dependent discovery.** Sort discovered files deterministically (alphabetically)
  and document that order. Never rely on filesystem ordering.

---

## 2. No-Code / Low-Code Agent Framework Patterns

### CrewAI (YAML agents + `@CrewBase`)

CrewAI is the closest precedent to what Orchestra is building. Structure:

```
my_crew/
  config/
    agents.yaml    # agent definitions
    tasks.yaml     # task definitions
  crew.py          # @CrewBase class wiring YAML → Python
```

`agents.yaml` fields:
```yaml
researcher:
  role: "{topic} Senior Researcher"      # {placeholder} for runtime injection
  goal: "Uncover developments in {topic}"
  backstory: "Expert in..."
  llm: anthropic/claude-opus-4           # provider/model string
  tools:
    - search_tool
    - read_file
  verbose: true
  max_iter: 5
  memory: true
```

The `@CrewBase` decorator loads both YAML files and maps them to the decorated methods.
Python methods decorated with `@agent` return `Agent(config=self.agents_config['researcher'])`.
This is the **"thin glue" pattern**: YAML holds data, Python holds behavior.

Key limitation: the `@agent` methods must still be written — YAML does not eliminate code,
it moves configuration out of code. The escape hatch is always available: any field not in
YAML can be set in the Python method.

### Open Agent Specification (Oracle, arXiv 2510.04173)

The most ambitious declarative standard. Schema fields:

```yaml
component_type: Flow
name: research_pipeline
id: flow-001
inputs:
  - title: query
    type: string
outputs:
  - title: report
    type: string
nodes:
  - component_type: LLMNode
    id: drafter
    inputs: [...]
    outputs: [...]
control_flow_connections:
  - from: start
    to: drafter
  - from: drafter
    to: end
data_flow_connections:
  - source_node: drafter
    output: draft
    destination_node: end
    input: result
```

Key design decisions:
- `component_type` on every node (not just top-level) enables polymorphic deserialization.
- Separate `control_flow_connections` and `data_flow_connections` — execution order vs. data
  routing are different concerns. **This is the right separation for Orchestra.**
- `{{placeholder}}` syntax for auto-generating typed inputs.
- JSON Schema for input/output contracts.

### n8n (workflow JSON)

n8n stores workflows as JSON blobs in a database, not as files. Key lesson: **file-based
storage is better for developer workflows** (git-diffable, reviewable, composable). n8n's
approach works for hosted SaaS but is hostile to code review. Orchestra should keep YAML
in files.

n8n's "Code" node accepts JavaScript. Error handling inside code nodes is the user's
responsibility — n8n surfaces exceptions as node-level failures with a red border and
the raw JS error. Lesson: **when a code escape hatch throws, surface the original exception
with file + line, not a wrapped generic error**.

### Dify limitations (lessons from its failures)

Dify's most-cited limitation: structured input/output between nodes only supports 1-level
depth. Users immediately hit this wall when trying to pass nested objects between agents.
**Orchestra's YAML must support nested state schema from day one** — this is a critical
differentiator. Use JSON Schema `$ref` or Pydantic model references for nested types.

Flowise's limitation: logic control is only if/else. No loops, no parallel fan-out in the
UI. **Orchestra's YAML already has parallel edges** — the `add_parallel` pattern must be
expressible in YAML.

### LangGraph (no native YAML, but Open Agent Spec provides an adapter)

LangGraph 1.0 (October 2025) is code-first. The Open Agent Spec provides a LangGraph
runtime adapter that translates Agent Spec YAML into LangGraph primitives. This confirms
the architecture: **Orchestra's YAML layer should compile to the existing `WorkflowGraph`
Python API** — it's an adaptation layer, not a rewrite.

---

## 3. Tool / Plugin Discovery Patterns

### pytest's conftest.py model

pytest discovers `conftest.py` files by walking upward from the test directory. Each
`conftest.py` is imported and its fixtures/hooks become available in that directory scope.
Key design insight: **conftest.py is scoped, not global** — a conftest at `tests/unit/`
only affects tests under `tests/unit/`. This is the right model for `tools/`: tools
defined in a subdirectory are scoped to workflows in that subdirectory unless promoted
to the top level.

pytest also uses `pytest11` entry points for installed plugins. The two-tier model (local
conftest + installed packages) maps cleanly to Orchestra: **local `tools/` directory for
project-specific tools, entry points for shared tool packages**.

### setuptools entry points / importlib.metadata

Modern approach (Python 3.12+): `importlib.metadata.entry_points(group='orchestra.tools')`.
Entry points are declared in `pyproject.toml`:

```toml
[project.entry-points."orchestra.tools"]
search = "mypackage.tools:search_tool"
```

This is the right mechanism for tool packages that are shared across projects. Key
properties:
- No file scanning required — the metadata is indexed at install time.
- Lazy: entry points return `EntryPoint` objects; `.load()` only imports when called.
- Safe: only installed packages can contribute.
- `importlib.metadata` is stdlib (no `pkg_resources` dependency needed).

**Do not use `pkg_resources`** — it is deprecated and 10x slower than `importlib.metadata`.

### pluggy (pytest's plugin framework)

pluggy provides hook specifications, implementations, and call ordering. Its key
contribution is **hook call ordering** (LIFO by default, `tryfirst`/`trylast` markers).
For Orchestra's tool discovery, pluggy is probably overkill — the simpler `@tool` decorator
registry is sufficient. But pluggy's `PluginManager.check_pending()` pattern is worth
borrowing: after loading all plugins, verify that every declared hook has at least one
implementation. Orchestra equivalent: after loading all YAML files, verify every `tool:`
reference resolves to a registered `@tool` function.

### AST scanning vs. import-based scanning

**AST scanning (safe but limited):**
- Parse Python files with `ast.parse()` without executing them.
- Find decorated functions: look for `ast.FunctionDef` nodes with decorator names matching
  `tool` or `orchestra.tools.tool`.
- Advantages: no code execution, no side effects, fast.
- Limitations: cannot evaluate dynamic decorators (`@tool(name=compute_name())`), cannot
  resolve re-exports, cannot see conditionally defined tools.

**Import-based scanning (powerful but risky):**
- `importlib.util.spec_from_file_location()` + `exec_module()`.
- Discovers all `@tool` decorated objects because the decorator side-effect fires on import.
- Risk: arbitrary code in module body executes (database connections open, network calls
  fire, `sys.path` gets mutated).

**Recommendation for Orchestra:** Use a **two-phase approach**:
1. AST scan to build a manifest of expected tool names and their source files.
2. Only import files that the manifest says contain tools.
3. After import, reconcile: if AST scan found `search` but import produced no `search`
   registration, emit a clear error.

This does not prevent malicious code — any file imported still executes. The AST phase
provides a human-readable manifest, not a security boundary.

---

## 4. YAML Schema Design for Agent Systems

### Versioning

Always include a `version` field. Use it as a schema version, not a data version:

```yaml
version: "1"   # schema version — controls which parser to use
name: my_agent
```

The field should be a **string** (`"1"`, `"2"`), not a float (`1.0` vs `1` are the same
YAML scalar — ambiguous). Use integer strings. On load, dispatch to the correct Pydantic
model for that version:

```python
VERSION_MODELS = {"1": AgentConfigV1, "2": AgentConfigV2}
model_cls = VERSION_MODELS.get(raw["version"])
```

Never break schema compatibility without a version bump. Provide a migration function
`upgrade_v1_to_v2(data: dict) -> dict` and run it automatically on load.

### Pydantic + ruamel.yaml (Orchestra already uses this)

Orchestra already uses `ruamel.yaml` for round-trip YAML (comment-preserving). The
auto-discovery layer should add Pydantic models as the validation layer:

```python
class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")   # error on unknown keys
    version: str = "1"
    name: str
    system_prompt: str
    provider: str | None = None
    model: str | None = None
    tools: list[str] = []    # tool names — resolved against tool registry
    max_iterations: int = 10
    memory: bool = False
```

`extra="forbid"` is critical: it catches typos like `systm_prompt` immediately rather
than silently ignoring the field.

### Avoiding YAML hell

YAML hell symptoms: deeply nested anchors, `!!python/object` tags, multi-document files,
boolean ambiguity (`yes`/`no`/`on`/`off`). Mitigations:

- **Use `YAML(typ="safe")`** (ruamel safe loader). Orchestra's `dynamic.py` already does
  this. Never use the default loader for untrusted YAML.
- **Ban `!!` tags entirely**. Validate that no YAML scalar starts with `!`.
- **Limit nesting to 3 levels.** If a workflow needs more, it should be split.
- **Explicit string quotes for ambiguous values.** Emit a lint warning if an unquoted
  value looks like a boolean or number but is used in a string context.
- **Anchors (`&`) and aliases (`*`) are safe** for DRY YAML but document them. Forbid
  merge keys (`<<:`) in agent configs — they create surprising inheritance chains.

### Expressiveness vs. simplicity balance

The expressiveness ceiling for YAML: data, structure, and simple conditionals. The
moment a user needs to express logic (loops over dynamic data, error recovery, custom
retry strategies), they should drop to Python. The YAML schema should have a
**hard logical limit** and a clear, documented escape hatch to Python (see Section 6).

**Do not put Jinja2 or any template engine inside YAML values.** CrewAI's `{placeholder}`
pattern (simple string substitution) is acceptable. Full Jinja2 (conditionals, loops,
filters inside YAML strings) creates a language-inside-a-language that is impossible to
validate statically.

---

## 5. Hot-Reload Patterns

### What the frameworks do

**Vite / webpack HMR**: Module-level hot replacement. When a file changes, only the
changed module and its dependents are re-evaluated. State in unchanged modules is
preserved. This works because JavaScript modules have explicit import graphs — the
framework knows exactly what depends on what.

Python does not have this. Python's import system has no native invalidation mechanism.
`importlib.reload()` is unreliable for anything but the simplest modules.

**uvicorn `--reload`**: Uses `watchfiles` to detect changes, then sends SIGTERM to the
worker and restarts it. Full process restart — not module-level. Safe but slow (500ms+
restart time). **This is what Orchestra should do for Python tool files** — full process
restart on Python change.

**Django `runserver`**: Same approach as uvicorn — watches for Python file changes and
restarts the dev server. Django's key insight: **don't try to reload Python; restart
the process**. YAML config changes can be hot-reloaded because YAML is data. Python
changes require a restart because Python execution has side effects.

### Safe boundaries for Orchestra hot-reload

Orchestra already has `GraphHotReloader` in `src/orchestra/core/hotreload.py` which
watches YAML files and atomically swaps graphs into `GraphRegistry`. This is correct
for the YAML layer.

The two-boundary rule:

| Resource type | Reload strategy | Rationale |
|---|---|---|
| `workflows/*.yaml` | Hot-reload (atomic swap) | Pure data, no side effects |
| `agents/*.yaml` | Hot-reload (atomic swap) | Pure data |
| `tools/*.py` | Process restart | Imports execute code; module state is unpredictable |
| `tools/*.yaml` (if added) | Hot-reload | Data only |

**Do not attempt live Python reloading.** Frameworks that try (e.g., `reloader` packages)
consistently produce subtle bugs: old class instances with new class definitions, stale
references in closures, partially-initialized modules.

### In-flight protection

The `GraphHotReloader` correctly logs an error and keeps the old graph if YAML fails to
parse. The pattern to extend: maintain a **generation counter** per graph name. When a
hot-reload succeeds, increment the counter. Running workflows hold a reference to the
graph at their generation — they are not interrupted. New requests pick up the new
generation. This is analogous to how nginx handles config reloads (graceful workers drain).

---

## 6. Escape Hatches: Where YAML Ends and Python Begins

### The Deno principle

Deno's engineering blog (researched above) identifies three escape hatch patterns in
low-code platforms:
1. **Data transformation nodes** — inline code that transforms data between steps.
2. **Custom HTTP connectors** — code that handles webhooks/custom APIs.
3. **Custom UI components** — code that renders custom visualizations.

For Orchestra, the analogues are:
1. **Custom routing functions** — `lambda state: state["category"]` cannot be expressed
   in YAML. Routing logic stays Python.
2. **Custom tool implementations** — the `@tool` decorator IS the escape hatch. Tools
   are always Python.
3. **Custom state reducers** — `Annotated[dict, merge_dict]` semantics cannot be
   expressed in YAML. State schemas stay Python.

### The explicit boundary contract

Define the boundary in the docs and enforce it in the schema:

**What YAML can express:**
- Agent identity (name, system_prompt, model, tools list by name)
- Graph topology (nodes, edges, entry point, max_turns)
- Parallelism (parallel fan-out, join node name)
- Simple conditional routing IF the routing function is a named Python callable
  already registered in the tool registry

**What YAML cannot express (must be Python):**
- Routing logic (arbitrary `lambda` or function body)
- State schema and reducers
- Tool implementation
- Custom retry/error handling

### Referencing Python from YAML

The current `dynamic.py` uses `ref: "orchestra.tools.web_search"` — a dotted import
path. This is the right mechanism. Extend it for routing functions:

```yaml
edges:
  - source: classifier
    type: conditional
    condition: myproject.routing.route_by_category  # dotted path
    paths:
      a: path_a
      b: path_b
```

The `SubgraphBuilder.resolve_ref()` already enforces an allowlist of prefixes. For
user projects, the allowlist should be extended to include the project's own package
prefix. The `orchestra.yaml` project config file (see Section 8) can declare:

```yaml
allowed_prefixes:
  - "orchestra."
  - "myproject."
```

### n8n's code node as the template

n8n exposes a "Code" node where users write JavaScript. The node has access to the
workflow context (`$input`, `$workflow`). **Orchestra should NOT implement an equivalent
inline Python eval node** — the security implications are severe and the right answer
is always "write a `@tool` function". The `@tool` decorator is the escape hatch.

---

## 7. Error Reporting in Declarative Systems

### What good errors look like

**Terraform's model (best in class):**
```
Error: Invalid reference
  on main.tf line 42, in resource "aws_instance" "web":
  42:   ami = var.ami_id

A managed resource "aws_instance" "web" has not been declared.
Did you mean var.ami_image_id?
```

Key properties: file + line, the bad value quoted, what was expected, a did-you-mean
suggestion. Terraform achieves this because HCL is parsed into an AST with position
information, not plain dict parsing.

**Kubernetes validation errors:**
Kubernetes uses `field.NewPath("spec").Child("containers").Index(0).Child("image")` to
build structured field paths. Error output: `spec.containers[0].image: Required value`.
The path is machine-readable AND human-readable.

**GitHub Actions (negative example):**
GitHub Actions YAML errors are notoriously opaque — "Unexpected value 'on'" with no
line number in many cases. The workflow is validated server-side after push, not locally.
Lesson: **validate eagerly, locally, with line numbers**.

### Recommendations for Orchestra

**1. Use ruamel.yaml's position tracking.**
`ruamel.yaml` preserves `lc` (line/column) information on parsed dicts and lists.
When a Pydantic validation error fires, look up the field's position:

```python
raw = yaml.load(text)
# raw["nodes"]["classifier"]["ref"] has raw["nodes"]["classifier"].lc.value("ref")
# which returns (line, col)
```

**2. Error message template for every common failure mode:**

| Failure | Message pattern |
|---|---|
| Unknown YAML key | `agents/researcher.yaml:12: Unknown field 'systm_prompt'. Did you mean 'system_prompt'? Valid fields: name, system_prompt, model, tools, ...` |
| Tool ref not found | `workflows/pipeline.yaml:8: Tool 'web_serch' is not registered. Available tools: web_search, read_file, write_file. Check tools/ directory or installed packages.` |
| Agent ref not found | `workflows/pipeline.yaml:15: Agent 'clasifier' not found. Available agents: classifier, researcher, writer.` |
| Circular edge | `workflows/pipeline.yaml: Circular edge detected: researcher → classifier → researcher. Cycles require explicit loop-breaking conditions.` |
| Missing entry_point | `workflows/pipeline.yaml: 'entry_point' is required. Found nodes: researcher, writer. Set 'entry_point: researcher' to start there.` |
| YAML parse error | `workflows/pipeline.yaml:23: YAML syntax error — unexpected ':' in value. Hint: Quote string values containing colons: "value: with colon"` |

**3. Validate at load time, not at runtime.**
All reference resolution (tool names, agent names, edge targets) must be checked when
`orchestra up` starts, before any workflow runs. Runtime discovery of a missing tool
after 10 minutes of processing is unacceptable.

**4. Provide a `orchestra validate` command.**
Run validation without starting the server. Output: list of all discovered agents, tools,
and workflows with their resolved references. Exit non-zero on any error. This is
equivalent to `terraform validate` and should be part of CI.

---

## 8. Security in Auto-Discovery

### The threat model

The realistic threat for an internal developer tool (which Orchestra is) is not a
malicious external attacker but **accidental code execution** — a test fixture, a
vendored script, or a CI helper gets discovered and imported, executing database
migrations or sending Slack messages on startup.

The threat for a hosted/multi-tenant Orchestra deployment is more serious: a tenant's
tool file executes in the same process as other tenants' tools.

### Layer 1: Directory bounding (always apply)

Only scan files inside the declared project directories. Never recurse outside:

```
agents/     → *.yaml only
tools/      → *.py files with @tool decorator
workflows/  → *.yaml only
```

Never scan `node_modules/`, `.git/`, `__pycache__/`, or any hidden directory.

### Layer 2: AST pre-scan (apply before import)

Use `ast.parse()` on every `.py` file before importing:
- Reject files with top-level `exec()`, `eval()`, `__import__()` calls.
- Reject files that import from `os`, `subprocess`, `socket` at the top level (these
  might be legitimate — emit a WARNING, not an error, and require explicit `--allow-unsafe`).
- Collect all `@tool` decorated function names.

This does NOT prevent all risks (see the asteval CVE above — AST manipulation can bypass
static checks) but it catches the most common accidents.

### Layer 3: Import allowlisting (Orchestra already has this)

`SubgraphBuilder.resolve_ref()` already enforces `DEFAULT_ALLOWED_PREFIXES`. Extend
this to the tool import layer: only files under the project's declared `tool_dirs` are
imported during auto-discovery. A `tools/../../etc/passwd` path traversal attempt is
rejected by normalizing paths against the project root.

### Layer 4: For multi-tenant / hosted deployments

**Do not run user tools in the same process.** The options in order of security:

1. **subprocess isolation** — run each tool as a subprocess with a restricted environment.
   Slowest but safest. Good for hosted.
2. **Docker/gVisor** — container per tenant. E2B, Modal, and similar services do this.
3. **Wasm sandbox** — Orchestra already has a Wasm sandbox module (`security/`). Route
   untrusted tool code through it.

For the `orchestra up` local developer experience, subprocess isolation is not needed.
The import risk is the same as running any Python script. Document this clearly.

### What NOT to do

- **Do not use `RestrictedPython` as a sole defense** — it is bypassable (documented
  CVEs exist).
- **Do not use AST evaluation (asteval) as a sandbox** — CVE GHSA-vp47-9734-prjw shows
  that AST manipulation bypasses its safety checks.
- **Do not exec YAML values as Python expressions** — if a YAML field says `eval: true`,
  the value must still be a static reference, not an expression.

---

## 9. Synthesized Recommendations for Orchestra

### The `orchestra up` command — proposed design

```
myproject/
  orchestra.yaml           # project config (allowed_prefixes, env, server settings)
  agents/
    researcher.yaml        # AgentConfig v1
    writer.yaml
  tools/
    search.py              # contains @tool decorated functions
    file_ops.py
  workflows/
    pipeline.yaml          # WorkflowGraph YAML (nodes + edges)
    daily_report.yaml
```

**Startup sequence:**

1. Load `orchestra.yaml` (project config — schema version, allowed prefixes, server config).
2. AST-scan `tools/*.py` — build tool manifest.
3. Import `tools/*.py` — register all `@tool` objects into `ToolRegistry`.
4. Validate tool manifest against registry — error on any discrepancy.
5. Load `agents/*.yaml` — validate against `AgentConfig` Pydantic model.
6. Load `workflows/*.yaml` — validate all tool refs and agent refs against step 3/5 registries.
7. Compile workflows into `CompiledGraph` objects — register into `GraphRegistry`.
8. Start `GraphHotReloader` watching `agents/` and `workflows/` (YAML only).
9. Start HTTP server.

**Hot-reload applies to:** steps 5, 6, 7 (YAML changes only).
**Requires restart:** steps 2, 3, 4 (Python changes).

### Recommended YAML schema for Orchestra agents

```yaml
version: "1"
name: researcher
system_prompt: |
  You are a senior research analyst. You find accurate, cited information.
model: claude-sonnet-4-6          # optional — falls back to project default
tools:
  - web_search
  - read_file
max_iterations: 10
memory: false
```

### Recommended YAML schema for Orchestra workflows

```yaml
version: "1"
name: research_pipeline
entry_point: classifier
max_turns: 50

nodes:
  classifier:
    type: agent
    agent: classifier              # ref to agents/classifier.yaml
    output_key: category

  researcher:
    type: agent
    agent: researcher
    output_key: findings

  writer:
    type: agent
    agent: writer
    output_key: report

edges:
  - source: classifier
    type: conditional
    condition: myproject.routing.route_by_category
    paths:
      research: researcher
      write: writer

  - source: researcher
    target: writer

  - source: writer
    target: __end__
```

### What to build first (priority order)

1. `orchestra validate` CLI command — validates YAML without starting server.
2. `AgentConfig` and `WorkflowConfig` Pydantic models with `extra="forbid"`.
3. `ToolDiscovery` class: AST scan → import → registry reconciliation with clear errors.
4. `AgentLoader`: loads `agents/*.yaml` and resolves tool refs against `ToolRegistry`.
5. `WorkflowLoader`: loads `workflows/*.yaml`, calls `load_graph_yaml()` (already exists).
6. `orchestra up` command: runs all steps in the startup sequence above.
7. Extend `GraphHotReloader` to also watch `agents/` directory.
8. Add `orchestra.yaml` project config file with `allowed_prefixes` and default model.

---

## 10. Anti-Patterns Summary

| Anti-pattern | Why it's bad | Better approach |
|---|---|---|
| Scanning `sys.path` globally | Picks up test fixtures, CI helpers | Bound to declared directories only |
| Silent collision on duplicate tool name | Hidden bugs, last-writer-wins | Loud error with both file paths |
| YAML template engine (Jinja2 in YAML) | Language-in-a-language, unvalidatable | `{placeholder}` substitution only |
| `importlib.reload()` for Python hot-reload | Stale references, partial state | Restart process; hot-reload YAML only |
| `RestrictedPython` as sole sandbox | Multiple known bypass CVEs | Use subprocess/Docker for untrusted code |
| Runtime ref resolution (discover missing tool mid-run) | Silent failure after long run | Validate ALL refs at startup |
| Float version field (`version: 1.0`) | YAML type ambiguity | String version field (`version: "1"`) |
| Merge keys (`<<:`) in YAML | Surprising inheritance | Explicit fields only |
| `pkg_resources` for entry point discovery | Deprecated, 10x slower | `importlib.metadata.entry_points()` |
| Deeply nested YAML (4+ levels) | Hard to read, hard to validate | Split into sub-workflows or Python |
| No `orchestra validate` command | Errors discovered at runtime | Eager validation CLI command |
| `extra="allow"` in Pydantic schema | Typos silently ignored | `extra="forbid"` always |
