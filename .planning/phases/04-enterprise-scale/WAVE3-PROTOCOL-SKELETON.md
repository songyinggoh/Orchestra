# Wave 3 Protocol Skeleton — TieredMemoryManager

**Purpose:** Close Gaps 1+2 (MemoryManager too minimal, CacheBackend vs MemoryManager split).
**Approach:** Extend, don't replace. TieredMemoryManager satisfies the existing `MemoryManager` protocol (backward compat) while adding tier-aware methods.

---

## Tier Enum

```python
from enum import Enum

class Tier(str, Enum):
    HOT = "hot"    # In-process dict/TTLCache, <0.01ms
    WARM = "warm"  # Redis L2, 0.5-2ms
    COLD = "cold"  # pgvector + PostgreSQL, 5-50ms
```

## MemoryEntry

```python
from dataclasses import dataclass, field
from typing import Any
import time

@dataclass
class MemoryEntry:
    key: str
    value: Any
    tier: Tier = Tier.HOT
    access_count: int = 0
    last_accessed: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    size_bytes: int = 0
```

## MemoryBackend Protocol (NEW — for Redis WARM tier)

Separate from CacheBackend (which is typed to LLMResponse).

```python
from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class MemoryBackend(Protocol):
    """Backend for tier storage. Stores arbitrary values via msgpack."""

    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any, ttl: int | None = None) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def exists(self, key: str) -> bool: ...
    async def keys(self, pattern: str = "*") -> list[str]: ...
```

## TieredMemoryManager

```python
from orchestra.memory.manager import MemoryManager

class TieredMemoryManager:
    """3-tier memory: HOT (in-process) → WARM (Redis) → COLD (pgvector).

    Implements MemoryManager protocol for backward compat:
      - store(key, value) → writes to HOT
      - retrieve(key) → searches HOT→WARM→COLD, auto-promotes on hit

    Adds tier-aware methods for explicit control.
    """

    def __init__(
        self,
        warm_backend: MemoryBackend | None = None,  # Redis
        cold_backend: ColdTierBackend | None = None,  # pgvector
        hot_max: int = 1000,
        warm_max: int = 10000,
        warm_ttl: int = 3600,        # seconds
        idle_threshold: int = 300,    # seconds before demotion eligible
        scan_interval: int = 60,      # SLRU background scan period
    ) -> None: ...

    # --- MemoryManager protocol (backward compat) ---

    async def store(self, key: str, value: Any) -> None:
        """Store in HOT tier. SLRU handles demotion."""
        ...

    async def retrieve(self, key: str) -> Any | None:
        """Search HOT→WARM→COLD. Auto-promote on hit."""
        ...

    # --- Tier-aware methods (new) ---

    async def promote(self, key: str, to_tier: Tier) -> None:
        """Explicitly move entry to a higher tier."""
        ...

    async def demote(self, key: str, to_tier: Tier) -> None:
        """Explicitly move entry to a lower tier."""
        ...

    async def get_tier(self, key: str) -> Tier | None:
        """Return which tier holds this key, or None."""
        ...

    async def stats(self) -> TierStats:
        """Return counts/sizes per tier."""
        ...

    # --- Lifecycle ---

    async def start(self) -> None:
        """Start background SLRU scan task."""
        ...

    async def stop(self) -> None:
        """Cancel background task, flush pending writes."""
        ...
```

## ColdTierBackend Protocol (NEW — for pgvector)

```python
@runtime_checkable
class ColdTierBackend(Protocol):
    """Backend for cold tier with semantic retrieval."""

    async def store(self, key: str, value: Any, embedding: list[float]) -> None: ...
    async def retrieve(self, key: str) -> Any | None: ...
    async def search(self, embedding: list[float], limit: int = 10) -> list[tuple[str, float]]: ...
    async def delete(self, key: str) -> None: ...
```

## SLRUPolicy (pure logic, no I/O)

```python
from collections import OrderedDict

class SLRUPolicy:
    """Segmented LRU: probationary (WARM) + protected (HOT) segments."""

    def __init__(self, hot_max: int, warm_max: int): ...

    def access(self, key: str) -> Tier | None:
        """Record access. Returns new tier if promotion occurred, else None."""
        ...

    def insert(self, key: str) -> list[tuple[str, Tier]]:
        """Insert new key into WARM (probationary). Returns evictions."""
        ...

    def evictions_due(self) -> list[tuple[str, Tier]]:
        """Return keys that should be demoted based on capacity."""
        ...
```

## ExecutionContext Addition

```python
# In src/orchestra/core/context.py, add:
memory_manager: Any = None      # MemoryManager or TieredMemoryManager
restricted_mode: bool = False   # Set by Attenuator on injection detection
```

## File Layout

```
src/orchestra/memory/
    manager.py          # Existing — MemoryManager protocol (unchanged)
    backends.py         # NEW — MemoryBackend protocol + RedisMemoryBackend
    tiers.py            # NEW — Tier enum, MemoryEntry, TieredMemoryManager, SLRUPolicy
    vector_store.py     # NEW (T-4.9) — VectorStore using pgvector
    dedup.py            # NEW (T-4.9) — SemanticDeduplicator
    compression.py      # NEW (T-4.9) — StateCompressor

src/orchestra/cache/
    backends.py         # Existing — CacheBackend protocol (unchanged)
    redis_backend.py    # NEW — RedisCacheBackend implementing CacheBackend (LLMResponse only)

src/orchestra/security/
    output_scanner.py   # NEW (T-4.10) — OutputScanner implementing Guardrail protocol
    attenuator.py       # NEW (T-4.10) — Attenuator creates restricted ToolACL
    guard.py            # NEW (T-4.10) — SLM wrapper (ProtectAI DeBERTa / Prompt Guard)
```

## Protocol Relationships

```
                    ┌─────────────────────┐
                    │   MemoryManager     │ (existing protocol: store/retrieve)
                    │   Protocol          │
                    └─────────┬───────────┘
                              │ implements
                    ┌─────────▼───────────┐
                    │ TieredMemoryManager │ (new: promote/demote/stats/start/stop)
                    └──┬──────┬───────┬───┘
                       │      │       │
               ┌───────▼┐ ┌──▼────┐ ┌▼──────────────┐
               │  HOT   │ │ WARM  │ │    COLD        │
               │  dict  │ │ Redis │ │  pgvector      │
               └────────┘ └───┬───┘ └───────┬────────┘
                              │             │
                    MemoryBackend    ColdTierBackend
                      protocol         protocol

CacheBackend (LLMResponse) ← SEPARATE, not mixed with memory tiers
```
