"""Live end-to-end tests against real LLM backends.

These tests prove the framework works with actual models — not mocks.
They are intentionally not run in CI (no API keys there).

Run locally:

    # Any available backend (auto-detected):
    pytest tests/live/ -m live -v

    # Specific backend:
    pytest tests/live/ -m live -k anthropic -v
    pytest tests/live/ -m live -k openai -v
    pytest tests/live/ -m live -k google -v
    pytest tests/live/ -m live -k ollama -v

    # One test class, any backend:
    pytest tests/live/test_live_providers.py::TestMultiAgentRouting -v

Prerequisites (at least one):
    export ANTHROPIC_API_KEY=sk-ant-...
    export OPENAI_API_KEY=sk-...
    export GOOGLE_API_KEY=AIza...
    ollama serve && ollama pull llama3.1
"""
from __future__ import annotations

from typing import Annotated, Any

import pytest

from orchestra.core.agent import BaseAgent
from orchestra.core.context import ExecutionContext
from orchestra.core.graph import WorkflowGraph
from orchestra.core.runner import run
from orchestra.core.state import WorkflowState, merge_dict, merge_list
from orchestra.core.types import END, LLMResponse, Message, MessageRole, StreamChunk
from orchestra.tools.base import tool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user(content: str) -> Message:
    return Message(role=MessageRole.USER, content=content)


# ---------------------------------------------------------------------------
# 1. Basic completion — provider returns non-empty text
# ---------------------------------------------------------------------------


@pytest.mark.live
class TestBasicCompletion:
    """Provider.complete() returns a real LLMResponse with non-empty content."""

    @pytest.mark.asyncio
    async def test_anthropic_complete(self, anthropic_provider):
        result = await anthropic_provider.complete([_user("Reply with only the word: HELLO")])
        assert isinstance(result, LLMResponse)
        assert result.content
        assert isinstance(result.content, str)
        assert len(result.content.strip()) > 0

    @pytest.mark.asyncio
    async def test_anthropic_response_contains_expected_word(self, anthropic_provider):
        result = await anthropic_provider.complete(
            [_user("Reply with exactly one word: PONG. Nothing else.")],
            temperature=0.0,
        )
        assert "pong" in result.content.lower()

    @pytest.mark.asyncio
    async def test_anthropic_usage_reported(self, anthropic_provider):
        result = await anthropic_provider.complete([_user("Say hi")])
        assert result.usage is not None
        assert result.usage.input_tokens > 0
        assert result.usage.output_tokens > 0
        assert result.usage.total_tokens == result.usage.input_tokens + result.usage.output_tokens

    @pytest.mark.asyncio
    async def test_openai_complete(self, openai_provider):
        result = await openai_provider.complete([_user("Reply with only the word: HELLO")])
        assert isinstance(result, LLMResponse)
        assert result.content
        assert len(result.content.strip()) > 0

    @pytest.mark.asyncio
    async def test_openai_response_contains_expected_word(self, openai_provider):
        result = await openai_provider.complete(
            [_user("Reply with exactly one word: PONG. Nothing else.")],
            temperature=0.0,
        )
        assert "pong" in result.content.lower()

    @pytest.mark.asyncio
    async def test_openai_usage_reported(self, openai_provider):
        result = await openai_provider.complete([_user("Say hi")])
        assert result.usage is not None
        assert result.usage.input_tokens > 0
        assert result.usage.output_tokens > 0

    @pytest.mark.asyncio
    async def test_google_complete(self, google_provider):
        result = await google_provider.complete([_user("Reply with only the word: HELLO")])
        assert isinstance(result, LLMResponse)
        assert result.content
        assert len(result.content.strip()) > 0

    @pytest.mark.asyncio
    async def test_google_response_contains_expected_word(self, google_provider):
        result = await google_provider.complete(
            [_user("Reply with exactly one word: PONG. Nothing else.")],
            temperature=0.0,
        )
        assert "pong" in result.content.lower()

    @pytest.mark.asyncio
    async def test_ollama_complete(self, ollama_provider, ollama_model):
        result = await ollama_provider.complete(
            [_user("Reply with only the word: HELLO")],
            model=ollama_model,
        )
        assert isinstance(result, LLMResponse)
        assert result.content
        assert len(result.content.strip()) > 0


