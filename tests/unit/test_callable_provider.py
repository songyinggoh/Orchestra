"""Tests for CallableProvider — wraps any callable as an LLM provider.

Coverage:
  1.  Sync (str) -> str function
  2.  Async (str) -> str function
  3.  Function accepting list[Message]
  4.  Function accepting list[Message] + **kwargs
  5.  Function returning LLMResponse directly
  6.  Integration with BaseAgent in a WorkflowGraph (full pipeline)
  7.  Handoff between two agents in a graph (state flows correctly)
  8.  stream() yields word-by-word chunks + final stop chunk
  9.  count_tokens() approximation
  10. get_model_cost() always returns zero
  11. provider_name and default_model properties
  12. Custom name and model_name constructor kwargs
  13. None return value converted to empty string
  14. Non-string return value coerced to str
  15. Messages flattened to "role: content" lines for str-accepting functions

NOTE: This file intentionally omits ``from __future__ import annotations``.
CallableProvider's signature detection relies on ``inspect.signature()`` resolving
annotation objects at construction time.  PEP 563 deferred evaluation (activated
by that import) turns all annotations into strings, which breaks ``__origin__``/
``__args__`` introspection.  Keeping eager evaluation here means ``list[Message]``
in test callables resolves to a live GenericAlias, matching the production use-case
where users write normal (non-deferred) type annotations on their functions.
"""

from typing import Annotated

import pytest

from orchestra.core.agent import BaseAgent
from orchestra.core.context import ExecutionContext
from orchestra.core.graph import WorkflowGraph
from orchestra.core.state import WorkflowState, merge_list
from orchestra.core.types import (
    END,
    LLMResponse,
    Message,
    MessageRole,
    ModelCost,
    StreamChunk,
)
from orchestra.providers import CallableProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user(content: str) -> Message:
    return Message(role=MessageRole.USER, content=content)


def _system(content: str) -> Message:
    return Message(role=MessageRole.SYSTEM, content=content)


def _assistant(content: str) -> Message:
    return Message(role=MessageRole.ASSISTANT, content=content)


# ---------------------------------------------------------------------------
# Class 1: Sync (str) -> str
# ---------------------------------------------------------------------------


class TestSyncStringFunction:
    """CallableProvider wrapping a plain sync (str) -> str function."""

    def _make_provider(self, fn=None) -> CallableProvider:
        if fn is None:
            def fn(prompt: str) -> str:
                return f"echo: {prompt}"
        return CallableProvider(fn)

    @pytest.mark.asyncio
    async def test_complete_returns_llm_response(self) -> None:
        provider = self._make_provider()
        result = await provider.complete([_user("hello")])
        assert isinstance(result, LLMResponse)

    @pytest.mark.asyncio
    async def test_complete_content_contains_echoed_prompt(self) -> None:
        provider = self._make_provider()
        result = await provider.complete([_user("hello")])
        assert "echo:" in result.content
        assert "hello" in result.content

    @pytest.mark.asyncio
    async def test_complete_flattens_messages_to_prompt(self) -> None:
        captured: list[str] = []

        def capture(prompt: str) -> str:
            captured.append(prompt)
            return "ok"

        provider = CallableProvider(capture)
        await provider.complete([_system("be concise"), _user("hi")])

        assert len(captured) == 1
        flat = captured[0]
        # Each message appears as "role: content" on its own line
        assert "system: be concise" in flat
        assert "user: hi" in flat

    @pytest.mark.asyncio
    async def test_complete_uses_default_model_when_none_passed(self) -> None:
        provider = CallableProvider(lambda p: "reply", model_name="my-model")
        result = await provider.complete([_user("hi")])
        assert result.model == "my-model"

    @pytest.mark.asyncio
    async def test_complete_uses_explicit_model_when_passed(self) -> None:
        provider = CallableProvider(lambda p: "reply", model_name="default")
        result = await provider.complete([_user("hi")], model="override-model")
        assert result.model == "override-model"

    @pytest.mark.asyncio
    async def test_none_return_becomes_empty_string(self) -> None:
        provider = CallableProvider(lambda p: None)
        result = await provider.complete([_user("hi")])
        assert result.content == ""

    @pytest.mark.asyncio
    async def test_non_string_return_coerced_to_str(self) -> None:
        provider = CallableProvider(lambda p: 42)
        result = await provider.complete([_user("hi")])
        assert result.content == "42"

    def test_is_async_flag_false_for_sync_function(self) -> None:
        provider = CallableProvider(lambda p: "ok")
        assert provider._is_async is False

    def test_accepts_messages_false_for_str_param(self) -> None:
        def fn(prompt: str) -> str:
            return prompt
        provider = CallableProvider(fn)
        assert provider._accepts_messages is False


