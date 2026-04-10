"""Shared utilities for CLI-based providers (Claude Code, Gemini CLI, Codex CLI).

All CLI providers use the same prompt-engineering approach for tool calling:
tools are described in the system prompt, and the model replies with a
``<tool_calls>`` block that Orchestra parses automatically.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from asyncio.subprocess import PIPE
from contextlib import asynccontextmanager
from typing import Any

from orchestra.core.types import (
    Message,
    MessageRole,
    ToolCall,
)


@asynccontextmanager
async def managed_proc(*cmd: str, stdin: int | None = PIPE, stdout: int | None = PIPE, stderr: int | None = PIPE):  # type: ignore[return]
    """Spawn a subprocess and guarantee cleanup on exit — kills on exception."""
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdin=stdin, stdout=stdout, stderr=stderr
    )
    try:
        yield proc
    finally:
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                pass


# Marker the model must emit when it wants to call a tool.
TOOL_CALL_TAG = "<tool_calls>"
TOOL_CALL_END_TAG = "</tool_calls>"

TOOL_PREAMBLE = """\
You have access to the following tools. When you need to call one or more \
tools, respond ONLY with a JSON array wrapped in <tool_calls>...</tool_calls> \
tags. Each element must have "name" and "arguments" keys. Example:

<tool_calls>
[{"name": "search", "arguments": {"query": "hello"}}]
</tool_calls>

Do NOT mix tool calls with regular text. Either call tools OR respond with text.

Available tools:
"""


def format_tools_prompt(tools: list[dict[str, Any]]) -> str:
    """Turn OpenAI-style tool dicts into a human-readable tool description."""
    lines: list[str] = []
    for t in tools:
        func = t.get("function", t)
        name = func.get("name", "?")
        desc = func.get("description", "")
        params = func.get("parameters", {})
        props = params.get("properties", {})
        required = set(params.get("required", []))

        param_parts: list[str] = []
        for pname, pschema in props.items():
            ptype = pschema.get("type", "any")
            pdesc = pschema.get("description", "")
            req = " (required)" if pname in required else ""
            param_parts.append(f"    - {pname}: {ptype}{req} — {pdesc}")

        lines.append(f"- **{name}**: {desc}")
        if param_parts:
            lines.extend(param_parts)
    return "\n".join(lines)


def messages_to_prompt(
    messages: list[Message],
) -> tuple[str | None, str]:
    """Flatten Orchestra messages into (system_prompt, user_prompt).

    CLI providers accept a single user prompt plus an optional system prompt.
    Multi-turn conversations are serialised into the user prompt with role
    markers so the model sees the full history.
    """
    system: str | None = None
    parts: list[str] = []

    for msg in messages:
        if msg.role == MessageRole.SYSTEM:
            system = msg.content
            continue

        if msg.role == MessageRole.TOOL:
            parts.append(f"[tool result for call {msg.tool_call_id}]\n{msg.content}")
            continue

        if msg.role == MessageRole.ASSISTANT:
            parts.append(f"[assistant]\n{msg.content}")
            continue

        # USER
        parts.append(msg.content)

    return system, "\n\n".join(parts)


def parse_tool_calls(text: str) -> list[ToolCall] | None:
    """Extract tool calls from the model's response, if any."""
    start = text.find(TOOL_CALL_TAG)
    if start == -1:
        return None
    end = text.find(TOOL_CALL_END_TAG, start)
    if end == -1:
        return None

    json_str = text[start + len(TOOL_CALL_TAG) : end].strip()
    try:
        raw = json.loads(json_str)
    except json.JSONDecodeError:
        return None

    if not isinstance(raw, list):
        raw = [raw]

    calls: list[ToolCall] = []
    for item in raw:
        calls.append(
            ToolCall(
                id=f"call_{uuid.uuid4().hex[:12]}",
                name=item.get("name", ""),
                arguments=item.get("arguments", {}),
            )
        )
    return calls or None


def strip_tool_calls(text: str) -> str | None:
    """Remove the <tool_calls>...</tool_calls> block from response text.

    Returns the remaining text, or None if nothing is left.
    """
    start = text.find(TOOL_CALL_TAG)
    end = text.find(TOOL_CALL_END_TAG)
    if start != -1 and end != -1:
        content = (text[:start] + text[end + len(TOOL_CALL_END_TAG) :]).strip()
        return content or None
    return text


def inject_tools_into_system(system: str | None, tools: list[dict[str, Any]]) -> str:
    """Append tool descriptions to the system prompt."""
    tool_block = TOOL_PREAMBLE + format_tools_prompt(tools)
    return f"{system}\n\n{tool_block}" if system else tool_block
