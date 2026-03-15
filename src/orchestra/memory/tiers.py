"""Tier definitions, SLRU policy, and TieredMemoryManager."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

import structlog

from orchestra.memory.backends import MemoryBackend
from orchestra.memory.manager import MemoryManager

logger = structlog.get_logger(__name__)
_stdlib_logger = logging.getLogger(__name__)

# Sentinel used in retrieve() to distinguish "not found" from a stored None value.
_MISS: object = object()


def _log_task_exception(task: asyncio.Task) -> None:  # pragma: no cover
    """Done-callback that logs any unhandled exception from a background task."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        _stdlib_logger.exception(
            "unhandled exception in background task %r",
            task.get_name(),
            exc_info=exc,
        )


class Tier(str, Enum):
    """Memory tiers by latency and persistence."""
    HOT = "hot"    # In-process, <0.01ms
    WARM = "warm"  # Redis L2, 0.5-2ms
    COLD = "cold"  # pgvector, 5-50ms


@dataclass
class MemoryEntry:
    """Metadata for a memory item."""
    key: str
    value: Any
    tier: Tier = Tier.HOT
    access_count: int = 0
    last_accessed: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    size_bytes: int = 0


@dataclass(frozen=True)
class TierStats:
    """Statistics for each tier."""
    hot_count: int
    warm_count: int
    cold_count: int


@runtime_checkable
class ColdTierBackend(Protocol):
    """Protocol for cold tier storage (pgvector)."""
    async def store(self, key: str, value: Any, embedding: list[float] | None = None) -> None: ...
    async def retrieve(self, key: str) -> Any | None: ...
    async def search(self, embedding: list[float], limit: int = 10) -> list[tuple[str, float]]: ...
    async def delete(self, key: str) -> None: ...
    async def count(self) -> int: ...


class SLRUPolicy:
    """Segmented LRU policy for managing HOT and WARM segments."""

    def __init__(self, hot_max: int, warm_max: int) -> None:
        self.hot_max = hot_max
        self.warm_max = warm_max
        self._hot: OrderedDict[str, MemoryEntry] = OrderedDict()
        self._warm: OrderedDict[str, MemoryEntry] = OrderedDict()

    def access(self, key: str) -> tuple[Tier | None, list[tuple[str, Tier]]]:
        """Record access. Returns (new Tier if promotion occurred, list of evictions)."""
        if key in self._hot:
            entry = self._hot.pop(key)
            entry.access_count += 1
            entry.last_accessed = time.time()
            self._hot[key] = entry
            return None, []

        if key in self._warm:
            entry = self._warm.pop(key)
            entry.access_count += 1
            entry.last_accessed = time.time()
            entry.tier = Tier.HOT
            self._hot[key] = entry
            return Tier.HOT, self.evictions_due()

        return None, []

    def insert(self, key: str, entry: MemoryEntry) -> list[tuple[str, Tier]]:
        """Insert new entry. New items start in WARM."""
        if key in self._hot:
            self._hot[key] = entry
            return []
        if key in self._warm:
            self._warm[key] = entry
            return []

        entry.tier = Tier.WARM
        self._warm[key] = entry
        return self.evictions_due()

    def evictions_due(self) -> list[tuple[str, Tier]]:
        """Identify items that need demotion based on capacity."""
        evicted = []
        # 1. HOT -> WARM
        while len(self._hot) > self.hot_max:
            k, e = self._hot.popitem(last=False)
            e.tier = Tier.WARM
            self._warm[k] = e
            evicted.append((k, Tier.WARM))

        # 2. WARM -> COLD
        while len(self._warm) > self.warm_max:
            k, e = self._warm.popitem(last=False)
            e.tier = Tier.COLD
            evicted.append((k, Tier.COLD))
            
        return evicted

    def remove(self, key: str) -> None:
        self._hot.pop(key, None)
        self._warm.pop(key, None)

    @property
    def hot_keys(self) -> list[str]:
        return list(self._hot.keys())

    @property
    def warm_keys(self) -> list[str]:
        return list(self._warm.keys())


