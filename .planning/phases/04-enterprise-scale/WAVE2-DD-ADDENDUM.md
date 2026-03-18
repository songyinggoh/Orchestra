# Wave 2 Design Decisions Addendum (DD-11 through DD-19)

**Status:** New decisions from PDF research synthesis
**Source Documents:**
- "Implementation Report: Production-Grade Agentic System Architecture" (Stripe/Sarcouncil)
- "Implementation Report: The 'Orchestra' Identity & Security Layer" (KERI/NANDA)
**Online Research:** KERI vs did:peer:2 disambiguation, py-ucan 1.0 spec verification
**Created:** 2026-03-13
**Supersedes:** Nothing. Extends WAVE2-DESIGN-DECISIONS.md (DD-1..DD-10).

---

## CRITICAL FACTUAL CORRECTION: PDF 2 Conflates did:peer:2 with KERI

> **This must be read before implementing T-4.6.**

PDF 2 claims `did:peer:2` has "Native support via KEL/KERL with verifiable history" and
supports witnesses/watchers/judges. **This is factually incorrect.** Confirmed by online
research against the DIF Peer DID Spec and did:keri Method spec.

| Feature | did:peer:2 (numalgo 2) | KERI AID (did:keri) |
|---------|------------------------|---------------------|
| Key Event Log (KEL) | ❌ Static DID document | ✅ Append-only KEL |
| Key rotation with history | ❌ New DID per rotation | ✅ Via rotation events |
| Witnesses/Watchers/Judges | ❌ Not part of spec | ✅ KAWA model |
| Ambient Verifiability | ✅ Self-certifying (valid!) | ✅ Self-certifying |
| No external DNS dependency | ✅ Valid advantage | ✅ Same |

**Impact on DD-7:** The decision to use `did:peer:2` for ephemeral agents and `did:web`
for long-lived agents **remains correct**, but the justification from PDF 2's KERI
comparison does not apply. The actual reasons are:
- `did:peer:2` for ephemeral: self-certifying, no DNS dependency, works for single-session agents
- `did:web` for long-lived: supports key rotation by updating `did.json`
- Full KERI AIDs (`did:keri`, keripy library) deferred to Phase 5 — library is Alpha status

**What remains valid from PDF 2:**
- `did:web` DNS vulnerability is real → mitigate per DD-17 (below)
- OTel Baggage + UCAN pairing for semantic manipulation defense (DD-18)
- Vault path mapping for SecretProvider
- Agent Card integrity hashing (DD-19)

---

## DD-11: Integer Storage in the Persistent Budget Ledger (T-4.5)

**Gap (from PDF 1):** Existing `BudgetPolicy` and `CostAggregator` use `float` for
USD values. Floating-point rounding errors are unacceptable in a financial-grade ledger.

**Decision:** The `PersistentBudget` ledger (T-4.5) **MUST store costs as integers**
representing microdollars (1 USD = 1,000,000 µUSD). Floats are acceptable in-memory
for display and soft-limit checks only.

```
Storage unit:  1 µUSD (microdollar) = 0.000001 USD
Max int64:     9,223,372,036,854,775,807 µUSD ≈ $9.2 trillion → sufficient
Conversion:    int(cost_usd * 1_000_000)  for writes
               amount_micro / 1_000_000   for reads/display
```

**Scope:** Applies ONLY to the new `persistent_budget.py` SQLite/Postgres schema.
Existing `BudgetPolicy` (in-memory, per-run) keeps floats — it's not financial-grade.

**Rationale:** Floating-point representation of 0.1 USD stored as float = 0.10000000000000001.
After 10,000 operations, rounding drift can cause material over/under-spend mismatches.

**What we are NOT doing:**
- Not changing `BudgetPolicy` or `CostAggregator` (backwards compat, in-memory only)
- Not using `Decimal` (slower than int, unnecessary for microdollar precision)

---

## DD-12: Idempotency Key in the Budget Ledger (T-4.5)

