"""Workflow event types for event-sourced persistence."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Discriminator values for event deserialization."""

    EXECUTION_STARTED = "execution.started"
    EXECUTION_COMPLETED = "execution.completed"
    FORK_CREATED = "execution.forked"
    NODE_STARTED = "node.started"
    NODE_COMPLETED = "node.completed"
    STATE_UPDATED = "state.updated"
    ERROR_OCCURRED = "error.occurred"
    LLM_CALLED = "llm.called"
    TOOL_CALLED = "tool.called"
    EDGE_TRAVERSED = "edge.traversed"
    PARALLEL_STARTED = "parallel.started"
    PARALLEL_COMPLETED = "parallel.completed"
    INTERRUPT_REQUESTED = "interrupt.requested"
    INTERRUPT_RESUMED = "interrupt.resumed"
    CHECKPOINT_CREATED = "checkpoint.created"
    SECURITY_VIOLATION = "security.violation"
    OUTPUT_REJECTED = "output.rejected"
    HANDOFF_INITIATED = "handoff.initiated"
    HANDOFF_COMPLETED = "handoff.completed"


class WorkflowEvent(BaseModel):
    """Base event type. All events are immutable."""

    model_config = {"frozen": True}

    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    run_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sequence: int = 0  # Assigned by EventBus at emit time
    event_type: EventType
    schema_version: int = 1


# --- Lifecycle Events ---


class ExecutionStarted(WorkflowEvent):
    """Emitted when a workflow run begins."""

    event_type: Literal[EventType.EXECUTION_STARTED] = EventType.EXECUTION_STARTED
    workflow_name: str = ""
    initial_state: dict[str, Any] = Field(default_factory=dict)
    entry_point: str = ""


class ExecutionCompleted(WorkflowEvent):
    """Emitted when a workflow run finishes."""

    event_type: Literal[EventType.EXECUTION_COMPLETED] = EventType.EXECUTION_COMPLETED
    final_state: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float = 0.0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    status: str = "completed"  # "completed" or "failed"


class ForkCreated(WorkflowEvent):
    """Emitted when a new run is forked from an existing run."""

    event_type: Literal[EventType.FORK_CREATED] = EventType.FORK_CREATED
    parent_run_id: str
    fork_point_sequence: int
    new_run_id: str


# --- Node Events ---


class NodeStarted(WorkflowEvent):
    """Emitted when a node begins execution."""

    event_type: Literal[EventType.NODE_STARTED] = EventType.NODE_STARTED
    node_id: str
    node_type: str = ""  # "agent", "function", "subgraph"


class NodeCompleted(WorkflowEvent):
    """Emitted when a node finishes execution."""

    event_type: Literal[EventType.NODE_COMPLETED] = EventType.NODE_COMPLETED
    node_id: str
    node_type: str = ""
    duration_ms: float = 0.0
    state_update: dict[str, Any] = Field(default_factory=dict)


class StateUpdated(WorkflowEvent):
    """Emitted when workflow state changes after a node runs."""

    event_type: Literal[EventType.STATE_UPDATED] = EventType.STATE_UPDATED
    node_id: str
    field_updates: dict[str, Any] = Field(default_factory=dict)
    resulting_state: dict[str, Any] = Field(default_factory=dict)


class ErrorOccurred(WorkflowEvent):
    """Emitted when an error occurs during execution."""

    event_type: Literal[EventType.ERROR_OCCURRED] = EventType.ERROR_OCCURRED
    node_id: str = ""
    error_type: str = ""
    error_message: str = ""


# --- Agent Events ---


class LLMCalled(WorkflowEvent):
    """Emitted when an LLM provider is called."""

    event_type: Literal[EventType.LLM_CALLED] = EventType.LLM_CALLED
    node_id: str
    agent_name: str = ""
    model: str = ""
    content: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: float = 0.0
    finish_reason: str = ""


class ToolCalled(WorkflowEvent):
    """Emitted when an agent invokes a tool."""

    event_type: Literal[EventType.TOOL_CALLED] = EventType.TOOL_CALLED
    node_id: str
    agent_name: str = ""
    tool_name: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    error: str | None = None
    duration_ms: float = 0.0


# --- Graph Events ---


