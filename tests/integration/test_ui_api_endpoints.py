"""Integration tests for Orchestra UI-supporting API endpoints.

Tests the 5 new endpoints added for the UI dashboard:
- GET /runs/{id}/events
- GET /runs/{id}/state
- GET /runs/{id}/cost
- POST /runs/{id}/cancel
- GET /runs (historical merge from EventStore)
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
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


def _make_slow_graph(name: str = "slow-graph") -> Any:
    """Build a graph that takes time to complete (for cancel tests)."""
    import asyncio

    from orchestra.core.graph import WorkflowGraph

    async def slow_node(state: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(10)
        return {"output": "done"}

    graph = WorkflowGraph(name=name)
    graph.add_node("slow", slow_node)
    graph.set_entry_point("slow")
    return graph.compile()


def _make_multi_node_graph(name: str = "multi-graph") -> Any:
    """Build a graph with multiple nodes to produce richer events."""
    from orchestra.core.graph import WorkflowGraph

    async def step_a(state: dict[str, Any]) -> dict[str, Any]:
        return {"step_a_done": True}

    async def step_b(state: dict[str, Any]) -> dict[str, Any]:
        return {"step_b_done": True, "output": "final"}

    graph = WorkflowGraph(name=name)
    graph.add_node("step_a", step_a)
    graph.add_node("step_b", step_b)
    graph.set_entry_point("step_a")
    graph.add_edge("step_a", "step_b")
    return graph.compile()


@pytest.fixture()
def app() -> Any:
    """Create a FastAPI app."""
    from orchestra.server.app import create_app
    from orchestra.server.config import ServerConfig

    config = ServerConfig()
    return create_app(config)


@pytest.fixture()
def client(app: Any) -> Any:
    """Synchronous test client with lifespan events."""
    with TestClient(app, raise_server_exceptions=False) as c:
        graph = _make_test_graph()
        app.state.graph_registry.register("test-graph", graph)
        slow = _make_slow_graph()
        app.state.graph_registry.register("slow-graph", slow)
        multi = _make_multi_node_graph()
        app.state.graph_registry.register("multi-graph", multi)
        yield c


@pytest.fixture()
async def aclient(app: Any) -> AsyncIterator[AsyncClient]:
    """Asynchronous test client."""
    async with app.router.lifespan_context(app):
        graph = _make_test_graph()
        app.state.graph_registry.register("test-graph", graph)
        slow = _make_slow_graph()
        app.state.graph_registry.register("slow-graph", slow)
        multi = _make_multi_node_graph()
        app.state.graph_registry.register("multi-graph", multi)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


def _wait_for_status(
    run_id: str,
    client: Any,
    target_status: str,
    timeout: float = 5.0,
) -> None:
    """Poll until run reaches target_status or raise TimeoutError."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/api/v1/runs/{run_id}")
        if resp.status_code == 200 and resp.json()["status"] == target_status:
            return
        time.sleep(0.05)
    raise TimeoutError(f"Run {run_id} did not reach {target_status!r} within {timeout}s")


def _create_and_wait(client: Any, graph_name: str = "test-graph", wait: float = 0.5) -> str:
    """Helper: create a run and wait for it to complete."""
    resp = client.post(
        "/api/v1/runs",
        json={"graph_name": graph_name, "input": {"input": "test"}},
    )
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]
    _wait_for_status(run_id, client, "completed")
    return run_id


# ---------------------------------------------------------------------------
# GET /runs/{id}/events
# ---------------------------------------------------------------------------


