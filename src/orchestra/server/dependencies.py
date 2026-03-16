"""FastAPI dependency injection functions."""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

if TYPE_CHECKING:
    from orchestra.server.lifecycle import GraphRegistry, RunManager
    from orchestra.storage.store import EventStore

_bearer = HTTPBearer(auto_error=False)


def get_graph_registry(request: Request) -> "GraphRegistry":
    """Return the GraphRegistry from app state."""
    return request.app.state.graph_registry  # type: ignore[no-any-return]


def get_run_manager(request: Request) -> "RunManager":
    """Return the RunManager from app state."""
    return request.app.state.run_manager  # type: ignore[no-any-return]


def get_event_store(request: Request) -> "EventStore":
    """Return the EventStore from app state."""
    return request.app.state.event_store  # type: ignore[no-any-return]


async def require_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Verify the Bearer token matches ORCHESTRA_API_KEY.

    If no API key is configured on app.state, the check is skipped (dev mode).
    Set the ORCHESTRA_API_KEY environment variable to enable enforcement.
    """
    expected: str | None = getattr(request.app.state, "api_key", None)
    if not expected:
        return  # Auth not configured — dev/test mode, allow all.

    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode(), expected.encode()
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
