"""Conditional workflow: Route based on content analysis.

A classifier analyzes input and routes to the appropriate
specialist agent (technical writer vs. creative writer).

Run:
    python examples/conditional.py
"""

import asyncio
from typing import Annotated, Any

from orchestra.core.graph import WorkflowGraph
from orchestra.core.state import WorkflowState, merge_list
from orchestra.core.types import END


class ContentState(WorkflowState):
    request: str = ""
    content_type: str = ""
    output: str = ""
    log: Annotated[list[str], merge_list] = []


async def classifier(state: dict[str, Any]) -> dict[str, Any]:
    """Classify the request type."""
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
    """Routing function for conditional edge."""
    return state["content_type"]


async def main() -> None:
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

    compiled = graph.compile()

    # Test with technical request
    result = await compiled.run({"request": "Write API documentation for user auth"})
    print(f"Request: {result['request']}")
    print(f"Type: {result['content_type']}")
    print(f"Output: {result['output']}")
    print(f"Steps: {result['log']}")
    print()

    # Test with creative request
    result = await compiled.run({"request": "Write a blog post about AI trends"})
    print(f"Request: {result['request']}")
    print(f"Type: {result['content_type']}")
    print(f"Output: {result['output']}")
    print(f"Steps: {result['log']}")


if __name__ == "__main__":
    asyncio.run(main())
