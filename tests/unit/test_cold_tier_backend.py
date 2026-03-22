from unittest.mock import AsyncMock

import pytest

from orchestra.memory.compression import StateCompressor
from orchestra.memory.tiers import ColdTierBackend
from orchestra.memory.vector_store import VectorStore


@pytest.fixture
def mock_pool():
    pool = AsyncMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    return pool, conn


@pytest.mark.asyncio
async def test_vector_store_implements_cold_protocol(mock_pool):
    pool, _ = mock_pool
    store = VectorStore(pool)
    assert isinstance(store, ColdTierBackend)


@pytest.mark.asyncio
async def test_vector_store_integration_compression(mock_pool):
    pool, conn = mock_pool
    compressor = StateCompressor()
    store = VectorStore(pool, compressor=compressor)

    data = {"complex": "object"}
    await store.store("k1", data, embedding=[0.1] * 256)

    # Verify compressed_value was passed to SQL
    args = conn.execute.call_args[0]
    # compressed_value is index 5 in the INSERT statement
    assert isinstance(args[5], bytes)
    assert len(args[5]) > 0

    # Mock retrieval
    conn.fetchrow.return_value = {
        "content": str(data),
        "compressed_value": args[5],
        "metadata": "{}",
    }

    retrieved = await store.retrieve("k1")
    assert retrieved == data
