# Phase 4: Enterprise & Scale — Implementation Plan

**Phase:** 04-enterprise-scale
**Goal:** Transform Orchestra from a single-instance production framework into a distributed, enterprise-grade platform with cost-intelligent routing, agent identity (DID), multi-tier memory, interoperability (A2A), NATS messaging, and Kubernetes deployment.
**Status:** Ready for Execution (requires Phase 3 completion)
**Waves:** 6 (progressive layering with maximum parallelism)
**Estimated Tasks:** 19 tasks across 10 plans
**Prerequisites:** Phase 3 complete — FastAPI server, OTel integration, CachedProvider, MemoryManager protocol, guardrails, cost management all operational.

---

## Observable Truths (Goal-Backward)

When Phase 4 is complete, all of the following must be demonstrably true:

| # | Truth | Verification |
|---|-------|--------------|
| T1 | LLM requests are routed to the cheapest model that meets quality/SLA thresholds | `pytest tests/unit/test_cost_router.py` — heuristic routing picks cheaper model for simple prompts |
| T2 | Provider failures trigger automatic failover to alternate providers with circuit breaker | `pytest tests/unit/test_provider_failover.py` — circuit opens after N failures, recovers in HALF_OPEN |
| T3 | Budget state persists across server restarts and is enforced per-tenant | `pytest tests/unit/test_persistent_budget.py` — restart server, budget state restored from DB |
| T4 | Agents have cryptographically verifiable DID-based identities | `pytest tests/unit/test_agent_identity.py` — DID creation, resolution, VC issuance/verification |
| T5 | UCAN tokens delegate bounded capabilities between agents | `pytest tests/unit/test_ucan_delegation.py` — delegation creates attenuated token, verification succeeds |
| T6 | Enterprise users authenticate via OIDC and receive mapped agent identities | `pytest tests/unit/test_oidc_bridge.py` — mock OIDC flow maps claims to AgentIdentity |
| T7 | Memory promotes/demotes across hot/warm/cold tiers based on access patterns | `pytest tests/unit/test_memory_tiers.py` — item accessed N times promotes to hot; TTL expiry demotes |
| T8 | Redis L2 cache shares state across instances with Pub/Sub invalidation | `pytest tests/integration/test_redis_cache.py` — write on instance A invalidates L1 on instance B |
| T9 | Cold-tier vector retrieval returns semantically similar memories via HNSW | `pytest tests/unit/test_vector_retrieval.py` — cosine similarity search returns relevant results |
| T10 | Orchestra serves an A2A Agent Card at `/.well-known/agent.json` | `curl http://localhost:8000/.well-known/agent.json` returns valid Agent Card JSON |
| T11 | External A2A agents can submit tasks and receive streamed results | `pytest tests/integration/test_a2a_protocol.py` — send A2A task, receive SSE completion |
| T12 | NATS JetStream distributes agent tasks to competing consumer workers | `pytest tests/integration/test_nats_messaging.py` — publish task, worker consumes and acks |
| T13 | SPRT detects agent behavioral regression with fewer samples than fixed-N testing | `pytest tests/unit/test_sprt.py` — degraded agent triggers rejection in <50 samples |
| T14 | PromptShield SLM blocks prompt injection with zero added latency on happy path | `pytest tests/unit/test_prompt_shield.py` — injection detected, guard completes before LLM |
| T15 | Helm chart deploys Orchestra server + workers + NATS to a K8s cluster | `helm template orchestra ./deploy/helm/orchestra` renders valid manifests |
| T16 | TypeScript client SDK is generated from OpenAPI spec with full type safety | `npx openapi-typescript http://localhost:8000/openapi.json -o sdk/types.ts` produces types |

---

## Wave Structure

```
Wave 1: [Plan 01] Cost-Aware Routing + Provider Failover
         [Plan 02] Agent Identity (DID + AgentIdentity + VC)
         [Plan 03] Memory Tiers + Redis L2
         (all independent — maximum parallelism)
    |
    v
Wave 2: [Plan 04] UCAN Delegation + OIDC Bridge (depends on Plan 02)
         [Plan 05] Cold Tier Vector + Semantic Cache (depends on Plan 03)
         [Plan 06] Persistent Budget + Billing (depends on Plan 01)
         (3-way parallelism)
    |
    v
Wave 3: [Plan 07] A2A Protocol + Agent Card (depends on Plan 02)
         [Plan 08] SPRT + PromptShield (independent)
         (2-way parallelism)
    |
    v
Wave 4: [Plan 09] NATS JetStream Messaging (depends on Plans 01, 07)
    |
    v
Wave 5: [Plan 10] Kubernetes Deployment + Helm (depends on Plan 09)
    |
    v
Wave 6: [Plan 11] TypeScript SDK (depends on Plan 10)
```

---

## Plan 01: Cost-Aware Routing + Provider Failover

**Wave:** 1
**Dependencies:** None (Phase 3 CostAggregator, BudgetPolicy, ModelCostRegistry are foundation)
**Complexity:** Large
**Requirement IDs:** COST-01, COST-02, COST-03

### Task IDs

**T-4.1: CostAwareRouter with Heuristic Task Classification**

**Files to Create:**
- `src/orchestra/cost/router.py` — CostAwareRouter protocol, HeuristicRouter (Tier 1: classify by token count, tool presence, reasoning depth), RouterDecision dataclass
- `src/orchestra/cost/model_alias.py` — ModelAliasRegistry: logical names ("fast-cheap", "high-accuracy", "balanced") -> concrete model names, configurable via YAML
- `tests/unit/test_cost_router.py`

**Files to Modify:**
- `src/orchestra/cost/__init__.py` — Export CostAwareRouter, HeuristicRouter, ModelAliasRegistry

**Action:**
Create `CostAwareRouter` as a `Protocol` with `select_model(prompt, tools, context) -> RouterDecision`. Implement `HeuristicRouter` using 3-tier classification:
- Simple (token_count < 500, no tools, no chain-of-thought markers) -> cheapest model in alias group
- Moderate (token_count < 2000, <=2 tools) -> mid-tier model
- Complex (everything else) -> top-tier model

`ModelAliasRegistry` maps logical model names to concrete model names with fallback chains. Uses existing `ModelCostRegistry` for pricing lookups. `RouterDecision` includes: selected_model, reason, estimated_cost_usd, alternatives.

`CostAwareRouter` integrates with existing `BudgetPolicy.suggested_model` for budget-driven downgrades. When budget is at soft limit, router automatically selects next-cheapest model that meets quality tier.

**Verify:**
```
pytest tests/unit/test_cost_router.py -x
```

**Done:**
- Simple prompt routes to cheapest model (e.g., haiku/flash)
- Complex prompt routes to top-tier model (e.g., opus/gpt-4o)
- Budget soft limit triggers automatic model downgrade
- Model aliases resolve correctly with fallback chains

---

**T-4.2: Provider Failover with Circuit Breaker + Strategy Switching**

**Files to Create:**
- `src/orchestra/providers/failover.py` — ProviderFailover (wraps multiple providers with circuit breakers, fallback chain, latency tracking)
- `src/orchestra/providers/strategy.py` — ToolCallStrategy protocol, NativeStrategy, PromptedStrategy (for providers without native function calling)
- `src/orchestra/providers/degradation.py` — DegradationDetector: ErrorRateDetector (sliding window), LatencySpikeDetector (p95 tracking), RateLimitDetector (consecutive 429s)
- `tests/unit/test_provider_failover.py`
- `tests/unit/test_strategy_switch.py`

**Files to Modify:**
- `src/orchestra/providers/__init__.py` — Export ProviderFailover, DegradationDetector
- `pyproject.toml` — Add `aiobreaker>=1.2` to reliability deps

