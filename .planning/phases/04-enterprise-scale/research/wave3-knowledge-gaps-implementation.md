# Wave 3 Implementation Knowledge Gaps Research

**Researched:** 2026-03-12
**Domain:** Redis L2 caching, tiered memory (SLRU), pgvector HNSW cold tier, semantic deduplication, state compression, PromptShield output scanning
**Confidence:** MEDIUM (library APIs verified; some integration patterns need validation during implementation)
**Tasks covered:** T-4.8 (Redis L2 + Promote/Demote), T-4.9 (HSM 3-Tier + pgvector), T-4.10 (PromptShield Output Scanning + Attenuation)

---

## Summary

Wave 3 adds three capabilities: distributed tiered memory (T-4.8/T-4.9) and post-execution security scanning (T-4.10). The existing codebase has minimal foundations: `MemoryManager` is a 35-line protocol with only `store`/`retrieve`, `CacheBackend` is a separate protocol typed to `LLMResponse`, and the security module has guardrail infrastructure but no SLM-based detection. The plan assumes several things that need adjustment: the `redis[hiredis]>=7.0` version pin is incorrect (redis-py is at 7.3.0 and the extras syntax is `redis[hiredis]`), model2vec's version pin `>=0.3` needs updating to `>=0.7`, and the plan's `pyzstd>=0.17` should be changed to `>=0.19` (or better, use stdlib `compression.zstd` since Orchestra requires Python 3.11+, though `compression.zstd` is only in Python 3.14+).

**Primary recommendation:** Before implementing T-4.8, extend the `MemoryManager` protocol to support tier metadata and access tracking. The current protocol has no `delete`, `list_keys`, TTL, or tier concept. The `CacheBackend` protocol is separate and typed to `LLMResponse` -- it should NOT be used as the Redis L2 backend for memory; a new `MemoryBackend` protocol is needed that works with `Any` values. T-4.9's dependency on T-4.8 is a HARD dependency for the TieredMemoryManager, but the pgvector `VectorStore`, `SemanticDeduplicator`, and `StateCompressor` can be built in parallel since they are independent modules that plug into the cold tier. T-4.10 is fully independent and can be developed concurrently with T-4.8/T-4.9.

---

## 1. What Exists Today (Codebase Audit)

### 1.1 MemoryManager (`src/orchestra/memory/manager.py`, lines 1-35)

```python
@runtime_checkable
class MemoryManager(Protocol):
    async def store(self, key: str, value: Any) -> None: ...
    async def retrieve(self, key: str) -> Any | None: ...
```

**Critical observations:**
- Only 2 methods: `store` and `retrieve`. No `delete`, `list_keys`, `exists`, `clear`, or TTL support.
- Values are `Any` -- no serialization constraint, no size tracking, no metadata.
- No concept of tiers, access counting, or timestamps.
- The `InMemoryMemoryManager` is a plain dict wrapper (lines 21-34).
- **Not registered in `ExecutionContext`** -- the context has a comment "Phase 2+ adds: memory" (context.py line 19) but no `memory_manager` field exists.
- Only 3 unit tests (test_memory.py) -- store/retrieve, retrieve-none, overwrite.

**Gap for T-4.8:** The protocol must be extended (new methods, not breaking change) or a new `TieredMemoryManager` must be built as a separate class that composes multiple backends. Recommend the latter to avoid breaking existing code.

### 1.2 CacheBackend (`src/orchestra/cache/backends.py`, lines 1-108)

```python
@runtime_checkable
class CacheBackend(Protocol):
    async def get(self, key: str) -> LLMResponse | None: ...
    async def set(self, key: str, value: LLMResponse, ttl: int | None = None) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def clear(self) -> None: ...
```

**Critical observations:**
- **Typed to `LLMResponse`** -- cannot be used for general memory storage. The Redis L2 cache for memory tiers needs to store arbitrary `Any` values, not just LLM responses.
- Two implementations: `InMemoryCacheBackend` (cachetools TTLCache) and `DiskCacheBackend` (diskcache).
- `CachedProvider` (src/orchestra/providers/cached.py) uses `CacheBackend` to wrap LLM providers.
- TTL support exists in protocol but `InMemoryCacheBackend` ignores per-item TTL (line 57-58 comment: "Per-item TTL is not supported natively by TTLCache").

**Gap for T-4.8:** The plan says "create `src/orchestra/cache/redis_backend.py`" implementing Redis L2. But if this implements `CacheBackend`, it can only cache `LLMResponse` objects. The TieredMemoryManager needs a different protocol. Recommend creating a `MemoryBackend` protocol in `src/orchestra/memory/backends.py` that mirrors `CacheBackend` but uses `Any` values with serialization.

### 1.3 Security Module (`src/orchestra/security/`)

**Guardrails infrastructure (guardrails.py, 564 lines):**
- `Guardrail` protocol with `validate(text) -> GuardrailResult`
- `GuardrailChain` runs validators sequentially with `OnFail` actions (BLOCK, FIX, LOG, RETRY, EXCEPTION)
- `GuardedAgent` subclass with `input_guardrails` and `output_guardrails` chains + retry logic
- Built-in validators: `ContentFilter`, `PIIDetector`, `SchemaValidator`

