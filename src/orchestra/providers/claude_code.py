"""Claude Code CLI provider — uses your Claude Code subscription directly.

No API key required. Invokes the ``claude`` CLI in print mode (``-p``)
as a subprocess, so Orchestra piggybacks on your existing Claude Code
subscription.

Usage:
    from orchestra.providers.claude_code import ClaudeCodeProvider

    provider = ClaudeCodeProvider()                   # uses default model
    provider = ClaudeCodeProvider(model="sonnet")      # pick a model alias
"""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import AsyncIterator
from typing import Any

from orchestra.core.errors import ProviderError, ProviderUnavailableError
from orchestra.core.types import (
    LLMResponse,
    Message,
    ModelCost,
    StreamChunk,
    TokenUsage,
    ToolCall,
)
from orchestra.providers._cli_common import (
    inject_tools_into_system,
    messages_to_prompt,
    parse_tool_calls,
    strip_tool_calls,
)


class ClaudeCodeProvider:
    """LLM provider that delegates to the ``claude`` CLI.

    Requires only a Claude Code subscription — no ``ANTHROPIC_API_KEY``
    or any other billing account.  Each ``complete()`` call spawns
    ``claude -p --output-format json`` as a subprocess.

    Tool calling is supported via prompt engineering: tools are described
    in the system prompt and the model replies with a ``<tool_calls>``
    block that Orchestra parses automatically.
    """

    def __init__(
        self,
        model: str = "sonnet",
        timeout: float = 120.0,
        claude_path: str | None = None,
    ) -> None:
        self._default_model = model
        self._timeout = timeout
        self._claude_path = claude_path or shutil.which("claude") or "claude"

    @property
    def provider_name(self) -> str:
        return "claude_code"

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
        """Send a completion request via the ``claude`` CLI."""
        use_model = model or self._default_model
        system, prompt = messages_to_prompt(messages)

        if tools:
            system = inject_tools_into_system(system, tools)

        cmd: list[str] = [
            self._claude_path,
            "-p",
            "--output-format",
            "json",
            "--model",
            use_model,
            "--no-session-persistence",
            "--bare",
            "--tools",
            "",
        ]
        # Pass system prompt via stdin to prevent argument injection
        # via crafted system prompt content.
        stdin_payload = prompt
        if system:
            stdin_payload = f"[system]\n{system}\n\n[user]\n{prompt}"

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(stdin_payload.encode()),
                timeout=self._timeout,
            )
        except FileNotFoundError:
            raise ProviderUnavailableError(
                "The 'claude' CLI was not found on PATH.\n"
                "  Fix: Install Claude Code (https://docs.anthropic.com/en/docs/claude-code) "
                "or pass claude_path= to ClaudeCodeProvider."
            ) from None
        except TimeoutError:
            raise ProviderError(
                f"claude CLI timed out after {self._timeout}s. "
                "Increase timeout= or simplify the prompt."
            ) from None

        if proc.returncode != 0:
            err_text = stderr.decode(errors="replace").strip()
            raise ProviderError(
                f"claude CLI exited with code {proc.returncode}.\n  stderr: {err_text[:500]}"
            )

        try:
            data: dict[str, Any] = json.loads(stdout.decode())
        except json.JSONDecodeError:
            raw = stdout.decode(errors="replace")[:500]
            raise ProviderError(f"Failed to parse claude CLI JSON output:\n  {raw}") from None

        if data.get("is_error"):
            raise ProviderError(f"claude CLI returned an error: {data.get('result', 'unknown')}")

        return self._parse_response(data, use_model, tools)

    async def stream(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream completion via the ``claude`` CLI using ``stream-json``."""
        use_model = model or self._default_model
        system, prompt = messages_to_prompt(messages)

        if tools:
            system = inject_tools_into_system(system, tools)

        cmd: list[str] = [
            self._claude_path,
            "-p",
            "--output-format",
            "stream-json",
            "--model",
            use_model,
            "--no-session-persistence",
            "--bare",
            "--tools",
            "",
        ]
        # Pass system prompt via stdin to prevent argument injection.
        stdin_payload = prompt
        if system:
            stdin_payload = f"[system]\n{system}\n\n[user]\n{prompt}"

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            raise ProviderUnavailableError(
                "The 'claude' CLI was not found on PATH.\n  Fix: Install Claude Code."
            ) from None

        assert proc.stdin is not None
        assert proc.stdout is not None

        proc.stdin.write(stdin_payload.encode())
        proc.stdin.close()

        async for raw_line in proc.stdout:
            line = raw_line.decode(errors="replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = event.get("type", "")
            if etype == "assistant":
                content = event.get("message", {}).get("content", "")
                if isinstance(content, list):
                    text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
                else:
                    text = str(content)
                if text:
                    yield StreamChunk(content=text, model=use_model)
            elif etype == "result":
                yield StreamChunk(
                    content="",
                    finish_reason="stop",
                    model=use_model,
                )

        await proc.wait()

    def count_tokens(self, messages: list[Message], model: str | None = None) -> int:
        """Approximate token count (4 chars per token heuristic)."""
        total = 0
        for msg in messages:
            total += len(msg.content) // 4 + 4
        return total

    def get_model_cost(self, model: str | None = None) -> ModelCost:
        """Cost is zero — covered by the Claude Code subscription."""
        return ModelCost(input_cost_per_1k=0.0, output_cost_per_1k=0.0)

    def _parse_response(
        self,
        data: dict[str, Any],
        model: str,
        tools: list[dict[str, Any]] | None,
    ) -> LLMResponse:
        """Convert CLI JSON output to an LLMResponse."""
        result_text: str = data.get("result", "") or ""

        # Check for tool calls in the response text.
        tool_calls: list[ToolCall] = []
        content: str | None = result_text
        if tools:
            parsed = parse_tool_calls(result_text)
            if parsed:
                tool_calls = parsed
                content = strip_tool_calls(result_text) or None

        # Map stop reason.
        raw_stop = data.get("stop_reason", "end_turn")
        if tool_calls:
            finish_reason = "tool_calls"
        elif raw_stop == "max_tokens":
            finish_reason = "length"
        else:
            finish_reason = "stop"

        # Parse usage from the nested structure.
        raw_usage = data.get("usage", {})
        input_tok = raw_usage.get("input_tokens", 0)
        cache_creation = raw_usage.get("cache_creation_input_tokens", 0)
        cache_read = raw_usage.get("cache_read_input_tokens", 0)
        output_tok = raw_usage.get("output_tokens", 0)
        total_input = input_tok + cache_creation + cache_read

        usage = TokenUsage(
            input_tokens=total_input,
            output_tokens=output_tok,
            total_tokens=total_input + output_tok,
            estimated_cost_usd=data.get("total_cost_usd", 0.0),
        )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            model=model,
            raw_response=data,
        )

    async def aclose(self) -> None:
        """No persistent connections to close."""

    @staticmethod
    def is_available() -> bool:
        """Return True if the ``claude`` CLI is on PATH."""
        return shutil.which("claude") is not None
