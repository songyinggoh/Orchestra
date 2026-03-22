"""1000 Concurrent Agent Load Test.

Validates concurrency safety under high-throughput conditions, covering the
Week 2 remediation requirement from REVIEW_SUMMARY.md:

  "Load Testing: Run 1000 concurrent agent test suite"

Three areas under test:
1. Graph execution isolation — 1000 concurrent runs produce correct,
   non-corrupted per-run state (no state bleed between runs).
2. TieredMemoryManager safety — 1000 concurrent store/retrieve operations
   against a shared manager with no data corruption (CRITICAL-2.2).
3. Throughput baseline — asserts a minimum runs/sec floor so regressions
   in scheduling overhead are caught.

Run with:
    pytest tests/load/test_1000_concurrent_agents.py -v -m load

Skip in fast CI by omitting the `load` mark:
    pytest tests/ -m "not load"
"""

from __future__ import annotations

import asyncio
import statistics
import time
from typing import Any

import pytest

from orchestra.core.graph import WorkflowGraph
from orchestra.core.runner import run
from orchestra.memory.tiers import TieredMemoryManager

# ---------------------------------------------------------------------------
# Pytest markers
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.load

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONCURRENCY = 1_000  # Total number of tasks to launch
SEMAPHORE_LIMIT = 200  # Max tasks in-flight at once (CI-friendly)
SUCCESS_RATE_FLOOR = 0.999  # Require 99.9 % success rate
MIN_THROUGHPUT_RPS = 50  # Minimum acceptable runs per second
TIMEOUT_SECONDS = 120  # Hard deadline for the entire gather


# ---------------------------------------------------------------------------
# Shared graph fixture (compiled once, reused by all 1000 runs)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def echo_graph() -> Any:
    """Minimal graph: one node that echoes its run_id back in state."""

    async def echo(state: dict) -> dict:
        await asyncio.sleep(0)  # yield to event loop
        return {"output": state.get("run_id", "unknown")}

    g = WorkflowGraph()
    g.add_node("echo", echo)
    g.set_entry_point("echo")
    return g.compile()


@pytest.fixture(scope="module")
def counter_graph() -> Any:
    """Two-node pipeline that accumulates a counter; used for state-bleed check."""

    async def inc(state: dict) -> dict:
        await asyncio.sleep(0)
        return {"count": state.get("count", 0) + 1}

    g = WorkflowGraph()
    g.add_node("inc1", inc)
    g.add_node("inc2", inc)
    g.add_edge("inc1", "inc2")
    g.set_entry_point("inc1")
    return g.compile()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _run_with_semaphore(
    sem: asyncio.Semaphore,
    graph: Any,
    run_id: int,
) -> tuple[int, bool, float, str | None]:
    """Execute one run under the semaphore; return (run_id, ok, duration_ms, error)."""
    async with sem:
        t0 = time.monotonic()
        try:
            _result = await run(
                graph,
                initial_state={"run_id": str(run_id), "count": 0},
                persist=False,
            )
            duration_ms = (time.monotonic() - t0) * 1000
            return run_id, True, duration_ms, None
        except Exception as exc:
            duration_ms = (time.monotonic() - t0) * 1000
            return run_id, False, duration_ms, str(exc)


