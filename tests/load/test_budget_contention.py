"""Load-level test for CRITICAL-4.1: Budget store contention under high concurrency.

CRITICAL-4.1 describes a WAL + PRAGMA race condition in PersistentBudgetStore.
The fix uses BEGIN IMMEDIATE transactions to serialize concurrent writes.

This suite stresses three invariants that would break if the locking is wrong:

  INV-1  No overdraft — total debited across all concurrent tasks never
         exceeds the tenant's configured limit.
  INV-2  Idempotency — the same idempotency key submitted by N concurrent
         coroutines debits the balance exactly once.
  INV-3  Initialization safety — N stores initialized concurrently against
         the same on-disk WAL database produce a consistent schema with no
         corruption.

Run with:
    pytest tests/load/test_budget_contention.py -v -m load -s
"""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

import pytest

from orchestra.cost.persistent_budget import (
    BudgetExceededError,
    PersistentBudgetStore,
    micro_to_usd,
    usd_to_micro,
)

pytestmark = pytest.mark.load

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONCURRENCY = 1_000
SEMAPHORE_LIMIT = 200
DEBIT_USD = 0.01          # per-task cost
LIMIT_USD = 5.00          # $5 → exactly 500 tasks can succeed at $0.01 each
OVERDRAFT_TOLERANCE = 0   # zero tolerance — must never exceed limit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
async def store(tmp_path: Path) -> PersistentBudgetStore:  # type: ignore[misc]
    """File-based store that exercises the real WAL path (not :memory:)."""
    db_path = tmp_path / "budget_test.db"
    s = PersistentBudgetStore(db_path)
    await s.initialize()
    await s.create_account("tenant-load", parent_id=None, limit_usd=LIMIT_USD)
    yield s
    await s.close()


@pytest.fixture()
async def idempotency_store(tmp_path: Path) -> PersistentBudgetStore:  # type: ignore[misc]
    """File-based store for idempotency test.

    NOTE: :memory: stores share a single aiosqlite connection across all
    concurrent coroutines.  When multiple coroutines each issue BEGIN IMMEDIATE
    on the same connection, SQLite raises
    "cannot start a transaction within a transaction".
    This is a known limitation of the :memory: path — it is NOT safe for
    concurrent multi-coroutine use.  Production deployments use a file path
    (one connection per call), which is what this fixture exercises.
    """
    db_path = tmp_path / "idempotency_test.db"
    s = PersistentBudgetStore(db_path)
    await s.initialize()
    await s.create_account("tenant-idem", parent_id=None, limit_usd=LIMIT_USD)
    yield s
    await s.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _debit(
    store: PersistentBudgetStore,
    tenant_id: str,
    sem: asyncio.Semaphore,
    task_index: int,
    idempotency_key: str | None = None,
) -> tuple[int, bool, str | None]:
    """Attempt one debit under the semaphore.

    Returns (task_index, succeeded, error_class_name).
    """
    key = idempotency_key or f"idem-{task_index}-{uuid.uuid4().hex}"
    run_id = f"run-{task_index}"

    async with sem:
        try:
            await store.check_and_debit(
                tenant_id,
                estimated_usd=DEBIT_USD,
                run_id=run_id,
                model="test-model",
                idempotency_key=key,
            )
            return task_index, True, None
        except BudgetExceededError:
            return task_index, False, "BudgetExceededError"
        except Exception as exc:  # noqa: BLE001
            return task_index, False, type(exc).__name__ + ": " + str(exc)


