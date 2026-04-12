"""Backends for tiered memory storage."""

from __future__ import annotations

import fnmatch
import os
import time
from typing import Any, Protocol, runtime_checkable

import structlog

from orchestra.memory.serialization import pack, unpack

logger = structlog.get_logger(__name__)


@runtime_checkable
class MemoryBackend(Protocol):
    """Backend for tier storage. Stores arbitrary values."""

    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any, ttl: int | None = None) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def exists(self, key: str) -> bool: ...
    async def keys(self, pattern: str = "*") -> list[str]: ...


class InMemoryMemoryBackend:
    """In-memory implementation of MemoryBackend.

    Uses a dictionary with lazy expiration and pattern-based key lookup.
    """

    def __init__(self) -> None:
        # key -> (value, expiry_timestamp)
        self._data: dict[str, tuple[Any, float | None]] = {}

    async def get(self, key: str) -> Any | None:
        if key not in self._data:
            return None

        val, expiry = self._data[key]
        if expiry and time.time() > expiry:
            del self._data[key]
            return None

        return val

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        expiry = time.time() + ttl if ttl is not None else None
        self._data[key] = (value, expiry)

    async def delete(self, key: str) -> None:
        if key in self._data:
            del self._data[key]

    async def exists(self, key: str) -> bool:
        return (await self.get(key)) is not None

    async def keys(self, pattern: str = "*") -> list[str]:
        # Filter out expired items first
        now = time.time()
        expired = [k for k, (_, exp) in self._data.items() if exp and now > exp]
        for k in expired:
            del self._data[k]

        return fnmatch.filter(self._data.keys(), pattern)


class RedisMemoryBackend:
    """Redis-backed implementation of MemoryBackend.

    Uses redis.asyncio with connection pooling and msgpack serialization.
    """

    def __init__(
        self,
        url: str | None = None,
        prefix: str = "orch:mem:",
        max_connections: int = 20,
    ) -> None:
        url = url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        import redis.asyncio as redis
        from redis.asyncio.connection import BlockingConnectionPool
        from redis.backoff import ExponentialBackoff
        from redis.retry import Retry

        resolved_url = url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        self.prefix = prefix
        self.pool = BlockingConnectionPool.from_url(
            resolved_url,
            max_connections=max_connections,
            timeout=5.0,
            retry=Retry(ExponentialBackoff(), 3),
            health_check_interval=3,
        )
        self.client = redis.Redis(connection_pool=self.pool)

    def _prefixed(self, key: str) -> str:
        return f"{self.prefix}{key}"

    async def get(self, key: str) -> Any | None:
        try:
            data = await self.client.get(self._prefixed(key))
            if data is None:
                return None
            return unpack(data)
        except Exception as e:
            logger.error("redis_get_failed", key=key, error=str(e))
            return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        try:
            data = pack(value)
            await self.client.set(self._prefixed(key), data, ex=ttl)
        except Exception as e:
            logger.error("redis_set_failed", key=key, error=str(e))

    async def delete(self, key: str) -> None:
        try:
            await self.client.delete(self._prefixed(key))
        except Exception as e:
            logger.error("redis_delete_failed", key=key, error=str(e))

    async def exists(self, key: str) -> bool:
        try:
            return bool(await self.client.exists(self._prefixed(key)))
        except Exception as e:
            logger.error("redis_exists_failed", key=key, error=str(e))
            return False

    async def keys(self, pattern: str = "*") -> list[str]:
        try:
            # We must strip the prefix from the returned keys
            full_pattern = self._prefixed(pattern)
            keys = await self.client.keys(full_pattern)
            prefix_len = len(self.prefix)
            return [k.decode("utf-8")[prefix_len:] for k in keys]
        except Exception as e:
            logger.error("redis_keys_failed", pattern=pattern, error=str(e))
            return []

    async def close(self) -> None:
        await self.client.aclose()
        await self.pool.disconnect()

    async def __aenter__(self) -> RedisMemoryBackend:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        await self.close()
