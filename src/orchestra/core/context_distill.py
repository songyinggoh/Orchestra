"""Context distillation for agent handoffs.

Three-zone model for compressing conversation history before handoff:

1. Stable prefix  -- system messages (kept intact)
2. Compacted middleware -- intermediate reasoning/tool history (summarized)
3. Variable suffix -- last K turns (kept intact)

This approach preserves essential context while dramatically reducing
token cost for long conversations.

Usage:
    # With distillation (default for HandoffEdge):
    slim_history = distill_context(messages, max_middleware_tokens=500, keep_last_n_turns=3)

    # Without distillation (HandoffEdge(distill=False)):
    full_history = full_passthrough(messages)
"""

from __future__ import annotations

from typing import Any


def distill_context(
    messages: list[Any],
    *,
    max_middleware_tokens: int = 500,
    keep_last_n_turns: int = 3,
) -> list[Any]:
    """Distill conversation history for handoff.

    Three-zone partitioning:

    1. **Stable prefix** (system messages) -- kept intact.
    2. **Compacted middleware** (intermediate messages) -- summarized to
       at most ``max_middleware_tokens`` words in a single assistant message.
    3. **Variable suffix** (last ``keep_last_n_turns`` non-system messages)
       -- kept intact.

    Args:
        messages: Full conversation history (list of Message or dict).
        max_middleware_tokens: Maximum words in the middleware summary.
        keep_last_n_turns: Number of most-recent non-system messages to keep.

    Returns:
        Distilled message list.
    """
    if not messages:
        return []

    # Zone 1: stable prefix — all leading system messages
    prefix: list[Any] = []
    rest: list[Any] = []
    in_prefix = True
    for msg in messages:
        role = _get_role(msg)
        if in_prefix and role == "system":
            prefix.append(msg)
        else:
            in_prefix = False
            rest.append(msg)

    if not rest:
        # Only system messages — return as-is
        return list(prefix)

    # Zone 3: variable suffix — last N non-system messages
    suffix = rest[-keep_last_n_turns:] if keep_last_n_turns > 0 else []

    # Zone 2: middleware — everything in between
    middleware = rest[: max(0, len(rest) - keep_last_n_turns)]

    if not middleware:
        return prefix + suffix

    # Summarize middleware by concatenating content, then word-truncating
    parts: list[str] = []
    for msg in middleware:
        content = _get_content(msg)
        if content:
            parts.append(str(content))

    combined = " ".join(parts)
    words = combined.split()
    if len(words) > max_middleware_tokens:
        words = words[:max_middleware_tokens]
    summary_text = "[Context summary: " + " ".join(words) + "]"

    # Wrap summary as a single assistant message (same type as input)
    summary_msg = _make_summary_message(messages[0], summary_text)

    return prefix + [summary_msg] + suffix


def full_passthrough(messages: list[Any]) -> list[Any]:
    """No distillation -- pass all messages as-is.

    Used when HandoffEdge(distill=False) is specified.
    """
    return list(messages)


# ---------------------------------------------------------------------------
# Internal helpers — support both Message objects and plain dicts
# ---------------------------------------------------------------------------


def _get_role(msg: Any) -> str:
    """Extract role from a Message object or dict."""
    if isinstance(msg, dict):
        return str(msg.get("role", ""))
    role = getattr(msg, "role", "")
    # MessageRole enum has .value
    if hasattr(role, "value"):
        return str(role.value)
    return str(role)


def _get_content(msg: Any) -> str:
    """Extract content from a Message object or dict."""
    if isinstance(msg, dict):
        return str(msg.get("content", ""))
    return str(getattr(msg, "content", "") or "")


def _make_summary_message(template: Any, text: str) -> Any:
    """Create a summary message of the same type as the template."""
    if isinstance(template, dict):
        return {"role": "assistant", "content": text}
    # Try to construct a Message-like object
    try:
        from orchestra.core.types import Message, MessageRole
        return Message(role=MessageRole.ASSISTANT, content=text)
    except Exception:
        # Fallback to dict if types unavailable
        return {"role": "assistant", "content": text}