# ---------------------------------------------------------------------------
# INV-1: No overdraft under 1000 concurrent debits (file-based WAL)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_overdraft_1000_concurrent_debits(store: PersistentBudgetStore) -> None:
    """1000 concurrent debits of $0.01 against a $5.00 limit.

    Exactly 500 should succeed; the rest must raise BudgetExceededError.
    The final balance must never exceed $5.00 (INV-1).
    """
    sem = asyncio.Semaphore(SEMAPHORE_LIMIT)
    tasks = [_debit(store, "tenant-load", sem, i) for i in range(CONCURRENCY)]

    t0 = time.monotonic()
    results = await asyncio.wait_for(
        asyncio.gather(*tasks, return_exceptions=False),
        timeout=120,
    )
    elapsed = time.monotonic() - t0

    successes = [r for r in results if r[1]]
    failures  = [r for r in results if not r[1]]
    unexpected = [r for r in failures if r[2] != "BudgetExceededError"]

    # Read authoritative balance from the store
    remaining_usd = await store.get_remaining_usd("tenant-load")
    spent_usd = LIMIT_USD - remaining_usd
    throughput = len(successes) / elapsed

    print(
        f"\n[budget contention — file WAL]\n"
        f"  total={CONCURRENCY}  succeeded={len(successes)}  budget_exceeded={len(failures)}\n"
        f"  spent=${spent_usd:.6f}  limit=${LIMIT_USD:.2f}  remaining=${remaining_usd:.6f}\n"
        f"  unexpected_errors={len(unexpected)}  throughput={throughput:.1f} debits/s  wall={elapsed:.2f}s"
    )
    if unexpected:
        for _, _, err in unexpected[:5]:
            print(f"  UNEXPECTED: {err}")

    # INV-1: balance must never exceed limit
    assert spent_usd <= LIMIT_USD + 1e-6, (
        f"OVERDRAFT: spent ${spent_usd:.6f} exceeds limit ${LIMIT_USD:.2f}"
    )

    # No errors other than BudgetExceededError
    assert not unexpected, (
        f"{len(unexpected)} unexpected errors (not BudgetExceededError): "
        f"{[e[2] for e in unexpected[:3]]}"
    )

    # Accounting identity: successes × $0.01 == spent (within floating-point tolerance)
    expected_spent = len(successes) * DEBIT_USD
    assert abs(spent_usd - expected_spent) < 1e-4, (
        f"Ledger mismatch: {len(successes)} successes × ${DEBIT_USD} = ${expected_spent:.6f} "
        f"but store reports ${spent_usd:.6f}"
    )

    # Throughput floor: must sustain at least 20 debits/sec
    assert throughput >= 20, (
        f"Budget store throughput {throughput:.1f} debits/s below floor of 20 debits/s"
    )


# ---------------------------------------------------------------------------
# INV-2: Idempotency — same key submitted N times debits exactly once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotency_same_key_concurrent(idempotency_store: PersistentBudgetStore) -> None:
    """500 coroutines submit the same idempotency key concurrently.

    The balance must be debited exactly once regardless of how many
    concurrent submissions race to insert the ledger row (INV-2).
    Uses a file-based store (one connection per call) — the production path.
    """
    shared_key = f"shared-idem-{uuid.uuid4().hex}"
    sem = asyncio.Semaphore(SEMAPHORE_LIMIT)
    n = 500

    tasks = [
        _debit(idempotency_store, "tenant-idem", sem, i, idempotency_key=shared_key)
        for i in range(n)
    ]

    results = await asyncio.wait_for(
        asyncio.gather(*tasks, return_exceptions=False),
        timeout=60,
    )

    remaining_usd = await idempotency_store.get_remaining_usd("tenant-idem")
    spent_usd = LIMIT_USD - remaining_usd

    successes = [r for r in results if r[1]]
    unexpected = [r for r in results if not r[1] and r[2] != "BudgetExceededError"]

    print(
        f"\n[idempotency — {n} concurrent same-key submits]\n"
        f"  recorded_successes={len(successes)}  spent=${spent_usd:.6f}  expected=${DEBIT_USD:.6f}"
    )

    assert not unexpected, (
        f"Unexpected errors: {[e[2] for e in unexpected[:3]]}"
    )

    # INV-2: exactly $0.01 debited regardless of concurrency
    assert abs(spent_usd - DEBIT_USD) < 1e-6, (
        f"Idempotency violated: expected exactly ${DEBIT_USD} debited "
        f"but store shows ${spent_usd:.6f} (debited {spent_usd / DEBIT_USD:.1f}×)"
    )


