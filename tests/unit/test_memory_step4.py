"""Tests for Step 4: multi-tenant agent_id scoping and hybrid search."""

import numpy as np
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# #3 — search_memories() agent_id override
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_cold():
    m = AsyncMock()
    m.search = AsyncMock(return_value=[])
    return m


@pytest.fixture
def mock_dedup():
    d = AsyncMock()
    d.embed = AsyncMock(return_value=np.array([[0.1] * 256]))
    return d


@pytest.mark.asyncio
async def test_search_memories_passes_agent_id_to_cold(mock_cold, mock_dedup):
    from orchestra.memory.tiers import TieredMemoryManager
    mgr = TieredMemoryManager(cold_backend=mock_cold, deduplicator=mock_dedup)
    await mgr.search_memories("query", agent_id="other-agent")
    mock_cold.search.assert_called_once()
    _, kwargs = mock_cold.search.call_args
    assert kwargs["agent_id"] == "other-agent"


@pytest.mark.asyncio
async def test_search_memories_passes_none_agent_id_by_default(mock_cold, mock_dedup):
    from orchestra.memory.tiers import TieredMemoryManager
    mgr = TieredMemoryManager(cold_backend=mock_cold, deduplicator=mock_dedup)
    await mgr.search_memories("query")
    _, kwargs = mock_cold.search.call_args
    assert kwargs.get("agent_id") is None


@pytest.mark.asyncio
async def test_search_memories_passes_filter_metadata_and_agent_id(mock_cold, mock_dedup):
    from orchestra.memory.tiers import TieredMemoryManager
    mgr = TieredMemoryManager(cold_backend=mock_cold, deduplicator=mock_dedup)
    await mgr.search_memories("q", filter_metadata={"tag": "x"}, agent_id="a2")
    _, kwargs = mock_cold.search.call_args
    assert kwargs["filter_metadata"] == {"tag": "x"}
    assert kwargs["agent_id"] == "a2"


# ---------------------------------------------------------------------------
# VectorStore.search() agent_id override
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_pool():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool = AsyncMock()
    pool.acquire = AsyncMock(return_value=cm)
    return pool, conn


@pytest.mark.asyncio
async def test_vector_store_search_uses_override_agent_id(mock_pool):
    from orchestra.memory.vector_store import VectorStore
    pool, conn = mock_pool
    vs = VectorStore(pool=pool, agent_id="agent-default")
    await vs.search([0.0] * 4, agent_id="agent-other")
    sql, *params = conn.fetch.call_args.args
    assert "agent-other" in params
    assert "agent-default" not in params


@pytest.mark.asyncio
async def test_vector_store_search_falls_back_to_instance_agent_id(mock_pool):
    from orchestra.memory.vector_store import VectorStore
    pool, conn = mock_pool
    vs = VectorStore(pool=pool, agent_id="agent-default")
    await vs.search([0.0] * 4)
    sql, *params = conn.fetch.call_args.args
    assert "agent-default" in params


# ---------------------------------------------------------------------------
# #2 — VectorStore.hybrid_search()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hybrid_search_returns_key_score_tuples(mock_pool):
    from orchestra.memory.vector_store import VectorStore
    pool, conn = mock_pool
    row1 = MagicMock()
    row1.__getitem__ = lambda self, k: "k1" if k == "key" else 0.85
    row2 = MagicMock()
    row2.__getitem__ = lambda self, k: "k2" if k == "key" else 0.60
    conn.fetch = AsyncMock(return_value=[row1, row2])

    vs = VectorStore(pool=pool, agent_id="a1")
    results = await vs.hybrid_search("test query", [0.1] * 4, limit=2)
    assert len(results) == 2
    assert results[0][0] == "k1"
    assert results[1][0] == "k2"


@pytest.mark.asyncio
async def test_hybrid_search_passes_bm25_weight(mock_pool):
    from orchestra.memory.vector_store import VectorStore
    pool, conn = mock_pool
    conn.fetch = AsyncMock(return_value=[])

    vs = VectorStore(pool=pool, agent_id="a1")
    await vs.hybrid_search("q", [0.0] * 4, bm25_weight=0.5)
    sql, *params = conn.fetch.call_args.args
    assert 0.5 in params


@pytest.mark.asyncio
async def test_hybrid_search_uses_override_agent_id(mock_pool):
    from orchestra.memory.vector_store import VectorStore
    pool, conn = mock_pool
    conn.fetch = AsyncMock(return_value=[])

    vs = VectorStore(pool=pool, agent_id="a1")
    await vs.hybrid_search("q", [0.0] * 4, agent_id="a2")
    sql, *params = conn.fetch.call_args.args
    assert "a2" in params
    assert "a1" not in params


@pytest.mark.asyncio
async def test_hybrid_search_sql_contains_rrf_pattern(mock_pool):
    from orchestra.memory.vector_store import VectorStore
    pool, conn = mock_pool
    conn.fetch = AsyncMock(return_value=[])

    vs = VectorStore(pool=pool, agent_id="a1")
    await vs.hybrid_search("q", [0.0] * 4)
    sql = conn.fetch.call_args.args[0]
    assert "vector_results" in sql
    assert "text_results" in sql
    assert "FULL OUTER JOIN" in sql
