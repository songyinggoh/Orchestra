# Wave 2 Design Decisions

**Status:** Pre-implementation decisions for T-4.4 through T-4.7
**Created:** 2026-03-12
**Purpose:** Resolve the 6 critical knowledge gaps identified before coding begins

---

## DD-1: SLA + Budget Conflict Resolution (T-4.4)

**Gap:** When no model satisfies both SLA latency AND budget constraints, the router has no defined behavior.

**Decision:** Implement a `SelectionFallback` enum on `CostAwareRouter` with three modes:

```
FAVOR_COST    → Relax SLA constraint, pick cheapest model that fits budget
FAVOR_LATENCY → Relax budget constraint, pick fastest model within 1.5x budget
FAIL_FAST     → Raise ModelSelectionError immediately (default)
```

**Rationale:**
- `FAIL_FAST` as default prevents silent SLA/budget violations — callers must handle the error explicitly
- `FAVOR_COST` / `FAVOR_LATENCY` are opt-in relaxations configured per-workflow, not per-call
- The 1.5x budget multiplier in `FAVOR_LATENCY` prevents unbounded overspend while allowing headroom

**Integration point:** `CostAwareRouter.select_model()` accepts `fallback: SelectionFallback = FAIL_FAST`. The workflow config in `ExecutionContext.config["routing_fallback"]` overrides the default.

**What we are NOT doing:**
- No `DEGRADE_GRACEFULLY` mode (hard to define "graceful" without domain knowledge)
- No automatic retry with relaxed constraints (caller decides)

---

## DD-2: Budget Ledger Consistency Model (T-4.5)

**Gap:** Optimistic caching can allow overspend when concurrent requests read stale balances.

**Decision:** Use **pessimistic per-request locking** with the existing storage layer, not optimistic caching.

```
1. Before LLM call: BEGIN TRANSACTION
2. SELECT balance FROM budget_accounts WHERE tenant_id = ? FOR UPDATE
3. IF balance < estimated_cost → ROLLBACK, raise BudgetExceededError
4. Deduct estimated_cost → UPDATE budget_accounts SET balance = balance - ?
5. COMMIT
6. Execute LLM call
7. After LLM call: adjust ledger entry with actual cost (debit correction row)
```

**Rationale:**
- Orchestra is not a high-frequency trading system — LLM calls take 500ms-30s, so transaction lock contention is negligible
- Eliminates the entire class of cache-vs-DB divergence bugs
- The existing `SQLiteEventStore` uses WAL mode and `PostgresEventStore` has advisory locks — both support this pattern
- "95% hard limit" hack is unnecessary with proper locking

**For SQLite:** Use `BEGIN IMMEDIATE` (WAL mode allows concurrent reads during write lock).
**For PostgreSQL:** Use `SELECT ... FOR UPDATE` (row-level lock, no table lock).

**Budget period rollover:**
- All timestamps are **UTC**. No tenant timezone config (simplicity over flexibility).
- Period boundaries: `YYYY-MM-01 00:00:00 UTC` for monthly. Checked by comparing `created_at` of ledger entries.
- No grace period needed — the pessimistic lock ensures atomicity at boundaries.
- If server is down at rollover, first request after restart triggers lazy rollover (new period row inserted).

**Hierarchy semantics:**
- Child spending **counts toward** parent limit (additive, not independent).
- Parent budget = `allocated_to_self + SUM(allocated_to_children)`.
- A child cannot exceed its own allocation, even if parent has remaining balance. Explicit reallocation required.

---

## DD-3: Signature Algorithm for Agent Cards (T-4.6)

**Gap:** Research mandates "cryptographic signatures" but doesn't specify which algorithm.

**Decision:** **Ed25519** (EdDSA over Curve25519) for all Agent Card signatures.

**Rationale:**
- `did:peer:2` numalgo 2 already embeds Ed25519 verification keys (Wave 1 generates these via `peerdid`)
- Ed25519 has the smallest signatures (64 bytes) and fastest verification (~70k verifications/sec)
- `joserfc` supports EdDSA natively for JWT/JWS — no additional library needed
- No SHA-1 baggage (unlike ECDSA P-256), no RSA key bloat
- Aligns with DIDComm v2 specification's preference for Curve25519

**Key rotation:**
- Agent generates new Ed25519 keypair → publishes new Agent Card with incremented `version` field
- Old cards are valid until their `expires_at` timestamp (overlap window = 1 hour by default)
- `SignedDiscoveryProvider` keeps at most 2 active cards per DID (current + previous)
- No revocation list for Phase 4 — TTL-based expiry is sufficient (revocation lists are Phase 5)

**Signing format:** JWS Compact Serialization (`header.payload.signature`) using `joserfc.jws.serialize_compact()` with `alg: "EdDSA"`.

---

