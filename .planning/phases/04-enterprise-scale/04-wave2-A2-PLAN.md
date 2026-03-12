---
phase: 04-enterprise-scale
plan: wave2-A2
type: execute
wave: 2
depends_on: [wave2-A1]
files_modified:
  - src/orchestra/routing/router.py
  - src/orchestra/routing/__init__.py
  - tests/unit/test_cost_router.py
autonomous: true
requirements: [T-4.4]
must_haves:
  truths:
    - "CostAwareRouter.select_model() accepts SLAConstraint and BudgetConstraint and returns RoutingDecision"
    - "FAIL_FAST raises ModelSelectionError when no model satisfies both SLA and budget (DD-1)"
    - "FAVOR_COST relaxes SLA and picks cheapest model within budget (DD-1)"
    - "FAVOR_LATENCY allows up to 1.5x max_cost_usd and picks fastest model (DD-1)"
    - "Cost reduction of 30%+ achieved on mixed workloads via Thompson Sampling + budget filtering"
  artifacts:
    - path: "src/orchestra/routing/router.py"
      provides: "Rewritten CostAwareRouter with SelectionFallback, SLA filtering, budget filtering, Thompson Sampling"
      min_lines: 120
    - path: "tests/unit/test_cost_router.py"
      provides: "8 tests covering all SelectionFallback modes, Thompson sampling, backward compat"
      min_lines: 100
  key_links:
    - from: "src/orchestra/routing/router.py"
      to: "src/orchestra/routing/types.py"
      via: "from orchestra.routing.types import SelectionFallback, SLAConstraint, BudgetConstraint, RoutingDecision"
      pattern: "from orchestra\\.routing\\.types import"
    - from: "src/orchestra/routing/router.py"
      to: "src/orchestra/core/errors.py"
      via: "from orchestra.core.errors import ModelSelectionError"
      pattern: "ModelSelectionError"
---

<objective>
Rewrite CostAwareRouter to enforce SLA and budget constraints with the DD-1 SelectionFallback behavior.

Purpose: Implements the intelligence layer of T-4.4. The router becomes the central decision-maker for cost reduction — it must filter models by SLA, then by budget, apply Thompson Sampling on survivors, and handle conflicts via the configured fallback mode.
Output: Rewritten router.py, new test_cost_router.py with 8 tests passing.
</objective>

<execution_context>
@C:/Users/user/.claude/get-shit-done/workflows/execute-plan.md
@C:/Users/user/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/04-enterprise-scale/PLAN.md
@.planning/phases/04-enterprise-scale/WAVE2-DESIGN-DECISIONS.md

<interfaces>
<!-- From src/orchestra/routing/types.py (created in A1) -->
```python
class SelectionFallback(enum.Enum):
    FAIL_FAST = "fail_fast"
    FAVOR_COST = "favor_cost"
    FAVOR_LATENCY = "favor_latency"

@dataclass(frozen=True)
class SLAConstraint:
    max_latency_ms: float | None = None
    min_capability_score: int | None = None
    required_features: frozenset[str] = field(default_factory=frozenset)

@dataclass(frozen=True)
class BudgetConstraint:
    max_cost_usd: float | None = None
    remaining_budget_usd: float | None = None
    tenant_id: str | None = None

@dataclass(frozen=True)
class RoutingDecision:
    model: Any
    fallback_used: SelectionFallback | None = None
    candidates_considered: int = 0
    reason: str = ""
```