**Extended validators (validators.py, 261 lines):**
- `PIIRedactionGuardrail` with Presidio integration (optional) + regex fallback
- `MaxLengthGuardrail`, `RegexGuardrail`

**Prompt injection (rebuff.py, 658 lines):**
- Full Rebuff integration: `RebuffChecker`, `PromptInjectionAgent`, `InjectionAuditorAgent`
- Depends on external `rebuff` package + Pinecone + OpenAI (heavy infra)
- **Not usable for T-4.10** -- Rebuff is input-scanning only (pre-execution), not output-scanning

**ACL (acl.py, 73 lines):**
- `ToolACL` with allow/deny lists and glob patterns
- `UnauthorizedToolError` for unauthorized tool calls

**Circuit breaker (circuit_breaker.py, 185 lines):**
- `AsyncCircuitBreaker` with CLOSED/OPEN/HALF_OPEN states

**Gap for T-4.10:**
- The `GuardrailChain` + `GuardedAgent` architecture is the RIGHT integration point for output scanning. T-4.10's `OutputScanner` should implement the `Guardrail` protocol.
- The `Attenuator` (capability reduction) needs to modify `ToolACL` dynamically. Currently `ToolACL` is a frozen dataclass (line 14: `@dataclass(frozen=True)`). The attenuator will need to create a new restricted ACL and inject it, not mutate the existing one.
- Rebuff is a dead end for T-4.10 -- it requires Pinecone and OpenAI API keys. T-4.10 should use local SLM models (Sentinel/PromptGuard).

### 1.4 Storage Layer (`src/orchestra/storage/`)

**Relevant for T-4.9 (pgvector cold tier):**
- `PostgresEventStore` (postgres.py, 577 lines) already uses `asyncpg` and connection pooling
- DDL statements create tables with JSONB columns -- good pattern to follow for vector storage
- The pgvector extension would be added to the same PostgreSQL instance
- Pool configuration: min_size=4, max_size=20

**Gap:** The cold tier vector store is a new table, not part of the event store. It should share the asyncpg pool but have its own DDL and queries. The plan correctly places this in `src/orchestra/memory/vector_store.py`, separate from the event store.

### 1.5 Existing Dependencies (pyproject.toml)

Relevant current deps:
- `pydantic>=2.5` (core)
- `httpx>=0.26` (core)
- `structlog>=24.0` (logging)
- `cachetools>=5.5` (cache extra)
- `asyncpg>=0.29` (postgres extra)
- `numpy>=1.26` (routing extra)
- `wasmtime>=23.0` (security extra)

Missing deps needed for Wave 3:
- `redis[hiredis]` -- not in any extra
- `pgvector` -- not in any extra
- `model2vec` -- not in any extra
- `pyzstd` -- not in any extra (or stdlib `compression.zstd` for Python 3.14+)
- `msgpack` -- not in any extra
- `transformers` -- not in any extra
- `onnxruntime` -- not in any extra

---

## 2. Library Version Corrections

The PLAN.md specifies library versions that need updating based on current PyPI state.

### 2.1 T-4.8 Dependencies

| Plan Says | Actual Latest | Correction |
|-----------|---------------|------------|
| `redis[hiredis]>=7.0` | redis 7.3.0 (Mar 6, 2026), hiredis-py 3.2.0 | Change to `redis[hiredis]>=7.1`. The plan pin `>=7.0` is valid but conservative. redis 7.0 never existed on PyPI; major version started at 7.1.0. |
| `msgpack>=1.0` | msgpack 1.1.2 (Oct 8, 2025) | Pin is fine. msgpack is stable. |

### 2.2 T-4.9 Dependencies

| Plan Says | Actual Latest | Correction |
|-----------|---------------|------------|
| `pgvector>=0.3` | pgvector 0.4.2 (Dec 5, 2025) | Change to `pgvector>=0.4` for asyncpg HNSW support. 0.3.x had limited asyncpg helpers. |
| `pyzstd>=0.17` | pyzstd 0.19.1 (Dec 13, 2025) | Change to `pyzstd>=0.19`. Note: pyzstd 0.19+ internally uses stdlib `compression.zstd` (PEP 784, Python 3.14). For Python 3.11-3.13, pyzstd bundles its own zstd. |
| `model2vec>=0.3` | model2vec 0.7.0 (Oct 5, 2025) | **Major correction:** Change to `model2vec>=0.7`. The API changed significantly between 0.3 and 0.7 (StaticModel class, new model names). |

### 2.3 T-4.10 Dependencies

| Plan Says | Actual Latest | Correction |
|-----------|---------------|------------|
| `transformers>=4.40` | transformers ~4.50+ (2026) | Pin is reasonable floor. |
| `onnxruntime>=1.18` | onnxruntime ~1.21+ (2026) | Pin is reasonable floor. |

**New dependency consideration:** The plan references Sentinel (qualifire) but there are now TWO versions:
- **Sentinel v1**: ModernBERT-large (~355M params), accuracy 0.987, F1 0.980, 8K context
- **Sentinel v2**: Qwen3-0.6B (~600M params), F1 0.964, 32K context, 3x training data, 1.2GB model

