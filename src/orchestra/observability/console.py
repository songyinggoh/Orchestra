"""Rich-based real-time trace renderer for Orchestra workflows.

Subscribes to EventBus and renders a live-updating terminal tree:

  Workflow: customer_support [3.2s]
  +-- triage (gpt-4o-mini) [1.1s] 150 tok $0.001 OK
  |   +-- LLM call [0.8s] 100 in / 50 out
  |   +-- tool: classify_ticket({priority: "high"}) -> "billing" [0.3s]
  +-- billing_agent (gpt-4o) [2.1s] 500 tok $0.015 OK
  |   +-- LLM call [1.8s] 350 in / 150 out
  |   +-- tool: lookup_account({id: "123"}) -> "{balance: 50}" [0.3s]
  +-- TOTAL: 650 tokens, $0.016, 3.2s

Controlled by environment variables:
- ORCHESTRA_TRACE=rich (default in dev) / off / verbose
- ORCHESTRA_ENV=dev (default) / prod (disables trace)
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

try:
    from rich.live import Live
    from rich.tree import Tree

    _RICH_AVAILABLE = True
except ImportError:  # pragma: no cover
    _RICH_AVAILABLE = False

if TYPE_CHECKING:
    from orchestra.storage.events import AnyEvent


def _truncate(text: str, max_len: int) -> str:
    """Truncate a string with ellipsis if too long."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