# ---------------------------------------------------------------------------
# 2. Streaming — provider.stream() yields real StreamChunks
# ---------------------------------------------------------------------------


@pytest.mark.live
class TestStreaming:
    """provider.stream() yields multiple chunks and assembles into coherent text."""

    @pytest.mark.asyncio
    async def test_anthropic_stream_yields_chunks(self, anthropic_provider):
        chunks: list[StreamChunk] = []
        async for chunk in anthropic_provider.stream(
            [_user("Count from 1 to 5, one number per line.")]
        ):
            chunks.append(chunk)

        assert len(chunks) > 1
        full_text = "".join(c.content for c in chunks if c.content)
        assert len(full_text) > 0
        # Should contain at least some digits
        assert any(ch.isdigit() for ch in full_text)

    @pytest.mark.asyncio
    async def test_anthropic_stream_has_stop_chunk(self, anthropic_provider):
        chunks: list[StreamChunk] = []
        async for chunk in anthropic_provider.stream([_user("Say hi")]):
            chunks.append(chunk)

        finish_reasons = [c.finish_reason for c in chunks if c.finish_reason]
        assert len(finish_reasons) > 0
        assert finish_reasons[-1] == "stop"

    @pytest.mark.asyncio
    async def test_openai_stream_yields_chunks(self, openai_provider):
        chunks: list[StreamChunk] = []
        async for chunk in openai_provider.stream(
            [_user("Count from 1 to 5, one number per line.")]
        ):
            chunks.append(chunk)

        assert len(chunks) > 1
        full_text = "".join(c.content for c in chunks if c.content)
        assert len(full_text) > 0

    @pytest.mark.asyncio
    async def test_openai_stream_assembles_coherent_text(self, openai_provider):
        chunks: list[StreamChunk] = []
        async for chunk in openai_provider.stream(
            [_user("Reply with exactly one word: STREAMING")]
        ):
            chunks.append(chunk)

        full_text = "".join(c.content for c in chunks if c.content)
        assert "streaming" in full_text.lower()

    @pytest.mark.asyncio
    async def test_google_stream_yields_chunks(self, google_provider):
        chunks: list[StreamChunk] = []
        async for chunk in google_provider.stream(
            [_user("Count from 1 to 5, one number per line.")]
        ):
            chunks.append(chunk)

        full_text = "".join(c.content for c in chunks if c.content)
        assert len(full_text) > 0


# ---------------------------------------------------------------------------
# 3. Tool calling — the LLM actually invokes a @tool
# ---------------------------------------------------------------------------


@tool
async def add_numbers(a: int, b: int) -> str:
    """Add two integers and return their sum as a string."""
    return str(a + b)