<!-- From src/orchestra/core/errors.py (extended in A1) -->
```python
class ModelSelectionError(RoutingError):
    def __init__(self, message: str, sla: Any = None, budget: Any = None) -> None: ...
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true" id="A2.1" name="Rewrite CostAwareRouter with SLA/budget filtering and SelectionFallback">
  <files>src/orchestra/routing/router.py, src/orchestra/routing/__init__.py, tests/unit/test_cost_router.py</files>
  <behavior>
    - test_select_model_within_budget_and_sla: 3 models, one fits both SLA and budget — that model is selected
    - test_fail_fast_raises_on_conflict: No model fits both SLA AND budget — ModelSelectionError raised
    - test_favor_cost_relaxes_sla: FAVOR_COST picks cheapest model ignoring SLA filter
    - test_favor_latency_relaxes_budget: FAVOR_LATENCY allows 1.5x max_cost_usd, picks fastest
    - test_thompson_sampling_exploration: With uniform priors and 100 calls, all models selected at least once
    - test_report_outcome_updates_posteriors: After 10 successes for model A, model A's alpha increases
    - test_empty_options_raises: ValueError on empty options list
    - test_backward_compatible_no_constraints: Calling without sla/budget/fallback still works
  </behavior>
  <action>
Read src/orchestra/routing/router.py first to understand the existing ModelOption, ThompsonModelSelector, and CostAwareRouter structure.

REWRITE router.py keeping ModelOption and ThompsonModelSelector intact, fundamentally reworking CostAwareRouter:

1. Add imports from the new type contracts:
```python
from orchestra.routing.types import (
    SelectionFallback, SLAConstraint, BudgetConstraint, RoutingDecision, CostAwareRouterProtocol
)
from orchestra.core.errors import ModelSelectionError
```

2. New CostAwareRouter.select_model() signature:
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

3. Selection pipeline (in order):
   a. Validate: raise ValueError if options is empty.
   b. Filter by SLA — if sla is not None:
      - Remove models where model.latency_score > sla.max_latency_ms (if max_latency_ms set; use latency_score as ms proxy)
      - Remove models where model.capability_score < sla.min_capability_score (if set)
      - Remove models missing required_features (check model.features set if it exists, else skip)
   c. Filter by budget — if budget is not None:
      - Estimate per-request cost = (estimated_tokens / 1000) * (model.input_cost_per_1k + model.output_cost_per_1k)
      - Remove models where estimated cost > budget.max_cost_usd (if max_cost_usd set)
      - Remove models where estimated cost > budget.remaining_budget_usd (if remaining_budget_usd set)
   d. If candidates empty, apply fallback per DD-1:
      - FAIL_FAST: raise ModelSelectionError(f"No model satisfies constraints: sla={sla}, budget={budget}", sla=sla, budget=budget)
      - FAVOR_COST: restart from full options list, apply only budget filter, take cheapest by estimated cost
      - FAVOR_LATENCY: restart from full options list, apply only SLA filter, allow up to 1.5x max_cost_usd
   e. Thompson Sampling on surviving candidates.
   f. Return RoutingDecision(model=selected, fallback_used=fallback_applied_or_None, candidates_considered=len(candidates), reason=description_string)

4. report_outcome() extended to also accept actual_cost_usd (log at DEBUG level, no other action yet).

5. Keep SimpleHeuristicRouter and ThompsonModelSelector unchanged for backward compatibility.

6. Update src/orchestra/routing/__init__.py to export CostAwareRouter, SimpleHeuristicRouter, ThompsonModelSelector, ModelOption, plus all types from routing.types:
   from orchestra.routing.types import SelectionFallback, SLAConstraint, BudgetConstraint, RoutingDecision, CostAwareRouterProtocol

Write tests to tests/unit/test_cost_router.py covering all 8 behaviors listed above. Use pytest-asyncio for async tests. Create ModelOption instances with realistic cost values (e.g., gpt-4o at $0.01/$0.03, gpt-4o-mini at $0.001/$0.002).
  </action>
  <verify>
    <automated>pytest tests/unit/test_cost_router.py -x -v</automated>
  </verify>
  <done>CostAwareRouter selects models respecting SLA + budget constraints with FAIL_FAST default. FAVOR_COST and FAVOR_LATENCY fallbacks work correctly. All 8 tests pass. Existing routing tests still pass.</done>
</task>

</tasks>

<verification>
pytest tests/unit/test_cost_router.py -v
pytest tests/unit/ -x -q -k "router" 2>/dev/null || true
</verification>

<success_criteria>
- All 8 test_cost_router.py tests pass
- FAIL_FAST raises ModelSelectionError with sla/budget attributes
- FAVOR_COST picks cheapest without SLA filter
- FAVOR_LATENCY allows 1.5x budget overage
- Backward compatible: calling without sla/budget/fallback args still works
- ModelOption and ThompsonModelSelector unchanged (no regressions)
</success_criteria>

<output>
After completion, create .planning/phases/04-enterprise-scale/04-wave2-A2-SUMMARY.md
</output>
