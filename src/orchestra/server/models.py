"""Pydantic request/response schemas for the Orchestra server API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RunCreate(BaseModel):
    """Request body for creating a new workflow run."""

    graph_name: str
    input: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


class RunResponse(BaseModel):
    """Response returned when a run is created."""

    run_id: str
    status: str
    graph_name: str
    created_at: datetime


class RunStatus(BaseModel):
    """Status information about a workflow run."""

    run_id: str
    status: str
    created_at: str
    completed_at: str | None = None
    event_count: int = 0
    workflow_name: str = ""


class StreamEvent(BaseModel):
    """SSE event format."""

    event: str
    data: str
    id: str


class GraphInfo(BaseModel):
    """Information about a registered graph."""

    name: str
    nodes: list[str]
    edges: list[dict[str, Any]] = Field(default_factory=list)
    entry_point: str
    mermaid: str = ""


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str
    error_type: str = "server_error"


class ResumeRequest(BaseModel):
    """Request body for resuming an interrupted run.

    `state_updates` is the resume payload mechanism. Nodes read the user's
    decision from state (e.g. `state_updates={"decision": "approve"}` → the
    resumed node reads `state["decision"]` to branch). Unlike LangGraph's
    `Command(resume=...)`, Orchestra has no separate interrupt-return channel:
    decisions flow through state. UIs should encode choices as explicit state
    keys rather than relying on a reserved `decision` field.
    """

    state_updates: dict[str, Any] = Field(default_factory=dict)


class EventItem(BaseModel):
    """A single workflow event returned by the events endpoint."""

    event_id: str
    run_id: str
    event_type: str
    sequence: int
    timestamp: str
    data: dict[str, Any]


class RunState(BaseModel):
    """Current or final state of a workflow run."""

    run_id: str
    state: dict[str, Any]
    event_count: int = 0


class CostBreakdown(BaseModel):
    """Cost breakdown for a single dimension (model or agent)."""

    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    call_count: int = 0


class RunCost(BaseModel):
    """Cost summary for a workflow run."""

    run_id: str
    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 0
    by_model: dict[str, CostBreakdown] = Field(default_factory=dict)
    by_agent: dict[str, CostBreakdown] = Field(default_factory=dict)


class ForkRequest(BaseModel):
    """Request body for forking a run from a historical sequence."""

    from_sequence: int = Field(ge=0)
    state_overrides: dict[str, Any] = Field(default_factory=dict)


class ForkResponse(BaseModel):
    """Response returned when a new fork is created."""

    new_run_id: str
    parent_run_id: str
    from_sequence: int


class CostAggregateEntry(BaseModel):
    """Single aggregated cost entry."""

    key: str
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    call_count: int = 0


class CostAggregateResponse(BaseModel):
    """Response for the cost aggregate endpoint."""

    from_date: str
    to_date: str
    group_by: str
    entries: list[CostAggregateEntry] = Field(default_factory=list)
    total: CostAggregateEntry