class TestGetRunEvents:
    def test_returns_events_for_completed_run(self, client: Any) -> None:
        run_id = _create_and_wait(client)

        resp = client.get(f"/api/v1/runs/{run_id}/events")
        assert resp.status_code == 200
        events = resp.json()
        assert isinstance(events, list)
        assert len(events) >= 1

        # Each event should have required fields
        for evt in events:
            assert "event_id" in evt
            assert "run_id" in evt
            assert evt["run_id"] == run_id
            assert "event_type" in evt
            assert "sequence" in evt
            assert "timestamp" in evt
            assert "data" in evt

    def test_events_have_correct_types(self, client: Any) -> None:
        run_id = _create_and_wait(client)

        resp = client.get(f"/api/v1/runs/{run_id}/events")
        events = resp.json()
        event_types = [e["event_type"] for e in events]

        # A completed run should have at minimum started and completed events
        assert "execution.started" in event_types
        assert "execution.completed" in event_types

    def test_after_sequence_filter(self, client: Any) -> None:
        run_id = _create_and_wait(client)

        # Get all events
        all_resp = client.get(f"/api/v1/runs/{run_id}/events")
        all_events = all_resp.json()
        assert len(all_events) >= 2

        # Get events after the first one
        first_seq = all_events[0]["sequence"]
        filtered_resp = client.get(f"/api/v1/runs/{run_id}/events?after_sequence={first_seq}")
        filtered_events = filtered_resp.json()

        assert len(filtered_events) < len(all_events)
        for evt in filtered_events:
            assert evt["sequence"] > first_seq

    def test_event_type_filter(self, client: Any) -> None:
        run_id = _create_and_wait(client)

        resp = client.get(
            f"/api/v1/runs/{run_id}/events?event_types=execution.started"
        )
        events = resp.json()
        assert len(events) >= 1
        for evt in events:
            assert evt["event_type"] == "execution.started"

    def test_empty_events_for_unknown_run(self, client: Any) -> None:
        resp = client.get("/api/v1/runs/nonexistent-id/events")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_multi_node_graph_produces_node_events(self, client: Any) -> None:
        run_id = _create_and_wait(client, graph_name="multi-graph")

        resp = client.get(f"/api/v1/runs/{run_id}/events")
        events = resp.json()
        event_types = [e["event_type"] for e in events]

        assert "node.started" in event_types
        assert "node.completed" in event_types


# ---------------------------------------------------------------------------
# GET /runs/{id}/state
# ---------------------------------------------------------------------------


class TestGetRunState:
    def test_returns_projected_state(self, client: Any) -> None:
        run_id = _create_and_wait(client)

        resp = client.get(f"/api/v1/runs/{run_id}/state")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == run_id
        assert "state" in data
        assert isinstance(data["state"], dict)
        assert data["event_count"] >= 1

    def test_state_includes_output(self, client: Any) -> None:
        run_id = _create_and_wait(client)

        resp = client.get(f"/api/v1/runs/{run_id}/state")
        state = resp.json()["state"]
        # The echo graph returns {"output": input}
        assert "output" in state

    def test_multi_node_state_has_all_updates(self, client: Any) -> None:
        run_id = _create_and_wait(client, graph_name="multi-graph")

        resp = client.get(f"/api/v1/runs/{run_id}/state")
        state = resp.json()["state"]
        assert state.get("step_a_done") is True
        assert state.get("step_b_done") is True
        assert state.get("output") == "final"

    def test_state_404_for_unknown_run(self, client: Any) -> None:
        resp = client.get("/api/v1/runs/nonexistent-id/state")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /runs/{id}/cost
# ---------------------------------------------------------------------------


class TestGetRunCost:
    def test_returns_cost_structure(self, client: Any) -> None:
        """Even with no LLM calls, endpoint should return valid zero-cost response."""
        run_id = _create_and_wait(client)

        resp = client.get(f"/api/v1/runs/{run_id}/cost")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == run_id
        assert "total_cost_usd" in data
        assert "total_tokens" in data
        assert "call_count" in data
        assert "by_model" in data
        assert "by_agent" in data
        assert isinstance(data["by_model"], dict)
        assert isinstance(data["by_agent"], dict)

    def test_zero_cost_for_function_only_graph(self, client: Any) -> None:
        """Function-only graphs have no LLM calls, so cost should be 0."""
        run_id = _create_and_wait(client)

        resp = client.get(f"/api/v1/runs/{run_id}/cost")
        data = resp.json()
        assert data["total_cost_usd"] == 0.0
        assert data["total_tokens"] == 0
        assert data["call_count"] == 0

    def test_cost_for_unknown_run_returns_zeros(self, client: Any) -> None:
        """Unknown run should still return 200 with zero values."""
        resp = client.get("/api/v1/runs/nonexistent-id/cost")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_cost_usd"] == 0.0
        assert data["call_count"] == 0


# ---------------------------------------------------------------------------
# POST /runs/{id}/cancel
# ---------------------------------------------------------------------------


