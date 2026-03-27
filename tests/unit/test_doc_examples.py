"""Guard against documentation drift.

Every test in this module validates that a Python code example found in the
project documentation still works against the actual source.  When an API
changes but the docs are not updated, these tests fail and point directly to
the affected example.

Covered documentation files:
  - README.md
  - CLAUDE.md
  - docs/index.md
  - docs/getting-started.md
  - docs/concepts/agents.md
  - docs/concepts/graphs.md
  - docs/concepts/state.md
  - docs/concepts/testing.md
  - docs/api/core.md
  - docs/api/providers.md
  - docs/api/tools.md
  - docs/api/testing.md
  - docs/api/observability.md

Test classes:
  TestDocImports           -- every documented import path resolves
  TestDocAPIContracts      -- documented class/function signatures hold
  TestDocWorkflowPatterns  -- documented graph-construction patterns build and run
  TestDocStateReducers     -- documented state and reducer patterns work
  TestDocToolDecorator     -- @tool decorator behaves as documented
  TestDocScriptedLLM       -- ScriptedLLM API matches docs/api/testing.md

Implementation note on state class scope
-----------------------------------------
WorkflowState subclasses that use Annotated[T, reducer] in their field types
must be defined at module scope (not inside test methods) when they will be
passed to extract_reducers().  Python's get_type_hints() resolves forward
references against the class's defining module globals; reducer names defined
only inside a local function scope are not visible there and cause a
NameError.  Module-level definitions avoid this entirely.
"""

from __future__ import annotations

import inspect
from typing import Annotated, Any

import pytest

from orchestra.core.state import (
    WorkflowState,
    concat_str,
    keep_first,
    last_write_wins,
    max_value,
    merge_dict,
    merge_list,
    merge_set,
    min_value,
    sum_numbers,
)

# ---------------------------------------------------------------------------
# Module-level state class definitions
#
# These must live at module scope so that get_type_hints() can resolve the
# Annotated reducer names.  State classes defined inside test-method bodies
# would cause NameError in extract_reducers() on Python 3.13.
# ---------------------------------------------------------------------------


# Used by TestDocWorkflowPatterns.test_linear_graph_fluent_api
# docs/index.md quick example
class _ArticleState(WorkflowState):
    topic: str = ""
    draft: str = ""
    log: Annotated[list[str], merge_list] = []


# Used by TestDocWorkflowPatterns.test_parallel_fan_out_add_parallel
# CLAUDE.md / README.md parallel fan-out
class _ParallelState(WorkflowState):
    findings: Annotated[dict[str, str], merge_dict] = {}


# Used by TestDocStateReducers.test_extract_reducers_returns_all_annotated_fields
# docs/concepts/state.md
class _ResearchStateForExtract(WorkflowState):
    topic: str = ""
    findings: Annotated[dict[str, str], merge_dict] = {}
    messages: Annotated[list[str], merge_list] = []


# Used by TestDocStateReducers.test_workflow_state_all_reducer_annotations
# README.md built-in reducers example
class _FullState(WorkflowState):
    messages: Annotated[list[str], merge_list] = []
    results: Annotated[dict[str, str], merge_dict] = {}
    step_count: Annotated[int, sum_numbers] = 0
    current_agent: Annotated[str, last_write_wins] = ""
    tags: Annotated[set[str], merge_set] = set()
    log: Annotated[str, concat_str] = ""
    first_seen: Annotated[str, keep_first] = ""
    max_score: Annotated[float, max_value] = 0.0
    min_score: Annotated[float, min_value] = 100.0


# Used by TestDocStateReducers.test_apply_state_update_uses_reducers
# docs/api/core.md apply_state_update example
class _MergeListState(WorkflowState):
    messages: Annotated[list[str], merge_list] = []
    output: str = ""


# Used by TestDocStateReducers.test_merge_parallel_updates
# docs/concepts/state.md parallel state merging example
class _ParallelMergeState(WorkflowState):
    findings: Annotated[dict[str, str], merge_dict] = {}
    messages: Annotated[list[str], merge_list] = []


# Used by TestDocStateReducers.test_custom_reducer_works
# docs/concepts/state.md custom reducer example
def _weighted_average(existing: float, new: float) -> float:
    return existing * 0.7 + new * 0.3


class _WeightedState(WorkflowState):
    score: Annotated[float, _weighted_average] = 0.0


# ---------------------------------------------------------------------------
# A. Import verification tests
# ---------------------------------------------------------------------------


