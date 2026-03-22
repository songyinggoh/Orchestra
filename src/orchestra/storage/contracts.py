"""ESAA-style boundary contract validation (opt-in).

Validates agent outputs against JSON Schema before they become state.
Contracts are opt-in -- when no contract is registered for an agent,
validation is skipped.
"""

from __future__ import annotations

import warnings
from typing import Any

from pydantic import BaseModel


class BoundaryContract:
    """Validates data against a JSON Schema."""

    def __init__(self, schema: dict[str, Any], name: str = "") -> None:
        self._schema = schema
        self._name = name or "unnamed"

    @property
    def name(self) -> str:
        return self._name

    @property
    def schema(self) -> dict[str, Any]:
        return dict(self._schema)

    def validate(self, data: dict[str, Any]) -> list[str]:
        """Validate data against the schema. Returns list of error strings (empty = valid).

        Uses jsonschema if available, falls back to no-op (pass-through).
        """
        try:
            from jsonschema import ValidationError
            from jsonschema import validate as js_validate

            try:
                js_validate(instance=data, schema=self._schema)
                return []
            except ValidationError as e:
                return [e.message]
        except ImportError:
            warnings.warn(
                "jsonschema is not installed; boundary contract validation is disabled. "
                "Install it with: pip install jsonschema",
                RuntimeWarning,
                stacklevel=2,
            )
            return []

    @classmethod
    def from_pydantic(cls, model: type[BaseModel], name: str = "") -> BoundaryContract:
        """Create a contract from a Pydantic model's JSON Schema."""
        schema = model.model_json_schema()
        return cls(schema=schema, name=name or model.__name__)


class ContractRegistry:
    """Maps agent names to boundary contracts. Empty by default (opt-in)."""

    def __init__(self) -> None:
        self._contracts: dict[str, BoundaryContract] = {}

    def register(self, agent_name: str, contract: BoundaryContract) -> None:
        """Register a boundary contract for an agent."""
        self._contracts[agent_name] = contract

    def has_contract(self, agent_name: str) -> bool:
        """Check if an agent has a registered contract."""
        return agent_name in self._contracts

    def validate(self, agent_name: str, data: dict[str, Any]) -> list[str]:
        """Validate data against the agent's contract. Returns errors or empty list.

        If no contract is registered, returns empty list (pass-through).
        """
        contract = self._contracts.get(agent_name)
        if contract is None:
            return []
        return contract.validate(data)

    def get(self, agent_name: str) -> BoundaryContract | None:
        """Get the contract for an agent, or None."""
        return self._contracts.get(agent_name)
