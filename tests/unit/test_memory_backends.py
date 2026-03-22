import asyncio

import pytest

from orchestra.memory.backends import InMemoryMemoryBackend


@pytest.mark.asyncio
async def test_in_memory_backend_basic():
    backend = InMemoryMemoryBackend()

    await backend.set("k1", "v1")
    assert await backend.get("k1") == "v1"
    assert await backend.exists("k1") is True

    await backend.delete("k1")
    assert await backend.get("k1") is None
    assert await backend.exists("k1") is False


@pytest.mark.asyncio
async def test_in_memory_backend_ttl():
    backend = InMemoryMemoryBackend()

    # Set with 0.1s TTL
    await backend.set("k1", "v1", ttl=0.1)
    assert await backend.get("k1") == "v1"

    await asyncio.sleep(0.15)
    assert await backend.get("k1") is None


@pytest.mark.asyncio
async def test_in_memory_backend_keys():
    backend = InMemoryMemoryBackend()

    await backend.set("user:1:name", "alice")
    await backend.set("user:2:name", "bob")
    await backend.set("agent:1:status", "active")

    keys = await backend.keys("user:*")
    assert sorted(keys) == ["user:1:name", "user:2:name"]

    all_keys = await backend.keys()
    assert len(all_keys) == 3


@pytest.mark.asyncio
async def test_in_memory_backend_keys_expiry():
    backend = InMemoryMemoryBackend()

    await backend.set("k1", "v1", ttl=0.1)
    await backend.set("k2", "v2")

    assert len(await backend.keys()) == 2

    await asyncio.sleep(0.15)
    # k1 should be filtered out by keys()
    keys = await backend.keys()
    assert keys == ["k2"]
