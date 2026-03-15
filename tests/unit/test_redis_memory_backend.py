import asyncio
import pytest
from pydantic import BaseModel
from orchestra.memory.backends import RedisMemoryBackend

class SampleModel(BaseModel):
    name: str
    count: int

@pytest.fixture
async def redis_backend():
    backend = RedisMemoryBackend(url="redis://localhost:6379/0", prefix="test:mem:")
    # Check if redis is available
    try:
        await backend.client.ping()
    except Exception:
        pytest.skip("Redis not available")
    
    yield backend
    
    # Cleanup
    keys = await backend.client.keys("test:mem:*")
    if keys:
        await backend.client.delete(*keys)
    await backend.close()

@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_backend_basic(redis_backend):
    await redis_backend.set("k1", "v1")
    assert await redis_backend.get("k1") == "v1"
    assert await redis_backend.exists("k1") is True
    
    await redis_backend.delete("k1")
    assert await redis_backend.get("k1") is None

@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_backend_complex_obj(redis_backend):
    obj = SampleModel(name="test", count=42)
    await redis_backend.set("obj1", obj)
    
    retrieved = await redis_backend.get("obj1")
    assert isinstance(retrieved, SampleModel)
    assert retrieved.name == "test"
    assert retrieved.count == 42

@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_backend_ttl(redis_backend):
    await redis_backend.set("kt", "vt", ttl=1)
    assert await redis_backend.get("kt") == "vt"
    
    await asyncio.sleep(1.1)
    assert await redis_backend.get("kt") is None

@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_backend_keys(redis_backend):
    await redis_backend.set("user:1", "a")
    await redis_backend.set("user:2", "b")
    await redis_backend.set("other:1", "c")
    
    keys = await redis_backend.keys("user:*")
    assert sorted(keys) == ["user:1", "user:2"]
