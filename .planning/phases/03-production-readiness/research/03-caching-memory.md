# Phase 3: Caching & Memory - Deep Research

**Researched:** 2026-03-10
**Domain:** LLM Response Caching, Multi-Tier Memory, Distributed Events
**Confidence:** HIGH (core caching), MEDIUM (semantic caching), MEDIUM (memory tiering)

## Summary

LLM response caching is a well-understood optimization that delivers 80-95% latency reduction and significant cost savings. For Orchestra's current single-process deployment (Phase 3), **exact-match caching behind a `CacheBackend` protocol** is the correct scope. Semantic caching, Redis pub/sub, and vector-based memory retrieval are Phase 4 concerns that should be designed-for but not implemented now.

The recommended architecture is a **`CachedProvider` wrapper** that decorates any `LLMProvider` with cache-through semantics, backed by a pluggable `CacheBackend` protocol. Phase 3 ships two backends: `InMemoryCacheBackend` (cachetools TTLCache) and `DiskCacheBackend` (diskcache). A `RedisCacheBackend` is a mechanical Phase 4 addition. The `MemoryManager` protocol should be defined as a thin interface with a single `InMemoryMemoryManager` implementation.

**Primary recommendation:** Build `CachedProvider` + `CacheBackend` protocol with in-memory and disk backends. Define a simplified 2-method `MemoryManager` protocol. Defer semantic caching, Redis, and vector retrieval to Phase 4.

---

## 1. LLM Response Caching Strategies

### 1.1 When Caching is Appropriate for Non-Deterministic LLM Calls

LLM outputs are inherently non-deterministic at temperature > 0. Caching strategies must account for this.

| Temperature | Cacheability | Rationale |
|-------------|-------------|-----------|
| 0.0 | Always cache | Deterministic output; identical inputs produce identical outputs |
| 0.0-0.3 | Cache with short TTL | Near-deterministic; acceptable for most use cases |
| > 0.3 | Do NOT cache by default | High variance makes cached responses misleading |
| Any (with tool_calls) | Cache selectively | Tool call results may depend on external state |

**Confidence: HIGH** -- This is consensus across LangChain, GPTCache, Instructor, and AWS caching guidance.

### 1.2 Industry Approaches

**LangChain Cache** (reference architecture):
- `InMemoryCache`: Dict-based exact match on `(prompt_text, llm_string)` composite key
- `SQLiteCache`: SQLAlchemy-backed persistence with same key structure
- `RedisSemanticCache`: Vector similarity lookup using embeddings
- Key insight: LangChain uses `llm_string` (deterministic repr of model + params) as part of the composite key, preventing same-prompt-different-model collisions

**GPTCache** (semantic-first approach):
- Modular architecture: LLM Adapter -> Embedding Generator -> Vector Store -> Cache Storage -> Similarity Evaluator
- Supports FAISS, Milvus, and Zilliz as vector stores
- Supports SQLite, PostgreSQL, Redis, MongoDB for cache storage
- **Assessment:** Over-engineered for Phase 3. GPTCache's value is semantic caching, which Orchestra doesn't need yet. Its dependency chain (FAISS/Milvus, embedding models) is heavy.

**Instructor** (June 2025+):
- Ships native `AutoCache` (in-process LRU) and `RedisCache` as cache adapters
- Passed directly when creating client: `client = instructor.from_openai(openai.Client(), cache=AutoCache())`
- Validates the pattern of cache-as-wrapper rather than cache-in-provider

### 1.3 Recommended Pattern: CachedProvider Wrapper

This aligns with Orchestra's existing Protocol-based architecture. `CachedProvider` wraps any `LLMProvider` transparently.

