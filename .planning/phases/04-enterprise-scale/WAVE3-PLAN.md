# Wave 3 Execution Plan — Data, Memory & Security

**Created:** 2026-03-13
**Status:** READY FOR EXECUTION
**Depends on:** Phase 3 complete (T-3.4 MemoryManager). NOT blocked by Wave 2.
**Tasks:** T-4.8 (6 steps), T-4.9 (6 steps), T-4.10 (6 steps) = 18 steps total
**Decisions:** WAVE3-DECISIONS.md (D1-D7 approved)
**Protocol:** WAVE3-PROTOCOL-SKELETON.md (interfaces approved)
**Research:** wave3-knowledge-gaps-ecosystem.md, wave3-knowledge-gaps-implementation.md

---

## Parallelization Strategy

```
              Week 1                              Week 2
 ┌──────────────────────────────┐  ┌──────────────────────────────┐
 │                              │  │                              │
 │  T-4.8 Steps 1→2→3→4→5→6    │  │  T-4.9 Phase B (B1→B2)      │
 │  (Redis L2 + SLRU)          │  │  (wire cold into tiered mgr) │
 │                              │  │                              │
 │  T-4.9 Phase A (A1,A2,A3,A4)│  │                              │
 │  (compression, dedup, vector)│  │                              │
 │  ──parallel with T-4.8──    │  │                              │
 │                              │  │                              │
 │  T-4.10 Steps 1→2→3→4→5→6   │  │                              │
 │  (PromptShield)              │  │                              │
 │  ──fully independent──       │  │                              │
 └──────────────────────────────┘  └──────────────────────────────┘
```

**Three parallel tracks in Week 1:**
- Track A: T-4.8 (Redis L2 + TieredMemoryManager)
- Track B: T-4.9 Phase A (VectorStore, SemanticDeduplicator, StateCompressor)
- Track C: T-4.10 (PromptShield OutputScanner + Attenuator)

**Week 2:** T-4.9 Phase B only (wire cold tier into TieredMemoryManager from T-4.8)

---

## T-4.8: Redis L2 + MemoryManager Promote/Demote (6 steps)

### Step 8.1: Serialization Helpers

**Create:** `src/orchestra/memory/serialization.py`, `tests/unit/test_memory_serialization.py`
**Depends on:** Nothing

- `pack(value: Any) -> bytes` and `unpack(data: bytes) -> Any` using msgpack
- Custom `default` function for: datetime→ISO string, Pydantic→model_dump, dataclass→asdict
- Matching `object_hook` for reconstruction via importlib
- **Tests:** 7+ roundtrip cases (primitives, nested, datetime, Pydantic, dataclass, bytes, error)
- **Done when:** All roundtrips pass

### Step 8.2: MemoryBackend Protocol + SLRUPolicy

**Create:** `src/orchestra/memory/backends.py`, `src/orchestra/memory/tiers.py` (partial), `tests/unit/test_slru_policy.py`, `tests/unit/test_memory_backends.py`
**Depends on:** Step 8.1

- `MemoryBackend` protocol: get/set/delete/exists/keys
- `InMemoryMemoryBackend`: dict + TTL tracking, lazy expiry, fnmatch pattern keys
- `Tier` enum (HOT/WARM/COLD), `MemoryEntry` dataclass
- `SLRUPolicy`: OrderedDict-based protected (HOT) + probationary (WARM), access/insert/remove/evictions_due
- **Tests:** ~18 tests (9 SLRU + 9 backend)
- **Done when:** SLRU promotion/demotion/eviction logic correct, backend TTL works

### Step 8.3: RedisMemoryBackend

**Modify:** `src/orchestra/memory/backends.py`, `pyproject.toml`
**Create:** `tests/unit/test_redis_memory_backend.py`
**Depends on:** Step 8.2

- `RedisMemoryBackend` with `BlockingConnectionPool(max_connections=20)`, `health_check_interval=3`, `Retry(ExponentialBackoff(), 3)`
- Key prefixing: `f"{prefix}{key}"` on all operations
- initialize/close lifecycle, async context manager
- **pyproject.toml:** add `redis = ["redis[hiredis]>=7.0", "msgpack>=1.0"]` extra
- **Tests:** 10 tests, all `@pytest.mark.integration` (skip without Redis)
- **Done when:** Roundtrip with real Redis works, tests skip cleanly without Redis

### Step 8.4: Singleflight + Pub/Sub Invalidation

**Create:** `src/orchestra/memory/singleflight.py`, `src/orchestra/memory/invalidation.py`, `tests/unit/test_singleflight.py`, `tests/unit/test_invalidation.py`
**Depends on:** Step 8.3

