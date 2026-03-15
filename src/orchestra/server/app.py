"""FastAPI application factory for the Orchestra server."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from orchestra.server.config import ServerConfig
from orchestra.server.lifecycle import GraphRegistry, RunManager
from orchestra.server.middleware import add_cors_middleware, add_request_id_middleware
from orchestra.server.models import ErrorResponse


def create_app(config: ServerConfig | None = None) -> FastAPI:
    """Create and configure the Orchestra FastAPI application.

    Args:
        config: Server configuration. Uses defaults if not provided.

    Returns:
        Configured FastAPI application instance.
    """
    if config is None:
        config = ServerConfig()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        """Initialize shared resources on startup; clean up on shutdown."""
        import os
        from orchestra.observability.logging import setup_logging
        from orchestra.storage.store import InMemoryEventStore

        setup_logging(
            level=os.environ.get("LOG_LEVEL", "INFO"),
            json_output=os.environ.get("ORCHESTRA_ENV", "dev") != "dev",
        )

        app.state.config = config
        app.state.graph_registry = GraphRegistry()
        app.state.run_manager = RunManager()
        app.state.event_store = InMemoryEventStore()

        yield

        # Shutdown: cancel any still-running tasks
        run_manager: RunManager = app.state.run_manager
        for run_status in await run_manager.list_runs():
            active = run_manager.get_run(run_status.run_id)
            if active and not active.task.done():
                active.task.cancel()

    app = FastAPI(
        title="Orchestra Server",
        description="Multi-agent orchestration framework HTTP API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # --- Middleware ---
    add_cors_middleware(app, config)
    add_request_id_middleware(app)

    # --- Routes ---
    from orchestra.server.routes.health import router as health_router
    from orchestra.server.routes.runs import router as runs_router
    from orchestra.server.routes.streams import router as streams_router
    from orchestra.server.routes.graphs import router as graphs_router

    # Health endpoints are outside the API prefix for standard probe paths
    app.include_router(health_router)

    app.include_router(runs_router, prefix=config.api_prefix)
    app.include_router(streams_router, prefix=config.api_prefix)
    app.include_router(graphs_router, prefix=config.api_prefix)

    # --- Exception handlers ---
    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(detail=str(exc), error_type="validation_error").model_dump(),
        )

    @app.exception_handler(Exception)
    async def general_error_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                detail=str(exc), error_type=type(exc).__name__
            ).model_dump(),
        )

    return app
