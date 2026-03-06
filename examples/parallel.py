"""Parallel workflow: Fan-out to multiple researchers, fan-in to synthesizer.

Three research agents work in parallel on different aspects of a topic.
A synthesizer agent then combines their findings.

Run:
    python examples/parallel.py
"""

import asyncio
from typing import Annotated, Any

from orchestra.core.graph import WorkflowGraph
from orchestra.core.state import WorkflowState, merge_dict, merge_list
from orchestra.core.types import END


class ParallelResearchState(WorkflowState):
    topic: str = ""
    findings: Annotated[dict[str, str], merge_dict] = {}
    summary: str = ""
    log: Annotated[list[str], merge_list] = []


async def dispatch(state: dict[str, Any]) -> dict[str, Any]:
    """Entry point — just passes state through."""
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


async def main() -> None:
    graph = WorkflowGraph(state_schema=ParallelResearchState)

    graph.add_node("dispatch", dispatch)
    graph.add_node("tech", research_technical)
    graph.add_node("market", research_market)
    graph.add_node("competitors", research_competitors)
    graph.add_node("synthesizer", synthesize)

    graph.set_entry_point("dispatch")
    graph.add_parallel("dispatch", ["tech", "market", "competitors"], join_node="synthesizer")
    graph.add_edge("synthesizer", END)

    compiled = graph.compile()
    result = await compiled.run({"topic": "AI Orchestration Frameworks"})

    print(f"Topic: {result['topic']}")
    print(f"Findings: {result['findings']}")
    print(f"Summary: {result['summary']}")
    print(f"Steps: {result['log']}")


if __name__ == "__main__":
    asyncio.run(main())
