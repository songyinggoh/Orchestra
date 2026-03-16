# Phase 4: Enterprise & Scale — Authoritative Implementation Plan

**Phase:** 04-enterprise-scale
**Goal:** Transform Orchestra from a single-instance production framework into a distributed, enterprise-grade platform with cost-intelligent routing, agent identity, multi-tier memory, A2A interoperability, and Kubernetes deployment.
**Status:** Ready for Execution (requires Phase 3 completion)
**Tasks:** 13 tasks across 4 waves (8 weeks)
**Reconciled from:** Plan Agent (17 tasks), GSD Planner (19 tasks), ToT Analysis (9 tasks), Backup Plan, P0/P1/P2 Security Foundation

---

## Reconciliation Decisions

The ToT analysis scored overplanning at 0.88 (HIGH). This plan applies ToT cuts while preserving the Plan/GSD agents' detailed task specifications, now reinforced by the P0/P1/P2 Security Foundation.

| Decision | Rationale |
|----------|-----------|
| **NATS in Wave 1** (not Wave 4) | ToT: "NATS is the backbone — deploy first." Competitive analysis confirms. |
| **MANDATORY P0: NATS E2EE** | User Requirement: "At-least-once" persistence leaks PII. Implement DIDComm E2EE immediately. |
| **MANDATORY P0: Hard Sandboxing** | User Requirement: Soft isolation (Ray/Subinterpreters) is vulnerable. Implement Wasm/gVisor/Kata. |
| **MANDATORY P1: PromptShield Defense** | User Requirement: 35% bypass is too high. Add Output Scanning and Capability Attenuation. |
| **MANDATORY P1: Signed Discovery** | User Requirement: Prevent Gossip Poisoning. Mandate Cryptographic Signatures for Agent Cards. |
| **MANDATORY P2: TTL-Based Revocation** | User Requirement: Ghost capabilities risk. Use Short-Lived Capabilities (TTLs). |
| **MANDATORY P2: ZKP State Integrity** | User Requirement: Prevent cross-org state forgery. Implement Input Hash Commitments. |
| **CUT SPRT/Fingerprinting/Mutation** | Cut from Phase 3 by previous ToT. No new user demand. Phase 5. |
| **CUT Marketplace/Certification/Arbitration** | Gold plating. No user demand, no competitor has these. |
| **DEFER OIDC Bridge** | ToT: minimal IAM first. OIDC Bridge is Phase 5 "Advanced IAM." |
| **3-tier memory** (not 4) | Archive tier (S3) is Phase 5 compliance. |
| **Quick wins not tracked** | Prometheus exporter (5 LOC), OTel sampling YAML, Flowise (zero-effort). |

---

## Wave Structure

```
Wave 1 — Security & Distributed Backbone (Weeks 19-20)
  T-4.1  NATS JetStream + DIDComm E2EE               [L]
  T-4.2  Kubernetes + gVisor/Kata + KEDA              [L]
  T-4.3  Wasm Tool Sandbox                            [M]

Wave 2 — Intelligence & Identity (Weeks 21-22, PARALLEL TRACKS)
  Track A:
    T-4.4  Cost-Aware Router + Provider Failover      [L]
    T-4.5  Persistent Budget Tracking                 [M]
  Track B:
    T-4.6  Agent Identity + Signed Agent Cards        [L]
    T-4.7  UCAN + Short-Lived Capabilities (TTLs)     [M]

Wave 3 — Data & Memory (Weeks 23-24)
  T-4.8  Redis L2 + MemoryManager Promote/Demote     [M]
  T-4.9  HSM 3-Tier + pgvector Cold Tier              [L]
  T-4.10 PromptShield Output Scanning + Attenuation   [M]

Wave 4 — Ecosystem (Weeks 25-26)
  T-4.11 A2A Protocol + ZKP Input Commitments         [L]
  T-4.12 Dynamic Subgraphs                            [M]
  T-4.13 TypeScript Client SDK                        [S]
```

---

## Task Specifications

### T-4.1: NATS JetStream + DIDComm E2EE [L]

**Wave:** 1 | **Dependencies:** Phase 3 complete
**Create:**
- `src/orchestra/messaging/__init__.py` — exports SecureNatsProvider, TaskPublisher, TaskConsumer
- `src/orchestra/messaging/client.py` — async connection management, stream/consumer creation
- `src/orchestra/messaging/secure_provider.py` — DIDComm v2 E2EE wrapper (JWE encryption using recipient DID public key)
- `src/orchestra/messaging/publisher.py` — publishes encrypted tasks to `orchestra.tasks.{agent_type}`
- `src/orchestra/messaging/consumer.py` — pull-based consumer, transparent decryption, explicit ack
- `deploy/nats-values.yaml` — NATS Helm chart (JetStream, file storage, 3-node cluster)
- `tests/integration/test_secure_nats.py`
**Libraries:** `nats-py>=2.14`, `joserfc>=1.6`
**Note:** joserfc>=1.6 confirmed to support ECDH-1PU (draft-madden-jose-ecdh-1pu-04) and ECDH-ES with X25519/OKPKey + A256CBC-HS512. ECDH-1PU requires `register_ecdh_1pu()` at startup (not auto-registered). No pycryptodome needed for A256CBC-HS512 content encryption. Do not add `didcomm-python` (last PyPI release 2023-05, pins authlib<2.0 which conflicts with joserfc migration path).
**Done when:** Publish 100 tasks → 100 acks; NATS store contains only opaque ciphertexts; decryption verified.