```python
# src/orchestra/providers/cached.py

from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from orchestra.core.types import LLMResponse, Message


@runtime_checkable
class CacheBackend(Protocol):
    """Protocol for cache storage backends."""

    async def get(self, key: str) -> LLMResponse | None: ...
    async def set(self, key: str, value: LLMResponse, ttl: int | None = None) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def clear(self) -> None: ...


class CachedProvider:
    """Cache-through wrapper for any LLMProvider.

    Only caches calls with temperature <= max_cacheable_temperature (default 0.0).
    Tool-calling responses are cached by default but can be excluded.
    """

    def __init__(
        self,
        provider: Any,  # LLMProvider protocol
        cache: CacheBackend,
        *,
        default_ttl: int = 3600,  # 1 hour
        max_cacheable_temperature: float = 0.0,
        cache_tool_calls: bool = True,
    ) -> None:
        self._provider = provider
        self._cache = cache
        self._default_ttl = default_ttl
        self._max_temp = max_cacheable_temperature
        self._cache_tool_calls = cache_tool_calls

    @property
    def provider_name(self) -> str:
        return self._provider.provider_name

    @property
    def default_model(self) -> str:
        return self._provider.default_model

    @staticmethod
    def _cache_key(
        messages: list[Message],
        model: str | None,
        temperature: float,
        max_tokens: int | None,
        tools: list[dict[str, Any]] | None,
        output_type: type[BaseModel] | None,
    ) -> str:
        """Generate SHA-256 cache key from all parameters that affect output."""
        key_data = {
            "messages": [m.model_dump(exclude={"metadata"}) for m in messages],
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "tools": tools,
            "output_type": output_type.__name__ if output_type else None,
        }
        canonical = json.dumps(key_data, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    async def complete(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        output_type: type[BaseModel] | None = None,
    ) -> LLMResponse:
        # Skip cache for high-temperature calls
        if temperature > self._max_temp:
            return await self._provider.complete(
                messages, model=model, tools=tools,
                temperature=temperature, max_tokens=max_tokens,
                output_type=output_type,
            )

        key = self._cache_key(messages, model, temperature, max_tokens, tools, output_type)

        # Cache lookup
        cached = await self._cache.get(key)
        if cached is not None:
            return cached

        # Cache miss -- call provider
        result = await self._provider.complete(
            messages, model=model, tools=tools,
            temperature=temperature, max_tokens=max_tokens,
            output_type=output_type,
        )

        # Optionally skip caching tool-call responses
        if result.tool_calls and not self._cache_tool_calls:
            return result

        await self._cache.set(key, result, self._default_ttl)
        return result

    # Delegate stream() and other methods to underlying provider
    async def stream(self, *args, **kwargs):
        return await self._provider.stream(*args, **kwargs)

    def count_tokens(self, *args, **kwargs):
        return self._provider.count_tokens(*args, **kwargs)

    def get_model_cost(self, *args, **kwargs):
        return self._provider.get_model_cost(*args, **kwargs)
```

---

## 2. Cache Key Design

### 2.1 What Goes Into the Key

All parameters that affect LLM output must be included in the cache key:

| Parameter | Include? | Notes |
|-----------|----------|-------|
| `messages` (role + content) | YES | Core prompt content. Exclude `metadata` dict (local-only annotations) |
| `model` | YES | Different models produce different outputs |
| `temperature` | YES | Affects sampling behavior |
| `max_tokens` | YES | Can truncate output differently |
| `tools` (definitions) | YES | Tool availability changes model behavior |
| `output_type` (Pydantic class name) | YES | Structured output constraint changes response format |
| `message.name` | YES | Included via full message serialization |
| `message.tool_call_id` | YES | Included via full message serialization |
| `raw_response` | NO | This is output, not input |
| `message.metadata` | NO | Local annotations, not sent to LLM |

### 2.2 Hashing Strategy

```python
# Canonical approach: sorted JSON -> SHA-256
key_data = {
    "messages": [m.model_dump(exclude={"metadata"}) for m in messages],
    "model": model,
    "temperature": temperature,
    "max_tokens": max_tokens,
    "tools": tools,
    "output_type": output_type.__name__ if output_type else None,
}
canonical = json.dumps(key_data, sort_keys=True, default=str)
cache_key = hashlib.sha256(canonical.encode()).hexdigest()
```

