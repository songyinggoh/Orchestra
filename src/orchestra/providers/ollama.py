"""Ollama provider for local LLM inference.

Ollama exposes an OpenAI-compatible API at http://localhost:11434/v1/,
so this adapter reuses the OpenAI message format while adding Ollama-specific
behaviors: connection error messaging, model pull suggestions, and free cost
tracking (local models have no API cost).

Usage:
    from orchestra.providers import OllamaProvider

    provider = OllamaProvider()  # Uses localhost:11434
    provider = OllamaProvider(base_url="http://gpu-server:11434")
    provider = OllamaProvider(default_model="mistral")
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx

from orchestra.core.errors import (
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
    """Convert Orchestra Messages to OpenAI-compatible format (used by Ollama)."""
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


class OllamaProvider:
    """Local LLM provider using Ollama.

    Ollama runs locally and exposes an OpenAI-compatible API.
    No API key required. Supports any model installed via `ollama pull`.

    Models with tool support: llama3.1+, mistral, qwen2.5, etc.
    Models without tool support: gracefully ignore the tools parameter.

    Usage:
        provider = OllamaProvider()  # Uses localhost:11434
        provider = OllamaProvider(base_url="http://gpu-server:11434")
    """

    def __init__(
        self,
        base_url: str | None = None,
        default_model: str = "llama3.1",
        timeout: float = 120.0,
    ) -> None:
        url = base_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        self._base_url = url.rstrip("/")
        self._default_model = default_model
        # OpenAI-compatible client pointed at /v1
        self._client = httpx.AsyncClient(
            base_url=f"{self._base_url}/v1",
            timeout=timeout,
            headers={"Content-Type": "application/json"},
        )
        # Native Ollama API client (for /api/tags, health check, etc.)
        self._native_client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
        )

    @property
    def provider_name(self) -> str:
        return "ollama"

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
        """Send a chat completion request to Ollama."""
        use_model = model or self._default_model

        body: dict[str, Any] = {
            "model": use_model,
            "messages": _messages_to_openai_format(messages),
            "temperature": temperature,
            "stream": False,
        }
        if tools:
            body["tools"] = tools
        if max_tokens:
            body["max_tokens"] = max_tokens

        response_data = await self._request_with_retry(use_model, body)
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
        """Stream chat completion responses from Ollama."""
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

        try:
            async with self._client.stream("POST", "/chat/completions", json=body) as response:
                if response.status_code != 200:
                    text = ""
                    async for chunk in response.aiter_text():
                        text += chunk
                    self._handle_error_status(response.status_code, text, use_model)

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
        except httpx.ConnectError as e:
            raise ProviderUnavailableError(
                f"Cannot connect to Ollama at {self._base_url}.\n"
                f"  Error: {e}\n"
                f"  Fix: Start Ollama with `ollama serve` or check that it is running.\n"
                f"  Download: https://ollama.com"
            ) from e

    def count_tokens(self, messages: list[Message], model: str | None = None) -> int:
        """Approximate token count (4 chars per token heuristic).

        Ollama reports actual token counts in response.usage, but this
        provides a synchronous estimate without making an API call.
        """
        total = 0
        for msg in messages:
            total += len(msg.content) // 4 + 4
        return total

    def get_model_cost(self, model: str | None = None) -> ModelCost:
        """Get cost for a local Ollama model.

        Local models are free — always returns zero cost.
        """
        return ModelCost(input_cost_per_1k=0.0, output_cost_per_1k=0.0)

    async def health_check(self) -> bool:
        """Check if Ollama is running and reachable.

        Returns True if Ollama is running, False otherwise.
        """
        try:
            response = await self._native_client.get("/")
            return response.status_code == 200 and "ollama" in response.text.lower()
        except httpx.ConnectError:
            return False

    async def list_models(self) -> list[str]:
        """List models available in this Ollama instance.

        Uses the native Ollama /api/tags endpoint.
        """
        try:
            response = await self._native_client.get("/api/tags")
            if response.status_code == 200:
                data: dict[str, Any] = response.json()
                models = data.get("models", [])
                return [m.get("name", "") for m in models if m.get("name")]
            return []
        except httpx.ConnectError:
            return []

    async def _request_with_retry(self, model: str, body: dict[str, Any]) -> dict[str, Any]:
        """Make HTTP request with retry logic, wrapping connection errors."""
        last_error: Exception | None = None

        for attempt in range(3 + 1):
            try:
                response = await self._client.post("/chat/completions", json=body)

                if response.status_code == 200:
                    result: dict[str, Any] = response.json()
                    return result

                self._handle_error_status(response.status_code, response.text, model)

            except ProviderError:
                raise
            except (RateLimitError, ProviderUnavailableError) as e:
                last_error = e
                if attempt < 3:
                    import asyncio

                    await asyncio.sleep(2**attempt)
            except httpx.ConnectError as e:
                raise ProviderUnavailableError(
                    f"Cannot connect to Ollama at {self._base_url}.\n"
                    f"  Error: {e}\n"
                    f"  Fix: Start Ollama with `ollama serve` or check that it is running.\n"
                    f"  Download: https://ollama.com"
                ) from e
            except httpx.HTTPError as e:
                last_error = ProviderUnavailableError(
                    f"HTTP error connecting to Ollama: {e}\n"
                    f"  Endpoint: {self._base_url}\n"
                    f"  Fix: Check that Ollama is running and reachable."
                )
                if attempt < 3:
                    import asyncio

                    await asyncio.sleep(2**attempt)

        raise last_error or ProviderError("Request failed after retries")

    def _handle_error_status(self, status_code: int, text: str, model: str) -> None:
        """Convert HTTP error status to Orchestra exception."""
        if status_code == 404:
            lower = text.lower()
            if "model" in lower or "not found" in lower:
                raise ProviderError(
                    f"Model '{model}' not found in Ollama.\n"
                    f"  Response: {text[:200]}\n"
                    f"  Fix: Run `ollama pull {model}` to download the model."
                )
            raise ProviderError(f"Not found (404).\n  Response: {text[:200]}")
        elif status_code == 400:
            raise ProviderError(
                f"Bad request (400).\n"
                f"  Response: {text[:200]}\n"
                f"  Note: Some Ollama models do not support tool calling. "
                f"Try a model like llama3.1 or mistral."
            )
        elif status_code == 500:
            raise ProviderUnavailableError(
                f"Ollama internal error (500).\n  Response: {text[:200]}"
            )
        elif status_code >= 500:
            raise ProviderUnavailableError(
                f"Ollama server error ({status_code}).\n  Response: {text[:200]}"
            )
        else:
            raise ProviderError(f"HTTP {status_code}.\n  Response: {text[:200]}")

    def _parse_response(self, data: dict[str, Any], model: str) -> LLMResponse:
        """Parse OpenAI-compatible Ollama response into LLMResponse."""
        choices = data.get("choices", [])
        if not choices:
            return LLMResponse(content=None, model=model)

        choice = choices[0]
        message = choice.get("message", {})

        # Parse tool calls (present only if model supports them)
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

        # Parse usage — Ollama returns prompt_tokens + completion_tokens
        # (same as OpenAI format). Local models are free so cost = 0.
        usage = None
        raw_usage = data.get("usage")
        if raw_usage:
            input_tok = raw_usage.get("prompt_tokens", 0)
            output_tok = raw_usage.get("completion_tokens", 0)
            usage = TokenUsage(
                input_tokens=input_tok,
                output_tokens=output_tok,
                total_tokens=input_tok + output_tok,
                estimated_cost_usd=0.0,  # local = free
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
        """Close the HTTP clients."""
        await self._client.aclose()
        await self._native_client.aclose()