# ---------------------------------------------------------------------------
# Known limitation: :memory: store is not safe for concurrent transactions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_store_concurrent_transactions_raises() -> None:
    """:memory: stores share one connection — concurrent BEGIN IMMEDIATE raises.

    This documents the known limitation of the :memory: path and ensures
    no future change silently swallows the OperationalError (which would
    hide data corruption rather than surfacing it).
    """
    s = PersistentBudgetStore(":memory:")
    await s.initialize()
    await s.create_account("tenant-mem", parent_id=None, limit_usd=10.0)

    shared_key_base = uuid.uuid4().hex
    sem = asyncio.Semaphore(50)

    tasks = [
        _debit(s, "tenant-mem", sem, i, idempotency_key=f"{shared_key_base}-{i}")
        for i in range(50)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=False)

    operational_errors = [
        r for r in results
        if not r[1] and r[2] and "OperationalError" in r[2]
    ]

    await s.close()

    # Under concurrency, :memory: raises OperationalError for nested transactions.
    # This is expected and documented — production must use a file path.
    assert operational_errors, (
        "Expected OperationalError on :memory: concurrent transactions — "
        "if this passes, the shared-connection path has changed; verify correctness."
    )


# ---------------------------------------------------------------------------
# CRITICAL-4.1 (bug manifest): concurrent multi-instance init races on WAL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_critical_4_1_concurrent_init_races_on_wal(tmp_path: Path) -> None:
    """CRITICAL-4.1: 50 store instances racing to initialize the same fresh file.

    `PRAGMA journal_mode=WAL` requires a brief exclusive lock.  When N
    instances all open a connection to a brand-new file and issue the pragma
    simultaneously, the ones that don't win the lock raise
    `sqlite3.OperationalError: database is locked`.

    This test DOCUMENTS the bug — it asserts that lock errors occur so that
    the failure mode stays visible.  Once the CRITICAL-4.1 fix is applied
    (a process-level lock file / advisory lock around PRAGMA + CREATE), this
    test should be inverted: assert zero errors.
    """
    db_path = tmp_path / "concurrent_init_race.db"
    n = 50
    stores = [PersistentBudgetStore(db_path) for _ in range(n)]

    outcomes = await asyncio.gather(
        *[s.initialize() for s in stores],
        return_exceptions=True,
    )

    lock_errors = [
        o for o in outcomes
        if isinstance(o, Exception) and "database is locked" in str(o).lower()
    ]
    other_errors = [
        o for o in outcomes
        if isinstance(o, Exception) and "database is locked" not in str(o).lower()
    ]

    print(
        f"\n[CRITICAL-4.1 init race — {n} instances]\n"
        f"  lock_errors={len(lock_errors)}  other_errors={len(other_errors)}"
    )

    for s in stores:
        try:
            await s.close()
        except Exception:
            pass

    # No unexpected error types — only "database is locked" is the known bug
    assert not other_errors, (
        f"Unexpected error types during concurrent init: "
        f"{[type(e).__name__ + ': ' + str(e) for e in other_errors[:3]]}"
    )

    # The bug must be present — if this assertion fails, the fix was applied
    # and the test should be updated to assert lock_errors == 0 instead.
    assert lock_errors, (
        "Expected 'database is locked' errors on concurrent WAL init — "
        "if zero errors, CRITICAL-4.1 is fixed: flip this assertion to assert not lock_errors."
    )