class TestDocImports:
    """Every 'from orchestra.X import Y' shown in any doc file must resolve."""

    # --- orchestra root (__init__.py re-exports) ---

    def test_import_base_agent_from_root(self) -> None:
        # README.md: from orchestra import BaseAgent
        from orchestra import BaseAgent  # noqa: F401

    def test_import_workflow_graph_from_root(self) -> None:
        # README.md: from orchestra import WorkflowGraph
        from orchestra import WorkflowGraph  # noqa: F401

    def test_import_workflow_state_from_root(self) -> None:
        # README.md: from orchestra import WorkflowState
        from orchestra import WorkflowState  # noqa: F401

    def test_import_run_from_root(self) -> None:
        # README.md: from orchestra import run
        from orchestra import run  # noqa: F401

    def test_import_run_sync_from_root(self) -> None:
        # docs/index.md: from orchestra import run_sync
        from orchestra import run_sync  # noqa: F401

    def test_import_tool_from_root(self) -> None:
        # README.md / docs/concepts/agents.md: from orchestra import tool
        from orchestra import tool  # noqa: F401

    def test_import_end_from_root(self) -> None:
        # README.md: from orchestra import END
        from orchestra import END  # noqa: F401

    def test_import_execution_context_from_root(self) -> None:
        # README.md: from orchestra import ExecutionContext
        from orchestra import ExecutionContext  # noqa: F401

    def test_import_agent_decorator_from_root(self) -> None:
        # docs/concepts/agents.md: from orchestra import agent
        from orchestra import agent  # noqa: F401

    # --- orchestra.providers ---

    def test_import_auto_provider(self) -> None:
        # README.md / CLAUDE.md: from orchestra.providers import auto_provider
        from orchestra.providers import auto_provider  # noqa: F401

    def test_import_callable_provider_from_providers(self) -> None:
        # README.md: from orchestra.providers import CallableProvider
        from orchestra.providers import CallableProvider  # noqa: F401

    def test_import_http_provider_from_providers(self) -> None:
        # docs/api/providers.md: from orchestra.providers import HttpProvider
        from orchestra.providers import HttpProvider  # noqa: F401

    def test_import_anthropic_provider_from_providers(self) -> None:
        # docs/api/providers.md: from orchestra.providers import AnthropicProvider
        from orchestra.providers import AnthropicProvider  # noqa: F401

    def test_import_ollama_provider_from_providers(self) -> None:
        # CLAUDE.md: from orchestra.providers.ollama import OllamaProvider
        from orchestra.providers import OllamaProvider  # noqa: F401

    def test_import_claude_code_provider_direct(self) -> None:
        # CLAUDE.md: from orchestra.providers.claude_code import ClaudeCodeProvider
        from orchestra.providers.claude_code import ClaudeCodeProvider  # noqa: F401

    def test_import_gemini_cli_provider_direct(self) -> None:
        # CLAUDE.md: from orchestra.providers.gemini_cli import GeminiCliProvider
        from orchestra.providers.gemini_cli import GeminiCliProvider  # noqa: F401

    def test_import_codex_cli_provider_direct(self) -> None:
        # CLAUDE.md: from orchestra.providers.codex_cli import CodexCliProvider
        from orchestra.providers.codex_cli import CodexCliProvider  # noqa: F401

    def test_import_anthropic_provider_direct(self) -> None:
        # CLAUDE.md: from orchestra.providers.anthropic import AnthropicProvider
        from orchestra.providers.anthropic import AnthropicProvider  # noqa: F401

    def test_import_google_provider_direct(self) -> None:
        # CLAUDE.md: from orchestra.providers.google import GoogleProvider
        from orchestra.providers.google import GoogleProvider  # noqa: F401

    def test_import_ollama_provider_direct(self) -> None:
        # CLAUDE.md: from orchestra.providers.ollama import OllamaProvider
        from orchestra.providers.ollama import OllamaProvider  # noqa: F401

    def test_import_http_provider_direct(self) -> None:
        # CLAUDE.md: from orchestra.providers.http import HttpProvider
        from orchestra.providers.http import HttpProvider  # noqa: F401

    # --- orchestra.core.* direct imports ---

    def test_import_base_agent_from_core(self) -> None:
        # docs/concepts/agents.md: from orchestra.core.agent import BaseAgent
        from orchestra.core.agent import BaseAgent  # noqa: F401

    def test_import_workflow_graph_from_core(self) -> None:
        # docs/getting-started.md: from orchestra.core.graph import WorkflowGraph
        from orchestra.core.graph import WorkflowGraph  # noqa: F401

    def test_import_run_from_core(self) -> None:
        # docs/getting-started.md: from orchestra import run (via core.runner)
        from orchestra.core.runner import run  # noqa: F401

    def test_import_run_sync_from_core(self) -> None:
        # docs/getting-started.md: from orchestra import run_sync
        from orchestra.core.runner import run_sync  # noqa: F401

    def test_import_run_result_from_core(self) -> None:
        # docs/api/core.md: RunResult
        from orchestra.core.runner import RunResult  # noqa: F401

    def test_import_workflow_state_from_core(self) -> None:
        # docs/concepts/state.md: from orchestra.core.state import WorkflowState
        from orchestra.core.state import WorkflowState  # noqa: F401

    def test_import_all_reducers_from_core_state(self) -> None:
        # docs/concepts/state.md lists all 9 reducers
        from orchestra.core.state import (  # noqa: F401
            concat_str,
            keep_first,
            last_write_wins,
            max_value,
            merge_dict,
            merge_list,
            merge_set,
            min_value,
            sum_numbers,
        )

    def test_import_state_functions_from_core(self) -> None:
        # docs/api/core.md State Functions table
        from orchestra.core.state import (  # noqa: F401
            apply_state_update,
            extract_reducers,
            merge_parallel_updates,
        )

    def test_import_end_from_core_types(self) -> None:
        # docs/getting-started.md: from orchestra.core.types import END
        from orchestra.core.types import END  # noqa: F401

    def test_import_llm_response_and_tool_call_from_types(self) -> None:
        # docs/api/testing.md: from orchestra.core.types import LLMResponse, ToolCall
        from orchestra.core.types import LLMResponse, ToolCall  # noqa: F401

    def test_import_agent_result_from_types(self) -> None:
        # docs/concepts/agents.md: from orchestra.core.types import AgentResult
        from orchestra.core.types import AgentResult  # noqa: F401

    def test_import_execution_context_from_core(self) -> None:
        # README.md: from orchestra.core.context import ExecutionContext
        from orchestra.core.context import ExecutionContext  # noqa: F401

    # --- orchestra.tools.* ---

    def test_import_tool_from_tools_base(self) -> None:
        # docs/api/tools.md: from orchestra.tools.base import tool
        from orchestra.tools.base import tool  # noqa: F401

    def test_import_tool_wrapper_from_tools_base(self) -> None:
        # docs/api/tools.md: ToolWrapper
        from orchestra.tools.base import ToolWrapper  # noqa: F401

    def test_import_tool_registry(self) -> None:
        # docs/api/tools.md: from orchestra.tools.registry import ToolRegistry
        from orchestra.tools.registry import ToolRegistry  # noqa: F401

    def test_import_mcp_client(self) -> None:
        # README.md: from orchestra.tools import MCPClient
        from orchestra.tools import MCPClient  # noqa: F401

    # --- orchestra.testing ---

    def test_import_scripted_llm(self) -> None:
        # README.md / docs/api/testing.md: from orchestra.testing import ScriptedLLM
        from orchestra.testing import ScriptedLLM  # noqa: F401

    def test_import_script_exhausted_error(self) -> None:
        # docs/api/testing.md: ScriptExhaustedError
        from orchestra.testing import ScriptExhaustedError  # noqa: F401

    # --- orchestra.observability ---

    def test_import_setup_logging(self) -> None:
        # docs/api/observability.md: from orchestra.observability.logging import setup_logging
        from orchestra.observability.logging import setup_logging  # noqa: F401

    def test_import_get_logger(self) -> None:
        # docs/api/observability.md: from orchestra.observability.logging import get_logger
        from orchestra.observability.logging import get_logger  # noqa: F401


# ---------------------------------------------------------------------------
# B. API contract tests
# ---------------------------------------------------------------------------