## DD-4: UCAN Capability Attenuation Semantics (T-4.7)

**Gap:** When ACL and UCAN both specify limits, the intersection rule is undefined.

**Decision:** **Strict intersection** — the effective capability is `min(ACL, UCAN)` on every dimension.

```
Example:
  ACL grants:  tool:web_search (unlimited), tool:file_read (unlimited)
  UCAN grants: tool:web_search (max_calls=10)

  Effective: tool:web_search (max_calls=10), tool:file_read (DENIED — not in UCAN)
```

**Rules:**
1. A UCAN **cannot grant** a capability not present in the issuer's own ACL (or issuer's UCAN)
2. A UCAN **can only narrow** — lower `max_calls`, shorter `ttl_seconds`, fewer tools
3. If no UCAN is present on `ExecutionContext`, fall back to ACL-only (backward compatible)
4. If UCAN is present but expired, **deny all** — do not fall back to ACL

**ResourcePointer format for Orchestra tools:**
```
orchestra:tools/{tool_name}         → e.g., orchestra:tools/web_search
orchestra:agents/{agent_id}         → e.g., orchestra:agents/summarizer
orchestra:workflows/{workflow_id}   → e.g., orchestra:workflows/research-pipeline
```

**Ability verbs:**
```
tool/invoke    → execute a tool
agent/delegate → delegate to a sub-agent
workflow/run   → start a workflow
```

**Integration with ToolACL:**
- `ToolACL.is_authorized(tool_name, ucan=None)` gains an optional `ucan` parameter
- When `ucan` is provided: check ACL first (deny-list takes precedence), then verify UCAN grants `tool/invoke` for `orchestra:tools/{tool_name}`
- UCAN `max_calls` tracked via a counter dict on `ExecutionContext` (not persisted — scoped to single run)

---

## DD-5: Agent Identity Propagation in Nested Calls (T-4.6 + T-4.7)

**Gap:** When A delegates to B delegates to C, it's undefined whether C sees only B or the full chain.

**Decision:** Propagate a **delegation chain** as a list, not just the current identity.

**Model:**
```python
@dataclass(frozen=True)
class DelegationContext:
    chain: tuple[str, ...]     # DIDs from root to current: ("did:A", "did:B", "did:C")
    issuer_did: str            # Who started the chain (chain[0])
    current_did: str           # Current agent (chain[-1])
    depth: int                 # len(chain) - 1
    max_depth: int             # From root's AgentIdentity.max_delegation_depth (default=3)
```

**Rules:**
1. Each agent appends its own DID to the chain before delegating
2. If `depth >= max_depth`, delegation is **rejected** (raise `DelegationDepthExceededError`)
3. Default `max_depth = 3` (root + 3 levels of delegation)
4. The chain is serialized into OTel Baggage as `orchestra.delegation_chain=did:A,did:B,did:C`
5. If Baggage is missing or malformed, treat as **anonymous** — apply the most restrictive ACL (deny-all unless `allow_all=True`)

**Why chain, not just current:**
- Audit trail: logs show the full delegation path for debugging
- Capability attenuation: each hop can narrow permissions (UCAN chain)
- Trust decisions: an agent can inspect who originated the request

**What we are NOT doing:**
- No bidirectional chain (only forward delegation, no "who delegated to me" callbacks)
- No chain persistence (ephemeral, lives in OTel Baggage and `ExecutionContext` only)
- No chain signing (each UCAN in the delegation is already individually signed)

---

## DD-6: Use Existing AsyncCircuitBreaker vs. aiobreaker (T-4.4)

**Gap:** PLAN.md lists `aiobreaker>=1.2` but Phase 3 already built `AsyncCircuitBreaker`.

**Decision:** **Keep the existing `AsyncCircuitBreaker`**. Do not add `aiobreaker`.

**Rationale:**
- The existing implementation at `src/orchestra/security/circuit_breaker.py` is 185 lines, fully async, well-tested, and already integrated
- It supports injectable timestamps (`now` parameter) for deterministic testing
- Adding `aiobreaker` would create two circuit breaker implementations with no benefit
- The existing one has the exact API needed: `allow_request()`, `record_success()`, `record_failure()`, async context manager

**For ProviderFailover:** Wrap each provider with its own `AsyncCircuitBreaker` instance:
```python
class ProviderFailover:
    def __init__(self, providers: list[tuple[Provider, AsyncCircuitBreaker]]):
        self._chain = providers  # ordered by preference

    async def execute(self, messages, model) -> LLMResponse:
        for provider, breaker in self._chain:
            if breaker.allow_request():
                try:
                    result = await provider.complete(messages, model=model)
                    breaker.record_success()
                    return result
                except Exception:
                    breaker.record_failure()
        raise AllProvidersUnavailableError(...)
```

---

---

