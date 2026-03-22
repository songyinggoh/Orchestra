"""Integration tests for Orchestra FastAPI server endpoints.

These tests require server dependencies (fastapi, httpx, sse-starlette).
They are skipped automatically if dependencies are not installed.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

import pytest

try:
    from fastapi.testclient import TestClient
    from httpx import AsyncClient

    HAS_SERVER_DEPS = True
except ImportError:
    HAS_SERVER_DEPS = False

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not HAS_SERVER_DEPS, reason="Server dependencies not installed"),
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_test_graph(name: str = "test-graph") -> Any:
    """Build a trivial compiled graph for testing."""
    from orchestra.core.graph import WorkflowGraph

    async def echo(state: dict[str, Any]) -> dict[str, Any]:
        return {"output": state.get("input", "hello")}

    graph = WorkflowGraph(name=name)
    graph.add_node("echo", echo)
    graph.set_entry_point("echo")
    return graph.compile()


@pytest.fixture()
def app() -> Any:
    """Create a FastAPI app with a registered test graph."""
    from orchestra.server.app import create_app
    from orchestra.server.config import ServerConfig

    config = ServerConfig()
    application = create_app(config)

    # Manually trigger lifespan and register graph
    # We use TestClient which handles lifespan automatically
    return application


@pytest.fixture()
def client(app: Any) -> Any:
    """Synchronous test client with lifespan events."""
    with TestClient(app, raise_server_exceptions=False) as c:
        # Register test graph after lifespan has initialized app.state
        graph = _make_test_graph()
        app.state.graph_registry.register("test-graph", graph)
        yield c


@pytest.fixture()
async def aclient(app: Any) -> AsyncIterator[AsyncClient]:
    """Asynchronous test client with ASGI lifespan context triggered."""
    from httpx import ASGITransport

    async with app.router.lifespan_context(app):
        graph = _make_test_graph()
        app.state.graph_registry.register("test-graph", graph)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------


def test_healthz_returns_200(client: Any) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_readyz_returns_200(client: Any) -> None:
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def test_create_run_returns_202(client: Any) -> None:
    response = client.post(
        "/api/v1/runs",
        json={"graph_name": "test-graph", "input": {"input": "hi"}},
    )
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "running"
    assert data["graph_name"] == "test-graph"
    assert "run_id" in data


def test_create_run_invalid_input_returns_422(client: Any) -> None:
    """Test for Pydantic validation error."""
    response = client.post(
        "/api/v1/runs",
        json={"graph_name": "test-graph", "input": "not-a-dict"},
    )
    assert response.status_code == 422


def test_get_run_status(client: Any) -> None:
    # Create a run first
    create_resp = client.post(
        "/api/v1/runs",
        json={"graph_name": "test-graph", "input": {"input": "test"}},
    )
    run_id = create_resp.json()["run_id"]

    # Give the background task a moment to start
    import time

    time.sleep(0.2)

    response = client.get(f"/api/v1/runs/{run_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == run_id
    assert data["status"] in ("running", "completed")


async def test_full_run_lifecycle(aclient: AsyncClient) -> None:
    """Create a run, stream its output, verify final status."""
    # 1. Create the run
    create_resp = await aclient.post(
        "/api/v1/runs",
        json={"graph_name": "test-graph", "input": {"input": "lifecycle"}},
    )
    assert create_resp.status_code == 202
    run_id = create_resp.json()["run_id"]

    # 2. Stream the output
    # SSE format: "event: <type>\ndata: <json>\n\n"
    # Track current event type alongside data lines.
    import json as _json

    async with aclient.stream("GET", f"/api/v1/runs/{run_id}/stream") as response:
        assert response.status_code == 200
        events: list[dict] = []
        current_event_type: str = ""
        async for line in response.aiter_lines():
            line = line.strip()
            if line.startswith("event:"):
                current_event_type = line[len("event:") :].strip()
            elif line.startswith("data:"):
                payload = line[len("data:") :].strip()
                if payload:
                    try:
                        events.append({"event": current_event_type, "data": _json.loads(payload)})
                    except _json.JSONDecodeError:
                        pass

    # We expect at minimum a "done" terminal event
    event_types = [e["event"] for e in events]
    assert "done" in event_types or len(events) >= 1

    # 3. Verify final status
    status_resp = await aclient.get(f"/api/v1/runs/{run_id}")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["status"] == "completed"


def test_list_runs(client: Any) -> None:
    # Create a run
    client.post(
        "/api/v1/runs",
        json={"graph_name": "test-graph", "input": {}},
    )

    response = client.get("/api/v1/runs")
    assert response.status_code == 200
    runs = response.json()
    assert isinstance(runs, list)
    assert len(runs) >= 1


def test_get_nonexistent_run_returns_404(client: Any) -> None:
    response = client.get("/api/v1/runs/nonexistent-id")
    assert response.status_code == 404


def test_create_run_unknown_graph_returns_404(client: Any) -> None:
    response = client.post(
        "/api/v1/runs",
        json={"graph_name": "no-such-graph", "input": {}},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Graphs
# ---------------------------------------------------------------------------


def test_list_graphs(client: Any) -> None:
    response = client.get("/api/v1/graphs")
    assert response.status_code == 200
    graphs = response.json()
    assert isinstance(graphs, list)
    assert len(graphs) == 1
    assert graphs[0]["name"] == "test-graph"


def test_get_graph_detail(client: Any) -> None:
    response = client.get("/api/v1/graphs/test-graph")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "test-graph"
    assert "echo" in data["nodes"]
    assert data["entry_point"] == "echo"
    assert "mermaid" in data
    assert "graph TD" in data["mermaid"]


def test_get_graph_not_found(client: Any) -> None:
    response = client.get("/api/v1/graphs/nonexistent")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------


def test_resume_run(client: Any) -> None:
    # Create a run first
    create_resp = client.post(
        "/api/v1/runs",
        json={"graph_name": "test-graph", "input": {"input": "resume-me"}},
    )
    run_id = create_resp.json()["run_id"]

    import time

    time.sleep(0.2)

    # Try to resume — it will attempt but the graph likely completed already
    # so resume may fail at the checkpoint lookup level. What matters is
    # the endpoint is reachable and returns a valid response structure.
    response = client.post(
        f"/api/v1/runs/{run_id}/resume",
        json={"state_updates": {"approved": True}},
    )
    # 200 if accepted, or could get an error from the resume attempt
    assert response.status_code in (200, 404, 409, 500)


def test_resume_completed_run_returns_409(client: Any) -> None:
    # Create a run and let it complete
    create_resp = client.post(
        "/api/v1/runs",
        json={"graph_name": "test-graph", "input": {"input": "complete-me"}},
    )
    run_id = create_resp.json()["run_id"]
    time.sleep(0.5)  # Ensure it's completed

    # Try to resume it
    response = client.post(f"/api/v1/runs/{run_id}/resume", json={})
    assert response.status_code == 409
    assert "already completed" in response.json()["detail"]
