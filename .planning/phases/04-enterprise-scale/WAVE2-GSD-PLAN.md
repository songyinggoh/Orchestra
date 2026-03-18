# Phase 4 Wave 2: Intelligence & Identity — Executable GSD Plan

**Phase:** 04-enterprise-scale (Wave 2)
**Status:** Ready for Execution
**Depends On:** Wave 1 COMPLETE (T-4.1, T-4.2, T-4.3 verified)
**Tasks:** 4 tasks across 2 parallel tracks, 8 plans
**Locked Decisions:** DD-1 through DD-11 (see WAVE2-DESIGN-DECISIONS.md)
**Estimated Duration:** 2-3 Claude sessions (Tracks A and B run in parallel)

---

## Architecture Overview

```
Track A (Cost Intelligence)          Track B (Identity & Authorization)
================================     =====================================
Plan A1: Router contracts + types    Plan B1: Identity contracts + types
        |                                    |
Plan A2: CostAwareRouter rewrite     Plan B2: AgentIdentity + SignedDiscovery
        |                                    |
Plan A3: ProviderFailover rewrite    Plan B3: UCAN via joserfc
        |                                    |
Plan A4: PersistentBudget ledger     Plan B4: UCAN-ACL integration + wiring
        |                                    |
        +------------ SYNC -----------------+
        |                                    |
Plan C1: ExecutionContext extensions + integration test
```

---

## Locked Decisions Reference

These are NON-NEGOTIABLE. Every implementer must follow them exactly.

| ID | Decision | Applies To |
|----|----------|------------|
| DD-1 | `FAIL_FAST` default for SLA+Budget conflicts (SelectionFallback enum) | Plan A2 |
| DD-2 | Pessimistic locking for budget ledger (BEGIN IMMEDIATE / FOR UPDATE) | Plan A4 |
| DD-3 | Ed25519 for Agent Card signatures (JWS Compact, EdDSA) | Plan B2 |
| DD-4 | Strict ACL intersection with UCAN (min on every dimension) | Plan B4 |
| DD-5 | Delegation chain in OTel Baggage (`orchestra.delegation_chain`) | Plan B2, B3 |
| DD-6 | Reuse existing `AsyncCircuitBreaker` from `security/circuit_breaker.py` | Plan A3 |
| DD-7 | `did:web` for long-lived, `did:peer:2` for ephemeral agents | Plan B2 |
| DD-8 | Use custom `orchestra.messaging.peer_did` module (no external peerdid) | Plan B2 |
| DD-9 | UCAN via `joserfc` JWT directly (py-ucan dropped entirely) | Plan B3 |
| DD-10 | No PyNaCl; `cryptography` + `base58` sufficient | Plan B2 |
| DD-11 | `peer_did` API as documented (takes raw bytes, returns plain dict) | Plan B2 |

---

## Critical Implementation Notes (added 2026-03-13)

**joserfc EdDSA deprecation (RFC 9864):** As of joserfc 1.6.3, EdDSA is deprecated. All
`jwt.encode()`, `jwt.decode()`, `jws.serialize_compact()`, and `jws.deserialize_compact()`
calls MUST include `algorithms=["EdDSA"]` or they will raise `UnsupportedAlgorithmError`.
A `SecurityWarning` is emitted but can be suppressed with `warnings.filterwarnings`.

**UCAN `ucv` claim location:** The `ucv` field belongs in the JWT **payload**, NOT the header.
joserfc rejects non-standard header claims with `UnsupportedHeaderError`.

**Inventory staleness (corrected below):** Several files were partially or fully implemented
during Wave 1 scaffolding. The inventory table below reflects the ACTUAL current state as of
2026-03-13, not the pre-Wave-1 state originally documented. Plans should diff against existing
code before rewriting.

---

## Existing Codebase Inventory

Files that ALREADY EXIST and will be REWRITTEN or EXTENDED:

| File | Current State | Wave 2 Action |
|------|--------------|---------------|
| `src/orchestra/routing/router.py` | CostAwareRouter + ThompsonModelSelector (basic, no SLA/budget constraints) | EXTEND: add SelectionFallback, SLA constraints, budget-awareness |
| `src/orchestra/providers/failover.py` | Already imports `AsyncCircuitBreaker` from `security.circuit_breaker` (DD-6 done). Has `ProviderFailover` with `allow_request()`/`record_success()`/`record_failure()` pattern and basic `_is_retryable()` string matching. No error classification enum, no TTFT tracking, no budget pre-check (DD-16). | EXTEND: add error classification enum, TTFT-based circuit breaking (DD-14), budget pre-check on failover (DD-16) |
| `src/orchestra/cost/persistent_budget.py` | Already async (aiosqlite), WAL mode, `BEGIN IMMEDIATE` pessimistic locking (DD-2), microdollar integers (DD-11), idempotency keys with pending/committed states (DD-12), parent hierarchy traversal in `can_afford()`. Has `PersistentBudgetStore` + `TenantBudgetManager`. | EXTEND: add double-entry ledger reconciliation, budget hold/release for failover (DD-16), period reset improvements |
| `src/orchestra/cost/tenant.py` | BudgetConfig, BudgetState, BudgetStatus, Tenant (basic dataclasses) | EXTEND: add hierarchy semantics, parent/child budget delegation |
| `src/orchestra/identity/agent_identity.py` | AgentIdentity + AgentCard + Ed25519Signer (basic). Uses raw `cryptography` Ed25519 signing (not joserfc JWS). `to_json()` excludes `signature` field. No `card_hash`, `version`, `expires_at`, `max_delegation_depth`. No `did:web` support. | EXTEND: add did:web support, version/expires_at/card_hash on AgentCard (DD-19), JWS Compact signing via joserfc (DD-3, requires `algorithms=['EdDSA']`), SignedDiscoveryProvider |
| `src/orchestra/identity/ucan.py` | Already rewritten to `UCANService` using joserfc JWT (DD-9 done). Has `issue()`, `delegate()`, `verify()`, `OrchestraCapability`. Error types: `UCANExpiredError`, `UCANAudienceMismatchError`, `UCANCapabilityError`. `ucv` correctly in payload. `verify()` already passes `algorithms=['EdDSA']`; `issue()` now also passes it. | EXTEND: add capability attenuation validation in `delegate()` (DD-4), delegation chain depth enforcement |
| `src/orchestra/security/acl.py` | ToolACL with pattern-based allow/deny lists. `is_authorized(tool_name: str)` takes one param only. No UCAN integration. | EXTEND: add optional `ucan` parameter per DD-4 |
| `src/orchestra/core/errors.py` | Standard error hierarchy: Graph, Agent, Provider, Tool, State, Persistence, MCP, Budget errors. No routing/identity/authorization errors. | EXTEND: add routing, identity, authorization error types |
| `src/orchestra/core/context.py` | Already has Wave 2 fields: `tenant_id: str | None`, `identity: Any`, `ucan_token: str | None`, `delegation_context: Any`. | EXTEND: add type annotations (replace `Any` with proper types), add `routing_fallback: SelectionFallback` (DD-1) |

Files that DO NOT EXIST yet (will be CREATED):