**Action:**
Build `ProviderFailover` that wraps a list of `(LLMProvider, CircuitBreaker)` pairs. On each call:
1. Check circuit state — skip OPEN providers
2. Call provider with timeout
3. On success: record latency, close circuit if HALF_OPEN
4. On failure: record failure, check if circuit should open (configurable `fail_max=5`, `reset_timeout=30s`)
5. If all providers exhausted, raise `AllProvidersUnavailableError`

Use `aiobreaker` for async circuit breaking (not pybreaker — sync only).

`ToolCallStrategy` handles transparent switching between native function calling (Anthropic, OpenAI, Google) and prompted+validation fallback (Ollama, some open-source endpoints). `ProviderFailover` auto-detects provider capabilities and applies the correct strategy. Strategy switch is transparent to agents.

`DegradationDetector` components are composable, attached to EventBus as subscribers. They emit `ProviderDegraded` events when thresholds are breached:
- ErrorRateDetector: sliding window of last 100 calls, trigger at >= 40% failure rate
- LatencySpikeDetector: trigger when p95 > 2x baseline
- RateLimitDetector: trigger at >= 3 consecutive HTTP 429s

**Verify:**
```
pytest tests/unit/test_provider_failover.py tests/unit/test_strategy_switch.py -x
```

**Done:**
- Circuit opens after 5 failures, blocks calls for 30s, recovers via HALF_OPEN
- Failover chain tries providers in order, skipping open circuits
- Native-to-prompted strategy switch works transparently for tool calls
- Degradation detectors correctly identify error spikes, latency spikes, and rate limits
- All providers down raises clear `AllProvidersUnavailableError`

---

### Risk Assessment — Plan 01
- **Medium:** aiobreaker library is mature but ensure async compatibility with Orchestra's event loop. Mitigated by existing async codebase patterns.
- **Low:** Heuristic routing is deterministic — no ML training data needed. Thompson Sampling and MF deferred until routing data is collected.

---

## Plan 02: Agent Identity (DID + AgentIdentity + Verifiable Credentials)

**Wave:** 1
**Dependencies:** None
**Complexity:** Large
**Requirement IDs:** IAM-01, IAM-02, IAM-03

### Task IDs

**T-4.3: AgentIdentity + DID Creation and Resolution**

**Files to Create:**
- `src/orchestra/identity/__init__.py` — Exports AgentIdentity, DIDManager, VerifiableCredentialManager
- `src/orchestra/identity/agent_identity.py` — AgentIdentity frozen dataclass (did, controller_did, display_name, roles, capabilities, max_delegation_depth, issued_at, expires_at, verified_credentials)
- `src/orchestra/identity/did.py` — DIDManager: create_did_peer() for ephemeral agents, create_did_web() for organizational agents, resolve_did() for verification
- `src/orchestra/identity/keys.py` — KeyPair generation (Ed25519), SecretProvider protocol for key storage
- `tests/unit/test_agent_identity.py`
- `tests/unit/test_did_manager.py`

**Files to Modify:**
- `src/orchestra/core/context.py` — Add `identity: Optional[AgentIdentity] = None` to AgentContext
- `pyproject.toml` — Add `iam = ["peerdid>=0.5.2", "PyLD>=2.0", "pynacl>=1.5"]` optional dependency

**Action:**
Create `AgentIdentity` as a frozen dataclass carried in `AgentContext`. When `identity` is `None`, agent operates in legacy mode (no IAM enforcement) for backward compatibility.

`DIDManager` handles:
- `create_did_peer(key_pair)` — creates a `did:peer` identifier for ephemeral/cross-org agents using `peerdid` library
- `create_did_web(domain, path)` — creates a `did:web` identifier for organization-controlled agents
- `resolve_did(did_string)` — resolves DID Document, returns public key for verification

Use `peerdid` 0.5.2 for did:peer creation. For did:web, generate DID Document JSON and serve at well-known URL. Store private keys through `SecretProvider` protocol (initially backed by environment variables, Vault integration as optional).

Ed25519 key pairs via `pynacl` (pure Python, no Rust FFI issues unlike didkit which is archived).

**Verify:**
```
pytest tests/unit/test_agent_identity.py tests/unit/test_did_manager.py -x
```

**Done:**
- AgentIdentity is immutable (frozen dataclass) and serializable
- did:peer created and resolved locally without network
- did:web created with proper DID Document structure
- AgentContext carries optional identity (None = legacy mode)
- Key pairs generated and stored via SecretProvider protocol

---

**T-4.4: Verifiable Credentials (Issuance + Verification)**

**Files to Create:**
- `src/orchestra/identity/credentials.py` — VerifiableCredentialManager: issue_capability_vc(), issue_delegation_vc(), verify_vc()
- `src/orchestra/identity/schemas.py` — VC JSON schemas for capability and delegation credentials (W3C VC Data Model 2.0)
- `tests/unit/test_verifiable_credentials.py`

**Action:**
Implement JWT-based Verifiable Credentials using W3C VC Data Model 2.0 (`validFrom`/`validUntil`). Use `joserfc` for JWT signing/verification (modern replacement for python-jose, zero FFI issues).

`VerifiableCredentialManager`:
- `issue_capability_vc(issuer_did, subject_did, capabilities, ttl_hours=24)` — issues a VC asserting agent capabilities (e.g., "tool:web_search", "tool:file_read")
- `issue_delegation_vc(delegator_did, delegate_did, delegated_capabilities, max_depth)` — delegation VC with attenuated capabilities
- `verify_vc(vc_jwt, trusted_issuers)` — verify signature, check expiry, validate issuer chain

Short-lived VCs (1-24 hour validity) for agent sessions. Capability VCs map to Orchestra's existing ACL system as an authorization layer above it.

Add `joserfc>=1.0` to `iam` optional dependencies in pyproject.toml.

**Verify:**
```
pytest tests/unit/test_verifiable_credentials.py -x
```

**Done:**
- Capability VC issued with valid JWT structure and W3C 2.0 fields
- Delegation VC contains attenuated capability subset
- Expired VC fails verification
- Invalid signature fails verification
- Trusted issuer chain validated

---

### Risk Assessment — Plan 02
- **Medium:** DIDKit is archived (July 2025) — using `peerdid` + `pynacl` + `joserfc` instead. More assembly required but no Rust FFI dependency issues.
- **Low:** AgentIdentity integration is additive (Optional field) — zero regression risk.

---

## Plan 03: Memory Tiers + Redis L2 Backplane

**Wave:** 1
**Dependencies:** None (builds on Phase 3 MemoryManager protocol and InMemoryCacheBackend)
**Complexity:** Large
**Requirement IDs:** MEM-01, MEM-02, MEM-03

### Task IDs

**T-4.5: MemoryManager Promote/Demote + HSM Tier Logic**

**Files to Create:**
- `src/orchestra/memory/tiers.py` — MemoryTier enum (HOT, WARM, COLD), TieredMemoryManager (implements MemoryManager protocol with promote/demote)
- `src/orchestra/memory/access_stats.py` — AccessStats tracker: per-key access count, last_accessed, created_at, sliding window counters
- `src/orchestra/memory/policies.py` — SLRUPolicy: promotion trigger (N accesses in T seconds), demotion trigger (TTL expiry per tier), configurable thresholds
- `tests/unit/test_memory_tiers.py`
- `tests/unit/test_access_stats.py`

**Files to Modify:**
- `src/orchestra/memory/__init__.py` — Export TieredMemoryManager, MemoryTier, SLRUPolicy
- `src/orchestra/memory/manager.py` — Extend MemoryManager protocol with `promote(key, to_tier)`, `demote(key, to_tier)`, `get_tier(key)`

