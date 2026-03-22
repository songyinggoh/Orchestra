"""Handoff Protocol: Swarm-style agent-to-agent handoffs.

HandoffEdge is a first-class edge type for transferring execution
from one agent to another with optional context distillation.

Usage:
    graph.add_handoff("triage", "specialist", condition=needs_expert)
    graph.add_handoff("researcher", "writer")  # Unconditional
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

# EdgeCondition is any callable that takes state dict and returns a bool or route.
EdgeCondition = "Callable[[dict[str, Any]], Any]"


@dataclass(frozen=True)
class HandoffPayload:
    """Context transferred during a handoff.

    Carries conversation history and metadata from the source agent
    to the target agent. The ``distilled`` flag records whether the
    history was compressed before transfer.
    """

    from_agent: str
    to_agent: str
    reason: str
    conversation_history: tuple[Any, ...]  # immutable; stores Message objects
    metadata: tuple[tuple[str, Any], ...]  # immutable; key-value pairs
    distilled: bool  # Whether context was distilled

    @classmethod
    def create(
        cls,
        from_agent: str,
        to_agent: str,
        reason: str,
        conversation_history: list[Any],
        metadata: dict[str, Any] | None = None,
        distilled: bool = False,
    ) -> HandoffPayload:
        """Convenience constructor from mutable Python types."""
        return cls(
            from_agent=from_agent,
            to_agent=to_agent,
            reason=reason,
            conversation_history=tuple(conversation_history),
            metadata=tuple((k, v) for k, v in (metadata or {}).items()),
            distilled=distilled,
        )

    def metadata_dict(self) -> dict[str, Any]:
        """Return metadata as a plain dict."""
        return dict(self.metadata)

    def history_list(self) -> list[Any]:
        """Return conversation history as a plain list."""
        return list(self.conversation_history)


@dataclass(frozen=True)
class HandoffEdge:
    """Edge type for agent handoffs.

    Created via WorkflowGraph.add_handoff(). Transfers execution
    context from one agent to another with optional context distillation.

    Attributes:
        source: Source agent node ID.
        target: Target agent node ID.
        condition: Optional callable(state) -> bool that gates the handoff.
        distill: When True (default), apply context distillation.
    """

    source: str
    target: str
    condition: Any = None  # EdgeCondition | None
    distill: bool = True
