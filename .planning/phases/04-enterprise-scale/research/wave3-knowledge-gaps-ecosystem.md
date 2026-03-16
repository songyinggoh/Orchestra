# Wave 3 Knowledge Gaps: Ecosystem & Architecture Analysis

**Researched:** 2026-03-12
**Scope:** T-4.8 (Redis L2 + MemoryManager), T-4.9 (HSM 3-Tier + pgvector), T-4.10 (PromptShield)
**Method:** Source code analysis + library version verification + ecosystem research
**Overall Confidence:** MEDIUM (multiple corrections to plan assumptions identified)

---

## Executive Summary

Wave 3 has **6 critical knowledge gaps** and **9 moderate gaps** that the current plan either assumes incorrectly or hasn't researched. The most impactful findings are:

1. **The MemoryManager protocol is extremely minimal** (only `store(key, value)` / `retrieve(key)`). T-4.8's TieredMemoryManager must extend or replace it, not simply wrap it.
2. **The CacheBackend protocol is typed to LLMResponse**, not generic `Any`. Redis L2 must decide whether it implements `CacheBackend` (LLM response caching) or `MemoryManager` (arbitrary data) -- they are currently separate concerns.
3. **Sentinel v2 is NOT a 355M-param ModernBERT model** -- it is a 596M-param Qwen3-0.6B fine-tune requiring 1.2 GB in float16 and `transformers>=4.51`. The plan's `transformers>=4.40` constraint is insufficient, and the model is much larger than assumed.
4. **PostgreSQL already exists** as a dependency (asyncpg for PostgresEventStore), so pgvector does not introduce a new infrastructure dependency -- but it does require the `vector` extension to be installed.
5. **redis-py version constraint is wrong**: the plan says `redis[hiredis]>=7.0` but this only works with Python >=3.10 (fine since project requires >=3.11). However, `redis>=5.0` with `hiredis>=3.0` is the more standard installation pattern.
6. **T-4.9's dependency on T-4.8 is partially false**: the pgvector cold tier, deduplication, and compression can all be built independently. Only the tier-transition logic (warm->cold demotion) requires T-4.8.

---

## Gap 1: MemoryManager Protocol Is Too Minimal [CRITICAL]

### Current State (Source Code Analysis)

The existing `MemoryManager` protocol in `src/orchestra/memory/manager.py` has exactly 2 methods:

```python
@runtime_checkable
class MemoryManager(Protocol):
    async def store(self, key: str, value: Any) -> None: ...
    async def retrieve(self, key: str) -> Any | None: ...
```

The only implementation is `InMemoryMemoryManager` -- a simple dict wrapper.

### What the Plan Assumes

T-4.8 says: "Create `src/orchestra/memory/tiers.py` -- TieredMemoryManager (HOT/WARM/COLD) with SLRU promotion."

This assumes a `TieredMemoryManager` can be built on top of the existing protocol. But the protocol has **no concept of**:
- Tiers (hot/warm/cold)
- TTL or expiration
- Access statistics or frequency tracking
- Promotion or demotion
- Deletion or eviction
- Iteration over stored keys
- Metadata about stored entries

### Gap Impact

The TieredMemoryManager cannot simply implement the existing 2-method `MemoryManager` protocol. It must either:

**Option A (Recommended):** Extend the protocol with new methods while keeping backward compatibility:
```python
class TieredMemoryManager(MemoryManager):
    async def promote(self, key: str, to_tier: Tier) -> None: ...
    async def demote(self, key: str, to_tier: Tier) -> None: ...
    async def get_tier(self, key: str) -> Tier | None: ...
    async def stats(self) -> TierStats: ...
```

**Option B:** Create a wholly new protocol and adapt the old one as a facade.

### Recommendation

Use Option A. The TieredMemoryManager should implement the base `MemoryManager` protocol (so existing code still works via `store`/`retrieve`) while exposing additional tier management methods. The `store` method should default to HOT tier. The `retrieve` method should search tiers in order (HOT -> WARM -> COLD) and auto-promote on hit.

**Confidence:** HIGH (based on direct source code reading)

---

## Gap 2: CacheBackend vs MemoryManager Are Separate Concerns [CRITICAL]

### Current State