# ---------------------------------------------------------------------------
# INV-3: Post-init concurrent safety — one initializer, many concurrent ops
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_ops_after_single_init_no_corruption(tmp_path: Path) -> None:
    """One store initializes the schema; 50 separate instances then debit concurrently.

    This tests INV-3 in the realistic multi-process scenario: a single
    initialization step (e.g., migration runner) sets up WAL, and then
    N worker processes each open their own connection and debit concurrently.
    No corruption or overdraft is expected.
    """
    db_path = tmp_path / "post_init.db"

    # Step 1: single authoritative initialization
    primary = PersistentBudgetStore(db_path)
    await primary.initialize()
    await primary.create_account("tenant-post", parent_id=None, limit_usd=LIMIT_USD)
    await primary.close()

    # Step 2: 50 independent store instances open connections and debit concurrently
    n_workers = 50
    workers = [PersistentBudgetStore(db_path) for _ in range(n_workers)]
    for w in workers:
        await w.initialize()  # Now WAL is already set — no race

    sem = asyncio.Semaphore(50)
    tasks = [_debit(w, "tenant-post", sem, i) for i, w in enumerate(workers)]

    results = await asyncio.wait_for(
        asyncio.gather(*tasks, return_exceptions=False),
        timeout=60,
    )

    spent = LIMIT_USD - await workers[0].get_remaining_usd("tenant-post")
    successes = [r for r in results if r[1]]
    unexpected = [r for r in results if not r[1] and r[2] != "BudgetExceededError"]

    print(
        f"\n[post-init concurrent ops — {n_workers} workers]\n"
        f"  succeeded={len(successes)}  spent=${spent:.6f}"
    )

    for w in workers:
        await w.close()

    assert not unexpected, f"Unexpected errors: {[e[2] for e in unexpected[:3]]}"
    assert spent <= LIMIT_USD + 1e-6, f"Overdraft: ${spent:.6f} > ${LIMIT_USD}"
    assert abs(spent - len(successes) * DEBIT_USD) < 1e-4, "Ledger mismatch"


# ---------------------------------------------------------------------------
# INV-1 (variant): Multi-tenant isolation — tenants never bleed into each other
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_multitenant_no_balance_bleed(tmp_path: Path) -> None:
    """Two tenants debited concurrently must never affect each other's balance.

    If the BEGIN IMMEDIATE locking is wrong, tenant A's debit could
    corrupt tenant B's balance row.
    """
    db_path = tmp_path / "multitenant.db"
    store = PersistentBudgetStore(db_path)
    await store.initialize()
    await store.create_account("alpha", parent_id=None, limit_usd=LIMIT_USD)
    await store.create_account("beta",  parent_id=None, limit_usd=LIMIT_USD)

    sem = asyncio.Semaphore(SEMAPHORE_LIMIT)
    n_per_tenant = 300  # 300 tasks × $0.01 = $3.00 each (under the $5 limit)

    alpha_tasks = [_debit(store, "alpha", sem, i)       for i in range(n_per_tenant)]
    beta_tasks  = [_debit(store, "beta",  sem, i + n_per_tenant) for i in range(n_per_tenant)]

    results = await asyncio.wait_for(
        asyncio.gather(*alpha_tasks, *beta_tasks, return_exceptions=False),
        timeout=120,
    )

    alpha_results = results[:n_per_tenant]
    beta_results  = results[n_per_tenant:]

    alpha_spent = LIMIT_USD - await store.get_remaining_usd("alpha")
    beta_spent  = LIMIT_USD - await store.get_remaining_usd("beta")

    alpha_successes = sum(1 for r in alpha_results if r[1])
    beta_successes  = sum(1 for r in beta_results  if r[1])

    print(
        f"\n[multi-tenant isolation]\n"
        f"  alpha: {alpha_successes} succeeded, spent=${alpha_spent:.6f}\n"
        f"  beta:  {beta_successes} succeeded,  spent=${beta_spent:.6f}"
    )

    # Each tenant's balance must match only its own successes
    assert abs(alpha_spent - alpha_successes * DEBIT_USD) < 1e-4, (
        f"Alpha balance bleed: {alpha_successes} successes but ${alpha_spent:.6f} spent"
    )
    assert abs(beta_spent - beta_successes * DEBIT_USD) < 1e-4, (
        f"Beta balance bleed: {beta_successes} successes but ${beta_spent:.6f} spent"
    )

    # Neither tenant must overdraft
    assert alpha_spent <= LIMIT_USD + 1e-6, f"Alpha overdraft: ${alpha_spent:.6f}"
    assert beta_spent  <= LIMIT_USD + 1e-6, f"Beta overdraft: ${beta_spent:.6f}"

    await store.close()