**Gap (from PDF 1):** NATS JetStream assigns each message a unique `event_id`. If a
consumer crashes after charging the LLM but before ACKing, the message is redelivered.
Without idempotency, the budget is double-charged.

**Decision:** Add an `idempotency_key` column (UNIQUE) to the budget ledger table.
Use the NATS `event_id` (or a deterministic hash of `run_id + agent_id + call_sequence`)
as the key. Implement Check-Then-Act:

```
1. BEGIN IMMEDIATE (SQLite) / BEGIN (Postgres)
2. SELECT id, status FROM budget_ledger WHERE idempotency_key = ?
   → If row exists with status='committed': ROLLBACK, return cached result
   → If row exists with status='pending':   ROLLBACK, raise InProgressError (caller waits/polls)
   → If no row: continue
3. INSERT row with status='pending', estimated_cost_micro = estimated
4. COMMIT (locks the key)
5. Execute LLM call
6. UPDATE row: status='committed', actual_cost_micro = actual
7. COMMIT
```

**Why 'pending' state matters:** Prevents thundering herd when two concurrent retries
arrive for the same NATS message — the second caller sees 'pending' and backs off.

**What we are NOT doing:**
- Not using `asyncio.Lock` (not safe across processes/workers)
- Not using Redis for distributed locks (overkill for Phase 4; pessimistic DB lock is sufficient)

---

## DD-13: Router Escalation Triggers (T-4.4)

**Gap (from PDF 1):** Current `ThompsonModelSelector` selects models by cost/performance
profile but has no triggers for proactively escalating to larger models mid-workflow.

**Decision:** Add two escalation signals to `CostAwareRouter.select_model()`:

| Trigger | Condition | Action |
|---------|-----------|--------|
| **Tool-Density** | `len(required_tools) > tool_density_threshold` (default: 4) | Force large model regardless of cost preference |
| **Token-Count** | `estimated_context_tokens > 0.80 × model.context_limit` | Switch to next-tier model with larger context window |

```python
@dataclass
class RoutingHints:
    required_tools: list[str] = field(default_factory=list)
    estimated_input_tokens: int = 0
```

**Rationale:**
- Small models fail silently when given too many tools (hallucinate tool calls, miss
  required arguments). Deterministic threshold prevents these failures.
- Context overflow causes truncation that silently corrupts agent reasoning.
  Proactive switching before overflow is more reliable than error handling after.

**Default thresholds (configurable via `ExecutionContext.config`):**
```
tool_density_threshold: 4    # >4 concurrent tools → large model
context_fill_ratio:     0.80 # >80% of context window → escalate
```

**What we are NOT doing:**
- Not using these as hard rules — they inform the Thompson sampler as a prior bias,
  they don't override the FAIL_FAST/FAVOR_COST/FAVOR_LATENCY SelectionFallback

---

## DD-14: TTFT-Based Circuit Breaker Triggering (T-4.4)

**Gap (from PDF 1):** Existing `AsyncCircuitBreaker` counts binary success/failure.
PDF 1 specifies that circuit breakers should monitor **Time to First Token (TTFT)** —
a degraded provider that is slow but not erroring is also a failure mode.

**Decision:** Wrap each provider in `ProviderFailover` with both:
1. The existing `AsyncCircuitBreaker` (for error-rate-based trips)
2. A `ttft_threshold_seconds` parameter (default: 30s)

When `ProviderFailover` measures TTFT > threshold, call `breaker.record_failure()` even
if the provider eventually succeeded. This degrades its Thompson α/β score and may trip
the circuit breaker.

```python
class ProviderFailover:
    def __init__(
        self,
        providers: list[tuple[Provider, AsyncCircuitBreaker]],
        ttft_threshold_seconds: float = 30.0,
    ): ...
```

**What we are NOT doing:**
- Not modifying `AsyncCircuitBreaker` itself (it has a single responsibility)
- Not streaming TTFT in Phase 4 (providers return full responses; TTFT = time to first
  token of response, measurable as total latency for non-streaming calls)

---

## DD-15: Load Shedding Policy (T-4.4 Server Integration)