The `CacheBackend` protocol in `src/orchestra/cache/backends.py` is typed to `LLMResponse`:

```python
class CacheBackend(Protocol):
    async def get(self, key: str) -> LLMResponse | None: ...
    async def set(self, key: str, value: LLMResponse, ttl: int | None = None) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def clear(self) -> None: ...
```

The `MemoryManager` protocol stores `Any` values with string keys and has no TTL/delete/clear.

### What the Plan Assumes

T-4.8 says: "Create `src/orchestra/cache/redis_backend.py` -- redis.asyncio backend."

The plan does not clarify whether this Redis backend implements `CacheBackend` (for LLM response caching) or provides the L2 tier for `TieredMemoryManager` (for arbitrary memory data), or both.

### Gap Impact

These are architecturally different:
- **CacheBackend Redis**: Stores serialized `LLMResponse` objects. Used by the LLM call layer to avoid re-calling providers. Type-safe.
- **MemoryManager L2 Redis**: Stores arbitrary `Any` values (serialized via msgpack). Used for agent memory persistence. Generic.

### Recommendation

Build **two Redis integrations**:
1. `RedisCacheBackend` implementing `CacheBackend` -- stores `LLMResponse` via `model_dump_json()` / `model_validate_json()`, matching the existing pattern from `InMemoryCacheBackend`.
2. The TieredMemoryManager's WARM tier uses Redis internally (via `redis.asyncio`) but does NOT implement `CacheBackend` -- it uses msgpack serialization for arbitrary values.

Alternatively, if only one is needed for Wave 3, **prioritize the TieredMemoryManager WARM tier** since T-4.8 explicitly targets memory, not LLM response caching. The `RedisCacheBackend` for LLM responses is a quick follow-on.

**Confidence:** HIGH (based on direct source code reading)

---

## Gap 3: Library Version Constraints Are Wrong or Stale [CRITICAL]

### redis[hiredis]

| Plan Says | Actual Latest | Issue |
|-----------|---------------|-------|
| `redis[hiredis]>=7.0` | redis 7.3.0 (March 2026) | Constraint `>=7.0` is valid but aggressive -- redis-py 7.0.0 was released October 2025 and requires Python >=3.10. Since Orchestra requires Python >=3.11, this is compatible. However, the `[hiredis]` extra now installs `hiredis>=3.0.0`. |

**Verdict:** Constraint is functionally correct but should be `redis[hiredis]>=5.0` or `redis>=7.0` with separate `hiredis>=3.0`. The `>=7.0` floor is fine.

### pgvector

| Plan Says | Actual Latest | Issue |
|-----------|---------------|-------|
| `pgvector>=0.3` | pgvector 0.4.2 (December 2025) | The `>=0.3` floor works but the API changed significantly between 0.3 and 0.4. Use `pgvector>=0.4` to get the latest asyncpg integration with schema support. |

**Verdict:** Update to `pgvector>=0.4`.

### pyzstd

| Plan Says | Actual Latest | Issue |
|-----------|---------------|-------|
| `pyzstd>=0.17` | pyzstd 0.19.1 (December 2025) | Since version 0.19.0, pyzstd internally uses `compression.zstd` (stdlib in Python 3.14). For Python 3.11-3.13, pyzstd provides its own C extension. The `>=0.17` floor is compatible but consider that pyzstd 0.19+ requires Python >=3.10. |

**Verdict:** Constraint works. Consider future-proofing: use `compression.zstd` if Python >=3.14, else `pyzstd`. Or just use `pyzstd>=0.17` unconditionally.

### model2vec

| Plan Says | Actual Latest | Issue |
|-----------|---------------|-------|
| `model2vec>=0.3` | model2vec 0.7.0 (October 2025) | Major API changes between 0.3 and 0.7. The `StaticModel` class replaced `Model2Vec` in the API. Use `model2vec>=0.6` minimum for the current API shape. |

**Verdict:** Update to `model2vec>=0.6`.

### transformers

| Plan Says | Actual Latest | Issue |
|-----------|---------------|-------|
| `transformers>=4.40` | transformers 5.3.0 (March 2026) | **Transformers v5 was released January 2026 with breaking changes.** Sentinel v2 requires `transformers>=4.51`. ProtectAI DeBERTa-v3 works with older versions. The `>=4.40` floor is too low for Sentinel v2 and may not work with v5.x at all due to breaking changes. |