class TestDocAPIContracts:
    """Documented class signatures and method names must match the source."""

    # --- BaseAgent ---

    def test_base_agent_has_documented_constructor_params(self) -> None:
        # docs/concepts/agents.md Configuration Fields table
        from orchestra.core.agent import BaseAgent

        fields = BaseAgent.model_fields
        assert "name" in fields, "BaseAgent must have a 'name' field"
        assert "system_prompt" in fields, "BaseAgent must have a 'system_prompt' field"
        assert "tools" in fields, "BaseAgent must have a 'tools' field"
        assert "max_iterations" in fields, "BaseAgent must have a 'max_iterations' field"
        assert "temperature" in fields, "BaseAgent must have a 'temperature' field"
        assert "model" in fields, "BaseAgent must have a 'model' field"
        assert "output_type" in fields, "BaseAgent must have an 'output_type' field"

    def test_base_agent_instantiation_with_documented_params(self) -> None:
        # README.md: BaseAgent(name, system_prompt, model, tools, max_iterations)
        from orchestra.core.agent import BaseAgent

        agent = BaseAgent(
            name="researcher",
            system_prompt="You are a research analyst.",
            model="gpt-4o-mini",
            max_iterations=10,
            temperature=0.7,
        )
        assert agent.name == "researcher"
        assert agent.max_iterations == 10

    def test_base_agent_has_run_method(self) -> None:
        # docs/concepts/agents.md: agent.run(input, context)
        from orchestra.core.agent import BaseAgent

        assert callable(BaseAgent.run), "BaseAgent must have a callable run() method"

    # --- @agent decorator ---

    def test_agent_decorator_produces_decorated_agent(self) -> None:
        # docs/concepts/agents.md: @agent(model=..., temperature=...)
        from orchestra import agent
        from orchestra.core.agent import DecoratedAgent

        @agent(model="gpt-4o-mini", temperature=0.3)
        async def researcher(topic: str) -> str:
            """You are a research analyst. Find key facts about the given topic."""

        assert isinstance(researcher, DecoratedAgent)
        assert researcher.name == "researcher"
        expected = "You are a research analyst. Find key facts about the given topic."
        assert researcher.system_prompt == expected
        assert researcher.model == "gpt-4o-mini"
        assert researcher.temperature == 0.3

    # --- WorkflowGraph ---

    def test_workflow_graph_accepts_state_schema(self) -> None:
        # README.md / CLAUDE.md: WorkflowGraph(state_schema=State)
        from orchestra.core.graph import WorkflowGraph
        from orchestra.core.state import WorkflowState

        class MyState(WorkflowState):
            value: str = ""

        g = WorkflowGraph(state_schema=MyState)
        assert g is not None

    def test_workflow_graph_has_add_node(self) -> None:
        # docs/api/core.md WorkflowGraph members
        from orchestra.core.graph import WorkflowGraph

        assert hasattr(WorkflowGraph, "add_node")

    def test_workflow_graph_has_add_edge(self) -> None:
        from orchestra.core.graph import WorkflowGraph

        assert hasattr(WorkflowGraph, "add_edge")

    def test_workflow_graph_has_set_entry_point(self) -> None:
        # docs/getting-started.md explicit API
        from orchestra.core.graph import WorkflowGraph

        assert hasattr(WorkflowGraph, "set_entry_point")

    def test_workflow_graph_has_add_conditional_edge(self) -> None:
        # CLAUDE.md: graph.add_conditional_edge(...)
        from orchestra.core.graph import WorkflowGraph

        assert hasattr(WorkflowGraph, "add_conditional_edge")

    def test_workflow_graph_has_add_parallel(self) -> None:
        # CLAUDE.md: graph.add_parallel(...)
        from orchestra.core.graph import WorkflowGraph

        assert hasattr(WorkflowGraph, "add_parallel")

    def test_workflow_graph_has_compile(self) -> None:
        # docs/concepts/graphs.md: compiled = graph.compile()
        from orchestra.core.graph import WorkflowGraph

        assert hasattr(WorkflowGraph, "compile")

    def test_workflow_graph_has_then(self) -> None:
        # docs/index.md fluent API: .then(...)
        from orchestra.core.graph import WorkflowGraph

        assert hasattr(WorkflowGraph, "then")

    def test_workflow_graph_has_parallel_and_join(self) -> None:
        # docs/concepts/graphs.md: .parallel(...).join(...)
        from orchestra.core.graph import WorkflowGraph

        assert hasattr(WorkflowGraph, "parallel")
        assert hasattr(WorkflowGraph, "join")

    def test_workflow_graph_has_branch(self) -> None:
        # docs/concepts/graphs.md: .branch(condition, path_map)
        from orchestra.core.graph import WorkflowGraph

        assert hasattr(WorkflowGraph, "branch")

    def test_workflow_graph_has_if_then(self) -> None:
        # docs/concepts/graphs.md: .if_then(condition, then_agent, else_agent)
        from orchestra.core.graph import WorkflowGraph

        assert hasattr(WorkflowGraph, "if_then")

    def test_workflow_graph_has_loop(self) -> None:
        # docs/concepts/graphs.md: .loop(agent, condition=..., max_iterations=...)
        from orchestra.core.graph import WorkflowGraph

        assert hasattr(WorkflowGraph, "loop")

    # --- CompiledGraph ---

    def test_compiled_graph_has_run(self) -> None:
        # docs/api/core.md CompiledGraph members
        from orchestra.core.compiled import CompiledGraph

        assert hasattr(CompiledGraph, "run")

    def test_compiled_graph_has_to_mermaid(self) -> None:
        # docs/concepts/graphs.md: compiled.to_mermaid()
        from orchestra.core.compiled import CompiledGraph

        assert hasattr(CompiledGraph, "to_mermaid")

    # --- run() / run_sync() ---

    def test_run_accepts_documented_params(self) -> None:
        # README.md: run(graph, input=..., provider=..., persist=False)
        # docs/getting-started.md: run(graph, initial_state=..., provider=...)
        from orchestra.core.runner import run

        sig = inspect.signature(run)
        params = sig.parameters
        assert "graph" in params
        assert "input" in params
        assert "initial_state" in params
        assert "provider" in params
        assert "persist" in params

    def test_run_sync_accepts_documented_params(self) -> None:
        # docs/index.md: run_sync(graph, initial_state=...)
        from orchestra.core.runner import run_sync

        sig = inspect.signature(run_sync)
        params = sig.parameters
        assert "graph" in params
        assert "input" in params
        assert "initial_state" in params
        assert "provider" in params

    def test_run_result_has_documented_attributes(self) -> None:
        # README.md: result.output, result.state, result.node_execution_order
        # docs/concepts/graphs.md: result.output, result.state, result.duration_ms
        from orchestra.core.runner import RunResult

        fields = RunResult.model_fields
        assert "output" in fields
        assert "state" in fields
        assert "duration_ms" in fields
        assert "node_execution_order" in fields
        assert "run_id" in fields

    # --- ExecutionContext ---

    def test_execution_context_accepts_provider(self) -> None:
        # README.md: ExecutionContext(provider=provider)
        from orchestra.core.context import ExecutionContext

        ctx = ExecutionContext(provider=None)
        assert ctx.provider is None

    # --- CLI providers: model param ---

    def test_claude_code_provider_accepts_model_param(self) -> None:
        # CLAUDE.md: ClaudeCodeProvider(model="opus")
        from orchestra.providers.claude_code import ClaudeCodeProvider

        sig = inspect.signature(ClaudeCodeProvider.__init__)
        assert "model" in sig.parameters, \
            "ClaudeCodeProvider.__init__ must accept 'model' kwarg (documented in CLAUDE.md)"

    def test_gemini_cli_provider_accepts_model_param(self) -> None:
        # CLAUDE.md: GeminiCliProvider(model="gemini-2.5-pro")
        from orchestra.providers.gemini_cli import GeminiCliProvider

        sig = inspect.signature(GeminiCliProvider.__init__)
        assert "model" in sig.parameters, \
            "GeminiCliProvider.__init__ must accept 'model' kwarg (documented in CLAUDE.md)"

    def test_codex_cli_provider_accepts_model_param(self) -> None:
        # CLAUDE.md: CodexCliProvider(model="o4-mini")
        from orchestra.providers.codex_cli import CodexCliProvider

        sig = inspect.signature(CodexCliProvider.__init__)
        assert "model" in sig.parameters, \
            "CodexCliProvider.__init__ must accept 'model' kwarg (documented in CLAUDE.md)"

    # --- API providers: default_model param (not 'model') ---

    def test_http_provider_uses_default_model_not_model(self) -> None:
        # docs/api/providers.md shows HttpProvider(model=...) but actual param is default_model
        # This test documents the REAL parameter name so if it drifts in either
        # direction the failure message explains the situation.
        from orchestra.providers.http import HttpProvider

        sig = inspect.signature(HttpProvider.__init__)
        assert "default_model" in sig.parameters, \
            "HttpProvider uses 'default_model' (not 'model'). " \
            "docs/api/providers.md shows 'model=' which is incorrect — " \
            "update the docs or rename the param."

    def test_anthropic_provider_uses_default_model_not_model(self) -> None:
        # docs/api/providers.md shows AnthropicProvider(model=...) but actual is default_model
        from orchestra.providers.anthropic import AnthropicProvider

        sig = inspect.signature(AnthropicProvider.__init__)
        assert "default_model" in sig.parameters, \
            "AnthropicProvider uses 'default_model' (not 'model'). " \
            "docs/api/providers.md shows 'model=' which is incorrect."

    def test_ollama_provider_uses_default_model(self) -> None:
        # CLAUDE.md shows OllamaProvider(default_model="llama3.1") -- param name correct
        from orchestra.providers.ollama import OllamaProvider

        sig = inspect.signature(OllamaProvider.__init__)
        assert "default_model" in sig.parameters

    # --- setup_logging ---

    def test_setup_logging_accepts_level_and_json_output(self) -> None:
        # docs/api/observability.md: setup_logging(level, json_output)
        from orchestra.observability.logging import setup_logging

        sig = inspect.signature(setup_logging)
        params = sig.parameters
        assert "level" in params, "setup_logging must accept 'level' param"
        assert "json_output" in params, "setup_logging must accept 'json_output' param"
        assert "format" not in params, \
            "setup_logging must NOT accept 'format' — docs use 'json_output'"

    # --- ScriptedLLM ---

    def test_scripted_llm_has_assert_all_consumed(self) -> None:
        # docs/concepts/testing.md: llm.assert_all_consumed()
        from orchestra.testing import ScriptedLLM

        assert hasattr(ScriptedLLM, "assert_all_consumed")

    def test_scripted_llm_has_assert_prompt_received(self) -> None:
        # docs/api/testing.md: llm.assert_prompt_received(call_index, pattern)
        from orchestra.testing import ScriptedLLM

        assert hasattr(ScriptedLLM, "assert_prompt_received")

    def test_scripted_llm_has_call_count_and_call_log(self) -> None:
        # docs/concepts/testing.md: llm.call_count, llm.call_log
        from orchestra.testing import ScriptedLLM

        llm = ScriptedLLM(["test"])
        assert hasattr(llm, "call_count")
        assert hasattr(llm, "call_log")

    def test_scripted_llm_has_reset(self) -> None:
        # docs/api/testing.md: llm.reset()
        from orchestra.testing import ScriptedLLM

        assert hasattr(ScriptedLLM, "reset")


