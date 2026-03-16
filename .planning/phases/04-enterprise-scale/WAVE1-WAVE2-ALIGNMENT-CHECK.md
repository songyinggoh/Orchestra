# Phase 4: Wave 1 + Wave 2 Alignment Check

**Checked:** 2026-03-12
**Checker:** Claude Opus 4.6 (gsd-plan-checker)
**Scope:** Verify Wave 1 deliverables and Wave 2 plan align with the Phase 4 "Enterprise & Scale" goal
**Method:** Goal-backward verification across 6 dimensions

---

## Phase 4 Goal (from ROADMAP.md)

> Transform Orchestra from a single-instance production framework into a distributed,
> enterprise-grade platform with cost-intelligent routing, agent identity, multi-tier
> memory, A2A interoperability, and Kubernetes deployment.

**Decomposed Requirements:**
1. Distributed backbone (NATS messaging, K8s deployment)
2. Cost-intelligent routing (model selection, failover, budget)
3. Agent identity and authorization (DIDs, signed cards, UCAN)
4. Multi-tier memory (Redis L2, pgvector cold tier)
5. A2A interoperability (Agent Cards, cross-org protocol)
6. Kubernetes deployment (Helm, autoscaling, sandboxing)

---

## 1. Goal Alignment

### Wave 1 Deliverables vs Phase 4 Goal

| Deliverable | Phase 4 Requirement | Alignment |
|-------------|---------------------|-----------|
| T-4.1 NATS JetStream + DIDComm E2EE | Distributed backbone | DIRECT -- establishes inter-agent messaging |
| T-4.2 K8s + Helm + gVisor/KEDA | Kubernetes deployment | DIRECT -- full deployment story |
| T-4.3 Wasm Tool Sandbox | Security hardening | SUPPORTING -- hard sandboxing for enterprise trust |

**Assessment: STRONG ALIGNMENT.** Wave 1 correctly established the distributed backbone as the foundation. The ToT analysis explicitly recommended "NATS is the backbone -- deploy first." This was followed correctly.

### Wave 2 Plan vs Phase 4 Goal

| Planned Task | Phase 4 Requirement | Alignment |
|--------------|---------------------|-----------|
| T-4.4 CostAwareRouter + Failover | Cost-intelligent routing | DIRECT |
| T-4.5 Persistent Budget | Cost-intelligent routing | DIRECT |
| T-4.6 Agent Identity + Signed Cards | Agent identity | DIRECT |
| T-4.7 UCAN + TTLs | Agent authorization | DIRECT |

**Assessment: STRONG ALIGNMENT.** Wave 2 covers two of the six decomposed requirements (cost intelligence and agent identity). The parallel track structure (Track A: cost, Track B: identity) is correct because these are independent subsystems with no inter-dependencies.

### Gap: Neither Wave 1 nor Wave 2 addresses multi-tier memory (requirement 4) or A2A interoperability (requirement 5). These are correctly deferred to Waves 3 and 4 respectively. No premature scope creep.

**VERDICT: PASS** -- Waves 1+2 collectively address 4 of 6 phase requirements, with the remaining 2 properly scheduled in later waves.

---

## 2. Dependency Chain Integrity

### Wave 2 -> Phase 3 Dependencies

| Wave 2 Task | Claims Dependency On | Code Exists? | Status |
|-------------|---------------------|--------------|--------|
| T-4.4 | Phase 3 T-3.6 CostAggregator | `src/orchestra/cost/aggregator.py` (183 lines) | SATISFIED |
| T-4.4 | Phase 3 AsyncCircuitBreaker | `src/orchestra/security/circuit_breaker.py` (185 lines) | SATISFIED |
| T-4.4 | Phase 3 LLM Providers | `src/orchestra/providers/` (6 provider files) | SATISFIED |
| T-4.5 | Phase 3 BudgetPolicy | `src/orchestra/cost/budget.py` + `tenant.py` | SATISFIED |
| T-4.6 | Phase 3 complete | Server, OTel, security all present | SATISFIED |
| T-4.7 | T-4.6 (Agent Identity) | Not yet built (Wave 2 Track B) | PLANNED |

### Wave 2 -> Wave 1 Dependencies

| Wave 2 Task | Claims Dependency On | Code Exists? | Status |
|-------------|---------------------|--------------|--------|
| T-4.4 | None (depends on Phase 3 only) | N/A | OK |
| T-4.5 | T-4.4 (CostAwareRouter) | Not yet built | PLANNED (same wave, sequential) |
| T-4.6 | Phase 3 complete | N/A | OK |
| T-4.7 | T-4.6 (Agent Identity) | Not yet built | PLANNED (same wave, sequential) |