**Verdict:** CRITICAL -- must decide between `transformers>=4.51,<6` or `transformers>=5.0`. Test model loading with both v4.51+ and v5.x. Sentinel v2's model card says `transformers>=4.51.0`.

### onnxruntime

| Plan Says | Actual Latest | Issue |
|-----------|---------------|-------|
| `onnxruntime>=1.18` | onnxruntime 1.24.3 (March 2026) | The `>=1.18` floor is fine. No breaking changes. However, the `optimum[onnxruntime]` package is also needed for easy model loading via `ORTModelForSequenceClassification`. |

**Verdict:** Constraint works. Add `optimum[onnxruntime]>=1.24` as an optional dependency for ONNX inference.

### msgpack

| Plan Says | Actual Latest | Issue |
|-----------|---------------|-------|
| `msgpack>=1.0` | msgpack 1.1.2 (October 2025) | Constraint is fine. No issues. |

**Verdict:** No change needed.

**Confidence:** HIGH (verified against PyPI)

---

## Gap 4: Sentinel v2 Is NOT What the Plan Describes [CRITICAL]

### What the Plan / Prior Research Says

Research document `05-testing-safety-guardrails.md` states:
> "Sentinel (qualifire) -- ~355M -- 0.987/0.980 -- Open"

The plan for T-4.10 says:
> "Async SLM wrapper (Sentinel/Prompt Guard)"
> Libraries: `transformers>=4.40`, `onnxruntime>=1.18`

This implies a small, fast model (~355M params) that can run efficiently on CPU via ONNX Runtime.

### Actual State (Verified March 2026)

Sentinel v1 (original, June 2025): ModernBERT-large backbone, ~395M params, 1.6 GB float16
Sentinel v2 (current, late 2025): **Qwen3-0.6B backbone, 596M params, 1.2 GB float16**

| Property | Assumed | Actual (v2) |
|----------|---------|-------------|
| Architecture | ModernBERT-large | Qwen3-0.6B |
| Parameters | ~355M | 596M |
| Size (fp16) | ~700 MB | 1.2 GB |
| ONNX available | Assumed yes | **No official ONNX** |
| License | "Open" | Elastic License (commercial-ready, not Apache 2.0) |
| transformers version | >=4.40 | **>=4.51.0** |
| CPU inference | Fast via ONNX | PyTorch only, ~38ms GPU |

### Gap Impact

1. **Sentinel v2 is 2x larger than assumed** and has no official ONNX export
2. **CPU inference without ONNX** for a 596M-param model will be 200-500ms, far from the "zero latency" claim
3. ModernBERT ONNX export only became supported in optimum v1.24.0, and Qwen3 ONNX support is community-provided, not official
4. The Elastic License is NOT Apache 2.0 -- may have implications for redistribution

### Recommendation: Use ProtectAI DeBERTa-v3-base OR Prompt Guard 2 22M instead

**Primary choice: ProtectAI deberta-v3-base-prompt-injection-v2**
- 184M params, Apache 2.0 license
- **Official ONNX export included in the repo**
- F1: 95.49%, Recall: 99.74%
- CPU via ONNX Runtime: ~10-30ms
- Works with `transformers>=4.30`, `optimum[onnxruntime]`

**Secondary choice: Meta Llama-Prompt-Guard-2-22M**
- 22M params (tiny!), Llama 4 Community License
- Community ONNX export available (gravitee-io/Llama-Prompt-Guard-2-22M-onnx)
- F1: ~94.5% (quantized ONNX), excellent recall
- CPU via ONNX Runtime: ~5-10ms
- Supports 8 languages

**Sentinel v2 should be optional/premium**, not the default guard model.

**Confidence:** HIGH (verified against HuggingFace model cards)

---

## Gap 5: PostgreSQL Infrastructure Already Exists [MODERATE]

### Current State

The project already has `PostgresEventStore` in `src/orchestra/storage/postgres.py` using asyncpg. This means:

1. `asyncpg>=0.29` is already an optional dependency (`[postgres]` extra)
2. PostgreSQL connection pooling patterns already exist
3. DDL migration patterns are established