class TieredMemoryManager(MemoryManager):
    """3-tier memory manager implementing the MemoryManager protocol."""

    def __init__(
        self,
        warm_backend: MemoryBackend | None = None,
        cold_backend: ColdTierBackend | None = None,
        deduplicator: Any | None = None,
        hot_max: int = 1000,
        warm_max: int = 10000,
        scan_interval: int = 60,
    ) -> None:
        self._warm = warm_backend
        self._cold = cold_backend
        self._dedup = deduplicator
        self._policy = SLRUPolicy(hot_max, warm_max)
        self._policy_lock = asyncio.Lock()
        self._scan_interval = scan_interval
        self._stop_event = asyncio.Event()
        self._scan_task: asyncio.Task | None = None
        self._initialized = False

    async def start(self) -> None:
        """Start background scan task."""
        if self._initialized:
            return
        self._scan_task = asyncio.create_task(self._background_scan())
        self._scan_task.add_done_callback(_log_task_exception)
        self._initialized = True

    async def stop(self) -> None:
        """Stop background scan task."""
        self._stop_event.set()
        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                # Expected: we requested cancellation ourselves.  Do not
                # suppress or re-raise — the task is now done.
                pass
            except Exception:
                # An unexpected exception escaped _background_scan.
                # Log it so it is never silently lost.
                _stdlib_logger.exception(
                    "background scan task raised an unexpected exception during stop"
                )
        self._initialized = False

    async def store(self, key: str, value: Any) -> None:
        """Store value. Initially placed in WARM or updated in current tier."""
        entry = MemoryEntry(key=key, value=value)
        async with self._policy_lock:
            evictions = self._policy.insert(key, entry)

        # I/O outside the lock — no policy state is touched below this point
        # until _handle_evictions re-acquires it inside demote().
        if self._warm:
            await self._warm.set(key, value)

        await self._handle_evictions(evictions)

    async def retrieve(self, key: str, promote: bool = True) -> Any | None:
        """Retrieve value searching HOT -> WARM -> COLD.

        The _policy_lock is held only for in-memory policy mutations (no I/O
        inside the lock) to avoid holding it across awaits and prevent
        check-then-use races between concurrent coroutines.
        """
        evictions: list[tuple[str, Tier]] = []

        # 1. Try HOT tier — capture value under lock, then do I/O outside.
        async with self._policy_lock:
            if key in self._policy._hot:
                val = self._policy._hot[key].value
                if promote:
                    _, evictions = self._policy.access(key)
            else:
                val = _MISS

        if val is not _MISS:
            if evictions:
                await self._handle_evictions(evictions)
            return val  # type: ignore[return-value]

        # 2. Try WARM tier — same pattern.
        evictions = []
        async with self._policy_lock:
            if key in self._policy._warm:
                val = self._policy._warm[key].value
                if promote:
                    _, evictions = self._policy.access(key)
            else:
                val = _MISS

        if val is not _MISS:
            if evictions:
                await self._handle_evictions(evictions)
            return val  # type: ignore[return-value]

        # 3. Try WARM Backend (Redis) — no policy state involved in the get.
        if self._warm:
            val = await self._warm.get(key)
            if val is not None:
                if promote:
                    async with self._policy_lock:
                        entry = MemoryEntry(key=key, value=val, tier=Tier.HOT)
                        self._policy._hot[key] = entry
                        evictions = self._policy.evictions_due()
                    await self._handle_evictions(evictions)
                return val

        # 4. Try COLD Backend (pgvector).
        if self._cold:
            val = await self._cold.retrieve(key)
            if val is not None:
                if promote:
                    async with self._policy_lock:
                        entry = MemoryEntry(key=key, value=val, tier=Tier.HOT)
                        self._policy._hot[key] = entry
                        evictions = self._policy.evictions_due()
                    await self._handle_evictions(evictions)
                    if self._warm:
                        await self._warm.set(key, val)
                return val

        return None

    async def _handle_evictions(self, evictions: list[tuple[str, Tier]]) -> None:
        """Process a list of keys that were demoted/evicted by the policy."""
        for key, target_tier in evictions:
            if target_tier == Tier.COLD:
                await self.demote(key, Tier.COLD)

    async def promote(self, key: str, to_tier: Tier) -> None:
        """Explicitly promote an item."""
        if to_tier == Tier.HOT:
            await self.retrieve(key, promote=True)
            
    async def demote(self, key: str, to_tier: Tier) -> None:
        """Explicitly demote an item."""
        if to_tier == Tier.COLD and self._cold:
            val = await self.retrieve(key, promote=False)
            if val is not None:
                # Generate embedding if dedup available
                embedding = None
                if self._dedup:
                    embedding = (await self._dedup.embed([str(val)]))[0].tolist()

                await self._cold.store(key, val, embedding=embedding)
                async with self._policy_lock:
                    self._policy.remove(key)
                if self._warm:
                    await self._warm.delete(key)

    async def search_memories(self, query: str, limit: int = 10) -> list[tuple[str, float]]:
        """Semantic search across cold tier."""
        if not self._cold or not self._dedup:
            return []
        
        embedding = (await self._dedup.embed([query]))[0].tolist()
        return await self._cold.search(embedding, limit=limit)

    async def stats(self) -> TierStats:
        cold_count = 0
        if self._cold:
            try:
                cold_count = await self._cold.count()
            except Exception:
                _stdlib_logger.exception(
                    "failed to retrieve cold-tier count; reporting 0"
                )

        async with self._policy_lock:
            hot_count = len(self._policy._hot)
            warm_count = len(self._policy._warm)

        return TierStats(hot_count=hot_count, warm_count=warm_count, cold_count=cold_count)

    async def _background_scan(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(self._scan_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("background_scan_error", error=str(e))


def create_tiered_memory(
    redis_url: str | None = None,
    pg_pool: Any | None = None,
    agent_id: str = "default",
    hot_max: int = 1000,
    warm_max: int = 10000
) -> TieredMemoryManager:
    """Factory function for convenient tiered memory setup."""
    from orchestra.memory.backends import RedisMemoryBackend, InMemoryMemoryBackend
    
    warm = None
    if redis_url:
        warm = RedisMemoryBackend(url=redis_url)
    
    cold = None
    dedup = None
    if pg_pool:
        from orchestra.memory.vector_store import VectorStore
        from orchestra.memory.dedup import SemanticDeduplicator
        from orchestra.memory.compression import StateCompressor
        
        compressor = StateCompressor()
        dedup = SemanticDeduplicator()
        cold = VectorStore(
            pool=pg_pool, 
            agent_id=agent_id, 
            compressor=compressor, 
            deduplicator=dedup
        )
        
    return TieredMemoryManager(
        warm_backend=warm,
        cold_backend=cold,
        deduplicator=dedup,
        hot_max=hot_max,
        warm_max=warm_max
    )
