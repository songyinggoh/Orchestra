import asyncio
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from orchestra.memory.tiers import TieredMemoryManager, Tier, TierStats
from orchestra.memory.backends import MemoryBackend

@pytest.fixture
def mock_warm():
    return AsyncMock(spec=MemoryBackend)

@pytest.fixture
def mock_cold():
    # ColdTierBackend protocol
    m = AsyncMock()
    return m

@pytest.mark.asyncio
async def test_tiered_memory_basic_flow():
    mgr = TieredMemoryManager(hot_max=2, warm_max=2)
    
    # Store k1 -> goes to policy (WARM by default)
    await mgr.store("k1", "v1")
    assert await mgr.retrieve("k1") == "v1"
    
    # Retrieval should promote to HOT
    stats = await mgr.stats()
    assert stats.hot_count == 1
    assert stats.warm_count == 0

@pytest.mark.asyncio
async def test_tiered_memory_hot_to_warm_demotion():
    mgr = TieredMemoryManager(hot_max=1, warm_max=2)
    
    await mgr.store("k1", "v1")
    await mgr.retrieve("k1") # promote to HOT
    
    await mgr.store("k2", "v2")
    await mgr.retrieve("k2") # promote to HOT, should demote k1
    
    stats = await mgr.stats()
    assert stats.hot_count == 1
    assert stats.warm_count == 1
    
    # k2 should be in HOT, k1 in WARM
    assert "k2" in mgr._policy._hot
    assert "k1" in mgr._policy._warm

@pytest.mark.asyncio
async def test_tiered_memory_warm_backend_fallthrough(mock_warm):
    mgr = TieredMemoryManager(warm_backend=mock_warm, hot_max=2, warm_max=2)
    
    # Simulate item only in Redis
    mock_warm.get.return_value = "redis_val"
    
    val = await mgr.retrieve("missing_locally")
    assert val == "redis_val"
    mock_warm.get.assert_called_with("missing_locally")
    
    # Should now be in HOT
    stats = await mgr.stats()
    assert stats.hot_count == 1

@pytest.mark.asyncio
async def test_tiered_memory_cold_backend_fallthrough(mock_cold, mock_warm):
    mgr = TieredMemoryManager(warm_backend=mock_warm, cold_backend=mock_cold, hot_max=2, warm_max=2)
    
    # Simulate item only in pgvector
    mock_warm.get.return_value = None
    mock_cold.retrieve.return_value = "cold_val"
    
    val = await mgr.retrieve("in_cold")
    assert val == "cold_val"
    
    # Should be back-filled to WARM backend and HOT
    mock_warm.set.assert_called_with("in_cold", "cold_val")
    assert "in_cold" in mgr._policy._hot

@pytest.mark.asyncio
async def test_tiered_memory_demote_to_cold(mock_cold, mock_warm):
    mgr = TieredMemoryManager(warm_backend=mock_warm, cold_backend=mock_cold, hot_max=1, warm_max=1)

    # Fill HOT and WARM
    await mgr.store("k1", "v1")
    await mgr.retrieve("k1") # k1 in HOT

    await mgr.store("k2", "v2") # k2 in WARM

    # Store k3 -> k2 should be evicted from WARM to COLD
    await mgr.store("k3", "v3")

    # We need to wait for demote() which calls cold.store
    # Actually store() calls it synchronously in my implementation
    mock_cold.store.assert_called()
    # Find the call for k2
    found = False
    for call in mock_cold.store.call_args_list:
        if call.args[0] == "k2":
            found = True
            break
    assert found is True


