import json
from unittest.mock import AsyncMock

import pytest

from orchestra.memory.vector_store import VectorStore


@pytest.fixture
def mock_pool():
    pool = AsyncMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    return pool, conn


@pytest.mark.asyncio
async def test_vector_store_store(mock_pool):
    pool, conn = mock_pool
    store = VectorStore(pool, agent_id="a1")

    await store.store("k1", "content", embedding=[0.1] * 256, metadata={"meta": "data"})

    # Check if conn.execute was called with correct SQL
    args = conn.execute.call_args[0]
    assert "INSERT INTO memory_cold" in args[0]
    assert args[1] == "k1"
    assert args[2] == "a1"
    assert args[3] == "content"
    assert args[4] == [0.1] * 256
    # args[5] is compressed_value
    assert json.loads(args[6]) == {"meta": "data"}


@pytest.mark.asyncio
async def test_vector_store_retrieve(mock_pool):
    pool, conn = mock_pool
    store = VectorStore(pool)

    conn.fetchrow.return_value = {
        "content": "some content",
        "compressed_value": None,
        "metadata": '{"m": 1}',
        "agent_id": "a1",
    }

    res = await store.retrieve("k1")
    assert res == "some content"  # retrieve returns Any | None now
    assert "UPDATE memory_cold" in conn.fetchrow.call_args[0][0]


@pytest.mark.asyncio
async def test_vector_store_search_semantic(mock_pool):
    pool, conn = mock_pool
    store = VectorStore(pool, agent_id="a1")

    conn.fetch.return_value = [{"key": "k1", "score": 0.9}]

    results = await store.search(embedding=[0.1] * 256)
    assert len(results) == 1
    assert results[0][0] == "k1"
    assert "ORDER BY embedding <=> $1" in conn.fetch.call_args[0][0]
