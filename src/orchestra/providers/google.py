"""Google Gemini provider for generative AI models.

Uses httpx directly (zero extra dependencies beyond core).
Handles Gemini's unique message format (contents/parts vs messages/content)
and function calling schema (functionDeclarations vs tools.function).

Usage:
    from orchestra.providers import GoogleProvider

    provider = GoogleProvider(api_key="AIza...")
    # Or set GOOGLE_API_KEY env var
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
    "gemini-2.0-flash": (0.0001, 0.0004),
    "gemini-2.0-flash-lite": (0.000075, 0.0003),
    "gemini-2.5-pro-preview-06-05": (0.00125, 0.01),
    "gemini-2.5-flash-preview-05-20": (0.00015, 0.0035),
}

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com"


def _messages_to_gemini_format(
    messages: list[Message],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Convert Orchestra Messages to Gemini API format.

    Returns (system_instruction, contents) since Gemini separates system
    instructions from the conversation contents array.

    Gemini format:
        contents: [{"role": "user"|"model", "parts": [{"text": "..."}]}]
    """
    system_instruction: str | None = None
    contents: list[dict[str, Any]] = []

    for msg in messages:
        if msg.role == MessageRole.SYSTEM:
            system_instruction = msg.content
            continue

        if msg.role == MessageRole.TOOL:
            # Tool results go as "user" role with functionResponse parts
            contents.append({
                "role": "user",
                "parts": [
                    {
                        "functionResponse": {
                            "name": msg.name or "tool",
                            "response": {"result": msg.content},
                        }
                    }
                ],
            })
            continue

        # Gemini uses "model" instead of "assistant"
        role = "model" if msg.role == MessageRole.ASSISTANT else "user"
        parts: list[dict[str, Any]] = []

        if msg.tool_calls:
            # Assistant message with function calls
            if msg.content:
                parts.append({"text": msg.content})
            for tc in msg.tool_calls:
                parts.append({
                    "functionCall": {
                        "name": tc.name,
                        "args": tc.arguments,
                    }
                })
        else:
            parts.append({"text": msg.content})

        contents.append({"role": role, "parts": parts})

    return system_instruction, contents


