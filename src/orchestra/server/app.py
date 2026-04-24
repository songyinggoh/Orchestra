"""FastAPI application factory for the Orchestra server."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from orchestra.server.config import ServerConfig
from orchestra.server.lifecycle import GraphRegistry, RunManager
from orchestra.server.middleware import (
    add_body_size_middleware,
    add_cors_middleware,
    add_rate_limit_middleware,
    add_request_id_middleware,
)
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

    try:
        from orchestra.tools.wasm_runtime import WasmToolSandbox

        WASM_AVAILABLE = True
    except ImportError:
        WASM_AVAILABLE = False

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        """Initialize shared resources on startup; clean up on shutdown."""
        import os

        import structlog

        from orchestra.observability.logging import setup_logging
        from orchestra.storage.sqlite import SQLiteEventStore

        setup_logging(
            level=os.environ.get("LOG_LEVEL", "INFO"),
            json_output=os.environ.get("ORCHESTRA_ENV", "dev") != "dev",
        )

        log = structlog.get_logger(__name__)
        api_key = os.environ.get("ORCHESTRA_SERVER_KEY") or os.environ.get("ORCHESTRA_API_KEY")
        app.state.api_key = api_key
        if not api_key:
            log.warning(
                "orchestra_api_key_not_set",
                detail="Server is running without authentication. Set ORCHESTRA_API_KEY to enable.",
            )

        event_store = SQLiteEventStore()
        await event_store.initialize()

        app.state.config = config
        # If orchestra up pre-registered workflows via discovery, reuse that
        # registry. Otherwise create a fresh one.
        if not getattr(app.state, "_discovery_registry", None):
            app.state.graph_registry = GraphRegistry()
        else:
            app.state.graph_registry = app.state._discovery_registry
        app.state.run_manager = RunManager()
        app.state.event_store = event_store

        if WASM_AVAILABLE:
            wasm_sandbox = WasmToolSandbox()
            app.state.wasm_sandbox = wasm_sandbox
        else:
            app.state.wasm_sandbox = None

        try:
            yield
        finally:
            # Shutdown: cancel tasks, await them, then close the store.
            # Awaiting is critical — run tasks may be mid-append() and the
            # store must not be closed while writes are in flight.
            run_manager: RunManager = app.state.run_manager
            active_tasks = []
            for run_status in await run_manager.list_runs():
                active = run_manager.get_run(run_status.run_id)
                if active and not active.task.done():
                    active.task.cancel()
                    active_tasks.append(active.task)
            if active_tasks:
                await asyncio.gather(*active_tasks, return_exceptions=True)
            if app.state.wasm_sandbox is not None:
                app.state.wasm_sandbox.shutdown()
            await event_store.close()

    app = FastAPI(
        title="Orchestra Server",
        description="Multi-agent orchestration framework HTTP API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # --- Middleware ---
    # add_middleware prepends, so last call = outermost.
    # Desired chain: CORS → BodySize → RateLimit → RequestID → route handler
    add_request_id_middleware(app)  # innermost
    add_rate_limit_middleware(app, config)
    add_body_size_middleware(app, config)
    add_cors_middleware(app, config)  # outermost — OPTIONS preflight before auth

    # --- Routes ---
    from fastapi import Depends

    from orchestra.server.dependencies import require_api_key
    from orchestra.server.routes.cost import router as cost_router
    from orchestra.server.routes.graphs import router as graphs_router
    from orchestra.server.routes.health import router as health_router
    from orchestra.server.routes.runs import router as runs_router
    from orchestra.server.routes.streams import router as streams_router

    _auth = [Depends(require_api_key)]

    # Health endpoints are outside the API prefix for standard probe paths
    # and intentionally unauthenticated (Kubernetes liveness/readiness probes).
    app.include_router(health_router)

    app.include_router(runs_router, prefix=config.api_prefix, dependencies=_auth)
    app.include_router(streams_router, prefix=config.api_prefix, dependencies=_auth)
    app.include_router(graphs_router, prefix=config.api_prefix, dependencies=_auth)
    app.include_router(cost_router, prefix=config.api_prefix, dependencies=_auth)

    # --- UI static files ---
    # Serve the built React UI at /ui/ if the dist directory exists.
    # The UI is optional: install with `pip install orchestra[ui]` or
    # build from src/orchestra/ui/ with `npm run build`.
    import pathlib

    ui_dist = pathlib.Path(__file__).parent.parent / "ui" / "dist"
    if ui_dist.is_dir():
        from fastapi.responses import RedirectResponse
        from fastapi.staticfiles import StaticFiles

        @app.get("/ui")
        async def ui_redirect() -> RedirectResponse:
            """Redirect /ui to /ui/ so the SPA loads correctly."""
            return RedirectResponse("/ui/", status_code=301)

        app.mount("/ui", StaticFiles(directory=str(ui_dist), html=True), name="ui")

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
            content=ErrorResponse(detail=str(exc), error_type=type(exc).__name__).model_dump(),
        )

    return app