**Why SHA-256:**
- Fixed 64-character hex output regardless of prompt size
- Collision-resistant (no practical collisions for this use case)
- Fast enough (microseconds vs milliseconds for LLM calls)
- Standard library -- no dependencies

**Why `sort_keys=True`:**
- Ensures identical dicts with different key ordering produce the same hash
- Critical for tool definitions where dict ordering may vary

**Why `default=str`:**
- Handles edge cases like datetime objects or custom types in tool arguments
- Prevents json.dumps failures on non-serializable types

**Confidence: HIGH** -- This is the standard approach used by LangChain, Instructor, and AWS caching implementations.

---

## 3. Cache Backend Implementations

### 3.1 Backend Comparison

| Backend | Library | Version | Infra | Persistence | Async Native | Thread-Safe | Use Case |
|---------|---------|---------|-------|-------------|--------------|-------------|----------|
| In-Memory | `cachetools` | 7.0.3 | None | No | No | No | Dev, testing, ephemeral |
| Disk | `diskcache` | 5.6.3 | None | Yes (SQLite) | No | Yes | Single-process production |
| Redis (Phase 4) | `redis` | 7.x | Redis server | Yes | Yes | Yes | Distributed (Phase 4) |

### 3.2 InMemoryCacheBackend (cachetools)

```python
# src/orchestra/cache/memory.py

import asyncio
from typing import Any

from cachetools import TTLCache

from orchestra.core.types import LLMResponse


class InMemoryCacheBackend:
    """In-process TTL cache. No persistence, no infra.

    Uses cachetools.TTLCache for automatic expiration.
    Not thread-safe -- use only with asyncio (single-threaded event loop).
    """

    def __init__(self, maxsize: int = 1024, default_ttl: int = 3600) -> None:
        self._cache: TTLCache[str, str] = TTLCache(maxsize=maxsize, ttl=default_ttl)
        self._default_ttl = default_ttl

    async def get(self, key: str) -> LLMResponse | None:
        raw = self._cache.get(key)
        if raw is None:
            return None
        return LLMResponse.model_validate_json(raw)

    async def set(self, key: str, value: LLMResponse, ttl: int | None = None) -> None:
        # TTLCache uses a global TTL; per-item TTL requires a wrapper
        self._cache[key] = value.model_dump_json()

    async def delete(self, key: str) -> None:
        self._cache.pop(key, None)

    async def clear(self) -> None:
        self._cache.clear()
```

**Why cachetools for in-memory:**
- Pure Python, zero dependencies, 7.0.3 is stable
- TTLCache handles automatic expiration
- LRU eviction when maxsize reached
- Asyncio-safe (single-threaded event loop -- no threading concern)
- 3.5M+ monthly PyPI downloads

**Limitation:** No native async. But since operations are pure dict lookups (nanoseconds), wrapping in `run_in_executor` is unnecessary -- just make the methods `async def` for protocol compliance.

### 3.3 DiskCacheBackend (diskcache)

```python
# src/orchestra/cache/disk.py

import asyncio
from functools import partial
from pathlib import Path

from orchestra.core.types import LLMResponse


class DiskCacheBackend:
    """Disk-backed cache using diskcache. Persists across restarts.

    Uses asyncio.to_thread() for non-blocking I/O.
    """

    def __init__(
        self,
        directory: str | Path = ".orchestra/cache",
        size_limit: int = 2**30,  # 1 GB
    ) -> None:
        import diskcache
        self._cache = diskcache.Cache(str(directory), size_limit=size_limit)

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
        await asyncio.to_thread(self._cache.close)
```

**Why diskcache for persistent caching:**
- Pure Python, zero C dependencies
- SQLite-backed -- battle-tested durability
- Native per-item TTL via `expire` parameter
- Thread-safe by default (unlike cachetools)
- Faster than Redis for single-process (no network hop)
- Size-limited with automatic eviction
- 1.5M+ monthly PyPI downloads