### Critical Finding: Pre-existing Code

Several Wave 2 files already exist in the codebase, apparently from earlier Phase 3 or Phase 4 planning work:

| File | Lines | Status | Alignment with PLAN.md |
|------|-------|--------|----------------------|
| `src/orchestra/routing/router.py` | 214 | Has CostAwareRouter + ThompsonModelSelector | PARTIAL -- missing SelectionFallback (DD-1), RoutingHints (DD-13), TTFT (DD-14) |
| `src/orchestra/providers/failover.py` | 161 | Has ProviderFailover + AsyncCircuitBreaker | PARTIAL -- has its own CircuitBreaker (duplicates security/ one), missing TTFT, budget pre-check |
| `src/orchestra/identity/agent_identity.py` | 169 | Has AgentIdentity + AgentCard + Ed25519Signer | PARTIAL -- missing SignedDiscoveryProvider, did:web support, card_hash (DD-19) |
| `src/orchestra/identity/ucan.py` | 135 | Has UcanManager + UcanAuthenticator | STALE -- imports py-ucan which DD-9 explicitly rejects as broken |
| `src/orchestra/cost/persistent_budget.py` | 118 | Has PersistentBudgetStore + TenantBudgetManager | PARTIAL -- uses floats (DD-11 requires microdollars), no idempotency key (DD-12), no pessimistic locking (DD-2) |
| `src/orchestra/cost/tenant.py` | 67 | Has Tenant, BudgetConfig, BudgetState | PARTIAL -- no hierarchy semantics (DD-2) |

**WARNING: The existing `identity/ucan.py` imports `py-ucan` which DD-9 confirmed is broken (no working JWT serialization, poetry as runtime dep, version conflicts). This file MUST be rewritten to use joserfc JWT directly before Wave 2 execution.**

**WARNING: `providers/failover.py` defines its own `AsyncCircuitBreaker` class (lines 28-89) which duplicates `security/circuit_breaker.py`. DD-6 explicitly decided to keep the security/ version. The failover module needs refactoring to use the canonical breaker.**

**VERDICT: PASS with WARNINGS** -- All claimed dependencies are satisfied by existing code. Pre-existing Wave 2 code requires significant revision to match design decisions.

---

## 3. Forward Compatibility

### Does T-4.6 (Identity) enable T-4.11 (A2A Protocol)?

**T-4.11 requires:** A2AService + AgentCardBuilder, A2A SDK integration, Agent Card served at `/.well-known/agent-card.json`, cross-org communication.

**T-4.6 provides:**
- AgentIdentity with DID-backed signing (Ed25519) -- A2A needs this for card signing
- AgentCard dataclass with name, type, capabilities, DID, signature -- A2A compatible
- Ed25519Signer -- signing protocol usable by A2A service
- did:peer:2 for ephemeral agents, did:web for long-lived agents (DD-7)

**Assessment: ENABLES.** The AgentCard structure from T-4.6 maps cleanly to the A2A Agent Card specification. The DID + Ed25519 signing infrastructure provides the cryptographic foundation T-4.11 needs. The card_hash integrity check (DD-19) provides tamper detection that A2A cross-org scenarios require.

**One concern:** T-4.6 plans AgentCard as a simple dataclass with custom fields. T-4.11 uses `a2a-sdk>=0.3.24` which has its own AgentCard class. Potential friction if the T-4.6 card format diverges from the A2A SDK format. However, B3 in the research topics explicitly calls this out, and the existing AgentCard already includes A2A-compatible fields (name, capabilities, DID). **Low risk.**

### Does T-4.4 (CostRouter) enable T-4.5 (Budget)?

**T-4.5 requires:** Model selection events to charge against, estimated costs before LLM calls, actual costs after LLM calls.

**T-4.4 provides:**
- `CostAwareRouter.select_model()` returns a `ModelOption` with cost rates
- `report_outcome()` provides success/failure signal
- `ProviderFailover` provides the execution path where costs are incurred
- DD-1 defines `SelectionFallback` for conflict resolution
- DD-16 defines proactive budget lock during failover

**Assessment: ENABLES CLEANLY.** The router-then-budget pattern is sound:
1. Router selects model -> budget deducts estimated cost
2. Provider executes -> budget reconciles actual cost
3. Failover triggers -> budget pre-check before expensive fallback (DD-16)

The DD-16 cross-cutting concern is the most complex integration point, but it has been explicitly designed with clear sequencing.

### Do DID choices (DD-7, DD-8) work for T-4.11 A2A?

