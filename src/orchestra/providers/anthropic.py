"""Anthropic provider for Claude models.

Uses httpx directly (zero extra dependencies beyond core).
Handles Anthropic's Messages API format which differs from OpenAI's.

Usage:
    from orchestra.providers import AnthropicProvider

    provider = AnthropicProvider(api_key="sk-ant-...")
    # Or set ANTHROPIC_API_KEY env var
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx

from orchestra.core.errors import (
    AuthenticationError,
    ContextWindowError,
    ProviderError,
    ProviderUnavailableError,
    RateLimitError,
)
from orchestra.core.types import (
    LLMResponse,
    Message,
    MessageRole,
    ModelCost,
    StreamChunk,
    TokenUsage,
    ToolCall,
)

# Approximate costs per 1K tokens (input/output)
_MODEL_COSTS: dict[str, tuple[float, float]] = {
    "claude-opus-4-6": (0.015, 0.075),
    "claude-sonnet-4-6": (0.003, 0.015),
    "claude-haiku-4-5-20251001": (0.0008, 0.004),
    "claude-3-5-sonnet-20241022": (0.003, 0.015),
    "claude-3-5-haiku-20241022": (0.0008, 0.004),
}


def _messages_to_anthropic_format(
    messages: list[Message],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Convert Orchestra Messages to Anthropic API format.

    Returns (system_prompt, messages) since Anthropic separates system
    from the messages array.
    """
    system_prompt: str | None = None
    result: list[dict[str, Any]] = []

    for msg in messages:
        if msg.role == MessageRole.SYSTEM:
            system_prompt = msg.content
            continue

        if msg.role == MessageRole.TOOL:
            result.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id or "",
                        "content": msg.content,
                    }
                ],
            })
            continue

        role = "assistant" if msg.role == MessageRole.ASSISTANT else "user"
        content: Any

        if msg.tool_calls:
            # Assistant message with tool calls
            blocks: list[dict[str, Any]] = []
            if msg.content:
                blocks.append({"type": "text", "text": msg.content})
            for tc in msg.tool_calls:
                blocks.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.arguments,
                })
            content = blocks
        else:
            content = msg.content

        result.append({"role": role, "content": content})

    return system_prompt, result


