---
phase: 04-enterprise-scale
plan: wave2-A4
type: execute
wave: 3
depends_on: [wave2-A2, wave2-A3]
files_modified:
  - src/orchestra/cost/persistent_budget.py
  - src/orchestra/cost/tenant.py
  - src/orchestra/cost/__init__.py
  - tests/unit/test_persistent_budget.py
autonomous: true
requirements: [T-4.5]
must_haves:
  truths:
    - "Budget survives server restart (persisted in SQLite/Postgres)"
    - "Tenant-scoped budgets enforce hard limits via pessimistic locking — no overspend possible (DD-2)"
    - "Child tenant spending counts toward parent limit; child cannot exceed own allocation even if parent has headroom (DD-2)"
    - "Idempotent debits: same idempotency_key does not double-charge"
    - "Period rollover is lazy UTC-based: first request after boundary triggers reset (DD-2)"
  artifacts:
    - path: "src/orchestra/cost/persistent_budget.py"
      provides: "Async double-entry ledger with 3-table schema, pessimistic locking, hierarchy enforcement"
      min_lines: 150
      contains: "BEGIN IMMEDIATE"
    - path: "src/orchestra/cost/tenant.py"
      provides: "Extended Tenant with parent_id, BudgetConfig with UTC periods"
      contains: "parent_id"
    - path: "tests/unit/test_persistent_budget.py"
      provides: "9 tests covering all budget scenarios including concurrent debits"
      min_lines: 120
  key_links:
    - from: "src/orchestra/cost/persistent_budget.py"
      to: "aiosqlite"
      via: "import aiosqlite (async SQLite for WAL mode + BEGIN IMMEDIATE)"
      pattern: "import aiosqlite"
    - from: "src/orchestra/cost/persistent_budget.py"
      to: "src/orchestra/core/errors.py"
      via: "from orchestra.core.errors import BudgetExceededError"
      pattern: "BudgetExceededError"
---

<objective>
Rewrite PersistentBudget with an async double-entry ledger using pessimistic locking per DD-2.

Purpose: The current implementation uses synchronous SQLite with no locking — concurrent LLM calls can read stale balances and cause overspend. The rewrite uses BEGIN IMMEDIATE (SQLite WAL) and SELECT FOR UPDATE (PostgreSQL) to ensure atomicity. Double-entry ledger enables audit trails and cost correction after actual token counts are known.
Output: Async PersistentBudgetStore and TenantBudgetManager, 9 tests covering all budget scenarios.
</objective>

<execution_context>
@C:/Users/user/.claude/get-shit-done/workflows/execute-plan.md
@C:/Users/user/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/04-enterprise-scale/PLAN.md
@.planning/phases/04-enterprise-scale/WAVE2-DESIGN-DECISIONS.md

<interfaces>
<!-- From src/orchestra/core/errors.py (extended in A1) -->
```python
class BudgetExceededError(OrchestraError):
    def __init__(self, message: str, tenant_id: str = "", remaining_usd: float = 0.0) -> None: ...
    tenant_id: str
    remaining_usd: float
```

<!-- DD-2 locking model -->
```
SQLite: BEGIN IMMEDIATE (WAL mode allows concurrent reads during write lock)
PostgreSQL: SELECT ... FOR UPDATE (row-level lock)
Period boundaries: UTC, YYYY-MM for monthly, YYYY-MM-DD for daily
Hierarchy: child spending counts toward parent; child cannot exceed own allocation
Lazy rollover: first request after period end inserts rollover entry + new period row
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true" id="A4.1" name="Rewrite PersistentBudgetStore with double-entry ledger and pessimistic locking">
  <files>src/orchestra/cost/persistent_budget.py, src/orchestra/cost/tenant.py, src/orchestra/cost/__init__.py, tests/unit/test_persistent_budget.py</files>
  <behavior>
    - test_create_account_and_check_balance: Fresh account has $0 spent, full limit available
    - test_debit_reduces_remaining: After debit of $2.50 on $10 limit, remaining is $7.50
    - test_budget_exceeded_raises: Debit of $11 on $10 limit raises BudgetExceededError
    - test_idempotent_debit: Calling check_and_debit twice with same idempotency_key charges only once
    - test_actual_cost_correction: adjust_actual() inserts credit_correction entry when actual != estimated
    - test_hierarchy_parent_limit: Child debit counts against parent; parent blocks when parent limit exhausted
    - test_child_cannot_exceed_own_allocation: Child capped at its own limit even if parent has headroom
    - test_period_rollover_monthly: After month boundary (mock datetime), balance resets to $0
    - test_concurrent_debits_pessimistic_lock: Two concurrent debits totaling more than limit — one raises BudgetExceededError (no double spend)
  </behavior>
  <action>
Read src/orchestra/cost/persistent_budget.py and src/orchestra/cost/tenant.py first.

**tenant.py extension (EXTEND, not replace):**
Add parent_id to Tenant dataclass and document UTC period rule:
```python
@dataclass
class Tenant:
    tenant_id: str
    name: str
    parent_id: str | None = None   # NEW: for hierarchy (DD-2: child counts toward parent)
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class BudgetConfig:
    limit_usd: float
    warning_threshold: float = 0.8
    is_hard_limit: bool = True
    reset_period: str = "monthly"  # "monthly", "daily", "none"
    # DD-2: All timestamps are UTC. No tenant timezone configuration.
```
Keep BudgetState and BudgetStatus as-is (backward compatible).

**persistent_budget.py full rewrite:**

Schema (3 tables, created in initialize()):
```sql
CREATE TABLE IF NOT EXISTS budget_accounts (
    tenant_id TEXT PRIMARY KEY,
    parent_id TEXT,
    limit_usd REAL NOT NULL,
    reset_period TEXT NOT NULL DEFAULT 'monthly',
    current_period_start TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(parent_id) REFERENCES budget_accounts(tenant_id)
);

