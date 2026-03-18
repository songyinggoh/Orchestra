"""SQLite-backed event store for zero-config workflow persistence.

Provides SQLiteEventStore (implements EventStore protocol) and SnapshotManager
(periodically checkpoints state by subscribing to EventBus).

Database location defaults to .orchestra/runs.db (auto-created on first use).
Uses WAL mode for concurrent read/write access.

Usage:
    store = SQLiteEventStore()              # .orchestra/runs.db
    store = SQLiteEventStore(":memory:")    # in-memory (testing)
    await store.initialize()
    # or:
    async with SQLiteEventStore() as store:
        ...
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from orchestra.storage.checkpoint import Checkpoint
from orchestra.storage.events import (
    CheckpointCreated,
    EventType,
    WorkflowEvent,
)
from orchestra.storage.serialization import dict_to_event, event_to_dict
from orchestra.storage.store import RunSummary


_DDL = """
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;

CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id       TEXT PRIMARY KEY,
    workflow_name TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'running',
    started_at   TEXT NOT NULL,
    completed_at TEXT,
    entry_point  TEXT,
    metadata     TEXT
);

CREATE TABLE IF NOT EXISTS workflow_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT NOT NULL,
    event_id     TEXT NOT NULL UNIQUE,
    event_type   TEXT NOT NULL,
    sequence     INTEGER NOT NULL,
    timestamp_iso TEXT NOT NULL,
    data         TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_events_run_seq  ON workflow_events(run_id, sequence);
CREATE INDEX IF NOT EXISTS idx_events_type     ON workflow_events(event_type);

