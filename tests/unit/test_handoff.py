"""Tests for HandoffEdge, HandoffPayload, distill_context, and add_handoff()."""

from __future__ import annotations

import pytest

from orchestra.core.context_distill import distill_context, full_passthrough
from orchestra.core.graph import WorkflowGraph
from orchestra.core.handoff import HandoffEdge, HandoffPayload
from orchestra.core.types import Message, MessageRole

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def sys_msg(content: str) -> Message:
    return Message(role=MessageRole.SYSTEM, content=content)


def user_msg(content: str) -> Message:
    return Message(role=MessageRole.USER, content=content)


def asst_msg(content: str) -> Message:
    return Message(role=MessageRole.ASSISTANT, content=content)


def tool_msg(content: str) -> Message:
    return Message(role=MessageRole.TOOL, content=content)


async def _noop(state: dict) -> dict:  # type: ignore[type-arg]
    return {}


# ---------------------------------------------------------------------------
# Test 1: add_handoff() creates HandoffEdge and registers it
# ---------------------------------------------------------------------------


class TestAddHandoff:
    def test_add_handoff_creates_edge(self) -> None:
        graph = WorkflowGraph()
        graph.add_node("triage", _noop)
        graph.add_node("specialist", _noop)
        graph.add_handoff("triage", "specialist")
        assert len(graph._handoff_edges) == 1
        edge = graph._handoff_edges[0]
        assert edge.source == "triage"
        assert edge.target == "specialist"

    def test_add_handoff_returns_graph_for_chaining(self) -> None:
        graph = WorkflowGraph()
        graph.add_node("a", _noop)
        graph.add_node("b", _noop)
        result = graph.add_handoff("a", "b")
        assert result is graph

    def test_add_handoff_multiple_edges(self) -> None:
        graph = WorkflowGraph()
        graph.add_node("a", _noop)
        graph.add_node("b", _noop)
        graph.add_node("c", _noop)
        graph.add_handoff("a", "b")
        graph.add_handoff("a", "c")
        assert len(graph._handoff_edges) == 2

    def test_add_handoff_distill_default_true(self) -> None:
        graph = WorkflowGraph()
        graph.add_node("x", _noop)
        graph.add_node("y", _noop)
        graph.add_handoff("x", "y")
        assert graph._handoff_edges[0].distill is True

    def test_add_handoff_distill_false(self) -> None:
        graph = WorkflowGraph()
        graph.add_node("x", _noop)
        graph.add_node("y", _noop)
        graph.add_handoff("x", "y", distill=False)
        assert graph._handoff_edges[0].distill is False


# ---------------------------------------------------------------------------
# Test 2: HandoffEdge is frozen (immutable)
# ---------------------------------------------------------------------------


class TestHandoffEdgeFrozen:
    def test_handoff_edge_is_frozen(self) -> None:
        edge = HandoffEdge(source="a", target="b")
        with pytest.raises((AttributeError, TypeError)):
            edge.source = "c"  # type: ignore[misc]

    def test_handoff_edge_stores_condition(self) -> None:
        cond = lambda s: s.get("escalate")  # noqa: E731
        edge = HandoffEdge(source="triage", target="expert", condition=cond, distill=True)
        assert edge.condition is cond


# ---------------------------------------------------------------------------
# Test 3: distill_context with only system messages
# ---------------------------------------------------------------------------


class TestDistillContextSystemOnly:
    def test_only_system_messages_returned_intact(self) -> None:
        msgs = [sys_msg("You are helpful."), sys_msg("Be concise.")]
        result = distill_context(msgs)
        assert len(result) == 2
        assert result[0].role == MessageRole.SYSTEM
        assert result[1].role == MessageRole.SYSTEM

    def test_empty_messages_returns_empty(self) -> None:
        result = distill_context([])
        assert result == []


# ---------------------------------------------------------------------------
# Test 4: distill_context compresses middleware
# ---------------------------------------------------------------------------


class TestDistillContextMiddleware:
    def test_middleware_compressed_into_single_message(self) -> None:
        """Many intermediate messages should be summarized into one."""
        msgs = (
            [sys_msg("You are a triage agent.")]
            + [user_msg(f"step {i}") for i in range(10)]
            + [asst_msg(f"response {i}") for i in range(10)]
        )
        result = distill_context(msgs, max_middleware_tokens=50, keep_last_n_turns=3)
        # Should have: 1 system + 1 summary + 3 tail messages
        assert len(result) == 1 + 1 + 3

    def test_middleware_summary_starts_with_context_summary(self) -> None:
        msgs = (
            [sys_msg("sys")]
            + [user_msg(f"intermediate {i}") for i in range(5)]
            + [user_msg("final1"), asst_msg("final2"), user_msg("final3")]
        )
        result = distill_context(msgs, max_middleware_tokens=100, keep_last_n_turns=3)
        # The summary message should be the second item (after system)
        summary = result[1]
        content = summary.content if hasattr(summary, "content") else summary.get("content", "")
        assert "[Context summary:" in content

    def test_middleware_truncated_to_max_tokens(self) -> None:
        """Summary word count should not exceed max_middleware_tokens."""
        long_content = " ".join(["word"] * 1000)
        msgs = [
            sys_msg("sys"),
            user_msg(long_content),
            user_msg("tail1"),
            asst_msg("tail2"),
            user_msg("tail3"),
        ]
        result = distill_context(msgs, max_middleware_tokens=20, keep_last_n_turns=3)
        summary = result[1]
        content = summary.content if hasattr(summary, "content") else summary.get("content", "")
        # Word count within the summary brackets should be <= 20
        inner = content.replace("[Context summary: ", "").rstrip("]")
        word_count = len(inner.split())
        assert word_count <= 20