CREATE TABLE IF NOT EXISTS budget_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    entry_type TEXT NOT NULL,  -- 'debit_estimate', 'credit_correction', 'debit_actual', 'rollover'
    amount_usd REAL NOT NULL,
    run_id TEXT,
    model TEXT,
    idempotency_key TEXT UNIQUE,
    created_at TEXT NOT NULL,
    period TEXT NOT NULL,   -- 'YYYY-MM' for monthly, 'YYYY-MM-DD' for daily
    FOREIGN KEY(tenant_id) REFERENCES budget_accounts(tenant_id)
);

CREATE TABLE IF NOT EXISTS budget_balances (
    tenant_id TEXT NOT NULL,
    period TEXT NOT NULL,
    spent_usd REAL NOT NULL DEFAULT 0.0,
    PRIMARY KEY(tenant_id, period)
);
```

PersistentBudgetStore class:
```python
import aiosqlite
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from orchestra.core.errors import BudgetExceededError

class PersistentBudgetStore:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    async def initialize(self) -> None:
        """Create tables and enable WAL mode."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            # Create 3 tables from schema above
            await db.commit()

    async def create_account(
        self, tenant_id: str, parent_id: str | None, limit_usd: float, reset_period: str = "monthly"
    ) -> None:
        """Create a budget account. parent_id=None for root tenant."""

    async def check_and_debit(
        self,
        tenant_id: str,
        estimated_cost: float,
        run_id: str,
        model: str,
        idempotency_key: str,
    ) -> float:
        """DD-2 pessimistic locking flow:
        1. BEGIN IMMEDIATE (WAL mode)
        2. Trigger lazy rollover if period has changed
        3. Read current spent_usd for current period
        4. Traverse parent hierarchy — check each parent's remaining budget
        5. If spent + estimated > limit (at any level) -> ROLLBACK, raise BudgetExceededError
        6. INSERT debit_estimate ledger entry with idempotency_key
        7. UPDATE budget_balances (INSERT OR IGNORE + UPDATE)
        8. COMMIT
        Returns: remaining_budget_usd for this tenant after debit
        """

    async def adjust_actual(
        self, tenant_id: str, run_id: str, actual_cost: float, idempotency_key: str
    ) -> None:
        """Post-call correction: insert credit_correction if actual != estimated.
        Uses a different idempotency_key (append '-actual') to avoid conflict.
        """

    async def get_balance(self, tenant_id: str) -> tuple[float, float]:
        """Returns (spent_usd, limit_usd) for current period."""

    async def rollover_if_needed(self, tenant_id: str) -> bool:
        """Lazy rollover check. Returns True if rollover occurred."""

    def _current_period(self, reset_period: str) -> str:
        """Return 'YYYY-MM' for monthly or 'YYYY-MM-DD' for daily (UTC)."""
        now = datetime.now(timezone.utc)
        if reset_period == "daily":
            return now.strftime("%Y-%m-%d")
        return now.strftime("%Y-%m")
```

TenantBudgetManager wrapper:
```python
class TenantBudgetManager:
    def __init__(self, store: PersistentBudgetStore) -> None:
        self._store = store

    async def check_budget(self, tenant_id: str) -> bool:
        """Returns True if tenant has remaining budget."""
        spent, limit = await self._store.get_balance(tenant_id)
        return spent < limit

    async def reserve(self, tenant_id: str, estimated_cost: float, run_id: str, model: str) -> float:
        """Reserve budget before LLM call. Returns remaining after reservation."""
        key = f"{run_id}-{tenant_id}-est"
        return await self._store.check_and_debit(tenant_id, estimated_cost, run_id, model, key)

    async def finalize(self, tenant_id: str, run_id: str, actual_cost: float) -> None:
        """Finalize with actual cost after LLM call completes."""
        key = f"{run_id}-{tenant_id}-actual"
        await self._store.adjust_actual(tenant_id, run_id, actual_cost, key)
```

For the concurrent test, use asyncio.gather() with two debits that together exceed the limit. One must raise BudgetExceededError. Use a temporary file DB (not :memory:) for the concurrent test to test real WAL locking.

Update src/orchestra/cost/__init__.py to export PersistentBudgetStore, TenantBudgetManager, BudgetConfig, BudgetState, Tenant.
  </action>
  <verify>
    <automated>pytest tests/unit/test_persistent_budget.py -x -v</automated>
  </verify>
  <done>Budget persists across process restarts. Pessimistic locking prevents overspend under concurrency. Hierarchy enforcement works. All 9 tests pass.</done>
</task>

</tasks>

<verification>
pytest tests/unit/test_persistent_budget.py -v
python -c "
import asyncio
from orchestra.cost.persistent_budget import PersistentBudgetStore, TenantBudgetManager
store = PersistentBudgetStore(':memory:')
asyncio.run(store.initialize())
print('PersistentBudgetStore init OK')
"
</verification>

<success_criteria>
- All 9 test_persistent_budget.py tests pass
- BEGIN IMMEDIATE used in check_and_debit (grep confirms 'BEGIN IMMEDIATE' in persistent_budget.py)
- BudgetExceededError raised with tenant_id and remaining_usd attributes
- Idempotency key prevents double-charge
- Hierarchy: child spending counts toward parent limit
- UTC-only timestamps in all ledger entries
- aiosqlite used (no synchronous sqlite3 calls in async methods)
</success_criteria>

<output>
After completion, create .planning/phases/04-enterprise-scale/04-wave2-A4-SUMMARY.md
</output>
