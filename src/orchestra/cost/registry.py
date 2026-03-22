"""ModelCostRegistry: resolves model pricing and calculates costs.

Loads bundled pricing from _default_prices.json, supports exact and
prefix matching, and allows runtime overrides for custom pricing.
"""

from __future__ import annotations

import json
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

_PRICES_FILE = Path(__file__).parent / "_default_prices.json"


class ModelCostRegistry:
    """Registry of model pricing data.

    Resolves pricing by exact match first, then by longest prefix match.
    Unknown models return zero cost with a structlog warning (never crash).
    """

    def __init__(self, prices: dict[str, dict[str, float]] | None = None) -> None:
        """Initialize with bundled or custom prices.

        Args:
            prices: Optional dict of model -> {input_cost_per_token, output_cost_per_token}.
                    If None, loads from bundled _default_prices.json.
        """
        if prices is not None:
            self._prices: dict[str, dict[str, float]] = dict(prices)
        else:
            self._prices = self._load_default_prices()

    @staticmethod
    def _load_default_prices() -> dict[str, dict[str, float]]:
        """Load pricing data from the bundled JSON file."""
        try:
            with open(_PRICES_FILE) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning("default_prices_load_failed", error=str(e))
            return {}

    def get_pricing(self, model: str) -> dict[str, float] | None:
        """Look up pricing for a model by exact match then prefix match.

        Returns:
            Dict with input_cost_per_token and output_cost_per_token, or None.
        """
        # 1. Exact match
        if model in self._prices:
            return self._prices[model]

        # 2. Prefix match: find the longest registered model name
        #    that is a prefix of the requested model.
        #    e.g., "gpt-4" matches "gpt-4-turbo-2024-01-25"
        best_match: str | None = None
        best_len = 0
        for registered_model in self._prices:
            if model.startswith(registered_model) and len(registered_model) > best_len:
                best_match = registered_model
                best_len = len(registered_model)

        if best_match is not None:
            return self._prices[best_match]

        return None

    def calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost in USD for a model call.

        Args:
            model: Model name (exact or prefix-matched).
            input_tokens: Number of input/prompt tokens.
            output_tokens: Number of output/completion tokens.

        Returns:
            Cost in USD. Returns 0.0 for unknown models (with warning).
        """
        pricing = self.get_pricing(model)
        if pricing is None:
            logger.warning(
                "unknown_model_zero_cost",
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            return 0.0

        input_cost = input_tokens * pricing.get("input_cost_per_token", 0.0)
        output_cost = output_tokens * pricing.get("output_cost_per_token", 0.0)
        return input_cost + output_cost

    def set_pricing(
        self,
        model: str,
        input_cost_per_token: float,
        output_cost_per_token: float,
    ) -> None:
        """Set or override pricing for a model at runtime.

        Args:
            model: Model name.
            input_cost_per_token: Cost per input token in USD.
            output_cost_per_token: Cost per output token in USD.
        """
        self._prices[model] = {
            "input_cost_per_token": input_cost_per_token,
            "output_cost_per_token": output_cost_per_token,
        }

    @property
    def models(self) -> list[str]:
        """List all registered model names."""
        return list(self._prices.keys())