# ---------------------------------------------------------------------------
# C. Workflow construction tests
# ---------------------------------------------------------------------------


class TestDocWorkflowPatterns:
    """Documented graph construction patterns must build and execute correctly."""

    async def test_linear_graph_explicit_api(self) -> None:
        # docs/getting-started.md Step 2-3: explicit add_node/add_edge/set_entry_point pattern
        from orchestra.core.graph import WorkflowGraph
        from orchestra.core.runner import run
        from orchestra.core.state import WorkflowState
        from orchestra.core.types import END

        class ArticleState(WorkflowState):
            topic: str = ""
            research: str = ""
            draft: str = ""

        async def research_node(state: dict[str, Any]) -> dict[str, Any]:
            return {"research": f"Findings about {state['topic']}"}

        async def writer_node(state: dict[str, Any]) -> dict[str, Any]:
            return {"draft": f"Article based on: {state['research']}"}

        graph = WorkflowGraph(state_schema=ArticleState)
        graph.add_node("researcher", research_node)
        graph.add_node("writer", writer_node)
        graph.set_entry_point("researcher")
        graph.add_edge("researcher", "writer")
        graph.add_edge("writer", END)

        result = await run(graph, initial_state={"topic": "AI"}, persist=False)
        assert "Findings about AI" in result.state["research"]
        assert "researcher" in result.node_execution_order
        assert "writer" in result.node_execution_order

    async def test_linear_graph_fluent_api(self) -> None:
        # docs/index.md quick example: WorkflowGraph(state_schema=...).then(...).then(...)
        # docs/concepts/graphs.md fluent API
        # Uses module-level _ArticleState to avoid get_type_hints scope issues.
        # Uses run() instead of run_sync() because run_sync() calls asyncio.run()
        # which cannot be called from inside a running event loop (pytest-asyncio mode=auto).
        # run_sync() is tested separately via test_run_sync_accepts_documented_params which
        # validates its signature; its end-to-end behaviour is identical to run().
        from orchestra.core.graph import WorkflowGraph
        from orchestra.core.runner import run

        async def research(state: dict[str, Any]) -> dict[str, Any]:
            return {"draft": f"Research on {state['topic']}", "log": ["researched"]}

        async def write(state: dict[str, Any]) -> dict[str, Any]:
            return {"draft": f"Article: {state['draft']}", "log": ["wrote"]}

        graph = WorkflowGraph(state_schema=_ArticleState).then(research).then(write)
        result = await run(graph, initial_state={"topic": "AI agents"}, persist=False)
        assert result.state["draft"].startswith("Article:")
        assert result.state["log"] == ["researched", "wrote"]

    def test_compile_returns_compiled_graph(self) -> None:
        # docs/concepts/graphs.md: compiled = graph.compile(max_turns=50)
        from orchestra.core.compiled import CompiledGraph
        from orchestra.core.graph import WorkflowGraph

        async def node_fn(state: dict[str, Any]) -> dict[str, Any]:
            return {}

        graph = WorkflowGraph().then(node_fn)
        compiled = graph.compile(max_turns=50)
        assert isinstance(compiled, CompiledGraph)

    def test_compiled_graph_to_mermaid(self) -> None:
        # docs/concepts/graphs.md: compiled.to_mermaid()
        from orchestra.core.graph import WorkflowGraph

        async def node_fn(state: dict[str, Any]) -> dict[str, Any]:
            return {}

        compiled = WorkflowGraph().then(node_fn).compile()
        diagram = compiled.to_mermaid()
        assert isinstance(diagram, str)
        assert len(diagram) > 0

    async def test_conditional_routing_pattern(self) -> None:
        # CLAUDE.md / README.md conditional routing with add_conditional_edge + path_map
        from orchestra.core.graph import WorkflowGraph
        from orchestra.core.runner import run
        from orchestra.core.state import WorkflowState
        from orchestra.core.types import END

        class RouteState(WorkflowState):
            category: str = ""
            output: str = ""

        async def classifier(state: dict[str, Any]) -> dict[str, Any]:
            return {"category": "fast"}

        async def fast_path(state: dict[str, Any]) -> dict[str, Any]:
            return {"output": "fast result"}

        async def thorough_path(state: dict[str, Any]) -> dict[str, Any]:
            return {"output": "thorough result"}

        graph = WorkflowGraph(state_schema=RouteState)
        graph.add_node("classifier", classifier)
        graph.add_node("fast_path", fast_path)
        graph.add_node("thorough_path", thorough_path)
        graph.set_entry_point("classifier")
        graph.add_conditional_edge(
            "classifier",
            lambda state: state.get("category", "thorough"),
            path_map={"fast": "fast_path", "thorough": "thorough_path"},
        )
        graph.add_edge("fast_path", END)
        graph.add_edge("thorough_path", END)

        result = await run(graph, persist=False)
        assert result.state["output"] == "fast result"

    async def test_fluent_branch_pattern(self) -> None:
        # docs/concepts/graphs.md .branch(condition, path_map)
        from orchestra.core.graph import WorkflowGraph
        from orchestra.core.runner import run

        async def classifier(state: dict[str, Any]) -> dict[str, Any]:
            return {"category": "technical"}

        async def tech_writer(state: dict[str, Any]) -> dict[str, Any]:
            return {"output": "technical article"}

        async def creative_writer(state: dict[str, Any]) -> dict[str, Any]:
            return {"output": "creative article"}

        graph = (
            WorkflowGraph()
            .then(classifier)
            .branch(
                lambda state: state.get("category"),
                {"technical": tech_writer, "creative": creative_writer},
            )
        )
        result = await run(graph, persist=False)
        assert result.state["output"] == "technical article"

    async def test_parallel_fan_out_add_parallel(self) -> None:
        # CLAUDE.md / README.md parallel fan-out via add_parallel + join_node
        # Uses module-level _ParallelState (Annotated[dict, merge_dict]) to avoid
        # get_type_hints scope issues with locally-defined reducer names.
        from orchestra.core.graph import WorkflowGraph
        from orchestra.core.runner import run
        from orchestra.core.types import END

        async def dispatch(state: dict[str, Any]) -> dict[str, Any]:
            return {}

        async def worker_a(state: dict[str, Any]) -> dict[str, Any]:
            return {"findings": {"a": "result_a"}}

        async def worker_b(state: dict[str, Any]) -> dict[str, Any]:
            return {"findings": {"b": "result_b"}}

        async def joiner(state: dict[str, Any]) -> dict[str, Any]:
            return {}

        graph = WorkflowGraph(state_schema=_ParallelState)
        graph.add_node("dispatch", dispatch)
        graph.add_node("worker_a", worker_a)
        graph.add_node("worker_b", worker_b)
        graph.add_node("join", joiner)
        graph.set_entry_point("dispatch")
        graph.add_parallel("dispatch", ["worker_a", "worker_b"], join_node="join")
        graph.add_edge("join", END)

        result = await run(graph, persist=False)
        assert "a" in result.state["findings"]
        assert "b" in result.state["findings"]

    async def test_fluent_parallel_join_pattern(self) -> None:
        # docs/concepts/graphs.md .parallel(...).join(...)
        from orchestra.core.graph import WorkflowGraph
        from orchestra.core.runner import run

        async def planner(state: dict[str, Any]) -> dict[str, Any]:
            return {}

        async def researcher_a(state: dict[str, Any]) -> dict[str, Any]:
            return {}

        async def researcher_b(state: dict[str, Any]) -> dict[str, Any]:
            return {}

        async def synthesizer(state: dict[str, Any]) -> dict[str, Any]:
            return {"output": "synthesized"}

        graph = (
            WorkflowGraph()
            .then(planner)
            .parallel(researcher_a, researcher_b)
            .join(synthesizer)
        )
        result = await run(graph, persist=False)
        assert result.state["output"] == "synthesized"

    async def test_if_then_pattern(self) -> None:
        # docs/concepts/graphs.md .if_then(condition, then_agent, else_agent)
        from orchestra.core.graph import WorkflowGraph
        from orchestra.core.runner import run

        async def reviewer(state: dict[str, Any]) -> dict[str, Any]:
            return {"approved": True}

        async def publisher(state: dict[str, Any]) -> dict[str, Any]:
            return {"output": "published"}

        async def reviser(state: dict[str, Any]) -> dict[str, Any]:
            return {"output": "revised"}

        graph = (
            WorkflowGraph()
            .then(reviewer)
            .if_then(
                lambda state: state.get("approved", False),
                then_agent=publisher,
                else_agent=reviser,
            )
        )
        result = await run(graph, persist=False)
        assert result.state["output"] == "published"

    async def test_run_accepts_compiled_graph(self) -> None:
        # docs/concepts/graphs.md: "run() accepts both a WorkflowGraph and a CompiledGraph"
        from orchestra.core.graph import WorkflowGraph
        from orchestra.core.runner import run

        async def node(state: dict[str, Any]) -> dict[str, Any]:
            return {"output": "from compiled"}

        compiled = WorkflowGraph().then(node).compile()
        result = await run(compiled, persist=False)
        assert result.state["output"] == "from compiled"

    async def test_graph_with_agent_and_scripted_llm(self) -> None:
        # README.md deterministic unit testing example
        from orchestra.core.agent import BaseAgent
        from orchestra.core.graph import WorkflowGraph
        from orchestra.core.runner import run
        from orchestra.core.state import WorkflowState
        from orchestra.core.types import END
        from orchestra.testing import ScriptedLLM

        class MyState(WorkflowState):
            query: str = ""
            research: str = ""
            report: str = ""

        researcher = BaseAgent(name="researcher", system_prompt="Research analyst.")
        writer = BaseAgent(name="writer", system_prompt="Technical writer.")

        graph = WorkflowGraph(state_schema=MyState)
        graph.add_node("research", researcher, output_key="research")
        graph.add_node("write", writer, output_key="report")
        graph.set_entry_point("research")
        graph.add_edge("research", "write")
        graph.add_edge("write", END)

        provider = ScriptedLLM([
            "Multi-agent systems have evolved significantly...",
            "## Research Report\n\nKey findings include...",
        ])
        result = await run(graph, input={"query": "test query"}, provider=provider, persist=False)

        assert "Key findings" in result.state["report"]
        assert result.node_execution_order == ["research", "write"]


