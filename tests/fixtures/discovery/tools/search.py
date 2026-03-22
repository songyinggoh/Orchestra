"""Fixture tool file: web search tool."""

from orchestra.tools.base import tool


@tool
async def web_search(query: str, max_results: int = 5) -> str:
    """Search the web for information about a topic."""
    return f"Results for: {query}"