class RichTraceRenderer:
    """Real-time terminal trace renderer using Rich.

    Subscribes to EventBus and renders a live-updating tree.

    Controlled by ORCHESTRA_TRACE and ORCHESTRA_ENV env vars.
    Raises ImportError (with install hint) if rich is not installed.
    """

    def __init__(self, verbose: bool = False) -> None:
        if not _RICH_AVAILABLE:
            raise ImportError(
                "rich is required for trace rendering. "
                "Install it with: pip install orchestra[observability]"
            )
        self._verbose = verbose
        self._tree = Tree("Workflow")
        self._live: Live | None = None
        self._node_branches: dict[str, Any] = {}  # node_id -> Rich Tree branch
        self._node_start_times: dict[str, float] = {}  # node_id -> start epoch
        self._node_tokens: dict[str, int] = {}  # node_id -> accumulated tokens
        self._node_cost: dict[str, float] = {}  # node_id -> accumulated cost_usd
        self._start_time: float | None = None
        self._total_tokens: int = 0
        self._total_cost: float = 0.0
        self._workflow_name: str = "Workflow"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start Rich Live display."""
        self._start_time = time.monotonic()
        self._live = Live(self._tree, refresh_per_second=4)
        try:
            self._live.start()
        except Exception:
            # Gracefully degrade when no terminal is available (e.g., in tests).
            self._live = None

    def stop(self) -> None:
        """Stop Rich Live display, render final tree."""
        if self._live is not None:
            try:
                self._live.stop()
            except Exception:
                pass
            self._live = None

    # ------------------------------------------------------------------
    # EventBus subscriber
    # ------------------------------------------------------------------

    def on_event(self, event: AnyEvent) -> None:
        """Sync EventBus subscriber. Updates tree based on event type."""
        try:
            self._dispatch(event)
        except Exception:
            # Never let rendering crash the workflow.
            pass

    def _dispatch(self, event: Any) -> None:
        """Route event to the appropriate handler."""
        from orchestra.storage.events import (
            ExecutionCompleted,
            ExecutionStarted,
            LLMCalled,
            NodeCompleted,
            NodeStarted,
            ToolCalled,
        )

        if isinstance(event, ExecutionStarted):
            self._on_run_started(event)
        elif isinstance(event, NodeStarted):
            self._on_node_entered(event)
        elif isinstance(event, LLMCalled):
            self._on_llm_called(event)
        elif isinstance(event, ToolCalled):
            self._on_tool_called(event)
        elif isinstance(event, NodeCompleted):
            self._on_node_completed(event)
        elif isinstance(event, ExecutionCompleted):
            self._on_run_completed(event)
        # Unknown events are silently ignored (graceful handling).

    # ------------------------------------------------------------------
    # Per-event handlers
    # ------------------------------------------------------------------

    def _on_run_started(self, event: Any) -> None:
        name = getattr(event, "workflow_name", "workflow") or "workflow"
        self._workflow_name = name
        self._tree.label = f"[bold]Workflow:[/bold] {name}"
        self._start_time = time.monotonic()

    def _on_node_entered(self, event: Any) -> None:
        node_id = event.node_id
        self._node_start_times[node_id] = time.monotonic()
        self._node_tokens[node_id] = 0
        self._node_cost[node_id] = 0.0
        branch = self._tree.add(f"[dim]{node_id} ...[/dim]")
        self._node_branches[node_id] = branch

    def _on_llm_called(self, event: Any) -> None:
        node_id = event.node_id
        branch = self._node_branches.get(node_id)
        if branch is None:
            return

        in_tok = getattr(event, "input_tokens", 0) or 0
        out_tok = getattr(event, "output_tokens", 0) or 0
        cost = getattr(event, "cost_usd", 0.0) or 0.0
        duration_ms = getattr(event, "duration_ms", 0.0) or 0.0
        duration_s = duration_ms / 1000.0

        # Accumulate per-node totals
        self._node_tokens[node_id] = self._node_tokens.get(node_id, 0) + in_tok + out_tok
        self._node_cost[node_id] = self._node_cost.get(node_id, 0.0) + cost
        self._total_tokens += in_tok + out_tok
        self._total_cost += cost

        label = f"[dim]LLM [{duration_s:.1f}s] {in_tok} in / {out_tok} out ${cost:.4f}[/dim]"
        branch.add(label)

    def _on_tool_called(self, event: Any) -> None:
        node_id = event.node_id
        branch = self._node_branches.get(node_id)
        if branch is None:
            return

        tool_name = getattr(event, "tool_name", "") or ""
        args = getattr(event, "arguments", {}) or {}
        result = getattr(event, "result", None)
        duration_ms = getattr(event, "duration_ms", 0.0) or 0.0
        duration_s = duration_ms / 1000.0
        error = getattr(event, "error", None)

        max_len = 200 if self._verbose else 50

        args_str = _truncate(str(args), max_len)
        result_str = _truncate(str(result), max_len) if result is not None else "None"

        if error:
            label = (
                f"[red]tool: {tool_name}({args_str}) -> "
                f"ERROR: {_truncate(error, max_len)} [{duration_s:.2f}s][/red]"
            )
        else:
            label = (
                f"[cyan]tool: {tool_name}({args_str}) -> {result_str} [{duration_s:.2f}s][/cyan]"
            )

        branch.add(label)

    def _on_node_completed(self, event: Any) -> None:
        node_id = event.node_id
        branch = self._node_branches.get(node_id)
        if branch is None:
            return

        duration_ms = getattr(event, "duration_ms", 0.0) or 0.0
        duration_s = duration_ms / 1000.0

        total_tok = self._node_tokens.get(node_id, 0)
        cost = self._node_cost.get(node_id, 0.0)

        # Update branch label (replace the spinner/dim label)
        branch.label = f"[green]✓ {node_id} [{duration_s:.1f}s] {total_tok} tok ${cost:.4f}[/green]"

    def _on_run_completed(self, event: Any) -> None:
        status = getattr(event, "status", "completed") or "completed"
        duration_ms = getattr(event, "duration_ms", 0.0) or 0.0
        duration_s = duration_ms / 1000.0

        total_tokens = getattr(event, "total_tokens", None)
        if total_tokens is not None:
            self._total_tokens = total_tokens

        total_cost = getattr(event, "total_cost_usd", None)
        if total_cost is not None:
            self._total_cost = total_cost

        if status == "failed":
            self._tree.add(f"[red]FAILED after {duration_s:.1f}s[/red]")
        else:
            self._tree.add(
                f"[bold]TOTAL: {self._total_tokens} tokens, "
                f"${self._total_cost:.4f}, {duration_s:.1f}s[/bold]"
            )

    # ------------------------------------------------------------------
    # Properties for testing
    # ------------------------------------------------------------------

    @property
    def verbose(self) -> bool:
        """Whether verbose mode is active."""
        return self._verbose

    @property
    def total_tokens(self) -> int:
        """Accumulated total tokens across all LLM calls."""
        return self._total_tokens

    @property
    def total_cost(self) -> float:
        """Accumulated total cost across all LLM calls."""
        return self._total_cost