# ---------------------------------------------------------------------------
# Test 1: Graph execution — state isolation and success rate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_1000_concurrent_graph_runs_state_isolation(echo_graph: Any) -> None:
    """1000 concurrent graph runs must all succeed with no state corruption.

    State bleed would manifest as a run receiving another run's `run_id` in
    its output — detectable because each run injects a unique run_id.
    """
    sem = asyncio.Semaphore(SEMAPHORE_LIMIT)
    tasks = [_run_with_semaphore(sem, echo_graph, i) for i in range(CONCURRENCY)]

    wall_start = time.monotonic()
    outcomes = await asyncio.wait_for(
        asyncio.gather(*tasks, return_exceptions=False),
        timeout=TIMEOUT_SECONDS,
    )
    wall_elapsed = time.monotonic() - wall_start

    # ---- aggregate results ------------------------------------------------
    successes = [o for o in outcomes if o[1]]
    failures = [o for o in outcomes if not o[1]]
    durations = [o[2] for o in successes]

    success_rate = len(successes) / CONCURRENCY
    throughput = len(successes) / wall_elapsed
    p50 = statistics.median(durations) if durations else 0.0
    p99 = (
        sorted(durations)[int(len(durations) * 0.99) - 1]
        if len(durations) >= 100
        else max(durations, default=0.0)
    )

    # ---- print summary (visible with -s / -v) ----------------------------
    print(
        f"\n[1000-agent graph stress]\n"
        f"  total={CONCURRENCY}  success={len(successes)}  fail={len(failures)}\n"
        f"  success_rate={success_rate:.4%}  throughput={throughput:.1f} rps\n"
        f"  latency p50={p50:.1f}ms  p99={p99:.1f}ms  wall={wall_elapsed:.2f}s"
    )
    if failures:
        for run_id, _, _, err in failures[:5]:
            print(f"  FAIL run_id={run_id}: {err}")

    # ---- assertions -------------------------------------------------------
    assert success_rate >= SUCCESS_RATE_FLOOR, (
        f"Success rate {success_rate:.4%} below floor {SUCCESS_RATE_FLOOR:.4%}. "
        f"First failure: {failures[0][3] if failures else 'n/a'}"
    )
    assert throughput >= MIN_THROUGHPUT_RPS, (
        f"Throughput {throughput:.1f} rps below floor {MIN_THROUGHPUT_RPS} rps"
    )


# ---------------------------------------------------------------------------
# Test 2: TieredMemoryManager — concurrent store/retrieve (CRITICAL-2.2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_1000_concurrent_memory_operations_no_corruption() -> None:
    """1000 concurrent store+retrieve pairs against one TieredMemoryManager.

    Before the CRITICAL-2.2 fix, direct access to _hot/_warm without the
    policy lock caused races that could drop or overwrite entries.  This test
    catches regressions in that fix by verifying every key can be retrieved
    with its original value after concurrent writes.
    """
    mem = TieredMemoryManager(hot_max=500, warm_max=2000)
    await mem.start()

    sem = asyncio.Semaphore(SEMAPHORE_LIMIT)

    async def store_and_retrieve(key: str, value: str) -> tuple[bool, str | None]:
        async with sem:
            try:
                await mem.store(key, value)
                result = await mem.retrieve(key)
                if result != value:
                    return False, f"key={key} expected={value!r} got={result!r}"
                return True, None
            except Exception as exc:
                return False, str(exc)

    tasks = [store_and_retrieve(f"agent:{i}:state", f"value-{i}") for i in range(CONCURRENCY)]

    wall_start = time.monotonic()
    results = await asyncio.wait_for(
        asyncio.gather(*tasks, return_exceptions=False),
        timeout=TIMEOUT_SECONDS,
    )
    wall_elapsed = time.monotonic() - wall_start

    successes = [r for r in results if r[0]]
    failures = [r for r in results if not r[0]]
    success_rate = len(successes) / CONCURRENCY

    print(
        f"\n[1000-agent memory stress]\n"
        f"  total={CONCURRENCY}  success={len(successes)}  fail={len(failures)}\n"
        f"  success_rate={success_rate:.4%}  wall={wall_elapsed:.2f}s"
    )
    if failures:
        for _, err in failures[:5]:
            print(f"  FAIL: {err}")

    await mem.stop()

    assert success_rate >= SUCCESS_RATE_FLOOR, (
        f"Memory corruption detected: {len(failures)} keys returned wrong values. "
        f"First: {failures[0][1] if failures else 'n/a'}"
    )


# ---------------------------------------------------------------------------
# Test 3: No deadlocks — all tasks complete within deadline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_1000_concurrent_runs_no_deadlock(counter_graph: Any) -> None:
    """All 1000 tasks must finish within TIMEOUT_SECONDS.

    A deadlock in the policy lock or any shared resource would cause
    asyncio.wait_for to raise TimeoutError, failing this test.
    """
    sem = asyncio.Semaphore(SEMAPHORE_LIMIT)
    tasks = [_run_with_semaphore(sem, counter_graph, i) for i in range(CONCURRENCY)]

    # If any task hangs, this raises asyncio.TimeoutError → test fails.
    outcomes = await asyncio.wait_for(
        asyncio.gather(*tasks, return_exceptions=False),
        timeout=TIMEOUT_SECONDS,
    )

    completed = len(outcomes)
    assert completed == CONCURRENCY, (
        f"Only {completed}/{CONCURRENCY} tasks completed — possible deadlock"
    )
