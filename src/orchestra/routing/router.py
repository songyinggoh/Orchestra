"""Cost-aware routing for multi-model orchestration.

Provides protocols and implementations for selecting the optimal LLM provider
based on cost, historical performance (Thompson Sampling), and task complexity.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import numpy as np
import structlog

from orchestra.core.errors import ModelSelectionError
from orchestra.routing.types import (
    BudgetConstraint,
    RoutingDecision,
    SelectionFallback,
    SLAConstraint,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ModelOption:
    """A candidate model for routing.

    Attributes:
        model_name: Identifier for the model (e.g., "gpt-4o").
        provider_name: Identifier for the provider (e.g., "openai").
        input_cost_1k: Cost per 1k input tokens.
        output_cost_1k: Cost per 1k output tokens.
        latency_score: Qualitative latency score (1-5, 1=fastest).
        capability_score: Qualitative capability score (1-5, 5=smartest).
        features: Set of supported features (e.g., {"tool_calling", "vision"}).
    """

    model_name: str
    provider_name: str
    input_cost_1k: float = 0.0
    output_cost_1k: float = 0.0
    latency_score: int = 3
    capability_score: int = 3
    features: set[str] = field(default_factory=set)


@runtime_checkable
class RouterProtocol(Protocol):
    """Protocol for model selection strategies."""

    async def select_model(
        self,
        options: list[ModelOption],
        task_description: str = "",
        estimated_tokens: int = 500,
        sla: SLAConstraint | None = None,
        budget: BudgetConstraint | None = None,
        fallback: SelectionFallback = SelectionFallback.FAIL_FAST,
        **kwargs: Any,
    ) -> RoutingDecision | ModelOption:
        """Select the best model from the available options."""
        ...

    def report_outcome(
        self,
        model_name: str,
        provider_name: str,
        success: bool,
        latency_ms: float | None = None,
        actual_cost_usd: float | None = None,
    ) -> None:
        """Update historical performance data for a model/provider pair."""
        ...


class ThompsonModelSelector:
    """Multi-armed bandit selector using Thompson Sampling with Beta priors.

    Balances exploration (trying new/uncertain models) with exploitation
    (using proven high-performers) to optimize for success rate.
    """

    def __init__(self, alpha_init: float = 1.0, beta_init: float = 1.0) -> None:
        """Initialize priors.

        Args:
            alpha_init: Initial successful observations (default 1.0).
            beta_init: Initial failed observations (default 1.0).
        """
        # (model, provider) -> [alpha, beta]
        self._stats: dict[tuple[str, str], list[float]] = {}
        self._alpha_init = alpha_init
        self._beta_init = beta_init

    def select(self, options: list[ModelOption]) -> ModelOption:
        """Select the model with the highest sampled success probability."""
        if not options:
            raise ValueError("No model options provided to ThompsonModelSelector")

        samples = []
        for opt in options:
            key = (opt.model_name, opt.provider_name)
            if key not in self._stats:
                self._stats[key] = [self._alpha_init, self._beta_init]

            alpha, beta = self._stats[key]
            # Sample from Beta distribution
            sample = np.random.beta(alpha, beta)
            samples.append((sample, opt))

        # Pick the option with the highest sampled probability
        best_sample, best_option = max(samples, key=lambda x: x[0])
        logger.debug(
            "thompson_sample_selected",
            model=best_option.model_name,
            provider=best_option.provider_name,
            sample_prob=f"{best_sample:.4f}",
        )
        return best_option

    def update(self, model_name: str, provider_name: str, success: bool) -> None:
        """Update Beta distribution parameters for the chosen model."""
        key = (model_name, provider_name)
        if key not in self._stats:
            self._stats[key] = [self._alpha_init, self._beta_init]

        if success:
            self._stats[key][0] += 1.0
        else:
            self._stats[key][1] += 1.0


class CostAwareRouter:
    """Router that balances cost, capabilities, and performance.

    Uses Thompson Sampling for performance and supports SLA and budget constraints.
    """

    def __init__(
        self,
        selector: ThompsonModelSelector | None = None,
        cost_weight: float = 0.5,
        capability_weight: float = 0.5,
    ) -> None:
        """Initialize the router.

        Args:
            selector: ThompsonModelSelector for performance-based selection.
            cost_weight: Importance of cost (0.0 to 1.0).
            capability_weight: Importance of capability (0.0 to 1.0).
        """
        self._selector = selector or ThompsonModelSelector()
        self._cost_weight = cost_weight
        self._capability_weight = capability_weight

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
        """Select a model by filtering on cost/capability then sampling performance."""
        if not options:
            raise ValueError("No options provided to CostAwareRouter")

        candidates = list(options)
        fallback_used = None
        reason = "Direct selection"

        # 1. Filter by SLA
        if sla:
            candidates = self._filter_by_sla(candidates, sla)

        # 2. Filter by Budget
        if budget:
            candidates = self._filter_by_budget(candidates, budget, estimated_tokens)

        # 3. Handle empty candidates based on fallback strategy (DD-1)
        if not candidates:
            if fallback == SelectionFallback.FAIL_FAST:
                raise ModelSelectionError(
                    "No models satisfy SLA and budget constraints",
                    sla=sla,
                    budget=budget,
                )
            elif fallback == SelectionFallback.FAVOR_COST:
                # Relax SLA, pick cheapest within budget
                candidates = options
                if budget:
                    candidates = self._filter_by_budget(candidates, budget, estimated_tokens)
                if not candidates:
                    candidates = [min(options, key=lambda x: x.input_cost_1k)]
                else:
                    candidates = [min(candidates, key=lambda x: x.input_cost_1k)]
                fallback_used = SelectionFallback.FAVOR_COST
                reason = "SLA relaxed to favor cost"
            elif fallback == SelectionFallback.FAVOR_LATENCY:
                # Relax budget (1.5x), pick fastest
                candidates = options
                if sla:
                    candidates = self._filter_by_sla(candidates, sla)

                # Apply relaxed budget
                if budget:
                    relaxed_budget = BudgetConstraint(
                        max_cost_usd=(budget.max_cost_usd * 1.5 if budget.max_cost_usd else None),
                        remaining_budget_usd=budget.remaining_budget_usd,
                        tenant_id=budget.tenant_id,
                    )
                    candidates = self._filter_by_budget(
                        candidates, relaxed_budget, estimated_tokens
                    )

                if not candidates:
                    candidates = [min(options, key=lambda x: x.latency_score)]
                else:
                    candidates = [min(candidates, key=lambda x: x.latency_score)]
                fallback_used = SelectionFallback.FAVOR_LATENCY
                reason = "Budget relaxed to favor latency"

        # 4. Use Thompson Sampling to pick from the remaining candidates
        selected = self._selector.select(candidates)
        return RoutingDecision(
            model=selected,
            fallback_used=fallback_used,
            candidates_considered=len(options),
            reason=reason,
        )

    def _filter_by_sla(self, options: list[ModelOption], sla: SLAConstraint) -> list[ModelOption]:
        filtered = options
        if sla.min_capability_score is not None:
            filtered = [o for o in filtered if o.capability_score >= sla.min_capability_score]

        # Note: latency_score (1=fastest, 5=slowest) is used as a proxy for max_latency_ms
        # In a real system, we'd map ms to score or vice versa.
        if sla.max_latency_ms is not None:
            # Simple heuristic: max_latency_ms < 500ms -> score 1, < 1000ms -> score 2, etc.
            max_score = 5
            if sla.max_latency_ms < 500:
                max_score = 1
            elif sla.max_latency_ms < 1000:
                max_score = 2
            elif sla.max_latency_ms < 2000:
                max_score = 3
            elif sla.max_latency_ms < 5000:
                max_score = 4
            filtered = [o for o in filtered if o.latency_score <= max_score]

        if sla.required_features:
            filtered = [o for o in filtered if sla.required_features.issubset(o.features)]

        return filtered

    def _filter_by_budget(
        self, options: list[ModelOption], budget: BudgetConstraint, estimated_tokens: int
    ) -> list[ModelOption]:
        filtered = []
        for opt in options:
            est_cost = (estimated_tokens / 1000) * (opt.input_cost_1k + opt.output_cost_1k)

            if budget.max_cost_usd is not None and est_cost > budget.max_cost_usd:
                continue
            if budget.remaining_budget_usd is not None and est_cost > budget.remaining_budget_usd:
                continue
            filtered.append(opt)
        return filtered

    def report_outcome(
        self,
        model_name: str,
        provider_name: str,
        success: bool,
        latency_ms: float | None = None,
        actual_cost_usd: float | None = None,
    ) -> None:
        """Update performance stats and log cost."""
        self._selector.update(model_name, provider_name, success)
        if actual_cost_usd is not None:
            logger.debug("routing_actual_cost", model=model_name, cost=actual_cost_usd)


class SimpleHeuristicRouter:
    """Baseline router using fixed rules and random choice among tiers."""

    async def select_model(
        self,
        options: list[ModelOption],
        task_description: str = "",
        estimated_tokens: int = 500,
        **kwargs: Any,
    ) -> ModelOption:
        if not options:
            raise ValueError("No options provided")

        # Very small tasks -> cheapest model
        if estimated_tokens < 200:
            return min(options, key=lambda x: x.input_cost_1k)

        # Complex tasks -> smartest model
        if "complex" in task_description.lower():
            return max(options, key=lambda x: x.capability_score)

        # Default: random choice to maintain diversity
        return random.choice(options)

    def report_outcome(self, *args: Any, **kwargs: Any) -> None:
        pass  # Stateless
