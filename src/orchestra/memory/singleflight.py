"""Singleflight pattern to coalesce concurrent requests."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

T = TypeVar("T")


class SingleFlight(Generic[T]):
    """Coalesces concurrent requests for the same key.

    Useful for preventing cache stampedes (thundering herds).
    """

    def __init__(self) -> None:
        # key -> Future
        self._inflight: dict[str, asyncio.Future[T]] = {}

    async def do(self, key: str, fn: Callable[[], Awaitable[T]]) -> T:
        """Execute fn, coalescing concurrent calls for the same key.

        If a call for 'key' is already in progress, wait for its result.
        Otherwise, execute 'fn' and return the result to all callers.
        """
        if key in self._inflight:
            return await self._inflight[key]

        # Register our intent to fetch
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._inflight[key] = fut

        try:
            result = await fn()
            fut.set_result(result)
            return result
        except Exception as e:
            fut.set_exception(e)
            raise
        finally:
            # Remove from inflight so subsequent calls start fresh
            # (but ONLY if we are the one who started this future)
            if self._inflight.get(key) is fut:
                del self._inflight[key]
