"""RAG tool factory — wraps TieredMemoryManager.search_memories() as an agent tool."""

from __future__ import annotations

from typing import TYPE_CHECKING

from orchestra.tools.base import ToolWrapper

if TYPE_CHECKING:
    from orchestra.memory.tiers import TieredMemoryManager


def rag_tool(
    memory_manager: "TieredMemoryManager",
    *,
    name: str = "search_memory",
    description: str | None = None,
    default_limit: int = 5,
) -> ToolWrapper:
    """Create a RAG tool that performs semantic search over agent memory.

    The returned :class:`~orchestra.tools.base.ToolWrapper` can be passed
    directly to :class:`~orchestra.core.agent.BaseAgent` via its ``tools``
    argument.  It depends only on
    :meth:`~orchestra.memory.tiers.TieredMemoryManager.search_memories` and
    :meth:`~orchestra.memory.tiers.TieredMemoryManager.retrieve`, so it works
    with any ``TieredMemoryManager`` regardless of which cold-tier backend is
    configured.

    Example::

        from orchestra.memory import TieredMemoryManager, create_tiered_memory
        from orchestra.memory.tools import rag_tool
        from orchestra.core.agent import BaseAgent

        memory = create_tiered_memory(pg_pool=pool)
        agent = BaseAgent(
            name="researcher",
            tools=[rag_tool(memory)],
        )

    Args:
        memory_manager: The tiered memory instance to search.
        name: Tool name exposed to the LLM (default ``"search_memory"``).
        description: Override the tool description shown to the LLM.  Defaults
            to a description that includes a token-budget warning.
        default_limit: Default number of results when the agent does not supply
            one.  Keep this low (≤5) — each result consumes prompt tokens.

    Returns:
        A :class:`~orchestra.tools.base.ToolWrapper` ready for agent use.
    """
    _description = description or (
        "Search agent memory for stored context relevant to a query. "
        "Returns the most semantically similar memories as ranked text. "
        f"The 'limit' parameter controls how many results are returned "
        f"(default {default_limit}); each result consumes prompt tokens, "
        "so increase it only when your prompt has sufficient budget."
    )

    async def search_memory(query: str, limit: int = default_limit) -> str:
        """Search memory for relevant context.

        Args:
            query: Natural language search query.
            limit: Maximum number of results to return. Each result consumes
                prompt tokens — keep this at 5 or below unless your prompt
                template explicitly accounts for the extra content.

        Returns:
            Numbered list of matching memory contents ranked by similarity,
            or a message indicating no results were found.
        """
        results = await memory_manager.search_memories(query, limit=limit)

        if not results:
            return "No relevant memories found."

        lines = [f"Memory search results for: {query!r}"]
        for i, (key, score) in enumerate(results, 1):
            value = await memory_manager.retrieve(key, promote=False)
            content = str(value) if value is not None else key
            lines.append(f"{i}. [score={score:.3f}] {content}")

        return "\n".join(lines)

    return ToolWrapper(search_memory, name=name, description=_description)
