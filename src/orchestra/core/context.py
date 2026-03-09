"""ExecutionContext: runtime context injected into agents.

Provides agents with access to state, provider, tools, and run metadata
without making them hold direct references.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecutionContext:
    """Runtime context passed to agents during execution.

    Phase 1 provides: run metadata, state, provider, tools.
    Phase 2+ adds: memory, identity, telemetry, secrets.
    """

    # Run metadata
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    thread_id: str = ""
    turn_number: int = 0
    node_id: str = ""

    # Current workflow state (read-only view for agents)
    state: dict[str, Any] = field(default_factory=dict)

    # Injected LLM provider (satisfies LLMProvider protocol)
    provider: Any = None

    # Tool registry
    tool_registry: Any = None

    # Configuration
    config: dict[str, Any] = field(default_factory=dict)

    # Per-run loop counters (scoped to each run() call)
    loop_counters: dict[str, int] = field(default_factory=dict)

    # Node execution order tracking
    node_execution_order: list[str] = field(default_factory=list)

    # Event bus for workflow event emission (Phase 2+)
    event_bus: Any = None

    # Time-travel / Replay data
    replay_events: list[Any] = field(default_factory=list)

    @property
    def replay_mode(self) -> bool:
        """Return True if we are in historical replay mode."""
        return len(self.replay_events) > 0

    def get_config(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        return self.config.get(key, default)
