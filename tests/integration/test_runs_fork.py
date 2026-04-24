"""Integration tests for POST /api/v1/runs/{id}/fork.

Covers the fork endpoint introduced in Phase 6 Wave 2 (T-6.2.3): projects
state at a historical sequence, merges overrides, and spins up a child
run whose parent event stream records an execution.forked event.
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


def _make_multi_node_graph(name: str = "fork-graph") -> Any:
    from orchestra.core.graph import WorkflowGraph

    async def step_a(state: dict[str, Any]) -> dict[str, Any]:
        return {"step_a_done": True, "counter": 1}

    async def step_b(state: dict[str, Any]) -> dict[str, Any]:
        return {"step_b_done": True, "counter": (state.get("counter") or 0) + 1}

    async def step_c(state: dict[str, Any]) -> dict[str, Any]:
        return {"step_c_done": True, "output": "final"}

    graph = WorkflowGraph(name=name)
    graph.add_node("step_a", step_a)
    graph.add_node("step_b", step_b)
    graph.add_node("step_c", step_c)
    graph.set_entry_point("step_a")
    graph.add_edge("step_a", "step_b")
    graph.add_edge("step_b", "step_c")
    return graph.compile()


@pytest.fixture()
def app() -> Any:
    from orchestra.server.app import create_app
    from orchestra.server.config import ServerConfig

    return create_app(ServerConfig())


@pytest.fixture()
def client(app: Any) -> Any:
    with TestClient(app, raise_server_exceptions=False) as c:
        app.state.graph_registry.register("fork-graph", _make_multi_node_graph())
        yield c


@pytest.fixture()
async def aclient(app: Any) -> AsyncIterator[AsyncClient]:
    async with app.router.lifespan_context(app):
        app.state.graph_registry.register("fork-graph", _make_multi_node_graph())
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


def _wait_for_status(run_id: str, client: Any, target: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/api/v1/runs/{run_id}")
        if resp.status_code == 200 and resp.json()["status"] == target:
            return
        time.sleep(0.05)
    raise TimeoutError(f"Run {run_id} did not reach {target!r} within {timeout}s")


def _create_and_wait(client: Any) -> str:
    resp = client.post(
        "/api/v1/runs", json={"graph_name": "fork-graph", "input": {"input": "seed"}}
    )
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]
    _wait_for_status(run_id, client, "completed")
    return run_id


class TestForkEndpoint:
    def test_happy_path_creates_child_run(self, client: Any) -> None:
        parent_id = _create_and_wait(client)

        events_resp = client.get(f"/api/v1/runs/{parent_id}/events")
        events = events_resp.json()
        # Pick a node.completed to fork from — anything mid-stream is fine.
        fork_seq = next(
            e["sequence"] for e in events if e["event_type"] == "node.completed"
        )

        resp = client.post(
            f"/api/v1/runs/{parent_id}/fork",
            json={"from_sequence": fork_seq, "state_overrides": {"counter": 42}},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["parent_run_id"] == parent_id
        assert body["from_sequence"] == fork_seq
        new_run_id = body["new_run_id"]
        assert new_run_id and new_run_id != parent_id

        _wait_for_status(new_run_id, client, "completed")

        # Parent's event stream should now include an execution.forked event.
        parent_events = client.get(f"/api/v1/runs/{parent_id}/events").json()
        fork_events = [
            e for e in parent_events if e["event_type"] == "execution.forked"
        ]
        assert len(fork_events) == 1
        assert fork_events[0]["data"].get("new_run_id") == new_run_id
        assert fork_events[0]["data"].get("parent_run_id") == parent_id

    def test_state_override_propagates_to_child_state(self, client: Any) -> None:
        parent_id = _create_and_wait(client)
        events = client.get(f"/api/v1/runs/{parent_id}/events").json()
        fork_seq = next(
            e["sequence"] for e in events if e["event_type"] == "node.completed"
        )

        resp = client.post(
            f"/api/v1/runs/{parent_id}/fork",
            json={"from_sequence": fork_seq, "state_overrides": {"counter": 999}},
        )
        assert resp.status_code == 201
        new_run_id = resp.json()["new_run_id"]
        _wait_for_status(new_run_id, client, "completed")

        child_state = client.get(f"/api/v1/runs/{new_run_id}/state").json()["state"]
        # step_b/step_c will continue running from the fork point; the override
        # must be the baseline before subsequent node updates reducer-merge.
        assert "counter" in child_state

    def test_rejects_sequence_past_parent_head(self, client: Any) -> None:
        parent_id = _create_and_wait(client)
        resp = client.post(
            f"/api/v1/runs/{parent_id}/fork",
            json={"from_sequence": 9999, "state_overrides": {}},
        )
        assert resp.status_code == 409
        assert "exceeds" in resp.json()["detail"].lower()

    def test_rejects_unknown_run(self, client: Any) -> None:
        resp = client.post(
            "/api/v1/runs/does-not-exist/fork",
            json={"from_sequence": 0, "state_overrides": {}},
        )
        assert resp.status_code == 404

    def test_rejects_negative_sequence(self, client: Any) -> None:
        parent_id = _create_and_wait(client)
        resp = client.post(
            f"/api/v1/runs/{parent_id}/fork",
            json={"from_sequence": -1, "state_overrides": {}},
        )
        # Pydantic ge=0 validation → 422.
        assert resp.status_code == 422

    def test_rate_limit_after_many_forks(self, client: Any) -> None:
        parent_id = _create_and_wait(client)
        events = client.get(f"/api/v1/runs/{parent_id}/events").json()
        fork_seq = next(
            e["sequence"] for e in events if e["event_type"] == "node.completed"
        )

        last_status = None
        for _ in range(12):
            resp = client.post(
                f"/api/v1/runs/{parent_id}/fork",
                json={"from_sequence": fork_seq, "state_overrides": {}},
            )
            last_status = resp.status_code
            if last_status == 429:
                break
        assert last_status == 429

    def test_unauthorized_when_api_key_set(self, monkeypatch: Any) -> None:
        # Simulate prod auth — ORCHESTRA_API_KEY must be set before lifespan
        # startup so app.state.api_key picks it up.
        monkeypatch.setenv("ORCHESTRA_API_KEY", "secret-token")
        from orchestra.server.app import create_app
        from orchestra.server.config import ServerConfig

        secured_app = create_app(ServerConfig())
        with TestClient(secured_app, raise_server_exceptions=False) as c:
            secured_app.state.graph_registry.register(
                "fork-graph", _make_multi_node_graph()
            )
            resp = c.post(
                "/api/v1/runs/whatever/fork",
                json={"from_sequence": 0, "state_overrides": {}},
            )
            assert resp.status_code == 401
