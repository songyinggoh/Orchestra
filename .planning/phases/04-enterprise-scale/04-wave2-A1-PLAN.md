---
phase: 04-enterprise-scale
plan: wave2-A1
type: execute
wave: 1
depends_on: []
files_modified:
  - src/orchestra/routing/types.py
  - src/orchestra/core/errors.py
  - src/orchestra/core/__init__.py
autonomous: true
requirements: [T-4.4]
must_haves:
  truths:
    - "All routing types (SelectionFallback, SLAConstraint, BudgetConstraint, RoutingDecision, CostAwareRouterProtocol) importable from orchestra.routing.types"
    - "All routing/identity/authorization error types importable from orchestra.core.errors"
    - "No implementation exists — contracts only"
  artifacts:
    - path: "src/orchestra/routing/types.py"
      provides: "Type contracts for cost-aware routing (DD-1 SelectionFallback enum, SLA/Budget constraints, Protocol)"
      min_lines: 50
    - path: "src/orchestra/core/errors.py"
      provides: "Extended error hierarchy: RoutingError, IdentityError, AuthorizationError and subclasses"
      contains: "ModelSelectionError"
  key_links:
    - from: "src/orchestra/routing/router.py"
      to: "src/orchestra/routing/types.py"
      via: "from orchestra.routing.types import SelectionFallback, SLAConstraint, BudgetConstraint, RoutingDecision"
      pattern: "from orchestra\\.routing\\.types import"
    - from: "src/orchestra/providers/failover.py"
      to: "src/orchestra/core/errors.py"
      via: "from orchestra.core.errors import AllProvidersUnavailableError"
      pattern: "AllProvidersUnavailableError"
---

<objective>
Define type contracts and error types for all Wave 2 routing and identity work.

Purpose: Plans A2, A3, A4 (routing/cost) and B2, B3, B4 (identity/auth) all import from these contracts. Creating them first in Wave 1 lets both tracks run in parallel without coupling.
Output: src/orchestra/routing/types.py (new), extended src/orchestra/core/errors.py with routing, identity, and authorization error classes.
</objective>

<execution_context>
@C:/Users/user/.claude/get-shit-done/workflows/execute-plan.md
@C:/Users/user/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/04-enterprise-scale/PLAN.md
@.planning/phases/04-enterprise-scale/WAVE2-DESIGN-DECISIONS.md
</context>

<tasks>

<task type="auto" tdd="true" id="A1.1" name="Create routing type contracts and extend errors">
  <files>src/orchestra/routing/types.py, src/orchestra/core/errors.py, src/orchestra/core/__init__.py</files>
  <behavior>
    - SelectionFallback enum has exactly 3 members: FAIL_FAST, FAVOR_COST, FAVOR_LATENCY
    - SLAConstraint is frozen dataclass with max_latency_ms, min_capability_score, required_features
    - BudgetConstraint is frozen dataclass with max_cost_usd, remaining_budget_usd, tenant_id
    - RoutingDecision is frozen dataclass with model, fallback_used, candidates_considered, reason
    - CostAwareRouterProtocol is a runtime_checkable Protocol with select_model() and report_outcome()
    - ModelSelectionError stores sla and budget on the instance
    - AllProvidersUnavailableError, InvalidSignatureError, DelegationDepthExceededError, UCANVerificationError, CapabilityDeniedError are all importable
  </behavior>
  <action>
Create src/orchestra/routing/types.py — this file is contracts only, no logic:

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
    max_latency_ms: float | None = None
    min_capability_score: int | None = None
    required_features: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class BudgetConstraint:
    """Per-request budget constraints."""
    max_cost_usd: float | None = None
    remaining_budget_usd: float | None = None
    tenant_id: str | None = None


@dataclass(frozen=True)
class RoutingDecision:
    """Result of model selection with audit trail."""
    model: Any                                        # ModelOption
    fallback_used: SelectionFallback | None = None    # Non-None if constraint was relaxed
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

