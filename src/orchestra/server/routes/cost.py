"""Cost aggregation endpoint."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from orchestra.server.dependencies import get_event_store
from orchestra.server.models import CostAggregateEntry, CostAggregateResponse
from orchestra.storage.events import EventType

router = APIRouter(prefix="/cost", tags=["cost"])

_GROUP_BY_LITERAL = Literal["model", "agent", "graph", "week"]


@router.get("/aggregate", response_model=CostAggregateResponse)
async def aggregate_cost(
    request: Request,
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    group_by: _GROUP_BY_LITERAL = Query("model"),
) -> CostAggregateResponse:
    """Return cost aggregated by the requested dimension and date window.

    Query params:
        from: Start date inclusive (YYYY-MM-DD).
        to:   End date inclusive (YYYY-MM-DD).
        group_by: Dimension — model | agent | graph | week (ISO-week bucket).

    Validation:
        - from must be <= to.
        - Window must not exceed 365 days.
    """
    if from_date > to_date:
        raise HTTPException(status_code=422, detail="'from' must be <= 'to'.")
    if (to_date - from_date).days > 365:
        raise HTTPException(status_code=422, detail="Date window must not exceed 365 days.")

    event_store = get_event_store(request)

    # Load all llm.called events and filter by date window.
    from orchestra.cost.registry import ModelCostRegistry
    from orchestra.storage.events import LLMCalled

    registry = ModelCostRegistry()

    # Fetch llm.called events across all runs (no run_id filter).
    # EventStore's get_events is per-run; use list_runs to iterate.
    stored_runs = await event_store.list_runs(limit=10_000)

    buckets: dict[str, dict[str, float | int]] = {}
    total_cost = 0.0
    total_in = 0
    total_out = 0
    total_calls = 0

    from_dt = from_date.isoformat()
    to_dt = (to_date + timedelta(days=1)).isoformat()  # exclusive upper bound

    for run_record in stored_runs:
        # Quick date pre-filter using run start time.
        run_start = run_record.started_at or ""
        if run_start and (run_start[:10] > to_date.isoformat() or run_start[:10] < from_dt[:10]):
            # Run started outside window — but some events might still be in window.
            # Keep for safety; server-side date filter is per-event below.
            pass

        events = await event_store.get_events(run_record.run_id, event_types=[EventType.LLM_CALLED])
        for e in events:
            if not isinstance(e, LLMCalled):
                continue
            ts = e.timestamp.isoformat() if hasattr(e.timestamp, "isoformat") else str(e.timestamp)
            if ts < from_dt or ts >= to_dt:
                continue

            model = e.model or ""
            agent = e.agent_name or ""
            inp = e.input_tokens or 0
            out = e.output_tokens or 0
            cost = registry.calculate_cost(model, inp, out)

            total_cost += cost
            total_in += inp
            total_out += out
            total_calls += 1

            if group_by == "model":
                key = model or "(unknown)"
            elif group_by == "agent":
                key = agent or "(unknown)"
            elif group_by == "graph":
                key = run_record.workflow_name or "(unknown)"
            else:  # week
                ts_date = date.fromisoformat(ts[:10])
                iso_week = ts_date.isocalendar()
                key = f"{iso_week.year}-W{iso_week.week:02d}"

            if key not in buckets:
                buckets[key] = {"cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "call_count": 0}
            buckets[key]["cost_usd"] += cost
            buckets[key]["input_tokens"] += inp
            buckets[key]["output_tokens"] += out
            buckets[key]["call_count"] += 1

    entries = [
        CostAggregateEntry(
            key=k,
            cost_usd=v["cost_usd"],
            input_tokens=int(v["input_tokens"]),
            output_tokens=int(v["output_tokens"]),
            call_count=int(v["call_count"]),
        )
        for k, v in sorted(buckets.items(), key=lambda x: -x[1]["cost_usd"])
    ]

    return CostAggregateResponse(
        from_date=from_date.isoformat(),
        to_date=to_date.isoformat(),
        group_by=group_by,
        entries=entries,
        total=CostAggregateEntry(
            key="__total__",
            cost_usd=total_cost,
            input_tokens=total_in,
            output_tokens=total_out,
            call_count=total_calls,
        ),
    )