- `SingleFlight.do(key, fn)`: coalesce concurrent requests, clean up on exception
- `InvalidationSubscriber`: subscribe to `orchestra:mem:inv`, callback on message, `on_reconnect` flushes L1
- `publish_invalidation()`: standalone async function
- **Tests:** 4 singleflight + 3 invalidation (unit with mocks + integration)
- **Done when:** Concurrent reads coalesced, Pub/Sub messages delivered

### Step 8.5: TieredMemoryManager

**Modify:** `src/orchestra/memory/tiers.py`, `src/orchestra/memory/__init__.py`, `src/orchestra/core/context.py`
**Create:** `tests/unit/test_tiered_memory.py`
**Depends on:** Steps 8.1-8.4

- Implements `MemoryManager` protocol (store→HOT, retrieve→HOT→WARM→COLD with auto-promote)
- Extended API: promote/demote/get_tier/stats
- Background SLRU scan via `asyncio.create_task` + `_shutdown_event`
- L1 TTL safety net (30s), singleflight on WARM reads
- Pub/Sub invalidation integration, reconnect flushes HOT
- **context.py:** add `memory_manager: Any = None`
- **Tests:** ~20 tests across 7 groups (protocol compat, tier behavior, promote/demote, SLRU eviction, background scan, singleflight, stats)
- **Done when:** `isinstance(mgr, MemoryManager)` is True, all tier transitions work

### Step 8.6: Integration Test

**Create:** `tests/integration/test_redis_tiered_memory.py`
**Depends on:** Step 8.5

- Full roundtrip with real Redis, msgpack serialization
- Cross-instance Pub/Sub invalidation
- Singleflight stampede test (50 concurrent reads)
- Lifecycle idempotency
- All `@pytest.mark.integration`
- **Done when:** Full stack works against real Redis

---

## T-4.9: HSM 3-Tier + pgvector Cold Tier (6 steps)

### Phase A: Independent Modules (parallel with T-4.8)

### Step 9.A1: StateCompressor

**Create:** `src/orchestra/memory/compression.py`, `tests/unit/test_compression.py`
**Depends on:** Nothing

- `compress(value: Any) -> bytes`: msgpack.packb → pyzstd.compress (level 3)
- `decompress(data: bytes) -> Any`: pyzstd.decompress → msgpack.unpackb
- Sync methods (sub-ms for <100KB)
- **Tests:** 8 tests (roundtrip dict/list/bytes/large, size reduction, custom level, empty, None)
- **Done when:** All roundtrips pass, compressed < raw for >1KB payloads

### Step 9.A2: SemanticDeduplicator

**Create:** `src/orchestra/memory/dedup.py`, `tests/unit/test_dedup.py`
**Depends on:** Nothing

- Lazy-load `StaticModel.from_pretrained("minishlab/potion-base-8M")`
- `embed(texts) -> list[list[float]]` via `asyncio.to_thread` (batch, not per-text)
- `is_duplicate(text, pool, agent_id) -> (bool, key|None)` at cosine similarity >= 0.98
- `find_similar(text, pool, agent_id, limit)` for near-duplicate range
- Query uses `<=>` cosine distance, `1 - (embedding <=> $1)` for similarity
- **Tests:** 12 tests (embed batching, asyncio.to_thread, threshold boundary, lazy loading)
- **Done when:** Dedup correctly classifies at 0.98 threshold, model lazy-loaded

### Step 9.A3: VectorStore

**Create:** `src/orchestra/memory/vector_store.py`, `tests/unit/test_vector_store.py`, `tests/integration/test_cold_tier.py`
**Depends on:** Nothing

- Constructor: accepts existing asyncpg pool OR DSN
- `_register_vector(conn)` as pool init callback (per-connection!)
- DDL: memory_cold table with VECTOR(256), HNSW index (M=16, ef_construction=200), GIN index, agent index
- `store()`: INSERT ON CONFLICT (upsert)
- `retrieve()`: SELECT + increment access_count
- `search_semantic()`: HNSW with `SET hnsw.ef_search = 100`
- `search_fulltext()`: tsvector/tsquery with ts_rank
- `search()`: hybrid RRF (k=60), over-fetch 20 from each source
- `count()`: utility for tests/stats
- **Unit tests:** 16 tests (mock pool — lifecycle, store, retrieve, search, count)
- **Integration tests:** 12 tests (real Postgres+pgvector — DDL, roundtrip, semantic search, hybrid RRF, recall@10 benchmark, agent isolation)
- **Done when:** `<=>` operator matches `vector_cosine_ops` index, hybrid RRF works