# ---------------------------------------------------------------------------
# Test 5: distill_context keeps last N turns intact
# ---------------------------------------------------------------------------


class TestDistillContextSuffix:
    def test_last_n_turns_kept_intact(self) -> None:
        tail = [user_msg("u1"), asst_msg("a1"), user_msg("u2")]
        msgs = [sys_msg("sys")] + [user_msg(f"mid{i}") for i in range(5)] + tail
        result = distill_context(msgs, keep_last_n_turns=3)
        # Last 3 messages in result must match tail
        assert result[-3].content == "u1"
        assert result[-2].content == "a1"
        assert result[-1].content == "u2"

    def test_no_middleware_when_few_messages(self) -> None:
        """When messages <= keep_last_n_turns, no summary is added."""
        msgs = [user_msg("a"), asst_msg("b"), user_msg("c")]
        result = distill_context(msgs, keep_last_n_turns=3)
        # No summary needed -- just the 3 messages
        assert len(result) == 3


# ---------------------------------------------------------------------------
# Test 6: full_passthrough returns identical list
# ---------------------------------------------------------------------------


class TestFullPassthrough:
    def test_full_passthrough_returns_all_messages(self) -> None:
        msgs = [sys_msg("sys"), user_msg("hi"), asst_msg("hello")]
        result = full_passthrough(msgs)
        assert len(result) == 3

    def test_full_passthrough_is_a_copy(self) -> None:
        msgs = [user_msg("hi")]
        result = full_passthrough(msgs)
        assert result is not msgs  # New list object
        assert result == msgs

    def test_full_passthrough_empty(self) -> None:
        assert full_passthrough([]) == []


# ---------------------------------------------------------------------------
# Test 7: HandoffPayload is frozen (immutable)
# ---------------------------------------------------------------------------


class TestHandoffPayloadFrozen:
    def test_payload_is_frozen(self) -> None:
        payload = HandoffPayload.create(
            from_agent="triage",
            to_agent="expert",
            reason="needs expertise",
            conversation_history=[],
        )
        with pytest.raises((AttributeError, TypeError)):
            payload.from_agent = "other"  # type: ignore[misc]

    def test_payload_stores_fields(self) -> None:
        msgs = [user_msg("help")]
        payload = HandoffPayload.create(
            from_agent="a",
            to_agent="b",
            reason="reason_x",
            conversation_history=msgs,
            metadata={"priority": "high"},
            distilled=True,
        )
        assert payload.from_agent == "a"
        assert payload.to_agent == "b"
        assert payload.reason == "reason_x"
        assert payload.distilled is True
        assert payload.metadata_dict() == {"priority": "high"}
        assert len(payload.history_list()) == 1


# ---------------------------------------------------------------------------
# Test 8: Conditional HandoffEdge stores condition correctly
# ---------------------------------------------------------------------------


class TestConditionalHandoffEdge:
    def test_condition_stored_on_edge(self) -> None:
        cond = lambda s: s.get("route") == "expert"  # noqa: E731
        edge = HandoffEdge(source="triage", target="expert", condition=cond)
        assert edge.condition is cond

    def test_condition_none_by_default(self) -> None:
        edge = HandoffEdge(source="a", target="b")
        assert edge.condition is None

    def test_add_handoff_stores_condition(self) -> None:
        cond = lambda s: True  # noqa: E731
        graph = WorkflowGraph()
        graph.add_node("a", _noop)
        graph.add_node("b", _noop)
        graph.add_handoff("a", "b", condition=cond)
        assert graph._handoff_edges[0].condition is cond


# ---------------------------------------------------------------------------
# Test 9: distill=False edge passes through without distillation
# ---------------------------------------------------------------------------


class TestDistillFalseEdge:
    def test_distill_false_stored_on_edge(self) -> None:
        edge = HandoffEdge(source="a", target="b", distill=False)
        assert edge.distill is False

    def test_full_passthrough_used_when_distill_false(self) -> None:
        """Verify full_passthrough preserves all messages."""
        msgs = [sys_msg("sys")] + [user_msg(f"msg{i}") for i in range(20)]
        result = full_passthrough(msgs)
        assert len(result) == 21  # all preserved


# ---------------------------------------------------------------------------
# Test 10: distill_context with empty messages
# ---------------------------------------------------------------------------


class TestDistillContextEmpty:
    def test_empty_list_returns_empty_list(self) -> None:
        result = distill_context([])
        assert result == []

    def test_single_system_message(self) -> None:
        result = distill_context([sys_msg("Be helpful.")])
        assert len(result) == 1
        assert result[0].content == "Be helpful."

    def test_single_user_message(self) -> None:
        result = distill_context([user_msg("hello")])
        assert len(result) == 1
        assert result[0].content == "hello"
