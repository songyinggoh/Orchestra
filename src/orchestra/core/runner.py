"""Top-level run() and run_sync() functions.

Usage:
    from orchestra import run, run_sync

    # Async
    result = await run(graph, input={"topic": "quantum computing"})

    # Sync (for scripts and notebooks)
    result = run_sync(graph, input={"topic": "quantum computing"})
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from pydantic import BaseModel, Field

from orchestra.core.context import ExecutionContext


class RunResult(BaseModel):
    """Result of a workflow run."""

    output: Any = None
    state: dict[str, Any] = Field(default_factory=dict)
    messages: list[Any] = Field(default_factory=list)
    run_id: str = ""
    duration_ms: float = 0.0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    node_execution_order: list[str] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}


async def run(
    graph: Any,
    input: str | dict[str, Any] | None = None,
    *,
    initial_state: dict[str, Any] | None = None,
    provider: Any = None,
    config: dict[str, Any] | None = None,
) -> RunResult:
    """Run a workflow graph (or compiled graph) and return a RunResult.

    Args:
        graph: A WorkflowGraph or CompiledGraph.
        input: Input data (string or dict).
        initial_state: Full initial state dict.
        provider: LLM provider instance.
        config: Additional configuration.

    Returns:
        RunResult with output, state, metrics.
    """
    from orchestra.core.compiled import CompiledGraph
    from orchestra.core.graph import WorkflowGraph

    # Compile if needed
    if isinstance(graph, WorkflowGraph):
        compiled = graph.compile()
    elif isinstance(graph, CompiledGraph):
        compiled = graph
    else:
        raise TypeError(
            f"Expected WorkflowGraph or CompiledGraph, got {type(graph).__name__}.\n"
            f"  Fix: Pass a graph built with WorkflowGraph() or graph.compile()."
        )

    run_id = uuid.uuid4().hex
    context = ExecutionContext(
        run_id=run_id,
        provider=provider,
        config=config or {},
    )

    start = time.monotonic()
    final_state = await compiled.run(
        initial_state=initial_state,
        input=input,
        context=context,
        provider=provider,
    )
    duration_ms = (time.monotonic() - start) * 1000

    # Extract output
    output = final_state.get("output", "")
    messages = final_state.get("messages", [])
    node_order = context.node_execution_order

    return RunResult(
        output=output,
        state=final_state,
        messages=messages,
        run_id=run_id,
        duration_ms=duration_ms,
        node_execution_order=node_order,
    )


def run_sync(
    graph: Any,
    input: str | dict[str, Any] | None = None,
    *,
    initial_state: dict[str, Any] | None = None,
    provider: Any = None,
    config: dict[str, Any] | None = None,
) -> RunResult:
    """Synchronous wrapper around run() for scripts and notebooks."""
    return asyncio.run(
        run(
            graph,
            input=input,
            initial_state=initial_state,
            provider=provider,
            config=config,
        )
    )