### What the Plan Assumes

T-4.9 lists `pgvector>=0.3` as if PostgreSQL is new infrastructure. It is not.

### Gap Impact

This is actually good news -- pgvector does NOT require a new database dependency. The cold tier can reuse the existing PostgreSQL connection pool from `PostgresEventStore`. However:

1. The `pgvector` PostgreSQL extension must be installed on the database server (separate from the Python library)
2. The `register_vector(conn)` call must be made on each asyncpg connection, which requires hooking into the pool's init callback
3. The existing DDL migration pattern (`_DDL_STATEMENTS` list in `postgres.py`) should be extended for vector tables

### Recommendation

Add pgvector table creation to a shared migration system. Use the existing asyncpg pool with `init=register_vector` callback. Document that `CREATE EXTENSION IF NOT EXISTS vector` must be run before first use.

**Confidence:** HIGH (source code verified)

---

## Gap 6: T-4.9 Dependency on T-4.8 Is Partially False [MODERATE]

### What the Plan Says

> T-4.9: HSM 3-Tier + pgvector Cold Tier [L]
> **Depends on:** T-4.8

### Analysis

T-4.9 creates three components:
1. `vector_store.py` -- pgvector HNSW + hybrid retrieval
2. `dedup.py` -- SemanticDeduplicator
3. `compression.py` -- StateCompressor (zstd + msgpack)

Of these:
- **vector_store.py** depends only on asyncpg + pgvector + model2vec. No Redis or tier logic needed.
- **dedup.py** depends only on model2vec embeddings. No Redis or tier logic needed.
- **compression.py** depends only on pyzstd + msgpack. Completely independent.

The **only** part that needs T-4.8 is wiring the cold tier INTO the TieredMemoryManager's demotion logic (WARM -> COLD transitions).

### Gap Impact

This false dependency blocks 80% of T-4.9's work behind T-4.8. In practice:
- vector_store.py, dedup.py, and compression.py can be built in parallel with T-4.8
- Only the integration (tier transitions, HSM orchestration) must wait for T-4.8

### Recommendation

Split T-4.9 internally:
- **T-4.9a (parallel with T-4.8):** vector_store.py, dedup.py, compression.py -- all independent components
- **T-4.9b (after T-4.8):** Wire cold tier into TieredMemoryManager, implement WARM->COLD demotion triggers

This removes 1-2 weeks from the critical path.

**Confidence:** HIGH (architecture analysis)

---

## Gap 7: Redis Pub/Sub Invalidation Is Best-Effort [MODERATE]

### What the Plan Assumes

The prior research (04-memory-data-caching.md) describes L1+L2 with Pub/Sub invalidation but notes: "Pub/Sub is best-effort and non-persistent."

The plan's "Done when: L2 <2ms; promotion/demotion functional across distributed instances" implies reliable cross-instance consistency.

### Gap Analysis

Redis Pub/Sub messages are fire-and-forget:
- If a subscriber disconnects temporarily, it misses invalidation messages
- No delivery guarantees, no message replay
- Reconnecting subscribers must treat their L1 as fully stale

### Mitigation Options

