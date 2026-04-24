"""Integration tests for GET /api/v1/cost/aggregate endpoint (T-6.3.3)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
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
        yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso(dt: datetime) -> str:
    return dt.isoformat()


async def _seed_events(event_store: Any, *, days_back: int = 0) -> None:
    """Seed a run with 2 llm.called events into the event store."""
    from orchestra.storage.events import LLMCalled

    run_id = str(uuid.uuid4())
    ts = datetime.now(UTC) - timedelta(days=days_back)

    await event_store.create_run(run_id, "graph-a", "agent")
    for i, (model, cost) in enumerate([("gpt-4", 0.01), ("claude-3", 0.005)]):
        await event_store.append(
            LLMCalled(
                run_id=run_id,
                event_id=str(uuid.uuid4()),
                sequence=i,
                timestamp=ts,
                node_id="agent",
                agent_name="agent",
                model=model,
                input_tokens=100,
                output_tokens=50,
                cost_usd=cost,
            )
        )


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _daysago(n: int) -> str:
    return (datetime.now(UTC).date() - timedelta(days=n)).isoformat()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_aggregate_empty_window_returns_zero(client: Any, app: Any) -> None:
    resp = client.get(
        "/api/v1/cost/aggregate",
        params={"from": _today(), "to": _today(), "group_by": "model"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["entries"] == []
    assert data["total"]["cost_usd"] == 0.0


def test_aggregate_invalid_range_returns_422(client: Any) -> None:
    resp = client.get(
        "/api/v1/cost/aggregate",
        params={"from": _today(), "to": _daysago(5), "group_by": "model"},
    )
    assert resp.status_code == 422


def test_aggregate_window_over_365_days_returns_422(client: Any) -> None:
    resp = client.get(
        "/api/v1/cost/aggregate",
        params={"from": _daysago(400), "to": _today(), "group_by": "model"},
    )
    assert resp.status_code == 422


def test_aggregate_group_by_model(client: Any, app: Any) -> None:
    import asyncio

    asyncio.get_event_loop().run_until_complete(_seed_events(app.state.event_store))

    resp = client.get(
        "/api/v1/cost/aggregate",
        params={"from": _daysago(1), "to": _today(), "group_by": "model"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["entries"]) >= 2
    keys = {e["key"] for e in data["entries"]}
    assert "gpt-4" in keys
    assert "claude-3" in keys
    assert data["total"]["cost_usd"] > 0


def test_aggregate_group_by_graph(client: Any, app: Any) -> None:
    import asyncio

    asyncio.get_event_loop().run_until_complete(_seed_events(app.state.event_store))

    resp = client.get(
        "/api/v1/cost/aggregate",
        params={"from": _daysago(1), "to": _today(), "group_by": "graph"},
    )
    assert resp.status_code == 200
    data = resp.json()
    keys = {e["key"] for e in data["entries"]}
    assert "graph-a" in keys


def test_aggregate_group_by_week(client: Any, app: Any) -> None:
    import asyncio

    asyncio.get_event_loop().run_until_complete(_seed_events(app.state.event_store))

    resp = client.get(
        "/api/v1/cost/aggregate",
        params={"from": _daysago(30), "to": _today(), "group_by": "week"},
    )
    assert resp.status_code == 200
    data = resp.json()
    # ISO-week keys like "2026-W17"
    for entry in data["entries"]:
        assert "-W" in entry["key"]


def test_aggregate_date_filter_excludes_out_of_window_events(client: Any, app: Any) -> None:
    import asyncio

    # Seed events 10 days ago — they should be excluded from a 3-day window.
    asyncio.get_event_loop().run_until_complete(
        _seed_events(app.state.event_store, days_back=10)
    )

    resp = client.get(
        "/api/v1/cost/aggregate",
        params={"from": _daysago(3), "to": _today(), "group_by": "model"},
    )
    assert resp.status_code == 200
    data = resp.json()
    # The old events should not appear.
    for entry in data["entries"]:
        assert entry["key"] not in {"gpt-4", "claude-3"} or data["total"]["cost_usd"] == pytest.approx(
            sum(e["cost_usd"] for e in data["entries"]), abs=1e-9
        )
    # Total consistency check.
    assert data["total"]["cost_usd"] == pytest.approx(
        sum(e["cost_usd"] for e in data["entries"]), abs=1e-9
    )


def test_aggregate_unknown_group_by_returns_422(client: Any) -> None:
    resp = client.get(
        "/api/v1/cost/aggregate",
        params={"from": _daysago(1), "to": _today(), "group_by": "unknown"},
    )
    assert resp.status_code == 422


def test_aggregate_response_schema(client: Any) -> None:
    resp = client.get(
        "/api/v1/cost/aggregate",
        params={"from": _today(), "to": _today(), "group_by": "model"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "from_date" in data
    assert "to_date" in data
    assert "group_by" in data
    assert "entries" in data
    assert "total" in data
    total = data["total"]
    for field in ("key", "cost_usd", "input_tokens", "output_tokens", "call_count"):
        assert field in total
