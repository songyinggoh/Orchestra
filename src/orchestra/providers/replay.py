"""Replay LLM Provider for side-effect safe time-travel.

Wraps historical events and returns recorded LLM responses instead of
calling real APIs during replay/forked phases.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from orchestra.core.types import LLMResponse, Message, TokenUsage, ToolCall
from orchestra.storage.events import LLMCalled


class ReplayProvider:
    """LLM Provider that 'plays back' recorded responses from history."""

    def __init__(self, historical_events: Iterable[Any]) -> None:
        # Index LLMCalled events by their sequence/node if possible,
        # or just maintain a queue.
        self._llm_calls = [e for e in historical_events if isinstance(e, LLMCalled)]
        self._ptr = 0

    async def complete(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Return the next recorded LLM response from history."""
        if self._ptr >= len(self._llm_calls):
            raise RuntimeError(
                "ReplayProvider exhausted historical LLM calls. "
                "The workflow has diverged from history."
            )

        call = self._llm_calls[self._ptr]
        self._ptr += 1

        # Reconstruct tool calls
        tool_calls = []
        if call.tool_calls:
            for tc_dict in call.tool_calls:
                tool_calls.append(ToolCall.model_validate(tc_dict))

        # Reconstruct LLMResponse from event
        return LLMResponse(
            content=call.content or "",
            tool_calls=tool_calls,
            usage=TokenUsage(
                input_tokens=call.input_tokens,
                output_tokens=call.output_tokens,
                total_tokens=call.input_tokens + call.output_tokens,
                estimated_cost_usd=call.cost_usd,
            ),
            model=call.model,
        )
