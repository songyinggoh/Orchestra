"""Cache backends for Orchestra."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol, runtime_checkable

from orchestra.core.types import LLMResponse


@runtime_checkable
class CacheBackend(Protocol):
    """Protocol for cache storage backends."""

    async def get(self, key: str) -> LLMResponse | None:
        """Retrieve a response from the cache."""
        ...

    async def set(self, key: str, value: LLMResponse, ttl: int | None = None) -> None:
        """Store a response in the cache."""
        ...

    async def delete(self, key: str) -> None:
        """Remove a response from the cache."""
        ...

    async def clear(self) -> None:
        """Clear all entries from the cache."""
        ...


class InMemoryCacheBackend:
    """In-process TTL cache. No persistence, no infra.

    Uses cachetools.TTLCache for automatic expiration and LRU eviction.
    """

    def __init__(self, maxsize: int = 1024, default_ttl: int = 3600) -> None:
        try:
            from cachetools import TTLCache  # type: ignore[import-untyped]
        except ImportError as err:
            raise ImportError(
                "cachetools is required for InMemoryCacheBackend. "
                "Install it with: pip install orchestra-agents[cache]"
            ) from err

        self._cache: TTLCache[str, str] = TTLCache(maxsize=maxsize, ttl=default_ttl)

    async def get(self, key: str) -> LLMResponse | None:
        raw = self._cache.get(key)
        if raw is None:
            return None
        return LLMResponse.model_validate_json(raw)

    async def set(self, key: str, value: LLMResponse, ttl: int | None = None) -> None:
        # Note: TTLCache uses a global TTL set at initialization.
        # Per-item TTL is not supported natively by TTLCache, so we ignore it here.
        self._cache[key] = value.model_dump_json()

    async def delete(self, key: str) -> None:
        self._cache.pop(key, None)

    async def clear(self) -> None:
        self._cache.clear()


class DiskCacheBackend:
    """Disk-backed cache using diskcache. Persists across restarts.

    Uses asyncio.to_thread() to avoid blocking the event loop during I/O.
    """

    def __init__(
        self,
        directory: str | Path = ".orchestra/cache",
        size_limit: int = 2**30,  # 1 GB
    ) -> None:
        try:
            from diskcache import Cache, JSONDisk
        except ImportError as err:
            raise ImportError(
                "diskcache is required for DiskCacheBackend. "
                "Install it with: pip install orchestra-agents[cache]"
            ) from err

        # Use JSONDisk instead of the default pickle-based Disk to avoid
        # unsafe deserialization (CVE-2025-69872). Orchestra only stores JSON
        # strings, so JSONDisk is fully compatible.
        self._cache = Cache(str(directory), disk=JSONDisk, size_limit=size_limit)

    async def get(self, key: str) -> LLMResponse | None:
        raw = await asyncio.to_thread(self._cache.get, key)
        if raw is None:
            return None
        return LLMResponse.model_validate_json(raw)

    async def set(self, key: str, value: LLMResponse, ttl: int | None = None) -> None:
        data = value.model_dump_json()
        await asyncio.to_thread(self._cache.set, key, data, expire=ttl)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._cache.delete, key)

    async def clear(self) -> None:
        await asyncio.to_thread(self._cache.clear)

    async def close(self) -> None:
        """Close the disk cache."""
        await asyncio.to_thread(self._cache.close)