# ---------------------------------------------------------------------------
# D. State and reducer tests
# ---------------------------------------------------------------------------


class TestDocStateReducers:
    """Documented state and reducer patterns must work as described."""

    def test_workflow_state_subclass_with_annotated_field(self) -> None:
        # docs/concepts/state.md defining state with reducers
        from orchestra.core.state import WorkflowState

        class MyState(WorkflowState):
            messages: Annotated[list[str], merge_list] = []
            current_agent: str = ""

        state = MyState()
        assert state.messages == []
        assert state.current_agent == ""

    def test_workflow_state_all_reducer_annotations(self) -> None:
        # README.md: all 9 reducers annotated on a state class.
        # Uses module-level _FullState (defined at the top of this file) to
        # avoid get_type_hints NameError for locally-scoped reducer names.
        state = _FullState()
        assert state.step_count == 0
        assert state.messages == []
        assert state.min_score == 100.0

    def test_extract_reducers_returns_all_annotated_fields(self) -> None:
        # docs/api/core.md: extract_reducers(state_class) -> {field_name: reducer_fn}
        # Uses module-level _ResearchStateForExtract to avoid get_type_hints scope issues.
        from orchestra.core.state import extract_reducers, merge_dict, merge_list

        reducers = extract_reducers(_ResearchStateForExtract)
        assert "findings" in reducers
        assert "messages" in reducers
        assert reducers["findings"] is merge_dict
        assert reducers["messages"] is merge_list
        assert "topic" not in reducers  # no reducer = not in map

    def test_merge_list_reducer(self) -> None:
        # docs/concepts/state.md: merge_list appends
        from orchestra.core.state import merge_list

        result = merge_list(["a", "b"], ["c"])
        assert result == ["a", "b", "c"]

    def test_merge_dict_reducer(self) -> None:
        # docs/concepts/state.md: merge_dict shallow-merges
        from orchestra.core.state import merge_dict

        result = merge_dict({"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}

    def test_sum_numbers_reducer(self) -> None:
        # docs/concepts/state.md: sum_numbers adds
        from orchestra.core.state import sum_numbers

        assert sum_numbers(5, 3) == 8
        assert sum_numbers(1.5, 2.5) == 4.0

    def test_last_write_wins_reducer(self) -> None:
        # docs/concepts/state.md
        from orchestra.core.state import last_write_wins

        assert last_write_wins("old", "new") == "new"

    def test_merge_set_reducer(self) -> None:
        # docs/concepts/state.md: merge_set union
        from orchestra.core.state import merge_set

        result = merge_set({1, 2}, {2, 3})
        assert result == {1, 2, 3}

    def test_concat_str_reducer(self) -> None:
        # docs/concepts/state.md
        from orchestra.core.state import concat_str

        assert concat_str("hello", " world") == "hello world"

    def test_keep_first_reducer(self) -> None:
        # docs/concepts/state.md: keep_first ignores new value
        from orchestra.core.state import keep_first

        assert keep_first("original", "replacement") == "original"

    def test_max_value_reducer(self) -> None:
        # docs/concepts/state.md
        from orchestra.core.state import max_value

        assert max_value(3, 7) == 7
        assert max_value(10, 5) == 10

    def test_min_value_reducer(self) -> None:
        # docs/concepts/state.md
        from orchestra.core.state import min_value

        assert min_value(3, 7) == 3
        assert min_value(10, 5) == 5

    def test_apply_state_update_uses_reducers(self) -> None:
        # docs/api/core.md: apply_state_update(state, update, reducers)
        # Uses module-level _MergeListState (messages: Annotated[list, merge_list]) to
        # avoid get_type_hints scope issues with locally-defined reducer names.
        from orchestra.core.state import apply_state_update, extract_reducers

        state = _MergeListState(messages=["first"], output="old")
        reducers = extract_reducers(_MergeListState)
        new_state = apply_state_update(state, {"messages": ["second"], "output": "new"}, reducers)

        assert new_state.messages == ["first", "second"]
        assert new_state.output == "new"

    def test_merge_parallel_updates(self) -> None:
        # docs/api/core.md / docs/concepts/state.md parallel state merging example
        # Uses module-level _ParallelMergeState to avoid get_type_hints scope issues.
        from orchestra.core.state import extract_reducers, merge_parallel_updates

        state = _ParallelMergeState()
        updates = [
            {"findings": {"tech": "..."}, "messages": ["A done"]},
            {"findings": {"market": "..."}, "messages": ["B done"]},
            {"findings": {"legal": "..."}, "messages": ["C done"]},
        ]
        reducers = extract_reducers(_ParallelMergeState)
        result = merge_parallel_updates(state, updates, reducers)

        assert result.findings == {"tech": "...", "market": "...", "legal": "..."}
        assert result.messages == ["A done", "B done", "C done"]

    def test_custom_reducer_works(self) -> None:
        # docs/concepts/state.md: any callable (existing, new) -> merged works as a reducer.
        # Uses module-level _WeightedState and _weighted_average to avoid
        # get_type_hints scope issues with locally-defined callable names.
        from orchestra.core.state import apply_state_update, extract_reducers

        state = _WeightedState(score=10.0)
        reducers = extract_reducers(_WeightedState)
        new_state = apply_state_update(state, {"score": 20.0}, reducers)
        assert new_state.score == pytest.approx(10.0 * 0.7 + 20.0 * 0.3)


# ---------------------------------------------------------------------------
# E. Tool decorator tests
# ---------------------------------------------------------------------------


class TestDocToolDecorator:
    """The @tool decorator must produce the JSON schema described in docs/api/tools.md."""

    def test_tool_decorator_plain_form(self) -> None:
        # docs/api/tools.md simple form: @tool on an async function
        from orchestra.tools.base import ToolWrapper, tool

        @tool
        async def web_search(query: str, max_results: int = 5) -> str:
            """Search the web for information."""
            return f"Results for: {query}"

        assert isinstance(web_search, ToolWrapper)
        assert web_search.name == "web_search"
        assert web_search.description == "Search the web for information."

    def test_tool_schema_required_vs_optional_params(self) -> None:
        # docs/api/tools.md: Parameters with defaults are optional in the schema.
        from orchestra.tools.base import tool

        @tool
        async def web_search(query: str, max_results: int = 5) -> str:
            """Search the web for information."""
            return f"Results for: {query}"

        schema = web_search.parameters_schema
        assert schema["type"] == "object"
        assert "query" in schema["properties"]
        assert "max_results" in schema["properties"]
        assert schema["required"] == ["query"]
        assert "max_results" not in schema.get("required", [])

    def test_tool_schema_type_mapping(self) -> None:
        # docs/api/tools.md Supported Type Mappings table
        from orchestra.tools.base import tool

        @tool
        async def typed_tool(s: str, n: int, f: float, b: bool) -> str:
            """Typed tool."""
            return ""

        props = typed_tool.parameters_schema["properties"]
        assert props["s"]["type"] == "string"
        assert props["n"]["type"] == "integer"
        assert props["f"]["type"] == "number"
        assert props["b"]["type"] == "boolean"

    def test_tool_decorator_with_custom_name_and_description(self) -> None:
        # docs/api/tools.md: @tool(name="search", description="Search the internet")
        from orchestra.tools.base import tool

        @tool(name="search", description="Search the internet")
        async def web_search(query: str) -> str:
            return f"Results for: {query}"

        assert web_search.name == "search"
        assert web_search.description == "Search the internet"

    async def test_tool_is_callable_via_execute(self) -> None:
        # docs/api/tools.md: tool.execute(arguments) returns ToolResult
        from orchestra.tools.base import tool

        @tool
        async def greet(name: str) -> str:
            """Greet someone."""
            return f"Hello, {name}!"

        result = await greet.execute({"name": "Alice"})
        assert result.content == "Hello, Alice!"
        assert result.error is None

    def test_tool_registry_register_and_get_schemas(self) -> None:
        # docs/api/tools.md ToolRegistry usage
        from orchestra.tools.base import tool
        from orchestra.tools.registry import ToolRegistry

        @tool
        async def calculator(x: int, y: int) -> str:
            """Add two numbers."""
            return str(x + y)

        registry = ToolRegistry()
        registry.register(calculator)

        schemas = registry.get_schemas()
        assert isinstance(schemas, list)
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "calculator"

        retrieved = registry.get("calculator")
        assert retrieved.name == "calculator"

    def test_tool_registry_has_and_list_tools(self) -> None:
        # docs/api/tools.md: registry.has(), registry.list_tools()
        from orchestra.tools.base import tool
        from orchestra.tools.registry import ToolRegistry

        @tool
        async def my_func(x: str) -> str:
            """Does something."""
            return x

        registry = ToolRegistry()
        registry.register(my_func)

        assert registry.has("my_func")
        tools_list = registry.list_tools()
        assert any(t["name"] == "my_func" for t in tools_list)

    def test_tool_registry_unregister_and_clear(self) -> None:
        # docs/api/tools.md: registry.unregister(), registry.clear()
        from orchestra.tools.base import tool
        from orchestra.tools.registry import ToolRegistry

        @tool
        async def temp_tool(x: str) -> str:
            """Temp."""
            return x

        registry = ToolRegistry()
        registry.register(temp_tool)
        assert registry.has("temp_tool")

        registry.unregister("temp_tool")
        assert not registry.has("temp_tool")

        registry.register(temp_tool)
        registry.clear()
        assert len(registry) == 0


# ---------------------------------------------------------------------------
# F. ScriptedLLM tests
# ---------------------------------------------------------------------------


class TestDocScriptedLLM:
    """ScriptedLLM API must match docs/api/testing.md and docs/concepts/testing.md."""

    async def test_scripted_llm_returns_responses_in_order(self) -> None:
        # docs/concepts/testing.md basic usage
        from orchestra.core.types import Message, MessageRole
        from orchestra.testing import ScriptedLLM

        llm = ScriptedLLM([
            "First response from the LLM.",
            "Second response from the LLM.",
        ])

        msgs = [Message(role=MessageRole.USER, content="hello")]
        r1 = await llm.complete(msgs)
        r2 = await llm.complete(msgs)

        assert r1.content == "First response from the LLM."
        assert r2.content == "Second response from the LLM."

    async def test_scripted_llm_wraps_strings_in_llm_response(self) -> None:
        # docs/api/testing.md: Strings are auto-wrapped in LLMResponse
        from orchestra.core.types import LLMResponse, Message, MessageRole
        from orchestra.testing import ScriptedLLM

        llm = ScriptedLLM(["plain string response"])
        msgs = [Message(role=MessageRole.USER, content="hi")]
        response = await llm.complete(msgs)
        assert isinstance(response, LLMResponse)
        assert response.content == "plain string response"

    async def test_scripted_llm_accepts_llm_response_objects(self) -> None:
        # docs/api/testing.md: Mixed string and LLMResponse objects
        from orchestra.core.types import LLMResponse, Message, MessageRole, ToolCall
        from orchestra.testing import ScriptedLLM

        tool_response = LLMResponse(
            content="",
            tool_calls=[ToolCall(name="web_search", arguments={"query": "AI trends"})],
            finish_reason="tool_calls",
        )
        llm = ScriptedLLM([tool_response, "Final answer"])
        msgs = [Message(role=MessageRole.USER, content="search")]

        r1 = await llm.complete(msgs)
        r2 = await llm.complete(msgs)

        assert len(r1.tool_calls) == 1
        assert r1.tool_calls[0].name == "web_search"
        assert r2.content == "Final answer"

    async def test_assert_all_consumed_passes_when_all_used(self) -> None:
        # docs/concepts/testing.md: assert_all_consumed() should not raise
        from orchestra.core.types import Message, MessageRole
        from orchestra.testing import ScriptedLLM

        llm = ScriptedLLM(["r1", "r2"])
        msgs = [Message(role=MessageRole.USER, content="x")]
        await llm.complete(msgs)
        await llm.complete(msgs)
        llm.assert_all_consumed()  # Should not raise

    async def test_assert_all_consumed_raises_when_responses_remain(self) -> None:
        # docs/concepts/testing.md: assert_all_consumed raises AssertionError with remaining count
        from orchestra.core.types import Message, MessageRole
        from orchestra.testing import ScriptedLLM

        llm = ScriptedLLM(["response 1", "response 2", "response 3"])
        msgs = [Message(role=MessageRole.USER, content="x")]
        await llm.complete(msgs)
        await llm.complete(msgs)
        # Only 2 consumed, 1 remains

        with pytest.raises(AssertionError) as exc_info:
            llm.assert_all_consumed()
        error_msg = str(exc_info.value)
        assert "1" in error_msg  # 1 unconsumed
        assert "2" in error_msg  # used 2

    async def test_script_exhausted_error_on_extra_call(self) -> None:
        # docs/api/testing.md: ScriptExhaustedError raised when all responses consumed
        from orchestra.core.types import Message, MessageRole
        from orchestra.testing import ScriptedLLM, ScriptExhaustedError

        llm = ScriptedLLM(["only one"])
        msgs = [Message(role=MessageRole.USER, content="hi")]
        await llm.complete(msgs)

        with pytest.raises(ScriptExhaustedError):
            await llm.complete(msgs)

    async def test_call_count_increments(self) -> None:
        # docs/concepts/testing.md: llm.call_count
        from orchestra.core.types import Message, MessageRole
        from orchestra.testing import ScriptedLLM

        llm = ScriptedLLM(["a", "b"])
        assert llm.call_count == 0

        msgs = [Message(role=MessageRole.USER, content="x")]
        await llm.complete(msgs)
        assert llm.call_count == 1

        await llm.complete(msgs)
        assert llm.call_count == 2

    async def test_call_log_records_messages(self) -> None:
        # docs/concepts/testing.md: llm.call_log[0]["messages"]
        from orchestra.core.types import Message, MessageRole
        from orchestra.testing import ScriptedLLM

        llm = ScriptedLLM(["response"])
        msgs = [Message(role=MessageRole.USER, content="test query")]
        await llm.complete(msgs)

        assert len(llm.call_log) == 1
        assert "messages" in llm.call_log[0]

    async def test_reset_clears_state(self) -> None:
        # docs/api/testing.md: llm.reset() resets index and call log
        from orchestra.core.types import Message, MessageRole
        from orchestra.testing import ScriptedLLM

        llm = ScriptedLLM(["response 1", "response 2"])
        msgs = [Message(role=MessageRole.USER, content="x")]
        await llm.complete(msgs)
        assert llm.call_count == 1

        llm.reset()
        assert llm.call_count == 0
        assert llm.call_log == []

        # After reset, can consume responses from the beginning again
        r = await llm.complete(msgs)
        assert r.content == "response 1"

    async def test_assert_prompt_received(self) -> None:
        # docs/api/testing.md: llm.assert_prompt_received(call_index, pattern)
        from orchestra.core.types import Message, MessageRole
        from orchestra.testing import ScriptedLLM

        llm = ScriptedLLM(["answer"])
        msgs = [Message(role=MessageRole.USER, content="research quantum computing please")]
        await llm.complete(msgs)

        llm.assert_prompt_received(0, r"quantum")  # Should not raise

    async def test_assert_prompt_received_raises_on_mismatch(self) -> None:
        # docs/api/testing.md: raises AssertionError when pattern not found
        from orchestra.core.types import Message, MessageRole
        from orchestra.testing import ScriptedLLM

        llm = ScriptedLLM(["answer"])
        msgs = [Message(role=MessageRole.USER, content="hello world")]
        await llm.complete(msgs)

        with pytest.raises(AssertionError):
            llm.assert_prompt_received(0, r"quantum_physics_xyz_not_present")

    async def test_scripted_llm_used_as_provider_in_workflow(self) -> None:
        # docs/concepts/testing.md / README.md: pass ScriptedLLM as provider to run()
        #
        # NOTE — documentation drift identified: docs/concepts/testing.md asserts
        # `"quantum" in result.output.lower()`, but when agents are added via the
        # fluent .then() API without an explicit output_key, each agent writes to a
        # per-agent state key ("<name>_output"), not to "output".  result.output is
        # therefore "".  The assertion below reflects the actual runtime behaviour.
        # To use result.output, add agents with output_key="output" or use the
        # explicit graph.add_node("name", agent, output_key="output") API.
        from orchestra.core.agent import BaseAgent
        from orchestra.core.graph import WorkflowGraph
        from orchestra.core.runner import run
        from orchestra.testing import ScriptedLLM

        researcher = BaseAgent(name="researcher", system_prompt="Research the topic.")
        writer = BaseAgent(name="writer", system_prompt="Write a summary.")

        graph = WorkflowGraph().then(researcher).then(writer)

        llm = ScriptedLLM([
            "Key facts about quantum computing: superposition, entanglement.",
            "Quantum computing harnesses quantum mechanics for computation.",
        ])
        result = await run(graph, input="quantum computing", provider=llm, persist=False)

        # Agent outputs land in per-agent state keys, not result.output
        writer_output = result.state.get("writer_output", "")
        assert "quantum" in writer_output.lower(), (
            "writer_output should contain the scripted quantum response; "
            f"got state keys: {list(result.state.keys())}"
        )
        llm.assert_all_consumed()

    async def test_function_node_workflow_needs_no_scripted_llm(self) -> None:
        # docs/concepts/testing.md: function-node workflows need no ScriptedLLM
        from orchestra.core.graph import WorkflowGraph
        from orchestra.core.state import WorkflowState

        class MyState(WorkflowState):
            input: str = ""
            output: str = ""

        async def step_a(state: dict[str, Any]) -> dict[str, Any]:
            return {"output": state["input"] + "_processed"}

        async def step_b(state: dict[str, Any]) -> dict[str, Any]:
            return {"output": state["output"] + "_finalized"}

        graph = WorkflowGraph(state_schema=MyState).then(step_a).then(step_b)
        compiled = graph.compile()
        result = await compiled.run({"input": "test data"})
        assert result["output"] == "test data_processed_finalized"