@pytest.mark.live
class TestToolCalling:
    """The LLM calls a registered tool and the framework executes it."""

    async def _run_tool_agent(self, provider: Any, model: str) -> Any:
        agent = BaseAgent(
            name="calculator",
            model=model,
            system_prompt=(
                "You are a math assistant. When asked to add numbers, "
                "you MUST use the add_numbers tool. Do not compute in your head."
            ),
            tools=[add_numbers],
            temperature=0.0,
            max_iterations=3,
        )
        ctx = ExecutionContext(provider=provider)
        return await agent.run("What is 12 + 34?", ctx)

    @pytest.mark.asyncio
    async def test_anthropic_tool_called(self, anthropic_provider, anthropic_model):
        result = await self._run_tool_agent(anthropic_provider, anthropic_model)
        assert result.tool_calls_made, "Expected at least one tool call"
        tool_names = [tc.tool_call.name for tc in result.tool_calls_made]
        assert "add_numbers" in tool_names

    @pytest.mark.asyncio
    async def test_anthropic_tool_result_correct(self, anthropic_provider, anthropic_model):
        result = await self._run_tool_agent(anthropic_provider, anthropic_model)
        assert "46" in result.output

    @pytest.mark.asyncio
    async def test_openai_tool_called(self, openai_provider, openai_model):
        result = await self._run_tool_agent(openai_provider, openai_model)
        assert result.tool_calls_made, "Expected at least one tool call"
        tool_names = [tc.tool_call.name for tc in result.tool_calls_made]
        assert "add_numbers" in tool_names

    @pytest.mark.asyncio
    async def test_openai_tool_result_correct(self, openai_provider, openai_model):
        result = await self._run_tool_agent(openai_provider, openai_model)
        assert "46" in result.output

    @pytest.mark.asyncio
    async def test_google_tool_called(self, google_provider, google_model):
        result = await self._run_tool_agent(google_provider, google_model)
        assert result.tool_calls_made, "Expected at least one tool call"

    @pytest.mark.asyncio
    async def test_google_tool_result_correct(self, google_provider, google_model):
        result = await self._run_tool_agent(google_provider, google_model)
        assert "46" in result.output
    @pytest.mark.asyncio
    async def test_ollama_tool_called(self, ollama_provider, ollama_model):
        result = await self._run_tool_agent(ollama_provider, ollama_model)
        assert result.tool_calls_made, "Expected at least one tool call"
        tool_names = [tc.tool_call.name for tc in result.tool_calls_made]
        assert "add_numbers" in tool_names

    @pytest.mark.asyncio
    async def test_ollama_tool_result_correct(self, ollama_provider, ollama_model):
        result = await self._run_tool_agent(ollama_provider, ollama_model)
        assert "46" in result.output

    @pytest.mark.asyncio
    async def test_any_provider_tool_called(self, any_provider_and_model):
        provider, model = any_provider_and_model
        result = await self._run_tool_agent(provider, model)
        assert result.tool_calls_made, "Expected at least one tool call"
        tool_names = [tc.tool_call.name for tc in result.tool_calls_made]
        assert "add_numbers" in tool_names

    @pytest.mark.asyncio
    async def test_any_provider_tool_result_correct(self, any_provider_and_model):
        provider, model = any_provider_and_model
        result = await self._run_tool_agent(provider, model)
        assert "46" in result.output





# ---------------------------------------------------------------------------
# 3b. Multi-turn tool use — agent calls a tool then uses the result
# ---------------------------------------------------------------------------


@tool
async def lookup_capital(country: str) -> str:
    """Return the capital city of a country."""
    capitals = {
        "france": "Paris",
        "germany": "Berlin",
        "japan": "Tokyo",
        "brazil": "Brasilia",
        "australia": "Canberra",
    }
    return capitals.get(country.lower(), f"Unknown capital for {country}")


