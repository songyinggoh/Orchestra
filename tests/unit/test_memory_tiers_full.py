import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import numpy as np
from orchestra.memory.tiers import TieredMemoryManager, Tier, create_tiered_memory
from orchestra.memory.backends import MemoryBackend
from orchestra.memory.serialization import pack, unpack

@pytest.fixture
def mock_warm():
    return AsyncMock(spec=MemoryBackend)

@pytest.fixture
def mock_cold():
    m = AsyncMock()
    # retrieve, store, search, delete, count
    return m

@pytest.fixture
def mock_dedup():
    m = AsyncMock()
    # embed
    m.embed.return_value = np.zeros((1, 256))
    return m

@pytest.mark.asyncio
async def test_tiered_memory_full_promotion_flow(mock_warm, mock_cold):
    mgr = TieredMemoryManager(warm_backend=mock_warm, cold_backend=mock_cold, hot_max=2, warm_max=2)
    
    # Ensure they return None by default
    mock_warm.get.return_value = None
    mock_cold.retrieve.return_value = None
    
    # 1. Start empty
    assert await mgr.retrieve("k1") is None
    
    # 2. Mock cold tier hit
    mock_cold.retrieve.return_value = "cold_val"
    val = await mgr.retrieve("k1")
    
    assert val == "cold_val"
    # Should promote to HOT and WARM backend
    assert "k1" in mgr._policy._hot
    mock_warm.set.assert_called_with("k1", "cold_val")

@pytest.mark.asyncio
async def test_tiered_memory_search(mock_cold, mock_dedup):
    mgr = TieredMemoryManager(cold_backend=mock_cold, deduplicator=mock_dedup)
    
    mock_cold.search.return_value = [("key1", 0.95)]
    
    results = await mgr.search_memories("find something")
    
    assert results == [("key1", 0.95)]
    mock_dedup.embed.assert_called_with(["find something"])
    mock_cold.search.assert_called()

@pytest.mark.asyncio
async def test_tiered_memory_factory():
    # Test create_tiered_memory without external infra (should use In-memory defaults or None)
    mgr = create_tiered_memory()
    assert isinstance(mgr, TieredMemoryManager)
    assert mgr._warm is None
    assert mgr._cold is None

@pytest.mark.asyncio
async def test_demote_with_embedding(mock_cold, mock_dedup):
    mgr = TieredMemoryManager(cold_backend=mock_cold, deduplicator=mock_dedup, hot_max=1, warm_max=1)
    
    # Create a vector very similar to something
    mock_dedup.embed.return_value = np.array([[0.1]*256])
    
    await mgr.store("k1", "v1")
    await mgr.retrieve("k1") # k1 in HOT
    
    await mgr.store("k2", "v2") # k2 in WARM
    
    # k3 -> WARM, triggers k2 -> COLD
    await mgr.store("k3", "v3")
    
    # Verify demote called cold.store with an embedding
    # Wait, k2 is in WARM, so when k3 is inserted into WARM, k2 is evicted.
    # My current SLRUPolicy.insert returns evictions.
    # In store(): for evicted_key, target_tier in evictions: if COLD: demote(evicted_key)
    
    mock_cold.store.assert_called()
    args = mock_cold.store.call_args[1]
    assert "embedding" in args
    assert args["embedding"] == [0.1]*256