def _tools_to_gemini_format(
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert OpenAI-style tool schemas to Gemini functionDeclarations format."""
    function_declarations = []
    for t in tools:
        func = t.get("function", t)
        declaration: dict[str, Any] = {
            "name": func.get("name", ""),
            "description": func.get("description", ""),
        }
        params = func.get("parameters", {})
        if params:
            declaration["parameters"] = params
        function_declarations.append(declaration)
    return [{"functionDeclarations": function_declarations}]


def _gemini_tool_to_orchestra(call: dict[str, Any]) -> ToolCall:
    """Convert a Gemini functionCall part to Orchestra ToolCall."""
    return ToolCall(
        name=call.get("name", ""),
        arguments=call.get("args", {}),
    )


class GoogleProvider:
    """Google Gemini provider using the Generative Language API.

    Handles the Gemini-specific API format (contents/parts structure,
    functionDeclarations for tools, usageMetadata for token counts).

    Usage:
        provider = GoogleProvider(api_key="AIza...")
        # Or set GOOGLE_API_KEY env var
        provider = GoogleProvider()
    """

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = "gemini-2.0-flash",
        max_retries: int = 3,
        timeout: float = 120.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("GOOGLE_API_KEY", "")
        self._default_model = default_model
        self._max_retries = max_retries
        self._client = httpx.AsyncClient(
            base_url=_GEMINI_BASE_URL,
            timeout=timeout,
            headers={
                "content-type": "application/json",
                "x-goog-api-key": self._api_key,
            },
        )

    @property
    def provider_name(self) -> str:
        return "google"

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
        """Send a generateContent request to the Gemini API."""
        use_model = model or self._default_model
        system_instruction, contents = _messages_to_gemini_format(messages)

        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
            },
        }
        if max_tokens:
            body["generationConfig"]["maxOutputTokens"] = max_tokens
        if system_instruction:
            body["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }
        if tools:
            body["tools"] = _tools_to_gemini_format(tools)

        # JSON mode via response_mime_type
        if output_type is not None:
            body["generationConfig"]["responseMimeType"] = "application/json"
            try:
                schema = output_type.model_json_schema()
                body["generationConfig"]["responseSchema"] = schema
            except (AttributeError, Exception):
                pass

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
        """Stream generateContent responses from Gemini via SSE."""
        use_model = model or self._default_model
        system_instruction, contents = _messages_to_gemini_format(messages)

        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
            },
        }
        if max_tokens:
            body["generationConfig"]["maxOutputTokens"] = max_tokens
        if system_instruction:
            body["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }
        if tools:
            body["tools"] = _tools_to_gemini_format(tools)

        endpoint = (
            f"/v1beta/models/{use_model}:streamGenerateContent"
            f"?alt=sse&key={self._api_key}"
        )

        async with self._client.stream("POST", endpoint, json=body) as response:
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

                candidates = event.get("candidates", [])
                if not candidates:
                    continue

                candidate = candidates[0]
                finish_reason = candidate.get("finishReason")

                parts = candidate.get("content", {}).get("parts", [])
                for part in parts:
                    if "text" in part:
                        yield StreamChunk(
                            content=part["text"],
                            model=use_model,
                        )
                    elif "functionCall" in part:
                        # Tool call in stream — yield empty chunk with finish signal
                        yield StreamChunk(
                            content="",
                            finish_reason="tool_calls",
                            model=use_model,
                        )

                if finish_reason and finish_reason not in ("", "FINISH_REASON_UNSPECIFIED"):
                    reason = _map_finish_reason(finish_reason)
                    yield StreamChunk(
                        content="",
                        finish_reason=reason,
                        model=use_model,
                    )

    def count_tokens(self, messages: list[Message], model: str | None = None) -> int:
        """Approximate token count (4 chars per token heuristic)."""
        total = 0
        for msg in messages:
            total += len(msg.content) // 4 + 4
        return total

    def get_model_cost(self, model: str | None = None) -> ModelCost:
        """Get cost information for a Gemini model."""
        m = model or self._default_model
        costs = _MODEL_COSTS.get(m, (0.0, 0.0))
        return ModelCost(input_cost_per_1k=costs[0], output_cost_per_1k=costs[1])

    async def _request_with_retry(
        self, model: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """Make HTTP request with retry logic."""
        endpoint = f"/v1beta/models/{model}:generateContent?key={self._api_key}"
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.post(endpoint, json=body)

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
                    f"  Endpoint: {_GEMINI_BASE_URL}\n"
                    f"  Fix: Check network connectivity."
                )
                if attempt < self._max_retries:
                    import asyncio

                    await asyncio.sleep(2**attempt)

        raise last_error or ProviderError("Request failed after retries")

    def _handle_error_status(self, status_code: int, text: str) -> None:
        """Convert HTTP error status to Orchestra exception."""
        if status_code == 400:
            lower = text.lower()
            if "context" in lower or "token" in lower or "length" in lower:
                raise ContextWindowError(
                    f"Context window exceeded.\n"
                    f"  Response: {text[:200]}\n"
                    f"  Fix: Reduce input length or use a model with a larger context window."
                )
            raise ProviderError(
                f"Bad request (400).\n"
                f"  Response: {text[:200]}"
            )
        elif status_code == 403:
            raise AuthenticationError(
                "Permission denied (403).\n"
                "  Fix: Check your API key or set GOOGLE_API_KEY env var.\n"
                "  Ensure the Generative Language API is enabled in your Google Cloud project."
            )
        elif status_code == 401:
            raise AuthenticationError(
                "Authentication failed (401).\n"
                "  Fix: Check your API key or set GOOGLE_API_KEY env var."
            )
        elif status_code == 429:
            raise RateLimitError(
                f"Rate limited (429).\n"
                f"  Response: {text[:200]}"
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
        """Parse Gemini generateContent response into LLMResponse."""
        candidates = data.get("candidates", [])
        if not candidates:
            return LLMResponse(content=None, model=model)

        candidate = candidates[0]
        content_block = candidate.get("content", {})
        parts = content_block.get("parts", [])

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for part in parts:
            if "text" in part:
                text_parts.append(part["text"])
            elif "functionCall" in part:
                tool_calls.append(_gemini_tool_to_orchestra(part["functionCall"]))

        # Map Gemini finish reasons to Orchestra's
        raw_finish = candidate.get("finishReason", "STOP")
        finish_reason = _map_finish_reason(raw_finish)

        # Parse usage from usageMetadata
        usage = None
        raw_usage = data.get("usageMetadata")
        if raw_usage:
            input_tok = raw_usage.get("promptTokenCount", 0)
            output_tok = raw_usage.get("candidatesTokenCount", 0)
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
            model=model,
            raw_response=data,
        )

    async def aclose(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()


def _map_finish_reason(
    gemini_reason: str,
) -> "LLMResponse.__fields__['finish_reason'].annotation":  # type: ignore[name-defined]
    """Map Gemini finishReason to Orchestra finish_reason literal."""
    mapping = {
        "STOP": "stop",
        "MAX_TOKENS": "length",
        "SAFETY": "stop",
        "RECITATION": "stop",
        "OTHER": "stop",
        "FUNCTION_CALL": "tool_calls",
    }
    return mapping.get(gemini_reason.upper(), "stop")  # type: ignore[return-value]