### Step 9.A4: Package + Exports

**Modify:** `pyproject.toml`, `src/orchestra/memory/__init__.py`
**Depends on:** Steps 9.A1, 9.A2, 9.A3

- **pyproject.toml:** add `vectordb = ["pgvector>=0.4", "model2vec>=0.6", "pyzstd>=0.17", "msgpack>=1.0"]`
- **__init__.py:** guarded imports (try/except ImportError) for VectorStore, SemanticDeduplicator, StateCompressor
- **Done when:** `from orchestra.memory import MemoryManager` works without vectordb extras

### Phase B: Integration (requires T-4.8)

### Step 9.B1: ColdTierBackend Protocol on VectorStore

**Modify:** `src/orchestra/memory/vector_store.py`
**Depends on:** Steps 9.A1-A3, T-4.8 complete

- Adapt VectorStore to satisfy `ColdTierBackend` protocol from tiers.py
- `store(key, value, embedding)`: serialize value via StateCompressor, extract content text
- `retrieve(key)`: decompress via StateCompressor before returning
- `search(embedding, limit)`: wrapper around hybrid search with default agent_id
- Integrate SemanticDeduplicator on store (skip duplicates)
- Add `agent_id` and `compressor`/`deduplicator` to constructor
- **Tests:** 6 tests (protocol compliance, compression roundtrip, dedup skip)
- **Done when:** `isinstance(vector_store, ColdTierBackend)` is True

### Step 9.B2: Wire into TieredMemoryManager

**Modify:** `src/orchestra/memory/tiers.py`, `tests/unit/test_memory_tiers.py`
**Depends on:** Step 9.B1

- WARM→COLD demotion: read from WARM, embed, dedup check, compress, store in cold
- COLD retrieval in lookup chain: HOT miss → WARM miss → COLD (auto-promote to WARM)
- `search_memories(query, limit)`: semantic search exposed through TieredMemoryManager
- `create_tiered_memory()` factory function for convenient setup
- **Tests:** 6 tests (cold fallthrough, cold promote, demotion pipeline, dedup prevents write, search delegation, graceful degradation without cold)
- **Done when:** Full HOT→WARM→COLD pipeline works end-to-end

---

## T-4.10: PromptShield Output Scanning + Attenuation (6 steps)

### Step 10.1: Add restricted_mode to ExecutionContext

**Modify:** `src/orchestra/core/context.py`
**Depends on:** Nothing

- Add `restricted_mode: bool = False` after delegation_context field
- **Done when:** Existing tests still pass

### Step 10.2: SLMGuard (ONNX Model Wrapper)

**Create:** `src/orchestra/security/guard.py`
**Depends on:** Nothing

- `SLMGuard(model_id, threshold, device)` with lazy loading via `_ensure_loaded()`
- Default model: `gravitee-io/Llama-Prompt-Guard-2-86M-onnx` (282 MB quantized)
- `classify(text) -> SLMGuardResult`: tokenize (truncate 512), ONNX inference, numpy softmax
- Auto-detect label mapping from `model.config.id2label` (PG2: 3 labels, ProtectAI: 2 labels)
- `threading.Lock` for safe concurrent loading
- `ORCHESTRA_GUARD_MODEL` env var override
- Constants: DEFAULT_MODEL, LIGHTWEIGHT_MODEL, PROTECTAI_MODEL
- **Tests:** 8 tests (lazy load, benign/injection classification, threshold boundary, truncation, import error, env var, protectai file_name)
- **Done when:** All tests pass with mocked ONNX model, zero real downloads

### Step 10.3: OutputScanner (Guardrail Protocol)

**Create:** `src/orchestra/security/output_scanner.py`
**Depends on:** Step 10.2

- Implements `Guardrail` protocol (name, on_fail, validate)
- `validate(text, **kwargs)`: runs `asyncio.to_thread(guard.classify, text)`
- On injection: creates GuardrailViolation, optionally calls Attenuator if context in kwargs
- `validate_input()` returns [] (output-only scanner)
- **Tests:** 9 tests (pass/block, protocol compliance, on_fail, attenuator integration, chain integration)
- **Done when:** `isinstance(scanner, Guardrail)` is True, integrates with GuardrailChain

### Step 10.4: Attenuator (Capability Attenuation)

**Create:** `src/orchestra/security/attenuator.py`
**Depends on:** Step 10.1

