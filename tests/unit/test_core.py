"""Tests for core types, state, graph engine, agents, tools, and ScriptedLLM."""

from __future__ import annotations

import ast
import operator
import sqlite3
from typing import Annotated
from unittest.mock import AsyncMock, patch

import pytest

from orchestra.core.agent import BaseAgent, agent
from orchestra.core.context import ExecutionContext
from orchestra.core.errors import (
    GraphCompileError,
    MaxIterationsError,
    StateValidationError,
)
from orchestra.core.graph import WorkflowGraph
from orchestra.core.runner import RunResult, run
from orchestra.core.state import (
    WorkflowState,
    apply_state_update,
    concat_str,
    extract_reducers,
    keep_first,
    last_write_wins,
    max_value,
    merge_dict,
    merge_list,
    merge_parallel_updates,
    merge_set,
    min_value,
    sum_numbers,
)
from orchestra.core.types import (
    END,
    AgentResult,
    LLMResponse,
    Message,
    MessageRole,
    TokenUsage,
    ToolCall,
)
from orchestra.testing import ScriptedLLM, ScriptExhaustedError
from orchestra.tools import ToolRegistry, tool

# ===== Types =====


class TestTypes:
    def test_message_frozen(self):
        msg = Message(role=MessageRole.USER, content="hi")
        with pytest.raises(Exception):
            msg.content = "changed"

    def test_tool_call_generates_id(self):
        tc1 = ToolCall(name="test", arguments={})
        tc2 = ToolCall(name="test", arguments={})
        assert tc1.id != tc2.id
        assert tc1.id.startswith("call_")

    def test_end_sentinel_singleton(self):
        from orchestra.core.types import _EndSentinel
        assert END is _EndSentinel()
        assert _EndSentinel() == END
        assert hash(END) == hash(_EndSentinel())
        assert repr(END) == "END"

    def test_end_not_equal_to_string(self):
        assert END != "__end__"
        assert END != "END"

    def test_token_usage_provider_neutral(self):
        usage = TokenUsage(input_tokens=10, output_tokens=20, total_tokens=30)
        assert usage.input_tokens == 10
        assert usage.output_tokens == 20

    def test_agent_result_shape(self):
        result = AgentResult(
            agent_name="test",
            output="hello",
            state_updates={"key": "value"},
            token_usage=TokenUsage(input_tokens=5, output_tokens=10, total_tokens=15),
        )
        assert result.structured_output is None
        assert result.state_updates == {"key": "value"}
        assert result.token_usage.input_tokens == 5

    def test_message_serialization_roundtrip(self):
        msg = Message(role=MessageRole.ASSISTANT, content="test", name="agent1")
        data = msg.model_dump()
        restored = Message.model_validate(data)
        assert restored.content == "test"
        assert restored.name == "agent1"


# ===== State =====