| File | Purpose |
|------|---------|
| `src/orchestra/routing/strategy.py` | NativeStrategy vs PromptedStrategy transparent switching |
| `src/orchestra/identity/discovery.py` | SignedDiscoveryProvider (verifies signatures before ingestion) |
| `src/orchestra/identity/delegation.py` | DelegationContext + chain verification with attenuation |
| `src/orchestra/identity/did_web.py` | did:web manager (create, resolve, serve did.json) |
| `src/orchestra/security/secrets.py` | SecretProvider ABC + InMemory + Vault(hvac) backends |

---

## Plan A1: Cost Router Contracts & Error Types

**Wave:** 1 (no dependencies)
**Files modified:** `src/orchestra/routing/types.py` (NEW), `src/orchestra/core/errors.py`
**Context budget:** ~10%

### Task A1.1: Define routing type contracts and new error types

**Files:**
- `src/orchestra/routing/types.py` (CREATE)
- `src/orchestra/core/errors.py` (EXTEND)

**Action:**

Create `src/orchestra/routing/types.py` with the following type contracts. These are the interfaces all routing code will implement against:

```python
# src/orchestra/routing/types.py
from __future__ import annotations
import enum
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class SelectionFallback(enum.Enum):
    """How to handle SLA + Budget conflicts (DD-1: FAIL_FAST default)."""
    FAIL_FAST = "fail_fast"          # Raise ModelSelectionError immediately
    FAVOR_COST = "favor_cost"        # Relax SLA, pick cheapest within budget
    FAVOR_LATENCY = "favor_latency"  # Relax budget (1.5x), pick fastest


@dataclass(frozen=True)
class SLAConstraint:
    """Service-level constraints for model selection."""
    max_latency_ms: float | None = None     # P95 latency target
    min_capability_score: int | None = None  # Minimum capability (1-5)
    required_features: set[str] = field(default_factory=set)  # e.g., {"tool_calling", "vision"}


@dataclass(frozen=True)
class BudgetConstraint:
    """Per-request budget constraints."""
    max_cost_usd: float | None = None          # Max cost for this single request
    remaining_budget_usd: float | None = None  # Remaining tenant budget
    tenant_id: str | None = None


@dataclass(frozen=True)
class RoutingDecision:
    """Result of model selection with audit trail."""
    model: "ModelOption"               # Selected model (import from router.py)
    fallback_used: SelectionFallback | None = None  # Non-None if constraint was relaxed
    candidates_considered: int = 0
    reason: str = ""


@runtime_checkable
class CostAwareRouterProtocol(Protocol):
    """Protocol for cost-aware model selection."""
    async def select_model(
        self,
        options: list[Any],
        task_description: str = "",
        estimated_tokens: int = 500,
        sla: SLAConstraint | None = None,
        budget: BudgetConstraint | None = None,
        fallback: SelectionFallback = SelectionFallback.FAIL_FAST,
        **kwargs: Any,
    ) -> RoutingDecision: ...

    def report_outcome(
        self,
        model_name: str,
        provider_name: str,
        success: bool,
        latency_ms: float | None = None,
        actual_cost_usd: float | None = None,
    ) -> None: ...
```

Add the following error types to `src/orchestra/core/errors.py`:

```python
# Under "--- Routing Errors ---" section (new)
class RoutingError(OrchestraError):
    """Base for routing/model-selection errors."""

class ModelSelectionError(RoutingError):
    """No model satisfies both SLA and budget constraints."""
    def __init__(self, message: str, sla: Any = None, budget: Any = None) -> None:
        super().__init__(message)
        self.sla = sla
        self.budget = budget

class AllProvidersUnavailableError(RoutingError):
    """All providers in failover chain failed or are circuit-broken."""

# Under "--- Identity Errors ---" section (new)
class IdentityError(OrchestraError):
    """Base for agent identity errors."""

class InvalidSignatureError(IdentityError):
    """Agent Card or message signature verification failed."""

class DelegationDepthExceededError(IdentityError):
    """Delegation chain exceeds max_depth."""

# Under "--- Authorization Errors ---" section (new)
class AuthorizationError(OrchestraError):
    """Base for capability/authorization errors."""

class UCANVerificationError(AuthorizationError):
    """UCAN token is expired, has invalid audience, or bad signature."""

class CapabilityDeniedError(AuthorizationError):
    """UCAN does not grant the required capability."""
```

Also update `src/orchestra/core/__init__.py` to export all new error types.

**Verify:**
```
python -c "from orchestra.routing.types import SelectionFallback, SLAConstraint, BudgetConstraint, RoutingDecision, CostAwareRouterProtocol; print('OK')"
python -c "from orchestra.core.errors import ModelSelectionError, AllProvidersUnavailableError, InvalidSignatureError, UCANVerificationError, CapabilityDeniedError, DelegationDepthExceededError; print('OK')"
```

**Done:** All routing types, identity errors, and authorization errors importable. No implementation yet -- contracts only.

**Commit:** `feat(wave2): add routing type contracts and identity/auth error types`

---

## Plan A2: CostAwareRouter Rewrite

**Wave:** 2 (depends on A1)
**Files modified:** `src/orchestra/routing/router.py`, `tests/unit/test_cost_router.py` (CREATE)
**Context budget:** ~25%

### Task A2.1: Rewrite CostAwareRouter with SLA + Budget awareness

**Files:**
- `src/orchestra/routing/router.py` (REWRITE)
- `src/orchestra/routing/__init__.py` (EXTEND)
- `tests/unit/test_cost_router.py` (CREATE)

**Action:**

Rewrite `router.py` keeping `ModelOption` and `ThompsonModelSelector` largely intact, but fundamentally reworking `CostAwareRouter`:

1. **Import new types** from `orchestra.routing.types` (SelectionFallback, SLAConstraint, BudgetConstraint, RoutingDecision).

2. **CostAwareRouter.select_model()** new signature:
   ```python
   async def select_model(
       self,
       options: list[ModelOption],
       task_description: str = "",
       estimated_tokens: int = 500,
       sla: SLAConstraint | None = None,
       budget: BudgetConstraint | None = None,
       fallback: SelectionFallback = SelectionFallback.FAIL_FAST,
       **kwargs: Any,
   ) -> RoutingDecision:
   ```

3. **Selection pipeline** (in order):
   a. **Filter by SLA** -- Remove models below `min_capability_score` or above `max_latency_ms` (use `latency_score` as proxy). Remove models missing `required_features`.
   b. **Filter by budget** -- Estimate per-request cost = `(estimated_tokens / 1000) * (input_cost_1k + output_cost_1k)`. Remove models where estimated cost > `max_cost_usd` or > `remaining_budget_usd`.
   c. **If candidates empty, apply fallback per DD-1:**
      - `FAIL_FAST`: raise `ModelSelectionError` with description of unmet constraints.
      - `FAVOR_COST`: restart from full options, apply only budget filter, take cheapest.
      - `FAVOR_LATENCY`: restart from full options, apply SLA filter only, allow up to 1.5x `max_cost_usd`.
   d. **Thompson Sampling** on surviving candidates.
   e. Return `RoutingDecision` with selected model, fallback status, candidate count, reason string.

4. **report_outcome()** extended to also accept `actual_cost_usd` for future cost model calibration (log only for now).

5. **Keep `SimpleHeuristicRouter` and `ThompsonModelSelector` unchanged** (backward compatible).

6. Update `src/orchestra/routing/__init__.py` to export: `CostAwareRouter`, `SimpleHeuristicRouter`, `ThompsonModelSelector`, `ModelOption`, plus all types from `routing.types`.