# ---------------------------------------------------------------------------
# Class 2: Async (str) -> str
# ---------------------------------------------------------------------------


class TestAsyncStringFunction:
    """CallableProvider wrapping an async (str) -> str function."""

    @pytest.mark.asyncio
    async def test_async_fn_called_and_awaited(self) -> None:
        async def my_llm(prompt: str) -> str:
            return f"async: {prompt}"

        provider = CallableProvider(my_llm)
        result = await provider.complete([_user("test")])
        assert result.content == "async: user: test"

    @pytest.mark.asyncio
    async def test_async_fn_complete_returns_llm_response(self) -> None:
        async def my_llm(prompt: str) -> str:
            return "done"

        provider = CallableProvider(my_llm)
        result = await provider.complete([_user("x")])
        assert isinstance(result, LLMResponse)
        assert result.content == "done"

    def test_is_async_flag_true_for_async_function(self) -> None:
        async def my_llm(prompt: str) -> str:
            return "ok"

        provider = CallableProvider(my_llm)
        assert provider._is_async is True

    @pytest.mark.asyncio
    async def test_async_fn_multiple_messages_flattened(self) -> None:
        received: list[str] = []

        async def capture(prompt: str) -> str:
            received.append(prompt)
            return "ok"

        provider = CallableProvider(capture)
        await provider.complete([_system("sys"), _user("usr"), _assistant("asst")])

        flat = received[0]
        assert "system: sys" in flat
        assert "user: usr" in flat
        assert "assistant: asst" in flat


# ---------------------------------------------------------------------------
# Class 3: Function accepting list[Message]
# ---------------------------------------------------------------------------


class TestMessageListFunction:
    """CallableProvider whose callable accepts list[Message]."""

    @pytest.mark.asyncio
    async def test_receives_raw_message_objects(self) -> None:
        received: list[list[Message]] = []

        def fn(messages: list[Message]) -> str:
            received.append(messages)
            return "got messages"

        provider = CallableProvider(fn)
        msgs = [_user("hello")]
        await provider.complete(msgs)

        assert len(received) == 1
        assert received[0] is msgs

    @pytest.mark.asyncio
    async def test_message_content_preserved(self) -> None:
        def fn(messages: list[Message]) -> str:
            return messages[0].content

        provider = CallableProvider(fn)
        result = await provider.complete([_user("my content")])
        assert result.content == "my content"

    @pytest.mark.asyncio
    async def test_multiple_messages_all_passed(self) -> None:
        def fn(messages: list[Message]) -> str:
            return str(len(messages))

        provider = CallableProvider(fn)
        result = await provider.complete([_system("s"), _user("u"), _assistant("a")])
        assert result.content == "3"

    def test_accepts_messages_true_when_annotated_as_list_message(self) -> None:
        def fn(messages: list[Message]) -> str:
            return "ok"

        provider = CallableProvider(fn)
        assert provider._accepts_messages is True

    @pytest.mark.asyncio
    async def test_async_message_list_function(self) -> None:
        async def fn(messages: list[Message]) -> str:
            return messages[-1].content

        provider = CallableProvider(fn)
        result = await provider.complete([_user("first"), _user("last")])
        assert result.content == "last"


# ---------------------------------------------------------------------------
# Class 4: Function accepting list[Message], **kwargs
# ---------------------------------------------------------------------------