**Why `asyncio.to_thread()`:**
- diskcache does not support native async
- `to_thread()` runs blocking I/O in the default executor without blocking the event loop
- Overhead is negligible (~50us) compared to disk I/O

### 3.4 RedisCacheBackend (Phase 4 -- Design Only)

```python
# src/orchestra/cache/redis.py (Phase 4 implementation)

class RedisCacheBackend:
    """Redis-backed cache for distributed deployments.

    Uses redis.asyncio for native async support.
    Requires: pip install redis>=5.0
    """

    def __init__(self, url: str = "redis://localhost:6379", prefix: str = "orchestra:cache:") -> None:
        import redis.asyncio as aioredis
        self._redis = aioredis.from_url(url, decode_responses=True)
        self._prefix = prefix

    async def get(self, key: str) -> LLMResponse | None:
        raw = await self._redis.get(f"{self._prefix}{key}")
        if raw is None:
            return None
        return LLMResponse.model_validate_json(raw)

    async def set(self, key: str, value: LLMResponse, ttl: int | None = None) -> None:
        full_key = f"{self._prefix}{key}"
        data = value.model_dump_json()
        if ttl:
            await self._redis.setex(full_key, ttl, data)
        else:
            await self._redis.set(full_key, data)

    async def delete(self, key: str) -> None:
        await self._redis.delete(f"{self._prefix}{key}")

    async def clear(self) -> None:
        # Scan and delete all keys with prefix
        async for key in self._redis.scan_iter(f"{self._prefix}*"):
            await self._redis.delete(key)

    async def close(self) -> None:
        await self._redis.aclose()
```

**Redis connection pooling best practices (for Phase 4):**
- Use `Redis.from_url()` which creates an internal connection pool automatically
- For shared pools across clients, use `Redis.from_pool(pool)` to transfer ownership
- Configure: `max_connections=10`, `retry_on_timeout=True`, `socket_keepalive=True`, `health_check_interval=30`
- Always call `aclose()` explicitly -- no async destructor magic in Python
- Use `BlockingConnectionPool` if pool exhaustion is a concern (blocks instead of raising ConnectionError)

**Confidence: HIGH** -- redis-py 7.x is the canonical async Redis client (aioredis was merged in).

---

## 4. Semantic Caching (Phase 4 -- Research Notes)

### 4.1 When Exact Match is Insufficient

Exact-match caching has a fundamental limitation: "What is Python?" and "Tell me about Python" are semantically identical but have different cache keys. Semantic caching addresses this with embedding-based similarity lookup.

### 4.2 Architecture

```
Query -> Embed(query) -> Vector Search(top-k=1) -> Similarity Score
  |                                                      |
  |  score >= threshold (e.g., 0.85) -> Return cached response
  |  score < threshold -> Call LLM -> Store (embedding, response) -> Return
```

### 4.3 Threshold Selection

| Threshold | Behavior | Use Case |
|-----------|----------|----------|
| >= 0.95 | Near-duplicate only | High-accuracy, low hit rate |
| 0.85-0.90 | Balanced | General purpose (recommended starting point) |
| 0.75-0.85 | Broader matching | FAQ-style, high hit rate, some accuracy loss |
| < 0.75 | Risky | Too many false positives |

**Research finding (2025):** Adaptive thresholds outperform fixed thresholds. MeanCache achieves ~17% higher F-score and 20% higher precision than GPTCache by optimizing thresholds per category.

### 4.4 Vector Store Options for Phase 4

| Store | Type | Strengths | Integration Pattern |
|-------|------|-----------|-------------------|
| **pgvector** | PostgreSQL extension | Orchestra already uses PostgreSQL; no new infra. Handles 10-100M vectors. | Add `CREATE EXTENSION vector` to postgres.py schema |
| ChromaDB | Embedded | Zero-config, Python-native, fast prototyping. Rust rewrite (2025) = 4x faster. | Separate embedded process |
| FAISS | Library | Fastest raw search. GPU support. Meta-backed. | In-process, no persistence |