# ---------------------------------------------------------------------------
# CRITICAL-1.1: exception-suppression fixes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stats_cold_count_error_is_logged(mock_cold, caplog):
    """stats() must log and survive when cold_backend.count() raises."""
    mock_cold.count.side_effect = RuntimeError("db is down")
    mgr = TieredMemoryManager(cold_backend=mock_cold, hot_max=2, warm_max=2)

    with caplog.at_level(logging.ERROR, logger="orchestra.memory.tiers"):
        result = await mgr.stats()

    # Cold count falls back to 0 — method must not raise
    assert result.cold_count == 0
    # The failure must be visible in logs
    assert any("cold-tier count" in r.getMessage() for r in caplog.records), (
        "Expected error log about cold-tier count failure"
    )


@pytest.mark.asyncio
async def test_stats_cold_count_error_logs_traceback(mock_cold, caplog):
    """stats() must capture the full traceback, not just the message."""
    mock_cold.count.side_effect = RuntimeError("connection refused")
    mgr = TieredMemoryManager(cold_backend=mock_cold, hot_max=2, warm_max=2)

    with caplog.at_level(logging.ERROR, logger="orchestra.memory.tiers"):
        await mgr.stats()

    # caplog records exc_info when logger.exception() is used
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert error_records, "Expected at least one ERROR record"
    assert error_records[0].exc_info is not None, (
        "logger.exception() must capture exc_info for traceback visibility"
    )


@pytest.mark.asyncio
async def test_stop_cancelled_error_does_not_propagate():
    """stop() must absorb the expected CancelledError from its own cancel() call."""
    mgr = TieredMemoryManager(hot_max=2, warm_max=2, scan_interval=9999)
    await mgr.start()

    # Should complete without raising
    await mgr.stop()
    assert not mgr._initialized


@pytest.mark.asyncio
async def test_stop_unexpected_task_exception_is_logged(caplog):
    """stop() must log (not swallow) an unexpected exception from the scan task."""
    mgr = TieredMemoryManager(hot_max=2, warm_max=2, scan_interval=9999)
    await mgr.start()

    # Replace the real task with a fake one that raises a non-cancellation error
    boom = RuntimeError("unexpected scan failure")
    fake_task = AsyncMock()
    fake_task.cancel.return_value = True
    fake_task.__await__ = MagicMock(side_effect=boom)

    async def _raise():
        raise boom

    # Swap in a coroutine-based task stand-in
    cancelled_task = asyncio.ensure_future(_raise())
    # Let it run to completion (raising) so we can await it
    try:
        await cancelled_task
    except RuntimeError:
        pass

    mgr._scan_task = cancelled_task  # already done, raises on await

    with caplog.at_level(logging.ERROR, logger="orchestra.memory.tiers"):
        await mgr.stop()

    assert any("unexpected exception" in r.getMessage() for r in caplog.records), (
        "Expected error log about unexpected background task exception"
    )


@pytest.mark.asyncio
async def test_background_task_done_callback_installed():
    """start() must attach a done-callback to the background scan task."""
    mgr = TieredMemoryManager(hot_max=2, warm_max=2, scan_interval=9999)
    await mgr.start()

    assert mgr._scan_task is not None
    # asyncio.Task stores callbacks; verify at least one was added
    # (_log_task_exception is the one we registered)
    callbacks = mgr._scan_task._callbacks  # internal attribute, but stable across CPython 3.8+
    assert len(callbacks) >= 1, "Expected at least one done-callback on the scan task"

    await mgr.stop()


# ---------------------------------------------------------------------------
# CRITICAL-2.2: concurrent-access safety tests
#
# These tests confirm that the asyncio.Lock introduced in _policy_lock
# prevents check-then-use races between concurrent retrieve() coroutines
# and concurrent store() / demote() calls.
#
# Design note — why these tests are meaningful:
#   asyncio is single-threaded, but coroutines yield at every `await`.
#   Without the lock a concurrent coroutine could modify _hot or _warm
#   between the `key in self._policy._hot` check and the subsequent
#   `self._policy._hot[key].value` read, causing a KeyError.  The lock
#   collapses that window to a single uninterrupted critical section.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_retrieve_no_corruption():
    """50 concurrent retrieve() calls on the same key must all return the
    same value and must never raise KeyError or return a corrupted result."""
    mgr = TieredMemoryManager(hot_max=100, warm_max=100)

    # Pre-populate so the key is present in policy (WARM tier after store,
    # promoted to HOT after the first retrieve).
    await mgr.store("shared_key", "expected_value")

    results = await asyncio.gather(
        *[mgr.retrieve("shared_key") for _ in range(50)]
    )

    # Every coroutine must get the correct value — no None, no KeyError.
    assert all(r == "expected_value" for r in results), (
        f"Concurrent retrieve() returned unexpected values: {set(results)}"
    )