**Action:**
Extend Phase 3's `MemoryManager` protocol with tier-aware methods. `TieredMemoryManager` orchestrates three tier backends:
- HOT: In-process dict/TTLCache (L1, <0.01ms, TTL 5min)
- WARM: Pluggable backend (Redis in T-4.6, or dict for testing, TTL 1hr)
- COLD: Pluggable backend (pgvector in Plan 05, or dict for testing, permanent)

`SLRUPolicy` implements SLRU (Segmented LRU):
- Promotion HOT: item accessed >= 3 times within 60s sliding window -> copy to HOT
- Demotion WARM: item not accessed for > TTL -> move to COLD
- Demotion HOT: item not accessed for > TTL -> move to WARM

Background `asyncio.Task` runs periodic SLRU scan (configurable interval, default 30s). Each tier backend implements a `TierBackend` protocol with get/set/delete/keys.

**Verify:**
```
pytest tests/unit/test_memory_tiers.py tests/unit/test_access_stats.py -x
```

**Done:**
- Items start in WARM tier by default on store()
- 3+ accesses in 60s promotes to HOT
- TTL expiry demotes HOT->WARM->COLD
- Background task runs periodic scans
- Protocol remains backward-compatible (InMemoryMemoryManager still works)

---

**T-4.6: Redis L2 Cache Backend with Pub/Sub Invalidation**

**Files to Create:**
- `src/orchestra/cache/redis_backend.py` — RedisCacheBackend (implements CacheBackend protocol), L1L2CacheManager (L1 TTLCache + L2 Redis with write-through)
- `src/orchestra/cache/invalidation.py` — PubSubInvalidator: publishes invalidation events on write/delete to `orchestra:cache:invalidate` channel, subscribes and evicts L1 on receive
- `src/orchestra/memory/redis_tier.py` — RedisTierBackend (implements TierBackend for WARM tier in TieredMemoryManager)
- `tests/unit/test_redis_cache_backend.py` (mocked Redis)
- `tests/integration/test_redis_cache.py` (requires Redis)

**Files to Modify:**
- `pyproject.toml` — Add `redis = ["redis[hiredis]>=5.0"]` optional dependency
- `src/orchestra/cache/__init__.py` — Export RedisCacheBackend, L1L2CacheManager

**Action:**
Build `RedisCacheBackend` implementing existing `CacheBackend` protocol using `redis.asyncio` (async client built into redis-py 5.x+). Use `redis[hiredis]` for C-accelerated parsing.

`L1L2CacheManager` implements write-through strategy:
1. On write: write to Redis L2 first, then L1, then publish invalidation
2. On read: check L1 first (fast), miss -> check L2, miss -> return None
3. On invalidation receive: evict from L1

`PubSubInvalidator` uses Redis Pub/Sub channel `orchestra:cache:invalidate`. Messages contain cache key + operation (set/delete). Each instance subscribes on startup and evicts matching L1 entries. Pub/Sub is best-effort — short L1 TTLs (30-60s) as safety net for missed messages.

`RedisTierBackend` provides the WARM tier backend for `TieredMemoryManager`, storing serialized memory entries with TTL.

Serialization via `msgpack` (30-50% smaller than JSON, faster). Add `msgpack>=1.0` to redis optional dependency.

**Verify:**
```
pytest tests/unit/test_redis_cache_backend.py -x
pytest tests/integration/test_redis_cache.py -x  # requires Redis
```

**Done:**
- L1 hit returns in <0.01ms, L2 hit in <2ms
- Write-through ensures L2 always has latest data
- Pub/Sub invalidation evicts stale L1 entries across instances
- RedisTierBackend works as WARM tier in TieredMemoryManager
- CacheBackend protocol fully satisfied (drop-in for InMemoryCacheBackend)

---

### Risk Assessment — Plan 03
- **Medium:** Redis Pub/Sub is best-effort (no delivery guarantee). Mitigated by short L1 TTLs and write-through L2.
- **Low:** TieredMemoryManager builds on proven MemoryManager protocol from Phase 3.

---

## Plan 04: UCAN Delegation + OIDC Bridge

**Wave:** 2
**Dependencies:** Plan 02 (AgentIdentity, DID, VC infrastructure)
**Complexity:** Medium
**Requirement IDs:** IAM-04, IAM-05

### Task IDs

**T-4.7: UCAN Capability Delegation**

**Files to Create:**
- `src/orchestra/identity/ucan.py` — UCANManager: create_ucan(issuer, audience, capabilities, ttl), delegate_ucan(parent_ucan, sub_capabilities), verify_ucan(token, required_capabilities)
- `src/orchestra/identity/capabilities.py` — OrchestraCapability enum/dataclass: resource URIs (e.g., `orchestra://tools/web_search`), abilities (e.g., `tool/invoke`, `memory/read`, `memory/write`), caveats (time-bound, call-count limit)
- `tests/unit/test_ucan_delegation.py`

**Files to Modify:**
- `src/orchestra/identity/__init__.py` — Export UCANManager, OrchestraCapability
- `pyproject.toml` — Add `py-ucan>=1.0.0` to iam deps

**Action:**
Build `UCANManager` using `py-ucan` 1.0.0 (Pydantic v2 models). UCAN sits as an authorization layer ABOVE existing ACL system:
- ACLs are the "root" authority (what an agent CAN do)
- UCANs are delegation tokens derived from ACL-granted capabilities
- Delegation creates attenuated tokens: sub-agent gets subset of parent's capabilities

`OrchestraCapability` uses resource URIs: `orchestra://tools/{tool_name}`, `orchestra://memory/{tier}`, `orchestra://graphs/{graph_name}`. Abilities: `tool/invoke`, `memory/read`, `memory/write`, `graph/execute`.

Caveats support: time-bound (single session), call-count limit (max 10 tool invocations), scope restriction (read-only).

Delegation chain verification: verify ENTIRE chain of signatures back to root authority. Max delegation depth enforced (default 3).

**Verify:**
```
pytest tests/unit/test_ucan_delegation.py -x
```

**Done:**
- UCAN token created with capability claims and DID principals
- Delegation creates attenuated token with subset capabilities
- Verification checks signature chain, expiry, and capability containment
- Max delegation depth enforced
- Caveats (time-bound, call-count) respected

---

**T-4.8: OIDC Bridge (Enterprise IdP Integration)**

**Files to Create:**
- `src/orchestra/identity/oidc.py` — OIDCBridge: validate_token(), map_claims_to_identity(), create_agent_identity_from_oidc()
- `src/orchestra/identity/claim_mapping.py` — ClaimMappingConfig: YAML-configurable mapping from OIDC claims (sub, roles, groups) to Orchestra capabilities
- `src/orchestra/server/routes/auth.py` — POST /api/v1/auth/oidc (token exchange endpoint)
- `tests/unit/test_oidc_bridge.py`

**Files to Modify:**
- `src/orchestra/server/routes/__init__.py` — Register auth router
- `pyproject.toml` — Add `Authlib>=1.6.9` to iam deps

**Action:**
Build `OIDCBridge` using `Authlib` 1.6.9 for OIDC token validation and JWKS fetching. The bridge:
1. Validates id_token signature against IdP JWKS (cached with 10-min TTL)
2. Extracts claims (sub, roles/groups — handle provider-specific claim names: `roles` for Azure, `groups` for Okta, `realm_access.roles` for Keycloak)
3. Maps OIDC roles to Orchestra capabilities via `ClaimMappingConfig`
4. Creates/resolves agent DID: `did:web:{issuer_domain}:users:{sub_hash}`
5. Returns `AgentIdentity` with mapped roles and capabilities

`POST /api/v1/auth/oidc` accepts `{"id_token": "..."}`, validates, returns `AgentIdentity` with session JWT for subsequent API calls.

Provider-specific extraction handled via configurable `ClaimMappingConfig` (YAML). Default mappings provided for Azure AD, Okta, Auth0, Keycloak.

