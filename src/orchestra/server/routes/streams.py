"""SSE streaming endpoint for real-time workflow events."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from orchestra.server.dependencies import get_event_store, get_run_manager

router = APIRouter(prefix="/runs", tags=["streams"])


@router.get("/{run_id}/stream")
async def stream_run_events(run_id: str, request: Request) -> Any:
    """SSE endpoint for streaming workflow events in real time.

    Supports reconnection via the ``Last-Event-ID`` header: if provided,
    events with a sequence number <= that ID are replayed from the
    EventStore before switching to the live queue.

    Response headers include ``X-Accel-Buffering: no`` and
    ``Cache-Control: no-cache`` for proper proxy behaviour.
    """
    from sse_starlette.sse import EventSourceResponse

    run_manager = get_run_manager(request)
    event_store = get_event_store(request)

    active_run = run_manager.get_run(run_id)
    if active_run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")

    # Determine replay point from Last-Event-ID header
    last_event_id = request.headers.get("Last-Event-ID")
    after_sequence = int(last_event_id) if last_event_id else -1

    config = request.app.state.config
    heartbeat_interval = config.sse_heartbeat_interval
    retry_ms = config.sse_retry_ms

    async def _event_generator() -> AsyncGenerator[dict[str, str], None]:
        # Send initial retry directive
        yield {"event": "config", "data": json.dumps({"retry": retry_ms}), "id": "0"}

        # Replay missed events from store
        if after_sequence >= 0:
            stored_events = await event_store.get_events(run_id, after_sequence=after_sequence)
            for evt in stored_events:
                yield {
                    "event": evt.event_type.value,
                    "data": evt.model_dump_json(),
                    "id": str(evt.sequence),
                }

        # Stream live events from the queue
        while True:
            try:
                event = await asyncio.wait_for(
                    active_run.event_queue.get(), timeout=heartbeat_interval
                )
            except TimeoutError:
                # Send heartbeat as SSE comment
                yield {"event": "ping", "data": "", "id": ""}
                continue

            if event is None:
                # Run finished — send terminal event and close
                yield {
                    "event": "done",
                    "data": json.dumps({"status": active_run.status}),
                    "id": "",
                }
                break

            yield {
                "event": event.event_type.value,
                "data": event.model_dump_json(),
                "id": str(event.sequence),
            }

    return EventSourceResponse(
        _event_generator(),
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
        },
    )