**Tests** (`tests/unit/test_cost_router.py`):
- `test_select_model_within_budget_and_sla`: 3 models, one fits both -- selected.
- `test_fail_fast_raises_on_conflict`: No model fits both SLA and budget -- `ModelSelectionError` raised.
- `test_favor_cost_relaxes_sla`: FAVOR_COST mode relaxes SLA, picks cheapest.
- `test_favor_latency_relaxes_budget`: FAVOR_LATENCY mode allows 1.5x budget.
- `test_thompson_sampling_exploration`: With uniform priors, all models get selected over 100 calls (not deterministic).
- `test_report_outcome_updates_posteriors`: After 10 successes for model A, its alpha increases.
- `test_empty_options_raises`: ValueError on empty options list.
- `test_backward_compatible_no_constraints`: Calling without sla/budget/fallback works as before.

**Verify:**
```
pytest tests/unit/test_cost_router.py -x -v
```

**Done:** CostAwareRouter selects models respecting SLA + budget constraints with FAIL_FAST default. All 8 tests pass.

**Commit:** `feat(T-4.4): rewrite CostAwareRouter with SLA/budget constraints and SelectionFallback`

---

## Plan A3: ProviderFailover Rewrite

**Wave:** 2 (depends on A1, parallel with A2)
**Files modified:** `src/orchestra/providers/failover.py`, `tests/unit/test_provider_failover.py` (CREATE)
**Context budget:** ~20%

### Task A3.1: Rewrite ProviderFailover using security.AsyncCircuitBreaker

**Files:**
- `src/orchestra/providers/failover.py` (REWRITE)
- `tests/unit/test_provider_failover.py` (CREATE)

**Action:**

Rewrite `failover.py` with these changes per DD-6:

1. **Remove the duplicate `CircuitState` and `AsyncCircuitBreaker`** from this file entirely. Import from `orchestra.security.circuit_breaker`:
   ```python
   from orchestra.security.circuit_breaker import AsyncCircuitBreaker, CircuitOpenError, CircuitState
   ```

2. **Error classification** -- Create an `ErrorClassifier` that categorizes provider errors:
   ```python
   class ErrorCategory(enum.Enum):
       RETRYABLE = "retryable"           # Rate limit, timeout, 5xx -> try next provider
       TERMINAL = "terminal"             # Auth failure -> fail immediately
       MODEL_MISMATCH = "model_mismatch" # Context window exceeded -> try smaller model

   def classify_error(exc: Exception) -> ErrorCategory:
       # Check for known exception types first (RateLimitError, AuthenticationError, etc.)
       # Then fall back to string matching for generic exceptions
   ```

3. **ProviderFailover rewrite:**
   ```python
   class ProviderFailover:
       def __init__(
           self,
           providers: list[Any],  # LLMProvider instances
           failure_threshold: int = 3,
           reset_timeout: float = 60.0,
       ) -> None:
           self._providers = list(providers)
           self._breakers = [
               AsyncCircuitBreaker(
                   failure_threshold=failure_threshold,
                   reset_timeout=reset_timeout,
                   name=getattr(p, "provider_name", f"provider_{i}"),
               )
               for i, p in enumerate(providers)
           ]
           self._latency_tracker: dict[int, list[float]] = {}  # TTFT tracking per provider

       async def complete(self, *args, **kwargs) -> LLMResponse:
           errors = []
           for i, (provider, breaker) in enumerate(zip(self._providers, self._breakers)):
               if not breaker.allow_request():
                   continue
               try:
                   t0 = time.monotonic()
                   result = await provider.complete(*args, **kwargs)
                   latency = (time.monotonic() - t0) * 1000
                   breaker.record_success()
                   self._track_latency(i, latency)
                   return result
               except Exception as exc:
                   breaker.record_failure()
                   category = classify_error(exc)
                   errors.append((exc, category))
                   if category == ErrorCategory.TERMINAL:
                       raise
                   if category == ErrorCategory.MODEL_MISMATCH:
                       raise  # Caller should retry with different model
           raise AllProvidersUnavailableError(
               f"All {len(self._providers)} providers failed: {[str(e) for e, _ in errors]}"
           )
   ```

4. **TTFT latency tracking** -- Keep a sliding window (last 20 calls) per provider for health monitoring. Expose via `get_provider_health(index) -> dict` with p50/p95 latency.

5. Import `AllProvidersUnavailableError` from `orchestra.core.errors`.

**Tests** (`tests/unit/test_provider_failover.py`):
- `test_first_provider_succeeds`: Normal path, first provider called.
- `test_failover_to_second`: First fails with retryable error, second succeeds.
- `test_circuit_breaker_opens`: After N failures, provider skipped.
- `test_circuit_breaker_half_open_recovery`: After timeout, provider retried.
- `test_terminal_error_raises_immediately`: AuthenticationError not retried.
- `test_model_mismatch_raises_immediately`: ContextWindowError not retried.
- `test_all_providers_fail_raises`: AllProvidersUnavailableError raised.
- `test_latency_tracking`: TTFT values recorded and accessible.

**Verify:**
```
pytest tests/unit/test_provider_failover.py -x -v
```

**Done:** ProviderFailover uses the canonical AsyncCircuitBreaker, classifies errors correctly, tracks TTFT. All 8 tests pass.

**Commit:** `feat(T-4.4): rewrite ProviderFailover with error classification and TTFT tracking`

---

## Plan A4: Persistent Budget Ledger

**Wave:** 3 (depends on A2)
**Files modified:** `src/orchestra/cost/persistent_budget.py`, `src/orchestra/cost/tenant.py`, `src/orchestra/cost/__init__.py`, `tests/unit/test_persistent_budget.py` (CREATE)
**Context budget:** ~25%

### Task A4.1: Rewrite PersistentBudget with double-entry ledger and pessimistic locking

**Files:**
- `src/orchestra/cost/persistent_budget.py` (REWRITE)
- `src/orchestra/cost/tenant.py` (EXTEND)
- `src/orchestra/cost/__init__.py` (EXTEND)
- `tests/unit/test_persistent_budget.py` (CREATE)

**Action:**

**tenant.py extensions:**

Add `parent_id` to `Tenant` for hierarchy. Add period boundary logic:
```python
@dataclass
class Tenant:
    tenant_id: str
    name: str
    parent_id: str | None = None  # NEW: for hierarchy (DD-2)
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class BudgetConfig:
    limit_usd: float
    warning_threshold: float = 0.8
    is_hard_limit: bool = True
    reset_period: str = "monthly"  # "monthly", "daily", "none"
    # Note: All timestamps are UTC per DD-2. No tenant timezone.
```

Keep `BudgetState` and `BudgetStatus` as-is (backward compatible).

**persistent_budget.py full rewrite:**

Replace the synchronous SQLite implementation with an async double-entry ledger:

1. **Schema** (3 tables):
   ```sql
   -- Accounts table (one per tenant)
   CREATE TABLE IF NOT EXISTS budget_accounts (
       tenant_id TEXT PRIMARY KEY,
       parent_id TEXT,
       limit_usd REAL NOT NULL,
       reset_period TEXT NOT NULL DEFAULT 'monthly',
       current_period_start TEXT NOT NULL,
       created_at TEXT NOT NULL,
       FOREIGN KEY(parent_id) REFERENCES budget_accounts(tenant_id)
   );

   -- Ledger entries (double-entry: every charge has debit + credit)
   CREATE TABLE IF NOT EXISTS budget_ledger (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       tenant_id TEXT NOT NULL,
       entry_type TEXT NOT NULL,  -- 'debit_estimate', 'credit_correction', 'debit_actual', 'rollover'
       amount_usd REAL NOT NULL,
       run_id TEXT,
       model TEXT,
       idempotency_key TEXT UNIQUE,  -- Prevents double-charge
       created_at TEXT NOT NULL,
       period TEXT NOT NULL,  -- 'YYYY-MM' for monthly, 'YYYY-MM-DD' for daily
       FOREIGN KEY(tenant_id) REFERENCES budget_accounts(tenant_id)
   );

   -- Materialized balance (updated atomically with ledger writes)
   CREATE TABLE IF NOT EXISTS budget_balances (
       tenant_id TEXT NOT NULL,
       period TEXT NOT NULL,
       spent_usd REAL NOT NULL DEFAULT 0.0,
       PRIMARY KEY(tenant_id, period)
   );
   ```

2. **PersistentBudgetStore** class (async via `aiosqlite`):
   ```python
   class PersistentBudgetStore:
       def __init__(self, db_path: str | Path) -> None: ...
       async def initialize(self) -> None:  # Create tables
       async def create_account(self, tenant_id, parent_id, limit_usd, reset_period) -> None: ...
       async def check_and_debit(self, tenant_id, estimated_cost, run_id, model, idempotency_key) -> float:
           """DD-2: Pessimistic locking.
           1. BEGIN IMMEDIATE (SQLite WAL mode)
           2. Read current spent_usd for current period
           3. If spent + estimated > limit -> raise BudgetExceededError
           4. Also check parent hierarchy (child spending counts toward parent per DD-2)
           5. Insert debit_estimate ledger entry
           6. Update balance
           7. COMMIT
           Returns remaining budget.
           """
       async def adjust_actual(self, tenant_id, run_id, actual_cost, idempotency_key) -> None:
           """Post-call: insert credit_correction if actual != estimated."""
       async def get_balance(self, tenant_id) -> tuple[float, float]:
           """Returns (spent_usd, limit_usd) for current period."""
       async def rollover_if_needed(self, tenant_id) -> bool:
           """Lazy rollover: if current date > period end, insert rollover entry, new period row."""
   ```

3. **TenantBudgetManager** (async wrapper):
   ```python
   class TenantBudgetManager:
       def __init__(self, store: PersistentBudgetStore) -> None: ...
       async def check_budget(self, tenant_id) -> bool: ...
       async def reserve(self, tenant_id, estimated_cost, run_id, model) -> float: ...
       async def finalize(self, tenant_id, run_id, actual_cost) -> None: ...
   ```

4. **Hierarchy enforcement (DD-2):** Child spending counts toward parent. A child cannot exceed its own allocation even if parent has remaining balance. Traverse parent chain upward during `check_and_debit`.

5. **Period handling (DD-2):** UTC-only timestamps. Monthly = `YYYY-MM`, Daily = `YYYY-MM-DD`. First request after period boundary triggers lazy rollover.

6. Update `src/orchestra/cost/__init__.py` to export `PersistentBudgetStore` and `TenantBudgetManager`.

**Tests** (`tests/unit/test_persistent_budget.py`):
- `test_create_account_and_check_balance`: Fresh account has $0 spent.
- `test_debit_reduces_remaining`: After debit, remaining = limit - spent.
- `test_budget_exceeded_raises`: Debit exceeding limit raises `BudgetExceededError`.
- `test_idempotent_debit`: Same idempotency_key does not double-charge.
- `test_actual_cost_correction`: After adjust_actual, ledger has correction entry.
- `test_hierarchy_parent_limit`: Child debit counted against parent; parent blocks if parent limit exceeded.
- `test_child_cannot_exceed_own_allocation`: Even with parent headroom, child is capped.
- `test_period_rollover_monthly`: After month boundary, balance resets.
- `test_concurrent_debits_pessimistic_lock`: Two concurrent debits on same tenant -- one succeeds, one raises or waits (not both succeed causing overspend).

All tests use `aiosqlite` with in-memory database (`:memory:` or temp file).

**Verify:**
```
pytest tests/unit/test_persistent_budget.py -x -v
```

**Done:** Budget survives server restart; tenant-scoped budgets enforce limits with pessimistic locking; hierarchy works. All 9 tests pass.

**Commit:** `feat(T-4.5): rewrite PersistentBudget with double-entry ledger and pessimistic locking`

---

## Plan B1: Identity Contracts & Types

**Wave:** 1 (no dependencies, parallel with A1)
**Files modified:** `src/orchestra/identity/types.py` (NEW)
**Context budget:** ~10%

### Task B1.1: Define identity and authorization type contracts

**Files:**
- `src/orchestra/identity/types.py` (CREATE)

**Action:**

Create the type contracts for the entire identity/authorization subsystem:

```python
# src/orchestra/identity/types.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class DelegationContext:
    """Tracks the delegation chain from root to current agent (DD-5)."""
    chain: tuple[str, ...]     # DIDs from root to current: ("did:A", "did:B", "did:C")
    issuer_did: str            # Who started the chain (chain[0])
    current_did: str           # Current agent (chain[-1])
    depth: int                 # len(chain) - 1
    max_depth: int = 3         # From root's AgentIdentity.max_delegation_depth

    @classmethod
    def root(cls, did: str, max_depth: int = 3) -> DelegationContext:
        return cls(chain=(did,), issuer_did=did, current_did=did, depth=0, max_depth=max_depth)

    def delegate_to(self, child_did: str) -> DelegationContext:
        if self.depth >= self.max_depth:
            from orchestra.core.errors import DelegationDepthExceededError
            raise DelegationDepthExceededError(
                f"Delegation depth {self.depth} >= max {self.max_depth}"
            )
        new_chain = self.chain + (child_did,)
        return DelegationContext(
            chain=new_chain,
            issuer_did=self.issuer_did,
            current_did=child_did,
            depth=len(new_chain) - 1,
            max_depth=self.max_depth,
        )

    def to_baggage_value(self) -> str:
        """Serialize for OTel Baggage (DD-5)."""
        return ",".join(self.chain)

    @classmethod
    def from_baggage_value(cls, value: str, max_depth: int = 3) -> DelegationContext:
        dids = tuple(value.split(","))
        return cls(chain=dids, issuer_did=dids[0], current_did=dids[-1],
                   depth=len(dids) - 1, max_depth=max_depth)


@dataclass(frozen=True)
class UCANCapability:
    """A UCAN capability grant (DD-4 resource pointer format)."""
    resource: str   # e.g., "orchestra:tools/web_search"
    ability: str    # e.g., "tool/invoke"
    max_calls: int | None = None  # Optional invocation limit


@dataclass(frozen=True)
class UCANToken:
    """Parsed UCAN token metadata."""
    raw: str                          # The JWT string
    issuer_did: str                   # iss
    audience_did: str                 # aud
    capabilities: tuple[UCANCapability, ...]
    not_before: int                   # nbf (Unix timestamp)
    expires_at: int                   # exp (Unix timestamp)
    nonce: str                        # nnc
    proofs: tuple[str, ...]           # prf (inline JWT strings)

    @property
    def is_expired(self) -> bool:
        import time
        return time.time() > self.expires_at


@runtime_checkable
class SecretProvider(Protocol):
    """ABC for secret storage backends (DD-7: key material storage)."""
    async def get_secret(self, path: str) -> bytes: ...
    async def put_secret(self, path: str, value: bytes) -> None: ...
    async def delete_secret(self, path: str) -> None: ...
```

