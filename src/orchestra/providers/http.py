"""Generic OpenAI-compatible HTTP provider.

Zero extra dependencies beyond httpx (already in core).
Works with any endpoint that speaks the OpenAI chat completions format:
OpenAI, Ollama, vLLM, LiteLLM, Azure OpenAI, Groq, Together, Mistral, etc.

Environment variables (checked in priority order):
    ORCHESTRA_BASE_URL   — endpoint base URL  (e.g. https://api.groq.com/openai/v1)
    ORCHESTRA_API_KEY    — API key for the endpoint
    ORCHESTRA_MODEL      — default model name
    OPENAI_API_KEY       — fallback key when ORCHESTRA_API_KEY is not set

Usage:
    from orchestra.providers import HttpProvider

    # Zero-config: reads ORCHESTRA_* env vars
    provider = HttpProvider()

    # Explicit — useful in tests or multi-provider setups
    provider = HttpProvider(base_url="https://api.groq.com/openai/v1", api_key="gsk_...")
    provider = HttpProvider(base_url="http://localhost:11434/v1", default_model="llama3")
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
    ModelCost,
    StreamChunk,
    TokenUsage,
    ToolCall,
)


def _messages_to_openai_format(messages: list[Message]) -> list[dict[str, Any]]:
    """Convert Orchestra Messages to OpenAI API format."""
    result = []
    for msg in messages:
        entry: dict[str, Any] = {
            "role": msg.role.value,
            "content": msg.content,
        }
        if msg.name:
            entry["name"] = msg.name
        if msg.tool_call_id:
            entry["tool_call_id"] = msg.tool_call_id
        if msg.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in msg.tool_calls
            ]
        result.append(entry)
    return result


# Approximate costs per 1K tokens (input/output)
_MODEL_COSTS: dict[str, tuple[float, float]] = {
    "gpt-4o": (0.0025, 0.01),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4-turbo": (0.01, 0.03),
    "o1": (0.015, 0.06),
    "o3-mini": (0.0011, 0.0044),
}


class HttpProvider:
    """Generic OpenAI-compatible HTTP provider. Zero extra dependencies.

    Works with any endpoint that speaks the OpenAI chat completions format.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        default_model: str | None = None,
        max_retries: int = 3,
        timeout: float = 120.0,
    ) -> None:
        self._base_url = (
            base_url
            or os.environ.get("ORCHESTRA_BASE_URL", "https://api.openai.com/v1")
        ).rstrip("/")
        self._api_key = (
            api_key
            or os.environ.get("ORCHESTRA_API_KEY")
            or os.environ.get("OPENAI_API_KEY", "")
        )
        self._default_model = (
            default_model
            or os.environ.get("ORCHESTRA_MODEL", "gpt-4o-mini")
        )
        self._max_retries = max_retries
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            headers=self._build_headers(),
        )

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    @property
    def provider_name(self) -> str:
        return "http_openai_compat"

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
        """Send a chat completion request."""
        use_model = model or self._default_model

        body: dict[str, Any] = {
            "model": use_model,
            "messages": _messages_to_openai_format(messages),
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
        if max_tokens:
            body["max_tokens"] = max_tokens

        # Structured output via response_format
        if output_type is not None:
            try:
                schema = output_type.model_json_schema()
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": output_type.__name__,
                        "schema": schema,
                        "strict": True,
                    },
                }
            except (AttributeError, Exception):
                pass

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
        """Stream chat completion responses."""
        use_model = model or self._default_model

        body: dict[str, Any] = {
            "model": use_model,
            "messages": _messages_to_openai_format(messages),
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            body["tools"] = tools
        if max_tokens:
            body["max_tokens"] = max_tokens

        async with self._client.stream(
            "POST", "/chat/completions", json=body
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
                if data == "[DONE]":
                    break
                try:
                    chunk_data = json.loads(data)
                    choices = chunk_data.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        content = delta.get("content", "")
                        finish = choices[0].get("finish_reason")
                        yield StreamChunk(
                            content=content or "",
                            finish_reason=finish,
                            model=use_model,
                        )
                except json.JSONDecodeError:
                    continue

    def count_tokens(self, messages: list[Message], model: str | None = None) -> int:
        """Approximate token count (4 chars per token heuristic)."""
        total = 0
        for msg in messages:
            total += len(msg.content) // 4 + 4  # message overhead
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
                response = await self._client.post("/chat/completions", json=body)

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
                    f"  Endpoint: {self._base_url}\n"
                    f"  Fix: Check that the endpoint is running and reachable."
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
                "  Fix: Check your API key or set OPENAI_API_KEY env var."
            )
        elif status_code == 429:
            raise RateLimitError(
                f"Rate limited (429).\n"
                f"  Response: {text[:200]}"
            )
        elif status_code == 400 and "context_length" in text.lower():
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
        """Parse OpenAI-format response into LLMResponse."""
        choices = data.get("choices", [])
        if not choices:
            return LLMResponse(content=None, model=model)

        choice = choices[0]
        message = choice.get("message", {})

        # Parse tool calls
        tool_calls = []
        raw_tool_calls = message.get("tool_calls", [])
        for tc in raw_tool_calls:
            func = tc.get("function", {})
            try:
                args = json.loads(func.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(
                ToolCall(
                    id=tc.get("id", ""),
                    name=func.get("name", ""),
                    arguments=args,
                )
            )

        # Parse finish reason
        raw_finish = choice.get("finish_reason", "stop")
        finish_reason = "stop"
        if raw_finish == "tool_calls":
            finish_reason = "tool_calls"
        elif raw_finish == "length":
            finish_reason = "length"

        # Parse usage
        usage = None
        raw_usage = data.get("usage")
        if raw_usage:
            input_tok = raw_usage.get("prompt_tokens", 0)
            output_tok = raw_usage.get("completion_tokens", 0)
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
            content=message.get("content"),
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            model=data.get("model", model),
            raw_response=data,
        )

    async def aclose(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()