## DD-7: Key Rotation Strategy for Agent DIDs (T-4.6)

**Open Question:** For long-lived agent identities needing periodic key rotation: (a) accept DID churn, (b) use `did:web`, (c) wait for numalgo 1.

**Decision:** **Option (b) — `did:web` for agents needing rotation, `did:peer:2` for ephemeral/session agents.**

- Orchestrator agents and named service agents (long-lived) → `did:web:orchestra.example.com:agents:{name}`
  - Key rotation: update `did.json` on the web server; old DID remains valid
- Sub-agents and ephemeral task agents → `did:peer:2` (fresh DID per session, no rotation needed)
- DID churn (option a) is rejected: breaks trust chains and requires counterparty re-registration
- Numalgo 1 (option c) is not production-ready; no Python library support

**What we are NOT doing:** No microledger rotation in Phase 4.

---

## DD-8: DID peer Implementation — Custom Module (T-4.6)

**Open Question (original):** `peerdid` (SICPA-DLab) vs `did-peer-2` (DIF — newer, simpler).

**REVISED Decision (2026-03-13): Use Orchestra's built-in `src/orchestra/messaging/peer_did.py`. No external DID library needed.**

**Discovered:** `secure_provider.py` was already updated in a previous session to use a custom `orchestra.messaging.peer_did` module instead of the `peerdid` library. This module:
- `create_peer_did_numalgo_2(encryption_keys: list[bytes], signing_keys: list[bytes], service: dict)` — takes raw bytes directly
- `resolve_peer_did(did: str) -> dict` — returns a plain dict (not a pydantic model), camelCase fields
- Already strips multicodec prefix internally — no prefix stripping needed in callers
- Zero external dependencies beyond `base58` (already in messaging extras)
- Tests pass: 7/7 in `tests/unit/test_e2e_encryption.py`

**Why NOT peerdid library:**
- `peerdid 0.5.2` depends on `pydid~=0.3.5` which breaks on Python 3.13 + Pydantic v2 (`__modify_schema__` removed)
- No code imports `peerdid` anywhere in src/ or tests/
- Custom module is simpler, faster (no pydantic overhead), and fully tested

**For T-4.6:** Extend `orchestra.messaging.peer_did` if needed (e.g., `did:web` support). Do NOT add `peerdid` dependency.

**`pyproject.toml` messaging extras:** Removed `peerdid>=0.5.2` (was dead weight). Current: `nats-py`, `joserfc`, `base58`, `cryptography`.

---

## DD-9: py-ucan Broken — Implement UCAN via joserfc JWT (T-4.7)

**Open Question (original):** `py-ucan 1.0.0` implements 0.9.x format. Small maintainer surface. Proof CID resolution undocumented.

**REVISED Decision (2026-03-13): Drop `py-ucan` entirely. Implement UCAN via `joserfc` JWT directly.**

**Evidence from live spike:**
- `ucan.encode()` — does NOT exist (`AttributeError: module 'ucan' has no attribute 'encode'`)
- `ucan.build()` — exists but is a coroutine; returns a `Ucan` object
- `str(Ucan)` — returns Python repr, NOT a JWT string
- `sign_with_keypair()` — returns a 5-part string (not the 3-part `header.payload.signature` JWT)
- No working JWT serialization path found anywhere in the library
- Internal `ucv` version is `0.8.1` (not `1.0.x` as PyPI advertises)
- `poetry` is a **runtime dependency** (packaging bug — pulls 2MB of dev tooling)
- `cryptography>=43,<44` conflicts with project's `cryptography>=42.0`

**Implementation:** UCAN 0.8.1 JWT constructed directly using joserfc:

```python
import secrets, time
from joserfc import jwt
from joserfc.jwk import OKPKey

payload = {
    "ucv": "0.8.1",
    "iss": issuer_did,          # did:peer:2... or did:web:...
    "aud": audience_did,
    "nbf": int(time.time()),
    "exp": int(time.time()) + ttl_seconds,
    "att": [{"with": resource_uri, "can": ability}],
    "prf": [],                  # inline token strings for delegation chains
    "nnc": secrets.token_hex(8),
}
header = {"alg": "EdDSA", "typ": "JWT", "ucv": "0.8.1"}
token: str = jwt.encode(header, payload, signing_key)  # OKPKey(crv="Ed25519")
```

Verification uses `jwt.decode(token, verification_key, algorithms=["EdDSA"])` — same joserfc already used in Wave 1.

**The `UCANService` wrapper (DD-9 original intent) is still correct** — hide the joserfc JWT details behind `UCANService.issue()`, `UCANService.verify()`, `UCANService.delegate()`.

**What we are NOT doing:**
- No `py-ucan` anywhere in the codebase
- No UCAN 1.0 spec (`sub`/`cmd`/`pol`) — wait for a maintained Python library
- No CID-based proof resolution — pass inline JWT strings in `prf` array