@pytest.mark.live
class TestMultiTurnToolUse:
    """Agent calls a tool, receives the result, then formulates a final answer.

    This exercises the full max_iterations loop: think → call tool → observe
    result → answer. A one-shot model that refuses to use tools would fail here.
    """

    async def _run_capital_agent(self, provider: Any, model: str) -> Any:
        agent = BaseAgent(
            name="geo_assistant",
            model=model,
            system_prompt=(
                "You are a geography assistant. When asked about a capital city, "
                "you MUST use the lookup_capital tool to find it. "
                "Do not rely on memory — always call the tool first."
            ),
            tools=[lookup_capital],
            temperature=0.0,
            max_iterations=5,
        )
        ctx = ExecutionContext(provider=provider)
        return await agent.run("What is the capital of France?", ctx)

    @pytest.mark.asyncio
    async def test_anthropic_tool_called_in_loop(self, anthropic_provider, anthropic_model):
        result = await self._run_capital_agent(anthropic_provider, anthropic_model)
        assert result.tool_calls_made, "Agent should have called lookup_capital"
        assert "Paris" in result.output

    @pytest.mark.asyncio
    async def test_openai_tool_called_in_loop(self, openai_provider, openai_model):
        result = await self._run_capital_agent(openai_provider, openai_model)
        assert result.tool_calls_made
        assert "Paris" in result.output

    @pytest.mark.asyncio
    async def test_ollama_tool_called_in_loop(self, ollama_provider, ollama_model):
        result = await self._run_capital_agent(ollama_provider, ollama_model)
        assert result.tool_calls_made, "Agent should have called lookup_capital"
        assert "Paris" in result.output

    @pytest.mark.asyncio
    async def test_any_provider_tool_called_in_loop(self, any_provider_and_model):
        provider, model = any_provider_and_model
        result = await self._run_capital_agent(provider, model)
        assert result.tool_calls_made, "Agent should have called lookup_capital"
        assert "Paris" in result.output

    @pytest.mark.asyncio
    async def test_any_provider_sequential_tool_calls(self, any_provider_and_model):
        """Agent calls a tool twice in sequence to answer a compound question."""
        provider, model = any_provider_and_model
        agent = BaseAgent(
            name="multi_lookup",
            model=model,
            system_prompt=(
                "You are a geography assistant. For every country mentioned, "
                "call lookup_capital once per country. Always use the tool."
            ),
            tools=[lookup_capital],
            temperature=0.0,
            max_iterations=8,
        )
        ctx = ExecutionContext(provider=provider)
        result = await agent.run(
            "What are the capitals of France and Japan?", ctx
        )
        assert result.tool_calls_made, "Expected tool calls"
        assert "Paris" in result.output
        assert "Tokyo" in result.output

# ---------------------------------------------------------------------------
# 4. BaseAgent.run() — single agent returns coherent AgentResult
# ---------------------------------------------------------------------------


@pytest.mark.live
class TestBaseAgent:
    """BaseAgent.run() against a real provider returns structured AgentResult."""

    @pytest.mark.asyncio
    async def test_anthropic_agent_output_non_empty(self, anthropic_provider, anthropic_model):
        agent = BaseAgent(
            name="qa",
            model=anthropic_model,
            system_prompt="Answer questions briefly.",
            max_iterations=1,
        )
        ctx = ExecutionContext(provider=anthropic_provider)
        result = await agent.run("What color is the sky?", ctx)
        assert result.output
        assert len(result.output.strip()) > 0

    @pytest.mark.asyncio
    async def test_anthropic_agent_name_matches(self, anthropic_provider, anthropic_model):
        agent = BaseAgent(name="my_agent", model=anthropic_model)
        ctx = ExecutionContext(provider=anthropic_provider)
        result = await agent.run("Hi", ctx)
        assert result.agent_name == "my_agent"

    @pytest.mark.asyncio
    async def test_openai_agent_output_non_empty(self, openai_provider, openai_model):
        agent = BaseAgent(
            name="qa",
            model=openai_model,
            system_prompt="Answer questions briefly.",
            max_iterations=1,
        )
        ctx = ExecutionContext(provider=openai_provider)
        result = await agent.run("What color is the sky?", ctx)
        assert result.output
        assert len(result.output.strip()) > 0

    @pytest.mark.asyncio
    async def test_any_provider_agent_answers_factual_question(self, any_provider_and_model):
        provider, model = any_provider_and_model
        agent = BaseAgent(
            name="factual",
            model=model,
            system_prompt="Answer with a single word only.",
            temperature=0.0,
            max_iterations=1,
        )
        ctx = ExecutionContext(provider=provider)
        result = await agent.run(
            "What is the chemical symbol for water? Reply with only the symbol.", ctx
        )
        # Accept ASCII H2O and Unicode subscript H₂O (both are correct)
        normalised = result.output.lower().replace("₂", "2")
        assert "h2o" in normalised


# ---------------------------------------------------------------------------
# 5. Multi-agent routing — classifier routes to correct specialist
# ---------------------------------------------------------------------------


class RoutingState(WorkflowState):
    question: str = ""
    category: str = ""
    answer: str = ""