Extend src/orchestra/core/errors.py — append the following sections after the existing error classes. Read the file first to find OrchestraError and the end of the file, then append:

```python
# --- Routing Errors ---
class RoutingError(OrchestraError):
    """Base for routing/model-selection errors."""


class ModelSelectionError(RoutingError):
    """No model satisfies both SLA and budget constraints (DD-1: raised by FAIL_FAST)."""
    def __init__(self, message: str, sla: Any = None, budget: Any = None) -> None:
        super().__init__(message)
        self.sla = sla
        self.budget = budget


class AllProvidersUnavailableError(RoutingError):
    """All providers in failover chain failed or are circuit-broken (DD-6)."""


# --- Identity Errors ---
class IdentityError(OrchestraError):
    """Base for agent identity errors."""


class InvalidSignatureError(IdentityError):
    """Agent Card or message signature verification failed (DD-3)."""


class DelegationDepthExceededError(IdentityError):
    """Delegation chain exceeds max_depth (DD-5: default max_depth=3)."""


# --- Authorization Errors ---
class AuthorizationError(OrchestraError):
    """Base for capability/authorization errors."""


class UCANVerificationError(AuthorizationError):
    """UCAN token is expired, has invalid audience, or bad signature (DD-9)."""


class CapabilityDeniedError(AuthorizationError):
    """UCAN does not grant the required capability (DD-4)."""


class BudgetExceededError(OrchestraError):
    """Tenant budget limit would be exceeded (DD-2: raised by pessimistic locking)."""
    def __init__(self, message: str, tenant_id: str = "", remaining_usd: float = 0.0) -> None:
        super().__init__(message)
        self.tenant_id = tenant_id
        self.remaining_usd = remaining_usd
```

Update src/orchestra/core/__init__.py to re-export the new error types. Read the file first, then add the new names to the existing __all__ or import block.
  </action>
  <verify>
    <automated>python -c "from orchestra.routing.types import SelectionFallback, SLAConstraint, BudgetConstraint, RoutingDecision, CostAwareRouterProtocol; print('routing types OK')" &amp;&amp; python -c "from orchestra.core.errors import ModelSelectionError, AllProvidersUnavailableError, InvalidSignatureError, UCANVerificationError, CapabilityDeniedError, DelegationDepthExceededError, BudgetExceededError; print('errors OK')"</automated>
  </verify>
  <done>All routing types and error types importable. No implementation logic in types.py — contracts only. Both import checks print OK.</done>
</task>

</tasks>

<verification>
python -c "
from orchestra.routing.types import SelectionFallback, SLAConstraint, BudgetConstraint, RoutingDecision, CostAwareRouterProtocol
from orchestra.core.errors import ModelSelectionError, AllProvidersUnavailableError, InvalidSignatureError, UCANVerificationError, CapabilityDeniedError, DelegationDepthExceededError, BudgetExceededError
assert SelectionFallback.FAIL_FAST.value == 'fail_fast'
assert SelectionFallback.FAVOR_COST.value == 'favor_cost'
assert SelectionFallback.FAVOR_LATENCY.value == 'favor_latency'
e = ModelSelectionError('test', sla='x', budget='y')
assert e.sla == 'x'
print('A1 verification passed')
"
</verification>

<success_criteria>
- src/orchestra/routing/types.py exists with SelectionFallback, SLAConstraint, BudgetConstraint, RoutingDecision, CostAwareRouterProtocol
- src/orchestra/core/errors.py contains RoutingError, IdentityError, AuthorizationError hierarchies
- BudgetExceededError, ModelSelectionError, AllProvidersUnavailableError all import cleanly
- No existing tests broken (run: pytest tests/unit/ -x -q --ignore=tests/unit/test_cost_router.py --ignore=tests/unit/test_provider_failover.py)
</success_criteria>

<output>
After completion, create .planning/phases/04-enterprise-scale/04-wave2-A1-SUMMARY.md
</output>