class TestState:
    def test_all_nine_reducers_exist(self):
        fns = [merge_list, merge_dict, sum_numbers, last_write_wins,
               merge_set, concat_str, keep_first, max_value, min_value]
        assert len(fns) == 9
        for fn in fns:
            assert callable(fn)

    def test_merge_list(self):
        assert merge_list([1, 2], [3, 4]) == [1, 2, 3, 4]

    def test_merge_dict(self):
        assert merge_dict({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    def test_sum_numbers(self):
        assert sum_numbers(5, 3) == 8

    def test_merge_set(self):
        assert merge_set({1, 2}, {2, 3}) == {1, 2, 3}

    def test_concat_str(self):
        assert concat_str("hello ", "world") == "hello world"

    def test_keep_first(self):
        assert keep_first("original", "new") == "original"

    def test_max_value(self):
        assert max_value(5, 10) == 10

    def test_min_value(self):
        assert min_value(5, 10) == 5

    def test_extract_reducers(self):
        class S(WorkflowState):
            items: Annotated[list[str], merge_list] = []
            count: Annotated[int, sum_numbers] = 0
            plain: str = ""

        reducers = extract_reducers(S)
        assert "items" in reducers
        assert "count" in reducers
        assert "plain" not in reducers

    def test_apply_state_update_with_reducer(self):
        class S(WorkflowState):
            items: Annotated[list[str], merge_list] = []
            count: Annotated[int, sum_numbers] = 0

        state = S(items=["a"], count=1)
        reducers = extract_reducers(S)
        new_state = apply_state_update(state, {"items": ["b"], "count": 2}, reducers)
        assert new_state.items == ["a", "b"]
        assert new_state.count == 3

    def test_apply_state_update_last_write_wins(self):
        class S(WorkflowState):
            result: str = ""

        state = S(result="old")
        new_state = apply_state_update(state, {"result": "new"}, {})
        assert new_state.result == "new"

    def test_apply_state_update_unknown_field_raises(self):
        class S(WorkflowState):
            x: int = 0

        state = S(x=1)
        with pytest.raises(StateValidationError, match="Unknown state field"):
            apply_state_update(state, {"nonexistent": 1}, {})

    def test_apply_state_preserves_unmentioned(self):
        class S(WorkflowState):
            a: str = ""
            b: str = ""

        state = S(a="keep", b="old")
        new_state = apply_state_update(state, {"b": "new"}, {})
        assert new_state.a == "keep"
        assert new_state.b == "new"

    def test_merge_parallel_updates(self):
        class S(WorkflowState):
            items: Annotated[list[str], merge_list] = []
            count: Annotated[int, sum_numbers] = 0

        state = S()
        reducers = extract_reducers(S)
        updates = [
            {"items": ["from_a"], "count": 1},
            {"items": ["from_b"], "count": 2},
        ]
        merged = merge_parallel_updates(state, updates, reducers)
        assert merged.items == ["from_a", "from_b"]
        assert merged.count == 3

    def test_state_immutable_update(self):
        class S(WorkflowState):
            x: int = 0

        state = S(x=1)
        new_state = apply_state_update(state, {"x": 2}, {})
        assert state.x == 1
        assert new_state.x == 2


# ===== Graph =====


class TestGraph:
    def test_add_node_and_compile(self):
        async def noop(state: dict) -> dict:
            return {}

        g = WorkflowGraph()
        g.add_node("a", noop)
        g.set_entry_point("a")
        g.add_edge("a", END)
        compiled = g.compile()
        assert compiled is not None

    def test_add_node_rejects_duplicate(self):
        async def noop(state: dict) -> dict:
            return {}

        g = WorkflowGraph()
        g.add_node("a", noop)
        with pytest.raises(GraphCompileError):
            g.add_node("a", noop)

    def test_compile_raises_without_entry(self):
        g = WorkflowGraph()
        with pytest.raises(GraphCompileError):
            g.compile()

    def test_fluent_then(self):
        async def step_a(state: dict) -> dict:
            return {"result": "a"}

        async def step_b(state: dict) -> dict:
            return {"result": "b"}

        g = WorkflowGraph().then(step_a, name="a").then(step_b, name="b")
        compiled = g.compile()
        assert compiled is not None

    def test_to_mermaid(self):
        async def step_a(state: dict) -> dict:
            return {}

        async def step_b(state: dict) -> dict:
            return {}

        g = WorkflowGraph().then(step_a, name="a").then(step_b, name="b")
        mermaid = g.compile().to_mermaid()
        assert "graph TD" in mermaid
        assert "a" in mermaid
        assert "b" in mermaid


# ===== Execution =====


class TestExecution:
    @pytest.mark.asyncio
    async def test_sequential_two_node(self):
        class S(WorkflowState):
            result: str = ""
            count: Annotated[int, sum_numbers] = 0

        async def node_a(state: dict) -> dict:
            return {"result": "hello", "count": 1}

        async def node_b(state: dict) -> dict:
            return {"result": state["result"] + " world", "count": 1}

        g = WorkflowGraph(state_schema=S)
        g.add_node("a", node_a)
        g.add_node("b", node_b)
        g.set_entry_point("a")
        g.add_edge("a", "b")
        g.add_edge("b", END)

        result = await g.compile().run({})
        assert result["result"] == "hello world"
        assert result["count"] == 2

    @pytest.mark.asyncio
    async def test_conditional_routing(self):
        class S(WorkflowState):
            path: str = ""

        async def router(state: dict) -> dict:
            return {}

        async def branch_a(state: dict) -> dict:
            return {"path": "took_a"}

        async def branch_b(state: dict) -> dict:
            return {"path": "took_b"}

        g = WorkflowGraph(state_schema=S)
        g.add_node("router", router)
        g.add_node("a", branch_a)
        g.add_node("b", branch_b)
        g.set_entry_point("router")
        g.add_conditional_edge(
            "router",
            lambda s: "go_a",
            {"go_a": "a", "go_b": "b"},
        )
        g.add_edge("a", END)
        g.add_edge("b", END)

        result = await g.compile().run({})
        assert result["path"] == "took_a"

    @pytest.mark.asyncio
    async def test_parallel_fan_out(self):
        class S(WorkflowState):
            items: Annotated[list[str], merge_list] = []

        async def source(state: dict) -> dict:
            return {}

        async def worker_a(state: dict) -> dict:
            return {"items": ["from_a"]}

        async def worker_b(state: dict) -> dict:
            return {"items": ["from_b"]}

        async def joiner(state: dict) -> dict:
            return {}

        g = WorkflowGraph(state_schema=S)
        g.add_node("source", source)
        g.add_node("a", worker_a)
        g.add_node("b", worker_b)
        g.add_node("join", joiner)
        g.set_entry_point("source")
        g.add_parallel("source", ["a", "b"], join_node="join")
        g.add_edge("join", END)

        result = await g.compile().run({})
        assert "from_a" in result["items"]
        assert "from_b" in result["items"]

    @pytest.mark.asyncio
    async def test_max_turns_terminates(self):
        async def looper(state: dict) -> dict:
            return {}

        g = WorkflowGraph()
        g.add_node("loop", looper)
        g.set_entry_point("loop")
        g.add_edge("loop", "loop")

        with pytest.raises(MaxIterationsError):
            await g.compile(max_turns=5).run({})

    @pytest.mark.asyncio
    async def test_fluent_sequential_execution(self):
        async def step1(state: dict) -> dict:
            return {"output": "step1"}

        async def step2(state: dict) -> dict:
            return {"output": state.get("output", "") + "+step2"}

        g = WorkflowGraph().then(step1, name="s1").then(step2, name="s2")
        result = await g.compile().run({})
        assert result["output"] == "step1+step2"


# ===== Fluent API =====


class TestFluentAPI:
    @pytest.mark.asyncio
    async def test_branch_routes_correctly(self):
        class S(WorkflowState):
            category: str = ""
            output: str = ""

        async def classifier(state: dict) -> dict:
            return {"category": "tech"}

        async def tech_handler(state: dict) -> dict:
            return {"output": "tech result"}

        async def creative_handler(state: dict) -> dict:
            return {"output": "creative result"}

        g = (
            WorkflowGraph(state_schema=S)
            .then(classifier, name="classify")
            .branch(
                lambda s: s.get("category", ""),
                {"tech": tech_handler, "creative": creative_handler},
            )
        )
        result = await g.compile().run({})
        assert result["output"] == "tech result"

    @pytest.mark.asyncio
    async def test_if_then_true_branch(self):
        class S(WorkflowState):
            approved: bool = False
            output: str = ""

        async def checker(state: dict) -> dict:
            return {"approved": True}

        async def publisher(state: dict) -> dict:
            return {"output": "published"}

        async def reviser(state: dict) -> dict:
            return {"output": "revised"}

        g = (
            WorkflowGraph(state_schema=S)
            .then(checker, name="check")
            .if_then(lambda s: s.get("approved", False), publisher, reviser)
        )
        result = await g.compile().run({})
        assert result["output"] == "published"

    @pytest.mark.asyncio
    async def test_if_then_false_branch(self):
        class S(WorkflowState):
            approved: bool = False
            output: str = ""

        async def checker(state: dict) -> dict:
            return {"approved": False}

        async def publisher(state: dict) -> dict:
            return {"output": "published"}

        async def reviser(state: dict) -> dict:
            return {"output": "revised"}

        g = (
            WorkflowGraph(state_schema=S)
            .then(checker, name="check")
            .if_then(lambda s: s.get("approved", False), publisher, reviser)
        )
        result = await g.compile().run({})
        assert result["output"] == "revised"

    @pytest.mark.asyncio
    async def test_if_then_without_else(self):
        class S(WorkflowState):
            done: bool = False
            output: str = "initial"

        async def checker(state: dict) -> dict:
            return {"done": False}

        async def extra_step(state: dict) -> dict:
            return {"output": "extra"}

        g = (
            WorkflowGraph(state_schema=S)
            .then(checker, name="check")
            .if_then(lambda s: s.get("done", False), extra_step)
        )
        result = await g.compile().run({})
        assert result["output"] == "initial"

    @pytest.mark.asyncio
    async def test_loop_repeats_until_condition_false(self):
        class S(WorkflowState):
            count: Annotated[int, sum_numbers] = 0

        async def incrementer(state: dict) -> dict:
            return {"count": 1}

        g = (
            WorkflowGraph(state_schema=S)
            .then(incrementer, name="start")
            .loop(
                incrementer, name="looper",
                condition=lambda s: s.get("count", 0) < 3, max_iterations=10,
            )
        )
        result = await g.compile().run({})
        assert result["count"] == 3

    @pytest.mark.asyncio
    async def test_loop_respects_max_iterations(self):
        class S(WorkflowState):
            count: Annotated[int, sum_numbers] = 0

        async def incrementer(state: dict) -> dict:
            return {"count": 1}

        g = (
            WorkflowGraph(state_schema=S)
            .then(incrementer, name="start")
            .loop(incrementer, name="looper", condition=lambda s: True, max_iterations=3)
        )
        result = await g.compile().run({})
        # start gives 1, loop runs 3 times (max_iterations), total = 4
        assert result["count"] == 4

    @pytest.mark.asyncio
    async def test_loop_counter_resets_between_runs(self):
        class S(WorkflowState):
            count: Annotated[int, sum_numbers] = 0

        async def incrementer(state: dict) -> dict:
            return {"count": 1}

        g = (
            WorkflowGraph(state_schema=S)
            .then(incrementer, name="start")
            .loop(incrementer, name="looper", condition=lambda s: True, max_iterations=3)
        )
        compiled = g.compile()

        result1 = await compiled.run({})
        result2 = await compiled.run({})
        # Both runs should produce the same result
        assert result1["count"] == result2["count"]

    @pytest.mark.asyncio
    async def test_fluent_parallel_join(self):
        class S(WorkflowState):
            items: Annotated[list[str], merge_list] = []

        async def noop(state: dict) -> dict:
            return {}

        async def worker_a(state: dict) -> dict:
            return {"items": ["a"]}

        async def worker_b(state: dict) -> dict:
            return {"items": ["b"]}

        g = (
            WorkflowGraph(state_schema=S)
            .then(noop, name="start")
            .parallel(worker_a, worker_b, names=["wa", "wb"])
            .join(noop, name="join")
        )
        result = await g.compile().run({})
        assert "a" in result["items"]
        assert "b" in result["items"]

    def test_join_without_parallel_raises(self):
        async def noop(state: dict) -> dict:
            return {}

        g = WorkflowGraph().then(noop, name="start")
        with pytest.raises(GraphCompileError, match="Cannot join without"):
            g.join(noop, name="join")


# ===== Tools =====


class TestTools:
    def test_tool_decorator_no_args(self):
        @tool
        async def search(query: str) -> str:
            """Search the web."""
            return f"results for {query}"

        assert search.name == "search"
        assert search.description == "Search the web."
        assert "query" in search.parameters_schema["properties"]

    def test_tool_decorator_with_args(self):
        @tool(name="custom", description="Custom tool")
        async def fn(x: int) -> str:
            return str(x)

        assert fn.name == "custom"
        assert fn.description == "Custom tool"

    @pytest.mark.asyncio
    async def test_tool_execute(self):
        @tool
        async def add(a: int, b: int) -> str:
            """Add two numbers."""
            return str(a + b)

        result = await add.execute({"a": 2, "b": 3})
        assert result.content == "5"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_tool_execute_error(self):
        @tool
        async def fail(msg: str) -> str:
            """Always fails."""
            raise RuntimeError(msg)

        result = await fail.execute({"msg": "boom"})
        assert result.error is not None
        assert "boom" in result.error

    def test_registry(self):
        @tool
        async def t1(x: str) -> str:
            """Tool 1."""
            return x

        reg = ToolRegistry()
        reg.register(t1)
        assert reg.has("t1")
        assert len(reg) == 1
        assert reg.get("t1") is t1
        schemas = reg.get_schemas()
        assert len(schemas) == 1


# ===== ScriptedLLM =====


class TestScriptedLLM:
    @pytest.mark.asyncio
    async def test_returns_scripted_responses(self):
        llm = ScriptedLLM(["response 1", "response 2"])
        r1 = await llm.complete([])
        assert r1.content == "response 1"
        r2 = await llm.complete([])
        assert r2.content == "response 2"

    @pytest.mark.asyncio
    async def test_exhausted_raises(self):
        llm = ScriptedLLM(["only one"])
        await llm.complete([])
        with pytest.raises(ScriptExhaustedError):
            await llm.complete([])

    @pytest.mark.asyncio
    async def test_call_log(self):
        llm = ScriptedLLM(["r"])
        msgs = [Message(role=MessageRole.USER, content="hi")]
        await llm.complete(msgs, model="test-model")
        assert llm.call_count == 1
        assert llm.call_log[0]["model"] == "test-model"

    def test_reset(self):
        llm = ScriptedLLM(["a", "b"])
        llm.reset()
        assert llm.call_count == 0


# ===== Agent + ScriptedLLM Integration =====


class TestAgentIntegration:
    @pytest.mark.asyncio
    async def test_base_agent_with_scripted_llm(self):
        llm = ScriptedLLM(["Hello from the agent!"])
        agent_inst = BaseAgent(name="greeter", system_prompt="Be friendly")
        ctx = ExecutionContext(provider=llm)

        result = await agent_inst.run("Hi there", ctx)
        assert result.agent_name == "greeter"
        assert result.output == "Hello from the agent!"
        assert llm.call_count == 1

    @pytest.mark.asyncio
    async def test_decorator_agent_with_scripted_llm(self):
        @agent(name="writer", model="gpt-4o-mini")
        async def writer(topic: str) -> str:
            """You are a technical writer."""

        llm = ScriptedLLM(["A well-written article."])
        ctx = ExecutionContext(provider=llm)

        result = await writer.run("Write about AI", ctx)
        assert result.output == "A well-written article."

    @pytest.mark.asyncio
    async def test_max_iterations_attaches_partial_output(self):
        """MaxIterationsError.partial_output must contain accumulated tool records."""
        @tool
        async def noop_tool(x: str) -> str:
            """Do nothing."""
            return x

        # Every LLM call returns a tool-call, so the loop never finishes naturally.
        responses = [
            LLMResponse(
                content="calling tool",
                tool_calls=[ToolCall(name="noop_tool", arguments={"x": str(i)})],
            )
            for i in range(5)
        ]
        llm = ScriptedLLM(responses)
        agent_inst = BaseAgent(name="looper", tools=[noop_tool], max_iterations=3)
        ctx = ExecutionContext(provider=llm)

        with pytest.raises(MaxIterationsError) as exc_info:
            await agent_inst.run("go", ctx)

        err = exc_info.value
        assert err.partial_output is not None, "partial_output should be attached to the exception"
        assert err.partial_output.partial is True
        # 3 iterations → 3 tool calls recorded
        assert len(err.partial_output.tool_calls_made) == 3

    @pytest.mark.asyncio
    async def test_max_iterations_emit_partial_returns_result(self):
        """emit_partial_on_max_iterations=True must return a partial AgentResult
        instead of raising."""
        @tool
        async def noop_tool(x: str) -> str:
            """Do nothing."""
            return x

        responses = [
            LLMResponse(
                content="calling tool",
                tool_calls=[ToolCall(name="noop_tool", arguments={"x": str(i)})],
            )
            for i in range(5)
        ]
        llm = ScriptedLLM(responses)
        agent_inst = BaseAgent(name="looper", tools=[noop_tool], max_iterations=2)
        ctx = ExecutionContext(provider=llm)

        result = await agent_inst.run("go", ctx, emit_partial_on_max_iterations=True)

        assert isinstance(result, AgentResult)
        assert result.partial is True
        assert len(result.tool_calls_made) == 2  # max_iterations tool calls

    @pytest.mark.asyncio
    async def test_agent_tool_loop(self):
        @tool
        async def calculator(expression: str) -> str:
            """Evaluate a math expression safely (no eval)."""
            _ops = {
                ast.Add: operator.add,
                ast.Sub: operator.sub,
                ast.Mult: operator.mul,
            }

            def _safe_eval(node: ast.expr) -> int | float:
                if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                    return node.value
                if isinstance(node, ast.BinOp) and type(node.op) in _ops:
                    return _ops[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
                raise ValueError(f"Unsupported: {ast.dump(node)}")

            tree = ast.parse(expression, mode="eval")
            return str(_safe_eval(tree.body))

        # First response has a tool call, second is final
        llm = ScriptedLLM([
            LLMResponse(
                content="Let me calculate that.",
                tool_calls=[ToolCall(name="calculator", arguments={"expression": "2+2"})],
            ),
            LLMResponse(content="The answer is 4."),
        ])

        agent_inst = BaseAgent(name="math", tools=[calculator])
        ctx = ExecutionContext(provider=llm)
        result = await agent_inst.run("What is 2+2?", ctx)

        assert result.output == "The answer is 4."
        assert len(result.tool_calls_made) == 1
        assert llm.call_count == 2


# ===== run() =====


class TestRunner:
    @pytest.mark.asyncio
    async def test_run_function(self):
        async def step(state: dict) -> dict:
            return {"output": "done"}

        g = WorkflowGraph().then(step, name="step")
        result = await run(g, input={"data": "test"})

        assert isinstance(result, RunResult)
        assert result.state["output"] == "done"
        assert result.duration_ms > 0
        assert "step" in result.node_execution_order


# ===== SubgraphBuilder Security (CRITICAL-4.5) =====


class TestSubgraphBuilderSecurity:
    """Verify that the dynamic.py allowlist independently blocks untrusted modules
    and that the stored allowlist tuple cannot be mutated at runtime."""

    def test_dynamic_allowlist_blocks_untrusted_module(self):
        """SubgraphBuilder.resolve_ref must raise ImportError for any ref not
        covered by the configured allowlist, before importlib is invoked."""
        from orchestra.core.dynamic import SubgraphBuilder

        builder = SubgraphBuilder(allowed_prefixes=["orchestra.core.", "orchestra.tools."])

        for untrusted_ref in ("os.path", "subprocess.run", "sys.exit", "builtins.eval"):
            with pytest.raises(ImportError, match="not in the security allowlist"):
                builder.resolve_ref(untrusted_ref)

    def test_dynamic_allowlist_is_immutable(self):
        """The allowlist stored on SubgraphBuilder._allowed_prefixes must be a
        tuple (immutable). Any attempt to append or assign into it must raise
        TypeError (tuple does not support mutation) or AttributeError."""
        from orchestra.core.dynamic import SubgraphBuilder, DEFAULT_ALLOWED_PREFIXES

        builder = SubgraphBuilder()

        # Verify it is stored as a tuple, not a mutable list or set.
        assert isinstance(builder._allowed_prefixes, tuple), (
            "_allowed_prefixes must be a tuple, not "
            f"{type(builder._allowed_prefixes).__name__}"
        )

        # Attempting to call .append() must raise AttributeError (tuples have no append).
        with pytest.raises(AttributeError):
            builder._allowed_prefixes.append("malicious.")  # type: ignore[attr-defined]

        # Attempting item assignment must raise TypeError.
        with pytest.raises(TypeError):
            builder._allowed_prefixes[0] = "malicious."  # type: ignore[index]

        # The module-level DEFAULT_ALLOWED_PREFIXES constant must also be a tuple.
        assert isinstance(DEFAULT_ALLOWED_PREFIXES, tuple), (
            "DEFAULT_ALLOWED_PREFIXES must be a tuple"
        )
        with pytest.raises(AttributeError):
            DEFAULT_ALLOWED_PREFIXES.append("malicious.")  # type: ignore[attr-defined]


# ===== Checkpoint Resume Exception Handling (CRITICAL-1.2) =====


class TestCheckpointResumeExceptions:
    """Verify that CompiledGraph.resume() catches only expected I/O and DB exceptions
    when auto-initialising the SQLite event store, and lets all other exceptions
    propagate without being swallowed.

    The try block in question (compiled.py lines 262-267):
        from orchestra.storage.sqlite import SQLiteEventStore
        event_store = SQLiteEventStore()
        await event_store.initialize()

    Expected to catch and wrap as AgentError: ImportError, OSError, sqlite3.Error.
    Expected to propagate without wrapping: RuntimeError (and any other Exception
    subclass not in the narrow list above).
    """

    def _make_compiled_graph(self) -> "object":
        """Return a minimal compiled graph instance for calling resume()."""
        from orchestra.core.graph import WorkflowGraph
        from orchestra.core.types import END

        async def noop(state: dict) -> dict:
            return {}

        g = WorkflowGraph()
        g.add_node("a", noop)
        g.set_entry_point("a")
        g.add_edge("a", END)
        return g.compile()

    @pytest.mark.asyncio
    async def test_import_error_becomes_agent_error(self):
        """ImportError (missing aiosqlite/module) is wrapped as AgentError."""
        from orchestra.core.errors import AgentError

        compiled = self._make_compiled_graph()
        with patch(
            "orchestra.storage.sqlite.SQLiteEventStore",
            side_effect=ImportError("aiosqlite not installed"),
        ):
            with patch(
                "orchestra.core.compiled.SQLiteEventStore",
                side_effect=ImportError("aiosqlite not installed"),
                create=True,
            ):
                # The import inside resume() itself — patch the module-level import
                with patch.dict(
                    "sys.modules",
                    {"orchestra.storage.sqlite": None},
                ):
                    with pytest.raises(AgentError, match="Failed to auto-initialize"):
                        await compiled.resume("nonexistent-run-id")

    @pytest.mark.asyncio
    async def test_os_error_becomes_agent_error(self):
        """OSError from makedirs (e.g. permission denied) is wrapped as AgentError."""
        from orchestra.core.errors import AgentError

        compiled = self._make_compiled_graph()

        mock_store = AsyncMock()
        mock_store.initialize = AsyncMock(side_effect=OSError("Permission denied"))

        with patch("orchestra.core.compiled.SQLiteEventStore", return_value=mock_store, create=True):
            # Force the branch where event_store is None by not passing event_store;
            # we also need the import inside the function to succeed and return our mock.
            # Patch at the location where the name is looked up inside the function body.
            import orchestra.storage.sqlite as _sqlite_mod
            original_cls = getattr(_sqlite_mod, "SQLiteEventStore", None)
            _sqlite_mod.SQLiteEventStore = lambda *a, **kw: mock_store  # type: ignore[attr-defined]
            try:
                with pytest.raises(AgentError, match="Failed to auto-initialize"):
                    await compiled.resume("nonexistent-run-id")
            finally:
                if original_cls is not None:
                    _sqlite_mod.SQLiteEventStore = original_cls  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_sqlite_error_becomes_agent_error(self):
        """sqlite3.Error from DB operations is wrapped as AgentError."""
        from orchestra.core.errors import AgentError

        compiled = self._make_compiled_graph()

        mock_store = AsyncMock()
        mock_store.initialize = AsyncMock(
            side_effect=sqlite3.OperationalError("disk I/O error")
        )

        import orchestra.storage.sqlite as _sqlite_mod
        original_cls = getattr(_sqlite_mod, "SQLiteEventStore", None)
        _sqlite_mod.SQLiteEventStore = lambda *a, **kw: mock_store  # type: ignore[attr-defined]
        try:
            with pytest.raises(AgentError, match="Failed to auto-initialize"):
                await compiled.resume("nonexistent-run-id")
        finally:
            if original_cls is not None:
                _sqlite_mod.SQLiteEventStore = original_cls  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_runtime_error_propagates(self):
        """RuntimeError must NOT be swallowed — it should propagate as-is."""
        compiled = self._make_compiled_graph()

        mock_store = AsyncMock()
        mock_store.initialize = AsyncMock(
            side_effect=RuntimeError("unexpected internal failure")
        )

        import orchestra.storage.sqlite as _sqlite_mod
        original_cls = getattr(_sqlite_mod, "SQLiteEventStore", None)
        _sqlite_mod.SQLiteEventStore = lambda *a, **kw: mock_store  # type: ignore[attr-defined]
        try:
            with pytest.raises(RuntimeError, match="unexpected internal failure"):
                await compiled.resume("nonexistent-run-id")
        finally:
            if original_cls is not None:
                _sqlite_mod.SQLiteEventStore = original_cls  # type: ignore[attr-defined]
