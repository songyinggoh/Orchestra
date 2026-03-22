"""CallableProvider: wrap any function as an LLM provider.

Accepts any callable that takes a prompt string and returns a string.
No API format knowledge required — bring your own LLM, any platform.

Supports three signatures:
    (str) -> str                     # Simplest: prompt in, text out
    (list[Message]) -> str           # Full message history
    (list[Message], **kwargs) -> str # Messages + model/tools/temp

Usage:
    from orchestra.providers import CallableProvider

    # Any function works — Cohere, Mistral, HuggingFace, a local model, etc.
    def my_llm(prompt: str) -> str:
        return some_api.call(prompt)

    provider = CallableProvider(my_llm)

    # Async functions work too
    async def my_async_llm(prompt: str) -> str:
        return await some_api.call(prompt)

    provider = CallableProvider(my_async_llm)

    # Use with the framework
    compiled.run(input="hello", provider=provider)
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator, Callable
from typing import Any

from orchestra.core.types import (
    LLMResponse,
    Message,
    ModelCost,
    StreamChunk,
)


def _messages_to_prompt(messages: list[Message]) -> str:
    """Flatten a list of Messages into a single prompt string."""
    parts = []
    for msg in messages:
        parts.append(f"{msg.role.value}: {msg.content}")
    return "\n".join(parts)


class CallableProvider:
    """Wraps any callable as a full LLM provider.

    The callable can be sync or async, and can accept:
        (str) -> str                     — receives flattened prompt
        (list[Message]) -> str           — receives raw message objects
        (list[Message], **kwargs) -> str — receives messages + extra params

    This lets you plug in ANY LLM backend without writing an adapter.
    """

    def __init__(
        self,
        fn: Callable[..., Any],
        *,
        name: str = "callable",
        model_name: str = "custom",
    ) -> None:
        self._fn = fn
        self._name = name
        self._model_name = model_name
        self._is_async = asyncio.iscoroutinefunction(fn)

        # Detect function signature to know what to pass
        sig = inspect.signature(fn)
        params = list(sig.parameters.values())
        self._accepts_messages = False
        self._accepts_kwargs = False

        if params:
            first = params[0]
            hint = first.annotation
            # Check if first param is typed as list[Message] or list
            if hint is not inspect.Parameter.empty:
                origin = getattr(hint, "__origin__", None)
                if origin is list:
                    args = getattr(hint, "__args__", ())
                    if (args and args[0] is Message) or not args:
                        self._accepts_messages = True

            # Check for **kwargs or extra parameters
            if len(params) > 1 or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params):
                self._accepts_kwargs = True

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def default_model(self) -> str:
        return self._model_name

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
        """Call the wrapped function and return an LLMResponse."""
        result = await self._call_fn(messages, model=model, tools=tools, temperature=temperature)

        # If the function returned an LLMResponse directly, use it
        if isinstance(result, LLMResponse):
            return result

        # Otherwise wrap the string result
        content = str(result) if result is not None else ""
        return LLMResponse(content=content, model=model or self._model_name)

    async def stream(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream by calling complete() and yielding the result as chunks."""
        response = await self.complete(
            messages,
            model=model,
            tools=tools,
            temperature=temperature,
        )
        if response.content:
            # Yield word by word to simulate streaming
            words = response.content.split()
            for word in words:
                yield StreamChunk(content=word + " ", model=model or self._model_name)
        yield StreamChunk(content="", finish_reason="stop", model=model or self._model_name)

    def count_tokens(self, messages: list[Message], model: str | None = None) -> int:
        """Approximate token count (4 chars per token)."""
        return sum(len(m.content) // 4 + 4 for m in messages)

    def get_model_cost(self, model: str | None = None) -> ModelCost:
        """Return zero cost — the user manages their own billing."""
        return ModelCost(input_cost_per_1k=0.0, output_cost_per_1k=0.0)

    async def _call_fn(self, messages: list[Message], **kwargs: Any) -> Any:
        """Route to the correct calling convention based on function signature."""
        if self._accepts_messages and self._accepts_kwargs:
            result = self._fn(messages, **kwargs)
        elif self._accepts_messages:
            result = self._fn(messages)
        else:
            # Flatten to string
            prompt = _messages_to_prompt(messages)
            result = self._fn(prompt)

        # Await if async
        if inspect.isawaitable(result):
            result = await result

        return result