**DD-7:** did:peer:2 for ephemeral, did:web for long-lived agents.
**DD-8:** Custom `orchestra.messaging.peer_did` module (no external peerdid lib).
**A2A requires:** DIDs for agent identification, verifiable signatures on Agent Cards.

**Assessment: COMPATIBLE.** The A2A Protocol specification supports multiple DID methods. `did:web` is the most common for organizational agents in A2A (it resolves via standard HTTPS). `did:peer:2` works for intra-organization agents. The custom peer_did module (DD-8) generates standard-compliant `did:peer:2` strings, verified by 7 passing tests.

**One forward concern:** T-4.11 includes ZKP Input Commitments using `py-ecc`. This is orthogonal to the DID infrastructure. The ZKP component does not depend on the DID method choice -- it depends on having a signing key (which T-4.6 provides via Ed25519). **No conflict.**

### Does Wave 1 E2EE constrain or enable Wave 3+4?

**Wave 3 (Memory):** Redis L2 and pgvector cold tier operate on decrypted data within the application boundary. NATS E2EE encrypts data in transit between agents. These are complementary, not conflicting. Memory tier stores plaintext locally; NATS transports ciphertext between nodes.

**Wave 4 (A2A):** A2A cross-org communication may need its own encryption layer beyond intra-cluster NATS E2EE. The DIDComm v2 protocol used in T-4.1 is the standard encryption protocol for A2A as well. The SecureNatsProvider can be reused for A2A messaging channels.

**VERDICT: PASS** -- All forward compatibility vectors are clean. No blocking design choices detected.

---

## 4. Scope Creep Check

### Wave 2 Tasks Against Original Phase 4 Scope

ROADMAP.md Phase 4 scope: "Cost router, agent IAM, Ray executor, NATS messaging, dynamic subgraphs, TypeScript SDK, and Kubernetes deployment."

| Wave 2 Task | In Original Scope? |
|-------------|-------------------|
| T-4.4 Cost-Aware Router | YES ("Cost router") |
| T-4.5 Persistent Budget | YES (implied by "Cost router" -- budget is enforcement) |
| T-4.6 Agent Identity | YES ("agent IAM") |
| T-4.7 UCAN + TTLs | YES (implied by "agent IAM" -- authorization is part of IAM) |

### Design Decisions Scope Check

| DD | Within Phase 4 Scope? | Assessment |
|----|----------------------|------------|
| DD-1 (SelectionFallback) | YES | Core router behavior |
| DD-2 (Budget locking) | YES | Core budget behavior |
| DD-3 (Ed25519 signing) | YES | Core IAM algorithm |
| DD-4 (UCAN attenuation) | YES | Core authorization behavior |
| DD-5 (Delegation chain) | YES | Core IAM propagation |
| DD-6 (Existing breaker) | YES | Reduces scope (reuses existing code) |
| DD-7 (DID key rotation) | YES | Core IAM lifecycle |
| DD-8 (Custom peer_did) | YES | Reduces scope (no external lib) |
| DD-9 (Drop py-ucan) | YES | Reduces scope (no broken lib) |
| DD-10 (Dep validation) | YES | Dependency hygiene |
| DD-11 (Microdollars) | YES | Ledger correctness |
| DD-12 (Idempotency key) | YES | Ledger correctness under NATS retry |
| DD-13 (Router escalation) | YES | Router intelligence |
| DD-14 (TTFT breaker) | YES | Provider health monitoring |
| DD-15 (Load shedding) | BORDERLINE | Defines enum only; middleware deferred |
| DD-16 (Budget + failover) | YES | Cross-cutting integration |
| DD-17 (did:web DNS) | YES | Security constraint |
| DD-18 (Baggage vs UCAN) | YES | Security validation |
| DD-19 (Card hash) | YES | Integrity check |

**DD-15 (Load Shedding)** is borderline scope creep. Load shedding is a server concern, not directly a cost routing or IAM concern. However, the document explicitly notes "For Wave 2, define the enum and the ExecutionContext field. The server middleware integration is deferred." This is acceptable as a lightweight definition with no implementation cost.

**Items correctly excluded from Wave 2:**
- Ray executor (cut by ToT analysis, NATS replaces it)
- OIDC Bridge (deferred to Phase 5 per ToT)
- PromptShield (Wave 3, not Wave 2)
- VDB Sharding (deferred to Phase 5 per ToT)
- SPRT/Fingerprinting/Mutation (cut by ToT)
- Marketplace/Certification (cut by ToT)

**VERDICT: PASS** -- Wave 2 stays within scope. No Phase 5 leakage detected. DD-15 is the only borderline item but is limited to an enum definition.