class TestMessageListWithKwargsFunction:
    """CallableProvider whose callable accepts messages + **kwargs."""

    @pytest.mark.asyncio
    async def test_kwargs_passed_through(self) -> None:
        received_kwargs: dict = {}

        def fn(messages: list[Message], **kwargs) -> str:
            received_kwargs.update(kwargs)
            return "ok"

        provider = CallableProvider(fn)
        await provider.complete([_user("hi")], model="gpt-x", temperature=0.3)

        assert received_kwargs.get("model") == "gpt-x"
        assert received_kwargs.get("temperature") == 0.3

    @pytest.mark.asyncio
    async def test_messages_still_received_correctly(self) -> None:
        def fn(messages: list[Message], **kwargs) -> str:
            return messages[0].content

        provider = CallableProvider(fn)
        result = await provider.complete([_user("kwarg test")])
        assert result.content == "kwarg test"

    @pytest.mark.asyncio
    async def test_async_messages_with_kwargs(self) -> None:
        captured: dict = {}

        async def fn(messages: list[Message], **kwargs) -> str:
            captured.update(kwargs)
            return "async-ok"

        provider = CallableProvider(fn)
        result = await provider.complete([_user("hi")], model="test-model")
        assert result.content == "async-ok"
        assert captured.get("model") == "test-model"

    def test_accepts_kwargs_true_when_var_keyword_present(self) -> None:
        def fn(messages: list[Message], **kwargs) -> str:
            return "ok"

        provider = CallableProvider(fn)
        assert provider._accepts_kwargs is True

    @pytest.mark.asyncio
    async def test_tools_kwarg_forwarded(self) -> None:
        captured_tools: list = []

        def fn(messages: list[Message], **kwargs) -> str:
            captured_tools.extend(kwargs.get("tools") or [])
            return "ok"

        provider = CallableProvider(fn)
        tool_schema = [{"name": "search", "description": "Search"}]
        await provider.complete([_user("hi")], tools=tool_schema)

        assert captured_tools == tool_schema


# ---------------------------------------------------------------------------
# Class 5: Function returning LLMResponse directly
# ---------------------------------------------------------------------------


class TestFunctionReturningLLMResponse:
    """When the callable returns an LLMResponse, it is used as-is."""

    @pytest.mark.asyncio
    async def test_llm_response_returned_directly(self) -> None:
        expected = LLMResponse(content="direct response", model="custom-model")

        def fn(prompt: str) -> LLMResponse:
            return expected

        provider = CallableProvider(fn)
        result = await provider.complete([_user("hi")])

        assert result is expected
        assert result.content == "direct response"
        assert result.model == "custom-model"

    @pytest.mark.asyncio
    async def test_async_fn_returning_llm_response(self) -> None:
        async def fn(prompt: str) -> LLMResponse:
            return LLMResponse(content="async direct", model="x")

        provider = CallableProvider(fn)
        result = await provider.complete([_user("hi")])
        assert result.content == "async direct"

    @pytest.mark.asyncio
    async def test_llm_response_with_finish_reason_preserved(self) -> None:
        def fn(prompt: str) -> LLMResponse:
            return LLMResponse(content="done", finish_reason="stop", model="m")

        provider = CallableProvider(fn)
        result = await provider.complete([_user("hi")])
        assert result.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_string_return_is_wrapped_not_passthrough(self) -> None:
        """String returns are wrapped, not returned as LLMResponse directly."""
        def fn(prompt: str) -> str:
            return "plain string"

        provider = CallableProvider(fn)
        result = await provider.complete([_user("hi")])
        assert isinstance(result, LLMResponse)
        assert result.content == "plain string"


# ---------------------------------------------------------------------------
# Class 6: Integration with BaseAgent in a WorkflowGraph
# ---------------------------------------------------------------------------