- `attenuate(context, current_acl) -> ToolACL`: sets context.restricted_mode=True, creates NEW frozen ToolACL
- Two modes: denylist (allow_all=True + denied_tools) or strict allowlist
- Default denied: execute_code, shell, file_write, http_request, database_write + patterns *_write, *_delete, *_execute
- `Attenuator.default()` factory
- **Tests:** 9 tests (restricted_mode, new ACL, deny dangerous, allow safe, allowlist mode, deny patterns, frozen not mutated, is_attenuated, default factory)
- **Done when:** Creates correct restricted ACLs, never mutates frozen originals

### Step 10.5: Wire into GuardedAgent + E2E Tests

**Modify:** `src/orchestra/security/guardrails.py`
**Depends on:** Steps 10.2-10.4

- Change `GuardedAgent.run()`: pass `context=context` to both input and output guardrail chains
- GuardrailChain already forwards **kwargs — no chain changes needed
- **Tests:** 7 integration tests (GuardedAgent with scanner, attenuator E2E, chain ordering, context flow, restricted_mode default, existing guardrails unaffected)
- **Done when:** Context flows through chain to OutputScanner, existing tests pass

### Step 10.6: Exports + Dependencies

**Modify:** `src/orchestra/security/__init__.py`, `pyproject.toml`
**Depends on:** Steps 10.1-10.5

- Guarded try/except imports for SLMGuard, OutputScanner, Attenuator (same pattern as Rebuff)
- **pyproject.toml:** add `promptshield = ["optimum[onnxruntime]>=1.17", "transformers>=4.51,<5.0"]`
- **Tests:** 2 tests (import with/without optimum)
- **Done when:** Graceful degradation when optimum not installed

---

## Cross-Task Dependencies

```
T-4.8 Step 5 (TieredMemoryManager) ──→ T-4.9 Step B1 (ColdTierBackend protocol)
                                    ──→ T-4.9 Step B2 (wire into tiered mgr)

T-4.10: ZERO dependencies on T-4.8 or T-4.9 (fully independent)

T-4.8 Step 5 adds memory_manager to context.py
T-4.10 Step 1 adds restricted_mode to context.py
  → If executing in parallel, coordinate the context.py edit (both add fields)
```

---

## File Summary

| File | Task | Action | Step |
|------|------|--------|------|
| `src/orchestra/memory/serialization.py` | T-4.8 | Create | 8.1 |
| `src/orchestra/memory/backends.py` | T-4.8 | Create/Modify | 8.2, 8.3 |
| `src/orchestra/memory/tiers.py` | T-4.8 | Create/Modify | 8.2, 8.5, 9.B2 |
| `src/orchestra/memory/singleflight.py` | T-4.8 | Create | 8.4 |
| `src/orchestra/memory/invalidation.py` | T-4.8 | Create | 8.4 |
| `src/orchestra/memory/compression.py` | T-4.9 | Create | 9.A1 |
| `src/orchestra/memory/dedup.py` | T-4.9 | Create | 9.A2 |
| `src/orchestra/memory/vector_store.py` | T-4.9 | Create/Modify | 9.A3, 9.B1 |
| `src/orchestra/security/guard.py` | T-4.10 | Create | 10.2 |
| `src/orchestra/security/output_scanner.py` | T-4.10 | Create | 10.3 |
| `src/orchestra/security/attenuator.py` | T-4.10 | Create | 10.4 |
| `src/orchestra/core/context.py` | T-4.8/10 | Modify | 8.5, 10.1 |
| `src/orchestra/security/guardrails.py` | T-4.10 | Modify | 10.5 |
| `src/orchestra/memory/__init__.py` | T-4.8/9 | Modify | 8.5, 9.A4 |
| `src/orchestra/security/__init__.py` | T-4.10 | Modify | 10.6 |
| `pyproject.toml` | All | Modify | 8.3, 9.A4, 10.6 |

**New files:** 11 source + 12 test = 23 files
**Modified files:** 6 existing files
**Total tests:** ~160 (unit) + ~24 (integration)

---

## Verification

After all 18 steps complete:

```bash
# Full unit suite (should be ~400+ passing)
pytest tests/unit/ -x --timeout=60

# Integration (requires Redis + PostgreSQL+pgvector)
pytest tests/integration/test_redis_tiered_memory.py tests/integration/test_cold_tier.py -x -m integration

# Regression
pytest tests/unit/test_memory.py tests/unit/test_guardrails.py tests/unit/test_acl.py -x

# Import smoke (without optional deps)
python -c "from orchestra.memory import MemoryManager; from orchestra.security import GuardrailChain; print('OK')"
```
