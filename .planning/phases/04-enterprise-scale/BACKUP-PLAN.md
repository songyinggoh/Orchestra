# Phase 4: Enterprise & Scale — Backup and Contingency Plan

**Created:** 2026-03-11
**Phase:** 4 — Enterprise & Scale (Weeks 19-26+)
**Baseline:** Phase 3 complete — FastAPI server, OTel, Redis L2, CostAggregator, CacheBackend/MemoryManager protocols, 244+ passing tests

---

## Ground Rules

1. The Phase 3 test suite (unit + integration) is the hard gate. No Phase 4 wave ships if existing tests regress.
2. Every wave lands on a dedicated branch (`phase-4/wave-N`). The `phase-3/integration` merge to master is the baseline; Phase 4 branches from that.
3. Annotated tags before and after every wave: `phase4-pre-wave-N` / `phase4-post-wave-N`.
4. Rollback means `git revert -m 1 <merge-commit>` on the integration branch. History is never rewritten on shared branches.
5. Infrastructure components (NATS, Redis, Kubernetes) that fail must never propagate exceptions into `CompiledGraph.run()`. Fail-open at every infrastructure boundary.
6. Phase 4 introduces more external state (Kubernetes, NATS, Redis, Vault, pgvector) than any prior phase. Every external dependency is wrapped by an abstraction layer that has a local fallback mode.

---

## Section 1: Component Risk Register

This section documents every major Phase 4 component, its dependency risks, and confirmed fallback strategies before implementation begins.

---

### 1.1 Agent IAM — DID, Verifiable Credentials, UCAN

**Primary Risk: DIDKit Archived**

DIDKit (spruceid/didkit) was archived in July 2025. This was the most commonly referenced Python DID library. Replacing it is non-trivial because DIDKit provided both DID resolution and VC issuance in a single Rust/PyO3 package.

**Confirmed Replacement Stack:**
- DID resolution and VC operations: `peerdid 0.5.2` (did:peer, Apache 2.0) for ephemeral agent identities + ACA-Py (openwallet-foundation/aries-cloudagent-python) patterns for organizational agents. ACA-Py is a full agent framework, not a library; use it as a reference implementation and extract only the DID/VC primitives needed via its REST API or by importing `aries_cloudagent.wallet`.
- Organizational agent DIDs: `did:web` via direct HTTPS hosting of DID Documents — requires only `httpx` for resolution, no additional library.
- VC issuance and verification: `PyLD` (JSON-LD) + `joserfc` (JWT-secured VCs). Build a thin `VCIssuer` class (~200 lines) that produces VC Data Model 2.0 JWT-VCs using EdDSA keys managed through `SecretProvider`.
- JOSE operations: `Authlib 1.6.9` or `joserfc` (used by Authlib 1.7+ internally).

**Fallback: Custom JWT-Based Identity Without Full DID**

If DID resolution infrastructure proves too complex for the initial wave, the `AgentIdentity` dataclass can be backed by JWT claims instead of full W3C DIDs. The `did` field stores a logically structured identifier (`did:orchestra:{namespace}:{agent_name}`) without implementing W3C DID resolution. UCAN delegation still works because `py-ucan 1.0.0` accepts any DID-format principal string. Full W3C DID resolution can be layered in a subsequent iteration without breaking the `AgentIdentity` interface.

**Risk: No Python zcap-ld Library**

The W3C zcap-ld spec has a JavaScript-only reference implementation (digitalbazaar/zcapld). No Python library exists.

**Decision:** Use UCAN (`py-ucan 1.0.0`) instead of zcap-ld. UCAN provides equivalent capability delegation with JWT-based tokens, DID principals, and an active specification (ucan.xyz). The Python library is on PyPI and tested. zcap-ld is a stagnant W3C Community Group draft — there is no timeline risk from avoiding it.

**Risk: BBS+ / ZKP Library Gap**

There is no production-ready, audited Python BBS+ library. `py-ecc 8.0.0` (Ethereum Foundation) provides the underlying BLS12-381 curve operations but is experimental and not audited for production credential operations.

**Decision:** Implement selective disclosure using multiple single-capability VCs rather than BBS+ cryptographic selective disclosure. An agent presenting only the VC asserting `tool:web_search` capability reveals nothing about its other capabilities. This is architecturally equivalent for authorization purposes. BBS+ is a Phase 5 concern when a maintained Python wrapper for MATTR's Rust implementation becomes available.

**Risk: ACA-Py is Heavyweight**

ACA-Py is designed as a deployable service, not an importable library. Importing `aries_cloudagent` introduces a large dependency tree.

**Mitigation:** Structure the `security/identity/` module with optional imports behind `[iam]` extras. `AgentIdentity` and its JWT-backed implementation are in `security/identity/core.py` with no heavy dependencies. ACA-Py-backed resolution is in `security/identity/acapy_resolver.py` and only imports if `extras_require["iam-full"]` is installed. Unit tests for core identity logic use the JWT-backed implementation and never touch ACA-Py.

---

### 1.2 Cost-Aware Routing — CostRouter, Thompson Sampling, Circuit Breakers

**Primary Risk: Routing Complexity Accumulation**

The research identifies five composable routing layers: heuristic rules (Tier 1), Thompson Sampling (Tier 2), Matrix Factorization predictor (Tier 3), SLA filtering, and circuit-breaker-aware failover. Building all five at once is high risk. Each layer also depends on production data accumulation.

**Phased Implementation Protocol:**

Build in strict sequence; do not advance to the next layer until the previous layer has been running in production and generating observable metrics for at least one week.

- Layer 1 (Heuristic Tier): Classify by token count + tool count → route to small/medium/large model tier. Zero data dependency. Ships with the first wave.
- Layer 2 (Circuit Breaker + Failover): `aiobreaker` circuit breakers per provider + fallback chain defined in YAML config. Ships with Layer 1.
- Layer 3 (Thompson Sampling): Requires accumulated `(prompt, model, outcome)` tuples. Gate on having 50+ observations per model before enabling. Ships after sufficient production data exists.
- Layer 4 (MF Predictor): Requires 500+ observations with quality scores. Use `scipy.sparse` SVD. Gate behind a feature flag.
- Layer 5 (SLA Router): Requires p95 latency statistics per provider/model. Uses sliding window updated via EventBus. Ships when latency data infrastructure exists.

**Risk: GPTCache Maintenance Declining**

GPTCache has 83 unreleased commits and slowing maintenance activity. It should not be a dependency.