**Recommendation for Phase 4:** pgvector. Orchestra already has PostgresEventStore with asyncpg. Adding vector columns is additive -- no new infrastructure, no new connections, no new deployment concerns. Reserve ChromaDB/FAISS for teams without PostgreSQL.

### 4.5 Security Warning

Recent research (January 2026) documents **key collision attacks** on semantic caching where adversarial prompts are crafted to match cached entries and extract cached responses. Any semantic cache in production needs rate limiting and cache isolation per user/tenant.

**Confidence: MEDIUM** -- Semantic caching is well-researched but threshold tuning is workload-specific.

---

## 5. Redis Pub/Sub vs PostgreSQL LISTEN/NOTIFY

### 5.1 Comparison for Orchestra

| Feature | PostgreSQL LISTEN/NOTIFY | Redis Pub/Sub |
|---------|-------------------------|---------------|
| Already available | YES (asyncpg in Orchestra) | No (new dependency) |
| Message durability | Transactional (delivered on commit) | Fire-and-forget (no persistence) |
| Latency | 0.1-1ms higher | Lower (~0.05ms) |
| Throughput | Adequate for <10K msg/sec | Higher (100K+ msg/sec) |
| Message size | 8KB payload limit | 512MB limit |
| Pattern matching | Channel name only | Glob-pattern channel subscriptions |
| Missed messages | Buffered per connection | Lost if subscriber disconnected |

### 5.2 Recommendation

**Phase 3:** PostgreSQL LISTEN/NOTIFY is sufficient. Orchestra's EventBus is in-process. Distributed eventing is a Phase 4 concern (NATS is already planned for Phase 4 per ROADMAP.md). Adding Redis pub/sub now creates infrastructure cost with no benefit.

**Phase 4:** When distributed eventing is needed, NATS (already in roadmap) is a better fit than Redis pub/sub because:
- NATS has JetStream for message persistence (Redis pub/sub does not)
- NATS handles 10M+ msg/sec (order of magnitude above Redis pub/sub)
- NATS is purpose-built for messaging; Redis pub/sub is a secondary feature

**Confidence: HIGH** -- Orchestra's in-process EventBus handles single-process deployment. Distributed eventing is explicitly Phase 4 scope.

---

## 6. Multi-Tier Memory Architecture

### 6.1 Industry Patterns

**Mem0** (production-grade memory layer):
- Extracts, consolidates, and retrieves salient information from conversations
- Four memory types: episodic, semantic, procedural, associative
- Uses priority scoring and contextual tagging to prevent memory bloat
- Claims 91% lower p95 latency and 90%+ token cost savings vs full-context approaches
- Graph-based variant captures relational structures between conversation elements

**Letta/MemGPT** (LLM-as-OS paradigm):
- Three-tier architecture:
  - **Core Memory:** Always in-context, compressed essential facts (~few KB)
  - **Recall Memory:** Searchable database via semantic search (recent conversation history)
  - **Archival Memory:** Long-term storage, moved back into core/recall on demand
- Self-editing: the LLM decides what to remember/forget via tool calls
- Key insight: memory management is a tool-use problem, not a storage problem

**LangChain Memory** (simple patterns):
- `ConversationBufferMemory`: Keep all messages (simple, context window limited)
- `ConversationSummaryMemory`: LLM-summarized history (lossy, token-efficient)
- `ConversationBufferWindowMemory`: Sliding window of last K messages
- `VectorStoreRetrieverMemory`: Semantic search over past interactions

### 6.2 What Orchestra Already Has

Orchestra's existing infrastructure covers several memory concerns:

| Memory Need | Existing Solution | Gap |
|-------------|-------------------|-----|
| Current run state | `project_state()` from EventStore events | None |
| Run history | `EventStore.list_runs()` + `get_events()` | No semantic search |
| Checkpoint/resume | `Checkpoint` model + `save_checkpoint`/`get_checkpoint` | None |
| Cross-run context | Not implemented | Need MemoryManager |
| Semantic retrieval | Not implemented | Phase 4 (vector store) |