**Verify:**
```
python -c "from orchestra.identity.types import DelegationContext, UCANCapability, UCANToken, SecretProvider; dc = DelegationContext.root('did:test:1'); dc2 = dc.delegate_to('did:test:2'); print(f'chain={dc2.chain}, baggage={dc2.to_baggage_value()}')"
```

**Done:** All identity type contracts importable. DelegationContext supports chain operations and baggage serialization.

**Commit:** `feat(wave2): add identity type contracts (DelegationContext, UCANCapability, UCANToken, SecretProvider)`

---

## Plan B2: AgentIdentity + Signed Discovery

**Wave:** 2 (depends on B1)
**Files modified:** `src/orchestra/identity/agent_identity.py`, `src/orchestra/identity/discovery.py` (NEW), `src/orchestra/identity/did_web.py` (NEW), `src/orchestra/security/secrets.py` (NEW), `src/orchestra/identity/__init__.py`, `tests/unit/test_agent_identity.py` (CREATE), `tests/unit/test_signed_discovery.py` (CREATE)
**Context budget:** ~30%

### Task B2.1: Extend AgentIdentity with did:web, versioned AgentCards, JWS signing

**Files:**
- `src/orchestra/identity/agent_identity.py` (EXTEND)
- `src/orchestra/identity/did_web.py` (CREATE)
- `tests/unit/test_agent_identity.py` (CREATE)

**Action:**

1. **AgentCard extensions** -- Add fields required by DD-3 and DD-7:
   ```python
   @dataclass
   class AgentCard:
       did: str
       name: str
       agent_type: str
       capabilities: list[str] = field(default_factory=list)
       version: int = 1                           # NEW: incremented on rotation
       expires_at: float | None = None            # NEW: Unix timestamp (DD-3: 1h overlap)
       nats_url: str | None = None
       metadata: dict[str, Any] = field(default_factory=dict)
       signature: str | None = None               # JWS Compact Serialization
   ```

2. **JWS Compact signing** via `joserfc` (DD-3):
   ```python
   def sign_jws(self, signing_key: OKPKey) -> None:
       """Sign card using JWS Compact Serialization with EdDSA (DD-3)."""
       from joserfc import jws
       from joserfc.jwk import OKPKey
       payload = self.to_json().encode("utf-8")
       header = {"alg": "EdDSA"}
       self.signature = jws.serialize_compact(header, payload, signing_key, algorithms=["EdDSA"])

   def verify_jws(self, verification_key: OKPKey) -> bool:
       """Verify JWS Compact signature (DD-3)."""
       from joserfc import jws
       try:
           result = jws.deserialize_compact(self.signature, verification_key, algorithms=["EdDSA"])
           return result.payload == self.to_json().encode("utf-8")
       except Exception:
           return False
   ```

3. **Keep existing `sign()`/`verify()` as `sign_raw()`/`verify_raw()`** for backward compatibility. The new JWS methods are the preferred path going forward.

4. **AgentIdentity extensions** -- Add `max_delegation_depth`, `create_delegation_context()`:
   ```python
   class AgentIdentity:
       def __init__(self, ..., max_delegation_depth: int = 3) -> None: ...
       @property
       def delegation_context(self) -> DelegationContext:
           return DelegationContext.root(self._did, self._max_delegation_depth)
   ```

5. **did:web manager** (`did_web.py`, DD-7):
   ```python
   class DidWebManager:
       """Manages did:web identities for long-lived agents."""
       def __init__(self, base_url: str) -> None:
           """base_url e.g. 'orchestra.example.com'"""
       def create_did(self, agent_name: str) -> str:
           """Returns did:web:{base_url}:agents:{agent_name}"""
       def build_did_document(self, did: str, ed_pub: bytes, x_pub: bytes, service_endpoint: str) -> dict:
           """Build the did.json document for HTTP hosting."""
       async def resolve(self, did: str) -> dict:
           """Resolve did:web by fetching .well-known/did.json or path-based did.json."""
   ```

6. **Add `joserfc` import** to AgentIdentity for constructing `OKPKey` from `cryptography` Ed25519 keys:
   ```python
   def _make_okp_key(self) -> OKPKey:
       """Convert cryptography Ed25519 key to joserfc OKPKey for JWS signing."""
       from joserfc.jwk import OKPKey
       d_bytes = self._signing_key.private_bytes_raw()
       x_bytes = self._signing_key.public_key().public_bytes_raw()
       return OKPKey.import_key({"kty": "OKP", "crv": "Ed25519",
                                  "d": base64url_encode(d_bytes),
                                  "x": base64url_encode(x_bytes)})
   ```

**Tests** (`tests/unit/test_agent_identity.py`):
- `test_create_ephemeral_identity`: AgentIdentity.create() produces valid did:peer:2.
- `test_agent_card_jws_sign_verify`: Card signed with JWS, verified with public key.
- `test_agent_card_jws_tampered_rejected`: Modified card content fails verification.
- `test_agent_card_versioning`: version increments on rotation.
- `test_agent_card_expiry`: expires_at in the past detected by `is_expired` property.
- `test_delegation_context_from_identity`: delegation_context property returns root context.
- `test_did_web_create_and_document`: DidWebManager creates correct DID and document structure.
- `test_backward_compat_sign_raw`: Old sign()/verify() still works via renamed sign_raw()/verify_raw().

**Verify:**
```
pytest tests/unit/test_agent_identity.py -x -v
```

**Done:** AgentIdentity supports both did:peer:2 and did:web. AgentCards use JWS Compact. All 8 tests pass.

### Task B2.2: Create SignedDiscoveryProvider and SecretProvider

**Files:**
- `src/orchestra/identity/discovery.py` (CREATE)
- `src/orchestra/security/secrets.py` (CREATE)
- `src/orchestra/identity/__init__.py` (CREATE/UPDATE)
- `tests/unit/test_signed_discovery.py` (CREATE)

**Action:**

1. **SignedDiscoveryProvider** (`discovery.py`) -- Gossip poisoning defense (DD-3):
   ```python
   class SignedDiscoveryProvider:
       """Registry that only accepts agent cards with valid cryptographic signatures.
       Rejects unsigned or tampered cards to prevent gossip poisoning."""

       def __init__(self, max_cards_per_did: int = 2) -> None:
           self._cards: dict[str, list[AgentCard]] = {}  # did -> [current, previous]

       def register(self, card: AgentCard) -> bool:
           """Verify signature, then register. Returns False if signature invalid."""
           # 1. Resolve DID to get Ed25519 verification key
           # 2. Verify JWS signature
           # 3. Check expires_at not in past
           # 4. Check version is >= current version for this DID
           # 5. Store (keep at most max_cards_per_did per DD-3)
           # Raises InvalidSignatureError on bad signature

       def lookup(self, did: str) -> AgentCard | None:
           """Get the current (highest version) card for a DID."""

       def lookup_by_type(self, agent_type: str) -> list[AgentCard]:
           """Find all agents of a given type."""

       def revoke(self, did: str) -> None:
           """Remove all cards for a DID."""

       @property
       def registered_count(self) -> int: ...
   ```

