import asyncio
import tempfile
from datetime import UTC
from pathlib import Path

import pytest

from orchestra.cost.persistent_budget import (
    BudgetExceededError,
    CyclicHierarchyError,
    PersistentBudgetStore,
)


@pytest.fixture
async def memory_store():
    store = PersistentBudgetStore(":memory:")
    await store.initialize()
    yield store
    await store.close()


@pytest.mark.asyncio
async def test_create_account_and_check_balance(memory_store):
    await memory_store.create_account("t1", None, 10.0)

    remaining = await memory_store.get_remaining_usd("t1")
    assert remaining == 10.0

    state, config = await memory_store.get_state("t1")
    assert state.balance_usd == 0.0
    assert config.limit_usd == 10.0


@pytest.mark.asyncio
async def test_debit_reduces_remaining(memory_store):
    await memory_store.create_account("t1", None, 10.0)

    # Debit $2.5
    remaining = await memory_store.check_and_debit("t1", 2.5, "run-1", "m1", "k1")
    assert remaining == 7.5

    state, _ = await memory_store.get_state("t1")
    assert state.balance_usd == 2.5


@pytest.mark.asyncio
async def test_budget_exceeded_raises(memory_store):
    await memory_store.create_account("t1", None, 1.0)

    with pytest.raises(BudgetExceededError):
        await memory_store.check_and_debit("t1", 1.5, "run-1", "m1", "k1")


@pytest.mark.asyncio
async def test_idempotent_debit(memory_store):
    await memory_store.create_account("t1", None, 10.0)

    await memory_store.check_and_debit("t1", 2.0, "run-1", "m1", "k1")
    # Second call with same key should be ignored
    remaining = await memory_store.check_and_debit("t1", 2.0, "run-1", "m1", "k1")
    assert remaining == 8.0

    state, _ = await memory_store.get_state("t1")
    assert state.balance_usd == 2.0


@pytest.mark.asyncio
async def test_actual_cost_correction(memory_store):
    await memory_store.create_account("t1", None, 10.0)

    # Estimate $2.0
    await memory_store.check_and_debit("t1", 2.0, "run-1", "m1", "k1")

    # Actual was $1.5 (credit $0.5 back)
    await memory_store.adjust_actual("t1", "run-1", 1.5, "k2")

    remaining = await memory_store.get_remaining_usd("t1")
    assert remaining == 8.5

    state, _ = await memory_store.get_state("t1")
    assert state.balance_usd == 1.5


@pytest.mark.asyncio
async def test_hierarchy_parent_limit(memory_store):
    await memory_store.create_account("parent", None, 5.0)
    await memory_store.create_account("child", "parent", 10.0)

    # Child spends $3.0 - OK
    await memory_store.check_and_debit("child", 3.0, "r1", "m", "k1")

    # Child tries to spend another $3.0 - Fails because parent (5.0) exceeded
    with pytest.raises(BudgetExceededError) as exc:
        await memory_store.check_and_debit("child", 3.0, "r2", "m", "k2")
    assert exc.value.tenant_id == "parent"


@pytest.mark.asyncio
async def test_concurrent_debits_pessimistic_lock():
    # Use a real file for concurrency test to avoid :memory: connection sharing issues
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        store = PersistentBudgetStore(db_path)
        await store.initialize()
        await store.create_account("t1", None, 10.0)

        # Run 5 concurrent debits of $2.0
        tasks = [store.check_and_debit("t1", 2.0, f"run-{i}", "m", f"key-{i}") for i in range(6)]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, BudgetExceededError)]

        # With 10.0 limit and 2.0 debits, exactly 5 should succeed
        assert len(successes) == 5
        assert len(failures) == 1
        assert await store.get_remaining_usd("t1") == 0.0

        await store.close()
    finally:
        if Path(db_path).exists():
            Path(db_path).unlink()


@pytest.mark.asyncio
async def test_child_cannot_exceed_own_allocation(memory_store):
    await memory_store.create_account("parent", None, 100.0)
    await memory_store.create_account("child", "parent", 10.0)

    # Parent has 100, but child only has 10.
    # Debit 11.0 -> should fail.
    with pytest.raises(BudgetExceededError) as exc:
        await memory_store.check_and_debit("child", 11.0, "r1", "m", "k1")
    assert exc.value.tenant_id == "child"


