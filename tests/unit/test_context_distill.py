"""Unit tests for context_distill — three-zone context compression for handoffs."""

from __future__ import annotations

from orchestra.core.context_distill import (
    _get_content,
    _get_role,
    _make_summary_message,
    distill_context,
    full_passthrough,
)
from orchestra.core.types import Message, MessageRole

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def sys_msg(text: str) -> dict:
    return {"role": "system", "content": text}


def user_msg(text: str) -> dict:
    return {"role": "user", "content": text}


def asst_msg(text: str) -> dict:
    return {"role": "assistant", "content": text}


def typed_msg(role: MessageRole, text: str) -> Message:
    return Message(role=role, content=text)


# ---------------------------------------------------------------------------
# full_passthrough
# ---------------------------------------------------------------------------


class TestFullPassthrough:
    def test_returns_copy_of_all_messages(self):
        msgs = [user_msg("hello"), asst_msg("hi")]
        result = full_passthrough(msgs)
        assert result == msgs
        assert result is not msgs  # must be a new list

    def test_empty_input(self):
        assert full_passthrough([]) == []

    def test_single_message(self):
        msgs = [user_msg("x")]
        assert full_passthrough(msgs) == msgs


# ---------------------------------------------------------------------------
# distill_context — empty / edge cases
# ---------------------------------------------------------------------------


class TestDistillContextEdgeCases:
    def test_empty_messages_returns_empty(self):
        assert distill_context([]) == []

    def test_only_system_messages_returned_intact(self):
        msgs = [sys_msg("sys1"), sys_msg("sys2")]
        result = distill_context(msgs)
        assert result == msgs

    def test_single_user_message_no_middleware(self):
        msgs = [user_msg("hello")]
        result = distill_context(msgs, keep_last_n_turns=1)
        # no middleware, suffix = [user_msg]
        assert result == msgs

    def test_keep_last_n_zero_drops_everything(self):
        msgs = [user_msg("a"), asst_msg("b")]
        result = distill_context(msgs, keep_last_n_turns=0)
        # suffix empty, no middleware collapses, prefix empty → empty list
        assert result == []


# ---------------------------------------------------------------------------
# distill_context — three-zone partitioning
# ---------------------------------------------------------------------------


class TestDistillContextThreeZones:
    def test_prefix_preserved(self):
        msgs = [
            sys_msg("You are helpful."),
            user_msg("first"),
            asst_msg("second"),
            user_msg("third"),
        ]
        result = distill_context(msgs, keep_last_n_turns=1)
        # prefix = system message; suffix = last 1 non-system msg
        # middleware = [user first, asst second]
        assert result[0] == sys_msg("You are helpful.")

    def test_suffix_preserved_at_end(self):
        msgs = [
            user_msg("a"),
            asst_msg("b"),
            user_msg("c"),
        ]
        result = distill_context(msgs, keep_last_n_turns=1)
        assert result[-1] == user_msg("c")

    def test_middleware_becomes_single_summary(self):
        msgs = [
            user_msg("a"),
            asst_msg("b"),
            user_msg("c"),  # suffix
        ]
        result = distill_context(msgs, keep_last_n_turns=1)
        # prefix=[], middleware=[user a, asst b], suffix=[user c]
        assert len(result) == 2
        summary = result[0]
        assert "[Context summary:" in summary.get("content", "") or (
            hasattr(summary, "content") and "[Context summary:" in summary.content
        )

    def test_no_middleware_when_suffix_covers_all(self):
        msgs = [user_msg("a"), asst_msg("b")]
        result = distill_context(msgs, keep_last_n_turns=5)
        # keep_last_n_turns=5 > len(msgs)=2 so no middleware
        assert result == msgs

    def test_middleware_word_truncation(self):
        # Build a long middleware section
        long_text = " ".join(["word"] * 1000)
        msgs = [
            asst_msg(long_text),
            user_msg("final"),
        ]
        result = distill_context(msgs, max_middleware_tokens=50, keep_last_n_turns=1)
        summary = result[0]
        content = summary.get("content", "") if isinstance(summary, dict) else summary.content
        # should have no more than 50 words in the summary body
        # "[Context summary: word word ...]"
        body = content.replace("[Context summary:", "").rstrip("]").strip()
        assert len(body.split()) <= 50

    def test_system_prefix_isolation(self):
        """System messages are only collected from the leading position."""
        msgs = [
            sys_msg("sys1"),
            user_msg("user1"),
            sys_msg("sys2"),  # mid-message sys — treated as non-prefix
            user_msg("user2"),
        ]
        result = distill_context(msgs, keep_last_n_turns=1)
        # prefix should only contain sys1
        prefix = [
            m
            for m in result
            if (m.get("role") == "system" if isinstance(m, dict) else m.role == MessageRole.SYSTEM)
        ]
        assert len(prefix) == 1


# ---------------------------------------------------------------------------
# distill_context — with typed Message objects
# ---------------------------------------------------------------------------


class TestDistillContextWithTypedMessages:
    def test_typed_messages_preserved(self):
        msgs = [
            typed_msg(MessageRole.SYSTEM, "You are helpful."),
            typed_msg(MessageRole.USER, "hi"),
        ]
        result = distill_context(msgs, keep_last_n_turns=2)
        assert len(result) == 2
        assert result[0] == msgs[0]

    def test_summary_message_is_typed_when_input_is_typed(self):
        msgs = [
            typed_msg(MessageRole.USER, "a"),
            typed_msg(MessageRole.ASSISTANT, "b"),
            typed_msg(MessageRole.USER, "c"),
        ]
        result = distill_context(msgs, keep_last_n_turns=1)
        summary = result[0]
        # summary should be a Message object (matching template type)
        assert isinstance(summary, Message)
        assert summary.role == MessageRole.ASSISTANT
        assert "[Context summary:" in summary.content

    def test_mixed_types_fallback_to_dict(self):
        """dict template → summary also a dict."""
        msgs = [
            user_msg("a"),
            asst_msg("b"),
            user_msg("c"),
        ]
        result = distill_context(msgs, keep_last_n_turns=1)
        summary = result[0]
        assert isinstance(summary, dict)
        assert summary["role"] == "assistant"


# ---------------------------------------------------------------------------
# Internal helper tests
# ---------------------------------------------------------------------------


class TestInternalHelpers:
    def test_get_role_dict(self):
        assert _get_role({"role": "user", "content": "hi"}) == "user"

    def test_get_role_object(self):
        msg = typed_msg(MessageRole.USER, "hi")
        assert _get_role(msg) == "user"

    def test_get_role_missing(self):
        assert _get_role({}) == ""

    def test_get_content_dict(self):
        assert _get_content({"role": "user", "content": "hello"}) == "hello"

    def test_get_content_object(self):
        msg = typed_msg(MessageRole.USER, "hello")
        assert _get_content(msg) == "hello"

    def test_get_content_none(self):
        assert _get_content({"role": "user"}) == "None"

    def test_make_summary_message_dict(self):
        result = _make_summary_message({"role": "user", "content": "x"}, "summary text")
        assert result == {"role": "assistant", "content": "summary text"}

    def test_make_summary_message_typed(self):
        template = typed_msg(MessageRole.USER, "x")
        result = _make_summary_message(template, "summary text")
        assert isinstance(result, Message)
        assert result.content == "summary text"
        assert result.role == MessageRole.ASSISTANT