2. **SecretProvider backends** (`secrets.py`):
   ```python
   class InMemorySecretProvider:
       """In-memory secret store for testing and local development."""
       async def get_secret(self, path: str) -> bytes: ...
       async def put_secret(self, path: str, value: bytes) -> None: ...
       async def delete_secret(self, path: str) -> None: ...

   class VaultSecretProvider:
       """HashiCorp Vault KV v2 backend. Requires hvac library."""
       def __init__(self, url: str, token: str, mount_point: str = "secret") -> None: ...
       async def get_secret(self, path: str) -> bytes:
           # Uses asyncio.to_thread(self._client.secrets.kv.v2.read_secret_version, ...)
       async def put_secret(self, path: str, value: bytes) -> None: ...
       async def delete_secret(self, path: str) -> None: ...
   ```
   Both implement the `SecretProvider` protocol from `identity/types.py`.

3. **identity/__init__.py** -- Export:
   ```python
   from orchestra.identity.agent_identity import AgentIdentity, AgentCard, Ed25519Signer, Signer
   from orchestra.identity.types import DelegationContext, UCANCapability, UCANToken, SecretProvider
   from orchestra.identity.discovery import SignedDiscoveryProvider
   from orchestra.identity.did_web import DidWebManager
   ```

**Tests** (`tests/unit/test_signed_discovery.py`):
- `test_register_signed_card`: Valid signed card accepted.
- `test_reject_unsigned_card`: Card with no signature rejected.
- `test_reject_tampered_card`: Card with modified content but original signature rejected.
- `test_reject_wrong_key_card`: Card signed by different key rejected.
- `test_max_cards_per_did`: Third card evicts oldest.
- `test_lookup_by_type`: Multiple agents registered, filtered by type.
- `test_version_ordering`: Higher version replaces lower.
- `test_expired_card_rejected`: Card with past expires_at rejected.
- `test_in_memory_secret_provider`: Store and retrieve secrets.

**Verify:**
```
pytest tests/unit/test_signed_discovery.py -x -v
```

**Done:** Gossip poisoning blocked by signature verification. SecretProvider abstraction with InMemory backend works. All 9 tests pass.

**Commit:** `feat(T-4.6): add SignedDiscoveryProvider, DidWebManager, SecretProvider`

---

## Plan B3: UCAN via joserfc

**Wave:** 3 (depends on B2)
**Files modified:** `src/orchestra/identity/ucan.py`, `src/orchestra/identity/delegation.py` (NEW), `tests/unit/test_ucan_ttls.py` (CREATE)
**Context budget:** ~25%

### Task B3.1: Rewrite UCAN with joserfc JWT and delegation chains

**Files:**
- `src/orchestra/identity/ucan.py` (REWRITE)
- `src/orchestra/identity/delegation.py` (CREATE)
- `tests/unit/test_ucan_ttls.py` (CREATE)

**Action:**

**ucan.py full rewrite** (DD-9: drop py-ucan, use joserfc directly):

```python
"""UCAN implementation using joserfc JWT (DD-9: py-ucan dropped)."""
import secrets
import time
from joserfc import jwt
from joserfc.jwk import OKPKey

class UCANService:
    """Issues, verifies, and delegates UCAN tokens using joserfc."""

    def __init__(self, signing_key: OKPKey, issuer_did: str) -> None:
        self._key = signing_key
        self._issuer_did = issuer_did

    def issue(
        self,
        audience_did: str,
        capabilities: list[UCANCapability],
        ttl_seconds: int = 900,  # 15 min default (short-lived per PLAN.md: 1-60 min)
        proofs: list[str] | None = None,
    ) -> str:
        """Issue a UCAN token as a signed JWT (DD-9 format)."""
        now = int(time.time())
        payload = {
            "ucv": "0.8.1",
            "iss": self._issuer_did,
            "aud": audience_did,
            "nbf": now - 60,  # 1 min clock skew tolerance
            "exp": now + ttl_seconds,
            "att": [
                {"with": cap.resource, "can": cap.ability,
                 **({"max_calls": cap.max_calls} if cap.max_calls else {})}
                for cap in capabilities
            ],
            "prf": proofs or [],
            "nnc": secrets.token_hex(8),
        }
        header = {"alg": "EdDSA", "typ": "JWT"}
        return jwt.encode(header, payload, self._key, algorithms=["EdDSA"])

    @staticmethod
    def verify(
        token: str,
        verification_key: OKPKey,
        expected_audience: str,
    ) -> UCANToken:
        """Verify a UCAN token. Raises UCANVerificationError on failure."""
        try:
            result = jwt.decode(token, verification_key, algorithms=["EdDSA"])
        except Exception as e:
            raise UCANVerificationError(f"Signature verification failed: {e}")

        claims = result.claims
        now = int(time.time())

        if claims.get("exp", 0) < now:
            raise UCANVerificationError(f"Token expired at {claims['exp']}, now={now}")
        if claims.get("aud") != expected_audience:
            raise UCANVerificationError(f"Audience mismatch: {claims.get('aud')} != {expected_audience}")

        capabilities = tuple(
            UCANCapability(resource=att["with"], ability=att["can"],
                           max_calls=att.get("max_calls"))
            for att in claims.get("att", [])
        )
        return UCANToken(
            raw=token, issuer_did=claims["iss"], audience_did=claims["aud"],
            capabilities=capabilities, not_before=claims.get("nbf", 0),
            expires_at=claims["exp"], nonce=claims.get("nnc", ""),
            proofs=tuple(claims.get("prf", [])),
        )

    def delegate(
        self,
        parent_token: str,
        child_audience: str,
        child_capabilities: list[UCANCapability],
        ttl_seconds: int = 900,
    ) -> str:
        """Delegate a subset of capabilities from parent token to child (DD-4 attenuation)."""
        # The parent token is included as a proof in the child
        # Child capabilities must be a subset of parent's (checked by verify_chain)
        return self.issue(
            audience_did=child_audience,
            capabilities=child_capabilities,
            ttl_seconds=ttl_seconds,
            proofs=[parent_token],
        )
```

**delegation.py** (DD-5 chain verification):

```python
class DelegationChainVerifier:
    """Verifies UCAN delegation chains and enforces attenuation (DD-4)."""

    @staticmethod
    def verify_chain(tokens: list[str], keys: dict[str, OKPKey]) -> list[UCANToken]:
        """Verify a chain of UCAN tokens.
        Each token's issuer must be the previous token's audience.
        Each token's capabilities must be a subset of its proof's capabilities.
        """

    @staticmethod
    def check_attenuation(parent_caps: list[UCANCapability], child_caps: list[UCANCapability]) -> bool:
        """DD-4: Child caps must be subset of parent caps.
        For max_calls: child.max_calls <= parent.max_calls.
        For resources: child resource must match parent resource exactly.
        """

    @staticmethod
    def effective_capabilities(
        acl_caps: set[str],       # From ToolACL
        ucan_caps: list[UCANCapability],  # From UCAN token
    ) -> list[UCANCapability]:
        """DD-4: Strict intersection of ACL and UCAN.
        Only capabilities present in BOTH are granted.
        """
```