@pytest.mark.live
class TestMultiAgentRouting:
    """A classifier agent routes to a technical or creative specialist."""

    async def _run_routing(self, provider: Any, model: str, question: str) -> dict[str, Any]:
        classifier = BaseAgent(
            name="classifier",
            model=model,
            system_prompt=(
                "You are a classifier. Read the question and respond with EXACTLY "
                "one word: either 'technical' or 'creative'. Nothing else."
            ),
            temperature=0.0,
            max_iterations=1,
        )
        technical = BaseAgent(
            name="technical_expert",
            model=model,
            system_prompt="You are a software engineer. Answer technical questions concisely.",
            max_iterations=1,
        )
        creative = BaseAgent(
            name="creative_expert",
            model=model,
            system_prompt="You are a creative writing coach. Answer creative questions briefly.",
            max_iterations=1,
        )

        def route(state: dict[str, Any]) -> str:
            return "technical" if "technical" in state.get("category", "").lower() else "creative"

        graph = WorkflowGraph(state_schema=RoutingState)
        graph.add_node("classifier", classifier, output_key="category")
        graph.add_node("technical", technical, output_key="answer")
        graph.add_node("creative", creative, output_key="answer")
        graph.set_entry_point("classifier")
        graph.add_conditional_edge(
            "classifier",
            route,
            path_map={"technical": "technical", "creative": "creative"},
        )
        graph.add_edge("technical", END)
        graph.add_edge("creative", END)

        result = await run(graph, input={"question": question}, provider=provider, persist=False)
        return result.state

    @pytest.mark.asyncio
    async def test_anthropic_technical_question_routed(self, anthropic_provider, anthropic_model):
        state = await self._run_routing(
            anthropic_provider,
            anthropic_model,
            "How do I reverse a linked list in Python?",
        )
        assert "technical" in state["category"].lower()
        assert state["answer"]

    @pytest.mark.asyncio
    async def test_anthropic_answer_non_empty_after_routing(
        self, anthropic_provider, anthropic_model
    ):
        state = await self._run_routing(
            anthropic_provider,
            anthropic_model,
            "Write me a one-sentence poem about autumn.",
        )
        assert state["answer"]
        assert len(state["answer"].strip()) > 0

    @pytest.mark.asyncio
    async def test_openai_routing_produces_answer(self, openai_provider, openai_model):
        state = await self._run_routing(
            openai_provider,
            openai_model,
            "How do Python generators work?",
        )
        assert state["category"]
        assert state["answer"]

    @pytest.mark.asyncio
    async def test_any_provider_routing_executes_two_nodes(self, any_provider_and_model):
        provider, model = any_provider_and_model
        classifier = BaseAgent(
            name="classifier",
            model=model,
            system_prompt="Reply with exactly one word: 'technical' or 'creative'.",
            temperature=0.0,
            max_iterations=1,
        )
        specialist = BaseAgent(
            name="specialist",
            model=model,
            system_prompt="Answer the question in one sentence.",
            max_iterations=1,
        )

        class S(WorkflowState):
            question: str = ""
            category: str = ""
            answer: str = ""

        graph = WorkflowGraph(state_schema=S)
        graph.add_node("classifier", classifier, output_key="category")
        graph.add_node("specialist", specialist, output_key="answer")
        graph.set_entry_point("classifier")
        graph.add_edge("classifier", "specialist")
        graph.add_edge("specialist", END)

        result = await run(
            graph,
            input={"question": "What is async/await in Python?"},
            provider=provider,
            persist=False,
        )
        assert result.state["category"]
        assert result.state["answer"]
        assert result.node_execution_order == ["classifier", "specialist"]


# ---------------------------------------------------------------------------
# 6. Parallel fan-out — three agents run concurrently, synthesizer combines
# ---------------------------------------------------------------------------


class ResearchState(WorkflowState):
    topic: str = ""
    findings: Annotated[dict[str, str], merge_dict] = {}
    synthesis: str = ""
    log: Annotated[list[str], merge_list] = []


