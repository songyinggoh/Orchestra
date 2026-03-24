"""OpenAI Codex CLI provider — uses your OpenAI subscription directly.

No API key required. Invokes the ``codex`` CLI in quiet mode as a
subprocess, so Orchestra piggybacks on your existing OpenAI / ChatGPT
subscription.

The Codex CLI (https://github.com/openai/codex) authenticates via your
OpenAI account. If you can run ``codex`` in your terminal, this provider
works automatically.

Usage:
    from orchestra.providers.codex_cli import CodexCliProvider

    provider = CodexCliProvider()                   # uses default model
    provider = CodexCliProvider(model="o4-mini")    # pick a model
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


class CodexCliProvider:
    """LLM provider that delegates to the ``codex`` CLI.

    Requires only an OpenAI account — no ``OPENAI_API_KEY`` or any other
    billing account.  Each ``complete()`` call spawns ``codex`` in quiet
    mode as a subprocess.

    Tool calling is supported via prompt engineering: tools are described
    in the system prompt and the model replies with a ``<tool_calls>``
    block that Orchestra parses automatically.
    """

    def __init__(
        self,
        model: str = "o4-mini",
        timeout: float = 120.0,
        codex_path: str | None = None,
    ) -> None:
        self._default_model = model
        self._timeout = timeout
        self._codex_path = codex_path or shutil.which("codex") or "codex"

    @property
    def provider_name(self) -> str:
        return "codex_cli"

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
        """Send a completion request via the ``codex`` CLI in quiet mode."""
        use_model = model or self._default_model
        system, prompt = messages_to_prompt(messages)

        if tools:
            system = inject_tools_into_system(system, tools)

        # Build the full prompt including system instructions.
        full_prompt = prompt
        if system:
            full_prompt = f"[system]\n{system}\n\n{prompt}"

        cmd: list[str] = [
            self._codex_path,
            "--quiet",
            "--model",
            use_model,
            "--approval-mode",
            "full-auto",
            full_prompt,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._timeout,
            )
        except FileNotFoundError:
            raise ProviderUnavailableError(
                "The 'codex' CLI was not found on PATH.\n"
                "  Fix: Install the OpenAI Codex CLI (https://github.com/openai/codex) "
                "or pass codex_path= to CodexCliProvider."
            ) from None
        except TimeoutError:
            raise ProviderError(
                f"codex CLI timed out after {self._timeout}s. "
                "Increase timeout= or simplify the prompt."
            ) from None

        if proc.returncode != 0:
            err_text = stderr.decode(errors="replace").strip()
            raise ProviderError(
                f"codex CLI exited with code {proc.returncode}.\n  stderr: {err_text[:500]}"
            )

        raw_output = stdout.decode(errors="replace").strip()

        # Try JSON first (codex may output structured JSON).
        data: dict[str, Any] | None = None
        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError:
            pass

        if data and isinstance(data, dict):
            return self._parse_json_response(data, use_model, tools)

        # Fall back to plain text response.
        return self._parse_text_response(raw_output, use_model, tools)

    async def stream(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream completion via the ``codex`` CLI."""
        use_model = model or self._default_model
        system, prompt = messages_to_prompt(messages)

        if tools:
            system = inject_tools_into_system(system, tools)

        full_prompt = prompt
        if system:
            full_prompt = f"[system]\n{system}\n\n{prompt}"

        cmd: list[str] = [
            self._codex_path,
            "--quiet",
            "--model",
            use_model,
            "--approval-mode",
            "full-auto",
            full_prompt,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            raise ProviderUnavailableError(
                "The 'codex' CLI was not found on PATH.\n  Fix: Install the OpenAI Codex CLI."
            ) from None

        assert proc.stdout is not None

        async for raw_line in proc.stdout:
            line = raw_line.decode(errors="replace").strip()
            if not line:
                continue

            # Try to parse as JSON event.
            try:
                event = json.loads(line)
                text = event.get("text", event.get("content", ""))
                if text:
                    yield StreamChunk(content=text, model=use_model)
                if event.get("done") or event.get("type") == "result":
                    yield StreamChunk(content="", finish_reason="stop", model=use_model)
                continue
            except json.JSONDecodeError:
                pass

            # Plain text line.
            yield StreamChunk(content=line, model=use_model)

        yield StreamChunk(content="", finish_reason="stop", model=use_model)
        await proc.wait()

    def count_tokens(self, messages: list[Message], model: str | None = None) -> int:
        """Approximate token count (4 chars per token heuristic)."""
        total = 0
        for msg in messages:
            total += len(msg.content) // 4 + 4
        return total

    def get_model_cost(self, model: str | None = None) -> ModelCost:
        """Cost is zero — covered by the OpenAI / ChatGPT subscription."""
        return ModelCost(input_cost_per_1k=0.0, output_cost_per_1k=0.0)

    def _parse_json_response(
        self,
        data: dict[str, Any],
        model: str,
        tools: list[dict[str, Any]] | None,
    ) -> LLMResponse:
        """Parse structured JSON output from the CLI."""
        result_text: str = data.get("result", data.get("text", data.get("content", ""))) or ""

        tool_calls: list[ToolCall] = []
        content = result_text
        if tools:
            parsed = parse_tool_calls(result_text)
            if parsed:
                tool_calls = parsed
                content = strip_tool_calls(result_text)

        finish_reason = "tool_calls" if tool_calls else "stop"

        raw_usage = data.get("usage", {})
        input_tok = raw_usage.get("input_tokens", raw_usage.get("prompt_tokens", 0))
        output_tok = raw_usage.get("output_tokens", raw_usage.get("completion_tokens", 0))

        usage = TokenUsage(
            input_tokens=input_tok,
            output_tokens=output_tok,
            total_tokens=input_tok + output_tok,
            estimated_cost_usd=0.0,
        )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            model=model,
            raw_response=data,
        )

    def _parse_text_response(
        self,
        text: str,
        model: str,
        tools: list[dict[str, Any]] | None,
    ) -> LLMResponse:
        """Parse plain text output from the CLI."""
        tool_calls: list[ToolCall] = []
        content: str | None = text
        if tools:
            parsed = parse_tool_calls(text)
            if parsed:
                tool_calls = parsed
                content = strip_tool_calls(text)

        finish_reason = "tool_calls" if tool_calls else "stop"

        input_tok = len(text) // 4
        output_tok = len(text) // 4

        usage = TokenUsage(
            input_tokens=input_tok,
            output_tokens=output_tok,
            total_tokens=input_tok + output_tok,
            estimated_cost_usd=0.0,
        )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            model=model,
        )

    async def aclose(self) -> None:
        """No persistent connections to close."""

    @staticmethod
    def is_available() -> bool:
        """Return True if the ``codex`` CLI is on PATH."""
        return shutil.which("codex") is not None