@pytest.mark.asyncio
async def test_period_rollover_monthly(memory_store):
    from unittest.mock import patch

    # 1. Create account in Jan 2026
    with patch("orchestra.cost.persistent_budget.datetime") as mock_dt:
        from datetime import datetime

        mock_dt.now.return_value = datetime(2026, 1, 15, tzinfo=UTC)
        mock_dt.fromisoformat = datetime.fromisoformat  # Keep original

        await memory_store.create_account("t1", None, 10.0, reset_period="monthly")
        await memory_store.check_and_debit("t1", 4.0, "r1", "m", "k1")

        remaining = await memory_store.get_remaining_usd("t1")
        assert remaining == 6.0

    # 2. Advance to Feb 2026
    with patch("orchestra.cost.persistent_budget.datetime") as mock_dt:
        from datetime import datetime

        mock_dt.now.return_value = datetime(2026, 2, 1, tzinfo=UTC)
        mock_dt.fromisoformat = datetime.fromisoformat

        # This debit should trigger a rollover (new period YYYY-MM)
        # Note: PersistentBudgetStore doesn't automatically rollover on get_remaining_usd,
        # but check_and_debit should handle it via the recursive update.
        # Actually, let's check if the current implementation handles it.
        # My reading of persistent_budget.py:
        # _get_current_period() uses current time.
        # If period changes, budget_balances will get a new entry with spent_micro=0.

        remaining = await memory_store.get_remaining_usd("t1")
        assert remaining == 10.0  # New period!

        await memory_store.check_and_debit("t1", 2.0, "r2", "m", "k2")
        remaining = await memory_store.get_remaining_usd("t1")
        assert remaining == 8.0


@pytest.mark.asyncio
async def test_recursive_parent_debit_idempotency(memory_store):
    """Retried check_and_debit calls must not double-debit parent budgets (DD-12)."""
    # Hierarchy: grandparent (20.0) -> parent (10.0) -> child (5.0)
    await memory_store.create_account("grandparent", None, 20.0)
    await memory_store.create_account("parent", "grandparent", 10.0)
    await memory_store.create_account("child", "parent", 5.0)

    # First debit: $2.0 under idempotency key "idem-1"
    await memory_store.check_and_debit("child", 2.0, "run-1", "model-a", "idem-1")

    # Verify all three levels debited exactly once
    child_rem = await memory_store.get_remaining_usd("child")
    parent_rem = await memory_store.get_remaining_usd("parent")
    grandparent_rem = await memory_store.get_remaining_usd("grandparent")
    assert child_rem == 3.0
    assert parent_rem == 8.0
    assert grandparent_rem == 18.0

    # Retry with the same idempotency key — simulates a sub-agent re-submission
    await memory_store.check_and_debit("child", 2.0, "run-1", "model-a", "idem-1")

    # All balances must be unchanged after the retry
    assert await memory_store.get_remaining_usd("child") == 3.0
    assert await memory_store.get_remaining_usd("parent") == 8.0
    assert await memory_store.get_remaining_usd("grandparent") == 18.0

    # A genuinely new debit still works correctly
    await memory_store.check_and_debit("child", 1.0, "run-2", "model-a", "idem-2")
    assert await memory_store.get_remaining_usd("child") == 2.0
    assert await memory_store.get_remaining_usd("parent") == 7.0
    assert await memory_store.get_remaining_usd("grandparent") == 17.0


@pytest.mark.asyncio
async def test_tenant_hierarchy_cycle_detection(memory_store):
    """Circular parent references must raise CyclicHierarchyError, not hang."""
    # Set up two accounts without any parent link first
    await memory_store.create_account("alpha", None, 10.0)
    await memory_store.create_account("beta", "alpha", 10.0)

    # Manually introduce a cycle: alpha -> beta and beta -> alpha
    # by updating the parent_id of alpha to beta directly in the DB.
    async with memory_store.connection() as db:
        await db.execute("UPDATE budget_accounts SET parent_id = 'beta' WHERE tenant_id = 'alpha'")
        await db.commit()

    # Now alpha.parent_id = beta, beta.parent_id = alpha  →  cycle
    with pytest.raises(CyclicHierarchyError):
        await memory_store.check_and_debit("alpha", 1.0, "run-c", "model-x", "idem-cycle")
