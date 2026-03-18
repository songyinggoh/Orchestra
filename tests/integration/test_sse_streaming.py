"""Integration tests for SSE streaming endpoints.

These tests require server dependencies (fastapi, httpx, sse-starlette).
They are skipped automatically if dependencies are not installed.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import pytest

try:
    from fastapi.testclient import TestClient

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


def _make_slow_graph(name: str = "slow-graph", delay: float = 0.3) -> Any:
    """Build a graph with a short delay so we can observe streaming."""
    from orchestra.core.graph import WorkflowGraph

    async def step_one(state: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(delay / 2)
        return {"step": "one"}

    async def step_two(state: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(delay / 2)
        return {"output": "done"}

    graph = WorkflowGraph(name=name)
    graph.add_node("step_one", step_one)
    graph.add_node("step_two", step_two)
    graph.add_edge("step_one", "step_two")
    graph.set_entry_point("step_one")
    return graph.compile()


@pytest.fixture()
def app() -> Any:
    from orchestra.server.app import create_app
    from orchestra.server.config import ServerConfig

    config = ServerConfig(sse_heartbeat_interval=1)  # short heartbeat for tests
    return create_app(config)


@pytest.fixture()
def client(app: Any) -> Any:
    with TestClient(app, raise_server_exceptions=False) as c:
        graph = _make_slow_graph()
        app.state.graph_registry.register("slow-graph", graph)
        yield c


def _parse_sse_events(raw: str) -> list[dict[str, str]]:
    """Parse raw SSE text into a list of event dicts."""
    events: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("event:"):
            current["event"] = line[len("event:"):].strip()
        elif line.startswith("data:"):
            current["data"] = line[len("data:"):].strip()
        elif line.startswith("id:"):
            current["id"] = line[len("id:"):].strip()
        elif line == "" and current:
            events.append(current)
            current = {}
    if current:
        events.append(current)
    return events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_sse_stream_returns_events(client: Any) -> None:
    """Verify that streaming a run produces workflow events."""
    # Start a run
    create_resp = client.post(
        "/api/v1/runs",
        json={"graph_name": "slow-graph", "input": {"input": "stream-test"}},
    )
    assert create_resp.status_code == 202
    run_id = create_resp.json()["run_id"]

    # Stream events (TestClient blocks until generator is exhausted)
    with client.stream("GET", f"/api/v1/runs/{run_id}/stream") as response:
        assert response.status_code == 200
        # Read enough to see some events
        chunks: list[str] = []
        for chunk in response.iter_text():
            chunks.append(chunk)
            # Break after getting enough data or after timeout
            if "done" in chunk:
                break

    raw = "".join(chunks)
    events = _parse_sse_events(raw)

    # We should have at least a config event and a done event
    event_types = [e.get("event", "") for e in events]
    assert "config" in event_types
    assert "done" in event_types


def test_sse_reconnect_with_last_event_id(client: Any) -> None:
    """Verify that reconnecting with Last-Event-ID replays missed events."""
    # Start a run and let it complete
    create_resp = client.post(
        "/api/v1/runs",
        json={"graph_name": "slow-graph", "input": {"input": "reconnect-test"}},
    )
    run_id = create_resp.json()["run_id"]

    # Wait for run to complete
    time.sleep(1.0)

    # Now connect with Last-Event-ID = 0 (should replay events after sequence 0)
    with client.stream(
        "GET",
        f"/api/v1/runs/{run_id}/stream",
        headers={"Last-Event-ID": "0"},
    ) as response:
        assert response.status_code == 200
        chunks = []
        for chunk in response.iter_text():
            chunks.append(chunk)
            if "done" in chunk:
                break

    raw = "".join(chunks)
    events = _parse_sse_events(raw)

    # Should contain replayed events from the store
    assert len(events) >= 1


def test_sse_heartbeat(client: Any) -> None:
    """Verify heartbeat events are sent when no workflow events arrive.

    This test uses a graph that takes slightly longer than the heartbeat
    interval (set to 1s in the test fixture) to produce events.
    """
    from orchestra.core.graph import WorkflowGraph

    async def slow_step(state: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(2.0)
        return {"output": "finally"}

    graph = WorkflowGraph(name="very-slow")
    graph.add_node("slow", slow_step)
    graph.set_entry_point("slow")
    compiled = graph.compile()
    client._transport.app.state.graph_registry.register("very-slow", compiled)  # type: ignore[attr-defined]

    create_resp = client.post(
        "/api/v1/runs",
        json={"graph_name": "very-slow", "input": {}},
    )
    run_id = create_resp.json()["run_id"]

    with client.stream("GET", f"/api/v1/runs/{run_id}/stream") as response:
        chunks = []
        for chunk in response.iter_text():
            chunks.append(chunk)
            if "done" in chunk:
                break

    raw = "".join(chunks)
    events = _parse_sse_events(raw)
    event_types = [e.get("event", "") for e in events]

    # Should include at least one ping heartbeat
    assert "ping" in event_types