**Verify:**
```
pytest tests/unit/test_oidc_bridge.py -x
```

**Done:**
- Valid OIDC token maps to AgentIdentity with correct capabilities
- Invalid/expired token returns 401
- Provider-specific claim extraction works for Azure, Okta, Auth0
- JWKS cached with TTL
- Claim-to-capability mapping is YAML-configurable

---

### Risk Assessment — Plan 04
- **Medium:** OIDC provider differences in claim names. Mitigated by configurable ClaimMappingConfig with tested defaults for major providers.
- **Low:** py-ucan is PyPI 1.0.0 release with Pydantic v2 — stable foundation.

---

## Plan 05: Cold Tier Vector Retrieval + Semantic Cache

**Wave:** 2
**Dependencies:** Plan 03 (TieredMemoryManager, TierBackend protocol)
**Complexity:** Medium
**Requirement IDs:** MEM-04, MEM-05

### Task IDs

**T-4.9: Cold Tier HNSW Vector Retrieval**

**Files to Create:**
- `src/orchestra/memory/vector_store.py` — VectorStore protocol, HNSWVectorStore (hnswlib-backed), embedding helpers
- `src/orchestra/memory/cold_tier.py` — ColdTierBackend (implements TierBackend using VectorStore for semantic retrieval + SQLite/file for persistence)
- `src/orchestra/memory/embeddings.py` — EmbeddingProvider protocol, Model2VecEmbedder (fast static embeddings, 500x faster than sentence-transformers), SentenceTransformerEmbedder (higher quality fallback)
- `tests/unit/test_vector_retrieval.py`
- `tests/unit/test_embeddings.py`

**Files to Modify:**
- `src/orchestra/memory/__init__.py` — Export VectorStore, ColdTierBackend, EmbeddingProvider
- `pyproject.toml` — Add `memory-vector = ["hnswlib>=0.8", "model2vec>=0.3"]` optional dependency

**Action:**
Build cold-tier memory retrieval using HNSW approximate nearest neighbor search.

`VectorStore` protocol: `add(id, embedding, metadata)`, `search(embedding, k, threshold) -> list[SearchResult]`, `delete(id)`.

`HNSWVectorStore` wraps `hnswlib` with parameters: M=16, ef_construction=200, ef_search=100 (>95% recall at sub-10ms for 1M vectors). Index persisted to file, loaded on startup.

`EmbeddingProvider` protocol: `embed(text) -> list[float]`, `embed_batch(texts) -> list[list[float]]`.
- `Model2VecEmbedder` uses `potion-base-8M` (50x smaller, 500x faster than sentence-transformers). Default for real-time operations.
- `SentenceTransformerEmbedder` uses `all-MiniLM-L6-v2` (384 dims). Optional higher-quality fallback.

`ColdTierBackend` implements TierBackend for TieredMemoryManager's COLD tier:
- `store()`: embed text, add to HNSW index, persist metadata to SQLite
- `retrieve(key)`: exact key lookup from SQLite
- `search(query, limit)`: embed query, search HNSW, return top-k with scores

Hybrid retrieval formula: `score = similarity * 0.7 + recency * 0.2 + importance * 0.1` where recency = 0.5^(age_days / half_life_days).

**Verify:**
```
pytest tests/unit/test_vector_retrieval.py tests/unit/test_embeddings.py -x
```

**Done:**
- HNSW index returns semantically similar items with cosine similarity
- Sub-10ms query latency at 10K entries
- Index persists to disk and loads on restart
- Hybrid scoring combines similarity + recency + importance
- Model2Vec embedding works without GPU

---

**T-4.10: Semantic Cache Extension**

**Files to Create:**
- `src/orchestra/cache/semantic.py` — SemanticCacheBackend (extends CacheBackend with embedding-based lookup), configurable similarity threshold (default 0.85)
- `tests/unit/test_semantic_cache.py`

**Files to Modify:**
- `src/orchestra/cache/__init__.py` — Export SemanticCacheBackend

**Action:**
Extend `CacheBackend` with semantic lookup capability. On `get()`:
1. Try exact hash match first (fast, existing behavior)
2. If miss, compute embedding of query, search HNSW index of cached queries
3. If nearest neighbor similarity >= threshold (default 0.85), return cached response
4. Otherwise return None (cache miss)

On `set()`: store response under exact hash key AND add query embedding to HNSW index.

Uses same `EmbeddingProvider` and `HNSWVectorStore` from T-4.9. Configurable per-agent thresholds: 0.90 for safety-critical, 0.85 for general, 0.80 for aggressive caching.

Expected results at 0.85 threshold: ~50% hit rate with very good accuracy, significant LLM cost reduction.

**Verify:**
```
pytest tests/unit/test_semantic_cache.py -x
```

**Done:**
- Exact match still works (backward compatible)
- Semantically similar queries (>= 0.85 cosine) return cached response
- Below-threshold queries miss as expected
- Per-agent threshold configuration works
- Cache hit rate and cost savings measurable

---

### Risk Assessment — Plan 05
- **Low:** hnswlib is mature (5k stars), header-only C++ with Python bindings. Well-tested for sub-10ms at scale.
- **Medium:** Model2Vec embedding quality. Mitigated by fallback to sentence-transformers and configurable thresholds.

---

## Plan 06: Persistent Budget + Billing Foundation

**Wave:** 2
**Dependencies:** Plan 01 (CostAwareRouter, ModelCostRegistry extended)
**Complexity:** Medium
**Requirement IDs:** COST-04, COST-05

### Task IDs

**T-4.11: Per-Tenant Persistent Budget Tracking**

**Files to Create:**
- `src/orchestra/cost/persistent_budget.py` — PersistentBudgetPolicy (extends BudgetPolicy with SQLite-backed double-entry ledger), BudgetLedger
- `src/orchestra/cost/tenant.py` — TenantConfig dataclass (tenant_id, soft_limit_usd, hard_limit_usd, period, markup_pct)
- `tests/unit/test_persistent_budget.py`

**Files to Modify:**
- `src/orchestra/cost/__init__.py` — Export PersistentBudgetPolicy, TenantConfig
- `src/orchestra/cost/aggregator.py` — Add `tenant_id` field to cost event recording (~5 lines)

**Action:**
Build `PersistentBudgetPolicy` extending Phase 3's `BudgetPolicy`:
- SQLite-backed double-entry ledger: every budget change creates debit (cost) and credit (allocation)
- `check(tenant_id)` reads cached balance (optimistic caching with 1s TTL)
- `record_spend(tenant_id, amount_usd, run_id, model)` appends debit entry
- `add_credit(tenant_id, amount_usd, description)` appends credit entry
- `get_balance(tenant_id)` returns current balance = sum of all entries

Budget periods: daily, weekly, monthly. Auto-reset by creating a credit entry at period start equal to period budget.

Use optimistic caching (Option B from research): check against cached balance, deduct from cache, reconcile with DB periodically. Hard limit set at 95% of actual budget to absorb cache-window overspend.

Tenant ID propagation via OTel Baggage: set `tenant_id` at API entry point, propagates through all child spans. Use existing OTel infrastructure from Phase 3.

**Verify:**
```
pytest tests/unit/test_persistent_budget.py -x
```

**Done:**
- Budget state persists across server restarts (SQLite)
- Double-entry ledger maintains complete audit trail
- Soft limit triggers warning + model downgrade
- Hard limit blocks LLM calls
- Budget auto-resets at period boundary
- Tenant ID tracked in cost events

---

**T-4.12: Billing Records + Cost Attribution**

**Files to Create:**
- `src/orchestra/cost/billing.py` — BillingAggregator (EventBus subscriber: records per-call billing records with tenant_id, model, tokens, cost_usd, markup), BillingReport generator
- `src/orchestra/cli/billing.py` — CLI commands: `orchestra billing report --tenant T --period 2026-03`, `orchestra billing summary`
- `tests/unit/test_billing.py`

