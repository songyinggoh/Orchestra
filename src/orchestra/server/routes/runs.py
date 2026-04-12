"""Workflow run endpoints."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from orchestra.cost.registry import ModelCostRegistry
from orchestra.server.dependencies import get_event_store, get_graph_registry, get_run_manager
from orchestra.server.models import (
    CostBreakdown,
    EventItem,
    ResumeRequest,
    RunCost,
    RunCreate,
    RunResponse,
    RunState,
    RunStatus,
)
from orchestra.storage.events import EventType
from orchestra.storage.serialization import event_to_dict
from orchestra.storage.store import project_state

# BC-5: Create once at module level — avoids re-reading JSON from disk per request.
_cost_registry = ModelCostRegistry()

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
    """List all workflow runs — active (in-memory) and historical (from store)."""
    run_manager = get_run_manager(request)
    event_store = get_event_store(request)

    # Collect active runs from RunManager
    active_statuses = await run_manager.list_runs()
    seen_ids = {s.run_id for s in active_statuses}

    # Merge in historical runs from EventStore that aren't already active
    stored_runs = await event_store.list_runs(limit=200)
    for sr in stored_runs:
        if sr.run_id not in seen_ids:
            active_statuses.append(
                RunStatus(
                    run_id=sr.run_id,
                    status=sr.status,
                    created_at=sr.started_at,
                    completed_at=sr.completed_at,
                    event_count=sr.event_count,
                    workflow_name=sr.workflow_name,
                )
            )

    return active_statuses


@router.get("/{run_id}", response_model=RunStatus)
async def get_run_status(run_id: str, request: Request) -> RunStatus:
    """Get the current status of a specific run."""
    run_manager = get_run_manager(request)
    event_store = get_event_store(request)
    active_run = run_manager.get_run(run_id)

    if active_run is not None:
        events = await event_store.get_events(run_id)
        return RunStatus(
            run_id=run_id,
            status=active_run.status,
            created_at=active_run.created_at.isoformat(),
            event_count=len(events),
            workflow_name=active_run.graph_name,
        )

    # Fall back to EventStore for historical runs
    stored_runs = await event_store.list_runs(limit=500)
    for sr in stored_runs:
        if sr.run_id == run_id:
            return RunStatus(
                run_id=run_id,
                status=sr.status,
                created_at=sr.started_at,
                completed_at=sr.completed_at,
                event_count=sr.event_count,
                workflow_name=sr.workflow_name,
            )

    raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")


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


@router.get("/{run_id}/events", response_model=list[EventItem])
async def get_run_events(
    run_id: str,
    request: Request,
    after_sequence: int = -1,
    event_types: str | None = None,
    limit: int = Query(default=1000, ge=1, le=10000),
) -> list[EventItem]:
    """Retrieve stored events for a run.

    Query params:
        after_sequence: Only return events with sequence > this value.
        event_types: Comma-separated event type filter (e.g. "llm.called,node.started").
        limit: Max events to return (default 1000, min 1, max 10000).
    """
    event_store = get_event_store(request)

    type_filter = None
    if event_types:
        type_filter = [EventType(t.strip()) for t in event_types.split(",")]

    events = await event_store.get_events(
        run_id, after_sequence=after_sequence, event_types=type_filter
    )

    return [
        EventItem(
            event_id=e.event_id,
            run_id=e.run_id,
            event_type=e.event_type.value,
            sequence=e.sequence,
            timestamp=e.timestamp.isoformat(),
            data=event_to_dict(e),
        )
        for e in events[:limit]
    ]


@router.get("/{run_id}/state", response_model=RunState)
async def get_run_state(run_id: str, request: Request) -> RunState:
    """Get the current or final projected state of a run."""
    event_store = get_event_store(request)
    events = await event_store.get_events(run_id)
    if not events:
        raise HTTPException(status_code=404, detail=f"No events found for run '{run_id}'.")

    state = project_state(events)
    return RunState(run_id=run_id, state=state, event_count=len(events))


@router.get("/{run_id}/cost", response_model=RunCost)
async def get_run_cost(run_id: str, request: Request) -> RunCost:
    """Get cost breakdown for a run, reconstructed from stored LLM events."""
    from orchestra.storage.events import LLMCalled

    event_store = get_event_store(request)
    events = await event_store.get_events(run_id, event_types=[EventType.LLM_CALLED])

    registry = _cost_registry
    total_cost = 0.0
    total_in = 0
    total_out = 0
    by_model: dict[str, dict[str, float | int]] = {}
    by_agent: dict[str, dict[str, float | int]] = {}

    for e in events:
        if not isinstance(e, LLMCalled):
            continue
        model = e.model or ""
        agent = e.agent_name or ""
        inp = e.input_tokens or 0
        out = e.output_tokens or 0
        cost = registry.calculate_cost(model, inp, out)

        total_cost += cost
        total_in += inp
        total_out += out

        for key, bucket in [(model, by_model), (agent, by_agent)]:
            if not key:
                continue
            if key not in bucket:
                bucket[key] = {
                    "cost_usd": 0.0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "call_count": 0,
                }
            bucket[key]["cost_usd"] += cost
            bucket[key]["input_tokens"] += inp
            bucket[key]["output_tokens"] += out
            bucket[key]["call_count"] += 1

    return RunCost(
        run_id=run_id,
        total_cost_usd=total_cost,
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        total_tokens=total_in + total_out,
        call_count=len(events),
        by_model={k: CostBreakdown(**v) for k, v in by_model.items()},
        by_agent={k: CostBreakdown(**v) for k, v in by_agent.items()},
    )


@router.post("/{run_id}/cancel", response_model=RunStatus)
async def cancel_run(run_id: str, request: Request) -> RunStatus:
    """Cancel an active workflow run."""
    run_manager = get_run_manager(request)
    event_store = get_event_store(request)
    active_run = run_manager.get_run(run_id)

    if active_run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")

    if active_run.status in ("completed", "failed", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail=f"Run '{run_id}' already {active_run.status}.",
        )

    active_run.task.cancel()
    try:
        await asyncio.wait_for(asyncio.shield(active_run.task), timeout=2.0)
    except (TimeoutError, asyncio.CancelledError):
        pass
    active_run.status = "cancelled"

    events = await event_store.get_events(run_id)
    return RunStatus(
        run_id=run_id,
        status="cancelled",
        created_at=active_run.created_at.isoformat(),
        event_count=len(events),
        workflow_name=active_run.graph_name,
    )
