"""ExecutionContext: runtime context injected into agents.

Provides agents with access to state, provider, tools, and run metadata
without making them hold direct references.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecutionContext:
    """Runtime context passed to agents during execution.

    Phase 1 provides: run metadata, state, provider, tools.
    Phase 2+ adds: memory, identity, telemetry, secrets.

    Thread / task safety
    --------------------
    ``state``, ``loop_counters``, ``node_execution_order``, and
    ``turn_number`` are mutated by the execution engine.  When parallel
    edges fan-out via ``asyncio.gather`` all branches share the same
    ``ExecutionContext`` instance, so unprotected mutations create a real
    data race.

    Use the ``mutate()`` async context manager whenever you need to write
    to any of those four fields::

        async with ctx.mutate():
            ctx.turn_number += 1
            ctx.node_execution_order.append(node_id)

    The lock is an ``asyncio.Lock`` (cooperative, not OS-thread-safe).
    It is excluded from ``__init__``, ``__repr__``, ``__eq__``, and
    comparisons so that existing callers require no changes.
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

    # Concurrency lock — excluded from __init__ / comparisons / repr.
    # init=False so no caller change is required; repr=False / compare=False
    # so it does not interfere with equality checks or debug output.
    _lock: asyncio.Lock = field(
        default_factory=asyncio.Lock,
        init=False,
        repr=False,
        compare=False,
    )

    # Event bus for workflow event emission (Phase 2+)
    event_bus: Any = None

    # Wave 2: Cost Intelligence (Track A)
    tenant_id: str | None = None

    # Wave 2: Agent Identity (Track B)
    identity: Any = None  # AgentIdentity instance
    ucan_token: str | None = None  # Current UCAN JWT string
    delegation_context: Any = None  # DelegationContext instance

    # Wave 3: Memory & Security
    memory_manager: Any = None  # MemoryManager or TieredMemoryManager
    restricted_mode: bool = False  # Set by Attenuator on injection detection

    # Time-travel / Replay data
    replay_events: list[Any] = field(default_factory=list)

    @property
    def replay_mode(self) -> bool:
        """Return True if we are in historical replay mode."""
        return len(self.replay_events) > 0

    def get_config(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        return self.config.get(key, default)

    @asynccontextmanager
    async def mutate(self) -> AsyncIterator[None]:
        """Async context manager that serialises mutations to shared fields.

        Protects concurrent writes to ``state``, ``loop_counters``,
        ``node_execution_order``, and ``turn_number`` when parallel graph
        edges share the same ``ExecutionContext`` instance.

        Usage::

            async with ctx.mutate():
                ctx.turn_number += 1
                ctx.node_execution_order.append(node_id)
                ctx.state = new_state_dict
        """
        async with self._lock:
            yield