@pytest.mark.asyncio
async def test_concurrent_store_and_retrieve():
    """Interleaved stores and retrieves must not raise KeyError and must
    return either the stored value or None (key not yet visible)."""
    # Small tier limits to maximise eviction churn and lock contention.
    mgr = TieredMemoryManager(hot_max=5, warm_max=5)

    async def store_many():
        for i in range(30):
            await mgr.store(f"key_{i}", f"val_{i}")

    async def retrieve_many():
        errors = []
        for i in range(30):
            try:
                val = await mgr.retrieve(f"key_{i}")
                # val must be the correct string or None (not yet stored).
                assert val is None or val == f"val_{i}", (
                    f"key_{i} returned unexpected value: {val!r}"
                )
            except KeyError as exc:
                errors.append(exc)
        return errors

    errors_list = await asyncio.gather(store_many(), retrieve_many())
    # errors_list[0] is None (store_many returns None); errors_list[1] is the list.
    key_errors = errors_list[1]
    assert key_errors == [], (
        f"KeyError(s) raised during concurrent store+retrieve: {key_errors}"
    )


@pytest.mark.asyncio
async def test_promotion_under_concurrent_load():
    """Promotion between tiers (WARM -> HOT) while concurrent retrieves are
    in flight must not corrupt tier state or produce KeyErrors.

    Design:
      - 20 keys are seeded into a manager whose warm_max can hold all of them
        so no eviction to cold occurs (no cold backend is configured).
      - hot_max=3 means every promotion of a new key forces a HOT->WARM
        demotion of the LRU HOT entry, creating frequent in-memory state
        mutations that compete under concurrent retrieve() calls.
      - We verify: no exceptions, all values are correct, tier counts stay
        within configured maxima.
    """
    mgr = TieredMemoryManager(hot_max=3, warm_max=20)

    # Seed 20 keys — all land in WARM tier (warm_max=20 so no eviction).
    for i in range(20):
        await mgr.store(f"k{i}", f"v{i}")

    # Fire 60 concurrent retrieves across all 20 keys.  Each retrieve() may
    # promote its key from WARM to HOT and trigger a HOT->WARM demotion,
    # all while other coroutines are doing the same.
    keys = [f"k{i % 20}" for i in range(60)]
    results = await asyncio.gather(
        *[mgr.retrieve(k) for k in keys],
        return_exceptions=True,
    )

    # No coroutine should have raised any exception.
    exceptions = [r for r in results if isinstance(r, BaseException)]
    assert exceptions == [], (
        f"Exceptions raised during concurrent promotion: {exceptions}"
    )

    # Every result must be the correct value — no None, no corruption.
    for k, r in zip(keys, results):
        expected = f"v{int(k[1:])}"
        assert r == expected, f"{k} returned {r!r}, expected {expected!r}"

    # After all concurrent operations the policy must remain internally
    # consistent: hot + warm counts must not exceed their configured maxima.
    stats = await mgr.stats()
    assert stats.hot_count <= 3, (
        f"hot_count {stats.hot_count} exceeds hot_max=3 after concurrent promotion"
    )
    assert stats.warm_count <= 20, (
        f"warm_count {stats.warm_count} exceeds warm_max=20 after concurrent promotion"
    )
