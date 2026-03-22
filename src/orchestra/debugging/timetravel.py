"""Time-Travel Debugging Controller.

Enables state reconstruction and historical analysis of workflow runs
by projecting events up to a specific sequence number.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from orchestra.storage.store import project_state

if TYPE_CHECKING:
    from orchestra.storage.store import EventStore


@dataclass(frozen=True)
class HistoricalState:
    """Reconstructed state at a specific point in time."""

    run_id: str
    sequence_number: int
    state: dict[str, Any]
    node_id: str
    turn_number: int


class TimeTravelController:
    """Controller for historical state reconstruction and branching."""

    def __init__(self, event_store: EventStore) -> None:
        self.store = event_store

    async def get_state_at(self, run_id: str, sequence_number: int) -> HistoricalState:
        """Reconstruct the workflow state at a specific historical sequence.

        Args:
            run_id: The ID of the run to analyze.
            sequence_number: The sequence number to project up to (inclusive).

        Returns:
            HistoricalState object containing reconstructed state and metadata.
        """
        # 1. Fetch all events for the run up to the sequence
        events = await self.store.get_events(run_id, after_sequence=-1)

        # Filter to sequence (assuming events might come back unordered or full list)
        historical_events = [e for e in events if e.sequence <= sequence_number]

        if not historical_events:
            raise ValueError(
                f"No events found for run_id '{run_id}' up to sequence {sequence_number}"
            )

        # 2. Project state
        reconstructed_state = project_state(historical_events)

        # 3. Identify metadata (last active node, turn count)
        from orchestra.storage.events import ExecutionStarted, NodeStarted

        node_id = "unknown"
        turn_number = 0

        # Determine the active node at this point in history.
        # If the last event was NodeStarted, that's our node.
        # If it was NodeCompleted, we might be 'between' nodes (on an edge).
        # We'll use the most recent NodeStarted as the 'active' context.
        for e in reversed(historical_events):
            if isinstance(e, NodeStarted):
                node_id = e.node_id
                break

        # If still unknown, check ExecutionStarted for entry point
        if node_id == "unknown":
            for e in historical_events:
                if isinstance(e, ExecutionStarted):
                    node_id = e.entry_point
                    break

        # Calculate turn number (count NodeStarted events)
        turn_number = sum(1 for e in historical_events if isinstance(e, NodeStarted))

        return HistoricalState(
            run_id=run_id,
            sequence_number=sequence_number,
            state=reconstructed_state,
            node_id=node_id,
            turn_number=turn_number,
        )