def _tools_to_anthropic_format(
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert OpenAI-style tool schemas to Anthropic format."""
    result = []
    for t in tools:
        func = t.get("function", t)
        result.append({
            "name": func.get("name", ""),
            "description": func.get("description", ""),
            "input_schema": func.get("parameters", {}),
        })
    return result


class AnthropicProvider:
    """Anthropic Claude provider using the Messages API.

    Handles the Anthropic-specific API format (system prompt separation,
    tool_use/tool_result content blocks, different response structure).
    """

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = "claude-sonnet-4-6",
        max_retries: int = 3,
        timeout: float = 120.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._default_model = default_model
        self._max_retries = max_retries
        self._client = httpx.AsyncClient(
            base_url="https://api.anthropic.com",
            timeout=timeout,
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def default_model(self) -> str:
        return self._default_model

    async def complete(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        output_type: Any = None,
    ) -> LLMResponse:
        """Send a chat completion request to the Anthropic Messages API."""
        use_model = model or self._default_model
        system_prompt, api_messages = _messages_to_anthropic_format(messages)

        body: dict[str, Any] = {
            "model": use_model,
            "messages": api_messages,
            "max_tokens": max_tokens or 4096,
            "temperature": temperature,
        }
        if system_prompt:
            body["system"] = system_prompt
        if tools:
            body["tools"] = _tools_to_anthropic_format(tools)

        response_data = await self._request_with_retry(body)
        return self._parse_response(response_data, use_model)

    async def stream(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream chat completion responses from Anthropic."""
        use_model = model or self._default_model
        system_prompt, api_messages = _messages_to_anthropic_format(messages)

        body: dict[str, Any] = {
            "model": use_model,
            "messages": api_messages,
            "max_tokens": max_tokens or 4096,
            "temperature": temperature,
            "stream": True,
        }
        if system_prompt:
            body["system"] = system_prompt
        if tools:
            body["tools"] = _tools_to_anthropic_format(tools)

        async with self._client.stream(
            "POST", "/v1/messages", json=body
        ) as response:
            if response.status_code != 200:
                text = ""
                async for chunk in response.aiter_text():
                    text += chunk
                self._handle_error_status(response.status_code, text)

            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type", "")

                if event_type == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        yield StreamChunk(
                            content=delta.get("text", ""),
                            model=use_model,
                        )

                elif event_type == "message_delta":
                    stop = event.get("delta", {}).get("stop_reason")
                    if stop:
                        reason = "tool_calls" if stop == "tool_use" else "stop"
                        yield StreamChunk(
                            content="",
                            finish_reason=reason,
                            model=use_model,
                        )

                elif event_type == "message_stop":
                    break

    def count_tokens(self, messages: list[Message], model: str | None = None) -> int:
        """Approximate token count (4 chars per token heuristic)."""
        total = 0
        for msg in messages:
            total += len(msg.content) // 4 + 4
        return total

    def get_model_cost(self, model: str | None = None) -> ModelCost:
        """Get cost information for a model."""
        m = model or self._default_model
        costs = _MODEL_COSTS.get(m, (0.0, 0.0))
        return ModelCost(input_cost_per_1k=costs[0], output_cost_per_1k=costs[1])

    async def _request_with_retry(self, body: dict[str, Any]) -> dict[str, Any]:
        """Make HTTP request with retry logic."""
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.post("/v1/messages", json=body)

                if response.status_code == 200:
                    result: dict[str, Any] = response.json()
                    return result

                self._handle_error_status(response.status_code, response.text)

            except (AuthenticationError, ContextWindowError):
                raise
            except (RateLimitError, ProviderUnavailableError) as e:
                last_error = e
                if attempt < self._max_retries:
                    import asyncio

                    delay = min(2**attempt, 30)
                    if isinstance(e, RateLimitError) and e.retry_after_seconds:
                        delay = e.retry_after_seconds
                    await asyncio.sleep(delay)
            except httpx.HTTPError as e:
                last_error = ProviderUnavailableError(
                    f"HTTP error: {e}\n"
                    f"  Endpoint: https://api.anthropic.com\n"
                    f"  Fix: Check network connectivity."
                )
                if attempt < self._max_retries:
                    import asyncio

                    await asyncio.sleep(2**attempt)

        raise last_error or ProviderError("Request failed after retries")

    def _handle_error_status(self, status_code: int, text: str) -> None:
        """Convert HTTP error status to Orchestra exception."""
        if status_code == 401:
            raise AuthenticationError(
                "Authentication failed (401).\n"
                "  Fix: Check your API key or set ANTHROPIC_API_KEY env var."
            )
        elif status_code == 429:
            raise RateLimitError(
                f"Rate limited (429).\n"
                f"  Response: {text[:200]}"
            )
        elif status_code == 400 and "context" in text.lower():
            raise ContextWindowError(
                f"Context window exceeded.\n"
                f"  Response: {text[:200]}\n"
                f"  Fix: Reduce input length or use a model with a larger context window."
            )
        elif status_code >= 500:
            raise ProviderUnavailableError(
                f"Provider error ({status_code}).\n"
                f"  Response: {text[:200]}"
            )
        else:
            raise ProviderError(
                f"HTTP {status_code}.\n"
                f"  Response: {text[:200]}"
            )

    def _parse_response(self, data: dict[str, Any], model: str) -> LLMResponse:
        """Parse Anthropic Messages API response into LLMResponse."""
        content_blocks = data.get("content", [])

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in content_blocks:
            block_type = block.get("type", "")
            if block_type == "text":
                text_parts.append(block.get("text", ""))
            elif block_type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.get("id", ""),
                        name=block.get("name", ""),
                        arguments=block.get("input", {}),
                    )
                )

        # Map Anthropic stop reasons to Orchestra's
        stop_reason = data.get("stop_reason", "end_turn")
        if stop_reason == "tool_use":
            finish_reason = "tool_calls"
        elif stop_reason == "max_tokens":
            finish_reason = "length"
        else:
            finish_reason = "stop"

        # Parse usage
        usage = None
        raw_usage = data.get("usage")
        if raw_usage:
            input_tok = raw_usage.get("input_tokens", 0)
            output_tok = raw_usage.get("output_tokens", 0)
            cost_info = _MODEL_COSTS.get(model, (0.0, 0.0))
            estimated_cost = (input_tok / 1000 * cost_info[0]) + (
                output_tok / 1000 * cost_info[1]
            )
            usage = TokenUsage(
                input_tokens=input_tok,
                output_tokens=output_tok,
                total_tokens=input_tok + output_tok,
                estimated_cost_usd=estimated_cost,
            )

        return LLMResponse(
            content="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            model=data.get("model", model),
            raw_response=data,
        )

    async def aclose(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()