**Decision:** Build a purpose-specific `SemanticCache` class (~300 lines) using `hnswlib` for ANN search and `Model2Vec` for fast static embeddings. This eliminates a poorly-maintained dependency and results in a smaller, more controllable implementation. The existing `CacheBackend` protocol from Phase 3 is the insertion point.

**Risk: RouteLLM Pre-Trained Routers Are Domain-Specific**

RouteLLM's pre-trained routers (SW-ranking, BERT, MF) are trained on Chatbot Arena preference data (conversational tasks). Orchestra executes structured agent workflows — the domain mismatch may reduce router accuracy.

**Mitigation:** Use RouteLLM as a reference implementation only, not as a deployed dependency. The `RoutingDataCollector` EventBus subscriber accumulates Orchestra's own `(prompt_features, model, outcome)` tuples. A `GradientBoostingClassifier` trained on this data outperforms a generic pre-trained router for Orchestra's actual task distribution. The heuristic Layer 1 provides acceptable routing until sufficient training data is available.

**Risk: Stripe LLM Token Billing is in Preview**

Stripe's native LLM Meters API and AI Gateway are on preview/waitlist as of March 2026. GA timeline is unknown.

**Mitigation:** The `BillingAggregator` writes billing records to the internal SQLite ledger regardless of Stripe availability. The Stripe sink is an optional plugin that can be enabled when GA is confirmed. Internal billing reports (CLI command generating CSV/JSON per tenant per period) provide the core chargeback capability with no Stripe dependency.

---

### 1.3 NATS JetStream — Distributed Messaging

**Primary Risk: Operational Complexity Before Application Readiness**

NATS JetStream is easy to run but adds operational surface area (stream configuration, consumer durability, ack timeouts, monitoring endpoint). Introducing NATS before the application layer is stable adds two failure domains simultaneously.

**Sequencing Rule:** NATS is introduced only after the Kubernetes deployment is stable and the FastAPI server has been running under NATS-free conditions. Application-layer changes and infrastructure-layer changes never land in the same wave.