class TestBaseAgentIntegration:
    """Full pipeline: BaseAgent using CallableProvider inside a WorkflowGraph."""

    @pytest.mark.asyncio
    async def test_agent_in_graph_produces_output(self) -> None:
        class S(WorkflowState):
            output: str = ""

        def my_llm(prompt: str) -> str:
            return "graph agent reply"

        provider = CallableProvider(my_llm)
        agent_inst = BaseAgent(name="graph_agent", system_prompt="You are helpful.")
        ctx = ExecutionContext(provider=provider)

        async def agent_node(state: dict) -> dict:
            result = await agent_inst.run(state.get("input", "hello"), ctx)
            return {"output": result.output}

        g = WorkflowGraph(state_schema=S)
        g.add_node("agent", agent_node)
        g.set_entry_point("agent")
        g.add_edge("agent", END)

        final = await g.compile().run({"input": "run me"})
        assert final["output"] == "graph agent reply"

    @pytest.mark.asyncio
    async def test_agent_receives_input_from_state(self) -> None:
        class S(WorkflowState):
            question: str = ""
            answer: str = ""

        def answerer(prompt: str) -> str:
            if "capital" in prompt.lower():
                return "Paris"
            return "unknown"

        provider = CallableProvider(answerer)
        agent_inst = BaseAgent(name="qa_agent")
        ctx = ExecutionContext(provider=provider)

        async def qa_node(state: dict) -> dict:
            result = await agent_inst.run(state["question"], ctx)
            return {"answer": result.output}

        g = WorkflowGraph(state_schema=S)
        g.add_node("qa", qa_node)
        g.set_entry_point("qa")
        g.add_edge("qa", END)

        final = await g.compile().run({"question": "What is the capital of France?"})
        assert final["answer"] == "Paris"

    @pytest.mark.asyncio
    async def test_multiple_nodes_each_with_own_callable_provider(self) -> None:
        class S(WorkflowState):
            step1: str = ""
            step2: str = ""

        provider_a = CallableProvider(lambda p: "step1-done")
        provider_b = CallableProvider(lambda p: "step2-done")
        agent_a = BaseAgent(name="agent_a")
        agent_b = BaseAgent(name="agent_b")
        ctx_a = ExecutionContext(provider=provider_a)
        ctx_b = ExecutionContext(provider=provider_b)

        async def node_a(state: dict) -> dict:
            result = await agent_a.run("go", ctx_a)
            return {"step1": result.output}

        async def node_b(state: dict) -> dict:
            result = await agent_b.run("go", ctx_b)
            return {"step2": result.output}

        g = WorkflowGraph(state_schema=S)
        g.add_node("a", node_a)
        g.add_node("b", node_b)
        g.set_entry_point("a")
        g.add_edge("a", "b")
        g.add_edge("b", END)

        final = await g.compile().run({})
        assert final["step1"] == "step1-done"
        assert final["step2"] == "step2-done"

    @pytest.mark.asyncio
    async def test_agent_result_agent_name_matches(self) -> None:
        provider = CallableProvider(lambda p: "hello")
        agent_inst = BaseAgent(name="named_agent")
        ctx = ExecutionContext(provider=provider)

        result = await agent_inst.run("hi", ctx)
        assert result.agent_name == "named_agent"


# ---------------------------------------------------------------------------
# Class 7: Handoff between two agents (state flows correctly)
# ---------------------------------------------------------------------------


class TestAgentHandoff:
    """Two agents in a graph — state written by the first is readable by the second."""

    @pytest.mark.asyncio
    async def test_state_passes_between_agents(self) -> None:
        class S(WorkflowState):
            phase: str = ""
            summary: str = ""

        provider_a = CallableProvider(lambda p: "analysis complete")
        provider_b = CallableProvider(lambda p: "report written")
        agent_a = BaseAgent(name="analyst")
        agent_b = BaseAgent(name="reporter")
        ctx_a = ExecutionContext(provider=provider_a)
        ctx_b = ExecutionContext(provider=provider_b)

        async def analyst_node(state: dict) -> dict:
            result = await agent_a.run("analyse", ctx_a)
            return {"phase": "analysed", "summary": result.output}

        async def reporter_node(state: dict) -> dict:
            # reporter sees the phase set by analyst
            assert state["phase"] == "analysed"
            result = await agent_b.run(state["summary"], ctx_b)
            return {"phase": "reported", "summary": result.output}

        g = WorkflowGraph(state_schema=S)
        g.add_node("analyst", analyst_node)
        g.add_node("reporter", reporter_node)
        g.set_entry_point("analyst")
        g.add_edge("analyst", "reporter")
        g.add_edge("reporter", END)

        final = await g.compile().run({})
        assert final["phase"] == "reported"
        assert final["summary"] == "report written"

    @pytest.mark.asyncio
    async def test_accumulated_list_state_across_agents(self) -> None:
        class S(WorkflowState):
            messages: Annotated[list[str], merge_list] = []

        def make_agent_node(name: str, reply: str, provider: CallableProvider):
            agent_inst = BaseAgent(name=name)
            ctx = ExecutionContext(provider=provider)

            async def node(state: dict) -> dict:
                result = await agent_inst.run("go", ctx)
                return {"messages": [result.output]}

            return node

        node_a = make_agent_node("a", "from-a", CallableProvider(lambda p: "from-a"))
        node_b = make_agent_node("b", "from-b", CallableProvider(lambda p: "from-b"))

        g = WorkflowGraph(state_schema=S)
        g.add_node("a", node_a)
        g.add_node("b", node_b)
        g.set_entry_point("a")
        g.add_edge("a", "b")
        g.add_edge("b", END)

        final = await g.compile().run({})
        assert "from-a" in final["messages"]
        assert "from-b" in final["messages"]

    @pytest.mark.asyncio
    async def test_second_agent_uses_output_of_first_as_input(self) -> None:
        class S(WorkflowState):
            processed: str = ""

        def uppercase_llm(prompt: str) -> str:
            # Extract the last "user:" line and uppercase it
            for line in reversed(prompt.splitlines()):
                if line.startswith("user:"):
                    return line.split(":", 1)[1].strip().upper()
            return prompt.upper()

        def exclaim_llm(prompt: str) -> str:
            for line in reversed(prompt.splitlines()):
                if line.startswith("user:"):
                    return line.split(":", 1)[1].strip() + "!!!"
            return prompt + "!!!"

        provider_up = CallableProvider(uppercase_llm)
        provider_ex = CallableProvider(exclaim_llm)
        agent_up = BaseAgent(name="uppercaser")
        agent_ex = BaseAgent(name="exclaimer")
        ctx_up = ExecutionContext(provider=provider_up)
        ctx_ex = ExecutionContext(provider=provider_ex)

        async def upper_node(state: dict) -> dict:
            result = await agent_up.run("hello world", ctx_up)
            return {"processed": result.output}

        async def exclaim_node(state: dict) -> dict:
            result = await agent_ex.run(state["processed"], ctx_ex)
            return {"processed": result.output}

        g = WorkflowGraph(state_schema=S)
        g.add_node("upper", upper_node)
        g.add_node("exclaim", exclaim_node)
        g.set_entry_point("upper")
        g.add_edge("upper", "exclaim")
        g.add_edge("exclaim", END)

        final = await g.compile().run({})
        assert final["processed"] == "HELLO WORLD!!!"


