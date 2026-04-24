"""Integration tests for ParallelEdge join_node serialization in GET /graphs (T-6.3.2a)."""

from __future__ import annotations

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


def _make_parallel_graph() -> Any:
    """Build a graph with a ParallelEdge that has a join_node."""
    from orchestra.core.graph import WorkflowGraph
    from orchestra.core.types import END

    async def dispatcher(state: dict) -> dict:
        return {}

    async def worker_a(state: dict) -> dict:
        return {}

    async def worker_b(state: dict) -> dict:
        return {}

    async def joiner(state: dict) -> dict:
        return {}

    graph = WorkflowGraph(name="parallel-test")
    graph.add_node("dispatch", dispatcher)
    graph.add_node("worker_a", worker_a)
    graph.add_node("worker_b", worker_b)
    graph.add_node("join", joiner)
    graph.set_entry_point("dispatch")
    graph.add_parallel("dispatch", ["worker_a", "worker_b"], join_node="join")
    graph.add_edge("join", END)
    return graph.compile()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app() -> Any:
    from orchestra.server.app import create_app
    from orchestra.server.config import ServerConfig

    return create_app(ServerConfig())


@pytest.fixture()
def client(app: Any) -> Any:
    with TestClient(app, raise_server_exceptions=False) as c:
        graph = _make_parallel_graph()
        app.state.graph_registry.register("parallel-test", graph)
        yield c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_parallel_edge_join_node_present_in_graph_response(client: Any) -> None:
    resp = client.get("/api/v1/graphs/parallel-test")
    assert resp.status_code == 200
    data = resp.json()
    parallel_edges = [e for e in data["edges"] if e["type"] == "ParallelEdge"]
    assert len(parallel_edges) >= 1, "Expected at least one ParallelEdge"
    pe = parallel_edges[0]
    assert "join_node" in pe, "join_node field missing from ParallelEdge response"
    assert pe["join_node"] == "join", f"Expected 'join', got {pe['join_node']!r}"


def test_parallel_edge_targets_in_graph_response(client: Any) -> None:
    resp = client.get("/api/v1/graphs/parallel-test")
    assert resp.status_code == 200
    data = resp.json()
    parallel_edges = [e for e in data["edges"] if e["type"] == "ParallelEdge"]
    pe = parallel_edges[0]
    assert isinstance(pe.get("target"), list), "ParallelEdge target should be a list"
    assert set(pe["target"]) == {"worker_a", "worker_b"}


def test_graph_list_endpoint_includes_parallel_graph(client: Any) -> None:
    resp = client.get("/api/v1/graphs")
    assert resp.status_code == 200
    names = [g["name"] for g in resp.json()]
    assert "parallel-test" in names


def test_nonexistent_graph_returns_404(client: Any) -> None:
    resp = client.get("/api/v1/graphs/does-not-exist")
    assert resp.status_code == 404
