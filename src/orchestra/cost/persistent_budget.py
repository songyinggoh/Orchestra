"""Persistent budget tracking with double-entry ledger.

Provides an async SQLite-backed store for tracking tenant balances across
multiple runs and processes. Implements:
  - DD-11: Integer storage (microdollars)
  - DD-2:  Pessimistic per-request locking (BEGIN IMMEDIATE)
  - DD-12: Idempotency keys for double-entry ledger entries
  - DD-16: Budget hold/release for failover
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
import structlog

from orchestra.cost.tenant import BudgetConfig, BudgetState

logger = structlog.get_logger(__name__)

MICRO_PER_USD = 1_000_000


def usd_to_micro(usd: float) -> int:
    return round(usd * MICRO_PER_USD)


def micro_to_usd(micro: int) -> float:
    return micro / MICRO_PER_USD


class BudgetExceededError(Exception):
    """Raised when a budget limit is exceeded."""

    def __init__(self, tenant_id: str, spent_micro: int, limit_micro: int) -> None:
        super().__init__(
            f"Budget exceeded for tenant {tenant_id}: "
            f"spent={micro_to_usd(spent_micro):.6f}, limit={micro_to_usd(limit_micro):.6f}"
        )
        self.tenant_id = tenant_id
        self.spent_micro = spent_micro
        self.limit_micro = limit_micro


class IdempotencyConflictError(Exception):
    """Raised on idempotency key collision."""


class CyclicHierarchyError(Exception):
    """Raised when a circular parent reference is detected in the tenant hierarchy."""

    def __init__(self, tenant_id: str, cycle_path: list[str]) -> None:
        path_str = " -> ".join(cycle_path)
        super().__init__(f"Cyclic tenant hierarchy detected involving {tenant_id!r}: {path_str}")
        self.tenant_id = tenant_id
        self.cycle_path = cycle_path


class PersistentBudgetStore:
    """Async SQLite double-entry ledger for budgets."""

    def __init__(self, db_path: str | Path, timeout: float = 30.0) -> None:
        self.db_path = Path(db_path)
        self.timeout = timeout
        self._initialized = False
        self._init_lock = asyncio.Lock()
        self._memory_conn: aiosqlite.Connection | None = None  # Keep alive for :memory:

    async def initialize(self) -> None:
        async with self._init_lock:
            if self._initialized:
                return
            await self._do_initialize()

    async def _do_initialize(self) -> None:
        if self.db_path != Path(":memory:"):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            # Must keep one connection open for :memory: to persist
            if self._memory_conn is None:
                self._memory_conn = await aiosqlite.connect(self.db_path)

        async with self.connection() as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA foreign_keys=ON")

            await db.execute("""
                CREATE TABLE IF NOT EXISTS budget_accounts (
                    tenant_id TEXT PRIMARY KEY,
                    parent_id TEXT,
                    limit_micro INTEGER NOT NULL,
                    reset_period TEXT NOT NULL DEFAULT 'monthly',
                    current_period_start TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(parent_id) REFERENCES budget_accounts(tenant_id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS budget_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL,
                    entry_type TEXT NOT NULL,
                    amount_micro INTEGER NOT NULL,
                    run_id TEXT,
                    model TEXT,
                    idempotency_key TEXT UNIQUE,
                    created_at TEXT NOT NULL,
                    period TEXT NOT NULL,
                    FOREIGN KEY(tenant_id) REFERENCES budget_accounts(tenant_id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS budget_balances (
                    tenant_id TEXT NOT NULL,
                    period TEXT NOT NULL,
                    spent_micro INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(tenant_id, period),
                    FOREIGN KEY(tenant_id) REFERENCES budget_accounts(tenant_id)
                )
            """)
            await db.commit()
        self._initialized = True

    async def close(self) -> None:
        if self._memory_conn:
            await self._memory_conn.close()
            self._memory_conn = None
        self._initialized = False

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Provide a connection. Reuses the memory connection if applicable."""
        if self.db_path == Path(":memory:") and self._memory_conn:
            # We can't easily share the connection object itself for concurrent tasks
            # as aiosqlite connections are not thread-safe for simultaneous use.
            # But in :memory:, they must be the same connection object OR same URI.
            # Actually, we'll just yield it and rely on its internal lock.
            yield self._memory_conn
        else:
            async with aiosqlite.connect(self.db_path, timeout=self.timeout) as db:
                # PRAGMA foreign_keys is a per-connection setting in SQLite —
                # it must be re-applied on every new connection, not just at init.
                await db.execute("PRAGMA foreign_keys=ON")
                yield db

    def _get_current_period(self, period_type: str) -> str:
        now = datetime.now(UTC)
        if period_type == "daily":
            return now.strftime("%Y-%m-%d")
        return now.strftime("%Y-%m")

    async def create_account(
        self, tenant_id: str, parent_id: str | None, limit_usd: float, reset_period: str = "monthly"
    ) -> None:
        limit_micro = usd_to_micro(limit_usd)
        now = datetime.now(UTC).isoformat()
        period = self._get_current_period(reset_period)

        async with self.connection() as db:
            await db.execute(
                """
                INSERT INTO budget_accounts
                    (tenant_id, parent_id, limit_micro, reset_period,
                     current_period_start, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id) DO UPDATE SET
                    limit_micro = excluded.limit_micro,
                    reset_period = excluded.reset_period,
                    parent_id = excluded.parent_id
            """,
                (tenant_id, parent_id, limit_micro, reset_period, now, now),
            )

            await db.execute(
                """
                INSERT OR IGNORE INTO budget_balances (tenant_id, period, spent_micro)
                VALUES (?, ?, 0)
            """,
                (tenant_id, period),
            )
            await db.commit()

    async def check_and_debit(
        self, tenant_id: str, estimated_usd: float, run_id: str, model: str, idempotency_key: str
    ) -> float:
        est_micro = usd_to_micro(estimated_usd)
        now = datetime.now(UTC)

        async with self.connection() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    "SELECT id FROM budget_ledger WHERE idempotency_key = ?", (idempotency_key,)
                )
                if await cursor.fetchone():
                    await db.rollback()
                    return await self._get_remaining_usd_with_db(db, tenant_id)

                cursor = await db.execute(
                    "SELECT parent_id, limit_micro, reset_period"
                    " FROM budget_accounts WHERE tenant_id = ?",
                    (tenant_id,),
                )
                row = await cursor.fetchone()
                if not row:
                    await db.rollback()
                    return 1_000_000.0

                _parent_id, _limit_micro, reset_period = row
                period = self._get_current_period(reset_period)

                await self._recursive_check_and_update(
                    db, tenant_id, est_micro, period, idempotency_key
                )

                await db.execute(
                    """
                    INSERT INTO budget_ledger
                        (tenant_id, entry_type, amount_micro, run_id,
                         model, idempotency_key, created_at, period)
                    VALUES (?, 'debit_estimate', ?, ?, ?, ?, ?, ?)
                """,
                    (tenant_id, est_micro, run_id, model, idempotency_key, now.isoformat(), period),
                )

                await db.commit()
                return await self._get_remaining_usd_with_db(db, tenant_id)
            except Exception:
                await db.rollback()
                raise

    @staticmethod
    def _parent_idempotency_key(child_key: str, parent_id: str, period: str) -> str:
        """Derive a deterministic idempotency key for a parent-chain ledger entry.

        Hashed from (child_key, parent_id, period) so that:
        - Each (child debit, parent node, period) maps to exactly one ledger row.
        - Retries that reach this node again find the row and skip the balance update.
        """
        raw = f"{child_key}|{parent_id}|{period}"
        return "parent:" + hashlib.sha256(raw.encode()).hexdigest()

    async def _recursive_check_and_update(
        self,
        db,
        tenant_id: str,
        amount_micro: int,
        period: str,
        child_idempotency_key: str,
        *,
        visited: set[str] | None = None,
    ) -> None:
        """Check budget and update balance for *tenant_id* and all ancestors.

        Idempotency: each ancestor node gets its own ledger row whose key is
        derived deterministically from (child_idempotency_key, parent_id, period).
        INSERT OR IGNORE on that row makes every ancestor update idempotent.

        Cycle detection: the *visited* set tracks every tenant_id seen in the
        current call chain; a repeat signals a circular parent reference and
        raises CyclicHierarchyError immediately.
        """
        if visited is None:
            visited = set()

        if tenant_id in visited:
            raise CyclicHierarchyError(tenant_id, [*sorted(visited), tenant_id])
        visited.add(tenant_id)

        cursor = await db.execute(
            """
            SELECT b.spent_micro, a.limit_micro, a.parent_id, a.reset_period
            FROM budget_accounts a
            LEFT JOIN budget_balances b ON a.tenant_id = b.tenant_id AND b.period = ?
            WHERE a.tenant_id = ?
        """,
            (period, tenant_id),
        )
        row = await cursor.fetchone()
        if not row:
            return

        spent, limit, parent_id, _reset_period = row
        spent = spent or 0
        if spent + amount_micro > limit:
            raise BudgetExceededError(tenant_id, spent + amount_micro, limit)

        # For the root child the caller already inserted the ledger row with the
        # original idempotency_key.  For every ancestor we derive a stable key so
        # the INSERT OR IGNORE below is the idempotency guard.
        now = datetime.now(UTC).isoformat()
        parent_key = self._parent_idempotency_key(child_idempotency_key, tenant_id, period)
        result = await db.execute(
            """
            INSERT OR IGNORE INTO budget_ledger
                (tenant_id, entry_type, amount_micro, idempotency_key, created_at, period)
            VALUES (?, 'parent_debit', ?, ?, ?, ?)
        """,
            (tenant_id, amount_micro, parent_key, now, period),
        )

        if result.rowcount == 0:
            # Row already existed — this node was already debited for this
            # child transaction.  Skip balance update and stop recursion.
            return

        await db.execute(
            """
            INSERT INTO budget_balances (tenant_id, period, spent_micro)
            VALUES (?, ?, ?)
            ON CONFLICT(tenant_id, period) DO UPDATE SET spent_micro = spent_micro + ?
        """,
            (tenant_id, period, amount_micro, amount_micro),
        )

        if parent_id:
            await self._recursive_check_and_update(
                db, parent_id, amount_micro, period, child_idempotency_key, visited=visited
            )

    async def adjust_actual(
        self, tenant_id: str, run_id: str, actual_usd: float, idempotency_key: str
    ) -> None:
        actual_micro = usd_to_micro(actual_usd)
        now = datetime.now(UTC).isoformat()

        async with self.connection() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    """
                    SELECT amount_micro, period FROM budget_ledger
                    WHERE run_id = ? AND tenant_id = ? AND entry_type = 'debit_estimate'
                """,
                    (run_id, tenant_id),
                )
                row = await cursor.fetchone()
                if not row:
                    await db.rollback()
                    return

                est_micro, period = row
                diff_micro = actual_micro - est_micro

                await db.execute(
                    """
                    INSERT INTO budget_ledger
                        (tenant_id, entry_type, amount_micro, run_id,
                         idempotency_key, created_at, period)
                    VALUES (?, 'credit_correction', ?, ?, ?, ?, ?)
                """,
                    (tenant_id, -diff_micro, run_id, idempotency_key, now, period),
                )

                await self._recursive_update_balance(db, tenant_id, diff_micro, period)
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def _recursive_update_balance(
        self,
        db,
        tenant_id: str,
        amount_micro: int,
        period: str,
        *,
        visited: set[str] | None = None,
    ) -> None:
        if visited is None:
            visited = set()

        if tenant_id in visited:
            raise CyclicHierarchyError(tenant_id, [*sorted(visited), tenant_id])
        visited.add(tenant_id)

        await db.execute(
            """
            UPDATE budget_balances SET spent_micro = spent_micro + ?
            WHERE tenant_id = ? AND period = ?
        """,
            (amount_micro, tenant_id, period),
        )

        cursor = await db.execute(
            "SELECT parent_id FROM budget_accounts WHERE tenant_id = ?", (tenant_id,)
        )
        row = await cursor.fetchone()
        if row and row[0]:
            await self._recursive_update_balance(db, row[0], amount_micro, period, visited=visited)

    async def _get_remaining_usd_with_db(self, db, tenant_id: str) -> float:
        cursor = await db.execute(
            "SELECT reset_period, limit_micro FROM budget_accounts WHERE tenant_id = ?",
            (tenant_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return 1_000_000.0

        period_type, limit_micro = row
        period = self._get_current_period(period_type)

        cursor = await db.execute(
            "SELECT spent_micro FROM budget_balances WHERE tenant_id = ? AND period = ?",
            (tenant_id, period),
        )
        spent_row = await cursor.fetchone()
        spent_micro = spent_row[0] if spent_row else 0

        return micro_to_usd(max(0, limit_micro - spent_micro))

    async def get_remaining_usd(self, tenant_id: str) -> float:
        async with self.connection() as db:
            return await self._get_remaining_usd_with_db(db, tenant_id)

    async def get_state(self, tenant_id: str) -> tuple[BudgetState, BudgetConfig] | None:
        async with self.connection() as db:
            cursor = await db.execute(
                """
                SELECT a.limit_micro, a.reset_period, b.spent_micro, a.created_at
                FROM budget_accounts a
                LEFT JOIN budget_balances b ON a.tenant_id = b.tenant_id
                WHERE a.tenant_id = ?
                ORDER BY b.period DESC LIMIT 1
            """,
                (tenant_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return None

            limit_micro, period_type, spent_micro, created_at = row
            spent_micro = spent_micro or 0

            state = BudgetState(
                tenant_id=tenant_id,
                balance_usd=micro_to_usd(spent_micro),
                last_reset=datetime.fromisoformat(created_at),
            )
            config = BudgetConfig(limit_usd=micro_to_usd(limit_micro), reset_period=period_type)
            return state, config


class TenantBudgetManager:
    """Manager for multi-tenant budget enforcement."""

    def __init__(self, store: PersistentBudgetStore) -> None:
        self._store = store

    async def check_budget(self, tenant_id: str) -> bool:
        remaining = await self._store.get_remaining_usd(tenant_id)
        return remaining > 0

    async def reserve(
        self, tenant_id: str, estimated_cost: float, run_id: str, model: str, idempotency_key: str
    ) -> float:
        return await self._store.check_and_debit(
            tenant_id, estimated_cost, run_id, model, idempotency_key
        )

    async def finalize(
        self, tenant_id: str, run_id: str, actual_cost: float, idempotency_key: str
    ) -> None:
        await self._store.adjust_actual(tenant_id, run_id, actual_cost, idempotency_key)
