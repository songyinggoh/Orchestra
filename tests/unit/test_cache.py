"""Tests for Orchestra caching layer."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from orchestra.cache.backends import InMemoryCacheBackend
from orchestra.core.types import LLMResponse, Message, MessageRole, TokenUsage
from orchestra.providers.cached import CachedProvider


def _user(content: str) -> Message:
    return Message(role=MessageRole.USER, content=content)


@pytest.fixture
def mock_provider():
    provider = MagicMock()
    provider.provider_name = "test-provider"
    provider.default_model = "test-model"
    provider.complete = AsyncMock()
    return provider


@pytest.fixture
def memory_cache():
    return InMemoryCacheBackend(maxsize=100)


class TestCachedProvider:
    """Tests for CachedProvider wrapper."""

    @pytest.mark.asyncio
    async def test_cache_miss_calls_provider_and_stores(self, mock_provider, memory_cache):
        # Setup
        response = LLMResponse(content="Hello world", model="test-model", usage=TokenUsage(total_tokens=10))
        mock_provider.complete.return_value = response
        cached = CachedProvider(mock_provider, memory_cache)
        messages = [_user("Hi")]

        # Act
        result = await cached.complete(messages, temperature=0.0)

        # Assert
        assert result.content == "Hello world"
        assert mock_provider.complete.call_count == 1
        
        # Verify it's now in cache
        key = cached._cache_key(messages, None, 0.0, None, None, None)
        in_cache = await memory_cache.get(key)
        assert in_cache is not None
        assert in_cache.content == "Hello world"

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_value_without_calling_provider(self, mock_provider, memory_cache):
        # Setup: Pre-populate cache
        messages = [_user("Hi")]
        response = LLMResponse(content="Cached answer", model="test-model")
        cached = CachedProvider(mock_provider, memory_cache)
        key = cached._cache_key(messages, None, 0.0, None, None, None)
        await memory_cache.set(key, response)

        # Act
        result = await cached.complete(messages, temperature=0.0)

        # Assert
        assert result.content == "Cached answer"
        assert mock_provider.complete.call_count == 0

    @pytest.mark.asyncio
    async def test_high_temperature_bypasses_cache(self, mock_provider, memory_cache):
        # Setup
        response = LLMResponse(content="Fresh answer", model="test-model")
        mock_provider.complete.return_value = response
        cached = CachedProvider(mock_provider, memory_cache, max_cacheable_temperature=0.0)
        messages = [_user("Hi")]

        # Act
        result = await cached.complete(messages, temperature=0.7)

        # Assert
        assert result.content == "Fresh answer"
        assert mock_provider.complete.call_count == 1
        
        # Verify it's NOT in cache
        key = cached._cache_key(messages, None, 0.7, None, None, None)
        in_cache = await memory_cache.get(key)
        assert in_cache is None

    @pytest.mark.asyncio
    async def test_different_parameters_produce_different_keys(self, mock_provider, memory_cache):
        cached = CachedProvider(mock_provider, memory_cache)
        msg1 = [_user("Hi")]
        msg2 = [_user("Hello")]
        
        key1 = cached._cache_key(msg1, "model-a", 0.0, None, None, None)
        key2 = cached._cache_key(msg2, "model-a", 0.0, None, None, None)
        key3 = cached._cache_key(msg1, "model-b", 0.0, None, None, None)
        key4 = cached._cache_key(msg1, "model-a", 0.1, None, None, None)
        
        assert key1 != key2
        assert key1 != key3
        assert key1 != key4

    @pytest.mark.asyncio
    async def test_in_memory_cache_ttl_expires_entries(self):
        import time
        
        # Setup cache with a very short TTL
        cache = InMemoryCacheBackend(maxsize=10, default_ttl=0.1)
        response = LLMResponse(content="I will expire soon", model="test-model")

        # Set value
        await cache.set("my-key", response)
        
        # Assert it's there
        cached_item = await cache.get("my-key")
        assert cached_item is not None
        assert cached_item.content == "I will expire soon"
        
        # Wait for TTL to pass
        time.sleep(0.2)
        
        # Assert it's gone
        cached_item_after_ttl = await cache.get("my-key")
        assert cached_item_after_ttl is None

    @pytest.mark.asyncio
    async def test_disk_cache_backend(self, mock_provider, tmp_path):
        from orchestra.cache.backends import DiskCacheBackend

        cache_dir = tmp_path / "cache"
        disk_cache = DiskCacheBackend(directory=cache_dir)
        
        try:
            cached = CachedProvider(mock_provider, disk_cache)
            messages = [_user("Hi")]
            response = LLMResponse(content="Disk cached", model="test-model")
            mock_provider.complete.return_value = response

            # Miss
            await cached.complete(messages, temperature=0.0)
            assert mock_provider.complete.call_count == 1
            
            # Hit
            result = await cached.complete(messages, temperature=0.0)
            assert result.content == "Disk cached"
            assert mock_provider.complete.call_count == 1
        finally:
            await disk_cache.close()
