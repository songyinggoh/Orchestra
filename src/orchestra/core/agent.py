"""Agent definitions: BaseAgent class and @agent decorator.

Two styles for defining agents:
1. Class-based (BaseAgent subclass) - production
2. Decorator-based (@agent) - rapid prototyping

Both produce objects satisfying the Agent protocol.
"""

from __future__ import annotations

import functools
import inspect
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from orchestra.security.acl import ToolACL

import structlog
from pydantic import BaseModel, Field

from orchestra.core.context import ExecutionContext
from orchestra.core.errors import MaxIterationsError
from orchestra.core.types import (
    AgentResult,
    LLMResponse,
    Message,
    MessageRole,
    TokenUsage,
    ToolCall,
    ToolCallRecord,
    ToolResult,
)

logger = structlog.get_logger(__name__)


class BaseAgent(BaseModel):
    """Base class for agent implementations.

    Class attributes define agent configuration.
    Override run() for custom behavior, or use the default
    LLM-call-then-tool-loop implementation.
    """

    name: str = "agent"
    model: str = "gpt-4o-mini"
    system_prompt: str = "You are a helpful assistant."
    tools: list[Any] = Field(default_factory=list)
    acl: Any = None  # Lazy-loaded ToolACL
    max_iterations: int = 10
    temperature: float = 0.7
    output_type: Any = None
    provider: str | None = None

    model_config = {"arbitrary_types_allowed": True}

    async def run(
        self,
        input: str | list[Message],
        context: ExecutionContext,
    ) -> AgentResult:
        """Execute the agent's reasoning loop.

        1. Build system prompt + messages
        2. Call LLM via context.provider
        3. If tool calls, execute tools and loop
        4. Return final response as AgentResult
        """
        llm = context.provider
        if not llm:
            raise RuntimeError(
                f"Agent '{self.name}' has no LLM provider.\n"
                f"  Fix: Pass a provider when running the workflow, e.g.:\n"
                f"  compiled.run(state, provider=HttpProvider())"
            )

        # Build messages
        prompt = self._resolve_system_prompt(context)
        full_messages = [Message(role=MessageRole.SYSTEM, content=prompt)]

        if isinstance(input, str):
            if input:
                full_messages.append(Message(role=MessageRole.USER, content=input))
        elif isinstance(input, list):
            full_messages.extend(input)

        # Build tool schemas
        tool_schemas = [self._tool_to_schema(t) for t in self.tools] if self.tools else None
        all_tool_records: list[ToolCallRecord] = []
        total_usage = TokenUsage()

        for _iteration in range(self.max_iterations):
            _llm_start = time.monotonic()
            response: LLMResponse = await llm.complete(
                messages=full_messages,
                model=self.model,
                tools=tool_schemas,
                temperature=self.temperature,
                output_type=self.output_type,
            )
            _llm_duration_ms = (time.monotonic() - _llm_start) * 1000.0

            # Accumulate token usage
            if response.usage:
                total_usage.input_tokens += response.usage.input_tokens
                total_usage.output_tokens += response.usage.output_tokens
                total_usage.total_tokens += response.usage.total_tokens
                total_usage.estimated_cost_usd += response.usage.estimated_cost_usd

            # Emit LLMCalled event (skip during replay to avoid side-effect duplication)
            _replay = getattr(context, "replay_mode", False)
            if context.event_bus is not None and not _replay:
                from orchestra.storage.events import LLMCalled
                _in_tok = response.usage.input_tokens if response.usage else 0
                _out_tok = response.usage.output_tokens if response.usage else 0
                _cost = response.usage.estimated_cost_usd if response.usage else 0.0
                await context.event_bus.emit(
                    LLMCalled(
                        run_id=context.run_id,
                        node_id=context.node_id,
                        agent_name=self.name,
                        model=self.model,
                        content=response.content,
                        tool_calls=[tc.model_dump() for tc in response.tool_calls]
                        if response.tool_calls
                        else [],
                        input_tokens=_in_tok,
                        output_tokens=_out_tok,
                        cost_usd=_cost,
                        duration_ms=_llm_duration_ms,
                        finish_reason="tool_calls" if response.tool_calls else "stop",
                    )
                )

            if response.tool_calls:
                # Add assistant message with tool calls
                assistant_msg = Message(
                    role=MessageRole.ASSISTANT,
                    content=response.content or "",
                    tool_calls=response.tool_calls,
                )
                full_messages.append(assistant_msg)

                # Execute each tool
                for tool_call in response.tool_calls:
                    _tool_start = time.monotonic()
                    tool_result = await self._execute_tool(tool_call, context)
                    _tool_duration_ms = (time.monotonic() - _tool_start) * 1000.0

                    all_tool_records.append(
                        ToolCallRecord(
                            tool_call=tool_call,
                            result=tool_result.content,
                            error=tool_result.error,
                        )
                    )
                    full_messages.append(
                        Message(
                            role=MessageRole.TOOL,
                            content=tool_result.content or tool_result.error or "",
                            tool_call_id=tool_call.id,
                        )
                    )

                    # Emit ToolCalled event
                    if context.event_bus is not None and not _replay:
                        from orchestra.storage.events import ToolCalled
                        await context.event_bus.emit(
                            ToolCalled(
                                run_id=context.run_id,
                                node_id=context.node_id,
                                agent_name=self.name,
                                tool_name=tool_call.name,
                                arguments=dict(tool_call.arguments) if tool_call.arguments else {},
                                result=tool_result.content,
                                error=tool_result.error,
                                duration_ms=_tool_duration_ms,
                            )
                        )

                continue

            # No tool calls - final response
            output_text = response.content or ""
            assistant_msg = Message(
                role=MessageRole.ASSISTANT,
                content=output_text,
                name=self.name,
            )

            # Validate structured output if specified
            structured = None
            if self.output_type and output_text:
                try:
                    structured = self.output_type.model_validate_json(output_text)
                except Exception as e:
                    logger.warning(
                        "structured_output_validation_failed",
                        agent=self.name,
                        output_type=self.output_type.__name__,
                        error=str(e),
                    )

            return AgentResult(
                agent_name=self.name,
                output=output_text,
                structured_output=structured,
                messages=[assistant_msg],
                tool_calls_made=all_tool_records,
                token_usage=total_usage,
            )

        raise MaxIterationsError(
            f"Agent '{self.name}' exceeded max_iterations ({self.max_iterations}).\n"
            f"  Fix: Increase max_iterations or check why the agent keeps calling tools."
        )

    def _resolve_system_prompt(self, context: ExecutionContext) -> str:
        """Resolve the system prompt, supporting dynamic prompts."""
        return self.system_prompt

    async def _execute_tool(
        self,
        tool_call: ToolCall,
        context: ExecutionContext,
    ) -> ToolResult:
        """Execute a single tool call after authorizing via ACL."""
        # --- Time-Travel: Replay Check ---
        if context.replay_mode:
            from orchestra.storage.events import ToolCalled
            for event in context.replay_events:
                if (isinstance(event, ToolCalled) 
                    and event.tool_name == tool_call.name
                    # arguments check could be more robust (json match)
                    and event.arguments == (tool_call.arguments or {})):
                    
                    logger.debug("replaying_tool_call", tool=tool_call.name)
                    return ToolResult(
                        tool_call_id=tool_call.id,
                        name=tool_call.name,
                        content=str(event.result) if event.result is not None else "",
                        error=event.error,
                    )

        # 1. Authorization check
        if self.acl is None:
            from orchestra.security.acl import ToolACL
            object.__setattr__(self, "acl", ToolACL.open())

        if not self.acl.is_authorized(tool_call.name):
            from orchestra.storage.events import SecurityViolation
            if context.event_bus is not None:
                await context.event_bus.emit(
                    SecurityViolation(
                        run_id=context.run_id,
                        node_id=context.node_id,
                        agent_name=self.name,
                        violation_type="unauthorized_tool",
                        details={"tool_name": tool_call.name},
                    )
                )
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content="",
                error=f"Security Policy Violation: Agent '{self.name}' is not authorized to use tool '{tool_call.name}'.",
            )

        # 2. Tool lookup
        tool = next((t for t in self.tools if t.name == tool_call.name), None)
        if not tool:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content="",
                error=f"Tool '{tool_call.name}' not found. "
                f"Available: {[t.name for t in self.tools]}",
            )

        # 3. Execution
        try:
            result: ToolResult = await tool.execute(tool_call.arguments, context=context)
            return result
        except Exception as e:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content="",
                error=str(e),
            )

    def _tool_to_schema(self, tool: Any) -> dict[str, Any]:
        """Convert a Tool to the OpenAI function-calling schema format."""
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters_schema,
            },
        }