CREATE TABLE IF NOT EXISTS workflow_checkpoints (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL UNIQUE,
    node_id       TEXT NOT NULL,
    interrupt_type TEXT NOT NULL,
    sequence_at   INTEGER NOT NULL,
    state_snapshot TEXT NOT NULL,
    execution_context TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_run ON workflow_checkpoints(run_id);
"""


class SQLiteEventStore:
    """SQLite-backed event store. Zero-config default backend.

    Database location: .orchestra/runs.db (auto-created on first use).
    Uses WAL mode for concurrent access from parallel nodes.

    Implements the EventStore protocol from orchestra.storage.store.

    Usage:
        store = SQLiteEventStore()           # uses .orchestra/runs.db
        store = SQLiteEventStore(":memory:") # in-memory for tests
        await store.initialize()
        # or use as async context manager:
        async with SQLiteEventStore() as store:
            ...
    """

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            db_path = os.environ.get("ORCHESTRA_DB_PATH", ".orchestra/runs.db")
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._closed = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create the .orchestra/ directory and tables if they do not exist."""
        if self._db_path != ":memory:":
            dir_path = os.path.dirname(self._db_path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)

        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        # Execute DDL statements individually (aiosqlite executescript needs
        # sync connection; splitting on semicolons is more portable)
        for statement in _DDL.split(";"):
            stmt = statement.strip()
            if stmt:
                await self._conn.execute(stmt)
        await self._conn.commit()

    async def close(self) -> None:
        """Close the database connection."""
        self._closed = True
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def __aenter__(self) -> "SQLiteEventStore":
        await self.initialize()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_conn(self) -> aiosqlite.Connection:
        if self._closed:
            raise RuntimeError("SQLiteEventStore is closed.")
        if self._conn is None:
            raise RuntimeError(
                "SQLiteEventStore not initialized. Call await store.initialize() first "
                "or use 'async with SQLiteEventStore() as store:'."
            )
        return self._conn

    # ------------------------------------------------------------------
    # EventStore protocol methods
    # ------------------------------------------------------------------

    async def append(self, event: WorkflowEvent) -> None:
        """Persist one event to the store.

        Serializes the event using serialization.py (Pydantic JSON encoding).
        Auto-creates a run record if one does not already exist.
        """
        conn = self._require_conn()
        data_json = json.dumps(event_to_dict(event))
        timestamp_iso = event.timestamp.isoformat()

        await conn.execute(
            """
            INSERT OR IGNORE INTO workflow_events
                (run_id, event_id, event_type, sequence, timestamp_iso, data)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.run_id,
                event.event_id,
                event.event_type.value,
                event.sequence,
                timestamp_iso,
                data_json,
            ),
        )
        await conn.commit()

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
        if self._closed:
            return []
        conn = self._require_conn()

        if event_types:
            placeholders = ",".join("?" * len(event_types))
            type_values = [et.value for et in event_types]
            query = f"""
                SELECT data FROM workflow_events
                WHERE run_id = ?
                  AND sequence > ?
                  AND event_type IN ({placeholders})
                ORDER BY sequence ASC
            """
            params: list[Any] = [run_id, after_sequence, *type_values]
        else:
            query = """
                SELECT data FROM workflow_events
                WHERE run_id = ? AND sequence > ?
                ORDER BY sequence ASC
            """
            params = [run_id, after_sequence]

        async with conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        events: list[WorkflowEvent] = []
        for row in rows:
            raw = json.loads(row["data"])
            events.append(dict_to_event(raw))
        return events

    async def get_latest_checkpoint(self, run_id: str) -> Checkpoint | None:
        """Return the most recent checkpoint for a run, or None."""
        conn = self._require_conn()
        async with conn.execute(
            """
            SELECT checkpoint_id, node_id, interrupt_type, sequence_at,
                   state_snapshot, execution_context, created_at
            FROM workflow_checkpoints
            WHERE run_id = ?
            ORDER BY sequence_at DESC, id DESC
            LIMIT 1
            """,
            (run_id,),
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:
            return None

        ctx = json.loads(row["execution_context"])
        return Checkpoint(
            run_id=run_id,
            checkpoint_id=row["checkpoint_id"],
            node_id=row["node_id"],
            interrupt_type=row["interrupt_type"],
            sequence_number=row["sequence_at"],
            state=json.loads(row["state_snapshot"]),
            loop_counters=ctx.get("loop_counters", {}),
            node_execution_order=ctx.get("node_execution_order", []),
            timestamp=datetime.fromisoformat(row["created_at"]),
        )

    async def get_checkpoint(self, checkpoint_id: str) -> Checkpoint | None:
        """Retrieve a specific checkpoint by its ID."""
        conn = self._require_conn()
        async with conn.execute(
            """
            SELECT run_id, checkpoint_id, node_id, interrupt_type, sequence_at,
                   state_snapshot, execution_context, created_at
            FROM workflow_checkpoints
            WHERE checkpoint_id = ?
            """,
            (checkpoint_id,),
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:
            return None

        ctx = json.loads(row["execution_context"])
        return Checkpoint(
            run_id=row["run_id"],
            checkpoint_id=row["checkpoint_id"],
            node_id=row["node_id"],
            interrupt_type=row["interrupt_type"],
            sequence_number=row["sequence_at"],
            state=json.loads(row["state_snapshot"]),
            loop_counters=ctx.get("loop_counters", {}),
            node_execution_order=ctx.get("node_execution_order", []),
            timestamp=datetime.fromisoformat(row["created_at"]),
        )

    async def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        """Persist a Checkpoint object to the store."""
        conn = self._require_conn()
        ctx_json = json.dumps({
            "loop_counters": checkpoint.loop_counters,
            "node_execution_order": checkpoint.node_execution_order,
        })
        await conn.execute(
            """
            INSERT OR REPLACE INTO workflow_checkpoints
                (run_id, checkpoint_id, node_id, interrupt_type, sequence_at,
                 state_snapshot, execution_context, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                checkpoint.run_id,
                checkpoint.checkpoint_id,
                checkpoint.node_id,
                checkpoint.interrupt_type,
                checkpoint.sequence_number,
                json.dumps(checkpoint.state),
                ctx_json,
                checkpoint.timestamp.isoformat(),
            ),
        )
        await conn.commit()

    async def list_runs(
        self, *, limit: int = 50, status: str | None = None
    ) -> list[RunSummary]:
        """List workflow runs with optional status filter.

        Returns RunSummary objects ordered by started_at descending.
        """
        conn = self._require_conn()
        if status:
            query = """
                SELECT r.run_id, r.workflow_name, r.status, r.started_at, r.completed_at,
                       COUNT(e.id) AS event_count
                FROM workflow_runs r
                LEFT JOIN workflow_events e ON e.run_id = r.run_id
                WHERE r.status = ?
                GROUP BY r.run_id
                ORDER BY r.started_at DESC
                LIMIT ?
            """
            params_ls: list[Any] = [status, limit]
        else:
            query = """
                SELECT r.run_id, r.workflow_name, r.status, r.started_at, r.completed_at,
                       COUNT(e.id) AS event_count
                FROM workflow_runs r
                LEFT JOIN workflow_events e ON e.run_id = r.run_id
                GROUP BY r.run_id
                ORDER BY r.started_at DESC
                LIMIT ?
            """
            params_ls = [limit]

        async with conn.execute(query, params_ls) as cursor:
            rows = await cursor.fetchall()

        return [
            RunSummary(
                run_id=row["run_id"],
                workflow_name=row["workflow_name"],
                status=row["status"],
                started_at=row["started_at"],
                completed_at=row["completed_at"],
                event_count=row["event_count"],
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Extended helpers (not in protocol but used by CompiledGraph)
    # ------------------------------------------------------------------

    async def create_run(
        self,
        run_id: str,
        workflow_name: str,
        entry_point: str,
    ) -> None:
        """Insert a new run record with status 'running'."""
        conn = self._require_conn()
        started_at = datetime.now(timezone.utc).isoformat()
        await conn.execute(
            """
            INSERT OR IGNORE INTO workflow_runs
                (run_id, workflow_name, status, started_at, entry_point)
            VALUES (?, ?, 'running', ?, ?)
            """,
            (run_id, workflow_name, started_at, entry_point),
        )
        await conn.commit()

    async def update_run_status(
        self,
        run_id: str,
        status: str,
        completed_at: str | None = None,
    ) -> None:
        """Update the status (and optionally completed_at) of a run."""
        conn = self._require_conn()
        if completed_at is not None:
            await conn.execute(
                "UPDATE workflow_runs SET status = ?, completed_at = ? WHERE run_id = ?",
                (status, completed_at, run_id),
            )
        else:
            await conn.execute(
                "UPDATE workflow_runs SET status = ? WHERE run_id = ?",
                (status, run_id),
            )
        await conn.commit()


# ---------------------------------------------------------------------------
# SnapshotManager
# ---------------------------------------------------------------------------


class SnapshotManager:
    """Periodically creates state snapshots to speed up restoration.

    Subscribes to EventBus as a sync callback. After every N events (default 50),
    schedules a checkpoint via the EventStore.

    Usage:
        snapshot_mgr = SnapshotManager(store, interval=50)
        event_bus.subscribe(snapshot_mgr.on_event)
    """

    def __init__(self, store: SQLiteEventStore, interval: int = 50) -> None:
        self._store = store
        self._interval = interval
        # Per-run event counters
        self._counters: dict[str, int] = {}

    def on_event(self, event: WorkflowEvent) -> None:
        """EventBus subscriber callback (sync).

        Increments the per-run counter. When the counter reaches the interval,
        schedules a checkpoint via asyncio.ensure_future so it does not block
        the caller.
        """
        run_id = event.run_id
        count = self._counters.get(run_id, 0) + 1
        self._counters[run_id] = count

        if count % self._interval == 0:
            # Only CheckpointCreated events carry state_snapshot, so we only
            # snapshot when we receive one (full state available). For a generic
            # event we create a minimal checkpoint marker.
            if isinstance(event, CheckpointCreated):
                asyncio.ensure_future(self._store.save_checkpoint(event))
