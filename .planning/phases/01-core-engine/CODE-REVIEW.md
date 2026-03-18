# Phase 1 Code Review — Orchestra Core Engine

**Reviewer:** code-reviewer agent
**Date:** 2026-03-07
**Scope:** All source files in Phase 1 implementation (committed + uncommitted changes)
**Baseline:** Verification report at `01-VERIFICATION.md` (3/5 criteria, 4 test failures)

---

## Overall Quality Assessment

Orchestra's Phase 1 implementation is **structurally sound and architecturally coherent**. The foundational decisions are correct: Pydantic for typed state, `Annotated` reducers for parallel fan-in, Protocol-based duck typing for providers, frozen dataclasses for edges/nodes, and structlog for observability. These are the right choices for a production-grade framework.

The code is clean, readable, and well-documented. Error messages follow a consistent "what happened / how to fix" three-part format that is genuinely developer-friendly. The module boundaries are clean with one exception (the `SubgraphNode` deferred import in `graph.py`).

**The primary concerns are:**
1. A cluster of correctness bugs in the loop/parallel fluent API
2. Security: `eval()` in a test function that the framework's tool system could reach in production
3. Missing `__node_execution_order__` key being mutated on the returned state dict (caller-visible side effect)
4. Loop counter using closure-captured mutable state, which makes the graph non-reentrant
5. Incomplete type annotations at the boundary between the `Any`-typed internal state dict and the typed `WorkflowState`

The codebase is **close to shippable** but has a handful of issues that must be resolved before the "all tests pass, lint clean, type-check passes" bar is met.

---

## Critical Issues (Must Fix Before Shipping)

### C1 — Loop Counter Is Not Thread-Safe and Breaks Concurrent Runs

**File:** `src/orchestra/core/graph.py` lines 344–361

```python
counters: dict[str, int] = {}

def _loop_condition(state: dict[str, Any]) -> Any:
    count = counters.get(loop_id, 0) + 1
    counters[loop_id] = count
    ...
```

The `counters` dict is captured in a closure over the `loop()` method call. A single `CompiledGraph` instance is meant to be reusable (tests explicitly verify this with `test_loop_counter_resets_between_runs`). But if two coroutines call `compiled.run()` concurrently, they share the same `counters` dict and will corrupt each other's loop state. The counter "resets" only because the last run removes the key at exit — which is not atomic.

More immediately: the `test_loop_repeats_until_condition_false` and `test_loop_respects_max_iterations` tests check specific count values that depend on exactly how many times the condition is evaluated. The off-by-one behavior (`count >= max_iterations` vs `count > max_iterations`) needs a test that documents exactly what iteration N means: does `max_iterations=3` produce 3 or 4 executions of the loop body?

**Fix:** Move counter state into `CompiledGraph.run()`'s local context rather than the closure. Pass a `run_counters: dict[str, int]` into `_resolve_next` so each call to `run()` has its own counter scope. Alternatively, store counters in `ExecutionContext` (which is created fresh per `run()` call).

---

### C2 — `apply_state_update` Raises on Unknown Fields, Breaking Dict-State Workflows with Internal Keys

**File:** `src/orchestra/core/compiled.py` line 152; `src/orchestra/core/state.py` line 127

```python
result["__node_execution_order__"] = node_execution_order
```

The `__node_execution_order__` sentinel key is injected into the final state dict returned by `CompiledGraph.run()`. When the caller uses a typed `WorkflowState` schema, `apply_state_update` raises `StateValidationError` for any key not in the schema. This key is injected after the run completes (on the dict after `model_dump()`), so it does not hit that path — but it does mean the returned `state` dict in `RunResult` contains this internal key, which is then visible in `result.state`. The `runner.py` does pop it correctly:

```python
node_order = final_state.pop("__node_execution_order__", [])
```

But `CompiledGraph.run()` itself returns the dict with the key still in it, which means any caller who uses `compiled.run()` directly (without going through `run()`) gets a polluted state dict. This is a leaky abstraction: internal implementation details are surfacing in the public return value.

**Fix:** Do not inject `__node_execution_order__` into the state dict. Track it as a separate local variable and return it as part of a dedicated result object, or wrap `CompiledGraph.run()` to return a `(state_dict, execution_metadata)` tuple internally.