| Approach | Complexity | Reliability |
|----------|-----------|-------------|
| **Short L1 TTLs (30-60s)** as safety net | Low | Good -- stale data bounded to TTL |
| **Redis Streams** instead of Pub/Sub | Medium | Excellent -- persistent, replayable |
| **Version stamps** on each key | Medium | Good -- detect stale on read |
| **CLIENT TRACKING** (RESP3) | Low | Good -- but **not supported by redis.asyncio** (issue #3916) |

### Recommendation

Use Pub/Sub + short L1 TTLs (30-60 seconds) for Wave 3. This is the simplest approach and limits staleness to a bounded window. Redis Streams can be added in a future wave if stronger guarantees are needed.

**Important:** The prior research correctly identified that `redis.asyncio` does NOT support CLIENT TRACKING (server-assisted client-side caching). Do not attempt to use it.

**Confidence:** MEDIUM (based on redis-py issue tracker + general knowledge)

---

## Gap 8: Hybrid Retrieval for pgvector Needs Design [MODERATE]

### What the Plan Says

T-4.9: "pgvector HNSW + hybrid retrieval"

### What This Actually Requires

"Hybrid retrieval" in the pgvector context means combining:
1. **Semantic search** via HNSW cosine similarity (`<=>` operator)
2. **Full-text search** via PostgreSQL's built-in tsvector/tsquery
3. **Reciprocal Rank Fusion (RRF)** to merge results

This is a well-established pattern, but the plan does not specify:
- What fields to index for full-text search (memory content? metadata? both?)
- What RRF constant to use (k=60 is standard)
- Whether to use a `GENERATED ALWAYS AS` tsvector column or compute at query time
- What HNSW parameters to use (M=16, ef_construction=200 recommended for <1M vectors)
- Whether to create a materialized view for pre-computed scores

### Recommendation

For the cold tier vector store, implement:
```sql
CREATE TABLE memory_vectors (
    id UUID PRIMARY KEY,
    agent_id TEXT NOT NULL,
    content TEXT NOT NULL,
    content_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    embedding VECTOR(256),  -- model2vec potion-base-8M dimension
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    access_count INTEGER DEFAULT 0,
    last_accessed TIMESTAMPTZ
);

CREATE INDEX idx_memory_hnsw ON memory_vectors
    USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=200);
CREATE INDEX idx_memory_tsv ON memory_vectors USING gin (content_tsv);
CREATE INDEX idx_memory_agent ON memory_vectors (agent_id);
```

Hybrid retrieval query using RRF:
```sql
WITH semantic AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> $1) AS rank
    FROM memory_vectors WHERE agent_id = $2
    ORDER BY embedding <=> $1 LIMIT 20
),
fulltext AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY ts_rank(content_tsv, query) DESC) AS rank
    FROM memory_vectors, plainto_tsquery('english', $3) query
    WHERE content_tsv @@ query AND agent_id = $2
    LIMIT 20
)
SELECT COALESCE(s.id, f.id) AS id,
       COALESCE(1.0/(60+s.rank), 0) + COALESCE(1.0/(60+f.rank), 0) AS rrf_score
FROM semantic s FULL OUTER JOIN fulltext f ON s.id = f.id
ORDER BY rrf_score DESC LIMIT $4;
```

**Confidence:** MEDIUM (based on ecosystem research; specific tuning needs benchmarking)

---

## Gap 9: Model2Vec Embedding Dimension Alignment [MODERATE]

### What the Plan Says

T-4.9 uses `model2vec>=0.3` for the SemanticDeduplicator and cold tier embeddings.

### What Needs Specifying

The plan does not specify which model2vec model to use. Options:

| Model | Parameters | Dimensions | Size | Speed (CPU) |
|-------|-----------|------------|------|-------------|
| potion-base-8M | 8M | 256 | ~10 MB | ~25K sent/s |
| potion-base-4M | 4M | 256 | ~5 MB | ~30K sent/s |
| potion-base-2M | 2M | 256 | ~3 MB | ~35K sent/s |

All potion models output 256-dimensional embeddings.

### Gap Impact

The pgvector column must be defined with the correct dimension: `VECTOR(256)` for any potion model. If a different embedding model is used later (e.g., all-MiniLM-L6-v2 at 384 dims), the column type must change.

### Recommendation

Use `potion-base-8M` for best quality/speed tradeoff. Lock the dimension at 256 and document it. Add a config parameter for the model name so it can be swapped without code changes.

**Confidence:** HIGH (verified against model2vec docs and HuggingFace)

---

## Gap 10: The "90% Top-10 Accuracy" Target Needs Clarification [MODERATE]

### What the Plan Says

T-4.9 Done when: "Cold tier retrieval returns semantically similar memories; 90% top-10 accuracy."

### Issues

1. **What benchmark?** There is no existing test dataset of agent memories with ground-truth similarity labels.
2. **What metric?** "90% top-10 accuracy" could mean:
   - Recall@10: 90% of relevant items appear in top 10 (standard)
   - Precision@10: 9 of 10 returned items are relevant (very different)
   - Hit Rate@10: The correct item appears somewhere in top 10 (easiest)
3. **Compared to what?** Without a baseline, this is unverifiable.

### Recommendation

Define this as: **Recall@10 >= 0.90 on a synthetic benchmark**. Create the benchmark during implementation:
1. Generate 1000 synthetic memory entries with known clusters
2. For each query, mark the correct cluster members as "relevant"
3. Measure Recall@10 with HNSW search

This is standard for vector search evaluation. The 90% target is achievable with HNSW at M=16, ef_search=100 for datasets up to 1M vectors.

**Confidence:** MEDIUM (90% is achievable based on HNSW literature, but depends on data distribution)

---

## Gap 11: PromptShield Architecture vs Existing Rebuff [MODERATE]

### Current State

The project already has a comprehensive prompt injection system in `src/orchestra/security/rebuff.py`:
- `RebuffChecker` -- 4-layer detection (heuristic, LLM, VectorDB, canary tokens)
- `PromptInjectionAgent` -- pre/post execution guards
- `InjectionAuditorAgent` -- standalone auditor node
- `make_injection_guard_node()` -- graph node factory
- `rebuff_tool()` -- tool wrapper for inline checking

T-4.10 creates:
- `output_scanner.py` -- post-execution output scanning
- `attenuator.py` -- dynamic capability reduction
- `guard.py` -- async SLM wrapper

### Gap: No Migration Path Defined

The plan does not specify:
1. Does PromptShield **replace** Rebuff or **augment** it?
2. How does `guard.py`'s SLM classifier relate to Rebuff's LLM-based detection?
3. Can `output_scanner.py` integrate with the existing `GuardrailChain` (it should)?
4. Does the `attenuator.py` modify `ToolACL` (from `src/orchestra/security/acl.py`)?

### Recommendation

**Augment, don't replace.** Build T-4.10 as new guardrails that plug into the existing `GuardrailChain`:

1. `output_scanner.py` should implement the `Guardrail` protocol, so it works with `GuardrailChain` and `GuardedAgent`
2. `guard.py` (SLM classifier) should implement the `Guardrail` protocol for input scanning -- replacing Rebuff's LLM-based layer with a local model
3. `attenuator.py` should modify the agent's `ToolACL` when injection is detected -- switching from `ToolACL.open()` to a restricted `ToolACL.allow_list(["safe_tool_1"])` at runtime

This preserves backward compatibility while adding defense-in-depth.

**Confidence:** HIGH (based on source code architecture analysis)

---

## Gap 12: The "L2 <2ms" Target Is Network-Dependent [MINOR]

### What the Plan Says

T-4.8 Done when: "L2 <2ms"

### Analysis

Redis roundtrip latency depends on:
- **Same-machine (Unix socket):** 0.1-0.3 ms -- achievable
- **Same-datacenter (TCP):** 0.3-1.0 ms -- achievable
- **Cross-AZ (cloud):** 1-5 ms -- may exceed 2ms
- **Cross-region:** 10-100 ms -- will not meet target

The target of <2ms is achievable for same-datacenter deployments but should be documented as such.

### Recommendation

Qualify the target: "L2 <2ms for same-datacenter Redis (p99)". Add a test that measures actual latency and warns if >2ms. Use hiredis parser (included via `redis[hiredis]`) for ~30% speedup on response parsing.

**Confidence:** HIGH (well-established Redis latency characteristics)

---

## Gap 13: msgpack Serialization for MemoryManager Values [MINOR]

### What the Plan Says

T-4.8: Libraries include `msgpack>=1.0`

### Gap

The plan says to use msgpack for serialization, but the existing `MemoryManager.store()` accepts `Any`. Not all Python objects are msgpack-serializable. Pydantic models, dataclasses, datetime objects, and custom types will fail with default msgpack.

### Recommendation

Use a two-layer serialization strategy:
1. **Primary:** msgpack with a custom `default` function that handles common types (datetime -> ISO string, Pydantic model -> dict, dataclass -> dict)
2. **Fallback:** For complex objects, serialize to JSON first, then store as msgpack bytes
3. **Performance:** msgpack is ~30-50% smaller and ~2-3x faster than JSON for typical payloads

Also define the serialization format in a shared module so both WARM (Redis) and COLD (pgvector) tiers use consistent encoding.

**Confidence:** HIGH (well-known msgpack limitation)

---

## Gap 14: Background SLRU Scan Task Lifecycle [MINOR]

### What the Plan Says

T-4.8 creates TieredMemoryManager with SLRU promotion.

### Gap

SLRU requires a background task that periodically:
1. Scans HOT tier for items to demote (access count < threshold in window)
2. Scans WARM tier for items to promote (access count >= threshold)
3. Scans WARM tier for items to demote to COLD (TTL expired)

This background task must:
- Start when the TieredMemoryManager is initialized
- Stop cleanly when the application shuts down
- Not block the event loop
- Handle partial failures (Redis down, pgvector down)

### Recommendation

Use `asyncio.create_task()` with a cancellation token pattern. Register cleanup in the application's shutdown hook. Use exponential backoff if a tier is unreachable. Run scan interval at 30-60 seconds (configurable).

**Confidence:** HIGH (standard async pattern)

---

## Gap 15: pyproject.toml Extra Groups Need Updating [MINOR]

### Current State

The pyproject.toml has these relevant extras:
- `cache = ["cachetools>=5.5", "diskcache>=5.6"]`
- `postgres = ["asyncpg>=0.29"]`
- `security = ["wasmtime>=23.0", "joserfc>=1.6", "pynacl>=1.5"]`

### What Wave 3 Needs

New extras should be added:

```toml
[project.optional-dependencies]
# ... existing ...
redis = ["redis[hiredis]>=7.0", "msgpack>=1.0"]
memory = [
    "redis[hiredis]>=7.0",
    "msgpack>=1.0",
    "pgvector>=0.4",
    "pyzstd>=0.17",
    "model2vec>=0.6",
    "asyncpg>=0.29",
]
prompt-shield = [
    "transformers>=4.51",
    "onnxruntime>=1.18",
    "optimum>=1.24",
]
```

**Confidence:** HIGH (based on pyproject.toml analysis)

---

## Summary of All Gaps

| # | Gap | Severity | Task | Action Required |
|---|-----|----------|------|-----------------|
| 1 | MemoryManager protocol too minimal | CRITICAL | T-4.8 | Extend protocol with tier/promote/demote methods |
| 2 | CacheBackend vs MemoryManager confusion | CRITICAL | T-4.8 | Clarify Redis backend scope; build two backends or pick one |
| 3 | Library version constraints wrong/stale | CRITICAL | All | Update pgvector>=0.4, model2vec>=0.6, transformers>=4.51 |
| 4 | Sentinel v2 is 596M Qwen3 not 355M ModernBERT | CRITICAL | T-4.10 | Switch default to ProtectAI DeBERTa or Prompt Guard 2 22M |
| 5 | PostgreSQL already exists as infra | MODERATE | T-4.9 | Reuse existing asyncpg pool; add vector extension DDL |
| 6 | T-4.9 dependency on T-4.8 is partially false | MODERATE | T-4.9 | Split T-4.9 into parallel and sequential parts |
| 7 | Redis Pub/Sub is best-effort | MODERATE | T-4.8 | Use short L1 TTLs as safety net; avoid CLIENT TRACKING |
| 8 | Hybrid retrieval needs design | MODERATE | T-4.9 | Design RRF query combining HNSW + tsvector |
| 9 | Model2Vec dimension alignment | MODERATE | T-4.9 | Lock to potion-base-8M at 256 dims; make configurable |
| 10 | "90% top-10 accuracy" is vague | MODERATE | T-4.9 | Define as Recall@10 on synthetic benchmark |
| 11 | PromptShield vs Rebuff migration unclear | MODERATE | T-4.10 | Augment (not replace); implement Guardrail protocol |
| 12 | "L2 <2ms" is network-dependent | MINOR | T-4.8 | Qualify as same-datacenter p99 |
| 13 | msgpack can't serialize all `Any` values | MINOR | T-4.8 | Custom serializer with fallback |
| 14 | Background SLRU task lifecycle | MINOR | T-4.8 | Use asyncio.create_task + shutdown hook |
| 15 | pyproject.toml extras need updating | MINOR | All | Add redis, memory, prompt-shield extras |

---

## Corrected Library Versions

| Library | Plan Version | Recommended Version | Reason |
|---------|-------------|-------------------|--------|
| redis[hiredis] | >=7.0 | >=7.0 | OK (latest 7.3.0) |
| msgpack | >=1.0 | >=1.0 | OK (latest 1.1.2) |
| pgvector | >=0.3 | **>=0.4** | API changes in 0.4; asyncpg schema support |
| pyzstd | >=0.17 | >=0.17 | OK (latest 0.19.1) |
| model2vec | >=0.3 | **>=0.6** | StaticModel API introduced; major changes |
| transformers | >=4.40 | **>=4.51** | Sentinel v2 requires 4.51+; v5.3.0 is current |
| onnxruntime | >=1.18 | >=1.18 | OK (latest 1.24.3) |
| optimum | not listed | **>=1.24** | Needed for ORTModelForSequenceClassification |

---

## Recommended PromptShield Model Selection

| Use Case | Model | Params | Size | Latency (CPU/ONNX) | License | F1 |
|----------|-------|--------|------|---------------------|---------|-----|
| **Default (recommended)** | protectai/deberta-v3-base-prompt-injection-v2 | 184M | ~350 MB | 10-30ms | Apache 2.0 | 95.5% |
| **Lightweight** | meta-llama/Llama-Prompt-Guard-2-22M (ONNX) | 22M | ~90 MB | 5-10ms | Llama 4 | 94.5% |
| **Maximum accuracy** | qualifire/sentinel-v2 | 596M | 1.2 GB | 38ms (GPU) | Elastic | 96.4% |
| **Legacy/optional** | protectai/deberta-v3-base-injection (ONNX) | 184M | ~350 MB | 10-30ms | Apache 2.0 | 99.9%* |

*Note: v1 F1 may be inflated due to training data overlap with evaluation set.

**Recommendation:** Default to ProtectAI v2 (Apache 2.0, ONNX included, good balance). Offer Prompt Guard 2 22M as a lightweight option. Make model configurable.

---

## Sources

- [redis-py PyPI](https://pypi.org/project/redis/) -- version 7.3.0 verified
- [redis-py GitHub Releases](https://github.com/redis/redis-py/releases) -- version history
- [pgvector-python PyPI](https://pypi.org/project/pgvector/) -- version 0.4.2 verified
- [pgvector-python GitHub](https://github.com/pgvector/pgvector-python) -- asyncpg integration docs
- [model2vec PyPI](https://pypi.org/project/model2vec/) -- version 0.7.0 verified
- [model2vec GitHub](https://github.com/MinishLab/model2vec) -- StaticModel API
- [pyzstd PyPI](https://pypi.org/project/pyzstd/) -- version 0.19.1 verified
- [PEP 784](https://peps.python.org/pep-0784/) -- Zstandard in stdlib
- [transformers PyPI](https://pypi.org/project/transformers/) -- version 5.3.0 verified
- [onnxruntime PyPI](https://pypi.org/project/onnxruntime/) -- version 1.24.3 verified
- [Sentinel v2 HuggingFace](https://huggingface.co/qualifire/prompt-injection-jailbreak-sentinel-v2) -- model card verified
- [ProtectAI DeBERTa v2 HuggingFace](https://huggingface.co/protectai/deberta-v3-base-prompt-injection-v2) -- model card verified
- [Prompt Guard 2 22M HuggingFace](https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-22M) -- model card verified
- [Prompt Guard 2 22M ONNX](https://huggingface.co/gravitee-io/Llama-Prompt-Guard-2-22M-onnx) -- community ONNX export
- [Sentinel blog post](https://qualifire.ai/posts/sentinel-sota-model-to-protect-against-prompt-injections) -- architecture details
- [Optimum ONNX ModernBERT PR](https://github.com/huggingface/optimum/pull/2208) -- ONNX optimization support
- [Redis Pub/Sub cache invalidation](https://medium.com/@deghun/redis-pub-sub-local-memory-low-latency-high-consistency-caching-3740f66f0368)
- [pgvector hybrid search with RRF](https://dev.to/lpossamai/building-hybrid-search-for-rag-combining-pgvector-and-full-text-search-with-reciprocal-rank-fusion-6nk)
- [Hybrid search postgres pgvector](https://jkatz05.com/post/postgres/hybrid-search-postgres-pgvector/)
- [msgpack PyPI](https://pypi.org/project/msgpack/) -- version 1.1.2 verified