### 6.3 Recommended Phase 3 Scope: 2-Method Interface

```python
# src/orchestra/memory/manager.py

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class MemoryManager(Protocol):
    """Simplified protocol for session persistence."""

    async def store(self, key: str, value: Any) -> None: ...
    async def retrieve(self, key: str) -> Any | None: ...


class InMemoryMemoryManager:
    """Simple in-memory implementation for Phase 3.

    All data backed by a dict. No persistence, no vector search.
    Establishes the interface for Phase 4 backends.
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def store(self, key: str, value: Any) -> None:
        self._data[key] = value

    async def retrieve(self, key: str) -> Any | None:
        return self._data.get(key)
```

### 6.4 Phase 4 Upgrade Path

| Phase 3 (Now) | Phase 4 (Later) | Migration |
|----------------|-----------------|-----------|
| `InMemoryMemoryManager` | `RedisMemoryManager` (hot tier) | Swap implementation, same protocol |
| Simplified store/retrieve | Multi-tiering + Vector search | Extend protocol or add specialized methods |

**Confidence: MEDIUM** -- The interface is well-designed based on Mem0/Letta patterns, but the optimal search/retrieval strategy depends on actual usage patterns that Phase 3 deployment will reveal.

---

## 7. Cache Invalidation

### 7.1 TTL Strategies

| Content Type | Recommended TTL | Rationale |
|-------------|-----------------|-----------|
| Knowledge/reasoning (temp=0) | 1 hour - 24 hours | Static knowledge rarely changes |
| Code generation | 30 min - 1 hour | Libraries/APIs evolve |
| Tool-calling results | 0 (no cache) or 5 min | Tool results depend on external state |
| Structured output extraction | 1 hour | Deterministic given same input |
| Summarization | 1 hour | Deterministic at temp=0 |

### 7.2 State-Dependent Cache Keys

When an agent's behavior depends on workflow state (e.g., "current user context"), the state must be part of the cache key. Orchestra's approach:

```python
# Option A: Include relevant state in messages (already happens via system prompt)
# The system prompt contains state-dependent context, so it's naturally part of the key.

# Option B: Explicit state hash for advanced cases
def _cache_key_with_state(self, messages, state_fields: dict, **kwargs) -> str:
    key_data = {
        "messages": [...],
        "state_context": state_fields,  # Only include fields that affect behavior
        **kwargs,
    }
    return hashlib.sha256(json.dumps(key_data, sort_keys=True).encode()).hexdigest()
```

**Recommendation:** Option A is sufficient for Phase 3. State-dependent context is typically injected into the system prompt by Orchestra's agent execution, so it naturally becomes part of the cache key via message content.

### 7.3 Invalidation Patterns

| Pattern | Implementation | When |
|---------|---------------|------|
| TTL expiration | Built into TTLCache and diskcache | Default -- always use |
| Manual invalidation | `cache.delete(key)` | When external data changes |
| Full flush | `cache.clear()` | Model upgrade, schema change |
| Version prefix | Prepend `v{schema_version}:` to keys | Breaking changes in prompt format |

**Confidence: HIGH** -- TTL-based invalidation is the standard approach. Event-based invalidation is Phase 4 scope.

---

## 8. Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| In-memory TTL cache | Custom dict + threading.Timer | `cachetools.TTLCache` | Automatic expiration, LRU eviction, battle-tested |
| Persistent key-value cache | Custom SQLite wrapper | `diskcache.Cache` | Thread-safe, size-limited, per-item TTL, pure Python |
| SHA-256 hashing | Custom fingerprinting | `hashlib.sha256` + `json.dumps(sort_keys=True)` | Standard library, deterministic, collision-resistant |
| JSON serialization of Pydantic | Custom serializers | `LLMResponse.model_dump_json()` / `model_validate_json()` | Built-in round-trip serialization |
| Redis async client | aioredis (deprecated) | `redis.asyncio` (redis-py 7.x) | aioredis merged into redis-py; single maintained package |
| Vector similarity search | Custom cosine similarity | pgvector / ChromaDB (Phase 4) | Index optimization, approximate nearest neighbor, battle-tested |