**Files to Modify:**
- `src/orchestra/cli/main.py` — Register billing subcommand
- `src/orchestra/cost/__init__.py` — Export BillingAggregator

**Action:**
Build `BillingAggregator` as an EventBus subscriber (same pattern as `CostAggregator`). On each `LLMCalled` event:
1. Extract tenant_id from OTel Baggage or ExecutionContext
2. Record billing entry: tenant_id, run_id, model, input_tokens, output_tokens, cost_usd, markup_pct, billed_usd, timestamp
3. Store in SQLite `billing_records` table

`BillingReport` generates per-tenant-per-period reports:
- Total cost, total billed (with markup), breakdown by model
- Top-N most expensive runs
- Cost trend vs previous period

CLI commands provide quick access to billing data. Stripe integration deferred (optional future plugin).

Mandatory attribution tags per research: tenant_id, task_type, model_alias, run_id.

**Verify:**
```
pytest tests/unit/test_billing.py -x
```

**Done:**
- Every LLM call generates a billing record with tenant attribution
- Billing report shows per-tenant totals with model breakdown
- Markup percentage applied correctly
- CLI generates readable reports
- Wasted spend categories tracked separately (failed retries, guardrail-caught hallucinations)

---

### Risk Assessment — Plan 06
- **Low:** SQLite ledger is proven pattern (same backend as EventStore). Double-entry accounting is well-understood.
- **Low:** BillingAggregator follows same EventBus subscriber pattern as CostAggregator.

---

## Plan 07: A2A Protocol + Agent Card

**Wave:** 3
**Dependencies:** Plan 02 (AgentIdentity for Agent Card identity fields)
**Complexity:** Medium
**Requirement IDs:** A2A-01, A2A-02

### Task IDs

**T-4.13: A2A Agent Card + Discovery Endpoint**

**Files to Create:**
- `src/orchestra/interop/__init__.py` — Exports AgentCard, A2AServer
- `src/orchestra/interop/agent_card.py` — AgentCardBuilder: generates A2A-compliant Agent Card from GraphRegistry, populates skills from registered graphs, includes identity/security/capability fields
- `src/orchestra/server/routes/a2a.py` — GET `/.well-known/agent.json` (Agent Card), POST `/a2a/tasks` (task submission), GET `/a2a/tasks/{id}` (task status), GET `/a2a/tasks/{id}/stream` (SSE streaming)
- `tests/unit/test_agent_card.py`
- `tests/integration/test_a2a_protocol.py`

**Files to Modify:**
- `src/orchestra/server/app.py` — Mount A2A routes
- `src/orchestra/server/routes/__init__.py` — Register a2a router
- `pyproject.toml` — Add `a2a = ["a2a-sdk>=0.3.24"]` optional dependency

**Action:**
Build A2A protocol integration following Google's A2A spec v0.3:

`AgentCardBuilder` dynamically generates Agent Card from `GraphRegistry`:
- Identity: name, description, version from app config
- Skills: each registered graph becomes an `AgentSkill` with name, description, example prompts
- Interfaces: HTTP (JSON-RPC 2.0) + SSE streaming
- Security: OAuth2 scheme (when OIDC bridge active), none (dev mode)
- Capabilities: streaming=true, pushNotifications=false
- Extensions: cost profiles (estimated cost per skill from ModelCostRegistry)

Serve at `/.well-known/agent.json` (required A2A discovery endpoint).

A2A task lifecycle maps to Orchestra run lifecycle:
- `submitted` -> PENDING
- `working` -> RUNNING
- `input-required` -> INTERRUPTED (HITL)
- `completed` -> COMPLETED
- `failed` -> FAILED

A2A task submission translates to `POST /api/v1/runs` internally. SSE streaming uses same infrastructure as existing `/runs/{id}/stream`.

Use `a2a-sdk` 0.3.24 for AgentCard/AgentSkill models and JSON-RPC message types. Custom routing layer maps A2A tasks to graph executions.

**Verify:**
```
pytest tests/unit/test_agent_card.py tests/integration/test_a2a_protocol.py -x
curl http://localhost:8000/.well-known/agent.json
```

**Done:**
- Agent Card JSON at `/.well-known/agent.json` passes A2A schema validation
- Skills auto-generated from registered graphs
- A2A task submission creates an Orchestra run
- Task status reflects run lifecycle
- SSE streaming works for A2A clients
- Cost profiles included as extensions

---

### Risk Assessment — Plan 07
- **Low:** A2A SDK is official Google/Linux Foundation project, v0.3 stable. Mapping to Orchestra's existing run lifecycle is natural.
- **Medium:** A2A spec may evolve — use SDK types rather than hardcoding to absorb future changes.

---

## Plan 08: SPRT Statistical Testing + PromptShield

**Wave:** 3
**Dependencies:** None (testing/safety infrastructure independent of other Wave 3 work)
**Complexity:** Medium
**Requirement IDs:** TEST-01, TEST-02, SAFE-01

### Task IDs

**T-4.14: SPRT Binomial + Behavioral Fingerprinting**

**Files to Create:**
- `src/orchestra/testing/sprt.py` — SPRTBinomial class: update(observation: bool) -> Decision (ACCEPT_H0, REJECT_H0, CONTINUE), configurable alpha/beta/p0/p1/N_max. ~100 lines. Uses `scipy.stats.binom.logpmf()`
- `src/orchestra/testing/fingerprint.py` — BehavioralFingerprint: extracts features from execution traces (tool call frequency, response length distribution, latency stats, error rates, reasoning chain length). DriftMonitor: compares fingerprints using KS test + KL divergence
- `src/orchestra/testing/decorators.py` — `@run_n_times(n)` decorator for majority-vote testing, `@sprt_test(p0, p1)` decorator for adaptive sample testing
- `tests/unit/test_sprt.py`
- `tests/unit/test_behavioral_fingerprint.py`

**Files to Modify:**
- `src/orchestra/testing/__init__.py` — Export SPRTBinomial, BehavioralFingerprint, DriftMonitor

**Action:**
Build custom `SPRTBinomial` (~100 lines, no heavy library needed):
1. H0: agent success rate = p0 (baseline, e.g., 0.92)
2. H1: agent success rate = p1 (degraded, e.g., 0.85)
3. Boundaries: A = (1-beta)/alpha, B = beta/(1-alpha), default alpha=beta=0.05
4. After each observation: update log-likelihood ratio
5. Ratio > A -> reject H0 (degradation detected), ratio < B -> accept H0 (agent OK)
6. Cap at N_max (default 100) for truncation

Use three-valued verdicts: ACCEPT, REJECT, INCONCLUSIVE (per research: mathematically necessary for stochastic agents).

`BehavioralFingerprint` extracts 6 feature families from execution traces:
1. Tool usage distribution
2. Structural complexity (trace length, nesting depth)
3. Output characteristics (token counts)
4. Reasoning patterns (action type distributions)
5. Error/recovery rates
6. Efficiency metrics (cost per step, latency)

`DriftMonitor` detects behavioral regression:
- KS test for continuous features (latency, response length): `scipy.stats.ks_2samp()`
- KL divergence for categorical features (tool usage, error types): `scipy.stats.entropy()`
- Composite drift score with configurable thresholds

**Verify:**
```
pytest tests/unit/test_sprt.py tests/unit/test_behavioral_fingerprint.py -x
```

**Done:**
- SPRT detects degradation (p1=0.85) in fewer samples than fixed-N (N=50)
- SPRT correctly accepts stable agent (p0=0.92) quickly
- Behavioral fingerprint extracts all 6 feature families from traces
- Drift monitor detects statistically significant changes
- Three-valued verdicts (ACCEPT, REJECT, INCONCLUSIVE) supported
- Test decorators work with pytest

