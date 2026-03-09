"""EventBus, EventStore protocol, and in-memory implementation."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from orchestra.storage.events import (
    AnyEvent,
    CheckpointCreated,
    EventType,
    ExecutionCompleted,
    ExecutionStarted,
    StateUpdated,
    WorkflowEvent,
)


@dataclass
class RunSummary:
    """Summary of a workflow run for list_runs()."""

    run_id: str
    workflow_name: str = ""
    status: str = "running"
    started_at: str = ""
    completed_at: str | None = None
    event_count: int = 0


EventCallback = Callable[[WorkflowEvent], None] | Callable[[WorkflowEvent], Awaitable[None]]


class EventBus:
    """Async in-process event dispatcher with filtered subscriptions.

    Sequence numbers are assigned per run_id via next_sequence().
    Asyncio cooperative scheduling guarantees no concurrent access between
    awaits, making the counter safe without an explicit lock.
    """

    def __init__(self) -> None:
        self._subscribers: list[tuple[set[EventType] | None, EventCallback]] = []
        self._sequence_counters: dict[str, int] = {}

    def subscribe(
        self,
        callback: EventCallback,
        event_types: list[EventType] | None = None,
    ) -> tuple[set[EventType] | None, EventCallback]:
        """Subscribe to events. None = all events (wildcard).

        Returns an opaque handle that can be passed to unsubscribe().
        """
        type_set = set(event_types) if event_types else None
        entry = (type_set, callback)
        self._subscribers.append(entry)
        return entry

    def unsubscribe(self, handle: tuple[set[EventType] | None, EventCallback]) -> None:
        """Remove a previously registered subscriber.

        Accepts the handle returned by subscribe(). No-op if already removed.
        """
        try:
            self._subscribers.remove(handle)
        except ValueError:
            pass

    def next_sequence(self, run_id: str) -> int:
        """Return next monotonic sequence number for a run."""
        seq = self._sequence_counters.get(run_id, -1) + 1
        self._sequence_counters[run_id] = seq
        return seq

    async def emit(self, event: WorkflowEvent) -> None:
        """Dispatch event to matching subscribers. Async-safe."""
        for type_filter, callback in self._subscribers:
            if type_filter is not None and event.event_type not in type_filter:
                continue
            result = callback(event)
            if asyncio.iscoroutine(result):
                await result


@runtime_checkable
class EventStore(Protocol):
    """Protocol for event persistence backends."""

    async def append(self, event: WorkflowEvent) -> None: ...

    async def get_events(
        self,
        run_id: str,
        *,
        after_sequence: int = -1,
        event_types: list[EventType] | None = None,
    ) -> list[WorkflowEvent]: ...

    async def get_latest_checkpoint(self, run_id: str) -> CheckpointCreated | None: ...

    async def save_checkpoint(self, checkpoint: CheckpointCreated) -> None: ...

    async def list_runs(
        self, *, limit: int = 50, status: str | None = None
    ) -> list[RunSummary]: ...


class InMemoryEventStore:
    """Non-persistent EventStore for testing and development.

    Stores events in plain dicts keyed by run_id.
    Not suitable for production use.
    """

    def __init__(self) -> None:
        self._events: dict[str, list[WorkflowEvent]] = {}
        self._checkpoints: dict[str, list[CheckpointCreated]] = {}
        self._run_meta: dict[str, dict[str, Any]] = {}

    async def append(self, event: WorkflowEvent) -> None:
        """Append an event to the store."""
        self._events.setdefault(event.run_id, []).append(event)
        # Track run metadata from lifecycle events
        if isinstance(event, ExecutionStarted):
            self._run_meta[event.run_id] = {
                "workflow_name": event.workflow_name,
                "status": "running",
                "started_at": event.timestamp.isoformat(),
            }
        elif isinstance(event, ExecutionCompleted):
            meta = self._run_meta.setdefault(event.run_id, {})
            meta["status"] = "completed"
            meta["completed_at"] = event.timestamp.isoformat()

    async def get_events(
        self,
        run_id: str,
        *,
        after_sequence: int = -1,
        event_types: list[EventType] | None = None,
    ) -> list[WorkflowEvent]:
        """Retrieve events for a run, with optional filtering."""
        events = self._events.get(run_id, [])
        filtered = [e for e in events if e.sequence > after_sequence]
        if event_types:
            type_set = set(event_types)
            filtered = [e for e in filtered if e.event_type in type_set]
        return filtered

    async def get_latest_checkpoint(self, run_id: str) -> CheckpointCreated | None:
        """Get the most recent checkpoint for a run."""
        checkpoints = self._checkpoints.get(run_id, [])
        return checkpoints[-1] if checkpoints else None

    async def save_checkpoint(self, checkpoint: CheckpointCreated) -> None:
        """Persist a checkpoint event."""
        self._checkpoints.setdefault(checkpoint.run_id, []).append(checkpoint)

    async def list_runs(
        self, *, limit: int = 50, status: str | None = None
    ) -> list[RunSummary]:
        """List workflow runs with optional status filter."""
        summaries = []
        for run_id, meta in self._run_meta.items():
            if status and meta.get("status") != status:
                continue
            summaries.append(
                RunSummary(
                    run_id=run_id,
                    workflow_name=meta.get("workflow_name", ""),
                    status=meta.get("status", "unknown"),
                    started_at=meta.get("started_at", ""),
                    event_count=len(self._events.get(run_id, [])),
                )
            )
        return summaries[:limit]


def project_state(
    events: list[WorkflowEvent],
    initial_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Rebuild current state from an event sequence.

    Uses resulting_state from StateUpdated events (absolute post-reducer state).
    Falls back to initial_state from ExecutionStarted if no StateUpdated found.
    CheckpointCreated snapshots act as fast-forward points.
    """
    state: dict[str, Any] = dict(initial_state or {})

    for event in events:
        if isinstance(event, ExecutionStarted) and not initial_state:
            state = dict(event.initial_state)
        elif isinstance(event, CheckpointCreated):
            state = dict(event.state_snapshot)
        elif isinstance(event, StateUpdated):
            # Use absolute resulting_state -- no reducer logic needed
            state = dict(event.resulting_state)

    return state
