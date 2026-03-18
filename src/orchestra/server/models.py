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
    """Request body for resuming an interrupted run."""

    state_updates: dict[str, Any] = Field(default_factory=dict)