---

**T-4.15: PromptShield SLM Guard**

**Files to Create:**
- `src/orchestra/security/prompt_shield.py` — PromptShieldGuard: loads SLM classifier (Meta Prompt Guard 86M or protectai/deberta-v3-base-v2), async parallel execution pattern, configurable threshold
- `src/orchestra/security/guarded_call.py` — `guarded_agent_call()`: parallel guard + LLM call, cancel LLM if injection detected (zero added latency on happy path)
- `tests/unit/test_prompt_shield.py`

**Files to Modify:**
- `src/orchestra/security/__init__.py` — Export PromptShieldGuard
- `pyproject.toml` — Add `prompt-shield = ["transformers>=4.40", "torch>=2.0"]` optional dependency (or `onnxruntime>=1.17` for CPU optimization)

**Action:**
Build `PromptShieldGuard` implementing the parallel execution pattern from research:

```python
async def guarded_agent_call(prompt, agent):
    guard_task = asyncio.create_task(run_injection_guard(prompt))  # ~10-50ms
    llm_task = asyncio.create_task(agent.call_llm(prompt))          # ~500-3000ms
    guard_result = await guard_task
    if guard_result.is_injection:
        llm_task.cancel()
        raise PromptInjectionDetected(guard_result)
    return await llm_task
```

Guard is always faster than LLM call -> zero latency overhead on happy path.

Model options (configurable):
- `meta-llama/Prompt-Guard-86M` (86M params, fastest)
- `protectai/deberta-v3-base-v2` (184M params, highest accuracy)

Default to Prompt Guard 86M for speed. Load model lazily on first call. Support ONNX Runtime for CPU optimization (2-4x speedup).

Integrates with existing `GuardrailChain` as a `Guardrail` with `on_fail=BLOCK`.

For RAG scenarios, apply 4-step indirect injection mitigation:
1. Isolation: XML delimiters for system/user/retrieved content
2. Context anchoring: bind instructions to system prompt
3. Treat retrieved data as informational only
4. Restricted tool-calling scopes for RAG agents

**Verify:**
```
pytest tests/unit/test_prompt_shield.py -x
```

**Done:**
- Known injection prompt detected and blocked
- Clean prompt passes through without delay
- Guard completes before LLM on happy path (parallel execution)
- LLM task cancelled on injection detection
- Integrates with GuardrailChain (on_fail=BLOCK)
- Model loads lazily, ONNX Runtime supported for CPU

---

### Risk Assessment — Plan 08
- **Low:** SPRT is ~100 lines of scipy-backed math. Well-understood algorithm.
- **Medium:** PromptShield SLM requires torch or onnxruntime dependency (~500MB+). Mitigated by making it an optional dependency group, lazy loading, and ONNX CPU path.

---

## Plan 09: NATS JetStream Messaging

**Wave:** 4
**Dependencies:** Plan 01 (CostAwareRouter for task routing), Plan 07 (A2A for external task ingestion)
**Complexity:** Large
**Requirement IDs:** INFRA-01, INFRA-02

### Task IDs

**T-4.16: NATS JetStream Producer + Consumer**

**Files to Create:**
- `src/orchestra/messaging/__init__.py` — Exports NATSBroker, TaskProducer, TaskConsumer
- `src/orchestra/messaging/broker.py` — NATSBroker: connection management, stream creation (agent-tasks, agent-events), subject namespacing (orchestra.tasks.{agent_type})
- `src/orchestra/messaging/producer.py` — TaskProducer: publish task to JetStream with idempotent dedup (Nats-Msg-Id header), configurable retention (workqueue for tasks, limits for events)
- `src/orchestra/messaging/consumer.py` — TaskConsumer: pull consumer with explicit ack, max_deliver=3 with exponential backoff via nak(delay), configurable concurrency
- `src/orchestra/messaging/worker.py` — AgentWorker: competing consumer pattern — receives task from NATS, executes via CompiledGraph.run(), publishes result, acks message
- `docker-compose.nats.yml` — NATS server with JetStream enabled for local dev
- `tests/unit/test_nats_messaging.py` (mocked)
- `tests/integration/test_nats_messaging.py` (requires NATS)

**Files to Modify:**
- `pyproject.toml` — Add `messaging = ["nats-py>=2.14"]` optional dependency
- `src/orchestra/server/app.py` — Optional NATS connection in lifespan manager

**Action:**
Build NATS JetStream integration for distributed agent task execution:

`NATSBroker` manages NATS connection lifecycle:
- Connect with retry and reconnect callbacks
- Create streams: `agent-tasks` (workqueue retention, file storage) for task distribution, `agent-events` (limits retention) for event fan-out
- Subject hierarchy: `orchestra.tasks.{agent_type}` for targeted routing, `orchestra.events.>` for monitoring

`TaskProducer` publishes tasks with:
- Idempotent dedup via `Nats-Msg-Id` header + stream `duplicate_window=60s`
- Payload: serialized task dict (< 1MB, reference large payloads via storage URLs)
- Ack from JetStream confirms storage before returning

`TaskConsumer` implements pull consumer (preferred for agent workers):
- Durable consumer with explicit ack
- `max_deliver=3` with `nak(delay)` exponential backoff (5s, 15s, 45s)
- `ack_wait` set longer than max agent execution time (default 300s)
- Batch fetch (10 messages) for efficiency

`AgentWorker` is the competing consumer:
- Subscribes to `orchestra.tasks.{agent_type}`
- Receives task, resolves graph from GraphRegistry, executes
- Publishes result to `orchestra.results.{task_id}`
- On error: nak with delay for retry, publish error event

NATS discovery via request/reply: agents announce capabilities on `orchestra.discovery.ping`, consumers respond with agent type and status.

**Verify:**
```
pytest tests/unit/test_nats_messaging.py -x
pytest tests/integration/test_nats_messaging.py -x  # requires NATS server
docker compose -f docker-compose.nats.yml up -d  # local NATS
```

**Done:**
- Task published to JetStream with ack (guaranteed storage)
- Worker consumes task, executes graph, publishes result
- Failed tasks retry with exponential backoff (max 3 retries)
- Multiple workers compete for same task (exactly-once processing)
- Agent discovery via request/reply works
- Message size < 1MB enforced

---

### Risk Assessment — Plan 09
- **Medium:** NATS clustering requires 3 nodes for Raft consensus in production. Single-node fine for dev/test. Helm chart (Plan 10) handles production topology.
- **Low:** nats-py 2.14 is async-native and well-documented. Pull consumer pattern is straightforward.

---

## Plan 10: Kubernetes Deployment + Helm Chart

**Wave:** 5
**Dependencies:** Plan 09 (NATS messaging for worker deployment)
**Complexity:** Large
**Requirement IDs:** INFRA-03, INFRA-04, INFRA-05

### Task IDs

**T-4.17: Helm Chart for Orchestra Deployment**

**Files to Create:**
- `deploy/helm/orchestra/Chart.yaml` — Helm chart metadata (v0.1.0)
- `deploy/helm/orchestra/values.yaml` — Default values (replicas, image, resources, NATS, Redis, PostgreSQL)
- `deploy/helm/orchestra/templates/deployment-server.yaml` — Orchestra FastAPI server deployment
- `deploy/helm/orchestra/templates/deployment-worker.yaml` — Agent worker deployment with NATS consumer
- `deploy/helm/orchestra/templates/service.yaml` — ClusterIP service for server
- `deploy/helm/orchestra/templates/configmap.yaml` — Configuration (model aliases, claim mappings)
- `deploy/helm/orchestra/templates/hpa.yaml` — HPA for workers (KEDA ScaledObject if KEDA available, standard HPA fallback)
- `deploy/helm/orchestra/templates/health-probes.yaml` — Liveness/readiness/startup probes
- `deploy/helm/orchestra/templates/ingress.yaml` — Optional ingress with TLS
- `deploy/helm/orchestra/templates/serviceaccount.yaml`
- `deploy/helm/orchestra/templates/_helpers.tpl` — Template helpers
- `deploy/helm/orchestra/templates/NOTES.txt` — Post-install instructions
- `deploy/docker/Dockerfile` — Multi-stage build (builder + runtime)
- `deploy/docker/Dockerfile.worker` — Worker image variant
- `deploy/docker/.dockerignore`

