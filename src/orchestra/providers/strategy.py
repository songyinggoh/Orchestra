"""Strategy-based LLM provider wrappers (DD-10).

Provides transparent switching between NativeSchema (JSON/Tools)
and PromptedSchema (few-shot + validation) for models that lack
reliable native support.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Protocol, cast, runtime_checkable

import structlog
from pydantic import BaseModel

from orchestra.core.protocols import LLMProvider
from orchestra.core.types import (
    LLMResponse,
    Message,
    MessageRole,
    ModelCost,
    StreamChunk,
    ToolCall,
)

logger = structlog.get_logger(__name__)


@runtime_checkable
class ExecutionStrategy(Protocol):
    """Protocol for transforming generic LLM calls into provider-specific strategies."""

    async def execute(
        self,
        provider: LLMProvider,
        messages: list[Message],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        output_type: type[BaseModel] | None = None,
    ) -> LLMResponse: ...


class NativeStrategy:
    """Uses the provider's native tool-calling and structured output features."""

    async def execute(
        self,
        provider: LLMProvider,
        messages: list[Message],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        output_type: type[BaseModel] | None = None,
    ) -> LLMResponse:
        return await provider.complete(
            messages=messages,
            model=model,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            output_type=output_type,
        )


class PromptedStrategy:
    """Uses manual prompting and few-shot examples for structured output and tools."""

    async def execute(
        self,
        provider: LLMProvider,
        messages: list[Message],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        output_type: type[BaseModel] | None = None,
    ) -> LLMResponse:
        # Validate output_type is a Pydantic BaseModel if provided
        if output_type is not None and not (
            isinstance(output_type, type) and issubclass(output_type, BaseModel)
        ):
            raise ValueError(
                f"output_type must be a Pydantic BaseModel class, got {output_type!r}. "
                f"Make sure you pass the class itself, not an instance."
            )

        modified_messages = list(messages)

        # 1. Inject Tool Prompt if tools are provided
        if tools:
            tool_prompt = self._build_tool_prompt(tools)
            modified_messages.append(Message(role=MessageRole.SYSTEM, content=tool_prompt))

        # 2. Inject Structured Output Prompt if output_type is provided
        if output_type:
            schema_prompt = self._build_schema_prompt(output_type)
            modified_messages.append(Message(role=MessageRole.SYSTEM, content=schema_prompt))

        # 3. Call completion without native tools/schema
        response = await provider.complete(
            messages=modified_messages,
            model=model,
            tools=None,  # Explicitly disable native tools
            temperature=temperature,
            max_tokens=max_tokens,
            output_type=None,  # Explicitly disable native output type
        )

        # 4. Parse response for tools or structured output
        return self._parse_prompted_response(response, tools, output_type)

    def _build_tool_prompt(self, tools: list[dict[str, Any]]) -> str:
        tool_desc = json.dumps(tools, indent=2)
        return (
            "Available tools:\n"
            f"{tool_desc}\n\n"
            "To use a tool, respond with a JSON object in this format:\n"
            '{"tool_calls": [{"name": "tool_name", "arguments": {"arg1": "val1"}}]}'
        )

    def _build_schema_prompt(self, output_type: type[BaseModel]) -> str:
        schema = json.dumps(output_type.model_json_schema(), indent=2)
        return (
            "You must return your response as a JSON object matching this schema:\n"
            f"{schema}\n\n"
            "Return ONLY the JSON object."
        )

    def _parse_prompted_response(
        self,
        response: LLMResponse,
        tools: list[dict[str, Any]] | None,
        output_type: type[BaseModel] | None,
    ) -> LLMResponse:
        if not response.content:
            return response

        try:
            # Look for JSON in the content
            content = response.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "{" in content:
                start = content.find("{")
                end = content.rfind("}") + 1
                content = content[start:end]

            data = json.loads(content)

            # Extract tool calls
            tool_calls = []
            if tools and "tool_calls" in data:
                for tc in data["tool_calls"]:
                    tool_calls.append(ToolCall(name=tc["name"], arguments=tc["arguments"]))

            return LLMResponse(
                content=response.content,
                tool_calls=tool_calls,
                usage=response.usage,
                model=response.model,
                raw_response=response.raw_response,
            )
        except Exception as e:
            logger.warning("prompted_parse_failed", error=str(e))
            return response


class StrategySwitchingProvider:
    """A provider that automatically switches strategies based on model capabilities."""

    def __init__(
        self,
        provider: LLMProvider,
        native_models: set[str] | None = None,
    ) -> None:
        self._provider = provider
        self._native_models = native_models or {
            "gpt-4o",
            "gpt-4o-mini",
            "claude-3-5-sonnet-20240620",
            "gemini-1.5-pro",
        }
        self._native = NativeStrategy()
        self._prompted = PromptedStrategy()

    @property
    def provider_name(self) -> str:
        return f"strategy({self._provider.provider_name})"

    @property
    def default_model(self) -> str:
        return self._provider.default_model

    async def complete(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        output_type: type[BaseModel] | None = None,
    ) -> LLMResponse:
        target_model = model or self.default_model
        strategy = self._native if target_model in self._native_models else self._prompted

        logger.debug("strategy_selected", model=target_model, strategy=strategy.__class__.__name__)

        return await strategy.execute(
            provider=self._provider,
            messages=messages,
            model=target_model,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            output_type=output_type,
        )

    async def stream(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamChunk]:
        # All concrete providers implement stream() as async generators.
        # The Protocol annotates stream() as 'async def -> AsyncIterator' but
        # generators are directly iterable (no await needed). Cast to satisfy mypy.
        inner = cast(
            AsyncIterator[StreamChunk],
            self._provider.stream(
                messages=messages,
                model=model,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
            ),
        )
        async for chunk in inner:
            yield chunk

    def count_tokens(self, messages: list[Message], model: str | None = None) -> int:
        return self._provider.count_tokens(messages, model)

    def get_model_cost(self, model: str | None = None) -> ModelCost:
        return self._provider.get_model_cost(model)