# ---------------------------------------------------------------------------
# Class 8: stream() method
# ---------------------------------------------------------------------------


class TestStream:
    """stream() yields word-by-word StreamChunks then a stop chunk."""

    @pytest.mark.asyncio
    async def test_stream_yields_stream_chunks(self) -> None:
        provider = CallableProvider(lambda p: "hello world foo")
        chunks = []
        async for chunk in provider.stream([_user("hi")]):
            chunks.append(chunk)

        assert all(isinstance(c, StreamChunk) for c in chunks)

    @pytest.mark.asyncio
    async def test_stream_word_by_word_content(self) -> None:
        provider = CallableProvider(lambda p: "one two three")
        content_chunks = []
        async for chunk in provider.stream([_user("hi")]):
            if chunk.content:
                content_chunks.append(chunk)

        # Each word emitted as its own chunk with trailing space
        texts = [c.content.strip() for c in content_chunks]
        assert "one" in texts
        assert "two" in texts
        assert "three" in texts

    @pytest.mark.asyncio
    async def test_stream_final_chunk_has_stop_finish_reason(self) -> None:
        provider = CallableProvider(lambda p: "done")
        chunks = []
        async for chunk in provider.stream([_user("hi")]):
            chunks.append(chunk)

        last = chunks[-1]
        assert last.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_stream_final_chunk_empty_content(self) -> None:
        provider = CallableProvider(lambda p: "word")
        chunks = []
        async for chunk in provider.stream([_user("hi")]):
            chunks.append(chunk)

        last = chunks[-1]
        assert last.content == ""

    @pytest.mark.asyncio
    async def test_stream_empty_response_only_stop_chunk(self) -> None:
        provider = CallableProvider(lambda p: "")
        chunks = []
        async for chunk in provider.stream([_user("hi")]):
            chunks.append(chunk)

        # No content chunks — only the stop sentinel
        assert len(chunks) == 1
        assert chunks[0].finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_stream_chunk_model_set(self) -> None:
        provider = CallableProvider(lambda p: "hello", model_name="stream-model")
        chunks = []
        async for chunk in provider.stream([_user("hi")]):
            chunks.append(chunk)

        # All chunks should carry the model name
        for chunk in chunks:
            assert chunk.model == "stream-model"

    @pytest.mark.asyncio
    async def test_stream_with_explicit_model_override(self) -> None:
        provider = CallableProvider(lambda p: "hi", model_name="default")
        chunks = []
        async for chunk in provider.stream([_user("hi")], model="override"):
            chunks.append(chunk)

        for chunk in chunks:
            assert chunk.model == "override"

    @pytest.mark.asyncio
    async def test_stream_async_fn(self) -> None:
        async def fn(prompt: str) -> str:
            return "streamed async"

        provider = CallableProvider(fn)
        chunks = []
        async for chunk in provider.stream([_user("hi")]):
            chunks.append(chunk)

        content_text = "".join(c.content for c in chunks if c.content)
        assert "streamed" in content_text
        assert "async" in content_text