**Gap (from PDF 1):** No mechanism to disable non-critical background tasks during
high-traffic periods to preserve API capacity.

**Decision:** Define a `LoadSheddingPolicy` enum with two tiers:

```python
class LoadSheddingLevel(str, Enum):
    NORMAL     = "normal"      # All tasks run
    DEGRADED   = "degraded"    # Shed: memory summarization, non-urgent projections
    CRITICAL   = "critical"    # Shed: all non-user-facing background tasks
```

**Background tasks subject to shedding (DEGRADED+):**
- Long-term memory summarization (MemoryManager.summarize())
- Analytical cost projections / trend reports
- Agent Card refresh/rebroadcast (can be delayed)

**Trigger:** Server middleware (existing `src/orchestra/server/middleware.py`) checks
concurrent active requests. If > `DEGRADED_THRESHOLD` (default: 80% of worker capacity),
set `LoadSheddingLevel.DEGRADED` on `ExecutionContext`.

**Scope:** This is primarily a Phase 3 server concern. For Wave 2, define the enum and
the `ExecutionContext.load_shedding_level` field. The server middleware integration
is deferred to a server-layer patch after Wave 2.

---

## DD-16: Proactive Budget Lock During Provider Failover (T-4.4 × T-4.5)

**Gap (from PDF 1):** Cross-cutting risk — when ProviderFailover escalates to an
expensive model, the original budget estimate (for the cheap model) may be insufficient.
Budget check passes for cheap model, failover happens, expensive model overruns budget.

**Decision:** `ProviderFailover` MUST perform a budget pre-check before executing on
a more expensive fallback model:

```
1. Primary provider fails → identify next provider in failover chain
2. Estimate cost for expensive model (tokens × expensive_model_rate)
3. Call PersistentBudget.can_afford(tenant_id, estimated_cost_micro)
   → If False: raise BudgetCeilingViolationOnFailover (do NOT silently failover)
   → If True: place a temporary budget hold (idempotency_key = f"{run_id}:failover:{attempt}")
4. Execute on expensive model
5. Reconcile actual cost (may be less than estimated)
```

**Parent Org as absolute constraint:** During the pre-check, the budget check MUST
traverse the full Org > Team > User hierarchy. A child team showing availability
but the parent Org at $0 must halt execution (override any local cache).

**What we are NOT doing:**
- Not silently absorbing the cost difference (financial integrity > task completion)
- Not implementing this as a configurable opt-out (it is mandatory)

---

## DD-17: did:web DNS Risk Mitigation (T-4.6)

**Gap (from PDF 2, valid concern):** `did:web` relies on DNS + Certificate Authorities.
DNS hijacking can force acceptance of malicious DID Documents. This is a real attack vector.

**Decision:** Constrain `did:web` usage to **registration-time only**:
- `did:web` is written to the agent registry ONCE at agent startup/registration
- All subsequent A2A messages use `did:peer:2` (no DNS resolution at runtime)
- The SignedDiscoveryProvider resolves `did:web` once and caches the Ed25519 key locally
- Cache TTL = `min(key_overlap_window, 24h)` — refreshed on explicit rotation event only

**In practice:** An adversary who hijacks DNS after the key is cached gains nothing.
The attack window is only during the initial registration lookup.

**What we are NOT doing:**
- Not switching long-lived agents from `did:web` to `did:peer:2` (key rotation still needed)
- Not implementing DNSSEC verification (out of scope for Phase 4)
- Not adopting full KERI (`did:keri` / keripy Alpha library) for Phase 4

---

## DD-18: OTel Baggage + UCAN Semantic Manipulation Defense (T-4.7)

**Gap (from PDF 2):** OTel Baggage headers are unsigned. A compromised intermediate
agent can modify Baggage to claim permissions it doesn't have, manipulating downstream
agents' behavior even if the UCAN is valid.

**Decision:** Add a Baggage Intent vs UCAN Permission check to `DelegationContext`:

```python
def validate_baggage_against_ucan(
    baggage: dict[str, str],
    ucan: UCANToken,
) -> None:
    """Raise SemanticManipulationError if baggage intent exceeds UCAN abilities."""
    claimed_tools = baggage.get("orchestra.requested_tools", "").split(",")
    for tool in claimed_tools:
        if tool and not ucan.can("tool/invoke", f"orchestra:tools/{tool}"):
            raise SemanticManipulationError(
                f"Baggage claims tool '{tool}' not granted in UCAN"
            )
```

**Rule:** UCAN = Permission (authoritative, signed). Baggage = Intent (unsigned, informational).
If intent exceeds permission → drop the request. Log as a security event.

**Integration point:** Called in `DelegationContext` constructor when both `ucan` and
`baggage` are present on `ExecutionContext`.

**What we are NOT doing:**
- Not signing Baggage (OTel spec explicitly leaves Baggage unsigned; UCAN is the signature)
- Not blocking requests with missing Baggage (absent Baggage → treat as empty intent → no violation)

---

## DD-19: SAID-Like Integrity Hash for Agent Cards (T-4.6)

**Gap (from PDF 2, adapted):** Agent Cards can be tampered with in the registry between
write and read. PDF 2 recommends Self-Addressing Identifiers (SAIDs) from KERI/ACDC.
Full KERI SAIDs require keripy (Alpha). We need the property, not the library.

**Decision:** Implement a lightweight content-integrity hash on AgentCard:

```python
import hashlib, json

def compute_card_hash(card_dict: dict) -> str:
    """SHA-256 of canonical JSON (sorted keys, deterministic).
    Replaces the 'card_hash' field with a placeholder before hashing
    (same principle as SAID — the hash is bound to the content excluding itself).
    """
    d = {k: v for k, v in card_dict.items() if k != "card_hash"}
    canonical = json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
```

**Storage:** `AgentCard.card_hash` field set at creation, verified at ingestion.

**SignedDiscoveryProvider** rejects cards where `compute_card_hash(card) != card.card_hash`.
This catches in-transit tampering and registry corruption.

**What this is NOT:**
- Not a KERI SAID (no CESR encoding, no Blake3-256, no recursive self-inclusion)
- Not a signature (a hash proves integrity but not origin — origin is proven by the JWS envelope)
- Full KERI SAIDs with keripy deferred to Phase 5

---

## Summary Table: New Decisions

| ID | Task | Gap | Decision | Impact |
|----|------|-----|----------|--------|
| DD-11 | T-4.5 | Float rounding in ledger | Integer storage (microdollars) | Schema change |
| DD-12 | T-4.5 | Double-billing on NATS retry | Idempotency key + Pending state | New column |
| DD-13 | T-4.4 | No proactive model escalation | Tool-density + token-count triggers | New RoutingHints |
| DD-14 | T-4.4 | Circuit breaker ignores latency | TTFT threshold in ProviderFailover | Thin wrapper |
| DD-15 | T-4.4+ | No load shedding | LoadSheddingLevel enum + middleware hook | New enum |
| DD-16 | T-4.4×T-4.5 | Failover overruns budget | Proactive budget lock before failover | Cross-module |
| DD-17 | T-4.6 | did:web DNS hijack risk | Registration-time only; cache Ed25519 key | Constraint |
| DD-18 | T-4.7 | Unsigned Baggage can lie | Baggage intent vs UCAN permission check | New validator |
| DD-19 | T-4.6 | Agent Card tampering | SHA-256 content integrity hash | New field |

## Factual Corrections to Prior Research

| Claim in PDF 2 | Reality | Source |
|----------------|---------|--------|
| `did:peer:2` has KEL/KERL | FALSE — KEL/KERL are KERI-only features | DIF Peer DID Spec |
| `did:peer:2` supports witnesses/watchers | FALSE — KAWA/witnesses are KERI AID features | did:keri Method Spec |
| Key rotation via `did:peer:2` KERL | FALSE — `did:peer:2` is static | Peer DID Spec |
| DD-7 conclusion (did:web for long-lived) | STILL CORRECT but for different reasons | Online research |

*These corrections do not change any implementation decisions. DD-7 remains valid.*
