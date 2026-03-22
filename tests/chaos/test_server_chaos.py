"""Chaos tests: SSE stream interruption and concurrent connections.

Tests that the FastAPI server handles SSE streaming correctly under
adverse conditions: normal completion and multiple concurrent clients.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

try:
    from fastapi.testclient import TestClient
    from httpx import ASGITransport, AsyncClient

    HAS_SERVER_DEPS = True
except ImportError:
    HAS_SERVER_DEPS = False

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not HAS_SERVER_DEPS, reason="Server dependencies not installed"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_echo_graph(name: str = "chaos-echo") -> Any:
    """Build a minimal graph that echoes its input."""
    from orchestra.core.graph import WorkflowGraph

    async def echo(state: dict[str, Any]) -> dict[str, Any]:
        return {"output": state.get("input", "ok")}

    graph = WorkflowGraph(name=name)
    graph.add_node("echo", echo)
    graph.set_entry_point("echo")
    return graph.compile()


@pytest.fixture()
def app() -> Any:
    """Create a FastAPI app instance with a registered test graph."""
    from orchestra.server.app import create_app
    from orchestra.server.config import ServerConfig

    config = ServerConfig()
    application = create_app(config)
    return application


@pytest.fixture()
def client(app: Any) -> Any:
    """Synchronous test client with lifespan events triggered."""
    with TestClient(app, raise_server_exceptions=False) as c:
        graph = _make_echo_graph()
        app.state.graph_registry.register("chaos-echo", graph)
        yield c


def _parse_sse_data_events(raw: str) -> list[dict]:
    """Extract JSON data from SSE 'data:' lines."""
    events = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[len("data:") :].strip()
            if payload:
                try:
                    events.append(json.loads(payload))
                except json.JSONDecodeError:
                    pass
    return events


# ---------------------------------------------------------------------------
# SSE stream tests
# ---------------------------------------------------------------------------


def test_sse_stream_completes_normally(client: Any) -> None:
    """POST /api/v1/runs + GET /api/v1/runs/{id}/stream returns events."""
    # Create a run
    create_resp = client.post(
        "/api/v1/runs",
        json={"graph_name": "chaos-echo", "input": {"input": "chaos-test"}},
    )
    assert create_resp.status_code == 202
    run_id = create_resp.json()["run_id"]

    # Stream events
    with client.stream("GET", f"/api/v1/runs/{run_id}/stream") as response:
        assert response.status_code == 200
        chunks: list[str] = []
        for chunk in response.iter_text():
            chunks.append(chunk)
            if "done" in chunk:
                break

    raw = "".join(chunks)
    events = _parse_sse_data_events(raw)

    # Stream must produce at least one data event
    assert len(events) >= 1


def test_concurrent_sse_streams(app: Any) -> None:
    """Five concurrent SSE stream connections all complete without error."""

    async def _run_one_stream() -> list[dict]:
        """Create a run and stream its events; return parsed data events."""

        # Each coroutine uses its own async client against the shared app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # Create run
            create_resp = await ac.post(
                "/api/v1/runs",
                json={"graph_name": "chaos-echo", "input": {"input": "concurrent"}},
            )
            assert create_resp.status_code == 202
            run_id = create_resp.json()["run_id"]

            # Stream events
            events: list[dict] = []
            async with ac.stream("GET", f"/api/v1/runs/{run_id}/stream") as resp:
                assert resp.status_code == 200
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if line.startswith("data:"):
                        payload = line[len("data:") :].strip()
                        if payload:
                            try:
                                events.append(json.loads(payload))
                            except json.JSONDecodeError:
                                pass
                    if any(e.get("event") == "run_end" for e in events):
                        break

            return events

    async def _run_concurrent() -> None:
        # Register graph on the app state (requires lifespan to have run first)
        # We use TestClient to trigger lifespan, then do async work
        with TestClient(app, raise_server_exceptions=False):
            graph = _make_echo_graph()
            app.state.graph_registry.register("chaos-echo", graph)

            # Run 5 concurrent SSE streams
            results = await asyncio.gather(*[_run_one_stream() for _ in range(5)])

            # Every stream must have received at least one data event
            for stream_events in results:
                assert len(stream_events) >= 1

    asyncio.run(_run_concurrent())