@pytest.mark.live
class TestParallelFanOut:
    """Three researcher agents run in parallel; a synthesizer merges their output."""

    async def _run_parallel(self, provider: Any, model: str) -> Any:
        def make_researcher(role: str, focus: str) -> BaseAgent:
            return BaseAgent(
                name=f"{role}_researcher",
                model=model,
                system_prompt=(
                    f"You are a {focus} analyst. Given a topic, write 1-2 sentences "
                    f"on the {focus} perspective. Be specific and concise."
                ),
                max_iterations=1,
            )

        tech = make_researcher("tech", "technical")
        market = make_researcher("market", "market")
        risk = make_researcher("risk", "risk")
        synthesizer = BaseAgent(
            name="synthesizer",
            model=model,
            system_prompt=(
                "You receive research findings from multiple analysts. "
                "Write a 2-sentence executive summary combining all perspectives."
            ),
            max_iterations=1,
        )

        async def run_tech(state: dict[str, Any]) -> dict[str, Any]:
            ctx = ExecutionContext(provider=provider)
            r = await tech.run(state["topic"], ctx)
            return {"findings": {"technical": r.output}, "log": ["tech done"]}

        async def run_market(state: dict[str, Any]) -> dict[str, Any]:
            ctx = ExecutionContext(provider=provider)
            r = await market.run(state["topic"], ctx)
            return {"findings": {"market": r.output}, "log": ["market done"]}

        async def run_risk(state: dict[str, Any]) -> dict[str, Any]:
            ctx = ExecutionContext(provider=provider)
            r = await risk.run(state["topic"], ctx)
            return {"findings": {"risk": r.output}, "log": ["risk done"]}

        async def run_synthesizer(state: dict[str, Any]) -> dict[str, Any]:
            ctx = ExecutionContext(provider=provider)
            combined = "\n".join(
                f"[{k}] {v}" for k, v in state["findings"].items()
            )
            r = await synthesizer.run(
                f"Topic: {state['topic']}\n\nFindings:\n{combined}", ctx
            )
            return {"synthesis": r.output, "log": ["synthesizer done"]}

        graph = WorkflowGraph(state_schema=ResearchState)
        graph.add_node("dispatch", lambda s: {})
        graph.add_node("tech", run_tech)
        graph.add_node("market", run_market)
        graph.add_node("risk", run_risk)
        graph.add_node("synthesizer", run_synthesizer)
        graph.set_entry_point("dispatch")
        graph.add_parallel("dispatch", ["tech", "market", "risk"], join_node="synthesizer")
        graph.add_edge("synthesizer", END)

        return await run(
            graph,
            input={"topic": "AI agents in production"},
            provider=provider,
            persist=False,
        )

    @pytest.mark.asyncio
    async def test_anthropic_all_three_findings_populated(
        self, anthropic_provider, anthropic_model
    ):
        result = await self._run_parallel(anthropic_provider, anthropic_model)
        findings = result.state["findings"]
        assert "technical" in findings
        assert "market" in findings
        assert "risk" in findings
        for text in findings.values():
            assert text and len(text.strip()) > 0

    @pytest.mark.asyncio
    async def test_anthropic_synthesis_non_empty(self, anthropic_provider, anthropic_model):
        result = await self._run_parallel(anthropic_provider, anthropic_model)
        assert result.state["synthesis"]
        assert len(result.state["synthesis"].strip()) > 10

    @pytest.mark.asyncio
    async def test_anthropic_parallel_nodes_all_ran(self, anthropic_provider, anthropic_model):
        result = await self._run_parallel(anthropic_provider, anthropic_model)
        log = result.state["log"]
        assert "tech done" in log
        assert "market done" in log
        assert "risk done" in log
        assert "synthesizer done" in log

    @pytest.mark.asyncio
    async def test_openai_parallel_fan_out(self, openai_provider, openai_model):
        result = await self._run_parallel(openai_provider, openai_model)
        findings = result.state["findings"]
        assert len(findings) == 3
        assert result.state["synthesis"]

    @pytest.mark.asyncio
    async def test_any_provider_parallel_fan_out(self, any_provider_and_model):
        provider, model = any_provider_and_model
        result = await self._run_parallel(provider, model)
        assert len(result.state["findings"]) == 3
        assert result.state["synthesis"]
