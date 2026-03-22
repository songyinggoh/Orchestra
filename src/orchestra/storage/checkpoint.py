"""Workflow checkpoints for HITL (Interrupt/Resume).

Checkpoints capture the full state and execution context of a workflow
run at a specific node boundary, allowing it to be resumed later,
potentially in a different process.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Checkpoint(BaseModel):
    """A snapshot of workflow state and execution context."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    checkpoint_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    sequence_number: int = 0
    node_id: str
    interrupt_type: str  # "before" | "after"
    state: dict[str, Any]
    loop_counters: dict[str, int] = Field(default_factory=dict)
    node_execution_order: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def create(
        cls,
        run_id: str,
        node_id: str,
        interrupt_type: str,
        state: dict[str, Any],
        sequence_number: int,
        loop_counters: dict[str, int],
        node_execution_order: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> Checkpoint:
        """Factory for creating a new checkpoint."""
        return cls(
            run_id=run_id,
            node_id=node_id,
            interrupt_type=interrupt_type,
            state=state,
            sequence_number=sequence_number,
            loop_counters=loop_counters,
            node_execution_order=node_execution_order,
            metadata=metadata or {},
        )