# ---------------------------------------------------------------------------
# Class 9: count_tokens()
# ---------------------------------------------------------------------------


class TestCountTokens:
    """count_tokens() returns a reasonable approximate integer."""

    def test_returns_int(self) -> None:
        provider = CallableProvider(lambda p: "ok")
        count = provider.count_tokens([_user("hello")])
        assert isinstance(count, int)

    def test_positive_for_non_empty_messages(self) -> None:
        provider = CallableProvider(lambda p: "ok")
        count = provider.count_tokens([_user("hello world")])
        assert count > 0

    def test_grows_with_message_length(self) -> None:
        provider = CallableProvider(lambda p: "ok")
        short = provider.count_tokens([_user("hi")])
        long = provider.count_tokens([_user("hi " * 100)])
        assert long > short

    def test_grows_with_message_count(self) -> None:
        provider = CallableProvider(lambda p: "ok")
        one = provider.count_tokens([_user("hello")])
        many = provider.count_tokens([_user("hello")] * 5)
        assert many > one

    def test_empty_messages_returns_non_negative(self) -> None:
        provider = CallableProvider(lambda p: "ok")
        count = provider.count_tokens([])
        assert count >= 0

    def test_model_arg_accepted_without_error(self) -> None:
        provider = CallableProvider(lambda p: "ok")
        count = provider.count_tokens([_user("hi")], model="gpt-4")
        assert isinstance(count, int)

    def test_approximation_formula(self) -> None:
        """Each message contributes len(content)//4 + 4 tokens."""
        provider = CallableProvider(lambda p: "ok")
        content = "a" * 40  # 40 chars -> 40//4 + 4 = 14
        expected = 14
        count = provider.count_tokens([_user(content)])
        assert count == expected


# ---------------------------------------------------------------------------
# Class 10: get_model_cost()
# ---------------------------------------------------------------------------


class TestGetModelCost:
    """get_model_cost() always returns zero-cost ModelCost."""

    def test_returns_model_cost_instance(self) -> None:
        provider = CallableProvider(lambda p: "ok")
        cost = provider.get_model_cost()
        assert isinstance(cost, ModelCost)

    def test_input_cost_is_zero(self) -> None:
        provider = CallableProvider(lambda p: "ok")
        cost = provider.get_model_cost()
        assert cost.input_cost_per_1k == 0.0

    def test_output_cost_is_zero(self) -> None:
        provider = CallableProvider(lambda p: "ok")
        cost = provider.get_model_cost()
        assert cost.output_cost_per_1k == 0.0

    def test_any_model_name_returns_zero(self) -> None:
        provider = CallableProvider(lambda p: "ok")
        for model_name in ("gpt-4o", "gemini-pro", "llama3.1", "custom-xyz"):
            cost = provider.get_model_cost(model_name)
            assert cost.input_cost_per_1k == 0.0
            assert cost.output_cost_per_1k == 0.0

    def test_no_model_arg_also_zero(self) -> None:
        provider = CallableProvider(lambda p: "ok")
        cost = provider.get_model_cost(None)
        assert cost.input_cost_per_1k == 0.0


# ---------------------------------------------------------------------------
# Class 11: provider_name and default_model properties
# ---------------------------------------------------------------------------


