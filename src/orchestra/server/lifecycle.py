"""Graph registry and run management for the Orchestra server."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from orchestra.server.models import GraphInfo, RunStatus
from orchestra.storage.events import WorkflowEvent

if TYPE_CHECKING:
    from orchestra.core.compiled import CompiledGraph
    from orchestra.storage.store import EventStore

logger = structlog.get_logger(__name__)


class GraphRegistry:
    """Thread-safe registry for CompiledGraph instances keyed by name.

    Graphs are registered at startup and looked up when runs are created.
    """

    def __init__(self) -> None:
        self._graphs: dict[str, CompiledGraph] = {}
        self._lock = threading.Lock()

    def register(self, name: str, graph: CompiledGraph) -> None:
        """Register a compiled graph under the given name."""
        with self._lock:
            self._graphs[name] = graph

    def get(self, name: str) -> CompiledGraph | None:
        """Look up a graph by name. Returns None if not found."""
        with self._lock:
            return self._graphs.get(name)

    def list_graphs(self) -> list[GraphInfo]:
        """Return info about all registered graphs."""
        with self._lock:
            result: list[GraphInfo] = []
            for name, graph in self._graphs.items():
                edges_list: list[dict[str, Any]] = []
                for edge in graph._edges:
                    target = getattr(edge, "target", getattr(edge, "targets", ""))
                    # Convert sentinel objects (END) to strings for serialization
                    if not isinstance(target, (str, list)):
                        target = str(target)
                    elif isinstance(target, list):
                        target = [str(t) if not isinstance(t, str) else t for t in target]
                    edges_list.append(
                        {
                            "type": type(edge).__name__,
                            "source": getattr(edge, "source", ""),
                            "target": target,
                        }
                    )
                result.append(
                    GraphInfo(
                        name=name,
                        nodes=list(graph._nodes.keys()),
                        edges=edges_list,
                        entry_point=graph._entry_point,
                        mermaid=graph.to_mermaid(),
                    )
                )
            return result


@dataclass
class ActiveRun:
    """Tracks a running workflow execution."""

    run_id: str
    task: asyncio.Task[Any]
    event_store: EventStore
    status: str = "running"
    graph_name: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_queue: asyncio.Queue[WorkflowEvent | None] = field(default_factory=asyncio.Queue)


class RunManager:
    """Manages active workflow runs as asyncio.Tasks.

    Runs are decoupled from the HTTP request lifecycle so they
    survive client disconnects.
    """

    def __init__(self) -> None:
        self._runs: dict[str, ActiveRun] = {}

    async def start_run(
        self,
        run_id: str,
        graph: CompiledGraph,
        input_data: dict[str, Any],
        event_store: EventStore,
    ) -> ActiveRun:
        """Start a workflow run as a background asyncio.Task."""

        active_run = ActiveRun(
            run_id=run_id,
            task=asyncio.Future(),  # placeholder, replaced below
            event_store=event_store,
            graph_name=graph._name or "workflow",
        )

        # Subscribe a callback that feeds events into the run's queue
        # for SSE streaming clients.
        async def _queue_callback(event: WorkflowEvent) -> None:
            if event.run_id == run_id:
                await active_run.event_queue.put(event)

        # We need to attach the callback to the event bus created inside
        # CompiledGraph.run(). We do this by passing our own event store
        # that also notifies the queue.
        class _BroadcastStore:
            """Wraps an EventStore to also feed an asyncio.Queue."""

            def __init__(
                self, inner: EventStore, queue: asyncio.Queue[WorkflowEvent | None]
            ) -> None:
                self._inner = inner
                self._queue = queue

            async def append(self, event: WorkflowEvent) -> None:
                await self._inner.append(event)
                await self._queue.put(event)

            # Delegate all other EventStore methods
            async def get_events(self, *args: Any, **kwargs: Any) -> Any:
                return await self._inner.get_events(*args, **kwargs)

            async def get_latest_checkpoint(self, *args: Any, **kwargs: Any) -> Any:
                return await self._inner.get_latest_checkpoint(*args, **kwargs)

            async def get_checkpoint(self, *args: Any, **kwargs: Any) -> Any:
                return await self._inner.get_checkpoint(*args, **kwargs)

            async def save_checkpoint(self, *args: Any, **kwargs: Any) -> Any:
                return await self._inner.save_checkpoint(*args, **kwargs)

            async def list_runs(self, *args: Any, **kwargs: Any) -> Any:
                return await self._inner.list_runs(*args, **kwargs)

            async def create_run(self, *args: Any, **kwargs: Any) -> Any:
                return await self._inner.create_run(*args, **kwargs)

            async def update_run_status(self, *args: Any, **kwargs: Any) -> Any:
                return await self._inner.update_run_status(*args, **kwargs)

        broadcast_store = _BroadcastStore(event_store, active_run.event_queue)

        async def _run_workflow() -> dict[str, Any]:
            try:
                result = await graph.run(
                    input=input_data,
                    run_id=run_id,
                    event_store=broadcast_store,  # type: ignore[arg-type]
                    persist=False,  # we manage store ourselves
                )
                active_run.status = "completed"
                return result
            except Exception as exc:
                active_run.status = "failed"
                logger.error("run_failed", run_id=run_id, error=str(exc))
                raise
            finally:
                # Signal end-of-stream to any waiting SSE clients
                await active_run.event_queue.put(None)

        task = asyncio.create_task(_run_workflow(), name=f"run-{run_id}")
        active_run.task = task
        self._runs[run_id] = active_run
        return active_run

    def get_run(self, run_id: str) -> ActiveRun | None:
        """Look up a run by ID."""
        return self._runs.get(run_id)

    async def list_runs(self) -> list[RunStatus]:
        """List all tracked runs with their current status."""
        result: list[RunStatus] = []
        for run_id, active in self._runs.items():
            result.append(
                RunStatus(
                    run_id=run_id,
                    status=active.status,
                    created_at=active.created_at.isoformat(),
                    event_count=active.event_queue.qsize(),
                )
            )
        return result