---

### T-4.2: Kubernetes + gVisor/Kata + KEDA [L]

**Wave:** 1 | **Dependencies:** T-4.1
**Create:**
- `deploy/helm/orchestra/` — Helm chart with runtimeClassName support (defaulting to `runsc` for gVisor)
- `deploy/helm/orchestra/templates/keda-scaledobject.yaml` — NATS JetStream scaler
- `deploy/terraform/` — Provisioning scripts for EKS/GKE with gVisor (runsc) and Kata runtime support
- `deploy/otel-collector.yaml` — 2-tier Collector config with tail sampling and PII redaction
**Libraries:** Helm 3, KEDA 2.19+, Terraform
**Done when:** `helm install` deploys workers into gVisor sandboxes; KEDA scales workers on queue depth.

---

### T-4.3: Wasm Tool Sandbox [M]

**Wave:** 1 | **Dependencies:** Phase 3 (Tool protocols)
**Create:**
- `src/orchestra/tools/wasm_runtime.py` — wasmtime-py integration for executing .wasm tools
- `src/orchestra/tools/sandbox.py` — Restriction policies (No FS, No Net, CPU/Mem limits)
- `tests/unit/test_wasm_sandbox.py`
**Libraries:** `wasmtime>=23.0.0`
**Done when:** Wasm tool executes in restricted environment; host FS/Network access attempts are blocked.

---

### T-4.4: Cost-Aware Router + Provider Failover [L]

**Wave:** 2 Track A | **Dependencies:** Phase 3 (T-3.6 CostAggregator)
**Create:**
- `src/orchestra/routing/router.py` — CostAwareRouter Protocol + ThompsonModelSelector
- `src/orchestra/providers/failover.py` — ProviderFailover with AsyncCircuitBreaker
- `src/orchestra/providers/strategy.py` — NativeStrategy vs PromptedStrategy (transparent switching)
- `tests/unit/test_cost_router.py`
**Libraries:** `numpy>=1.26` (Note: existing `AsyncCircuitBreaker` from `security/circuit_breaker.py` is used per DD-6 — no `aiobreaker`)
**Done when:** 30%+ cost reduction on mixed workloads; failover within 5s of primary failure.

---

### T-4.5: Persistent Budget Tracking [M]

**Wave:** 2 Track A | **Dependencies:** T-4.4
**Create:**
- `src/orchestra/cost/persistent_budget.py` — SQLite/Postgres double-entry ledger
- `src/orchestra/cost/tenant.py` — Hierarchical budget delegation and credit conservation
- `tests/unit/test_persistent_budget.py`
**Libraries:** `aiosqlite>=0.20`
**Done when:** Budget survives server restart; tenant-scoped budgets enforce limits.

---

### T-4.6: Agent Identity + Signed Agent Cards [L]

**Wave:** 2 Track B | **Dependencies:** Phase 3 complete
**Create:**
- `src/orchestra/identity/agent_identity.py` — DID-backed identity model
- `src/orchestra/identity/did.py` — peerdid/did:web manager
- `src/orchestra/identity/discovery.py` — SignedDiscoveryProvider (verifies signatures on Agent Cards before ingestion)
- `src/orchestra/security/secrets.py` — SecretProvider ABC + Vault (hvac)
- `tests/unit/test_agent_identity.py`, `tests/unit/test_signed_discovery.py`
**Libraries:** `hvac>=2.4.0` (Note: custom `orchestra.messaging.peer_did` module is used per DD-8 — no `peerdid`/`pynacl`)
**Done when:** Agents carry verified DIDs; gossip poisoning blocked by signature verification.

---

### T-4.7: UCAN + Short-Lived Capabilities (TTLs) [M]

**Wave:** 2 Track B | **Dependencies:** T-4.6
**Create:**
- `src/orchestra/identity/ucan.py` — UCAN implementation with short-lived TTL (1–60 min)
- `src/orchestra/identity/delegation.py` — Delegation chain verification with attenuation
- `tests/unit/test_ucan_ttls.py`
**Libraries:** `joserfc>=1.0`
**Done when:** Tokens expire correctly; sub-agents request refreshes; tampered/expired tokens rejected.

---

