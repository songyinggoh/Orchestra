"""Graph node types.

Nodes are the processing units in a workflow graph. Each node
wraps a callable (agent, function, or subgraph) and executes
it with the current workflow state.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from orchestra.core.types import AgentResult

NodeFunction = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class AgentNode:
    """A node that runs an Agent.

    The agent receives the current state and returns an AgentResult
    which is converted to a state update via the merge strategy.
    """

    agent: Any
    output_key: str | None = None
    map_output: bool = False
    input_mapper: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    output_mapper: Callable[[AgentResult], dict[str, Any]] | None = None
    interrupt_before: bool = False
    interrupt_after: bool = False


@dataclass(frozen=True)
class FunctionNode:
    """A node that runs a plain async function.

    The function takes the full state dict and returns a partial
    state update dict.
    """

    func: NodeFunction
    name: str = ""
    interrupt_before: bool = False
    interrupt_after: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            object.__setattr__(self, "name", self.func.__name__)

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        import inspect

        result = self.func(state)
        if inspect.isawaitable(result):
            return await result
        return result


@dataclass(frozen=True)
class SubgraphNode:
    """A node that runs a compiled subgraph."""

    graph: Any
    input_mapper: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    output_mapper: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    interrupt_before: bool = False
    interrupt_after: bool = False

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        input_state = self.input_mapper(state) if self.input_mapper else state
        result = await self.graph.run(input_state)
        return self.output_mapper(result) if self.output_mapper else result


GraphNode = AgentNode | FunctionNode | SubgraphNode