---

## DD-10: New Dependencies Confirmed (T-4.6)

**Open Question:** Does peerdid dual-key (Ed25519 + X25519) work? Is `base58` needed? Is `PyNaCl` needed?

**Decisions (confirmed by live execution spike, 2026-03-13):**

| Question | Answer |
|----------|--------|
| peerdid embeds both Ed25519 + X25519 in numalgo 2? | **YES** — confirmed by byte-level round-trip. `verificationMethod[0]` = X25519; `[1]` = Ed25519 |
| `base58` needed? | **YES** — required for key extraction (multibase `z`-prefix decoding). Already in pyproject.toml messaging extras |
| `PyNaCl` needed? | **NO** — not needed for T-4.6 key extraction. Direct `cryptography` primitives sufficient for Ed25519+X25519 keygen |
| `pydid>=0.5.0` needed? | **YES (NEW)** — peerdid 0.5.2's bundled `pydid~=0.3.5` breaks on Python 3.13 + Pydantic v2 |

**Dependencies in `pyproject.toml` messaging extras (current + required):**
```
nats-py>=2.14       # already there
joserfc>=1.6        # already there
peerdid>=0.5.2      # already there
base58>=2.1         # already there
cryptography>=42.0  # already there
pydid>=0.5.0        # ADD THIS — overrides peerdid's bundled pydid~=0.3.5
```

**Remove from pyproject.toml security extras:** `pynacl>=1.5` — not needed for Wave 2 (was speculative). Keep only if needed by other consumers.

---

## DD-11: orchestra.messaging.peer_did API (T-4.6 Implementation Guide)

**Purpose:** Document the custom DID module API for T-4.6 implementers.

**Import path:**
```python
from orchestra.messaging.peer_did import create_peer_did_numalgo_2, resolve_peer_did
```

**Key creation API (takes raw bytes, not library wrapper objects):**
```python
did = create_peer_did_numalgo_2(
    encryption_keys=[x_pub_raw],    # list[bytes] — raw 32-byte X25519 keys
    signing_keys=[ed_pub_raw],      # list[bytes] — raw 32-byte Ed25519 keys
    service={"type": "DIDCommMessaging", "serviceEndpoint": "nats://..."},
)
```

**Resolution result:** `resolve_peer_did(did) -> dict` returns a plain dict:
```python
{
    "@context": "https://www.w3.org/ns/did/v1",
    "id": "did:peer:2...",
    "verificationMethod": [
        {"id": "...#key-1", "type": "X25519KeyAgreementKey2020", "controller": "...",
         "publicKeyMultibase": "z<base58>"},   # raw 32-byte key (prefix already stripped)
        {"id": "...#key-2", "type": "Ed25519VerificationKey2020", "controller": "...",
         "publicKeyMultibase": "z<base58>"},   # raw 32-byte key (prefix already stripped)
    ],
    "keyAgreement": ["...#key-1"],
    "service": [...],
}
```

**Key extraction:** multicodec prefix is already stripped by `resolve_peer_did()`. No need to strip 2 bytes.
```python
raw = base58.b58decode(vm["publicKeyMultibase"][1:])  # strip 'z', get raw 32-byte key
# len(raw) == 32 always (no conditional strip needed)
```

**`secure_provider.py` status:** Already uses this module correctly (no bugs). 7/7 tests pass.

---

## Summary Table

| ID | Gap | Decision | Complexity |
|----|-----|----------|------------|
| DD-1 | SLA+Budget conflict | `FAIL_FAST` default, opt-in `FAVOR_COST`/`FAVOR_LATENCY` | Low |
| DD-2 | Budget race condition | Pessimistic locking, UTC periods, additive hierarchy | Medium |
| DD-3 | Signature algorithm | Ed25519 (EdDSA), JWS Compact, 1h key rotation overlap | Low |
| DD-4 | UCAN attenuation | Strict intersection, deny-all on expired UCAN | Medium |
| DD-5 | Identity propagation | Delegation chain tuple, max_depth=3, OTel Baggage | Medium |
| DD-6 | Circuit breaker lib | Keep existing `AsyncCircuitBreaker`, drop `aiobreaker` | None |
| DD-7 | DID key rotation | `did:web` for long-lived agents, `did:peer:2` for ephemeral | Low |
| DD-8 | DID library | Use custom `orchestra.messaging.peer_did`; no external DID lib | None |
| DD-9 | py-ucan broken | **Drop py-ucan**; implement UCAN 0.8.1 via joserfc JWT directly | Low |
| DD-10 | peerdid dual-key + deps | Custom module confirmed; removed `peerdid` from pyproject.toml | None |
| DD-11 | peer_did API | Custom module API documented; `secure_provider.py` already correct | None |
