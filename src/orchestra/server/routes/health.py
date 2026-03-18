"""Health check endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from orchestra.server.dependencies import get_event_store

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe. Always returns 200 if the server is up."""
    return {"status": "healthy"}


@router.get("/readyz")
async def readyz(request: Request) -> dict[str, str]:
    """Readiness probe. Returns 200 if the event store is accessible."""
    from fastapi.responses import JSONResponse

    try:
        event_store = get_event_store(request)
        # Verify the store is working by listing runs (lightweight operation)
        await event_store.list_runs(limit=1)
        return {"status": "ready"}
    except Exception:
        return JSONResponse(  # type: ignore[return-value]
            status_code=503,
            content={"status": "not_ready", "detail": "Event store unavailable"},
        )
