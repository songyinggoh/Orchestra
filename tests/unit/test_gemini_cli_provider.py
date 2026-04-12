"""Tests for GeminiCliProvider.

Mocks asyncio.create_subprocess_exec to avoid running the real CLI.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestra.core.errors import ProviderError, ProviderUnavailableError
from orchestra.core.types import Message, MessageRole
from orchestra.providers.gemini_cli import GeminiCliProvider

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
# GeminiCliProvider.complete — plain text response
# ---------------------------------------------------------------------------


class TestCompleteText:
    @pytest.mark.asyncio
    async def test_basic_completion(self) -> None:
        proc = _mock_process(b"Hello from Gemini!")

        provider = GeminiCliProvider(model="gemini-2.5-flash")
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            resp = await provider.complete([_user("hi")])

        assert resp.content == "Hello from Gemini!"
        assert resp.finish_reason == "stop"
        assert resp.usage is not None

    @pytest.mark.asyncio
    async def test_tool_call_parsed_from_text(self) -> None:
        tool_text = (
            '<tool_calls>\n[{"name": "search", "arguments": {"query": "test"}}]\n</tool_calls>'
        )
        proc = _mock_process(tool_text.encode())

        provider = GeminiCliProvider()
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            resp = await provider.complete([_user("search for test")], tools=SAMPLE_TOOLS)

        assert resp.finish_reason == "tool_calls"
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "search"


# ---------------------------------------------------------------------------
# GeminiCliProvider.complete — JSON response
# ---------------------------------------------------------------------------


class TestCompleteJson:
    @pytest.mark.asyncio
    async def test_json_response_parsed(self) -> None:
        data = {
            "result": "Hello from Gemini!",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        proc = _mock_process(json.dumps(data).encode())

        provider = GeminiCliProvider()
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            resp = await provider.complete([_user("hi")])

        assert resp.content == "Hello from Gemini!"
        assert resp.usage is not None
        assert resp.usage.input_tokens == 10
        assert resp.usage.output_tokens == 5

    @pytest.mark.asyncio
    async def test_json_tool_call_parsed(self) -> None:
        tool_text = '<tool_calls>\n[{"name": "search", "arguments": {"query": "q"}}]\n</tool_calls>'
        data = {"result": tool_text}
        proc = _mock_process(json.dumps(data).encode())

        provider = GeminiCliProvider()
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

        provider = GeminiCliProvider()
        with (
            patch("asyncio.create_subprocess_exec", return_value=proc),
            pytest.raises(ProviderError, match="exited with code 1"),
        ):
            await provider.complete([_user("hi")])

    @pytest.mark.asyncio
    async def test_cli_not_found_raises(self) -> None:
        provider = GeminiCliProvider()
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
        provider = GeminiCliProvider(timeout=0.1)
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
        assert GeminiCliProvider().provider_name == "gemini_cli"

    def test_default_model(self) -> None:
        assert GeminiCliProvider().default_model == "gemini-2.5-flash"
        assert GeminiCliProvider(model="gemini-2.5-pro").default_model == "gemini-2.5-pro"

    def test_count_tokens(self) -> None:
        provider = GeminiCliProvider()
        tokens = provider.count_tokens([_user("hello world")])
        assert tokens > 0

    def test_model_cost_is_zero(self) -> None:
        cost = GeminiCliProvider().get_model_cost()
        assert cost.input_cost_per_1k == 0.0
        assert cost.output_cost_per_1k == 0.0

    def test_is_available_with_gemini_on_path(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/gemini"):
            assert GeminiCliProvider.is_available() is True

    def test_is_available_without_gemini(self) -> None:
        with patch("shutil.which", return_value=None):
            assert GeminiCliProvider.is_available() is False

    @pytest.mark.asyncio
    async def test_aclose_is_noop(self) -> None:
        provider = GeminiCliProvider()
        await provider.aclose()

    @pytest.mark.asyncio
    async def test_system_prompt_forwarded(self) -> None:
        proc = _mock_process(b"ok")

        provider = GeminiCliProvider()
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await provider.complete([_system("be helpful"), _user("hi")])

        # System prompt is now passed via stdin (not --system-prompt flag)
        # to prevent argument injection via crafted system prompt content.
        cmd_parts = list(mock_exec.call_args[0])
        assert "--system-prompt" not in cmd_parts
        stdin_data = proc.communicate.call_args[0][0].decode()
        assert "be helpful" in stdin_data