---

## 5. Design Decision Consistency

### Internal Consistency Check (DD-1 through DD-19)

| Pair | Potential Conflict | Assessment |
|------|-------------------|------------|
| DD-1 vs DD-16 | Failover mode interacts with budget check | CONSISTENT -- DD-16 adds a budget gate before DD-1 fallback triggers |
| DD-2 vs DD-12 | Two different concurrency controls | CONSISTENT -- DD-2 handles race conditions, DD-12 handles NATS retry dedup; complementary |
| DD-6 vs DD-14 | Two breaker mechanisms | CONSISTENT -- DD-14 wraps existing breaker, does not replace it |
| DD-3 vs DD-8 | Signing vs DID module | CONSISTENT -- Ed25519 keys go into peer_did module; same key type |
| DD-7 vs DD-17 | Recommends did:web then warns about DNS | CONSISTENT -- DD-17 constrains DD-7 (registration-time only, cached key) |
| DD-9 vs DD-4 | Library removed but semantics defined | CONSISTENT -- DD-9 provides joserfc implementation; DD-4 defines semantics |
| DD-11 vs existing code | Existing code uses floats | INCONSISTENT -- existing code must be rewritten. Not a DD conflict; it is a code-DD gap. |

### PLAN.md vs Design Decisions

| PLAN.md Statement | DD Alignment |
|-------------------|-------------|
| T-4.4: "aiobreaker>=1.2" | DD-6 says DROP aiobreaker, use existing -- **PLAN.md is stale** |
| T-4.6: "peerdid>=0.5.2" | DD-8/DD-10 say use custom module, drop peerdid -- **PLAN.md is stale** |
| T-4.6: "pynacl>=1.5" | DD-10 says PyNaCl not needed -- **PLAN.md is stale** |
| T-4.7: "joserfc>=1.0" | DD-9 says joserfc directly for UCAN -- CONSISTENT |

**ISSUE: PLAN.md lists 3 libraries that the Design Decisions explicitly rejected.** This is not a blocker for execution (DDs supersede PLAN.md per the addendum header), but creates confusion if someone reads only PLAN.md.

### Contradiction Between Two Circuit Breakers

`providers/failover.py` defines its own `AsyncCircuitBreaker` (lines 28-89) with a different API than `security/circuit_breaker.py` (185 lines). DD-6 explicitly decides to use the security/ version. The providers/ version must be removed during Wave 2 implementation.

**VERDICT: PASS with ADVISORIES** -- No design decision contradicts another. Three PLAN.md library references are stale (superseded by DDs). One code duplication must be resolved.

---

## 6. Gap Analysis

### What Waves 3-4 Need That Waves 1-2 Must Provide

| Wave 3-4 Requirement | Wave 1-2 Provider | Gap? |
|-----------------------|-------------------|------|
| T-4.8 Redis L2 needs cache protocol | `src/orchestra/cache/backends.py` CacheBackend protocol exists | NO GAP |
| T-4.8 Promote/Demote needs MemoryManager | `src/orchestra/memory/manager.py` MemoryManager protocol exists | NO GAP |
| T-4.9 HSM 3-tier needs signing key | T-4.6 AgentIdentity provides Ed25519 keys | NO GAP |
| T-4.9 pgvector needs connection pooling | Phase 3 PostgresEventStore uses asyncpg | NO GAP |
| T-4.10 PromptShield needs tool ACLs | Phase 2 `security/acl.py` ToolACL exists | NO GAP |
| T-4.10 Capability Attenuation needs UCAN | T-4.7 UCAN implementation | NO GAP |
| T-4.11 A2A needs Agent Cards | T-4.6 AgentCard + SignedDiscoveryProvider | NO GAP |
| T-4.11 A2A needs DID resolution | T-4.6 + custom peer_did module | NO GAP |
| T-4.11 ZKP needs signing keys | T-4.6 Ed25519 key infrastructure | NO GAP |
| T-4.12 Dynamic Subgraphs needs graph engine | Phase 1 `core/graph.py` + `core/compiled.py` | NO GAP |
| T-4.13 TypeScript SDK needs OpenAPI spec | Phase 3 FastAPI server generates OpenAPI | NO GAP |

### Identified Gaps

**GAP-1: `src/orchestra/identity/discovery.py` not yet created**

PLAN.md T-4.6 lists `discovery.py` as SignedDiscoveryProvider. The file does not exist yet. This is correctly scheduled as part of T-4.6 (Wave 2), so it is a planned deliverable, not a gap. However, the existing `agent_identity.py` has inline `verify()` on AgentCard but no registry/discovery service that ingests cards from external sources. This must be built in Wave 2.