---

## 9. Common Pitfalls

### Pitfall 1: Caching Non-Deterministic Responses
**What goes wrong:** Caching temperature > 0 responses returns stale, identical answers for queries that should vary.
**Why it happens:** Default cache-everything strategy without temperature gating.
**How to avoid:** Default `max_cacheable_temperature=0.0`. Let users opt-in to caching higher temperatures.
**Warning signs:** Users report "the agent always says the same thing."

### Pitfall 2: Cache Key Excluding Tool Definitions
**What goes wrong:** Same prompt with different tool sets returns wrong cached response (e.g., cached response includes tool_calls for tools that are no longer available).
**Why it happens:** Tools omitted from cache key because they "don't change the prompt."
**How to avoid:** Include `tools` parameter in cache key. Tool definitions change model behavior.

### Pitfall 3: Unbounded In-Memory Cache
**What goes wrong:** Memory grows without limit, eventually OOM.
**Why it happens:** Using plain dict instead of bounded cache.
**How to avoid:** Use `TTLCache(maxsize=N)` with explicit bounds. Default 1024 entries.
**Warning signs:** Gradual memory growth in long-running processes.

### Pitfall 4: Serializing raw_response
**What goes wrong:** `raw_response` contains provider-specific objects (httpx.Response, etc.) that fail JSON serialization.
**Why it happens:** Caching the full LLMResponse including `raw_response`.
**How to avoid:** Exclude `raw_response` when serializing for cache. Set it to `None` on cache retrieval.

### Pitfall 5: diskcache in asyncio Without to_thread
**What goes wrong:** Blocking disk I/O stalls the event loop, causing timeouts in concurrent requests.
**Why it happens:** Calling diskcache synchronous methods directly in async code.
**How to avoid:** Always wrap diskcache calls in `asyncio.to_thread()`.

### Pitfall 6: Redis Connection Leak
**What goes wrong:** Connections pile up, Redis hits max client limit, new connections refused.
**Why it happens:** Not calling `aclose()` on shutdown, or creating Redis clients per-request.
**How to avoid:** Singleton Redis client with connection pool. Use `async with` or explicit cleanup in shutdown hooks.

---

## 10. Project Structure

### Recommended Layout

```
src/orchestra/
  cache/
    __init__.py        # Exports CacheBackend, InMemoryCacheBackend, DiskCacheBackend
    backends.py        # CacheBackend protocol + InMemoryCacheBackend + DiskCacheBackend
  memory/
    __init__.py        # Exports MemoryManager, InMemoryMemoryManager
    manager.py         # MemoryManager protocol + InMemoryMemoryManager
  providers/
    cached.py          # CachedProvider wrapper
```

### Why `cache/` and `memory/` are Separate

- **Cache** = transparent performance optimization (same input -> same output, faster)
- **Memory** = semantic state management (what the agent remembers across interactions)
- Different lifecycles: cache entries expire, memories persist
- Different access patterns: cache is key-value lookup, memory is search/retrieval

---

## 11. Dependencies

### Phase 3 (New)

```toml
[project.optional-dependencies]
cache = ["cachetools>=5.5", "diskcache>=5.6"]
```

### Phase 4 (Future)

```toml
[project.optional-dependencies]
redis = ["redis>=5.0"]
vector = ["pgvector>=0.3"]  # or chromadb
```

**Note:** Both `cachetools` and `diskcache` are pure Python with zero transitive dependencies. They add negligible install overhead.

---

## 12. State of the Art