**Tests** (`tests/unit/test_ucan_ttls.py`):
- `test_issue_and_verify`: Issue token, verify succeeds.
- `test_expired_token_rejected`: Token with 1s TTL, wait 2s, verify raises UCANVerificationError.
- `test_wrong_audience_rejected`: Verify with wrong audience raises UCANVerificationError.
- `test_wrong_key_rejected`: Verify with different key raises UCANVerificationError.
- `test_delegate_creates_chain`: Delegated token has parent in prf array.
- `test_attenuation_narrows_caps`: Child max_calls < parent max_calls passes check.
- `test_attenuation_rejects_escalation`: Child requesting more than parent fails.
- `test_effective_caps_intersection`: ACL{A,B} intersect UCAN{B,C} = {B} only.
- `test_expired_ucan_denies_all`: Expired UCAN means deny-all (DD-4 rule 4), not ACL fallback.
- `test_no_ucan_falls_back_to_acl`: Missing UCAN = ACL-only (DD-4 rule 3, backward compatible).

**Verify:**
```
pytest tests/unit/test_ucan_ttls.py -x -v
```

**Done:** UCAN tokens issued via joserfc, expire correctly, delegation chains verified, attenuation enforced. All 10 tests pass.

**Commit:** `feat(T-4.7): implement UCAN via joserfc with TTLs and delegation chain verification`

---

## Plan B4: UCAN-ACL Integration

**Wave:** 4 (depends on B3)
**Files modified:** `src/orchestra/security/acl.py`, `tests/unit/test_ucan_acl_integration.py` (CREATE)
**Context budget:** ~15%

### Task B4.1: Integrate UCAN with ToolACL per DD-4

**Files:**
- `src/orchestra/security/acl.py` (EXTEND)
- `tests/unit/test_ucan_acl_integration.py` (CREATE)

**Action:**

Extend `ToolACL.is_authorized()` with optional UCAN parameter per DD-4:

```python
def is_authorized(self, tool_name: str, *, ucan: UCANToken | None = None) -> bool:
    """Check if a tool is authorized.

    DD-4 rules:
    1. If no UCAN provided: check ACL only (backward compatible).
    2. If UCAN provided but expired: deny ALL (do NOT fall back to ACL).
    3. If UCAN provided and valid: effective = intersection(ACL, UCAN).
       - ACL deny-list still takes precedence.
       - Tool must appear in UCAN's att[] as orchestra:tools/{tool_name} with ability tool/invoke.
    """
    # Step 1: ACL deny-list always wins
    if tool_name in self.denied_tools:
        return False
    for pattern in self.deny_patterns:
        if fnmatch.fnmatch(tool_name, pattern):
            return False

    # Step 2: If no UCAN, ACL-only mode
    if ucan is None:
        return self._check_acl_only(tool_name)

    # Step 3: If UCAN expired, deny ALL (DD-4 rule 4)
    if ucan.is_expired:
        return False

    # Step 4: ACL allows it?
    if not self._check_acl_only(tool_name):
        return False

    # Step 5: UCAN grants it?
    resource = f"orchestra:tools/{tool_name}"
    for cap in ucan.capabilities:
        if cap.resource == resource and cap.ability == "tool/invoke":
            return True

    return False  # Not in UCAN = denied (DD-4: UCAN cannot be wider than ACL)
```

Factor the current ACL-only logic into `_check_acl_only()` private method.

Also add a `check_ucan_call_limit()` method for tracking max_calls:
```python
def check_ucan_call_limit(
    self,
    tool_name: str,
    ucan: UCANToken,
    call_counts: dict[str, int],  # Mutable counter on ExecutionContext
) -> bool:
    """Check and decrement UCAN max_calls for a tool. Returns False if exhausted."""
```

**Tests** (`tests/unit/test_ucan_acl_integration.py`):
- `test_acl_only_backward_compatible`: No UCAN = same behavior as before.
- `test_ucan_intersection_allows`: ACL allows {A, B}, UCAN grants {B, C} -> B allowed, C denied.
- `test_ucan_not_in_acl_denied`: UCAN grants tool not in ACL -> denied.
- `test_expired_ucan_denies_all`: Expired UCAN -> even ACL-allowed tools denied.
- `test_deny_list_overrides_ucan`: ACL deny-list blocks even if UCAN grants.
- `test_max_calls_enforcement`: UCAN max_calls=3 -> 4th call returns False.
- `test_allow_all_acl_with_ucan`: ACL allow_all + UCAN = only UCAN-granted tools.

**Verify:**
```
pytest tests/unit/test_ucan_acl_integration.py -x -v
```

**Done:** ToolACL supports UCAN intersection. Expired UCANs deny all. Max calls enforced. All 7 tests pass.

**Commit:** `feat(T-4.7): integrate UCAN capability intersection with ToolACL`

---

## Plan C1: ExecutionContext Extensions & Integration

**Wave:** 5 (depends on A4 + B4 -- both tracks must complete)
**Files modified:** `src/orchestra/core/context.py`, `tests/unit/test_wave2_integration.py` (CREATE)
**Context budget:** ~15%

### Task C1.1: Extend ExecutionContext with identity, budget, and delegation

**Files:**
- `src/orchestra/core/context.py` (EXTEND)
- `tests/unit/test_wave2_integration.py` (CREATE)

**Action:**

Add optional fields to `ExecutionContext` (all backward-compatible with `None` defaults):

```python
@dataclass
class ExecutionContext:
    # ... existing fields ...

    # Phase 4 Wave 2 extensions (all Optional for backward compatibility)
    identity: Any = None              # AgentIdentity instance
    ucan_token: str | None = None     # Raw UCAN JWT string for current context
    tenant_id: str | None = None      # Budget tenant ID
    delegation_context: Any = None    # DelegationContext instance
    ucan_call_counts: dict[str, int] = field(default_factory=dict)  # max_calls tracker (DD-4)
```

**Integration test** (`tests/unit/test_wave2_integration.py`) -- End-to-end flow:

```python
async def test_full_wave2_flow():
    """Integration test: identity -> UCAN -> budget -> routing -> failover."""
    # 1. Create two agent identities (parent + child)
    parent = AgentIdentity.create()
    child = AgentIdentity.create()

    # 2. Parent creates and signs an AgentCard
    card = parent.create_card("orchestrator", "supervisor", ["delegate", "web_search"])
    # Card should have JWS signature

    # 3. Register card with SignedDiscoveryProvider
    discovery = SignedDiscoveryProvider()
    assert discovery.register(card) is True

    # 4. Parent issues UCAN to child with TTL and max_calls
    ucan_service = UCANService(parent._make_okp_key(), parent.did)
    token = ucan_service.issue(
        audience_did=child.did,
        capabilities=[UCANCapability("orchestra:tools/web_search", "tool/invoke", max_calls=5)],
        ttl_seconds=300,
    )

    # 5. Child verifies UCAN
    parsed = UCANService.verify(token, parent._make_okp_key(), child.did)
    # Note: verify uses parent's public key, not child's

    # 6. ToolACL intersection check
    acl = ToolACL(allowed_tools={"web_search", "code_exec"}, allow_all=False)
    assert acl.is_authorized("web_search", ucan=parsed) is True
    assert acl.is_authorized("code_exec", ucan=parsed) is False  # Not in UCAN

    # 7. Delegation chain
    ctx = DelegationContext.root(parent.did)
    ctx2 = ctx.delegate_to(child.did)
    assert ctx2.depth == 1
    assert ctx2.to_baggage_value() == f"{parent.did},{child.did}"

    # 8. Budget check (uses PersistentBudgetStore)
    store = PersistentBudgetStore(":memory:")
    await store.initialize()
    await store.create_account("tenant-1", None, 10.0, "monthly")
    remaining = await store.check_and_debit("tenant-1", 2.50, "run-1", "gpt-4o", "key-1")
    assert remaining == 7.50

    # 9. Cost-aware routing
    router = CostAwareRouter()
    options = [
        ModelOption("gpt-4o", "openai", 0.01, 0.03, 2, 5),
        ModelOption("gpt-4o-mini", "openai", 0.001, 0.002, 1, 3),
    ]
    decision = await router.select_model(
        options, "simple query", 200,
        budget=BudgetConstraint(max_cost_usd=0.005),
        fallback=SelectionFallback.FAIL_FAST,
    )
    assert decision.model.model_name == "gpt-4o-mini"  # Only one fits budget

    # 10. Wired into ExecutionContext
    ectx = ExecutionContext(
        identity=parent,
        ucan_token=token,
        tenant_id="tenant-1",
        delegation_context=ctx2,
    )
    assert ectx.tenant_id == "tenant-1"
    assert ectx.delegation_context.depth == 1
```

