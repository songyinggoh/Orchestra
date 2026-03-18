# Phase 4 Research: Advanced Memory & Data

**Research conducted**: 2026-03-11
**Scope**: 8 topics covering distributed caching, multi-tier memory, vector retrieval, semantic caching, and state compression.
**Current baseline**: In-process `TTLCache` with `CacheBackend` protocol, `MemoryManager` protocol stub with store/retrieve only, L1 tier only.

---

## 1. MemoryManager Promote/Demote

### Eviction/Promotion Policies

| Policy | Mechanism | Best For |
|--------|-----------|----------|
| **LRU** | Evicts item not accessed for longest time | Temporal locality |
| **LFU** | Evicts item with lowest access count | Frequency-dominated workloads |
| **ARC** | Two LRU lists (recent + frequent) with adaptive sizing | Mixed workloads |
| **SLRU** | Probationary + protected segments; promotion on re-access | General-purpose |
| **LFRU** | LFU+LRU hybrid with privileged/unprivileged partitions | Balancing recency and frequency |

### Recommended: SLRU with Access Counting

Maps naturally to Orchestra's tier model: hot (protected/frequent) vs warm (probationary) vs cold (archive). Promotion trigger: item accessed N times within sliding window (e.g., 3 accesses in 60s). Demotion trigger: item not accessed for T seconds, with exponentially increasing TTLs per tier.

### Key Libraries
- **cachetools 7.0.5** (March 2026, Python >= 3.10): `TTLCache`, `LRUCache`, `LFUCache`. Already used.
- **aiocache 0.12.3**: Async cache manager supporting memory, Redis, memcached backends.

### Implementation
Extend `MemoryManager` protocol with `promote(key, to_tier)` and `demote(key, to_tier)`. Maintain per-key `AccessStats`. Run background `asyncio.Task` for periodic SLRU scans.

---

## 2. Redis L2 Backplane

