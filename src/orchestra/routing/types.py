# src/orchestra/routing/types.py
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class SelectionFallback(enum.Enum):
    """How to handle SLA + Budget conflicts (DD-1: FAIL_FAST default)."""

    FAIL_FAST = "fail_fast"  # Raise ModelSelectionError immediately
    FAVOR_COST = "favor_cost"  # Relax SLA, pick cheapest within budget
    FAVOR_LATENCY = "favor_latency"  # Relax budget (1.5x), pick fastest


@dataclass(frozen=True)
class SLAConstraint:
    """Service-level constraints for model selection."""

    max_latency_ms: float | None = None  # P95 latency target
    min_capability_score: int | None = None  # Minimum capability (1-5)
    required_features: set[str] = field(default_factory=set)  # e.g., {"tool_calling", "vision"}


@dataclass(frozen=True)
class BudgetConstraint:
    """Per-request budget constraints."""

    max_cost_usd: float | None = None  # Max cost for this single request
    remaining_budget_usd: float | None = None  # Remaining tenant budget
    tenant_id: str | None = None


@dataclass(frozen=True)
class RoutingDecision:
    """Result of model selection with audit trail."""

    model: Any  # Selected model (ModelOption from router.py)
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