**Verify:**
```
pytest tests/unit/test_wave2_integration.py -x -v
```

**Done:** ExecutionContext carries identity, UCAN, budget, and delegation. Full end-to-end flow validated. Integration test passes.

**Commit:** `feat(wave2): extend ExecutionContext with identity/budget/delegation and add integration test`

---

## Wave Execution Schedule

```
Wave 1 (parallel, no deps):
  Plan A1: Cost Router Contracts        (~15 min)
  Plan B1: Identity Contracts           (~15 min)

Wave 2 (parallel within tracks):
  Plan A2: CostAwareRouter rewrite      (~30 min, depends A1)
  Plan A3: ProviderFailover rewrite     (~25 min, depends A1)
  Plan B2: AgentIdentity + Discovery    (~40 min, depends B1)

Wave 3 (parallel within tracks):
  Plan A4: PersistentBudget ledger      (~30 min, depends A2)
  Plan B3: UCAN via joserfc             (~30 min, depends B2)

Wave 4:
  Plan B4: UCAN-ACL Integration         (~20 min, depends B3)

Wave 5 (sync point -- both tracks):
  Plan C1: ExecutionContext + Integration (~20 min, depends A4 + B4)
```

**Total estimated Claude execution time:** ~3-4 hours across 2 sessions

**Parallelism opportunities:**
- Wave 1: A1 || B1 (completely independent)
- Wave 2: A2 || A3 || B2 (A2/A3 share no files; B2 is independent track)
- Wave 3: A4 || B3 (independent tracks)
- Wave 4-5: Sequential (integration requires both tracks)

---

## Dependency Graph

```
A1 (routing types)          B1 (identity types)
  |    \                      |
  |     \                     |
  v      v                    v
A2       A3                  B2
(router) (failover)          (identity + discovery)
  |                           |
  v                           v
A4                           B3
(budget)                     (ucan)
  |                           |
  |                           v
  |                          B4
  |                          (ucan-acl)
  |                           |
  +----------+  +-------------+
             |  |
             v  v
              C1
       (context + integration)
```

---

## Atomic Commit Points

| # | Commit Message | Plans | Files |
|---|---------------|-------|-------|
| 1 | `feat(wave2): add routing type contracts and identity/auth error types` | A1 | types.py, errors.py |
| 2 | `feat(wave2): add identity type contracts (DelegationContext, UCANCapability, UCANToken, SecretProvider)` | B1 | identity/types.py |
| 3 | `feat(T-4.4): rewrite CostAwareRouter with SLA/budget constraints and SelectionFallback` | A2 | router.py, test_cost_router.py |
| 4 | `feat(T-4.4): rewrite ProviderFailover with error classification and TTFT tracking` | A3 | failover.py, test_provider_failover.py |
| 5 | `feat(T-4.6): add SignedDiscoveryProvider, DidWebManager, SecretProvider` | B2 | agent_identity.py, discovery.py, did_web.py, secrets.py, tests |
| 6 | `feat(T-4.5): rewrite PersistentBudget with double-entry ledger and pessimistic locking` | A4 | persistent_budget.py, tenant.py, tests |
| 7 | `feat(T-4.7): implement UCAN via joserfc with TTLs and delegation chain verification` | B3 | ucan.py, delegation.py, tests |
| 8 | `feat(T-4.7): integrate UCAN capability intersection with ToolACL` | B4 | acl.py, tests |
| 9 | `feat(wave2): extend ExecutionContext with identity/budget/delegation and add integration test` | C1 | context.py, tests |

Each commit is independently revertable. Tests pass at every commit point.

---

## Observable Truths (Wave 2 Verification Criteria)

| # | Truth | Verification Command | Task |
|---|-------|---------------------|------|
| S3 | Gossip poisoning blocked by signature verification | `pytest tests/unit/test_signed_discovery.py -k "tampered or unsigned or wrong_key" -v` | B2 |
| S6 | Cost-aware routing reduces spend (selects cheaper model when appropriate) | `pytest tests/unit/test_cost_router.py -k "within_budget" -v` | A2 |
| S7 | UCAN tokens expire and require refresh | `pytest tests/unit/test_ucan_ttls.py -k "expired" -v` | B3 |
| W2-1 | Budget survives in persistent store with correct locking | `pytest tests/unit/test_persistent_budget.py -v` | A4 |
| W2-2 | Provider failover uses canonical circuit breaker | `pytest tests/unit/test_provider_failover.py -v` | A3 |
| W2-3 | UCAN + ACL intersection enforced | `pytest tests/unit/test_ucan_acl_integration.py -v` | B4 |
| W2-4 | Full flow: identity -> UCAN -> budget -> routing works end-to-end | `pytest tests/unit/test_wave2_integration.py -v` | C1 |

---

## Pyproject.toml Changes Required

No new external dependencies needed for Wave 2:
- `joserfc>=1.6` -- already in `messaging` and `security` extras
- `cryptography>=42.0` -- already in `messaging` extra
- `base58>=2.1` -- already in `messaging` extra
- `aiosqlite>=0.19` -- already in `storage` extra
- `numpy>=1.26` -- already in dev dependencies (used by ThompsonModelSelector)

Remove (per DD-9, DD-10):
- `pynacl>=1.5` from `security` extras (DD-10: not needed)

Add (convenience):
- `hvac>=2.4.0` to a new `vault` extra (optional, for VaultSecretProvider)

---

## Risk Register (Wave 2 Specific)

| Risk | Impact | Mitigation |
|------|--------|------------|
| joserfc EdDSA OKPKey import from cryptography | Low | DD-11 confirmed; tested in Wave 1 |
| aiosqlite BEGIN IMMEDIATE semantics | Low | Well-documented; use `execute("BEGIN IMMEDIATE")` explicitly |
| Thompson Sampling cold-start | Medium | Uniform priors (alpha=1, beta=1) = random until ~30 observations; acceptable |
| UCAN clock skew | Low | 60s tolerance in nbf (DD-9 format); documented in tests |
| ToolACL is frozen dataclass | Medium | Cannot add methods without unfreezing; may need to convert to regular class |

---

*Created: 2026-03-12*
*Sources: PLAN.md, WAVE2-DESIGN-DECISIONS.md (DD-1 through DD-11), wave2-combined-research.md*
*Codebase analysis: router.py, failover.py, persistent_budget.py, tenant.py, agent_identity.py, ucan.py, acl.py, circuit_breaker.py, context.py, peer_did.py*
