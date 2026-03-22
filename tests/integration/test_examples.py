"""Integration tests for example workflows (sequential, parallel, conditional).

Each test class recreates the workflow pattern from the corresponding example
and verifies correct execution using the graph engine directly.
"""

from __future__ import annotations

from typing import Annotated, Any

import pytest

from orchestra.core.graph import WorkflowGraph
from orchestra.core.runner import RunResult, run
from orchestra.core.state import WorkflowState, merge_dict, merge_list
from orchestra.core.types import END

# ===== Sequential Example =====


class TestSequentialExample:
    """Tests for the sequential pipeline: researcher -> writer -> editor."""

    @staticmethod
    def _build_state_and_graph() -> tuple[type[WorkflowState], WorkflowGraph]:
        class ArticleState(WorkflowState):
            topic: str = ""
            research: str = ""
            draft: str = ""
            final: str = ""
            log: Annotated[list[str], merge_list] = []

        async def research_node(state: dict[str, Any]) -> dict[str, Any]:
            topic = state["topic"]
            return {
                "research": f"Key findings about {topic}: [simulated research data]",
                "log": [f"Researched: {topic}"],
            }

        async def writer_node(state: dict[str, Any]) -> dict[str, Any]:
            research = state["research"]
            return {
                "draft": f"Article draft based on: {research[:50]}...",
                "log": ["Wrote draft"],
            }

        async def editor_node(state: dict[str, Any]) -> dict[str, Any]:
            draft = state["draft"]
            return {
                "final": f"[Edited] {draft}",
                "log": ["Edited and polished"],
            }

        graph = WorkflowGraph(state_schema=ArticleState)
        graph.add_node("researcher", research_node)
        graph.add_node("writer", writer_node)
        graph.add_node("editor", editor_node)
        graph.set_entry_point("researcher")
        graph.add_edge("researcher", "writer")
        graph.add_edge("writer", "editor")
        graph.add_edge("editor", END)

        return ArticleState, graph

    @pytest.mark.asyncio
    async def test_sequential_completes_successfully(self):
        _, graph = self._build_state_and_graph()
        result = await graph.compile().run({"topic": "Multi-Agent AI Systems"})

        assert result["topic"] == "Multi-Agent AI Systems"
        assert result["final"].startswith("[Edited]")
        assert "research" in result["final"].lower() or "draft" in result["final"].lower()

    @pytest.mark.asyncio
    async def test_sequential_state_has_all_intermediate_outputs(self):
        _, graph = self._build_state_and_graph()
        result = await graph.compile().run({"topic": "Testing"})

        assert result["research"] != ""
        assert result["draft"] != ""
        assert result["final"] != ""

    @pytest.mark.asyncio
    async def test_sequential_log_records_all_steps(self):
        _, graph = self._build_state_and_graph()
        result = await graph.compile().run({"topic": "AI"})

        assert len(result["log"]) == 3
        assert "Researched: AI" in result["log"][0]
        assert "Wrote draft" in result["log"][1]
        assert "Edited and polished" in result["log"][2]

    @pytest.mark.asyncio
    async def test_sequential_via_run_function(self):
        _, graph = self._build_state_and_graph()
        result = await run(graph, input={"topic": "Orchestration"})

        assert isinstance(result, RunResult)
        assert result.duration_ms > 0
        assert "researcher" in result.node_execution_order
        assert "writer" in result.node_execution_order
        assert "editor" in result.node_execution_order


# ===== Parallel Example =====


