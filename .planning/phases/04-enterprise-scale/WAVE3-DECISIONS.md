# Wave 3 Design Decisions

**Decided:** 2026-03-13
**Status:** APPROVED — all 6 decisions confirmed by user

---

## D1: Redis Standalone (not Cluster)

**Decision:** Use Redis Standalone with Pub/Sub for L2 cache.
**Why:** Cluster adds hash-slot complexity, cross-slot operation restrictions. Orchestra has no sharding need at current scale.
**Migration path:** Swap `Redis()` → `RedisCluster()` later if needed. `redis.asyncio` supports both.

## D2: Cold Tier Demotion — Dual Trigger

**Decision:** Demote WARM→COLD when `(warm_ttl_expired AND idle >5min) OR warm_size > max_warm_size`.
**Why:** Pure TTL misses size pressure. Pure size misses stale data. Dual covers both.
**Config:** `warm_ttl=3600`, `idle_threshold=300`, `max_warm_size=10000` — all constructor params.

## D3: Model Download — Lazy on First Use

**Decision:** PromptShield models download lazily via HuggingFace `cached_download` on first inference call.
**Why:** Avoids bloating install. Docker builds pre-download in image layer.
**CLI:** Optional `orchestra promptshield download` for pre-warming.
**Env:** `HF_HOME` controls cache location (transformers v5 dropped `TRANSFORMERS_CACHE`).

## D4: Attenuator Reset — Per-Run Permanent

**Decision:** Restricted Mode persists for the entire agent run. Agent must be re-instantiated to regain full capabilities.
**Why:** Prevents attacker from "waiting out" the restriction within a run.
**Field:** Add `restricted_mode: bool = False` to `ExecutionContext`.

## D5: Pin transformers <5.0

**Decision:** Use `transformers>=4.51,<5.0` for T-4.10 PromptShield.
**Why:** `optimum-onnx` is Pre-Alpha (v0.1.0), no verified transformers v5 compatibility. All target models were trained on v4.x. Upgrade when optimum-onnx stabilizes.
**Package:** Use `optimum[onnxruntime]` (not `optimum-onnx`) while pinned to v4.x.

## D7: PromptShield Default Model — Llama Prompt Guard 2 86M (REVISED)

**Decision:** Use `meta-llama/Llama-Prompt-Guard-2-86M` (community ONNX quantized, 282 MB) as default.
**Why:** ProtectAI DeBERTa v2's self-reported 95.49% F1 is misleading — cross-benchmark average is 70.93%, AgentDojo APR is 22.2%. Llama PG2 86M scores 0.998 AUC, 97.5% Recall@1%FPR, 81.2% AgentDojo APR. Supports 8 languages.
**License:** Llama 4 Community License (commercial use OK under 700M MAU).
**ONNX source:** `gravitee-io/Llama-Prompt-Guard-2-86M-onnx` — quantized model.quant.onnx = 282 MB.

**Full model tier:**

| Role | Model | ONNX Size | AUC (EN) | AgentDojo APR | License |
|------|-------|-----------|----------|---------------|---------|
| **Default** | Llama PG2 86M (quant ONNX) | 282 MB | 0.998 | 81.2% | Llama 4 Community |
| **Lightweight** | Llama PG2 22M (quant ONNX) | 72.8 MB | 0.995 | 78.4% | Llama 4 Community |
| **Apache-2.0 only** | ProtectAI DeBERTa v2 (ONNX) | 739 MB | — | 22.2% | Apache 2.0 |
| **Max accuracy (GPU)** | Sentinel v2 (GGUF) | 1.19 GB | — | — | Elastic |

**Why NOT ProtectAI (original recommendation):**
- AgentDojo APR: 22.2% vs 81.2% for PG2-86M (3.6x worse on real agent attacks)
- Cross-benchmark F1: 70.93% vs self-reported 95.49% (poor generalization)
- ONNX is 739 MB FP32 unquantized (vs 282 MB quantized for PG2-86M)

**Why NOT Sentinel v1:**
- License is "other" (gated, requires contact info) — not suitable for open distribution
- No ONNX export available
- 1.58 GB FP32 only

## D6: Embedding Model — potion-base-8M (256d)

**Decision:** Use `minishlab/potion-base-8M` for both SemanticDeduplicator and cold tier retrieval. 256 dimensions.
**Why:** 10MB model, 500x faster than sentence-transformers, 89% of MiniLM quality. Single dimension simplifies pgvector schema (`VECTOR(256)`). 32M models output 512d — unnecessary complexity for initial rollout.
**Upgrade path:** Swap to `potion-retrieval-32M` (512d) if Recall@10 < 0.90 on real data. Requires column migration.

---

## Corrected Library Pins (Post-Research)

| Library | Old Plan | New Pin | Source |
|---------|----------|---------|--------|
| redis[hiredis] | >=7.0 | **>=7.0** | PyPI confirms 7.3.0 is latest; 7.0.0 exists |
| pgvector | >=0.3 | **>=0.4** | API improvements for asyncpg schema support |
| model2vec | >=0.3 | **>=0.6** | StaticModel API; potion-base-8M = 256d |
| pyzstd | >=0.17 | **>=0.17** | OK as-is |
| msgpack | >=1.0 | **>=1.0** | OK as-is |
| transformers | >=4.40 | **>=4.51,<5.0** | Sentinel v2 needs 4.51; pin below v5 |
| onnxruntime | >=1.18 | **>=1.18** | OK as-is |
| optimum | not listed | **>=1.24** | ORTModelForSequenceClassification |

---

## Key Technical Corrections from Web Research

1. **redis-py 7.3.0 is real** — confirmed on PyPI. Research agent's claim of 7.1.1 was wrong.
2. **`register_vector(conn)` must be called per-connection** — use asyncpg pool `init` callback.
3. **Default `max_connections` in redis-py is 2^31** — must set explicitly. Use `BlockingConnectionPool(max_connections=20)`.
4. **hiredis 3.3.0** — minimal speedup for GET/SET (1.1x) but massive for bulk replies (83x). Worth including.
5. **`<=>` is cosine distance, `<->` is L2** — operator MUST match index ops class or silent sequential scan fallback.
6. **Default `ef_construction` is 64** (not 200) — we explicitly set 200 for better recall.
7. **aioredis fully deprecated** — merged into redis-py 4.2+. Do not depend on it.
8. **Async CLIENT TRACKING not supported** — redis-py #3916 still open. Use manual Pub/Sub.
9. **ProtectAI DeBERTa v2 poor generalization** — 95.49% F1 self-reported, but 70.93% cross-benchmark avg and 22.2% AgentDojo APR. Llama PG2 86M is 3.6x better on real agent attacks.
10. **Sentinel v1 license is gated** ("other"), not open/Apache as assumed. Requires contact info to download.
11. **Llama PG2 22M is ~70M total params** (22M backbone + 48M embedding), not 22M total.
12. **Llama PG2 86M is ~280M total params** (86M backbone + 190M multilingual embedding).
13. **transformers v5 removed TF/Flax** — PyTorch only. `AutoModelForSequenceClassification` import unchanged. `TRANSFORMERS_CACHE` env var removed (use `HF_HOME`). HTTP backend switched from `requests` to `httpx`.
14. **optimum v2.1.0 claims transformers v5 compat** — but `optimum-onnx` v0.1.0 is Pre-Alpha and references v4.56/4.57. Safest to stay on `optimum[onnxruntime]` + transformers v4.x.
