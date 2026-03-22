"""PostgreSQL-backed event store for production deployments.

Provides PostgresEventStore (implements EventStore protocol) using asyncpg.

Features beyond SQLite:
- Advisory locks for workflow-level concurrency control
- LISTEN/NOTIFY for real-time event streaming across processes
- JSONB for efficient event payload queries and filtering
- Connection pooling via asyncpg.create_pool

Usage:
    store = PostgresEventStore("postgresql://user:pass@localhost/orchestra")
    await store.initialize()
    # or:
    async with PostgresEventStore("postgresql://localhost/orchestra") as store:
        ...

    # Subscribe to live events:
    await store.subscribe_events(run_id, callback)
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from orchestra.storage.events import (
    EventType,
    WorkflowEvent,
)
from orchestra.storage.serialization import dict_to_event, event_to_dict
from orchestra.storage.store import RunSummary

if TYPE_CHECKING:
    from orchestra.storage.checkpoint import Checkpoint

try:
    import asyncpg
    import asyncpg.pool
except ImportError as _err:  # pragma: no cover
    raise ImportError(
        "asyncpg is required for PostgresEventStore. "
        "Install it with: pip install 'orchestra-agents[postgres]'"
    ) from _err


_DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS workflow_runs (
        run_id UUID PRIMARY KEY,
        workflow_name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'running',
        started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        completed_at TIMESTAMPTZ,
        entry_point TEXT,
        metadata JSONB DEFAULT '{}'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workflow_events (
        id BIGSERIAL PRIMARY KEY,
        run_id UUID NOT NULL REFERENCES workflow_runs(run_id),
        event_id UUID NOT NULL UNIQUE,
        event_type TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        timestamp_iso TIMESTAMPTZ NOT NULL,
        data JSONB NOT NULL,
        UNIQUE(run_id, sequence)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_events_run_seq
        ON workflow_events(run_id, sequence)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_events_type
        ON workflow_events(event_type)
    """,
    """
    CREATE TABLE IF NOT EXISTS workflow_checkpoints (
        id BIGSERIAL PRIMARY KEY,
        run_id UUID NOT NULL REFERENCES workflow_runs(run_id),
        checkpoint_id UUID NOT NULL UNIQUE,
        node_id TEXT NOT NULL,
        interrupt_type TEXT NOT NULL DEFAULT 'before',
        sequence_at INTEGER NOT NULL,
        state_snapshot JSONB NOT NULL,
        execution_context JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_checkpoints_run
        ON workflow_checkpoints(run_id)
    """,
]


