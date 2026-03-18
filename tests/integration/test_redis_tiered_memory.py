import asyncio
import pytest
from orchestra.memory.tiers import TieredMemoryManager, Tier
from orchestra.memory.backends import RedisMemoryBackend
from orchestra.memory.invalidation import InvalidationSubscriber, publish_invalidation

@pytest.fixture
async def redis_url():
    url = "redis://localhost:6379/0"
    # Check if redis is available
    import redis.asyncio as redis
    try:
        client = redis.from_url(url)
        await client.ping()
        await client.aclose()
    except Exception:
        pytest.skip("Redis not available")
    return url

@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_tiered_memory_integration(redis_url):
    backend1 = RedisMemoryBackend(url=redis_url, prefix="test:stack1:")
    backend2 = RedisMemoryBackend(url=redis_url, prefix="test:stack1:") # Same prefix = shared L2
    
    mgr1 = TieredMemoryManager(warm_backend=backend1, hot_max=10, warm_max=10)
    mgr2 = TieredMemoryManager(warm_backend=backend2, hot_max=10, warm_max=10)
    
    # 1. Setup invalidation for mgr1
    # When backend1 receives an invalidation, it should clear mgr1's local policy
    sub1 = InvalidationSubscriber(backend1.client, on_invalidate=lambda k: mgr1._policy.remove(k))
    await sub1.start()
    
    # 2. Store in mgr2
    await mgr2.store("shared_key", {"data": "v1"})
    # publish invalidation (normally this would be in backend.set)
    await publish_invalidation(backend2.client, "shared_key")
    
    await asyncio.sleep(0.2) # Allow for pub/sub
    
    # 3. Retrieve from mgr1 -> should get from shared Redis WARM tier
    val = await mgr1.retrieve("shared_key")
    assert val == {"data": "v1"}
    
    # Clean up
    await sub1.stop()
    keys = await backend1.client.keys("test:stack1:*")
    if keys: await backend1.client.delete(*keys)
    await backend1.close()
    await backend2.close()