class DecoratedAgent(BaseAgent):
    """Agent created from a decorated function."""

    _original_func: Any = None

    model_config = {"arbitrary_types_allowed": True}


def agent(
    name: str | None = None,
    *,
    model: str = "gpt-4o-mini",
    tools: list[Any] | None = None,
    temperature: float = 0.7,
    max_iterations: int = 10,
    output_type: type[BaseModel] | None = None,
    provider: str | None = None,
) -> Callable[..., DecoratedAgent]:
    """Decorator to create an agent from an async function.

    The function's docstring becomes the system prompt.

    Usage:
        @agent(model="gpt-4o-mini")
        async def researcher(topic: str) -> str:
            '''You are a research analyst. Find key facts about the topic.'''
    """

    def decorator(func: Callable[..., Any]) -> DecoratedAgent:
        agent_name = name or func.__name__
        system_prompt = inspect.getdoc(func) or "You are a helpful assistant."

        agent_instance = DecoratedAgent(
            name=agent_name,
            model=model,
            system_prompt=system_prompt,
            tools=tools or [],
            temperature=temperature,
            max_iterations=max_iterations,
            output_type=output_type,
            provider=provider,
        )
        agent_instance._original_func = func
        functools.update_wrapper(agent_instance, func)  # type: ignore[arg-type]

        return agent_instance

    return decorator
