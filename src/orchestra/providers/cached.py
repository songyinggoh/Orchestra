"""Cache-through LLM provider wrapper."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel

from orchestra.cache.backends import CacheBackend
from orchestra.core.types import LLMResponse, Message


class CachedProvider:
    """Cache-through wrapper for any LLMProvider.

    Only caches calls with temperature <= max_cacheable_temperature (default 0.0).
    """

    def __init__(
        self,
        provider: Any,  # LLMProvider protocol
        cache: CacheBackend,
        *,
        default_ttl: int = 3600,  # 1 hour
        max_cacheable_temperature: float = 0.0,
        cache_tool_calls: bool = True,
    ) -> None:
        self._provider = provider
        self._cache = cache
        self._default_ttl = default_ttl
        self._max_temp = max_cacheable_temperature
        self._cache_tool_calls = cache_tool_calls

    @property
    def provider_name(self) -> str:
        """Name of the underlying provider."""
        return self._provider.provider_name

    @property
    def default_model(self) -> str:
        """Default model for the underlying provider."""
        return self._provider.default_model

    def _cache_key(
        self,
        messages: list[Message],
        model: str | None,
        temperature: float,
        max_tokens: int | None,
        tools: list[dict[str, Any]] | None,
        output_type: type[BaseModel] | None,
    ) -> str:
        """Generate a SHA-256 cache key from all parameters that affect output."""
        key_data = {
            "messages": [m.model_dump(exclude={"metadata"}) for m in messages],
            "model": model or self.default_model,
            "temperature": round(temperature, 4),
            "max_tokens": max_tokens,
            "tools": tools,
            "output_type": output_type.__name__ if output_type else None,
        }
        # Sort keys and ensure deterministic JSON serialization
        canonical = json.dumps(key_data, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    async def complete(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        output_type: type[BaseModel] | None = None,
    ) -> LLMResponse:
        """Execute completion, checking the cache first."""
        # Skip cache for non-deterministic calls (temperature > max_temp)
        if temperature > self._max_temp:
            return await self._provider.complete(
                messages,
                model=model,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
                output_type=output_type,
            )

        key = self._cache_key(messages, model, temperature, max_tokens, tools, output_type)

        # Cache lookup
        cached = await self._cache.get(key)
        if cached is not None:
            # Re-inject the raw response placeholder if needed
            return cached

        # Cache miss -- call provider
        result = await self._provider.complete(
            messages,
            model=model,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            output_type=output_type,
        )

        # Optionally skip caching tool-call responses
        if result.tool_calls and not self._cache_tool_calls:
            return result

        # Store in cache (exclude raw_response from cache as it might not be serializable)
        # LLMResponse is already serialized/deserialized by the backend
        await self._cache.set(key, result, self._default_ttl)
        return result

    async def stream(self, *args, **kwargs):
        """Delegate streaming to the underlying provider (streaming is not cached)."""
        return await self._provider.stream(*args, **kwargs)

    def count_tokens(self, *args, **kwargs):
        """Delegate token counting to the underlying provider."""
        return self._provider.count_tokens(*args, **kwargs)

    def get_model_cost(self, *args, **kwargs):
        """Delegate cost calculation to the underlying provider."""
        return self._provider.get_model_cost(*args, **kwargs)