class PostgresEventStore:
    """PostgreSQL-backed event store for production deployments.

    Implements the EventStore protocol from orchestra.storage.store.

    Features beyond SQLite:
    - Advisory locks for workflow-level concurrency (prevents concurrent writers
      to the same workflow run within a transaction)
    - LISTEN/NOTIFY for real-time event streaming via subscribe_events()
    - JSONB columns for efficient payload queries
    - asyncpg connection pool for high-concurrency workloads

    Usage:
        store = PostgresEventStore("postgresql://user:pass@localhost/orchestra")
        await store.initialize()
        # or as context manager:
        async with PostgresEventStore("postgresql://localhost/orchestra") as store:
            ...
    """

    def __init__(
        self,
        dsn: str | None = None,
        min_pool_size: int = 4,
        max_pool_size: int = 20,
    ) -> None:
        """Create a PostgresEventStore.

        Args:
            dsn: PostgreSQL connection string. Falls back to DATABASE_URL env var.
            min_pool_size: Minimum connections in pool (default 4).
            max_pool_size: Maximum connections in pool (default 20).
        """
        self._dsn = dsn or os.environ.get("DATABASE_URL")
        if not self._dsn:
            raise ValueError(
                "PostgresEventStore requires a DSN. "
                "Pass dsn= or set the DATABASE_URL environment variable."
            )
        self._min_pool_size = min_pool_size
        self._max_pool_size = max_pool_size
        self._pool: asyncpg.pool.Pool | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create the connection pool and ensure all tables exist."""
        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size=self._min_pool_size,
            max_size=self._max_pool_size,
        )
        async with self._pool.acquire() as conn:
            for stmt in _DDL_STATEMENTS:
                await conn.execute(stmt)

    async def close(self) -> None:
        """Close the connection pool gracefully."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def __aenter__(self) -> PostgresEventStore:
        await self.initialize()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_pool(self) -> asyncpg.pool.Pool:
        if self._pool is None:
            raise RuntimeError(
                "PostgresEventStore not initialized. "
                "Call await store.initialize() first "
                "or use 'async with PostgresEventStore(...) as store:'."
            )
        return self._pool

    @asynccontextmanager
    async def _locked_transaction(self, run_id: str) -> AsyncGenerator[asyncpg.Connection, None]:
        """Acquire an advisory lock for a workflow run within a transaction.

        Uses pg_advisory_xact_lock(hashtext(run_id)) so the lock is
        automatically released when the transaction ends. This prevents
        concurrent writers from corrupting sequence numbers.
        """
        pool = self._require_pool()
        lock_id = hash(run_id) & 0x7FFFFFFF  # positive int required by pg
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", lock_id)
            yield conn

    async def _ensure_run_exists(
        self,
        conn: asyncpg.Connection,
        run_id: str,
        workflow_name: str = "",
        entry_point: str = "",
    ) -> None:
        """Insert a run row if it does not already exist (upsert-ignore)."""
        started_at = datetime.now(UTC)
        await conn.execute(
            """
            INSERT INTO workflow_runs
                (run_id, workflow_name, status, started_at, entry_point)
            VALUES ($1, $2, 'running', $3, $4)
            ON CONFLICT (run_id) DO NOTHING
            """,
            run_id,
            workflow_name,
            started_at,
            entry_point,
        )

    # ------------------------------------------------------------------
    # EventStore protocol methods
    # ------------------------------------------------------------------

    async def append(self, event: WorkflowEvent) -> None:
        """Persist one event to the store.

        Acquires a workflow-level advisory lock so sequence numbers remain
        monotonic even under concurrent appends for the same run_id.
        Automatically creates a run record if one does not exist.
        Sends a NOTIFY on channel 'workflow_events' for real-time subscribers.
        """
        data_payload = json.dumps(event_to_dict(event))
        timestamp_iso = event.timestamp

        async with self._locked_transaction(event.run_id) as conn:
            await self._ensure_run_exists(conn, event.run_id)
            await conn.execute(
                """
                INSERT INTO workflow_events
                    (run_id, event_id, event_type, sequence, timestamp_iso, data)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                ON CONFLICT (event_id) DO NOTHING
                """,
                event.run_id,
                event.event_id,
                event.event_type.value,
                event.sequence,
                timestamp_iso,
                data_payload,
            )
            # NOTIFY for live subscribers (fire-and-forget within same txn)
            notify_payload = json.dumps(
                {"run_id": event.run_id, "event_type": event.event_type.value}
            )
            await conn.execute("SELECT pg_notify('workflow_events', $1)", notify_payload)

    async def get_events(
        self,
        run_id: str,
        *,
        after_sequence: int = -1,
        event_types: list[EventType] | None = None,
    ) -> list[WorkflowEvent]:
        """Retrieve events for a run in sequence order.

        Args:
            run_id: The workflow run identifier.
            after_sequence: Return only events with sequence > this value.
            event_types: Optional list of EventType enum values to filter by.

        Returns:
            List of WorkflowEvent objects ordered by sequence ascending.
        """
        pool = self._require_pool()

        if event_types:
            type_values = [et.value for et in event_types]
            # asyncpg uses $N placeholders; build dynamic IN list
            placeholders = ", ".join(f"${i + 3}" for i in range(len(type_values)))
            query = f"""
                SELECT data FROM workflow_events
                WHERE run_id = $1
                  AND sequence > $2
                  AND event_type IN ({placeholders})
                ORDER BY sequence ASC
            """
            rows = await pool.fetch(query, run_id, after_sequence, *type_values)
        else:
            rows = await pool.fetch(
                """
                SELECT data FROM workflow_events
                WHERE run_id = $1 AND sequence > $2
                ORDER BY sequence ASC
                """,
                run_id,
                after_sequence,
            )

        events: list[WorkflowEvent] = []
        for row in rows:
            # asyncpg returns JSONB as a dict; convert back to WorkflowEvent
            raw = row["data"]
            if isinstance(raw, str):
                raw = json.loads(raw)
            events.append(dict_to_event(raw))
        return events

    async def get_latest_checkpoint(self, run_id: str) -> Checkpoint | None:
        """Return the most recent checkpoint for a run, or None."""
        from orchestra.storage.checkpoint import Checkpoint

        pool = self._require_pool()
        row = await pool.fetchrow(
            """
            SELECT checkpoint_id, node_id, interrupt_type, sequence_at,
                   state_snapshot, execution_context, created_at
            FROM workflow_checkpoints
            WHERE run_id = $1
            ORDER BY sequence_at DESC, id DESC
            LIMIT 1
            """,
            run_id,
        )
        if row is None:
            return None

        # asyncpg returns JSONB as dict or list
        state = row["state_snapshot"]
        ctx = row["execution_context"]

        return Checkpoint(
            run_id=run_id,
            checkpoint_id=str(row["checkpoint_id"]),
            node_id=row["node_id"],
            interrupt_type=row["interrupt_type"],
            sequence_number=row["sequence_at"],
            state=state if isinstance(state, dict) else json.loads(state),
            loop_counters=ctx.get("loop_counters", {}) if isinstance(ctx, dict) else {},
            node_execution_order=ctx.get("node_execution_order", [])
            if isinstance(ctx, dict)
            else [],
            timestamp=row["created_at"],
        )

    async def get_checkpoint(self, checkpoint_id: str) -> Checkpoint | None:
        """Retrieve a specific checkpoint by its ID."""
        from orchestra.storage.checkpoint import Checkpoint

        pool = self._require_pool()
        row = await pool.fetchrow(
            """
            SELECT run_id, checkpoint_id, node_id, interrupt_type, sequence_at,
                   state_snapshot, execution_context, created_at
            FROM workflow_checkpoints
            WHERE checkpoint_id = $1
            """,
            checkpoint_id,
        )
        if row is None:
            return None

        state = row["state_snapshot"]
        ctx = row["execution_context"]

        return Checkpoint(
            run_id=str(row["run_id"]),
            checkpoint_id=str(row["checkpoint_id"]),
            node_id=row["node_id"],
            interrupt_type=row["interrupt_type"],
            sequence_number=row["sequence_at"],
            state=state if isinstance(state, dict) else json.loads(state),
            loop_counters=ctx.get("loop_counters", {}) if isinstance(ctx, dict) else {},
            node_execution_order=ctx.get("node_execution_order", [])
            if isinstance(ctx, dict)
            else [],
            timestamp=row["created_at"],
        )

    async def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        """Persist a Checkpoint object to the store."""
        pool = self._require_pool()
        ctx_json = json.dumps(
            {
                "loop_counters": checkpoint.loop_counters,
                "node_execution_order": checkpoint.node_execution_order,
            }
        )
        await pool.execute(
            """
            INSERT INTO workflow_checkpoints
                (run_id, checkpoint_id, node_id, interrupt_type, sequence_at,
                 state_snapshot, execution_context, created_at)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8)
            ON CONFLICT (checkpoint_id) DO UPDATE
                SET state_snapshot = EXCLUDED.state_snapshot,
                    execution_context = EXCLUDED.execution_context,
                    created_at = EXCLUDED.created_at
            """,
            checkpoint.run_id,
            checkpoint.checkpoint_id,
            checkpoint.node_id,
            checkpoint.interrupt_type,
            checkpoint.sequence_number,
            json.dumps(checkpoint.state),
            ctx_json,
            checkpoint.timestamp,
        )

    async def list_runs(self, *, limit: int = 50, status: str | None = None) -> list[RunSummary]:
        """List workflow runs with optional status filter.

        Returns RunSummary objects ordered by started_at descending.
        """
        pool = self._require_pool()
        if status:
            rows = await pool.fetch(
                """
                SELECT r.run_id::text, r.workflow_name, r.status,
                       r.started_at, r.completed_at,
                       COUNT(e.id) AS event_count
                FROM workflow_runs r
                LEFT JOIN workflow_events e ON e.run_id = r.run_id
                WHERE r.status = $1
                GROUP BY r.run_id, r.workflow_name, r.status, r.started_at, r.completed_at
                ORDER BY r.started_at DESC
                LIMIT $2
                """,
                status,
                limit,
            )
        else:
            rows = await pool.fetch(
                """
                SELECT r.run_id::text, r.workflow_name, r.status,
                       r.started_at, r.completed_at,
                       COUNT(e.id) AS event_count
                FROM workflow_runs r
                LEFT JOIN workflow_events e ON e.run_id = r.run_id
                GROUP BY r.run_id, r.workflow_name, r.status, r.started_at, r.completed_at
                ORDER BY r.started_at DESC
                LIMIT $1
                """,
                limit,
            )

        return [
            RunSummary(
                run_id=row["run_id"],
                workflow_name=row["workflow_name"],
                status=row["status"],
                started_at=row["started_at"].isoformat()
                if hasattr(row["started_at"], "isoformat")
                else str(row["started_at"]),
                completed_at=row["completed_at"].isoformat()
                if row["completed_at"] is not None and hasattr(row["completed_at"], "isoformat")
                else (str(row["completed_at"]) if row["completed_at"] is not None else None),
                event_count=row["event_count"],
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Extended helpers (not in protocol but mirror SQLiteEventStore)
    # ------------------------------------------------------------------

    async def create_run(
        self,
        run_id: str,
        workflow_name: str,
        entry_point: str,
    ) -> None:
        """Insert a new run record with status 'running'."""
        pool = self._require_pool()
        started_at = datetime.now(UTC)
        await pool.execute(
            """
            INSERT INTO workflow_runs
                (run_id, workflow_name, status, started_at, entry_point)
            VALUES ($1, $2, 'running', $3, $4)
            ON CONFLICT (run_id) DO NOTHING
            """,
            run_id,
            workflow_name,
            started_at,
            entry_point,
        )

    async def update_run_status(
        self,
        run_id: str,
        status: str,
        completed_at: str | None = None,
    ) -> None:
        """Update the status (and optionally completed_at) of a run."""
        pool = self._require_pool()
        if completed_at is not None:
            ts = datetime.fromisoformat(completed_at)
            await pool.execute(
                "UPDATE workflow_runs SET status = $1, completed_at = $2 WHERE run_id = $3",
                status,
                ts,
                run_id,
            )
        else:
            await pool.execute(
                "UPDATE workflow_runs SET status = $1 WHERE run_id = $2",
                status,
                run_id,
            )

    # ------------------------------------------------------------------
    # PostgreSQL-specific: LISTEN/NOTIFY event streaming
    # ------------------------------------------------------------------

    async def subscribe_events(
        self,
        run_id: str,
        callback: Callable[[WorkflowEvent], Awaitable[None]],
    ) -> None:
        """Subscribe to real-time events via LISTEN/NOTIFY.

        Acquires a dedicated connection and listens on the 'workflow_events'
        channel. The callback is invoked for each notification whose run_id
        matches. The connection is kept open until cancelled.

        Note: This method blocks until cancelled. Run it as a background task:
            task = asyncio.create_task(store.subscribe_events(run_id, cb))
            ...
            task.cancel()
        """
        pool = self._require_pool()
        conn = await pool.acquire()
        try:

            async def _on_notification(
                connection: asyncpg.Connection,
                pid: int,
                channel: str,
                payload: str,
            ) -> None:
                try:
                    meta = json.loads(payload)
                except (json.JSONDecodeError, TypeError):
                    return
                if meta.get("run_id") != run_id:
                    return
                # Fetch and deliver the most recent event for this run
                rows = await connection.fetch(
                    """
                    SELECT data FROM workflow_events
                    WHERE run_id = $1
                    ORDER BY sequence DESC
                    LIMIT 1
                    """,
                    run_id,
                )
                for row in rows:
                    raw = row["data"]
                    if isinstance(raw, str):
                        raw = json.loads(raw)
                    event = dict_to_event(raw)
                    await callback(event)

            await conn.add_listener("workflow_events", _on_notification)  # type: ignore[arg-type]
            # Keep the connection open until cancelled
            import asyncio

            while True:
                await asyncio.sleep(1)
        finally:
            await conn.remove_listener("workflow_events", _on_notification)  # type: ignore[arg-type]
            await pool.release(conn)