Recommendation: Use Sentinel v1 (ModernBERT-large) for production -- it is smaller, faster, and has higher accuracy. Sentinel v2's larger context is unnecessary for output scanning where individual outputs are typically <4K tokens.

---

## 3. Architecture Analysis: Interface Mismatches

### 3.1 CRITICAL: MemoryManager vs CacheBackend Protocol Split

The plan conflates two separate concerns:

1. **Memory tiers** (T-4.8 TieredMemoryManager): Stores agent working memory across HOT/WARM/COLD. Values are `Any`. Keys are session-scoped. Need promote/demote lifecycle.

2. **LLM response cache** (existing CacheBackend): Caches deterministic LLM call results. Values are `LLMResponse`. Keys are hash-based. No tiering needed.

**The plan says:** "Create `src/orchestra/cache/redis_backend.py` -- redis.asyncio backend"

**Problem:** If `redis_backend.py` implements `CacheBackend`, it stores `LLMResponse` objects. But `TieredMemoryManager` needs to store arbitrary values. These are different use cases.

**Recommended fix:** Create TWO Redis integrations:
1. `src/orchestra/cache/redis_backend.py` -- implements `CacheBackend` for LLM response caching (typed to `LLMResponse`)
2. `src/orchestra/memory/backends.py` -- new `MemoryBackend` protocol + `RedisMemoryBackend` for tier storage (typed to `Any`, uses msgpack serialization)

### 3.2 TieredMemoryManager Protocol Design

The plan says the `TieredMemoryManager` should be at `src/orchestra/memory/tiers.py`. It needs to:
- Implement the existing `MemoryManager` protocol (backward compat for `store`/`retrieve`)
- Add tier-aware methods: `promote(key, to_tier)`, `demote(key, to_tier)`
- Track access statistics per key for SLRU decisions
- Run background asyncio task for periodic SLRU scans

**Key design question:** Should `TieredMemoryManager` be a drop-in replacement for `InMemoryMemoryManager`?

**Recommendation: Yes.** Make it satisfy the `MemoryManager` protocol. `store()` writes to HOT tier by default. `retrieve()` reads from HOT first, then WARM, then COLD (with automatic promotion on re-access). New tier-specific methods are additive.

### 3.3 PromptShield Integration with Guardrail Protocol

The plan puts output scanning in `src/orchestra/security/output_scanner.py` and capability attenuation in `src/orchestra/security/attenuator.py`.

**Integration point:** `OutputScanner` should implement the `Guardrail` protocol:
```
class OutputScanner:
    name = "output_scanner"
    on_fail = OnFail.BLOCK  # or OnFail.FIX for sanitization

    async def validate(self, text: str, **kwargs) -> GuardrailResult:
        # Run SLM classifier on text
        # Return passed=False with violations if injection detected
```

This lets it plug directly into `GuardedAgent.output_guardrails` chain without any new wiring.

**Attenuator integration:** The `Attenuator` cannot modify a frozen `ToolACL` directly. Instead:
1. When `OutputScanner` detects an injection, it sets a flag in the `GuardrailResult`
2. The agent loop (or a wrapper) checks this flag and creates a new restricted `ToolACL`
3. The restricted ACL is injected into `ExecutionContext` for subsequent tool calls

**Problem with frozen ToolACL:** `ToolACL` is `@dataclass(frozen=True)`. The attenuator must create a NEW `ToolACL` instance, not modify the existing one. This is fine -- just construct `ToolACL(allowed_tools=set(), allow_all=False)` for full restriction or `ToolACL.deny_list({"web_search", "file_write", ...})` for selective restriction.

---

## 4. Dependency Chain Analysis (T-4.8 -> T-4.9)

### Hard Dependencies

| T-4.9 Component | Depends on T-4.8? | Reason |
|------------------|--------------------|--------|
| `TieredMemoryManager` COLD tier integration | YES (HARD) | Cold tier is a tier within TieredMemoryManager. Without HOT/WARM tiers existing, cold tier has no lifecycle. |
| `VectorStore` (pgvector HNSW) | NO | Independent module. Can be built and tested standalone against PostgreSQL. |
| `SemanticDeduplicator` | NO | Takes embeddings + similarity threshold, returns dedup decisions. Independent of memory tiers. |
| `StateCompressor` (zstd + msgpack) | NO | Pure data transformation. No dependencies on memory infrastructure. |

### Recommended Parallelization

```
Week 23:
  [T-4.8] Redis L2 + SLRU TieredMemoryManager (HOT/WARM)
  [T-4.9-parallel] VectorStore, SemanticDeduplicator, StateCompressor (independent modules)
  [T-4.10] PromptShield OutputScanner + Attenuator (fully independent)

Week 24:
  [T-4.9-integration] Wire VectorStore as COLD tier into TieredMemoryManager
  [T-4.9-integration] Wire SemanticDeduplicator into WARM->COLD demotion path
  [T-4.9-integration] Wire StateCompressor into COLD tier serialization
  [T-4.10] Integration tests, GuardedAgent wiring
```

