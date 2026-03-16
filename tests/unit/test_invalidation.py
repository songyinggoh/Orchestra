import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest
from orchestra.memory.invalidation import InvalidationSubscriber, CHANNEL

@pytest.mark.asyncio
async def test_invalidation_subscriber():
    redis = MagicMock()
    pubsub = AsyncMock()
    redis.pubsub.return_value = pubsub
    
    invalidated_keys = []
    def on_invalidate(key):
        invalidated_keys.append(key)
        
    subscriber = InvalidationSubscriber(redis, on_invalidate)
    
    # Mock ps.listen() to yield one message then stop
    async def mock_listen():
        # First message: initial connect/reconnect trigger (handled in _listen_loop)
        # But we need to simulate the ps.listen() generator
        yield {"type": "message", "data": b"key1"}
        # Wait a bit then exit loop
        await asyncio.sleep(0.1)
        subscriber._running = False
        yield {"type": "message", "data": b"key2"}

    pubsub.listen = mock_listen
    pubsub.__aenter__.return_value = pubsub
    
    await subscriber.start()
    await asyncio.sleep(0.2)
    await subscriber.stop()
    
    # "*" is appended by the initial connect logic in _listen_loop
    assert "*" in invalidated_keys
    assert "key1" in invalidated_keys
    assert "key2" in invalidated_keys
    
    pubsub.subscribe.assert_called_with(CHANNEL)