---

### C3 — `_parallel_nodes` Is Instance State, Not Run State

**File:** `src/orchestra/core/graph.py` lines 203–204

```python
self._parallel_nodes = node_names
self._last_node = None  # Must call .join() next
```

`_parallel_nodes` is written to `self` as a dynamic instance attribute (not declared in `__init__`). This means:
- The `WorkflowGraph` class has an undeclared attribute that only exists after `.parallel()` is called
- `hasattr(self, "_parallel_nodes")` is used to guard `.join()`, which is a fragile pattern
- If `.parallel()` is called twice without `.join()`, the second call silently overwrites `_parallel_nodes`, corrupting the first parallel group
- mypy and type checkers cannot reason about an attribute that appears dynamically

**Fix:** Initialize `self._parallel_nodes: list[str] | None = None` in `__init__`, and use `is not None` checks instead of `hasattr`. Raise `GraphCompileError` if `.parallel()` is called while `_parallel_nodes is not None` (i.e., a previous `.parallel()` has not been joined yet).

---

### C4 — `eval()` in Test Demonstrates a Security Pattern That Should Be Explicitly Warned Against

**File:** `tests/unit/test_core.py` line 679

```python
@tool
async def calculator(expression: str) -> str:
    """Evaluate a math expression."""
    return str(eval(expression))
```

This is in a test, not production code, but it presents a material risk: new contributors reading these tests will copy this pattern into real agent implementations. The Orchestra tool system is designed to give LLM agents callable functions. A tool that calls `eval()` on LLM-provided input is a remote code execution vulnerability. If a malicious prompt causes the agent to call `calculator` with `expression="__import__('os').system('rm -rf /')"`, the host process executes arbitrary code.

The test itself is not broken, but the pattern is dangerous to normalize. A safer alternative for the test is integer arithmetic via `ast.literal_eval()` or hardcoded responses.

**Fix (test):** Replace `eval(expression)` with a safe equivalent. A comment in the test noting that `eval()` in a real tool is an RCE risk would serve as a teachable moment rather than a footgun.

---

### C5 — `ConditionalEdge.resolve()` Silently Falls Through on Unknown Keys

**File:** `src/orchestra/core/edges.py` lines 39–43

```python
def resolve(self, state: dict[str, Any]) -> Any:
    result = self.condition(state)
    if self.path_map and isinstance(result, str):
        return self.path_map.get(result, result)
    return result
```

When a `path_map` is provided and the condition returns a key that is not in the map, `dict.get(result, result)` falls back to returning the key itself as a node ID. If that string is not a valid node name, the execution engine will raise a `GraphCompileError` at runtime with a confusing message ("Node 'unknown_key' not found during execution").

This is worse than a KeyError because the error message does not identify the source: the developer sees a missing node error but cannot tell that the root cause is a bad condition return value.

**Fix:** Raise a descriptive `GraphCompileError` (or a new `InvalidRouteError`) when `path_map` is provided but the condition returns a key not in it. The message should name the condition function, the returned key, and the available keys.

---

## Important Issues (Should Fix Soon)

### I1 — `HttpProvider` Client Is Never Closed; Resource Leak

**File:** `src/orchestra/providers/http.py` lines 101–106

```python
self._client = httpx.AsyncClient(
    base_url=self._base_url,
    timeout=timeout,
    headers=self._build_headers(),
)
```

`HttpProvider` creates an `httpx.AsyncClient` in `__init__` and exposes `aclose()`, but nothing forces the caller to close it. There is no `async with` context manager support, no `__aenter__`/`__aexit__`, and no warning when the client is garbage-collected with open connections. In the test suite, `ScriptedLLM` is used so this is never triggered in tests, but any production workflow will leak the connection pool.

The same issue exists in `AnthropicProvider`.

**Fix:** Implement `__aenter__` and `__aexit__` on both providers to support `async with HttpProvider(...) as provider:`. Additionally, implement `__del__` with a warning if `aclose()` was not called. Consider accepting an externally-created `httpx.AsyncClient` as an optional constructor argument to allow sharing/lifecycle management at the caller level.

---

### I2 — `run()` in `runner.py` Creates a Second `ExecutionContext` After `CompiledGraph.run()` Creates Its Own