### T-4.8: Redis L2 + MemoryManager Promote/Demote [M]

**Wave:** 3 | **Dependencies:** Phase 3 (T-3.4 MemoryManager)
**Create:**
- `src/orchestra/cache/redis_backend.py` — redis.asyncio backend
- `src/orchestra/memory/tiers.py` — TieredMemoryManager (HOT/WARM/COLD) with SLRU promotion
- `tests/unit/test_memory_tiers.py`
**Libraries:** `redis[hiredis]>=7.0`, `msgpack>=1.0`
**Done when:** L2 <2ms; promotion/demotion functional across distributed instances.

---

### T-4.9: HSM 3-Tier + pgvector Cold Tier [L]

**Wave:** 3 | **Dependencies:** T-4.8
**Create:**
- `src/orchestra/memory/vector_store.py` — pgvector HNSW + hybrid retrieval
- `src/orchestra/memory/dedup.py` — SemanticDeduplicator (0.98 threshold)
- `src/orchestra/memory/compression.py` — StateCompressor (zstd + msgpack)
- `tests/unit/test_vector_store.py`
**Libraries:** `pgvector>=0.3`, `pyzstd>=0.17`, `model2vec>=0.3`
**Done when:** Cold tier retrieval returns semantically similar memories; 90% top-10 accuracy.

---

### T-4.10: PromptShield Output Scanning + Attenuation [M]

**Wave:** 3 | **Dependencies:** Phase 3 complete
**Create:**
- `src/orchestra/security/output_scanner.py` — Post-execution check for malicious tokens/PII
- `src/orchestra/security/attenuator.py` — Dynamic capability reduction ("Restricted Mode") on injection detection
- `src/orchestra/security/guard.py` — Async SLM wrapper (Sentinel/Prompt Guard) with parallel execution
- `tests/unit/test_injection_attenuation.py`
**Libraries:** `transformers>=4.40`, `onnxruntime>=1.18`
**Done when:** Injections neutralized via Restricted Mode; output scanning catches leaked secrets.

---

### T-4.11: A2A Protocol + ZKP Input Commitments [L]

**Wave:** 4 | **Dependencies:** T-4.6
**Create:**
- `src/orchestra/interop/a2a.py` — A2AService + AgentCardBuilder
- `src/orchestra/interop/zkp.py` — Input Hash Commitments in ZKP circuits (ensuring proofs tie to verified state)
- `tests/integration/test_a2a_zkp.py`
**Libraries:** `a2a-sdk>=0.3.24`, `py-ecc>=8.0.0`
**Done when:** Agent Card served; cross-org state forgery prevented by commitment verification.

---

### T-4.12: Dynamic Subgraphs [M]

**Wave:** 4 | **Dependencies:** Phase 3 complete
**Create:**
- `src/orchestra/core/dynamic.py` — SubgraphBuilder (Send API pattern)
- `src/orchestra/core/serialization.py` — Graph YAML versioning and hot-loading
**Done when:** Graphs compose at runtime; YAML round-trip preserves structure.

---

### T-4.13: TypeScript Client SDK [S]

**Wave:** 4 | **Dependencies:** Phase 3 complete
**Create:**
- `sdk/typescript/` — openapi-fetch wrapper with SSE streaming
**Done when:** `npm test` passes against running server.

---

## Observable Truths

| # | Truth | Verification |
|---|-------|--------------|
| S1 | NATS JetStream persists only opaque ciphertexts (E2EE) | Inspect NATS storage; confirm JWE format |
| S2 | Agent workers isolated in gVisor/Kata sandboxes | `kubectl get pod -o jsonpath='{.spec.runtimeClassName}'` |
| S3 | Gossip poisoning blocked by signature verification | Inject unsigned/fake card; verify rejection in logs |
| S4 | Prompt injections neutralized via Capability Attenuation | Trigger injection; verify agent loses Network/FS access |
| S5 | ZKP state forgery prevented by Hash Commitments | Attempt state forgery; verify ZKP verification failure |
| S6 | Cost-aware routing reduces spend 30%+ | A/B test vs static routing |
| S7 | UCAN tokens expire and require refresh (TTLs) | Wait for TTL expiry; verify tool access rejection |
| S8 | Redis L2 shares memory across instances | Write Instance A → Hit Instance B |

---

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|------------|
| NATS E2EE overhead | Low | Use ChaCha20-Poly1305 (fastest in Python/pynacl) |
| gVisor syscall performance | Med | Only for high-security workers; standard for others |
| Wasm tool complexity | Med | Provide C/Rust/Python-to-Wasm templates |
| ZKP Python performance | Med | Use `py-ecc` only for verification; proofs generated externally |

---

*Reconciled: 2026-03-11*
*Sources: Phase 3 PLAN.md, P0/P1/P2 Security Foundation, Research Reports 01-11*
*Authority: This file supersedes all previous implementation plans for Phase 4*
