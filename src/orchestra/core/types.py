"""Core types for Orchestra framework."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    """Roles for messages in agent conversations."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Message(BaseModel):
    """A single message in an agent conversation."""

    role: MessageRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}


class ToolCall(BaseModel):
    """A tool invocation requested by an LLM."""

    id: str = Field(default_factory=lambda: f"call_{uuid.uuid4().hex[:12]}")
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolCallRecord(BaseModel):
    """Record of a tool call that was executed."""

    tool_call: ToolCall
    result: str
    error: str | None = None
    duration_ms: float = 0.0


class ToolResult(BaseModel):
    """Result of executing a tool."""

    tool_call_id: str
    name: str
    content: str
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TokenUsage(BaseModel):
    """Token usage from an LLM call."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0


class AgentResult(BaseModel):
    """Result returned by an agent after execution."""

    agent_name: str
    output: str = ""
    structured_output: BaseModel | None = None
    messages: list[Message] = Field(default_factory=list)
    tool_calls_made: list[ToolCallRecord] = Field(default_factory=list)
    handoff_to: str | None = None
    state_updates: dict[str, Any] = Field(default_factory=dict)
    token_usage: TokenUsage | None = None

    model_config = {"arbitrary_types_allowed": True}


class LLMResponse(BaseModel):
    """Response from an LLM provider."""

    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: Literal["stop", "tool_calls", "length", "error"] = "stop"
    usage: TokenUsage | None = None
    model: str = ""
    raw_response: Any = None

    model_config = {"arbitrary_types_allowed": True}


class StreamChunk(BaseModel):
    """A single chunk from a streaming LLM response."""

    content: str = ""
    finish_reason: Literal["stop", "tool_calls", "length", "error"] | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    model: str = ""


class ModelCost(BaseModel):
    """Cost information for a model."""

    input_cost_per_1k: float = 0.0
    output_cost_per_1k: float = 0.0


class NodeStatus(str, Enum):
    """Status of a graph node during execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowStatus(str, Enum):
    """Status of an entire workflow run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    CANCELLED = "cancelled"


# --- Sentinels ---


class _EndSentinel:
    """Sentinel object for graph termination."""

    _instance: _EndSentinel | None = None

    def __new__(cls) -> _EndSentinel:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "END"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _EndSentinel)

    def __hash__(self) -> int:
        return hash("__orchestra_end__")


END = _EndSentinel()
START = "__start__"