class TestParallelExample:
    """Tests for the parallel fan-out: 3 researchers -> synthesizer."""

    @staticmethod
    def _build_state_and_graph() -> tuple[type[WorkflowState], WorkflowGraph]:
        class ParallelResearchState(WorkflowState):
            topic: str = ""
            findings: Annotated[dict[str, str], merge_dict] = {}
            summary: str = ""
            log: Annotated[list[str], merge_list] = []

        async def dispatch(state: dict[str, Any]) -> dict[str, Any]:
            return {}

        async def research_technical(state: dict[str, Any]) -> dict[str, Any]:
            topic = state["topic"]
            return {
                "findings": {"technical": f"Technical analysis of {topic}"},
                "log": ["Completed technical research"],
            }

        async def research_market(state: dict[str, Any]) -> dict[str, Any]:
            topic = state["topic"]
            return {
                "findings": {"market": f"Market analysis of {topic}"},
                "log": ["Completed market research"],
            }

        async def research_competitors(state: dict[str, Any]) -> dict[str, Any]:
            topic = state["topic"]
            return {
                "findings": {"competitors": f"Competitor analysis of {topic}"},
                "log": ["Completed competitor research"],
            }

        async def synthesize(state: dict[str, Any]) -> dict[str, Any]:
            findings = state["findings"]
            combined = " | ".join(f"{k}: {v}" for k, v in findings.items())
            return {
                "summary": f"Synthesis: {combined}",
                "log": ["Synthesized all findings"],
            }

        graph = WorkflowGraph(state_schema=ParallelResearchState)
        graph.add_node("dispatch", dispatch)
        graph.add_node("tech", research_technical)
        graph.add_node("market", research_market)
        graph.add_node("competitors", research_competitors)
        graph.add_node("synthesizer", synthesize)
        graph.set_entry_point("dispatch")
        graph.add_parallel("dispatch", ["tech", "market", "competitors"], join_node="synthesizer")
        graph.add_edge("synthesizer", END)

        return ParallelResearchState, graph

    @pytest.mark.asyncio
    async def test_parallel_completes_successfully(self):
        _, graph = self._build_state_and_graph()
        result = await graph.compile().run({"topic": "AI Orchestration"})

        assert result["summary"].startswith("Synthesis:")
        assert result["topic"] == "AI Orchestration"

    @pytest.mark.asyncio
    async def test_parallel_merges_all_findings(self):
        _, graph = self._build_state_and_graph()
        result = await graph.compile().run({"topic": "AI"})

        assert "technical" in result["findings"]
        assert "market" in result["findings"]
        assert "competitors" in result["findings"]
        assert len(result["findings"]) == 3

    @pytest.mark.asyncio
    async def test_parallel_log_includes_all_researchers(self):
        _, graph = self._build_state_and_graph()
        result = await graph.compile().run({"topic": "AI"})

        log_text = " ".join(result["log"])
        assert "technical" in log_text
        assert "market" in log_text
        assert "competitor" in log_text
        assert "Synthesized" in log_text

    @pytest.mark.asyncio
    async def test_parallel_via_run_function(self):
        _, graph = self._build_state_and_graph()
        result = await run(graph, input={"topic": "Frameworks"})

        assert isinstance(result, RunResult)
        assert result.duration_ms > 0
        assert "dispatch" in result.node_execution_order
        assert "synthesizer" in result.node_execution_order


# ===== Conditional Example =====


class TestConditionalExample:
    """Tests for the conditional routing: classifier -> specialist."""

    @staticmethod
    def _build_state_and_graph() -> tuple[type[WorkflowState], WorkflowGraph]:
        class ContentState(WorkflowState):
            request: str = ""
            content_type: str = ""
            output: str = ""
            log: Annotated[list[str], merge_list] = []

        async def classifier(state: dict[str, Any]) -> dict[str, Any]:
            request = state["request"].lower()
            if any(word in request for word in ["api", "code", "technical", "docs"]):
                content_type = "technical"
            else:
                content_type = "creative"
            return {
                "content_type": content_type,
                "log": [f"Classified as: {content_type}"],
            }

        async def technical_writer(state: dict[str, Any]) -> dict[str, Any]:
            return {
                "output": f"[Technical Doc] {state['request']}",
                "log": ["Technical writer produced output"],
            }

        async def creative_writer(state: dict[str, Any]) -> dict[str, Any]:
            return {
                "output": f"[Creative Content] {state['request']}",
                "log": ["Creative writer produced output"],
            }

        def route_by_type(state: dict[str, Any]) -> str:
            return state["content_type"]

        graph = WorkflowGraph(state_schema=ContentState)
        graph.add_node("classifier", classifier)
        graph.add_node("technical", technical_writer)
        graph.add_node("creative", creative_writer)
        graph.set_entry_point("classifier")
        graph.add_conditional_edge(
            "classifier",
            route_by_type,
            path_map={"technical": "technical", "creative": "creative"},
        )
        graph.add_edge("technical", END)
        graph.add_edge("creative", END)

        return ContentState, graph

    @pytest.mark.asyncio
    async def test_routes_to_technical_writer(self):
        _, graph = self._build_state_and_graph()
        result = await graph.compile().run({"request": "Write API documentation for user auth"})

        assert result["content_type"] == "technical"
        assert result["output"].startswith("[Technical Doc]")

    @pytest.mark.asyncio
    async def test_routes_to_creative_writer(self):
        _, graph = self._build_state_and_graph()
        result = await graph.compile().run({"request": "Write a blog post about AI trends"})

        assert result["content_type"] == "creative"
        assert result["output"].startswith("[Creative Content]")

    @pytest.mark.asyncio
    async def test_conditional_log_records_classification(self):
        _, graph = self._build_state_and_graph()
        result = await graph.compile().run({"request": "Write code examples"})

        assert len(result["log"]) == 2
        assert "Classified as: technical" in result["log"][0]
        assert "Technical writer" in result["log"][1]

    @pytest.mark.asyncio
    async def test_conditional_via_run_function(self):
        _, graph = self._build_state_and_graph()
        result = await run(graph, input={"request": "Write a poem about nature"})

        assert isinstance(result, RunResult)
        assert result.state["content_type"] == "creative"
        assert result.state["output"].startswith("[Creative Content]")
        assert result.duration_ms > 0

    @pytest.mark.asyncio
    async def test_multiple_technical_keywords_route_correctly(self):
        _, graph = self._build_state_and_graph()
        compiled = graph.compile()

        for keyword in ["api", "code", "technical", "docs"]:
            result = await compiled.run({"request": f"Write about {keyword}"})
            assert result["content_type"] == "technical", (
                f"Expected 'technical' for keyword '{keyword}', got '{result['content_type']}'"
            )