**File:** `src/orchestra/core/runner.py` lines 74–87

```python
context = ExecutionContext(
    run_id=run_id,
    provider=provider,
    config=config or {},
)

start = time.monotonic()
final_state = await compiled.run(
    initial_state=initial_state,
    input=input,
    context=context,
    provider=provider,   # <-- passed BOTH as context AND as a separate kwarg
```

Inside `CompiledGraph.run()`:
```python
if context is None:
    context = ExecutionContext(run_id=uuid.uuid4().hex, provider=provider)
elif provider is not None:
    context.provider = provider   # mutates the context passed from runner.py
```

The `provider` is being passed in twice and `context.provider` is being mutated. This is harmless in practice (same value), but it is confusing: `runner.py` already sets `context.provider = provider` in the constructor, and then `compiled.run()` sets it again if `provider is not None`. The mutation of a passed-in context object is also an unexpected side effect.

**Fix:** In `runner.py`, do not pass `provider=provider` separately to `compiled.run()` since it is already set on the `context` object. In `compiled.run()`, only set `context.provider = provider` if `context.provider is None` (i.e., do not overwrite an already-set provider).

---

### I3 — `_execute_agent_node` Default Input Logic Has a Surprising Fallback Chain

**File:** `src/orchestra/core/compiled.py` lines 215–224

```python
messages = state_dict.get("messages", [])
if isinstance(messages, list) and messages:
    agent_input = messages
else:
    input_text: str = state_dict.get("input", "") or ""
    if not input_text:
        # Use the last output as input
        input_text = state_dict.get("output", "") or ""
    agent_input = input_text
```

The fallback from `messages` → `input` → `output` is implicit behavior that is not documented in the public API or in the agent's docstring. A developer who writes a workflow where neither `messages`, `input`, nor `output` is in the state dict will get an empty string silently passed to the agent — the agent will then ask the LLM with no context. This is a silent failure mode.

The comment `# Use the last output as input` suggests this is intentional chaining behavior for sequential pipelines, but it is not explained to the user.

**Fix:** Document this fallback chain clearly in `BaseAgent.run()` and `AgentNode`. Consider adding a `debug`-level log entry when the fallback chain is activated: `logger.debug("agent_input_fallback", agent=node_id, source="output_field")`. Consider raising a warning (not an error) when the final `agent_input` is empty.

---

### I4 — `_tool_to_schema` on `BaseAgent` Duplicates Logic Already in `ToolRegistry.get_schemas()`

**File:** `src/orchestra/core/agent.py` lines 201–210; `src/orchestra/tools/registry.py` lines 42–58