class TestProviderProperties:
    """provider_name and default_model return configured values."""

    def test_provider_name_default(self) -> None:
        provider = CallableProvider(lambda p: "ok")
        assert provider.provider_name == "callable"

    def test_default_model_default(self) -> None:
        provider = CallableProvider(lambda p: "ok")
        assert provider.default_model == "custom"

    def test_provider_name_custom(self) -> None:
        provider = CallableProvider(lambda p: "ok", name="my-provider")
        assert provider.provider_name == "my-provider"

    def test_default_model_custom(self) -> None:
        provider = CallableProvider(lambda p: "ok", model_name="llama3-local")
        assert provider.default_model == "llama3-local"

    def test_provider_name_is_str(self) -> None:
        provider = CallableProvider(lambda p: "ok")
        assert isinstance(provider.provider_name, str)

    def test_default_model_is_str(self) -> None:
        provider = CallableProvider(lambda p: "ok")
        assert isinstance(provider.default_model, str)


# ---------------------------------------------------------------------------
# Class 12: Signature detection edge cases
# ---------------------------------------------------------------------------


class TestSignatureDetection:
    """Constructor correctly detects callable signature variants."""

    def test_bare_list_param_not_treated_as_messages(self) -> None:
        """A bare list annotation (no subscript) does NOT set _accepts_messages.

        The source checks ``origin is list``, which requires a subscripted
        ``list[X]`` — an unsubscripted ``list`` has ``__origin__ == None``.
        """
        def fn(messages: list) -> str:
            return "ok"

        provider = CallableProvider(fn)
        assert provider._accepts_messages is False

    def test_unannotated_param_treated_as_string(self) -> None:
        """A parameter with no annotation is not detected as message-list."""
        def fn(prompt) -> str:
            return prompt

        provider = CallableProvider(fn)
        assert provider._accepts_messages is False

    def test_extra_positional_param_sets_accepts_kwargs(self) -> None:
        def fn(messages: list[Message], model: str = "default") -> str:
            return "ok"

        provider = CallableProvider(fn)
        assert provider._accepts_kwargs is True

    def test_no_params_does_not_crash(self) -> None:
        """Callables with zero parameters should construct without error."""
        def fn() -> str:
            return "no-param"

        # Should not raise during construction
        provider = CallableProvider(fn)
        assert provider is not None

    @pytest.mark.asyncio
    async def test_no_param_callable_raises_type_error(self) -> None:
        """A zero-parameter callable is not a supported signature.

        The provider falls to the string-prompt branch and calls ``fn(prompt)``,
        which raises ``TypeError`` because the function accepts zero arguments.
        This documents the current behaviour — callers must accept at least one arg.
        """
        def fn() -> str:
            return "zero-param result"

        provider = CallableProvider(fn)
        with pytest.raises(TypeError):
            await provider.complete([_user("hi")])

    def test_list_of_non_message_type_not_treated_as_messages(self) -> None:
        """list[str] should NOT trigger _accepts_messages."""
        def fn(items: list[str]) -> str:
            return "ok"

        provider = CallableProvider(fn)
        assert provider._accepts_messages is False


# ---------------------------------------------------------------------------
# Class 13: _messages_to_prompt helper (tested indirectly via complete)
# ---------------------------------------------------------------------------


class TestMessageFlattening:
    """The flattened prompt format is 'role: content' lines joined by newlines."""

    @pytest.mark.asyncio
    async def test_single_user_message_format(self) -> None:
        captured: list[str] = []

        def fn(prompt: str) -> str:
            captured.append(prompt)
            return "ok"

        provider = CallableProvider(fn)
        await provider.complete([_user("hi there")])
        assert captured[0] == "user: hi there"

    @pytest.mark.asyncio
    async def test_system_user_format(self) -> None:
        captured: list[str] = []

        def fn(prompt: str) -> str:
            captured.append(prompt)
            return "ok"

        provider = CallableProvider(fn)
        await provider.complete([_system("sys"), _user("usr")])
        lines = captured[0].splitlines()
        assert lines[0] == "system: sys"
        assert lines[1] == "user: usr"

    @pytest.mark.asyncio
    async def test_assistant_role_label(self) -> None:
        captured: list[str] = []

        def fn(prompt: str) -> str:
            captured.append(prompt)
            return "ok"

        provider = CallableProvider(fn)
        await provider.complete([_assistant("prev reply")])
        assert "assistant: prev reply" in captured[0]

    @pytest.mark.asyncio
    async def test_messages_joined_by_newlines(self) -> None:
        captured: list[str] = []

        def fn(prompt: str) -> str:
            captured.append(prompt)
            return "ok"

        provider = CallableProvider(fn)
        await provider.complete([_user("a"), _user("b"), _user("c")])
        parts = captured[0].split("\n")
        assert len(parts) == 3