| Old Approach | Current Approach (2025-2026) | Impact |
|-------------|-------------------------------|--------|
| Cache everything | Temperature-gated caching | Prevents stale responses |
| GPTCache (heavy) | Lightweight exact-match + Protocol pattern | Simpler, fewer dependencies |
| aioredis (deprecated) | redis.asyncio (redis-py 7.x) | Single maintained package |
| Fixed similarity thresholds | Adaptive per-category thresholds | Higher F-score for semantic cache |
| Full context window memory | Tiered memory (Mem0/Letta pattern) | 90%+ token cost reduction |
| Manual memory management | LLM-as-OS self-editing memory (Letta) | Agent decides what to remember |

---

## Open Questions

1. **Cache metrics/observability**
   - What we know: Cache hit/miss rates are critical for tuning
   - What's unclear: Should cache emit events to EventBus, or use OTel metrics directly?
   - Recommendation: Add `cache_hit`/`cache_miss` counters. If OTel is ready (task 3.2), use OTel metrics. Otherwise, structlog.

2. **Multi-tenant cache isolation**
   - What we know: Shared cache could leak responses across tenants
   - What's unclear: Orchestra doesn't have a tenant model yet
   - Recommendation: Add optional `namespace` parameter to CacheBackend. Default to no namespace (single-tenant).

3. **Streaming response caching**
   - What we know: `CachedProvider.stream()` currently delegates directly (no caching)
   - What's unclear: Should we buffer streamed responses and cache the complete result?
   - Recommendation: Defer. Streaming caching adds complexity (buffering, incomplete responses). Cache only `complete()` for Phase 3.

---

## Sources

### Primary (HIGH confidence)
- [cachetools PyPI](https://pypi.org/project/cachetools/) - v7.0.3, TTLCache API
- [diskcache PyPI](https://pypi.org/project/diskcache/) - v5.6.3, Cache API, async limitations
- [redis-py docs](https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html) - redis.asyncio patterns
- [LangChain caching docs](https://python.langchain.com/docs/how_to/llm_caching/) - Cache types, key design

### Secondary (MEDIUM confidence)
- [GPTCache architecture](https://gptcache.readthedocs.io/) - Semantic caching design
- [Mem0 research](https://arxiv.org/abs/2504.19413) - Memory layer architecture, 26% accuracy improvement
- [MemGPT/Letta docs](https://docs.letta.com/concepts/memgpt/) - Tiered memory (Core/Recall/Archival)
- [pgvector vs ChromaDB comparison](https://blog.elest.io/pgvector-vs-chromadb-when-to-extend-postgresql-and-when-to-go-dedicated/) - Vector store tradeoffs
- [Redis pub/sub vs PostgreSQL](https://dev.to/polliog/i-replaced-redis-with-postgresql-and-its-faster-4942) - Event messaging comparison

### Tertiary (LOW confidence)
- [Semantic cache similarity thresholds](https://arxiv.org/html/2411.05276v2) - Threshold tuning research (workload-specific)
- [ToolCaching framework](https://arxiv.org/html/2601.15335) - RL-based cache admission (cutting-edge, unproven)
- [Semantic cache key collision attacks](https://arxiv.org/html/2601.23088v1) - Security considerations

---

## Metadata

**Confidence breakdown:**
- Standard stack (cachetools, diskcache): HIGH -- mature libraries, well-documented, widely used
- CachedProvider architecture: HIGH -- proven pattern across LangChain, Instructor, GPTCache
- Cache key design (SHA-256): HIGH -- industry standard, no known issues
- MemoryManager protocol: MEDIUM -- interface based on Mem0/Letta patterns, but optimal semantics TBD
- Semantic caching: MEDIUM -- well-researched but threshold tuning is empirical
- Redis patterns: HIGH -- redis-py 7.x is canonical, well-documented
- Vector store selection: MEDIUM -- pgvector recommended but depends on Phase 4 requirements

**Research date:** 2026-03-10
**Valid until:** 2026-04-10 (stable libraries, slow-moving domain)