class TestCancelRun:
    def test_cancel_running_task(self, client: Any) -> None:
        # Start a slow run that will still be running when we cancel
        resp = client.post(
            "/api/v1/runs",
            json={"graph_name": "slow-graph", "input": {}},
        )
        assert resp.status_code == 202
        run_id = resp.json()["run_id"]

        # Wait until the run is actually in running state before cancelling
        _wait_for_status(run_id, client, "running")

        # Cancel it
        cancel_resp = client.post(f"/api/v1/runs/{run_id}/cancel")
        assert cancel_resp.status_code == 200
        data = cancel_resp.json()
        assert data["run_id"] == run_id
        assert data["status"] == "cancelled"

    def test_cancel_completed_run_returns_409(self, client: Any) -> None:
        run_id = _create_and_wait(client)

        resp = client.post(f"/api/v1/runs/{run_id}/cancel")
        assert resp.status_code == 409
        assert "already" in resp.json()["detail"]

    def test_cancel_nonexistent_run_returns_404(self, client: Any) -> None:
        resp = client.post("/api/v1/runs/nonexistent-id/cancel")
        assert resp.status_code == 404

    def test_double_cancel_returns_409(self, client: Any) -> None:
        resp = client.post(
            "/api/v1/runs",
            json={"graph_name": "slow-graph", "input": {}},
        )
        run_id = resp.json()["run_id"]
        _wait_for_status(run_id, client, "running")

        # First cancel succeeds
        r1 = client.post(f"/api/v1/runs/{run_id}/cancel")
        assert r1.status_code == 200

        # Second cancel returns 409
        r2 = client.post(f"/api/v1/runs/{run_id}/cancel")
        assert r2.status_code == 409


# ---------------------------------------------------------------------------
# GET /runs — historical merge
# ---------------------------------------------------------------------------


class TestListRunsHistorical:
    def test_list_includes_completed_runs(self, client: Any) -> None:
        """Completed runs should appear in the list (not just active ones)."""
        run_id = _create_and_wait(client)

        resp = client.get("/api/v1/runs")
        assert resp.status_code == 200
        runs = resp.json()

        run_ids = [r["run_id"] for r in runs]
        assert run_id in run_ids

    def test_list_includes_workflow_name(self, client: Any) -> None:
        _create_and_wait(client)

        resp = client.get("/api/v1/runs")
        runs = resp.json()
        assert len(runs) >= 1

        # At least one run should have workflow_name populated
        has_name = any(r.get("workflow_name") for r in runs)
        assert has_name

    def test_run_status_includes_workflow_name(self, client: Any) -> None:
        run_id = _create_and_wait(client)

        resp = client.get(f"/api/v1/runs/{run_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "workflow_name" in data

    def test_multiple_runs_all_listed(self, client: Any) -> None:
        """Create several runs and verify they all appear."""
        ids = []
        for _ in range(3):
            ids.append(_create_and_wait(client, wait=0.3))

        resp = client.get("/api/v1/runs")
        listed_ids = {r["run_id"] for r in resp.json()}
        for run_id in ids:
            assert run_id in listed_ids


# ---------------------------------------------------------------------------
# Async versions of key tests (using aclient)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAsyncEndpoints:
    async def test_events_endpoint_async(self, aclient: AsyncClient) -> None:
        import asyncio

        create_resp = await aclient.post(
            "/api/v1/runs",
            json={"graph_name": "test-graph", "input": {"input": "async-test"}},
        )
        run_id = create_resp.json()["run_id"]
        await asyncio.sleep(0.5)

        resp = await aclient.get(f"/api/v1/runs/{run_id}/events")
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) >= 1

    async def test_state_endpoint_async(self, aclient: AsyncClient) -> None:
        import asyncio

        create_resp = await aclient.post(
            "/api/v1/runs",
            json={"graph_name": "test-graph", "input": {"input": "async-state"}},
        )
        run_id = create_resp.json()["run_id"]
        await asyncio.sleep(0.5)

        resp = await aclient.get(f"/api/v1/runs/{run_id}/state")
        assert resp.status_code == 200
        assert "state" in resp.json()

    async def test_cost_endpoint_async(self, aclient: AsyncClient) -> None:
        import asyncio

        create_resp = await aclient.post(
            "/api/v1/runs",
            json={"graph_name": "test-graph", "input": {"input": "async-cost"}},
        )
        run_id = create_resp.json()["run_id"]
        await asyncio.sleep(0.5)

        resp = await aclient.get(f"/api/v1/runs/{run_id}/cost")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == run_id
        assert "total_cost_usd" in data
