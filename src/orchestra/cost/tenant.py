"""Tenant and Budget data models.

Defines the structure for multi-tenant isolation and per-tenant/per-user
budgeting in Orchestra.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any


class BudgetStatus(Enum):
    """Current status of a tenant's budget."""

    ACTIVE = auto()
    WARNING = auto()
    EXCEEDED = auto()
    LOCKED = auto()


@dataclass
class Tenant:
    """Represents a billing/isolation unit (organization, team, or user).

    Attributes:
        tenant_id: Unique identifier for the tenant.
        name: Human-readable name.
        parent_id: Optional ID of the parent tenant for hierarchical budgets.
        metadata: Custom attributes (e.g. tier, contact).
    """

    tenant_id: str
    name: str
    parent_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BudgetConfig:
    """Configuration for a tenant's budget limits.

    Attributes:
        limit_usd: Total USD budget allowed.
        warning_threshold: Fraction (0.0 to 1.0) where warnings trigger.
        is_hard_limit: If True, block requests immediately upon exceeding.
        reset_period: 'monthly', 'daily', or 'none'.
    """

    limit_usd: float
    warning_threshold: float = 0.8
    is_hard_limit: bool = True
    reset_period: str = "monthly"


@dataclass
class BudgetState:
    """Current usage state of a budget.

    Attributes:
        tenant_id: The tenant this state belongs to.
        balance_usd: Current spent amount in USD.
        last_reset: Timestamp of the last budget reset (UTC).
        status: Calculated BudgetStatus.
    """

    tenant_id: str
    balance_usd: float = 0.0
    last_reset: datetime = field(default_factory=lambda: datetime.now(UTC))
    status: BudgetStatus = BudgetStatus.ACTIVE