class EdgeTraversed(WorkflowEvent):
    """Emitted when the workflow follows an edge between nodes."""

    event_type: Literal[EventType.EDGE_TRAVERSED] = EventType.EDGE_TRAVERSED
    from_node: str
    to_node: str
    edge_type: str = ""  # "direct", "conditional", "parallel", "handoff"
    condition_result: str | None = None


class ParallelStarted(WorkflowEvent):
    """Emitted when parallel fan-out begins."""

    event_type: Literal[EventType.PARALLEL_STARTED] = EventType.PARALLEL_STARTED
    source_node: str
    target_nodes: tuple[str, ...] = ()


class ParallelCompleted(WorkflowEvent):
    """Emitted when all parallel branches complete."""

    event_type: Literal[EventType.PARALLEL_COMPLETED] = EventType.PARALLEL_COMPLETED
    source_node: str
    target_nodes: tuple[str, ...] = ()
    duration_ms: float = 0.0


# --- HITL Events ---


class InterruptRequested(WorkflowEvent):
    """Emitted when human-in-the-loop interrupt is triggered."""

    event_type: Literal[EventType.INTERRUPT_REQUESTED] = EventType.INTERRUPT_REQUESTED
    node_id: str
    interrupt_type: str = "before"  # "before" or "after"


class InterruptResumed(WorkflowEvent):
    """Emitted when execution resumes after an interrupt."""

    event_type: Literal[EventType.INTERRUPT_RESUMED] = EventType.INTERRUPT_RESUMED
    node_id: str
    state_modifications: dict[str, Any] = Field(default_factory=dict)


class CheckpointCreated(WorkflowEvent):
    """Emitted when a state checkpoint is persisted."""

    event_type: Literal[EventType.CHECKPOINT_CREATED] = EventType.CHECKPOINT_CREATED
    checkpoint_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    node_id: str = ""
    state_snapshot: dict[str, Any] = Field(default_factory=dict)


class SecurityViolation(WorkflowEvent):
    """Emitted when a security policy (like Tool ACL) is violated."""

    event_type: Literal[EventType.SECURITY_VIOLATION] = EventType.SECURITY_VIOLATION
    node_id: str
    agent_name: str = ""
    violation_type: str = ""  # e.g., "unauthorized_tool"
    details: dict[str, Any] = Field(default_factory=dict)


# --- Contract Events ---


class OutputRejected(WorkflowEvent):
    """Emitted when agent output fails boundary contract validation."""

    event_type: Literal[EventType.OUTPUT_REJECTED] = EventType.OUTPUT_REJECTED
    node_id: str
    agent_name: str = ""
    contract_name: str = ""
    validation_errors: list[str] = Field(default_factory=list)


# --- Handoff Events ---


class HandoffInitiated(WorkflowEvent):
    """Emitted when an agent-to-agent handoff begins."""

    event_type: Literal[EventType.HANDOFF_INITIATED] = EventType.HANDOFF_INITIATED
    from_agent: str
    to_agent: str
    reason: str = ""


class HandoffCompleted(WorkflowEvent):
    """Emitted when an agent-to-agent handoff finishes."""

    event_type: Literal[EventType.HANDOFF_COMPLETED] = EventType.HANDOFF_COMPLETED
    from_agent: str
    to_agent: str


# --- Discriminated Union ---

AnyEvent = Annotated[
    Union[
        ExecutionStarted,
        ExecutionCompleted,
        ForkCreated,
        NodeStarted,
        NodeCompleted,
        StateUpdated,
        ErrorOccurred,
        LLMCalled,
        ToolCalled,
        EdgeTraversed,
        ParallelStarted,
        ParallelCompleted,
        InterruptRequested,
        InterruptResumed,
        CheckpointCreated,
        SecurityViolation,
        OutputRejected,
        HandoffInitiated,
        HandoffCompleted,
    ],
    Field(discriminator="event_type"),
]


def create_event(
    event_cls: type[WorkflowEvent], *, run_id: str, sequence: int = 0, **kwargs: Any
) -> WorkflowEvent:
    """Factory to create events with auto-generated id and timestamp."""
    return event_cls(run_id=run_id, sequence=sequence, **kwargs)
