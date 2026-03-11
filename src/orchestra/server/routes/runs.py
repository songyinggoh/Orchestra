"""Workflow run endpoints."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from orchestra.server.dependencies import get_event_store, get_graph_registry, get_run_manager
from orchestra.server.models import ResumeRequest, RunCreate, RunResponse, RunStatus

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", status_code=202, response_model=RunResponse)
async def create_run(body: RunCreate, request: Request) -> RunResponse:
    """Create and start a new workflow run.

    Returns 202 Accepted immediately. The workflow executes in the
    background as an asyncio.Task.
    """
    registry = get_graph_registry(request)
    run_manager = get_run_manager(request)
    event_store = get_event_store(request)

    graph = registry.get(body.graph_name)
    if graph is None:
        raise HTTPException(
            status_code=404,
            detail=f"Graph '{body.graph_name}' not found. "
            f"Register it via GraphRegistry.register() before starting the server.",
        )

    run_id = uuid.uuid4().hex
    active_run = await run_manager.start_run(
        run_id=run_id,
        graph=graph,
        input_data=body.input,
        event_store=event_store,
    )

    return RunResponse(
        run_id=run_id,
        status=active_run.status,
        graph_name=body.graph_name,
        created_at=active_run.created_at,
    )


@router.get("", response_model=list[RunStatus])
async def list_runs(request: Request) -> list[RunStatus]:
    """List all workflow runs tracked by the RunManager."""
    run_manager = get_run_manager(request)
    return await run_manager.list_runs()


@router.get("/{run_id}", response_model=RunStatus)
async def get_run_status(run_id: str, request: Request) -> RunStatus:
    """Get the current status of a specific run."""
    run_manager = get_run_manager(request)
    active_run = run_manager.get_run(run_id)
    if active_run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")

    # Count events from the store
    event_store = get_event_store(request)
    events = await event_store.get_events(run_id)
    event_count = len(events)

    return RunStatus(
        run_id=run_id,
        status=active_run.status,
        created_at=active_run.created_at.isoformat(),
        event_count=event_count,
    )


@router.post("/{run_id}/resume", response_model=RunResponse)
async def resume_run(run_id: str, body: ResumeRequest, request: Request) -> RunResponse:
    """Resume an interrupted workflow run with optional state updates.

    Creates a new asyncio.Task that continues from the latest checkpoint.
    """
    registry = get_graph_registry(request)
    run_manager = get_run_manager(request)
    event_store = get_event_store(request)

    # Find the original run to get the graph
    active_run = run_manager.get_run(run_id)
    if active_run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")

    if active_run.status == "completed":
        raise HTTPException(status_code=409, detail=f"Run '{run_id}' already completed.")

    graph = registry.get(active_run.graph_name)
    if graph is None:
        raise HTTPException(
            status_code=404,
            detail=f"Graph '{active_run.graph_name}' no longer registered.",
        )

    # Use the graph's resume method directly via a new task
    import asyncio
    from orchestra.server.lifecycle import ActiveRun
    from datetime import datetime, timezone

    async def _resume_workflow() -> dict[str, Any]:
        try:
            result = await graph.resume(
                run_id,
                state_updates=body.state_updates or None,
                event_store=event_store,
            )
            active_run.status = "completed"
            return result
        except Exception:
            active_run.status = "failed"
            raise
        finally:
            await active_run.event_queue.put(None)

    active_run.status = "running"
    active_run.task = asyncio.create_task(_resume_workflow(), name=f"resume-{run_id}")

    return RunResponse(
        run_id=run_id,
        status="running",
        graph_name=active_run.graph_name,
        created_at=active_run.created_at,
    )