### Library Status
- **redis-py 7.3.0**: Active, recommended. Built-in `redis.asyncio` module. Merged aioredis. **Async client does NOT support CLIENT TRACKING** (issue #3916).
- **aioredis**: Deprecated — merged into redis-py 4.2+.

### Architecture: L1 + L2 with Pub/Sub Invalidation

Each instance runs L1 in-process TTLCache. Redis serves as L2 (shared). On write/delete, publish invalidation to `orchestra:cache:invalidate` Pub/Sub channel. All other instances evict from L1. Target propagation: < 100 ms.

### Write Strategies
- **Write-Through** (recommended): Write to Redis L2 first, then L1, then publish invalidation. Strong consistency.
- **Write-Behind**: Write to L1 immediately, queue async write to Redis. Lower latency, risk of data loss.

### Important Limitations
- Pub/Sub is best-effort and non-persistent — short L1 TTLs (30-60s) as safety net
- Must use manual Pub/Sub (no async CLIENT TRACKING support)
- Use distributed lock or "single-flight" for stampede prevention

### Performance
- L1 hit: ~0.001 ms | L2 hit: 0.5-2 ms | L2 miss + LLM: 200-5000 ms

---

## 3. Warm Tier Semantic Deduplication

### Thresholds
| Cosine Similarity | Classification | Action |
|-------------------|---------------|--------|
| >= 0.98 | **Duplicate** | Drop new entry |
| >= 0.85, < 0.98 | **Similar** | Flag for review/merge |
| < 0.85 | **Distinct** | Store as new |

### Libraries
- **SemHash 0.4.1** (Jan 2026): Uses Model2Vec + Vicinity (ANN via usearch). Batch-oriented, millions/minute.
- **Model2Vec**: Static embeddings via vocabulary distillation. 50x smaller, 500x faster than sentence-transformers. Models: `potion-base-8M/4M/2M`.
- **sentence-transformers/all-MiniLM-L6-v2**: 22M params, 384 dims. Standard baseline.

### Approach
- **Real-time**: Compute embedding with Model2Vec, query warm-tier ANN index, apply thresholds.
- **Batch**: Use SemHash for periodic full-tier dedup.

---

## 4. Cold Tier HNSW Vector Retrieval

### Library Comparison

| Library | GPU | Query Latency (1M) | Key Strength |
|---------|-----|---------------------|--------------|
| **hnswlib** | No | 2-10 ms | Fastest CPU-only HNSW. Header-only C++. |
| **FAISS** | Yes | < 1 ms (GPU) | Most flexible. IVF, HNSW, PQ, CAGRA. |
| **ChromaDB** | No | < 50 ms | Full vector DB with async client (1.5.5). |
| **pgvector** | No | Varies | PostgreSQL extension. HNSW + IVFFlat. Iterative scan in 0.8.0. **471 QPS @ 99% recall on 50M vectors** (pgvectorscale). |
| **Qdrant** | No | 1-5 ms | Rust core. Async Python client. Distributed. |
| **Milvus** | Yes | < 5 ms | Cloud-native. Streaming Node GA in 2.6.0. |

### Scale Recommendations
- < 10K: hnswlib or ChromaDB
- 10K-1M: hnswlib, FAISS, or pgvector
- 1M-10M: pgvector+pgvectorscale or Qdrant
- 10M+: Qdrant or Milvus (distributed)

### HNSW Tuning
`M=16`, `ef_construction=200`, `ef_search=100` → > 95% recall, sub-10ms at 1M vectors.

### Recommendation
**Start with pgvector** (zero additional infra if using PostgreSQL). **Graduate to Qdrant** for distributed or > 100M vectors.

---

## 5. HSM (Hierarchical Storage Management)

### Tier Architecture

| Tier | Backend | Latency | TTL | Use Case |
|------|---------|---------|-----|----------|
| **Hot (L1)** | In-process TTLCache | < 0.01 ms | 5 min | Active session data |
| **Warm (L2)** | Redis 7.x | 0.5-2 ms | 1 hour | Cross-instance shared state |
| **Cold (L3)** | PostgreSQL + pgvector | 5-50 ms | Permanent | Long-term memories, semantic retrieval |
| **Archive (L4)** | S3 / blob storage | 50-500 ms | Permanent | Compliance archives |

### Tier Boundary Rules
- L1→L2: TTL expires or LRU eviction → write to Redis
- L2→L1: Access count >= 3 in 60s → copy to L1
- L2→L3: Redis TTL expires → persist to PostgreSQL
- L3→L4: Age > 30 days, access count = 0 → batch move to S3

### Reference: Redis Agent Memory Server
Open-source (2025): two-tier architecture (working + long-term), automatic promotion via background LLM extraction, content hashing + semantic deduplication, contextual grounding.

### Cost Model (100K entries/month)
Hot: $0 | Warm (Redis): $15-50 | Cold (PostgreSQL): $10-30 | Archive (S3): $0.50-2

---

## 6. Vector Database Sharding

### Strategies
| Strategy | Mechanism | Best For |
|----------|-----------|----------|
| **Hash-based** | `shard = hash(id) % N` | Uniform access |
| **Range-based** | Partition by timestamp | Temporal data |
| **Tenant-based** | One partition per tenant | Multi-tenant SaaS |
| **Semantic** | Cluster by embedding similarity | Large-scale similarity search |

### Managed vs Self-Hosted
- **Pinecone 7.3.0**: Automatic sharding, namespace isolation per tenant.
- **Qdrant**: Manual sharding + auto-replication. Raft consensus.
- **Milvus**: Auto-sharding. Streaming Node GA in 2.6.0.
- **pgvector**: PostgreSQL LIST/RANGE/HASH partitioning. Per-partition HNSW indexes.

### Recommendation
Start with pgvector partitioning (LIST by tenant, RANGE by timestamp). Graduate to Qdrant at > 100M vectors.

---

## 7. Semantic Caching

### How It Works
Compute embedding of query → search ANN index for nearest cached query → if similarity >= threshold, return cached response → otherwise call LLM and cache.

### Threshold Tuning

| Threshold | Hit Rate | Accuracy | Recommendation |
|-----------|----------|----------|----------------|
| 0.80 | ~68% | >97% | GPTCache default |
| **0.85** | ~50% | Very good | **Recommended start** |
| 0.90 | ~30% | Excellent | Safety-critical |

At threshold 0.80, GPTCache achieved 68.8% hit rate with >97% accuracy. Custom implementations report 72% reduction in LLM API costs.

### Libraries
- **GPTCache** (Zilliz): Modular (embedding, vector store, cache storage, similarity eval). Maintenance slowing.
- **Custom**: Model2Vec/all-MiniLM-L6-v2 + hnswlib/FAISS + Redis/dict.

### Integration
Extend `CacheBackend` with `get_similar(embedding, threshold)`. Dual lookup: exact hash first (fast), then semantic similarity fallback. Per-agent thresholds by task sensitivity.

---

## 8. State Compression

### Algorithms

| Algorithm | Library | Ratio | Speed | Notes |
|-----------|---------|-------|-------|-------|
| **zstd** | `compression.zstd` (3.14+ stdlib), `pyzstd` 0.17.0+ | 25-50% | Very fast | **Recommended**. PEP 784. |
| **zlib** | stdlib | 30-50% | Moderate | Already used by `eventsourcing`. |
| **lz4** | `lz4` | 40-60% | Fastest | Best for real-time streaming. |

### Strategies
- **Full snapshot + zstd**: 25-50% reduction for periodic checkpoints
- **Delta encoding**: 60-90% reduction for incremental updates
- **Binary serialization**: `msgpack` — 30-50% smaller than JSON
- **Rolling snapshots**: Every N events, compress with zstd

### Expected Sizes (MsgPack + zstd level 3)
1 KB → ~400 B | 10 KB → ~2.5 KB | 100 KB → ~20 KB | 1 MB → ~200 KB

---

## Implementation Order

1. **Redis L2 Backplane** — foundation for distributed caching
2. **MemoryManager Promote/Demote** — tier lifecycle
3. **HSM Manager** — orchestrates tiers
4. **Cold Tier HNSW** — long-term retrieval (parallel with #5)
5. **Warm Tier Semantic Dedup** — quality control (parallel with #4)
6. **Semantic Caching** — leverages embedding infra from #4/#5
7. **VDB Sharding** — scaling, only needed at volume
8. **State Compression** — independent, anytime

## Key Libraries

| Library | Version | Purpose |
|---------|---------|---------|
| redis (redis-py) | 7.3.0 | L2 Redis with async |
| SemHash | 0.4.1 | Batch semantic dedup |
| Model2Vec | latest | Fast static embeddings |
| hnswlib | latest | In-process HNSW ANN |
| pgvector | 0.8.0 | PostgreSQL vector search |
| ChromaDB | 1.5.5 | Full vector DB with async |
| pyzstd | 0.17.0+ | Zstandard compression |
| msgpack | latest | Binary serialization |
