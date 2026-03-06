"""Sequential workflow: Researcher -> Writer -> Editor.

This example shows the simplest orchestration pattern:
three agents running in sequence, each passing output to the next.

Run:
    python examples/sequential.py
"""

import asyncio
from typing import Annotated, Any

from orchestra.core.graph import WorkflowGraph
from orchestra.core.state import WorkflowState, merge_list
from orchestra.core.types import END


class ArticleState(WorkflowState):
    topic: str = ""
    research: str = ""
    draft: str = ""
    final: str = ""
    log: Annotated[list[str], merge_list] = []


async def research_node(state: dict[str, Any]) -> dict[str, Any]:
    """Simulate research agent."""
    topic = state["topic"]
    return {
        "research": f"Key findings about {topic}: [simulated research data]",
        "log": [f"Researched: {topic}"],
    }


async def writer_node(state: dict[str, Any]) -> dict[str, Any]:
    """Simulate writer agent."""
    research = state["research"]
    return {
        "draft": f"Article draft based on: {research[:50]}...",
        "log": ["Wrote draft"],
    }


async def editor_node(state: dict[str, Any]) -> dict[str, Any]:
    """Simulate editor agent."""
    draft = state["draft"]
    return {
        "final": f"[Edited] {draft}",
        "log": ["Edited and polished"],
    }


async def main() -> None:
    # Build graph using the explicit API
    graph = WorkflowGraph(state_schema=ArticleState)
    graph.add_node("researcher", research_node)
    graph.add_node("writer", writer_node)
    graph.add_node("editor", editor_node)

    graph.set_entry_point("researcher")
    graph.add_edge("researcher", "writer")
    graph.add_edge("writer", "editor")
    graph.add_edge("editor", END)

    compiled = graph.compile()

    # Run
    result = await compiled.run({"topic": "Multi-Agent AI Systems"})

    print(f"Topic: {result['topic']}")
    print(f"Final: {result['final']}")
    print(f"Steps: {result['log']}")


if __name__ == "__main__":
    asyncio.run(main())