**GAP-2: `src/orchestra/security/secrets.py` not yet created**

PLAN.md T-4.6 lists `secrets.py` as SecretProvider ABC + Vault (hvac). The file does not exist. This is planned for Wave 2 Track B. Not a gap but a dependency that T-4.6 must deliver for long-lived agent key management.

**GAP-3: No ExecutionContext extension plan**

Research topic C1 identifies that ExecutionContext needs new fields: `identity`, `ucan`, `tenant_id`, `delegation_context`. No design decision explicitly addresses HOW these will be added (flat vs sub-context). DD-5 defines DelegationContext as a dataclass but does not specify how it attaches to ExecutionContext.

This is a minor gap -- the implementation will naturally resolve it -- but could cause integration friction if T-4.4 (Track A) and T-4.6 (Track B) both extend ExecutionContext independently and create merge conflicts.

**Recommendation:** Add a brief DD clarifying that all new ExecutionContext fields are `Optional[X] = None` and added in a single coordinated commit, or documented as the first task of each track.

**GAP-4: No explicit numpy dependency declaration**

`src/orchestra/routing/router.py` imports numpy (line 14). The `pyproject.toml` does not list numpy in any optional dependency group. The existing CostAwareRouter code would fail on import if numpy is not installed as a transitive dependency. PLAN.md T-4.4 lists `numpy>=1.26` but it needs to be added to `pyproject.toml` (probably in a new `routing` extras group or in core dependencies).

---

## Summary

### Overall Alignment Score

| Dimension | Status |
|-----------|--------|
| 1. Goal Alignment | PASS |
| 2. Dependency Chain Integrity | PASS (with warnings) |
| 3. Forward Compatibility | PASS |
| 4. Scope Creep | PASS |
| 5. Design Decision Consistency | PASS (with advisories) |
| 6. Gap Analysis | PASS (4 minor gaps) |

### Blockers: None

### Warnings (should fix before Wave 2 execution)

| # | Issue | Severity | Fix |
|---|-------|----------|-----|
| W-1 | `identity/ucan.py` imports broken `py-ucan` | High | Rewrite per DD-9 using joserfc JWT |
| W-2 | `providers/failover.py` duplicates CircuitBreaker | Medium | Refactor per DD-6 to use `security/circuit_breaker.py` |
| W-3 | `persistent_budget.py` uses floats, not microdollars | Medium | Rewrite schema per DD-11 |
| W-4 | `persistent_budget.py` lacks pessimistic locking | Medium | Implement per DD-2 |
| W-5 | `persistent_budget.py` lacks idempotency key | Medium | Add per DD-12 |
| W-6 | PLAN.md lists 3 rejected libraries | Low | Update PLAN.md or add note that DDs supersede |
| W-7 | numpy not in `pyproject.toml` | Low | Add to routing or cost extras |
| W-8 | No explicit ExecutionContext extension plan | Low | Add brief DD or coordinate in implementation |

### Advisories (informational)

| # | Note |
|---|------|
| A-1 | Pre-existing Wave 2 code provides scaffolding but requires substantial revision to match DDs |
| A-2 | The parallel track structure (A: cost, B: identity) is sound and avoids inter-track blocking |
| A-3 | DD-15 (Load Shedding) is the only borderline scope item; limited to enum definition |
| A-4 | The ToT analysis score of 0.88 was well-heeded -- Wave 2 does not exhibit the cut symptoms |
| A-5 | Dockerfile still missing `messaging` extra (from Wave 1 verification); should be fixed |

### Conclusion

Waves 1 and 2 are well-aligned with the Phase 4 "Enterprise & Scale" goal. Wave 1 correctly established the distributed backbone (NATS + K8s + Wasm), and Wave 2 correctly targets cost intelligence and agent identity as the next layer.

The primary risk is that pre-existing code for Wave 2 tasks is stale relative to the design decisions (especially the broken py-ucan import, float-based budget ledger, and duplicate circuit breaker). Wave 2 execution should treat these files as scaffolding to be revised rather than code to be extended.

Forward compatibility is clean: Wave 2 deliverables enable Waves 3-4 without design conflicts. The DID choices, signing infrastructure, UCAN semantics, and router/budget integration patterns all compose correctly with downstream tasks.

No scope creep detected. All Wave 2 tasks trace directly to ROADMAP.md Phase 4 requirements. Items cut by the ToT analysis remain excluded.

---

*Checked: 2026-03-12*
*Checker: Claude Opus 4.6 (gsd-plan-checker)*
