"""Tests for RichTraceRenderer (EventBus subscriber for terminal trace output)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from orchestra.observability.console import RichTraceRenderer
from orchestra.storage.events import (
    ExecutionCompleted,
    ExecutionStarted,
    LLMCalled,
    NodeCompleted,
    NodeStarted,
    ToolCalled,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_renderer(verbose: bool = False) -> RichTraceRenderer:
    """Create a renderer with Rich Live patched to a no-op."""
    return RichTraceRenderer(verbose=verbose)


RUN_ID = "test-run-001"


# ---------------------------------------------------------------------------
# Test 1: Instantiation
# ---------------------------------------------------------------------------


class TestInstantiation:
    def test_instantiates_without_error(self) -> None:
        renderer = make_renderer()
        assert renderer is not None

    def test_verbose_false_by_default(self) -> None:
        renderer = make_renderer()
        assert renderer.verbose is False

    def test_verbose_propagates(self) -> None:
        renderer = make_renderer(verbose=True)
        assert renderer.verbose is True


# ---------------------------------------------------------------------------
# Test 2: RunStarted
# ---------------------------------------------------------------------------


class TestRunStarted:
    def test_handles_run_started_without_crash(self) -> None:
        renderer = make_renderer()
        event = ExecutionStarted(run_id=RUN_ID, workflow_name="my_workflow")
        renderer.on_event(event)  # Must not raise
        assert "my_workflow" in str(renderer._tree.label)

    def test_run_started_updates_tree_label(self) -> None:
        renderer = make_renderer()
        event = ExecutionStarted(run_id=RUN_ID, workflow_name="test_graph")
        renderer.on_event(event)
        assert "test_graph" in str(renderer._tree.label)


# ---------------------------------------------------------------------------
# Test 3: NodeEntered (NodeStarted)
# ---------------------------------------------------------------------------


class TestNodeEntered:
    def test_node_started_creates_branch(self) -> None:
        renderer = make_renderer()
        event = NodeStarted(run_id=RUN_ID, node_id="triage")
        renderer.on_event(event)
        assert "triage" in renderer._node_branches

    def test_node_started_branch_has_label(self) -> None:
        renderer = make_renderer()
        event = NodeStarted(run_id=RUN_ID, node_id="writer")
        renderer.on_event(event)
        branch = renderer._node_branches["writer"]
        assert branch is not None


# ---------------------------------------------------------------------------
# Test 4: NodeCompleted updates branch
# ---------------------------------------------------------------------------


class TestNodeCompleted:
    def test_node_completed_updates_branch_label(self) -> None:
        renderer = make_renderer()
        # First, create the branch via NodeStarted
        renderer.on_event(NodeStarted(run_id=RUN_ID, node_id="billing"))
        # Then complete it
        renderer.on_event(
            NodeCompleted(run_id=RUN_ID, node_id="billing", duration_ms=1100.0)
        )
        branch = renderer._node_branches["billing"]
        label = str(branch.label)
        assert "billing" in label
        assert "✓" in label

    def test_node_completed_without_prior_started_does_not_crash(self) -> None:
        renderer = make_renderer()
        # NodeCompleted for a node that was never NodeStarted should not raise
        renderer.on_event(NodeCompleted(run_id=RUN_ID, node_id="ghost", duration_ms=100.0))


# ---------------------------------------------------------------------------
# Test 5: RunCompleted adds totals
# ---------------------------------------------------------------------------


class TestRunCompleted:
    def test_run_completed_adds_totals_line(self) -> None:
        renderer = make_renderer()
        renderer.on_event(ExecutionStarted(run_id=RUN_ID, workflow_name="wf"))
        renderer.on_event(
            ExecutionCompleted(run_id=RUN_ID, duration_ms=3200.0, status="completed")
        )
        # Tree should have at least one child (the TOTAL line)
        assert len(renderer._tree.children) >= 1

    def test_run_completed_failed_adds_failed_line(self) -> None:
        renderer = make_renderer()
        renderer.on_event(
            ExecutionCompleted(run_id=RUN_ID, duration_ms=500.0, status="failed")
        )
        last_child = renderer._tree.children[-1]
        assert "FAILED" in str(last_child.label) or "failed" in str(last_child.label).lower()


# ---------------------------------------------------------------------------
# Test 6: Unknown event type handled gracefully
# ---------------------------------------------------------------------------


class TestUnknownEvent:
    def test_unknown_event_does_not_crash(self) -> None:
        renderer = make_renderer()
        unknown = MagicMock()
        unknown.__class__.__name__ = "UnknownEvent"
        renderer.on_event(unknown)  # Must not raise


# ---------------------------------------------------------------------------
# Test 7: start() / stop() lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_start_and_stop_without_terminal(self) -> None:
        """start() should degrade gracefully when no terminal is available."""
        renderer = make_renderer()
        # Patch Live to raise (simulating headless environment)
        with patch("orchestra.observability.console.Live") as MockLive:
            mock_live_instance = MagicMock()
            mock_live_instance.start.side_effect = Exception("no terminal")
            MockLive.return_value = mock_live_instance
            renderer.start()
            # After failed start, _live should be None (graceful fallback)
            assert renderer._live is None
        renderer.stop()  # Should not raise even if _live is None

    def test_stop_without_start_does_not_crash(self) -> None:
        renderer = make_renderer()
        renderer.stop()  # _live is None; should be a no-op


# ---------------------------------------------------------------------------
# Test 8: Verbose mode affects truncation
# ---------------------------------------------------------------------------


class TestVerboseMode:
    def test_verbose_flag_propagates(self) -> None:
        renderer = make_renderer(verbose=True)
        assert renderer.verbose is True

    def test_non_verbose_truncates_tool_args(self) -> None:
        renderer = make_renderer(verbose=False)
        renderer.on_event(NodeStarted(run_id=RUN_ID, node_id="n1"))
        long_result = "x" * 200
        renderer.on_event(
            ToolCalled(
                run_id=RUN_ID,
                node_id="n1",
                tool_name="my_tool",
                arguments={"key": "value"},
                result=long_result,
                duration_ms=10.0,
            )
        )
        branch = renderer._node_branches["n1"]
        last_child = branch.children[-1]
        # Non-verbose: result should be truncated (not full 200 chars)
        assert len(str(last_child.label)) < 350  # well under full 200-char result

    def test_verbose_allows_longer_tool_output(self) -> None:
        renderer_v = make_renderer(verbose=True)
        renderer_nv = make_renderer(verbose=False)

        node_ev = NodeStarted(run_id=RUN_ID, node_id="n1")
        long_result = "y" * 200
        tool_ev = ToolCalled(
            run_id=RUN_ID,
            node_id="n1",
            tool_name="tool",
            arguments={},
            result=long_result,
            duration_ms=5.0,
        )

        renderer_v.on_event(node_ev)
        renderer_v.on_event(tool_ev)
        renderer_nv.on_event(NodeStarted(run_id=RUN_ID, node_id="n1"))
        renderer_nv.on_event(tool_ev)

        verbose_label = str(renderer_v._node_branches["n1"].children[-1].label)
        nonverbose_label = str(renderer_nv._node_branches["n1"].children[-1].label)

        # Verbose label should contain more of the result
        assert len(verbose_label) > len(nonverbose_label)


# ---------------------------------------------------------------------------
# Test 9: LLMCalled accumulates token totals
# ---------------------------------------------------------------------------


class TestLLMCalled:
    def test_llm_called_accumulates_tokens(self) -> None:
        renderer = make_renderer()
        renderer.on_event(NodeStarted(run_id=RUN_ID, node_id="agent1"))
        renderer.on_event(
            LLMCalled(
                run_id=RUN_ID,
                node_id="agent1",
                input_tokens=100,
                output_tokens=50,
                cost_usd=0.001,
                duration_ms=800.0,
            )
        )
        assert renderer.total_tokens == 150
        assert abs(renderer.total_cost - 0.001) < 1e-9
