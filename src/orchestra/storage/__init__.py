"""Event-sourced persistence layer for Orchestra.

Provides the event type hierarchy, EventBus for dispatching,
EventStore protocol for backends, and state projection utilities.
"""

from orchestra.storage.contracts import BoundaryContract, ContractRegistry
from orchestra.storage.events import (
    AnyEvent,
    CheckpointCreated,
    EdgeTraversed,
    ErrorOccurred,
    EventType,
    ExecutionCompleted,
    ExecutionStarted,
    HandoffCompleted,
    HandoffInitiated,
    InterruptRequested,
    InterruptResumed,
    LLMCalled,
    NodeCompleted,
    NodeStarted,
    OutputRejected,
    ParallelCompleted,
    ParallelStarted,
    StateUpdated,
    ToolCalled,
    WorkflowEvent,
    create_event,
)
from orchestra.storage.store import (
    EventBus,
    EventStore,
    InMemoryEventStore,
    RunSummary,
    project_state,
)

try:
    from orchestra.storage.sqlite import SnapshotManager, SQLiteEventStore

    _sqlite_available = True
except ImportError:
    _sqlite_available = False

try:
    from orchestra.storage.postgres import PostgresEventStore

    _postgres_available = True
except ImportError:
    PostgresEventStore = None  # type: ignore[assignment,misc]
    _postgres_available = False

__all__ = [
    "AnyEvent",
    "BoundaryContract",
    "CheckpointCreated",
    "ContractRegistry",
    "EdgeTraversed",
    "ErrorOccurred",
    "EventBus",
    "EventStore",
    "EventType",
    "ExecutionCompleted",
    "ExecutionStarted",
    "HandoffCompleted",
    "HandoffInitiated",
    "InMemoryEventStore",
    "InterruptRequested",
    "InterruptResumed",
    "LLMCalled",
    "NodeCompleted",
    "NodeStarted",
    "OutputRejected",
    "ParallelCompleted",
    "ParallelStarted",
    "PostgresEventStore",
    "RunSummary",
    "SQLiteEventStore",
    "SnapshotManager",
    "StateUpdated",
    "ToolCalled",
    "WorkflowEvent",
    "create_event",
    "project_state",
]
