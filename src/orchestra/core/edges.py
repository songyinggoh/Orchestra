"""Graph edge types.

Edges define transitions between nodes:
- Edge: unconditional A -> B
- ConditionalEdge: A -> B|C|D based on state
- ParallelEdge: A -> [B, C, D] fan-out with join
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from orchestra.core.errors import GraphCompileError

EdgeCondition = Callable[[dict[str, Any]], Any]


def _coerce_path_key(value: Any) -> str | None:
    """Coerce a routing-function return value to a path_map lookup key.

    JSON-canonical scalars (str, bool, None, int, float) coerce to their
    JSON representation so that path_map can be authored cross-language.
    Returns None for any other type — the caller passes such values
    through unchanged (preserves "return END directly" patterns).
    """
    if isinstance(value, str):
        return value
    # bool must be checked before int because isinstance(True, int) is True.
    if isinstance(value, bool) or value is None:
        return json.dumps(value)
    if isinstance(value, (int, float)):
        return json.dumps(value)
    return None


@dataclass(frozen=True)
class Edge:
    """Unconditional edge: source always transitions to target."""

    source: str
    target: Any  # str or END sentinel


@dataclass(frozen=True)
class ConditionalEdge:
    """Conditional edge: routes based on a condition function.

    The condition receives state and returns the next node ID (or END).
    If path_map is provided, condition returns a key and path_map maps
    to node IDs.
    """

    source: str
    condition: EdgeCondition
    path_map: dict[str, Any] | None = None

    def resolve(self, state: dict[str, Any]) -> Any:
        result = self.condition(state)
        if self.path_map is not None:
            key = _coerce_path_key(result)
            if key is None:
                return result
            if key not in self.path_map:
                raise GraphCompileError(
                    f"Conditional edge returned {result!r} which is not in path_map.\n"
                    f"  Available keys: {list(self.path_map.keys())}\n"
                    f"  Fix: Return one of the available keys from your condition function, "
                    f"or add {key!r} to the path_map."
                )
            return self.path_map[key]
        return result


@dataclass(frozen=True)
class ParallelEdge:
    """Parallel edge: source fans out to multiple targets.

    All targets execute concurrently. Results are merged using
    state reducers before proceeding to join_node.
    """

    source: str
    targets: list[str]
    join_node: Any = None  # str or END sentinel


GraphEdge = Edge | ConditionalEdge | ParallelEdge
