"""Unit tests for rag_tool() factory."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from orchestra.memory.tools import rag_tool
from orchestra.tools.base import ToolWrapper


@pytest.fixture
def mock_memory():
    """TieredMemoryManager mock with search_memories and retrieve."""
    m = MagicMock()
    m.search_memories = AsyncMock(return_value=[])
    m.retrieve = AsyncMock(return_value=None)
    return m


# ---------------------------------------------------------------------------
# Factory behaviour
# ---------------------------------------------------------------------------


def test_rag_tool_returns_tool_wrapper(mock_memory):
    t = rag_tool(mock_memory)
    assert isinstance(t, ToolWrapper)


def test_rag_tool_default_name(mock_memory):
    t = rag_tool(mock_memory)
    assert t.name == "search_memory"


def test_rag_tool_custom_name(mock_memory):
    t = rag_tool(mock_memory, name="my_rag")
    assert t.name == "my_rag"


def test_rag_tool_custom_description(mock_memory):
    t = rag_tool(mock_memory, description="custom desc")
    assert t.description == "custom desc"


def test_rag_tool_default_description_mentions_limit(mock_memory):
    t = rag_tool(mock_memory)
    assert "limit" in t.description.lower() or "token" in t.description.lower()


def test_rag_tool_has_query_parameter(mock_memory):
    t = rag_tool(mock_memory)
    assert "query" in t.parameters_schema["properties"]
    assert t.parameters_schema["required"] == ["query"]


def test_rag_tool_limit_has_default_not_required(mock_memory):
    t = rag_tool(mock_memory)
    assert "limit" in t.parameters_schema["properties"]
    assert "limit" not in t.parameters_schema.get("required", [])


# ---------------------------------------------------------------------------
# Execution behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rag_tool_no_results(mock_memory):
    mock_memory.search_memories = AsyncMock(return_value=[])
    t = rag_tool(mock_memory)
    result = await t.execute({"query": "anything"})
    assert result.error is None
    assert "No relevant memories found" in result.content


@pytest.mark.asyncio
async def test_rag_tool_returns_ranked_results(mock_memory):
    mock_memory.search_memories = AsyncMock(return_value=[("key-a", 0.95), ("key-b", 0.80)])
    mock_memory.retrieve = AsyncMock(side_effect=["value A", "value B"])

    t = rag_tool(mock_memory)
    result = await t.execute({"query": "test query"})

    assert result.error is None
    assert "value A" in result.content
    assert "value B" in result.content
    assert "0.950" in result.content
    assert "0.800" in result.content


@pytest.mark.asyncio
async def test_rag_tool_falls_back_to_key_when_retrieve_returns_none(mock_memory):
    mock_memory.search_memories = AsyncMock(return_value=[("key-x", 0.7)])
    mock_memory.retrieve = AsyncMock(return_value=None)

    t = rag_tool(mock_memory)
    result = await t.execute({"query": "q"})

    assert "key-x" in result.content


@pytest.mark.asyncio
async def test_rag_tool_passes_limit_to_search(mock_memory):
    mock_memory.search_memories = AsyncMock(return_value=[])
    t = rag_tool(mock_memory)
    await t.execute({"query": "q", "limit": 3})
    mock_memory.search_memories.assert_called_once_with("q", limit=3)


@pytest.mark.asyncio
async def test_rag_tool_uses_default_limit(mock_memory):
    mock_memory.search_memories = AsyncMock(return_value=[])
    t = rag_tool(mock_memory, default_limit=7)
    await t.execute({"query": "q"})
    mock_memory.search_memories.assert_called_once_with("q", limit=7)


@pytest.mark.asyncio
async def test_rag_tool_retrieve_called_with_promote_false(mock_memory):
    mock_memory.search_memories = AsyncMock(return_value=[("k", 0.9)])
    mock_memory.retrieve = AsyncMock(return_value="val")

    t = rag_tool(mock_memory)
    await t.execute({"query": "q"})

    mock_memory.retrieve.assert_called_once_with("k", promote=False)