This means T-4.9 components can start in Week 23, with only the final integration requiring T-4.8 completion.

---

## 5. Technical Deep Dives

### 5.1 Redis L2 Cache Pattern (T-4.8)

**Architecture: Write-Through with Pub/Sub Invalidation**

```
Instance A                    Redis                     Instance B
-----------                   -----                     -----------
store(k, v)
  -> L1 write                -> SET k, msgpack(v), EX ttl
                              -> PUBLISH orchestra:mem:inv k
                                                        <- SUBSCRIBE
                                                        <- DEL L1[k]
retrieve(k)
  -> L1 check (hit? done)
  -> GET k from Redis
  -> L1 backfill
```

**Key technical details:**
- `redis.asyncio` does NOT support CLIENT TRACKING (redis/redis-py#3916). Must use manual Pub/Sub for invalidation.
- Pub/Sub is best-effort (fire-and-forget). Safety net: L1 TTLs of 30-60 seconds.
- Use `hiredis` parser for 2-5x faster response parsing.
- Serialization: msgpack for values (30-50% smaller than JSON, 3-5x faster).
- Connection: Use `redis.asyncio.ConnectionPool` with `max_connections`.

**Performance targets from plan:** "L2 < 2ms". This is achievable -- typical redis.asyncio GET latency is 0.5-2ms with hiredis parser on same-network Redis.

**Stampede prevention:** When L1 and L2 both miss, multiple concurrent requests for the same key can stampede the backend. Use a per-key asyncio.Lock or "singleflight" pattern to coalesce concurrent requests.

### 5.2 SLRU Promotion/Demotion (T-4.8)

**Algorithm:**

SLRU divides items into probationary (WARM) and protected (HOT) segments.
- New items enter WARM (probationary)
- On re-access, items promote to HOT (protected)
- When HOT is full, LRU item in HOT demotes to MRU end of WARM
- When WARM is full, LRU item in WARM demotes to COLD (or evicts)

**No existing Python SLRU library.** Must be built custom (~150-200 lines).

**Implementation approach:**
```python
@dataclass
class MemoryEntry:
    key: str
    value: Any
    tier: Tier  # HOT, WARM, COLD
    access_count: int = 0
    last_accessed: float = 0.0
    created_at: float = 0.0
    size_bytes: int = 0

class SLRUPolicy:
    def __init__(self, hot_max: int, warm_max: int):
        self._hot = OrderedDict()   # key -> MemoryEntry
        self._warm = OrderedDict()  # key -> MemoryEntry

    def access(self, key: str) -> Tier | None:
        """Record access, return new tier if promotion occurred."""
        if key in self._hot:
            self._hot.move_to_end(key)
            return None  # already in hot
        if key in self._warm:
            entry = self._warm.pop(key)
            entry.access_count += 1
            # Promote to HOT
            self._hot[key] = entry
            self._hot.move_to_end(key)
            self._maybe_evict_hot()
            return Tier.HOT
        return None  # not tracked
```

**Background task:** An `asyncio.create_task` that runs every 60 seconds, scanning for items that haven't been accessed within their tier's TTL window and demoting them.

### 5.3 pgvector HNSW Cold Tier (T-4.9)

**Setup with asyncpg:**
```python
from pgvector.asyncpg import register_vector

async def init_pool(conn):
    await register_vector(conn)

pool = await asyncpg.create_pool(dsn, init=init_pool)

# DDL
await conn.execute("""
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE TABLE IF NOT EXISTS memory_cold (
        id BIGSERIAL PRIMARY KEY,
        key TEXT NOT NULL UNIQUE,
        embedding vector(256),
        content JSONB NOT NULL,
        compressed_value BYTEA,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        access_count INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_cold_embedding_hnsw
        ON memory_cold USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 200);
    CREATE INDEX IF NOT EXISTS idx_cold_key ON memory_cold(key);
""")
```

**HNSW tuning:**
- `m=16` (graph connectivity) -- default, good for <1M vectors
- `ef_construction=200` (build-time accuracy) -- higher = better recall, slower build
- `ef_search=100` (query-time accuracy) -- set via `SET hnsw.ef_search = 100`
- Expected: >95% recall, sub-10ms at 1M vectors

**Hybrid retrieval (semantic + keyword):**
The plan mentions "hybrid retrieval" but does not specify how. Recommend:
1. Semantic: `ORDER BY embedding <-> $1 LIMIT k` (cosine distance)
2. Keyword: PostgreSQL full-text search with `tsvector`/`tsquery`
3. Fusion: Reciprocal Rank Fusion (RRF) to merge results

**Embedding dimensions:** model2vec potion-base-32M outputs 256-dimensional embeddings (distilled from bge-base-en-v1.5's 768d). The pgvector column should be `vector(256)`.

### 5.4 model2vec Embeddings (T-4.9)

**API (verified from GitHub, model2vec 0.7.0):**
```python
from model2vec import StaticModel

model = StaticModel.from_pretrained("minishlab/potion-base-32M")
embeddings = model.encode(["text1", "text2"])  # returns numpy array
```

**Key facts:**
- Model size: ~32MB (vs ~90MB for all-MiniLM-L6-v2)
- Inference: CPU-only, very fast (~500x faster than sentence-transformers)
- No async support -- must use `asyncio.to_thread(model.encode, texts)`
- Available models: potion-base-32M (256d), potion-base-8M, potion-base-4M, potion-base-2M, potion-retrieval-32M (optimized for retrieval), potion-multilingual-128M (101 languages)

**Recommendation:** Use `potion-retrieval-32M` for the cold tier (retrieval-optimized). Use `potion-base-8M` for the SemanticDeduplicator (speed over quality since we only need 0.98 threshold).

### 5.5 SemanticDeduplicator Design (T-4.9)

**Threshold table (from existing research 04-memory-data-caching.md):**

| Cosine Similarity | Classification | Action |
|-------------------|---------------|--------|
| >= 0.98 | Duplicate | Drop new entry |
| >= 0.85, < 0.98 | Similar | Flag for review/merge |
| < 0.85 | Distinct | Store as new |

**Implementation:**
```python
class SemanticDeduplicator:
    def __init__(self, model: StaticModel, threshold: float = 0.98):
        self._model = model
        self._threshold = threshold

    async def is_duplicate(self, text: str, pool: asyncpg.Pool) -> tuple[bool, str | None]:
        """Check if text is a semantic duplicate of existing cold-tier entries.
        Returns (is_dup, existing_key)."""
        embedding = await asyncio.to_thread(self._model.encode, [text])
        # Query pgvector for nearest neighbor
        row = await pool.fetchrow(
            "SELECT key, 1 - (embedding <-> $1) AS similarity FROM memory_cold "
            "ORDER BY embedding <-> $1 LIMIT 1",
            embedding[0].tolist()
        )
        if row and row["similarity"] >= self._threshold:
            return True, row["key"]
        return False, None
```

**Note on operator:** `<->` is L2 distance in pgvector. For cosine similarity, use `<=>` operator and index with `vector_cosine_ops`.

### 5.6 StateCompressor Design (T-4.9)

**Implementation (straightforward):**
```python
import msgpack
import pyzstd

class StateCompressor:
    def __init__(self, zstd_level: int = 3):
        self._level = zstd_level

    def compress(self, value: Any) -> bytes:
        packed = msgpack.packb(value, use_bin_type=True)
        return pyzstd.compress(packed, self._level)

    def decompress(self, data: bytes) -> Any:
        decompressed = pyzstd.decompress(data)
        return msgpack.unpackb(decompressed, raw=False)
```

**Expected compression (msgpack + zstd level 3):**
- 1 KB state -> ~400 bytes (60% reduction)
- 10 KB state -> ~2.5 KB (75% reduction)
- 100 KB state -> ~20 KB (80% reduction)

**Async wrapping:** Both msgpack and pyzstd are CPU-bound but very fast (<1ms for <100KB). No need for `asyncio.to_thread` unless processing very large states (>1MB).

### 5.7 PromptShield SLM Models (T-4.10)

**Model comparison (updated):**

| Model | Architecture | Size | F1 | Context | License | Inference |
|-------|-------------|------|----|---------|---------| ---------|
| **Sentinel v1** | ModernBERT-large | ~355M / 1.6GB | 0.980 | 8K | Open | <20ms GPU, <100ms CPU |
| **Sentinel v2** | Qwen3-0.6B | ~600M / 1.2GB | 0.964 | 32K | Open | Slower (generative) |
| **PromptGuard 2 86M** | mDeBERTa-v3-base | 86M / ~350MB | High | Standard | Meta Community | 5-10ms CPU |
| **DeBERTa-v3-small Injection v2** | DeBERTa-v3-small | ~44M / ~175MB | Good | Standard | Apache 2.0 | <5ms CPU |

**Recommendation for T-4.10:**
1. **Primary:** Sentinel v1 (ModernBERT-large) -- highest F1, reasonable size
2. **Fast fallback:** DeBERTa-v3-small-injection-v2 -- smallest, Apache 2.0, English-only
3. **Do NOT use** Sentinel v2 -- it is a generative model (Qwen3), much slower for classification, and has lower F1

**ONNX optimization:** Export Sentinel v1 to ONNX for 2-4x CPU speedup:
```python
from optimum.onnxruntime import ORTModelForSequenceClassification
model = ORTModelForSequenceClassification.from_pretrained(
    "qualifire/prompt-injection-sentinel", export=True
)
```

**Parallel execution pattern (zero added latency):**
```python
async def guarded_execution(prompt, agent):
    guard_task = asyncio.create_task(output_scanner.scan(prompt))  # ~10-50ms
    llm_task = asyncio.create_task(agent.call_llm(prompt))         # ~500-3000ms
    guard_result = await guard_task
    if guard_result.is_injection:
        llm_task.cancel()
        return apply_attenuation(agent)
    return await llm_task
```

This pattern is for INPUT scanning. For OUTPUT scanning (T-4.10's primary focus), the pattern is:
1. Execute agent normally
2. Scan the output with SLM
3. If injection detected in output, block the result + attenuate agent capabilities

---

## 6. Unrealistic Assumptions and Flags

### 6.1 "L2 <2ms" Target

**Assessment: ACHIEVABLE but conditional.**
- redis.asyncio with hiredis: 0.5-2ms for GET on same-network Redis
- Add serialization overhead: ~0.1ms for msgpack
- Add network latency: 0.1-0.5ms (same AZ)
- Total: 0.7-2.6ms
- **Risk:** If Redis is cross-AZ or under load, latency exceeds 2ms. This is a p50 target, not a p99 guarantee.

### 6.2 "90% top-10 accuracy" for Cold Tier Retrieval

**Assessment: ACHIEVABLE with correct HNSW tuning.**
- pgvector HNSW with m=16, ef_search=100 achieves >95% recall at 1M vectors
- model2vec embeddings are competitive with MiniLM for retrieval tasks
- **Risk:** Accuracy depends heavily on the quality of the embedding model and the similarity of stored memories. On heterogeneous agent state data, recall may be lower.

### 6.3 Sentinel Model Download Size

**Flag:** The plan does not account for model download/caching strategy.
- Sentinel v1: ~1.6GB download from HuggingFace
- ONNX-exported: ~800MB-1GB
- PromptGuard 2 86M: ~350MB
- DeBERTa injection v2: ~175MB

**Recommendation:** Ship the ONNX-exported DeBERTa-v3-small as the default (smallest, Apache 2.0). Allow Sentinel v1 as an optional upgrade. Add a `MODEL_CACHE_DIR` env var for deployment.

### 6.4 Missing: How TieredMemoryManager Connects to ExecutionContext

The plan does not specify how `TieredMemoryManager` gets injected into agents. Currently, `ExecutionContext` has no `memory_manager` field. Options:

1. Add `memory_manager: Any = None` to `ExecutionContext` dataclass
2. Use `config["memory_manager"]` (loose coupling)
3. Create a new `EnterpriseContext` that extends `ExecutionContext`

**Recommendation:** Option 1 (add field). It is the simplest, matches the existing pattern (`provider: Any = None`), and the comment on line 19 already anticipates it.

### 6.5 Missing: Redis Connection Configuration

The plan does not specify how Redis connection parameters are configured. Recommend following the same pattern as `PostgresEventStore`:
- Constructor accepts `url: str | None` with fallback to `REDIS_URL` env var
- Connection pool with configurable min/max connections
- `initialize()` / `close()` lifecycle methods
- Async context manager support

---

## 7. Common Pitfalls

### Pitfall 1: Pub/Sub Message Loss During Reconnection
**What goes wrong:** If a Redis subscriber disconnects momentarily, all invalidation messages during that period are lost, leading to stale L1 caches.
**How to avoid:** Short L1 TTLs (30-60s) as safety net. On reconnect, flush all L1 entries or use a generation counter.

### Pitfall 2: msgpack Serialization of Custom Objects
**What goes wrong:** msgpack cannot serialize Pydantic models or custom classes directly. Attempting to store an `AgentResult` in the memory tier will fail.
**How to avoid:** Serialize to dict first (`model.model_dump()` for Pydantic, or a custom `to_dict`/`from_dict` protocol). Define a clear serialization contract for memory entries.

### Pitfall 3: pgvector Dimension Mismatch
**What goes wrong:** If model2vec embedding dimensions change between model versions (e.g., upgrading from potion-base-8M to potion-base-32M), the pgvector column dimension becomes incompatible.
**How to avoid:** Store the model name and dimensionality in a metadata table. On startup, validate that the configured model matches the stored dimension. Provide a migration path for re-embedding.

### Pitfall 4: ONNX Runtime Conflicts with PyTorch
**What goes wrong:** If `torch` and `onnxruntime` are both installed, there can be symbol conflicts on Linux with CUDA. Also, `transformers` defaults to PyTorch even when ONNX model is available.
**How to avoid:** Use `optimum-onnx` (not raw `onnxruntime`), which handles the backend selection. For CPU-only deployment, install `onnxruntime` without `onnxruntime-gpu`.

### Pitfall 5: asyncio.to_thread Contention for model2vec
**What goes wrong:** model2vec.encode() acquires the GIL for numpy operations. If many concurrent requests call `asyncio.to_thread(model.encode, ...)`, they serialize on the GIL and block the thread pool.
**How to avoid:** Batch embeddings. Collect pending embedding requests over a short window (e.g., 10ms) and batch them into a single `model.encode()` call. This is especially important for the SemanticDeduplicator.

### Pitfall 6: Frozen ToolACL and Dynamic Attenuation
**What goes wrong:** Trying to modify `ToolACL` in place fails because it is `@dataclass(frozen=True)`.
**How to avoid:** The attenuator creates a new `ToolACL` instance with restricted permissions. This new ACL replaces the current one on the agent/context for the remainder of the execution.

---

## 8. Recommended Plan Changes

### 8.1 T-4.8 Changes

1. **Split Redis backend creation:**
   - `src/orchestra/cache/redis_backend.py` -- `RedisCacheBackend` implementing `CacheBackend` (for LLM response caching)
   - `src/orchestra/memory/backends.py` -- `RedisMemoryBackend` for tier storage (new `MemoryBackend` protocol using `Any` values + msgpack serialization)

2. **Add `MemoryBackend` protocol** to `src/orchestra/memory/backends.py`:
   ```python
   @runtime_checkable
   class MemoryBackend(Protocol):
       async def get(self, key: str) -> Any | None: ...
       async def set(self, key: str, value: Any, ttl: int | None = None) -> None: ...
       async def delete(self, key: str) -> None: ...
       async def exists(self, key: str) -> bool: ...
       async def keys(self, pattern: str = "*") -> list[str]: ...
   ```

3. **Add `memory_manager` field to `ExecutionContext`** (context.py):
   ```python
   memory_manager: Any = None  # MemoryManager or TieredMemoryManager
   ```

4. **Correct version pin:** `redis[hiredis]>=7.1` (not `>=7.0`)

### 8.2 T-4.9 Changes

1. **Correct version pins:**
   - `pgvector>=0.4` (not `>=0.3`)
   - `model2vec>=0.7` (not `>=0.3`)
   - `pyzstd>=0.19` (not `>=0.17`)

2. **Share asyncpg pool with PostgresEventStore:** If both event store and vector store use the same PostgreSQL instance, share the connection pool. Add an initialization option to `VectorStore` that accepts an existing pool.

3. **Use `potion-retrieval-32M`** for cold tier retrieval (not generic potion-base). Use `potion-base-8M` for dedup (speed-optimized).

4. **pgvector column dimension:** `vector(256)` for potion models, not 384 or 768.

5. **Use `<=>` cosine distance operator** (not `<->` which is L2) for semantic similarity queries. Index with `vector_cosine_ops`.

### 8.3 T-4.10 Changes

1. **Implement `OutputScanner` as a `Guardrail`** -- this lets it plug into `GuardedAgent.output_guardrails` without new infrastructure.

2. **Default to DeBERTa-v3-small-injection-v2** (44M, Apache 2.0) as the built-in model. Sentinel v1 as optional upgrade.

3. **Do NOT use Sentinel v2** (Qwen3-0.6B) -- it is a generative model, slower and lower F1 than v1.

4. **Attenuator creates new ToolACL, does not mutate** -- the plan's "dynamic capability reduction" must work with the frozen ToolACL design by constructing a new restricted ACL.

5. **Add `restricted_mode` field to ExecutionContext** or a capability attenuation state dict, so downstream code can check if the agent is in restricted mode.

### 8.4 pyproject.toml Changes

Add new optional dependency groups:

```toml
[project.optional-dependencies]
memory = [
    "redis[hiredis]>=7.1",
    "msgpack>=1.0",
]
vectordb = [
    "pgvector>=0.4",
    "model2vec>=0.7",
    "pyzstd>=0.19",
]
promptshield = [
    "transformers>=4.40",
    "onnxruntime>=1.18",
    "optimum-onnx>=1.0",
]
```

---

## 9. Open Questions

### Q1: Redis Cluster vs Standalone
**What we know:** The plan says "distributed instances" for L2. Redis Cluster and Redis Standalone with replicas are different deployment models.
**What's unclear:** Does Orchestra target Redis Cluster (sharded) or Redis Standalone with Pub/Sub (simpler)?
**Recommendation:** Start with Redis Standalone. The `redis.asyncio` client supports both, but Cluster mode adds complexity (hash slots, cross-slot operations). For Wave 3, Standalone is sufficient. Cluster support can be added later by swapping `Redis()` for `RedisCluster()`.

### Q2: Cold Tier Lifecycle -- When Does Data Move to Cold?
**What we know:** The plan says WARM->COLD demotion but does not specify the trigger.
**What's unclear:** Time-based (TTL expiry)? Access-based (0 accesses in N seconds)? Size-based (WARM exceeds capacity)?
**Recommendation:** Dual trigger: `(warm_ttl_expired AND access_count == 0 in last 5 minutes) OR warm_size > max_warm_size`. Configurable via constructor parameters.

### Q3: Model Download Strategy for PromptShield
**What we know:** Models are 175MB-1.6GB on HuggingFace.
**What's unclear:** Download at install time? First use? Docker layer?
**Recommendation:** Lazy download on first use (HuggingFace `cached_download`), with optional `orchestra promptshield download` CLI command for pre-warming. For Docker, pre-download in the image build step.

### Q4: How Does Attenuator Reset After Restricted Mode?
**What we know:** The plan says "dynamic capability reduction" but not how/when capabilities are restored.
**What's unclear:** Is restriction permanent for the execution? Time-limited? Requires human approval?
**Recommendation:** Restricted mode persists for the current run. The agent must be re-instantiated (or the run restarted) to regain full capabilities. This prevents an attacker from "waiting out" the restriction.

---

## 10. Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `python -m pytest tests/unit/ -x -q` |
| Full suite command | `python -m pytest tests/ --tb=short` |

### Phase Requirements to Test Map

| Req | Behavior | Test Type | Automated Command | Exists? |
|-----|----------|-----------|-------------------|---------|
| T-4.8-1 | Redis L2 GET/SET with TTL | unit (mock Redis) | `pytest tests/unit/test_memory_tiers.py -x` | No (Wave 0) |
| T-4.8-2 | SLRU promotion on re-access | unit | `pytest tests/unit/test_memory_tiers.py::test_slru_promotion -x` | No (Wave 0) |
| T-4.8-3 | SLRU demotion on inactivity | unit | `pytest tests/unit/test_memory_tiers.py::test_slru_demotion -x` | No (Wave 0) |
| T-4.8-4 | Pub/Sub invalidation across instances | integration (requires Redis) | `pytest tests/integration/test_redis_memory.py -x -m integration` | No (Wave 0) |
| T-4.8-5 | TieredMemoryManager backward compat | unit | `pytest tests/unit/test_memory_tiers.py::test_protocol_compat -x` | No (Wave 0) |
| T-4.9-1 | pgvector HNSW nearest neighbor | integration (requires Postgres+pgvector) | `pytest tests/integration/test_vector_store.py -x -m integration` | No (Wave 0) |
| T-4.9-2 | SemanticDeduplicator at 0.98 threshold | unit (mock embeddings) | `pytest tests/unit/test_vector_store.py::test_dedup -x` | No (Wave 0) |
| T-4.9-3 | StateCompressor round-trip | unit | `pytest tests/unit/test_vector_store.py::test_compression -x` | No (Wave 0) |
| T-4.9-4 | Cold tier retrieval accuracy | integration | `pytest tests/integration/test_vector_store.py::test_recall -x -m integration` | No (Wave 0) |
| T-4.10-1 | OutputScanner detects injection in output | unit (mock model) | `pytest tests/unit/test_injection_attenuation.py::test_output_scan -x` | No (Wave 0) |
| T-4.10-2 | Attenuator restricts ToolACL | unit | `pytest tests/unit/test_injection_attenuation.py::test_attenuation -x` | No (Wave 0) |
| T-4.10-3 | OutputScanner as Guardrail protocol | unit | `pytest tests/unit/test_injection_attenuation.py::test_guardrail_compat -x` | No (Wave 0) |
| T-4.10-4 | PII detected in output | unit | `pytest tests/unit/test_injection_attenuation.py::test_pii_output -x` | No (Wave 0) |

### Wave 0 Gaps

- [ ] `tests/unit/test_memory_tiers.py` -- T-4.8 unit tests
- [ ] `tests/unit/test_vector_store.py` -- T-4.9 unit tests (dedup, compression)
- [ ] `tests/unit/test_injection_attenuation.py` -- T-4.10 unit tests
- [ ] `tests/integration/test_redis_memory.py` -- T-4.8 integration (requires Redis)
- [ ] `tests/integration/test_vector_store.py` -- T-4.9 integration (requires PostgreSQL + pgvector)
- [ ] New pyproject.toml extras: `memory`, `vectordb`, `promptshield`

---

## 11. Sources

### Primary (HIGH confidence)
- **Codebase audit:** Direct reading of all source files in `src/orchestra/memory/`, `src/orchestra/cache/`, `src/orchestra/security/`, `src/orchestra/storage/`, `src/orchestra/core/`
- **Existing research:** `.planning/phases/04-enterprise-scale/research/04-memory-data-caching.md`, `05-testing-safety-guardrails.md`, `11-curated-tools-research.md`
- **PyPI verified:** redis 7.3.0, pgvector 0.4.2, model2vec 0.7.0, pyzstd 0.19.1, msgpack 1.1.2

### Secondary (MEDIUM confidence)
- [redis-py asyncio docs](https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html)
- [pgvector-python GitHub](https://github.com/pgvector/pgvector-python)
- [model2vec GitHub](https://github.com/MinishLab/model2vec)
- [Sentinel v1 HuggingFace](https://huggingface.co/qualifire/prompt-injection-sentinel)
- [Sentinel v2 HuggingFace](https://huggingface.co/qualifire/prompt-injection-jailbreak-sentinel-v2)
- [PEP 784 -- Zstandard in stdlib](https://peps.python.org/pep-0784/)
- [redis-py #3916 -- async CLIENT TRACKING not supported](https://github.com/redis/redis-py/issues/3916)

### Tertiary (LOW confidence)
- SLRU algorithm details from Wikipedia (no Python implementation found)
- Sentinel v2 accuracy claims (only from HuggingFace model card, not independently verified)
- "471 QPS @ 99% recall on 50M vectors" for pgvectorscale (marketing claim, not independently verified)

---

## 12. Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries verified on PyPI with current versions
- Architecture: MEDIUM -- interface mismatch analysis is solid, but SLRU implementation is custom with no reference impl
- Pitfalls: MEDIUM -- based on known patterns, but some (model2vec GIL contention) are theoretical
- Integration patterns: MEDIUM -- Redis Pub/Sub invalidation is well-documented but async Python specifics need validation

**Research date:** 2026-03-12
**Valid until:** 2026-04-12 (30 days -- stable libraries)