**Action:**
Create production-ready Helm chart for Kubernetes deployment:

**Server deployment:**
- FastAPI server with configurable replicas (default 2)
- Liveness: `/healthz` (event loop responsive), Readiness: `/readyz` (DB + NATS connected), Startup: 30s grace for initialization
- Resource requests: 500m CPU, 512Mi memory; limits: 2 CPU, 2Gi memory
- Environment: from ConfigMap + Secrets

**Worker deployment:**
- Agent workers consuming from NATS
- HPA based on NATS queue depth: `lagThreshold=10`, min 0 (scale-to-zero), max 20
- KEDA `nats-jetstream` trigger when KEDA available, standard CPU-based HPA fallback
- Resource requests: 250m CPU, 256Mi memory; limits: 1 CPU, 1Gi memory

**Dependencies (subcharts or external):**
- NATS: `nats/nats` Helm chart (JetStream enabled)
- Redis: `bitnami/redis` chart (for L2 cache)
- PostgreSQL: `bitnami/postgresql` chart (for EventStore + vector)

**Docker images:**
- Multi-stage build: Python 3.12-slim builder + runtime
- Non-root user, health check endpoint
- Separate server and worker images (shared base)

**Health probes:**
- Liveness: httpGet `/healthz` (15s period, 3 failure threshold)
- Readiness: httpGet `/readyz` (10s period, checks DB + NATS + Redis)
- Startup: httpGet `/healthz` (5s period, 30 failure threshold = 150s max startup)

**Verify:**
```
helm template orchestra ./deploy/helm/orchestra --set nats.enabled=true
helm lint ./deploy/helm/orchestra
docker build -f deploy/docker/Dockerfile -t orchestra:test .
```

**Done:**
- `helm template` renders valid K8s manifests without errors
- `helm lint` passes
- Docker image builds successfully
- Server deployment has proper health probes
- Worker deployment has HPA configuration
- Values.yaml has sensible defaults with full override capability
- NOTES.txt provides post-install connection instructions

---

**T-4.18: OTel Collector Pipeline + Prometheus Exporter**

**Files to Create:**
- `deploy/helm/orchestra/templates/otel-collector.yaml` — OTel Collector DaemonSet config (agent-tier)
- `deploy/helm/orchestra/templates/servicemonitor.yaml` — ServiceMonitor for Prometheus scraping
- `src/orchestra/observability/prometheus.py` — PrometheusMetricReader setup, LLM-optimized histogram buckets, AI Golden Signals
- `deploy/otel/collector-config.yaml` — 2-tier collector pipeline (agent + gateway)
- `tests/unit/test_prometheus_metrics.py`

**Files to Modify:**
- `src/orchestra/observability/__init__.py` — Export Prometheus setup
- `src/orchestra/observability/_otel_setup.py` — Add PrometheusMetricReader as optional reader
- `pyproject.toml` — Add `prometheus = ["opentelemetry-exporter-prometheus>=0.45b0"]`

**Action:**
Build OTel Collector pipeline configuration and Prometheus metrics exporter (deferred from Phase 3):

**Prometheus exporter:**
- `PrometheusMetricReader` exposes `/metrics` endpoint on port 9464
- LLM-optimized histogram buckets: `[100, 250, 500, 1000, 2500, 5000, 10000, 30000, 60000, 120000]` ms
- AI Golden Signals:
  - `gen_ai.client.operation.duration` (Histogram) — model, provider, operation
  - `gen_ai.client.token.usage` (Counter) — model, token_type (input/output/cache)
  - `gen_ai.client.operation.errors` (Counter) — error_type
  - `orchestra.cost_usd` (Counter) — model, service_name
- High-cardinality warning enforced: NO tenant_id/user_id as metric labels (use span attributes)

**Collector pipeline (2-tier):**
- Agent tier (DaemonSet): memory_limiter -> batch -> OTLP export to gateway
- Gateway tier (Deployment): memory_limiter -> filter (drop health checks) -> redaction (PII) -> tail_sampling -> batch -> export (Jaeger/Tempo + Prometheus)

**Tail sampling policies:**
- Always keep: errors (status_code=ERROR), slow traces (>10s), high-cost (orchestra.cost_tier=high)
- Sample 10% of normal traces
- Expected volume reduction: 85-90% with 100% error/slow retention

**Verify:**
```
pytest tests/unit/test_prometheus_metrics.py -x
curl http://localhost:9464/metrics  # Prometheus endpoint
```

**Done:**
- `/metrics` endpoint exposes AI Golden Signals
- Histogram buckets optimized for LLM latency distribution
- Collector config passes `otelcol validate` (if collector binary available)
- Tail sampling retains 100% errors and slow traces
- PII redaction processor strips sensitive attributes

---

### Risk Assessment — Plan 10
- **Medium:** Helm chart complexity. Mitigated by using established patterns (bitnami subcharts, standard templates).
- **Low:** OTel Collector config is declarative YAML — well-documented.
- **Medium:** Docker build may encounter dependency issues with native extensions (hnswlib, pynacl). Mitigated by multi-stage build with explicit build deps.

---

## Plan 11: TypeScript Client SDK

**Wave:** 6
**Dependencies:** Plan 10 (stable OpenAPI spec from deployed server)
**Complexity:** Small
**Requirement IDs:** SDK-01

### Task IDs

**T-4.19: TypeScript SDK Generation from OpenAPI**

**Files to Create:**
- `sdk/typescript/package.json` — npm package for generated SDK
- `sdk/typescript/tsconfig.json` — TypeScript config (strict mode)
- `sdk/typescript/src/index.ts` — Re-exports generated types + client
- `sdk/typescript/src/client.ts` — Thin wrapper around openapi-fetch with SSE streaming helper
- `sdk/typescript/README.md` — Usage documentation
- `scripts/generate-sdk.sh` — Automation script: extract OpenAPI spec from running server, generate types
- `tests/sdk/test_typescript_types.ts` — Type-level tests (tsc --noEmit)

**Action:**
Generate type-safe TypeScript SDK using `openapi-typescript` + `openapi-fetch` (zero runtime cost, 6kb):

1. Extract OpenAPI spec: `curl http://localhost:8000/openapi.json -o sdk/typescript/openapi.json`
2. Generate types: `npx openapi-typescript openapi.json -o src/types.gen.ts`
3. Create thin client wrapper using `openapi-fetch`:
   - `createOrchestraClient(baseUrl)` — returns typed client
   - `streamRun(runId)` — SSE streaming via async generator over response body
   - `submitA2ATask(card, task)` — A2A task submission helper

SSE streaming implemented as async generator:
```typescript
async function* streamRun(client, runId: string): AsyncGenerator<StreamEvent> {
  const response = await fetch(`${baseUrl}/api/v1/runs/${runId}/stream`);
  const reader = response.body!.getReader();
  // ... parse SSE events
}
```

SDK published as npm package `@orchestra/client` (initially local, npm publish later).

**Verify:**
```
cd sdk/typescript && npm install && npx tsc --noEmit
bash scripts/generate-sdk.sh
```