Both `BaseAgent._tool_to_schema()` and `ToolRegistry.get_schemas()` produce identical OpenAI function-calling schema dicts. This is duplicated logic. If the schema format ever needs to change (e.g., adding `strict: true` for OpenAI's newer structured mode), it must be updated in two places.

**Fix:** Extract the schema format into a single function, preferably on `ToolWrapper` itself as a `to_schema() -> dict[str, Any]` method. Both `BaseAgent` and `ToolRegistry` then delegate to it.

---

### I5 — `DecoratedAgent._original_func` Attribute Is Unused Dead Code

**File:** `src/orchestra/core/agent.py` lines 213–218, 254–256

```python
class DecoratedAgent(BaseAgent):
    """Agent created from a decorated function."""
    _original_func: Any = None
    ...

agent_instance._original_func = func
functools.update_wrapper(agent_instance, func)
```

`_original_func` is set but never read anywhere in the codebase. `functools.update_wrapper` copies `__wrapped__`, `__doc__`, `__name__`, etc. directly, making the separate `_original_func` attribute redundant. The private attribute naming (`_original_func`) further suggests it was intended to be internal, but there is no internal usage.

**Fix:** Remove `_original_func`. If introspection of the original function is needed (e.g., for generating docs), use `agent_instance.__wrapped__` which `functools.update_wrapper` sets. Also note that `functools.update_wrapper(agent_instance, func)` with `type: ignore[arg-type]` is suppressing a legitimate type error — a Pydantic `BaseModel` instance is not a `Callable`, so `update_wrapper` will succeed but only copies the dunder attributes.

---

### I6 — `_handle_error_status` in `AnthropicProvider` Uses Vague Context Detection

**File:** `src/orchestra/providers/anthropic.py` lines 309–316

```python
elif status_code == 400 and "context" in text.lower():
    raise ContextWindowError(...)
```

The substring `"context"` is far too broad. Anthropic returns 400 errors for many reasons: invalid model names, malformed requests, missing required fields. A request that fails because of a field naming error could spuriously raise `ContextWindowError` if the word "context" appears anywhere in the error message (e.g., "context_window_exceeded" or "in this context, the request...").

Compare with `HttpProvider` which correctly checks for `"context_length"` in the text, which is more specific (matching `context_length_exceeded`).

**Fix:** Use a more specific substring, e.g., `"context_window_exceeded"` or check the Anthropic error `type` field in the JSON body (`{"type": "error", "error": {"type": "context_window_exceeded"}}`). Parse the response body as JSON before inspecting it.

---

### I7 — `pyproject.toml` Optional Dependency Is Unused and Misleading

**File:** `pyproject.toml` lines 36–38

```toml
[project.optional-dependencies]
anthropic = ["anthropic>=0.20"]
google = ["google-generativeai>=0.5"]
```

The `AnthropicProvider` in `src/orchestra/providers/anthropic.py` uses `httpx` (already a core dependency) and does not import the `anthropic` SDK at all. The `[anthropic]` optional extra therefore installs a package that is never used. Similarly for `google`.

This creates two problems:
1. Users installing `pip install orchestra-agents[anthropic]` get an unused package installed
2. Users who rely on the `anthropic` SDK being present (thinking Orchestra uses it) will be confused when they discover the HTTP-based adapter

**Fix:** Either remove the SDK optional extras entirely (since both providers use raw HTTP), or implement SDK-based providers that actually use the SDK and move the HTTP providers to the core. Add a comment clarifying the provider strategy.

---

### I8 — `WorkflowGraph._validate()` Does Not Detect Unreachable Nodes

**File:** `src/orchestra/core/graph.py` lines 391–450

The validator checks that every edge source and target exists in nodes, but it does not verify that every node is reachable from the entry point. A user can add an orphan node (`add_node("orphan", fn)`) and the graph will compile and run without error — the orphan node is silently skipped. The `UnreachableNodeError` class exists in `errors.py` but is never raised.

**Fix:** After validating individual edges, perform a reachability check: starting from `_entry_point`, traverse all edges (including conditional path_maps and parallel targets) and build the set of reachable nodes. Any node not in this set should raise `UnreachableNodeError` with the node name. This is the kind of compile-time check that prevents subtle workflow bugs.

---

### I9 — `ScriptedLLM` Is Missing Promised Assertion Helpers

**File:** `src/orchestra/testing/scripted.py`

The verification report notes that `assert_all_consumed()` and `assert_prompt_received()` were specified as deliverables in Task 1.7. These are genuinely useful testing helpers:

- `assert_all_consumed()` — verifies the test used all scripted responses, catching cases where the workflow exited earlier than expected
- `assert_prompt_received(index, pattern)` — verifies the Nth LLM call included a message matching a pattern, enabling prompt-quality assertions

Without `assert_all_consumed()`, a developer might write a 3-response script, have the workflow only consume 2, and the test would pass silently even though the agent behavior was wrong.

**Fix:** Add both methods:
```python
def assert_all_consumed(self) -> None:
    remaining = len(self._responses) - self._index
    if remaining > 0:
        raise AssertionError(
            f"ScriptedLLM has {remaining} unconsumed response(s). "
            f"The workflow completed earlier than expected."
        )

def assert_prompt_received(self, call_index: int, pattern: str) -> None:
    import re
    if call_index >= len(self._call_log):
        raise AssertionError(f"Call {call_index} was never made (only {len(self._call_log)} calls total).")
    messages = self._call_log[call_index]["messages"]
    text = " ".join(m.content for m in messages)
    if not re.search(pattern, text):
        raise AssertionError(f"Pattern {pattern!r} not found in call {call_index} messages.")
```

---

### I10 — `ToolWrapper.execute()` Returns Empty `tool_call_id`

**File:** `src/orchestra/tools/base.py` lines 122–126

```python
return ToolResult(
    tool_call_id="",   # always empty
    name=self.name,
    content=str(result),
)
```

`ToolResult.tool_call_id` is always an empty string from `ToolWrapper.execute()`. The `tool_call_id` is populated by the caller (`BaseAgent._execute_tool`) via the `ToolCall.id` from the LLM response, but `execute()` has no access to it. This is architecturally awkward: the `tool_call_id` field exists on `ToolResult` but the tool itself can never populate it. In practice this works because `BaseAgent._execute_tool` ignores `result.tool_call_id` and builds the `Message` using `tool_call.id` from the call record. But the empty field in the returned `ToolResult` is misleading.

**Fix:** Either remove `tool_call_id` from `ToolResult` (since it is never actually set by tools) and have `BaseAgent` handle the correlation via the call record, or pass `tool_call_id` as a parameter to `execute()`. The protocol in `protocols.py` does not include `tool_call_id` in `execute()`, so changing the protocol would be a breaking change — but it is the cleanest fix.

---

## Minor Issues (Nice to Fix)

### M1 — Deferred Import of `SubgraphNode` Is a Lint Error

**File:** `src/orchestra/core/graph.py` line 64

```python
# Avoid circular import
from orchestra.core.nodes import SubgraphNode  # noqa: E402
```

The `# noqa: E402` suppressor is used to avoid a ruff error for a module-level import that is not at the top of the file. The actual reason is circular import avoidance: `graph.py` imports from `nodes.py`, and `nodes.py` would import from `graph.py` if `SubgraphNode` referenced `CompiledGraph` directly. However, examining `nodes.py`, `SubgraphNode` uses `graph: Any` — so there is no actual type-level circular dependency. The circular import is only at runtime if `nodes.py` were to import from `graph.py`, which it does not.

**Fix:** Move the `SubgraphNode` import to the top of the file alongside the other `nodes` imports. The `# noqa` suppressor indicates a code smell; the correct fix is to restructure so the import can be at the top. If a genuine circular dependency exists, the resolution is to move shared types to a separate module.

---

### M2 — `_wrap_as_node()` Checks for `system_prompt` Attribute to Detect Agents

**File:** `src/orchestra/core/graph.py` lines 49–50

```python
if hasattr(item, "system_prompt") and hasattr(item, "run"):
    return AgentNode(agent=item)
```

This duck-type detection for agents is fragile. Any object with a `system_prompt` attribute and a `run()` method will be treated as an agent. The `Agent` protocol in `protocols.py` is a `@runtime_checkable Protocol` — it should be used here with `isinstance(item, Agent)` for explicit and safe protocol checking.

**Fix:**
```python
from orchestra.core.protocols import Agent as AgentProtocol
if isinstance(item, AgentProtocol):
    return AgentNode(agent=item)
```

---

### M3 — `run_sync()` Will Fail in Environments With a Running Event Loop

**File:** `src/orchestra/core/runner.py` lines 105–122

```python
def run_sync(...) -> RunResult:
    return asyncio.run(run(...))
```

`asyncio.run()` raises `RuntimeError: This event loop is already running` when called from within an existing event loop (Jupyter notebooks, FastAPI applications, other async frameworks). This is a known Python gotcha. The docstring says "for scripts and notebooks" but Jupyter uses a running event loop.

**Fix:** Use `nest_asyncio` (add as optional dep) or detect the running loop and use `loop.run_until_complete()` as a fallback:
```python
try:
    loop = asyncio.get_running_loop()
except RuntimeError:
    loop = None

if loop and loop.is_running():
    # Running inside an event loop (Jupyter, etc.)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, run(...))
        return future.result()
else:
    return asyncio.run(run(...))
```

---

### M4 — `BaseAgent` Uses `model: str = "gpt-4o-mini"` as Default, Leaking Provider Choice into the Base Class

**File:** `src/orchestra/core/agent.py` line 46

```python
model: str = "gpt-4o-mini"
```

The base class encodes an OpenAI-specific model name as the default. A developer who creates a `BaseAgent` subclass and uses `AnthropicProvider` without overriding `model` will send an invalid model name to Anthropic's API. The default is provider-specific but the base class is meant to be provider-agnostic.

**Fix:** Default to `model: str = ""` and have the execution engine fall back to `provider.default_model` when `agent.model` is empty. Or document clearly in the class docstring that `model` must be set to a value supported by the configured provider.

---

### M5 — `ToolCallRecord.result` Is Non-Optional `str` but `ToolResult.content` Can Functionally Be Empty

**File:** `src/orchestra/core/types.py` line 47

```python
class ToolCallRecord(BaseModel):
    tool_call: ToolCall
    result: str          # non-optional
    error: str | None = None
```

In `BaseAgent._execute_tool()`:
```python
ToolCallRecord(
    tool_call=tool_call,
    result=tool_result.content,  # may be "" when there is an error
    error=tool_result.error,
)
```

When a tool fails, `ToolResult.content` is `""` and `ToolResult.error` is set. The `ToolCallRecord.result` is then `""` — a valid but misleading value. Callers inspecting `record.result` will see an empty string without knowing to also check `record.error`.

**Fix:** Change `result` to `result: str | None = None` and set it to `None` when there is an error. This makes the success/failure distinction explicit: non-None result means success, None means check `error`.

---

### M6 — `HttpProvider` Leaks `asyncio` Import Inside `_request_with_retry`

**File:** `src/orchestra/providers/http.py` lines 248–252

```python
except (RateLimitError, ProviderUnavailableError) as e:
    last_error = e
    if attempt < self._max_retries:
        import asyncio   # imported inside a hot retry loop

        delay = min(2**attempt, 30)
        await asyncio.sleep(delay)
```

`import asyncio` inside a retry loop is a minor performance and style issue. Python caches module imports so it is not a significant overhead, but it is unconventional and confusing (suggests `asyncio` is an optional dep that might not be available). The same pattern appears in `AnthropicProvider`.

**Fix:** Move `import asyncio` to the top of both provider files. `asyncio` is part of the Python standard library and has been a core dependency since Python 3.4.

---

### M7 — `to_mermaid()` Generates Invalid Mermaid for Nodes with Special Characters in Names

**File:** `src/orchestra/core/compiled.py` lines 337–381

```python
lines.append(f'    {node_id}["{agent_name}"]')
```

Node IDs can contain underscores, hyphens, and any string returned by `_get_node_name()`. Agent names could contain spaces, apostrophes, or special characters (e.g., `"research & analysis"`). Injecting these directly into Mermaid syntax without escaping will produce invalid diagrams or, in a web context, potentially enable diagram injection if agent names are user-supplied.

**Fix:** Sanitize node IDs to alphanumeric-plus-underscore before use in Mermaid output:
```python
def _safe_mermaid_id(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)
```

---

### M8 — `WorkflowGraph.compile()` Auto-Appends `END` Edge But Does Not Update `_last_node`

**File:** `src/orchestra/core/graph.py` lines 370–378

```python
if self._last_node is not None:
    has_outgoing = any(...)
    if not has_outgoing:
        self.add_edge(self._last_node, END)
```

This side-effectful mutation of `self._edges` happens inside `compile()`. If `compile()` is called twice on the same `WorkflowGraph`, the second call will add a second `END` edge for the last node (because `_last_node` is still set and the first auto-added edge is already in `self._edges`, but the `has_outgoing` check will find it and skip — actually this is fine). However, the broader issue is that `compile()` mutates builder state. A `WorkflowGraph` should be considered "sealed" after compilation, but there is nothing preventing further mutations to the builder after `compile()`.

**Fix:** Set a `_compiled: bool = False` flag in `__init__`, set it to `True` in `compile()`, and raise `GraphCompileError` on any mutation attempt after compilation. This guards against the footgun of modifying a graph that is already running.

---

### M9 — `TokenUsage` Total Not Validated Against Input + Output Sum

**File:** `src/orchestra/core/types.py` lines 61–67

```python
class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
```

`total_tokens` is a separate field that must be manually kept consistent with `input_tokens + output_tokens`. In `BaseAgent.run()`:
```python
total_usage.total_tokens += response.usage.total_tokens
```

This works as long as providers correctly populate `total_tokens`. In `HttpProvider._parse_response()`:
```python
total_tokens=input_tok + output_tok,
```

Correctly computed. But nothing prevents a custom provider from setting `total_tokens=0` while `input_tokens=100`. The field is redundant and error-prone.

**Fix:** Make `total_tokens` a `@property` (computed from `input_tokens + output_tokens`) or add a Pydantic `model_validator` that asserts consistency, or just remove it and compute on access.

---

### M10 — `cli/main.py` `run` Command Has No Error Handling for Import Failures

**File:** `src/orchestra/cli/main.py` lines 86–109

```python
spec.loader.exec_module(module)
```

If the workflow file has a syntax error, a missing import, or raises on load, this line will raise an uncaught exception and print a raw Python traceback to the user instead of a clean error message. The verification report notes "CLI error handling" as a human-verification item.

**Fix:** Wrap `spec.loader.exec_module(module)` in a `try/except Exception` block and print a user-friendly error:
```python
try:
    spec.loader.exec_module(module)
except SyntaxError as e:
    console.print(f"[red]Syntax error in {workflow_file}:[/red] {e}")
    raise typer.Exit(1)
except Exception as e:
    console.print(f"[red]Error loading {workflow_file}:[/red] {e}")
    raise typer.Exit(1)
```

---

## Positive Observations (What Is Done Well)

**Error Message Quality:** The three-part error message pattern (`what happened / where / how to fix`) used throughout the codebase is excellent. `GraphCompileError` messages like:
```
Node 'research' already exists.
  Fix: Use a unique name for each node.
```
...are significantly better than the typical terse Python exception messages. This is a first-class developer experience feature.

**Reducer System Design:** The `Annotated[list[Message], merge_list]` pattern for declaring state reducers is elegant and composable. It uses Python's native type annotation system rather than a custom DSL, which means IDE tooling, mypy, and documentation generators understand it natively. The 9 built-in reducers cover the common cases well. `apply_state_update` producing a new state instance (immutable update) is the correct design.

**Protocol-Based Extensibility:** Using `@runtime_checkable` Protocol for `Agent`, `Tool`, `LLMProvider`, and `StateReducer` is the right design. It enables duck-typed extensibility without inheritance coupling. A developer can implement their own provider by satisfying the protocol without subclassing Orchestra classes.

**`_EndSentinel` Singleton:** The singleton pattern for `END` with proper `__eq__`, `__hash__`, and `__repr__` is clean. The `==` check works correctly regardless of import path. Many frameworks get this wrong by using a string sentinel that collides with user values.

**Frozen Dataclasses for Edges and Nodes:** Using `@dataclass(frozen=True)` for `Edge`, `ConditionalEdge`, `ParallelEdge`, `AgentNode`, `FunctionNode`, and `SubgraphNode` prevents accidental mutation of graph structure after construction. This is the correct design for objects that represent compiled graph structure.

**`ScriptedLLM` Design:** The scripted mock LLM approach is correct for deterministic testing. The `call_log` property enables post-hoc assertions on what messages were sent. The `ScriptExhaustedError` with a clear message is better than returning a default or raising a generic `IndexError`.

**Fluent API Ergonomics:** The `.then().parallel().join().branch()` fluent API composes well for simple cases and is genuinely intuitive. The auto-naming from `_get_node_name()` reduces boilerplate. The auto-appending of `END` edges on `compile()` removes a common footgun.

**Structured Logging:** Using `structlog` with both console (dev) and JSON (production) modes is production-ready. The `get_logger(__name__)` pattern in every module is consistent and correct.

**Test Quality:** The 50+ unit tests cover the most important behaviors: types, reducers, graph construction, execution, routing, tools, and scripted LLM integration. The test names are descriptive and the test structure (one class per domain) is readable.

**Anthropic Provider Implementation:** The new `AnthropicProvider` correctly handles the key structural differences from OpenAI's API: system prompt extraction from the messages array, content block format for tool calls (`tool_use` type), tool result format (`tool_result` content block), and `stop_reason` vs `finish_reason` mapping. This is a non-trivial translation layer done correctly.

---

## Recommendations by Priority

### Priority 1 — Pre-Ship Blockers (fix before merging)

1. **C3:** Declare `_parallel_nodes` in `__init__` (prevents silent parallel group corruption)
2. **C1:** Move loop counter into `ExecutionContext` (prevents non-reentrancy bug, fixes `test_loop_counter_resets_between_runs`)
3. **C2:** Remove `__node_execution_order__` injection from state dict; track separately
4. **C5:** Add error for `path_map` key misses in `ConditionalEdge.resolve()`
5. **I9:** Add `assert_all_consumed()` to `ScriptedLLM` (was a stated Task 1.7 deliverable)
6. **M1:** Fix deferred `SubgraphNode` import to resolve ruff E402 lint error

### Priority 2 — Before First Public Release

7. **I1:** Add `__aenter__`/`__aexit__` to both HTTP providers (resource leak)
8. **I6:** Fix context window detection in `AnthropicProvider` (false positives on 400 errors)
9. **I7:** Remove or correct the unused `anthropic` optional extra in `pyproject.toml`
10. **I8:** Implement unreachable node detection in `_validate()` (uses existing `UnreachableNodeError`)
11. **M2:** Use `isinstance(item, AgentProtocol)` instead of `hasattr` duck-typing in `_wrap_as_node()`
12. **M8:** Add `_compiled` flag to `WorkflowGraph` to prevent post-compile mutation
13. **M10:** Wrap `exec_module` in try/except in CLI `run` command
14. **C4:** Replace `eval()` in test with safe alternative and add a comment about the security risk

### Priority 3 — Quality Improvements

15. **I2:** Clean up double-provider injection between `runner.py` and `compiled.py`
16. **I3:** Document and log the input fallback chain in `_execute_agent_node`
17. **I4:** Deduplicate `_tool_to_schema` logic into a single function on `ToolWrapper`
18. **I5:** Remove unused `_original_func` attribute from `DecoratedAgent`
19. **I10:** Fix empty `tool_call_id` in `ToolWrapper.execute()` — remove from `ToolResult` or thread it through
20. **M3:** Handle running event loop in `run_sync()` (Jupyter compatibility)
21. **M4:** Default `model: str = ""` in `BaseAgent` and fall back to `provider.default_model`
22. **M5:** Make `ToolCallRecord.result` optional (`str | None`) to explicitly represent failures
23. **M6:** Move `import asyncio` to top of provider files
24. **M7:** Sanitize node IDs in `to_mermaid()`
25. **M9:** Make `TokenUsage.total_tokens` a computed property

---

## Summary Table

| ID | Severity | File | Issue |
|----|----------|------|-------|
| C1 | Critical | `graph.py` | Loop counter closure is not run-safe |
| C2 | Critical | `compiled.py` | `__node_execution_order__` pollutes public state dict |
| C3 | Critical | `graph.py` | `_parallel_nodes` is undeclared dynamic instance state |
| C4 | Critical | `test_core.py` | `eval()` in tool example normalizes an RCE pattern |
| C5 | Critical | `edges.py` | Path map key miss falls through silently |
| I1 | Important | `http.py`, `anthropic.py` | HTTP client never closed; resource leak |
| I2 | Important | `runner.py` | Double provider injection; context mutation |
| I3 | Important | `compiled.py` | Implicit input fallback chain undocumented |
| I4 | Important | `agent.py`, `registry.py` | Duplicated tool schema logic |
| I5 | Important | `agent.py` | `_original_func` is dead code |
| I6 | Important | `anthropic.py` | Vague context window error detection |
| I7 | Important | `pyproject.toml` | Unused `anthropic` SDK optional extra |
| I8 | Important | `graph.py` | No unreachable node detection |
| I9 | Important | `scripted.py` | Missing `assert_all_consumed()` helper |
| I10 | Important | `base.py` | `tool_call_id` always empty from `ToolWrapper` |
| M1 | Minor | `graph.py` | Deferred `SubgraphNode` import (lint error) |
| M2 | Minor | `graph.py` | Fragile `hasattr` duck-type for agent detection |
| M3 | Minor | `runner.py` | `run_sync()` breaks in running event loops |
| M4 | Minor | `agent.py` | OpenAI model name as provider-agnostic default |
| M5 | Minor | `types.py` | `ToolCallRecord.result` non-optional despite possible failure |
| M6 | Minor | `http.py`, `anthropic.py` | `import asyncio` inside hot path |
| M7 | Minor | `compiled.py` | No Mermaid output sanitization |
| M8 | Minor | `graph.py` | No post-compile mutation guard |
| M9 | Minor | `types.py` | `total_tokens` is redundant and error-prone |
| M10 | Minor | `cli/main.py` | Raw traceback on workflow file load error |