**Risk: NATS JetStream Async — No CLIENT TRACKING in redis-py Async (Issue #3916)**

The Redis L2 backplane (from Phase 3) uses manual Pub/Sub for cache invalidation because `redis-py` async client does not support `CLIENT TRACKING`. This is a known limitation documented in the Phase 3 cost.py with a `# NOTE: single-process only` comment.

**Impact in Phase 4:** When multiple Uvicorn workers share the Redis L2 backplane in a multi-instance Kubernetes deployment, the manual Pub/Sub invalidation channel is the correct mechanism (NATS does not change this). The limitation is already mitigated: each instance has a short L1 TTL (30-60 seconds) as a safety net for missed invalidation messages. Budget enforcement race conditions (Phase 3 Pitfall 8) must be addressed in Phase 4 by switching from in-memory accumulation to the persistent ledger with optimistic locking.

**Risk: NATS 1MB Message Size Limit**

Default NATS message size limit is 1MB. Large agent context windows or multi-modal payloads can exceed this.

**Mitigation:** The NATS message carries a reference (a `run_id` or `payload_key`) not the full payload. Agents fetch the actual payload from the event store (PostgreSQL) or Redis using the key. This "reference passing" pattern is explicitly documented in the NATS research and aligns with Orchestra's existing event-sourced architecture — the event store is already the authoritative state location.

**Fallback: Redis Streams If NATS Cannot Be Operated**

If NATS infrastructure proves unworkable (Kubernetes deployment constraints, ops team unfamiliarity), Redis Streams (`XADD`/`XREADGROUP`) provides equivalent at-least-once semantics using the Redis instance already deployed for L2 caching. The `MessageBroker` protocol hides this choice: `NATSBroker` and `RedisStreamBroker` implement the same interface. The application layer never calls NATS directly.

---

### 1.4 Kubernetes Deployment — kopf, KEDA, Istio, Helm

**Primary Risk: kopf Operator in Maintenance Mode**

kopf 1.38.0 (May 2025) is stable but in maintenance mode. No major new features are planned. The risk is not immediate instability but gradual ecosystem drift (new Kubernetes API versions, new Python versions) without upstream support.

**Assessment:** Maintenance mode is acceptable for Phase 4. The kopf operator handles `OrchestraAgent` CRD lifecycle only. It does not need new features — it creates Deployments, ScaledObjects, and Services from CR specs. If kopf becomes incompatible with a future Kubernetes version, the operator can be rewritten using the raw `kubernetes` Python client (which kopf wraps) without changing any CRD schemas or consumer-facing APIs.

**Alternative:** If kopf cannot be used, the operator pattern can be replaced with Helm hooks + a Kubernetes admission webhook written with the `kubernetes` Python client directly. This adds complexity but avoids the kopf dependency entirely.

**Risk: KEDA and Manual Scaling Authority Conflict**

KEDA manages Deployment scale and conflicts with `kubectl scale` and manual HPA. If both are active simultaneously, KEDA's ScaledObject ownership causes errors.

**Rule:** KEDA is the sole scaling authority for all agent worker Deployments. The `maxReplicaCount` in each ScaledObject is the single configuration point. The kopf operator creates KEDA ScaledObjects when creating OrchestraAgent CRs; it never creates native HPAs. `kubectl scale` is forbidden in production runbooks.

**Risk: Istio Ambient Mesh is Relatively New (GA in Istio 1.24)**

Ambient mesh eliminates per-pod sidecars but is a newer architectural mode. If ambient mesh has stability issues in the target cluster version, the fallback is traditional sidecar injection.

**Rollback:** Set `istio.io/dataplane-mode: sidecar` on the namespace instead of `ambient`. The application behavior is identical; only the network proxy architecture changes. No code changes are needed.

**Risk: Terraform Managing Application-Level K8s Resources**

A common mistake is managing application Deployments and ConfigMaps through Terraform instead of GitOps. This creates drift between Terraform state and cluster reality.

**Rule:** Terraform provisions exactly: EKS/GKE cluster, VPC, IAM roles, RDS instance, and installs the following operators via Helm provider releases: KEDA, OTel Operator, cert-manager, External Secrets Operator. Everything else (Deployments, Services, ConfigMaps, ScaledObjects, OrchestraAgent CRs) is GitOps-managed through ArgoCD or FluxCD. This boundary is enforced by code review and a CI check that rejects Terraform files referencing `kubernetes_deployment` resources.

---

### 1.5 Multi-Tier Memory — Redis L2, pgvector, HSM

**Primary Risk: Redis L2 Budget Enforcement Race Conditions**

Phase 3's `BudgetPolicy` is documented as single-process only. In Phase 4, multiple Uvicorn workers share the Redis L2 backplane. A concurrent budget check can allow overspend within the cache TTL window.

**Resolution:** Switch to `PersistentBudgetPolicy` with optimistic locking. The pattern:
1. Read current balance from Redis (or PostgreSQL ledger as fallback).
2. Compute projected post-spend balance.
3. Write back with `SET balance IF balance == previous_value` (Redis `WATCH`/`MULTI` or PostgreSQL `UPDATE ... WHERE balance = $previous`).
4. On conflict: re-read and retry once. If still conflicting: use the hard limit at 95% of nominal to absorb the small race window.

This replaces the in-memory `CostAggregator` race-condition note with a concrete distributed solution.

**Risk: pgvector Query Performance at Scale**

pgvector 0.8.0 achieves 471 QPS at 99% recall on 50M vectors (pgvectorscale benchmark). At 10M+ cold-tier memories, HNSW index build time and query latency may become problematic.

**Scaling Path:**
- 0-10K memories: `hnswlib` in-process, no PostgreSQL dependency.
- 10K-1M: pgvector with HNSW index (`M=16`, `ef_construction=200`, `ef_search=100`).
- 1M-100M: pgvector + pgvectorscale (TimescaleDB extension for streaming index updates and DiskANN).
- 100M+: Migrate cold tier to Qdrant (Rust core, distributed, async Python client). The `MemoryManager` protocol from Phase 3 makes this a backend swap, not an API change.

**Risk: Redis Pub/Sub Missed Invalidations**

Redis Pub/Sub is best-effort and non-persistent. If a subscriber is disconnected during a publish, it misses the invalidation message, and its L1 cache serves stale data until TTL expiry.

**Mitigation:** L1 TTL is set to 30-60 seconds (not minutes). A stale L1 entry lasts at most 60 seconds before it is evicted and the next read goes to L2/L3. This is acceptable for most agent memory use cases. For use cases requiring strict consistency (budget balances, security credentials), bypass L1 and always read from L2/L3 directly. Document which key namespaces are cache-safe vs. consistency-critical.

**Risk: GPTCache/Semantic Cache Threshold Tuning**

A threshold that is too low (0.70) causes false cache hits where semantically different prompts are treated as equivalent. A threshold that is too high (0.95) achieves negligible hit rates.

**Mitigation:** The `SemanticCache` threshold is configurable per agent and per task type. Default: 0.85 (50% hit rate, good accuracy). Safety-critical agents: 0.95. High-volume repetitive agents: 0.80. Emit a `cache.semantic_hit` metric with the actual similarity score. Use the distribution of observed scores to tune thresholds per workload. The threshold is a config value, not a code change.

---

### 1.6 A2A Protocol — Spec Maturity Risk

**Primary Risk: A2A Protocol is v0.3 — Spec May Change**

A2A v0.3 was released in early 2026. The protocol is backed by Google and 150+ organizations, but it is not yet a formal standards body recommendation. Breaking changes between v0.3 and v0.4+ are possible.

**Mitigation Architecture:** All A2A integration is isolated in `src/orchestra/interop/a2a/`. The `AgentExecutor` interface that translates A2A tasks to Orchestra graph runs is the sole coupling point. If the A2A spec changes, only this module changes — no graph engine code or agent business logic is affected.

**Risk: A2A SDK Version Pinning**

`a2a-sdk >= 0.3.24` must be pinned to a minor version. The `a2a-python` SDK follows the spec versioning; a spec update will likely increment the SDK minor version with breaking changes.

**Pin:** `a2a-sdk>=0.3.24,<0.4.0`. On each spec release, upgrade in isolation on a dedicated branch with a full integration test run before merging.

**Fallback: A2A via Plain HTTP if SDK Breaks**

A2A's wire format is JSON-RPC 2.0 over HTTPS. The Agent Card is a JSON file served at a well-known URL. If the SDK becomes incompatible, a ~500-line manual implementation handles the full protocol:
- Serve `/.well-known/agent-card.json` directly from FastAPI.
- Parse JSON-RPC 2.0 requests manually.
- Emit SSE events using FastAPI's native `StreamingResponse`.

This fallback is documented in `interop/a2a/fallback.py` as commented reference code, not active code.

---

### 1.7 PromptShield / Safety — SLM Hosting

**Primary Risk: PromptShield SLM Models Require GPU or ONNX Optimization for CPU**

The Sentinel model (355M parameters, ModernBERT-large) achieves 0.987 accuracy but requires GPU for sub-10ms inference. On CPU without ONNX optimization, inference can reach 100-500ms, which adds latency to every agent call.

**Tiered Deployment Strategy:**

- Development/CI: No SLM inference. Use regex-based heuristic scanner only (fast, zero latency, lower accuracy).
- Staging: `protectai/deberta-v3-small-prompt-injection-v2` (smaller, faster, acceptable accuracy for testing).
- Production with GPU: Sentinel (355M) via ONNX Runtime (`optimum` library) for 2-4x speedup.
- Production without GPU: `meta-llama/Prompt-Guard-86M` via ONNX. 86M parameters, achieves high F1, CPU-viable.
- Production minimal: `protectai/deberta-v3-base-prompt-injection-v2` (184M, ONNX, Apache 2.0).

The `PromptShieldGuard` class accepts a `backend: Literal["heuristic", "small", "medium", "large"]` parameter resolved from environment config. The parallel execution pattern (fire guard task concurrently with LLM task; cancel LLM if injection detected) eliminates guard latency from the critical path on the happy path regardless of which backend is used.

**Risk: Rebuff Archived**

Rebuff (protectai/rebuff) was archived in May 2025. It cannot be used as a dependency.

**Migration Map:**

| Rebuff Layer | Replacement |
|---|---|
| Heuristic scanning | Regex patterns maintained in `security/guardrails.py` (already in Phase 3) |
| LLM-based detection | SLM classifier (Sentinel / Prompt-Guard-86M) |
| VectorDB injection history | Optional: store injection signatures in the cold-tier vector DB |
| Canary tokens | Maintained in `security/canary.py` |

**Risk: Mutahunter is AGPL**

Mutahunter's AGPL license creates copyleft obligations if it is imported into Orchestra's source tree or distributed with it.

**Decision:** Mutahunter is never a runtime or test dependency. Use `mutmut 3.3.1` (BSD) as the primary mutation testing tool. Study Mutahunter's LLM-generated mutation strategies as a reference, implement equivalent agent-specific mutation operators in `testing/mutation.py` without copying Mutahunter code.

---

### 1.8 Ray Distributed Execution

**Primary Risk: Ray Integration Complexity**

Ray Serve wrapping Orchestra's FastAPI app via `@serve.ingress` changes the process model significantly. Ray manages its own event loop per actor, which conflicts with Orchestra's existing `asyncio` patterns if not carefully isolated.

**Key Rules:**
- Never call `asyncio.get_event_loop()` inside Ray actors. Use `asyncio.get_running_loop()` only.
- The `RayGraphExecutor` implements the same interface as the in-process `CompiledGraph`. Agents never call Ray APIs directly.
- Orchestra's event-sourced persistence externalizes all agent state. Ray's serialization requirement is satisfied naturally — nothing in agent state is un-serializable.
- If Ray's object store 100MB limit is reached for large context windows: store the payload in PostgreSQL/Redis and pass the key through Ray.

**Risk: Ray Serve Autoscaler and KEDA Conflict**

Ray Serve has its own autoscaling (`num_replicas` in deployment config). KEDA scales Deployments from outside. If both are active on the same Deployment, they issue conflicting scale operations.

**Resolution:** Choose one scaling authority per deployment type. KEDA controls the agent worker Deployments (scales based on NATS queue depth). Ray Serve's autoscaler controls the Ray head node and actor pools (scales based on pending tasks). These are different Kubernetes objects; they do not conflict. The kopf operator creates KEDA ScaledObjects for `OrchestraAgent` CRs and Ray actor scaling for `OrchestraRayWorkflow` CRs.

**Risk: Ray Cold Start for Actors (~50-200ms)**

New Ray actors take 50-200ms to initialize. For latency-sensitive agent workflows, this adds unacceptable overhead.

**Mitigation:** Pre-warm actor pools for critical agent types. KEDA's `activationLagThreshold: 1` wakes workers before the queue depth grows. Set `minReplicaCount: 1` (not 0) for the highest-priority agent worker pools so at least one actor is always warm.

**Fallback: Keep In-Process Execution**

If Ray integration proves too complex or introduces regressions, the existing in-process `CompiledGraph.run()` continues to work with zero changes. Ray is an additive capability behind the `RayGraphExecutor` class. The `GraphEngine` accepts an `executor` parameter; passing `None` uses the default in-process executor. Existing 244+ tests all use the in-process executor and are unaffected.

---

### 1.9 TypeScript SDK

**Primary Risk: OpenAPI Spec Drift**

The TypeScript SDK is generated from Orchestra's FastAPI OpenAPI spec via `openapi-typescript`. If FastAPI route signatures change (new parameters, renamed fields), the generated types drift and client callers break.

**Mitigation:** The OpenAPI spec is versioned. `POST /v1/runs` is locked once the SDK ships. Breaking changes require a new version prefix (`/v2/`). The SDK generation is a CI step that runs on every PR that touches `src/orchestra/server/`. If the generated output changes, the PR requires a separate SDK version bump commit.

**Risk: SSE Streaming in TypeScript**

Server-Sent Events in TypeScript require `EventSource` (browser) or `eventsource` npm package (Node). The async generator pattern for SSE consumption is not standard in all environments.

**Mitigation:** Generate a typed `streamRun()` function that wraps `EventSource` and yields typed event objects via `AsyncGenerator`. Include explicit handling for the `retry: 5000` reconnection header and `HTTP_LAST_EVENT_ID` state recovery. Document the pattern with a working example in the SDK repository.

---

## Section 2: Rollback Strategies Per Wave

### Wave 1 — Infrastructure Foundation: NATS, Kubernetes, OTel Collector

**What is added:**
- `src/orchestra/messaging/` — NATS JetStream client wrapper (new module)
- `src/orchestra/messaging/redis_streams.py` — Redis Streams fallback implementation
- `deploy/helm/` — Helm chart for Orchestra server + worker Deployments
- `deploy/terraform/` — Terraform modules for cluster provisioning
- `deploy/k8s/` — Base Kubernetes manifests, ServiceMonitors, NetworkPolicies
- `.github/workflows/k8s-deploy.yaml` — GitOps pipeline
- OTel Collector pipeline config (deferred from Phase 3): `deploy/otel/collector.yaml`
- Prometheus exporter configuration and sampling strategy

**Rollback tier: Tier 1 (all additive — no existing source files modified)**

Rollback procedure:
1. `git revert -m 1 <wave-1-merge-commit>` removes all new files cleanly.
2. Infrastructure deployed to Kubernetes is independent of the Python source. If infrastructure deployment fails: `helm rollback orchestra` reverts to the previous Helm release. If no previous release exists: `helm uninstall orchestra` and restart from scratch.
3. The OTel Collector is separate infrastructure; removing its K8s manifest does not affect the application OTel SDK already present from Phase 3.
4. The existing in-process test suite never imports `orchestra.messaging` and is unaffected.

**Recovery time:** Under 5 minutes for source revert. Infrastructure rollback time depends on cluster state; plan for 10-20 minutes.

---

### Wave 2 — Cost Intelligence: CostRouter, Circuit Breakers, Billing

**What is added:**
- `src/orchestra/routing/` — CostAwareRouter, SLARouter, ThompsonSampler (new module)
- `src/orchestra/routing/circuit_breaker.py` — `aiobreaker`-backed per-provider circuit breakers
- `src/orchestra/routing/failover.py` — FallbackChain + StrategySwitch (native vs. prompted)
- `src/orchestra/billing/` — BillingAggregator, tenant ledger, Stripe plugin (new module)
- One modification to `agent.py`: optional `router: Optional[CostAwareRouter] = None` parameter. When `None`, agent calls `LLMProvider` directly (existing behavior).
- One modification to `providers/base.py`: expose `strategy` attribute (`native` or `prompted`) for `StrategySwitch` to read.

**Rollback tier: Tier 2 for agent.py and providers/base.py modifications; Tier 1 for new modules**

Rollback procedure:
1. `git revert <wave-2-merge-commit>` removes new modules and reverts the two file modifications.
2. The `router=None` guard in `agent.py` means existing tests that do not inject a router are unaffected. The modification is a single parameter addition with a default.
3. If only the billing module causes issues: `billing/` can be reverted independently while keeping `routing/` active.
4. The `StrategySwitch` in `providers/base.py` is a read-only attribute addition. Reverting it does not break any existing provider implementations.

**Recovery time:** Under 10 minutes.

---

### Wave 3 — Agent IAM: Identity, Credentials, UCAN, SecretProvider

**What is added:**
- `src/orchestra/security/identity/` — AgentIdentity, DID resolution, VC issuance (new subpackage)
- `src/orchestra/security/secrets.py` — SecretProvider ABC + Vault/AWS/GCP implementations
- `src/orchestra/security/ucan.py` — UCAN delegation using `py-ucan 1.0.0`
- One modification to `core/context.py`: add `identity: Optional[AgentIdentity] = None` and `secrets: Optional[SecretProvider] = None` fields to `AgentContext`.
- One modification to `security/acl.py`: add UCAN verification as an optional secondary check when identity is present.

**Rollback tier: Tier 2 for context.py and acl.py; Tier 1 for new modules**

Rollback procedure:
1. `git revert <wave-3-merge-commit>` reverts all changes.
2. The `identity=None` and `secrets=None` fields in `AgentContext` use `Optional` with `None` defaults. All existing code that constructs `AgentContext` without these fields continues to work. The rollback restores the pre-IAM state.
3. UCAN verification in `acl.py` is guarded by `if context.identity is not None and context.identity.verified_credentials:`. Agents without identity (the legacy mode) bypass this check entirely. Rollback is not required to disable UCAN — just don't inject an `AgentIdentity`.
4. The `[iam]` extras group means IAM dependencies are not installed unless explicitly requested. A rollback of the pip extras does not break the base installation.

**Recovery time:** Under 10 minutes for source. IAM key material (DID Documents, VC issuers) requires separate deprovisioning from Vault and external hosting; plan for 30-60 minutes.

---

### Wave 4 — Distributed Execution: Ray, NATS Workers, Dynamic Subgraphs

**What is added:**
- `src/orchestra/executors/ray_executor.py` — RayGraphExecutor implementing GraphExecutor protocol
- `src/orchestra/graph/dynamic.py` — Dynamic subgraph Send API and mutation primitives
- `src/orchestra/operator/` — kopf-based K8s operator for OrchestraAgent CRDs
- `deploy/k8s/crds/` — OrchestraAgent CRD schema
- One modification to `core/compiled.py`: accept optional `executor: Optional[GraphExecutor] = None` parameter. When `None`, uses the existing in-process execution (unchanged behavior).

**Rollback tier: Tier 2 for compiled.py; Tier 1 for all other additions**

Rollback procedure:
1. `git revert <wave-4-merge-commit>`.
2. The `executor=None` guard in `compiled.py` means all existing tests using the in-process executor are unaffected. This is the identical pattern used for OTel (`otel_tracer=None`) in Phase 3 Wave 1.
3. If Ray causes regressions but dynamic subgraphs do not: revert only `ray_executor.py` and the `compiled.py` executor parameter. Keep `graph/dynamic.py`.
4. kopf operator and CRDs are Kubernetes-only. Reverting them requires: `kubectl delete -f deploy/k8s/crds/` to remove CRD from cluster. The kopf Python code reverts with the source revert.
5. NATS workers launched by the operator are Kubernetes Deployments. They are removed via `kubectl delete deployment` or by the CRD deletion cascading through owner references.

**Recovery time:** Under 15 minutes for source and CRD removal. Ray cluster teardown depends on cluster state.

---

### Wave 5 — Interoperability and Testing: A2A, TypeScript SDK, SPRT, Behavioral Fingerprinting

**What is added:**
- `src/orchestra/interop/a2a/` — A2A protocol handler, Agent Card generator, AgentExecutor
- `src/orchestra/testing/sprt.py` — SPRTBinomial implementation (~100 lines)
- `src/orchestra/testing/fingerprint.py` — BehavioralFingerprint + DriftMonitor
- `src/orchestra/testing/mutation.py` — AgentMutator operators (ToolCallMutator, PromptMutator, etc.)
- `sdk/typescript/` — Generated TypeScript SDK (separate repo or subdirectory)
- `tests/e2e/` — Full E2E test suite against deployed Kubernetes environment

**Rollback tier: Tier 1 (all additive)**

Rollback procedure:
1. `git revert <wave-5-merge-commit>`.
2. The A2A module mounts as a FastAPI sub-application. If it causes issues, remove the `app.mount("/a2a", a2a_app)` line from `server/app.py` — a one-line change that does not require a full revert.
3. Testing modules (`sprt.py`, `fingerprint.py`, `mutation.py`) are never imported by production code paths. They cannot cause production regressions.
4. TypeScript SDK is a separate artifact; reverting the Python source does not affect any already-distributed SDK packages.

**Recovery time:** Under 5 minutes.

---

## Section 3: Dependency Risk Mitigation

### DIDKit (Archived July 2025)

**Impact:** High. Was the primary Python DID/VC library. No direct replacement exists at the same API level.

**Mitigation:**
- Use `peerdid 0.5.2` for `did:peer` creation and resolution. Apache 2.0, actively maintained, no Rust build dependency.
- Use `did:web` for organizational agents with manual HTTPS-based DID Document hosting. Resolution is plain HTTP, implemented in ~30 lines with `httpx`.
- VC issuance: `PyLD` (JSON-LD) + `joserfc` (JWT). Both are stable, widely used.
- Do not add `didkit` as a dependency at all. Remove any existing references in planning documents.
- Pin the replacement stack in `pyproject.toml [project.optional-dependencies] iam` group and verify all four libraries install cleanly in CI on Linux x86_64, Linux ARM64, and macOS ARM64.

### Rebuff (Archived May 2025)

**Impact:** Medium. Phase 3 guardrails did not depend on Rebuff. Phase 4 PromptShield is a fresh implementation using SLMs.

**Mitigation:** Use `llm-guard 0.3.x` (protectai, MIT) as the heuristic scanning backbone. Its `BanSubstrings`, `BanTopics`, and `PromptInjection` scanners replace Rebuff's heuristic and LLM layers. The SLM classifier (Prompt-Guard-86M or Sentinel) replaces Rebuff's LLM detection layer. Canary token logic is custom (already in the Phase 3 `security/guardrails.py` framework).

### py-ucan 1.0.0

**Risk:** `py-ucan` is v1.0.0 (first stable release). API stability is unverified across minor versions.

**Mitigation:** Pin `py-ucan>=1.0.0,<2.0.0`. All UCAN operations are wrapped in `security/ucan.py` — the rest of the codebase never imports `py_ucan` directly. If `py-ucan` breaks: the UCAN layer can be reimplemented from the UCAN spec (~300 lines of JWT operations using `joserfc`) without touching any dependent code.

### aiobreaker (Circuit Breakers)

**Risk:** `aiobreaker` is a smaller library. Version compatibility with `asyncio` changes.

**Mitigation:** Pin `aiobreaker>=1.2,<2.0`. All circuit breaker usage is behind the `routing/circuit_breaker.py` abstraction. The `CircuitBreaker` Protocol allows swapping `aiobreaker` for `purgatory` or a custom implementation without touching `ProviderFailover` logic.

### nats-py 2.14.0

**Risk:** nats-py follows the NATS server release cadence. API changes between minor versions are possible.

**Mitigation:** Pin `nats-py>=2.14.0,<3.0`. The `MessageBroker` protocol wraps all NATS calls. Integration tests run against a real NATS server (Docker Compose or Testcontainers). A CI job starts the NATS server as a service before running NATS-dependent tests; these tests are skipped if the NATS server cannot start (to keep the test suite runnable without infrastructure).

### kopf 1.38.0

**Risk:** Maintenance mode. Python or Kubernetes API compatibility issues may not be fixed upstream.

**Mitigation:** The kopf operator is in `src/orchestra/operator/` and can be replaced with a raw `kubernetes` Python client implementation if kopf becomes incompatible. The CRD schema and OrchestraAgent CR format are independent of kopf — they are Kubernetes API objects. A kopf replacement is a code change in `operator/`, not a breaking change to users.

### A2A SDK (`a2a-sdk`)

**Risk:** v0.3.x is the current version. Spec-driven breaking changes are expected as the protocol matures.

**Mitigation:** Pin `a2a-sdk>=0.3.24,<0.4.0`. All A2A integration is behind `interop/a2a/`. A spec upgrade is a controlled update to that module with a full integration test run. The A2A sub-application is mounted under a versioned prefix (`/a2a/v0.3/`) so clients can pin to a protocol version.

### redis-py 7.3.0

**Risk:** The async client does not support CLIENT TRACKING (issue #3916). This is a known limitation, not a bug — it is unlikely to be fixed without architectural changes to the library.

**Mitigation:** Manual Pub/Sub invalidation is the documented pattern. Design around this limitation: never assume CLIENT TRACKING will become available. If redis-py 8.x resolves the issue, migrate to CLIENT TRACKING as an optional optimization, not a requirement.

### High-Cardinality Prometheus Labels

**Risk:** Using `tenant_id` or `user_id` as Prometheus metric labels causes label cardinality explosion. At 10,000+ tenants, Prometheus TSDB crashes or degrades severely.

**Rule:** `tenant_id` and `user_id` are NEVER metric labels. They are OTel span attributes only (queryable via trace backends like Jaeger/Tempo). Budget and cost metrics use aggregate labels: `{model, provider, tier}`. Per-tenant cost data lives in the billing ledger database, not in Prometheus.

---

## Section 4: Scope Reduction Playbook

For each major Phase 4 area, an MVP definition that provides standalone value and does not block subsequent areas.

### IAM MVP (if time-constrained)

**Full scope:** DID lifecycle (Spawning → Credential Attachment → Presentation → Session), VC issuance/verification, OIDC bridge, UCAN delegation, ZKP selective disclosure.

**MVP:** `AgentIdentity` dataclass backed by JWT (no W3C DID resolution). `SecretProvider` with Vault (`hvac`) and local env backends. `py-ucan` delegation for tool ACL enforcement. OIDC bridge validating id_tokens from Okta/Auth0.

**What you lose:** W3C DID interoperability, cross-org VC presentation, cryptographically verifiable identity chains without a shared IdP.

**What you keep:** Agents have cryptographically signed identities. Tool access is capability-scoped. Secrets are fetched from Vault, not environment variables. Enterprise IdP integration works.

**Upgrade path:** Replace JWT-backed `AgentIdentity` with DID-backed `AgentIdentity`. The `AgentIdentity` interface does not change — only the internal verification mechanism changes.

---

### Cost Routing MVP (if time-constrained)

**Full scope:** Heuristic tier + Thompson Sampling + MF predictor + SLA router + circuit breakers + billing + persistent budget.

**MVP:** Heuristic tier (classify by token count → route to small/medium/large model tier) + circuit breakers with `aiobreaker` + persistent budget ledger (SQLite-backed `PersistentBudgetPolicy` replacing Phase 3 in-memory policy). No Thompson Sampling. No MF. No SLA router. No Stripe integration.

**What you lose:** Adaptive model selection learning from outcomes. SLA-based routing decisions. External billing integration.

**What you keep:** Immediate ~30-40% cost reduction from heuristic routing. Budget enforcement that survives process restarts. Provider failover when primary provider circuit trips.

**Upgrade path:** Add Thompson Sampling as a pluggable strategy within `CostAwareRouter`. It does not change the router interface, only the selection algorithm.

---

### Distributed Execution MVP (if time-constrained)

**Full scope:** Ray Serve + Ray Core actors + NATS JetStream + KEDA autoscaling + kopf operator + Dynamic Subgraphs.

**MVP:** NATS JetStream for task distribution (pull consumers on agent worker Deployments) + KEDA ScaledObjects based on NATS queue depth. No Ray. No kopf operator. Agent workers are standard Kubernetes Deployments pulling tasks from NATS and processing them with the existing in-process `CompiledGraph`.

**What you lose:** Ray's distributed actor model, Ray Serve's advanced deployment features, dynamic subgraph mutation at runtime.

**What you keep:** Horizontal scalability — multiple worker pods process tasks from the NATS queue in parallel. KEDA scales worker count based on queue depth. The application correctly distributes work across instances.

**Upgrade path:** Replace the in-process `CompiledGraph.run()` in worker pods with `RayGraphExecutor` as a later increment. The NATS consumer pattern is unchanged.

---

### Memory Tier MVP (if time-constrained)

**Full scope:** Redis L2 + SLRU promote/demote + pgvector cold tier + hybrid retrieval (BM25+dense) + semantic deduplication + state compression.

**MVP:** Redis L2 backplane with Pub/Sub invalidation (extends Phase 3 `CacheBackend` protocol) + basic MemoryManager promote/demote with LRU policy. No pgvector. No semantic deduplication. No state compression.

**What you lose:** Long-term vector memory, semantic search, memory compression.

**What you keep:** Shared L2 cache across multiple instances (critical for Kubernetes deployment correctness). Memory tier lifecycle (promote hot items, demote cold items).

**Upgrade path:** Add pgvector cold tier as a `MemoryManager` backend. The `MemoryManager` protocol is already defined from Phase 3.

---

### A2A MVP (if time-constrained)

**Full scope:** Agent Card with all required fields, A2A AgentExecutor, Agent Card Registry, A2A gRPC transport, arbitration nodes.

**MVP:** Static `agent-card.json` served at `/.well-known/agent-card.json` describing the Orchestra instance's capabilities. A2A JSON-RPC task handler that maps `send_message` to `POST /v1/runs` (no streaming). No Agent Card Registry. No gRPC.

**What you lose:** Real-time streaming over A2A, dynamic skill discovery as graphs are registered, cross-org agent discovery.

**What you keep:** Basic A2A interoperability — any A2A-compatible framework can dispatch tasks to Orchestra and poll for results.

**Upgrade path:** Add SSE streaming to the A2A task handler. Add dynamic Agent Card generation from `GraphRegistry`. Mount as a full `A2AStarletteApplication`.

---

## Section 5: Integration Conflict Map

Phase 4 introduces many components that interact. This section identifies the specific conflict surfaces.

| Component A | Component B | Conflict Surface | Resolution |
|---|---|---|---|
| KEDA ScaledObjects | Ray Serve autoscaler | Both issue scale commands to agent Deployment | KEDA scales worker Deployments; Ray Serve scales its own actors. Never overlap on the same Kubernetes object. |
| Redis L2 Pub/Sub | Budget enforcement | Missed invalidation allows brief overspend | Set hard budget at 95% of nominal. Use `PersistentBudgetPolicy` with pessimistic locking for hard limits. |
| OTel Baggage `tenant_id` | Prometheus metric labels | High-cardinality metric explosion | `tenant_id` is span attribute only. Never add to metric labels. |
| NATS message payload | Event store state | State must survive NATS message loss | NATS carries reference only; full state in PostgreSQL event store. NATS ack is separate from state persistence. |
| Ray actor event loop | Orchestra asyncio patterns | Ray manages its own event loop per actor | Use `asyncio.get_running_loop()` only inside Ray actors. Never `asyncio.get_event_loop()` or `asyncio.run()`. |
| A2A sub-application mount | FastAPI main app | Route conflicts at `/` or `/.well-known/` | Mount A2A at versioned prefix `/a2a/v0.3/`. Serve Agent Card at `/.well-known/agent-card.json` via main app route, not A2A sub-app. |
| kopf operator | Kubernetes Garbage Collection | Operator-created resources leak if finalizer not set | Use kopf finalizers for all resources with external state (NATS streams, database state). Use owner references for K8s-only resources. |
| DID resolution | did:web DNS dependency | DNS outage prevents identity verification | Cache DID Documents with 15-minute TTL. Fail-open on DID resolution failure for in-flight requests (log warning, continue with cached identity). Fail-closed only for new session establishment. |
| Thompson Sampling state | Process restarts | Learned alpha/beta posteriors lost on restart | Persist posterior state in the billing ledger SQLite database after each update. Cold start reloads posteriors; no data loss. |
| PII redaction in OTel | Token cost accounting | Redaction must happen before cost processor reads token content | PII redaction processor runs first in the OTel pipeline. Cost processor reads only token counts (numeric), not content. Order enforced in `observability/tracing.py` processor chain initialization. |

---

## Section 6: Scale Failure Modes

| Scenario | Failure Symptom | Detection | Resolution |
|---|---|---|---|
| NATS queue depth unbounded growth | Worker pods cannot keep pace with task arrival | KEDA lag metric > `lagThreshold` sustained for 5+ minutes | Scale `maxReplicaCount` up. If already at max: enable `CostAwareRouter` to reject tasks above budget. |
| Redis L2 memory exhaustion | `OOM` errors from Redis; cache misses spike | Redis `used_memory > maxmemory * 0.9` alert | Set `maxmemory-policy allkeys-lru`. Redis evicts L2 cache entries; L1 TTL picks up the slack. Application continues without L2 (degraded but functional). |
| pgvector index build time | Cold tier writes time out during bulk load | `INSERT ... RETURNING` latency > 1 second | Disable HNSW index during bulk load (`SET LOCAL enable_indexscan = off`). Rebuild index offline after bulk load completes. |
| Ray object store saturation | `ObjectStoreFullError` for large context windows | Ray dashboard object store usage > 80% | Payload reference pattern (see §1.3): store payloads in PostgreSQL, pass keys through Ray. |
| Prometheus TSDB cardinality crash | Prometheus OOM due to too many time series | Prometheus metric count alert or memory spike | Remove offending high-cardinality label (e.g., `tenant_id` accidentally added). Restart Prometheus with `--storage.tsdb.retention.time=2h` for fast recovery. Permanently fix the label at the source. |
| Kubernetes DNS overload from DID resolution | DID Document fetches time out | High-cardinality DNS query rate, CoreDNS latency spike | DID Document cache TTL is 15 minutes per instance. Add Redis-backed shared DID Document cache (L2) to reduce DNS query rate to once per 15 minutes per unique DID across all instances. |
| Circuit breaker flapping | Providers cycling between OPEN and HALF-OPEN | `circuit_breaker.state_change` metric rate > 3/minute | Increase `reset_timeout` (time in OPEN state before testing). Add exponential backoff on HALF-OPEN failures. |
| SPRT inconclusive rate too high | Testing never reaches a conclusion | SPRT `inconclusive` verdict rate > 50% | Increase `N_max` (maximum samples before forced decision). Widen the indifference zone (`p0 - p1` gap). Accept that stochastic agents have inherent variance and use fixed-sample testing for high-variance agents. |

---

## Section 7: Phase 5 Dependency Mapping

| Phase 4 Output | Phase 5 Task That Needs It | Hard Dependency? |
|---|---|---|
| `AgentIdentity` + UCAN delegation | Cross-org federation, multi-cloud deployment | Yes — cross-org A2A requires cryptographic identity |
| `PersistentBudgetPolicy` + billing ledger | Multi-cloud cost optimization, SLA contracts | Yes — billing requires persistent data |
| NATS JetStream + KEDA autoscaling | Global multi-region deployment | Yes — NATS clustering across regions |
| A2A Agent Card + Registry | Public marketplace, partner integrations | Yes — discovery requires stable Agent Card format |
| TypeScript SDK | Browser-based orchestration UI | Yes — UI consumes the SDK |
| `RayGraphExecutor` | GPU inference integration, large-scale parallel execution | Soft — in-process executor can be kept |
| pgvector cold tier | Cross-session episodic memory, audit retrieval | Yes — long-term memory requires durable vector storage |
| OTel Collector with tail sampling | Cost-efficient telemetry at 10TB+/day scale | Yes — 100% trace capture is not viable at Phase 5 volume |
| SOC2 Type I readiness | Enterprise sales, regulated industry customers | Yes — SOC2 Type II evidence collection requires Phase 4 controls running for 6+ months |
| PromptShield SLM | Adversarial robustness testing, red-teaming | Soft — red-teaming can proceed with heuristic-only guardrails |

---

## Section 8: Data Safety — Protecting Phase 3 Tests

**Rule 1: Unit tests never import Phase 4 infrastructure modules.**

`tests/unit/` must not import `orchestra.messaging`, `orchestra.routing.circuit_breaker`, `orchestra.security.identity`, `orchestra.executors.ray_executor`, or any module that requires external services (Redis, NATS, Vault, Ray). Enforce with an import boundary check in CI that fails if a unit test file resolves one of these imports without a mock.

**Rule 2: Phase 4 integration tests use infrastructure via Testcontainers or skips.**

Integration tests that require NATS, Redis, or PostgreSQL start real containers via `testcontainers-python`. If Docker is unavailable (CI environment without Docker-in-Docker), these tests are skipped via a `pytest.mark.requires_docker` marker — they do not fail.

**Rule 3: All Phase 4 modifications to existing source files use Optional parameters with None defaults.**

The pattern established in Phase 3 (OTel tracer injection, output validator injection) is mandatory for Phase 4:
- `compiled.py`: `executor: Optional[GraphExecutor] = None`
- `agent.py`: `router: Optional[CostAwareRouter] = None`
- `core/context.py`: `identity: Optional[AgentIdentity] = None`, `secrets: Optional[SecretProvider] = None`

No existing call site changes. Existing tests pass without modification.

**Rule 4: The 244+ unit tests run first in every CI job.**

```
job: unit-tests         (always runs; blocks everything else)
  pytest tests/unit/ -x

job: integration-tests  (runs after unit-tests passes)
  pytest tests/integration/ -m "not requires_docker"

job: docker-integration (runs after unit-tests; parallel with integration-tests)
  pytest tests/integration/ -m "requires_docker"

job: wave-gate          (runs after all test jobs pass)
  check coverage thresholds
  check import boundary violations
```

**Rule 5: Security-sensitive secrets are never in test fixtures.**

Test fixtures that require `SecretProvider` use `LocalEnvSecretProvider` backed by `pytest` fixture values (not environment variables). No test ever reaches out to a real Vault or AWS Secrets Manager.

---

## Appendix A: Git Branch and Tag Discipline

```
master                    (Phase 3 complete baseline — protected)
  └── phase-4/wave-1      (NATS + K8s + OTel Collector)
  └── phase-4/wave-2      (Cost Intelligence)
  └── phase-4/wave-3      (Agent IAM)
  └── phase-4/wave-4      (Distributed Execution)
  └── phase-4/wave-5      (A2A + SDK + Testing)
  └── phase-4/integration (landing branch; wave branches merge here after gate)
```

Tags to create:
- `phase4-pre-wave-1` — before any Wave 1 work begins (after Phase 3 merges to master)
- `phase4-post-wave-1` — after Wave 1 merges to integration and gate passes
- `phase4-pre-wave-N` / `phase4-post-wave-N` for each wave
- `phase4-complete` — after all waves merge to master

Rollback commands (for reference):
```bash
# Revert a wave merge from the integration branch
git revert -m 1 <wave-N-merge-commit-sha>

# Single-file revert (e.g., compiled.py introduced a regression)
git checkout phase4-pre-wave-4 -- src/orchestra/core/compiled.py

# Verify Phase 3 baseline tests pass after any revert
pytest tests/unit/ -x -q

# Infrastructure-only rollback (no source change needed)
helm rollback orchestra <revision-number>
```

---

## Appendix B: Decision Log — What Is Cut and Why

| Item | Decision | Reason |
|---|---|---|
| Python subinterpreters (PEP 734 / `InterpreterPoolExecutor`) | Deferred to Phase 5 | Python 3.14's extension compatibility is incomplete. `sqlite3`, most ML frameworks not yet compatible. Use `asyncio` (I/O-bound) and `ProcessPoolExecutor` (CPU-bound) instead. Re-evaluate at Python 3.15+. |
| zcap-ld capability delegation | Replaced by UCAN | No Python library exists. UCAN is the active alternative with `py-ucan 1.0.0` on PyPI. zcap-ld spec is stagnant. |
| BBS+ Selective Disclosure (ZKP) | Replaced by multi-VC pattern | No production-ready Python library. MATTR's Rust implementation has no Python wrapper. Multi-VC selective disclosure achieves equivalent authorization semantics. |
| GPTCache as semantic cache dependency | Replaced by custom `SemanticCache` | Maintenance declining (83 unreleased commits). A purpose-specific implementation using `hnswlib` + `Model2Vec` is smaller, more controllable, and has no transitive dependency risk. |
| Rebuff as prompt injection dependency | Replaced by `llm-guard` + SLM | Rebuff archived May 2025. `llm-guard` (protectai, MIT) provides equivalent heuristic scanning. Sentinel/Prompt-Guard-86M SLMs provide the detection layer. |
| Mutahunter as mutation testing dependency | Reference only | AGPL license creates copyleft obligations. `mutmut` (BSD) covers conventional mutation testing. Agent-specific mutation operators are implemented custom in `testing/mutation.py`. |
| Gossip protocol (Python library) | Replaced by NATS built-in discovery | No production-grade, async-native Python SWIM library exists. NATS JetStream's internal gossip handles cluster discovery. Custom gossip deferred to Phase 5 for cross-org scenarios. |
| Stripe LLM Meters API | Internal billing first | API is in preview/waitlist as of March 2026. Internal SQLite ledger provides full chargeback capability. Stripe is an optional plugin enabled when GA is confirmed. |
| SPRT framework (Phase 3) | Implemented in Phase 4 as planned | Cut from Phase 3 per ToT analysis to avoid overplanning. Research confirmed the design. Implemented in Wave 5. |
| SOC2 Type II certification | Ongoing evidence collection | Type I (point-in-time) readiness is Phase 4. Type II requires 6+ months of operational evidence — starts accumulating in Phase 4, certified in Phase 5. |
| Certification program (OCD/OCA) | Phase 5 | Requires stable SDK and marketplace first. Not blocking any Phase 4 technical deliverable. |

---

*Last updated: 2026-03-11*
*Authored by: backup-planner agent*