**Done:**
- Types generated from live OpenAPI spec match server endpoints
- `tsc --noEmit` passes (all types valid)
- Client can call all server endpoints with type safety
- SSE streaming works as async generator
- A2A task submission helper works
- Package.json has correct dependencies and exports

---

### Risk Assessment — Plan 11
- **Low:** openapi-typescript is mature (7.9k stars), zero runtime cost. FastAPI auto-generates OpenAPI spec.

---

## Dependency Graph (All Plans)

```
Plan 01 (Cost Router)    Plan 02 (Identity)    Plan 03 (Memory)
    |                        |    \                  |
    |                        |     \                 |
    v                        v      \                v
Plan 06 (Budget)    Plan 04 (UCAN)   \    Plan 05 (Vector)
                        |             \
                        |              \
                        v               v
                    Plan 07 (A2A)    Plan 08 (SPRT+Shield)
                        |
                        v
                    Plan 09 (NATS)
                        |
                        v
                    Plan 10 (K8s)
                        |
                        v
                    Plan 11 (TS SDK)

Wave 1: Plans 01, 02, 03   (independent roots — 3-way parallel)
Wave 2: Plans 04, 05, 06   (each depends on one Wave 1 plan — 3-way parallel)
Wave 3: Plans 07, 08       (07 depends on 02; 08 independent — 2-way parallel)
Wave 4: Plan 09            (depends on 01, 07)
Wave 5: Plan 10            (depends on 09)
Wave 6: Plan 11            (depends on 10)
```

---

## File Ownership Matrix

| Plan | Module(s) | Key Files |
|------|-----------|-----------|
| 01 | `cost/`, `providers/` | router.py, model_alias.py, failover.py, strategy.py, degradation.py |
| 02 | `identity/` | agent_identity.py, did.py, keys.py, credentials.py, schemas.py |
| 03 | `memory/`, `cache/` | tiers.py, access_stats.py, policies.py, redis_backend.py, invalidation.py, redis_tier.py |
| 04 | `identity/` | ucan.py, capabilities.py, oidc.py, claim_mapping.py |
| 05 | `memory/`, `cache/` | vector_store.py, cold_tier.py, embeddings.py, semantic.py |
| 06 | `cost/` | persistent_budget.py, tenant.py, billing.py |
| 07 | `interop/`, `server/routes/` | agent_card.py, a2a.py (route) |
| 08 | `testing/`, `security/` | sprt.py, fingerprint.py, decorators.py, prompt_shield.py, guarded_call.py |
| 09 | `messaging/` | broker.py, producer.py, consumer.py, worker.py |
| 10 | `deploy/`, `observability/` | Helm chart, Dockerfiles, prometheus.py, collector config |
| 11 | `sdk/typescript/` | Generated types, client wrapper, package.json |

**No file ownership conflicts** — each plan touches distinct modules. All Wave 1 plans can execute in full parallel.

---

## New Dependencies Summary

| Group | Packages | Plans |
|-------|----------|-------|
| `iam` | `peerdid>=0.5.2`, `PyLD>=2.0`, `pynacl>=1.5`, `joserfc>=1.0`, `py-ucan>=1.0.0`, `Authlib>=1.6.9` | 02, 04 |
| `redis` | `redis[hiredis]>=5.0`, `msgpack>=1.0` | 03 |
| `memory-vector` | `hnswlib>=0.8`, `model2vec>=0.3` | 05 |
| `messaging` | `nats-py>=2.14` | 09 |
| `reliability` | `aiobreaker>=1.2` | 01 |
| `a2a` | `a2a-sdk>=0.3.24` | 07 |
| `prometheus` | `opentelemetry-exporter-prometheus>=0.45b0` | 10 |
| `prompt-shield` | `transformers>=4.40`, `torch>=2.0` or `onnxruntime>=1.17` | 08 |
| `billing` | (no new deps — uses existing aiosqlite) | 06 |

---

## Deferred Items (Explicitly NOT in Phase 4)

These items from research are intentionally deferred to Phase 5+:

- **Ray Core/Serve distributed execution** — NATS competing consumers covers distributed task execution. Ray adds 500MB+ deps and no Python agent framework uses it successfully. Defer until proven need.
- **Thompson Sampling / Matrix Factorization for routing** — Requires production routing data. Build data collection in Phase 4, enable ML routing in Phase 5.
- **Model Distillation pipeline** — Requires accumulated routing data and fine-tuning infrastructure. Phase 5.
- **Python Subinterpreters** — Defer until Python 3.15+ when C extension compatibility improves.
- **kopf Kubernetes Operator (CRDs)** — Helm chart is sufficient for initial K8s deployment. Custom operator for CRD-based agent management in Phase 5.
- **Istio/Ambient Mesh** — Infrastructure concern, not framework code. Document in deployment guide.
- **Dynamic Subgraphs (runtime graph mutation)** — Complex feature with debugging implications. Phase 5.
- **Agent Marketplace + Certification Program** — Ecosystem features requiring user base. Phase 5+.
- **Visual Builder Partnerships (n8n, Flowise)** — Integration work requiring partner engagement. Phase 5+.
- **ZKP/BBS+ Selective Disclosure** — No production-ready Python library. Use selective disclosure via multiple VCs instead.
- **SOC2 documentation** — Compliance documentation (not code). Separate workstream.
- **Gossip Protocol** — NATS built-in discovery sufficient. Custom gossip only for cross-org A2A Phase 5+.
- **Full Stripe billing integration** — Optional plugin, build after internal billing proven.
- **KEDA ScaledObject with NATS scaler** — Included in Helm chart as optional, but KEDA operator installation is cluster-level ops.
- **Neo4j graph memory** — Alternative warm tier, evaluate after Redis tier proven.
- **Arbitration Nodes** — Multi-agent conflict resolution. Phase 5.
- **SLA-Driven Routing (TTFT-based)** — Requires production latency data collection. Phase 5.

---

## Success Criteria (Phase Complete When)

- [ ] All 19 tasks complete with passing acceptance criteria
- [ ] `pytest tests/ -x --cov=orchestra` shows >= 80% coverage on new modules
- [ ] LLM requests route to appropriate models based on complexity
- [ ] Provider failover with circuit breaker handles outages gracefully
- [ ] Agent identities are DID-based and cryptographically verifiable
- [ ] UCAN delegation creates bounded capability tokens
- [ ] OIDC bridge maps enterprise IdP tokens to agent identities
- [ ] Memory tiers promote/demote based on access patterns
- [ ] Redis L2 provides cross-instance caching with invalidation
- [ ] Cold-tier vector retrieval returns semantically similar memories
- [ ] A2A Agent Card served at well-known URL
- [ ] NATS messaging distributes tasks to competing consumers
- [ ] SPRT detects behavioral regression efficiently
- [ ] PromptShield blocks injection with zero added latency
- [ ] Helm chart deploys full stack to Kubernetes
- [ ] TypeScript SDK provides type-safe client access
- [ ] All 244+ existing tests still pass (no regressions)

---

## Estimated Execution Timeline

| Wave | Plans | Estimated Duration | Parallelism |
|------|-------|--------------------|-------------|
| 1 | 01, 02, 03 | 2-3 days | 3-way parallel |
| 2 | 04, 05, 06 | 2-3 days | 3-way parallel |
| 3 | 07, 08 | 1-2 days | 2-way parallel |
| 4 | 09 | 1-2 days | Sequential |
| 5 | 10 | 1-2 days | Sequential |
| 6 | 11 | 0.5-1 day | Sequential |

**Total estimated:** 8-13 days of Claude execution time (with parallelism), approximately 3-4 weeks calendar time.

---

*Plan created: 2026-03-11*
*Research basis: 10 research files in `.planning/phases/04-enterprise-scale/research/`*
*Phase 3 plan: `.planning/phases/03-production-readiness/PLAN.md`*
