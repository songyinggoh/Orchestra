"""BudgetPolicy: soft/hard limits for cost and token usage.

Provides pre-call budget checks. Soft limits trigger structlog warnings;
hard limits raise BudgetExceededError before the LLM call proceeds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from orchestra.core.errors import BudgetExceededError

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class BudgetCheckResult:
    """Result of a budget check.

    Attributes:
        allowed: Whether the call should proceed.
        soft_limit_hit: Whether a soft limit was exceeded (warning issued).
        hard_limit_hit: Whether a hard limit was exceeded (call blocked).
        reason: Human-readable explanation if blocked or warned.
        current_cost_usd: Current accumulated cost in USD.
        current_tokens: Current accumulated token count.
        suggested_model: If set, a cheaper model to downgrade to.
    """

    allowed: bool = True
    soft_limit_hit: bool = False
    hard_limit_hit: bool = False
    reason: str = ""
    current_cost_usd: float = 0.0
    current_tokens: int = 0
    suggested_model: str | None = None


class BudgetPolicy:
    """Budget enforcement with soft (warn) and hard (block) limits.

    Limits can be set in USD, total tokens, or both. When both are set,
    either limit being exceeded triggers the corresponding action.

    Attributes:
        soft_limit_usd: USD threshold that triggers a warning.
        hard_limit_usd: USD threshold that blocks the call.
        soft_limit_tokens: Token threshold that triggers a warning.
        hard_limit_tokens: Token threshold that blocks the call.
        downgrade_model: Optional model name to suggest when soft limit is hit.
    """

    def __init__(
        self,
        *,
        soft_limit_usd: float | None = None,
        hard_limit_usd: float | None = None,
        soft_limit_tokens: int | None = None,
        hard_limit_tokens: int | None = None,
        downgrade_model: str | None = None,
    ) -> None:
        self.soft_limit_usd = soft_limit_usd
        self.hard_limit_usd = hard_limit_usd
        self.soft_limit_tokens = soft_limit_tokens
        self.hard_limit_tokens = hard_limit_tokens
        self.downgrade_model = downgrade_model

    def check(
        self,
        current_cost_usd: float,
        current_tokens: int,
    ) -> BudgetCheckResult:
        """Check whether the current usage exceeds any limits.

        This should be called BEFORE making an LLM call. If the hard
        limit is exceeded, the caller should raise BudgetExceededError.
        If the soft limit is exceeded, the caller should log a warning
        but proceed.

        Args:
            current_cost_usd: Total accumulated cost so far.
            current_tokens: Total accumulated tokens so far.

        Returns:
            BudgetCheckResult with the check outcome.
        """
        soft_hit = False
        hard_hit = False
        reasons: list[str] = []
        suggested = None

        # Check hard limits first (they take priority)
        if self.hard_limit_usd is not None and current_cost_usd >= self.hard_limit_usd:
            hard_hit = True
            reasons.append(
                f"Hard USD limit exceeded: ${current_cost_usd:.4f} >= ${self.hard_limit_usd:.4f}"
            )

        if self.hard_limit_tokens is not None and current_tokens >= self.hard_limit_tokens:
            hard_hit = True
            reasons.append(
                f"Hard token limit exceeded: {current_tokens:,} >= {self.hard_limit_tokens:,}"
            )

        # Check soft limits (only relevant if hard limit not hit)
        if not hard_hit:
            if self.soft_limit_usd is not None and current_cost_usd >= self.soft_limit_usd:
                soft_hit = True
                reasons.append(
                    f"Soft USD limit exceeded: ${current_cost_usd:.4f} >= ${self.soft_limit_usd:.4f}"
                )
                if self.downgrade_model:
                    suggested = self.downgrade_model

            if self.soft_limit_tokens is not None and current_tokens >= self.soft_limit_tokens:
                soft_hit = True
                reasons.append(
                    f"Soft token limit exceeded: {current_tokens:,} >= {self.soft_limit_tokens:,}"
                )
                if self.downgrade_model:
                    suggested = self.downgrade_model

        reason = "; ".join(reasons) if reasons else ""

        if hard_hit:
            logger.error(
                "budget_hard_limit_exceeded",
                current_cost_usd=current_cost_usd,
                current_tokens=current_tokens,
                hard_limit_usd=self.hard_limit_usd,
                hard_limit_tokens=self.hard_limit_tokens,
                reason=reason,
            )
        elif soft_hit:
            logger.warning(
                "budget_soft_limit_exceeded",
                current_cost_usd=current_cost_usd,
                current_tokens=current_tokens,
                soft_limit_usd=self.soft_limit_usd,
                soft_limit_tokens=self.soft_limit_tokens,
                reason=reason,
                suggested_model=suggested,
            )

        return BudgetCheckResult(
            allowed=not hard_hit,
            soft_limit_hit=soft_hit,
            hard_limit_hit=hard_hit,
            reason=reason,
            current_cost_usd=current_cost_usd,
            current_tokens=current_tokens,
            suggested_model=suggested,
        )

    def enforce(
        self,
        current_cost_usd: float,
        current_tokens: int,
    ) -> BudgetCheckResult:
        """Check budget and raise BudgetExceededError if hard limit hit.

        Convenience method that calls check() and raises if not allowed.

        Args:
            current_cost_usd: Total accumulated cost so far.
            current_tokens: Total accumulated tokens so far.

        Returns:
            BudgetCheckResult (only returned if allowed).

        Raises:
            BudgetExceededError: If hard limit is exceeded.
        """
        result = self.check(current_cost_usd, current_tokens)
        if not result.allowed:
            raise BudgetExceededError(result.reason)
        return result
