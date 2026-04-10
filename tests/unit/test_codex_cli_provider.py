"""Tests for CodexCliProvider.

Mocks asyncio.create_subprocess_exec to avoid running the real CLI.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestra.core.errors import ProviderError, ProviderUnavailableError
from orchestra.core.types import Message, MessageRole
from orchestra.providers.codex_cli import CodexCliProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user(content: str) -> Message:
    return Message(role=MessageRole.USER, content=content)


def _system(content: str) -> Message:
    return Message(role=MessageRole.SYSTEM, content=content)


def _mock_process(stdout: bytes, stderr: bytes = b"", returncode: int = 0) -> AsyncMock:
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.close = MagicMock()
    proc.stdout = MagicMock()
    proc.wait = AsyncMock(return_value=0)
    return proc


SAMPLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search the web",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        },
    }
]


# ---------------------------------------------------------------------------
# CodexCliProvider.complete — plain text response
# ---------------------------------------------------------------------------


class TestCompleteText:
    @pytest.mark.asyncio
    async def test_basic_completion(self) -> None:
        proc = _mock_process(b"Hello from Codex!")

        provider = CodexCliProvider(model="o4-mini")
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            resp = await provider.complete([_user("hi")])

        assert resp.content == "Hello from Codex!"
        assert resp.finish_reason == "stop"
        assert resp.usage is not None

    @pytest.mark.asyncio
    async def test_tool_call_parsed_from_text(self) -> None:
        tool_text = (
            '<tool_calls>\n[{"name": "search", "arguments": {"query": "test"}}]\n</tool_calls>'
        )
        proc = _mock_process(tool_text.encode())

        provider = CodexCliProvider()
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            resp = await provider.complete([_user("search for test")], tools=SAMPLE_TOOLS)

        assert resp.finish_reason == "tool_calls"
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "search"


# ---------------------------------------------------------------------------
# CodexCliProvider.complete — JSON response
# ---------------------------------------------------------------------------


class TestCompleteJson:
    @pytest.mark.asyncio
    async def test_json_response_parsed(self) -> None:
        data = {
            "result": "Hello from Codex!",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        proc = _mock_process(json.dumps(data).encode())

        provider = CodexCliProvider()
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            resp = await provider.complete([_user("hi")])

        assert resp.content == "Hello from Codex!"
        assert resp.usage is not None
        assert resp.usage.input_tokens == 10
        assert resp.usage.output_tokens == 5

    @pytest.mark.asyncio
    async def test_json_tool_call_parsed(self) -> None:
        tool_text = '<tool_calls>\n[{"name": "search", "arguments": {"query": "q"}}]\n</tool_calls>'
        data = {"result": tool_text}
        proc = _mock_process(json.dumps(data).encode())

        provider = CodexCliProvider()
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            resp = await provider.complete([_user("search")], tools=SAMPLE_TOOLS)

        assert resp.finish_reason == "tool_calls"
        assert len(resp.tool_calls) == 1


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrors:
    @pytest.mark.asyncio
    async def test_nonzero_exit_raises(self) -> None:
        proc = _mock_process(b"", stderr=b"auth failed", returncode=1)

        provider = CodexCliProvider()
        with (
            patch("asyncio.create_subprocess_exec", return_value=proc),
            pytest.raises(ProviderError, match="exited with code 1"),
        ):
            await provider.complete([_user("hi")])

    @pytest.mark.asyncio
    async def test_cli_not_found_raises(self) -> None:
        provider = CodexCliProvider()
        with (
            patch(
                "asyncio.create_subprocess_exec",
                side_effect=FileNotFoundError,
            ),
            pytest.raises(ProviderUnavailableError, match="not found"),
        ):
            await provider.complete([_user("hi")])

    @pytest.mark.asyncio
    async def test_timeout_raises(self) -> None:
        provider = CodexCliProvider(timeout=0.1)
        proc = _mock_process(b"")  # proc is created but communicate times out
        with (
            patch("asyncio.create_subprocess_exec", return_value=proc),
            patch("asyncio.wait_for", side_effect=TimeoutError),
            pytest.raises(ProviderError, match="timed out"),
        ):
            await provider.complete([_user("hi")])


# ---------------------------------------------------------------------------
# Properties & utilities
# ---------------------------------------------------------------------------


class TestProviderProperties:
    def test_provider_name(self) -> None:
        assert CodexCliProvider().provider_name == "codex_cli"

    def test_default_model(self) -> None:
        assert CodexCliProvider().default_model == "o4-mini"
        assert CodexCliProvider(model="gpt-4.1").default_model == "gpt-4.1"

    def test_count_tokens(self) -> None:
        provider = CodexCliProvider()
        tokens = provider.count_tokens([_user("hello world")])
        assert tokens > 0

    def test_model_cost_is_zero(self) -> None:
        cost = CodexCliProvider().get_model_cost()
        assert cost.input_cost_per_1k == 0.0
        assert cost.output_cost_per_1k == 0.0

    def test_is_available_with_codex_on_path(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/codex"):
            assert CodexCliProvider.is_available() is True

    def test_is_available_without_codex(self) -> None:
        with patch("shutil.which", return_value=None):
            assert CodexCliProvider.is_available() is False

    @pytest.mark.asyncio
    async def test_aclose_is_noop(self) -> None:
        provider = CodexCliProvider()
        await provider.aclose()

    @pytest.mark.asyncio
    async def test_quiet_and_full_auto_flags(self) -> None:
        proc = _mock_process(b"ok")

        provider = CodexCliProvider()
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await provider.complete([_user("hi")])

        cmd_parts = list(mock_exec.call_args[0])
        assert "--quiet" in cmd_parts
        assert "--approval-mode" in cmd_parts
        idx = cmd_parts.index("--approval-mode")
        assert cmd_parts[idx + 1] == "full-auto"
