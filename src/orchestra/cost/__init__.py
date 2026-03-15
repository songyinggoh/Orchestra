"""Cost management module for Orchestra framework.

Provides model pricing lookup, per-run cost aggregation via EventBus,
and budget enforcement with soft/hard limits.
"""

from orchestra.cost.aggregator import CostAggregator, RunCostSummary
from orchestra.cost.budget import BudgetCheckResult, BudgetPolicy
from orchestra.cost.registry import ModelCostRegistry
from orchestra.cost.persistent_budget import (
    PersistentBudgetStore,
    TenantBudgetManager,
    BudgetExceededError,
)
from orchestra.cost.tenant import (
    BudgetConfig,
    BudgetState,
    BudgetStatus,
    Tenant,
)

__all__ = [
    "CostAggregator",
    "BudgetCheckResult",
    "BudgetPolicy",
    "ModelCostRegistry",
    "RunCostSummary",
    "PersistentBudgetStore",
    "TenantBudgetManager",
    "BudgetExceededError",
    "BudgetConfig",
    "BudgetState",
    "BudgetStatus",
    "Tenant",
]
