"""Tests for ClaudeCodeProvider.

Mocks asyncio.create_subprocess_exec to avoid running the real CLI.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestra.core.errors import ProviderError, ProviderUnavailableError
from orchestra.core.types import Message, MessageRole
from orchestra.providers._cli_common import format_tools_prompt as _format_tools_prompt
from orchestra.providers._cli_common import messages_to_prompt as _messages_to_prompt
from orchestra.providers._cli_common import parse_tool_calls as _parse_tool_calls
from orchestra.providers.claude_code import ClaudeCodeProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user(content: str) -> Message:
    return Message(role=MessageRole.USER, content=content)


def _system(content: str) -> Message:
    return Message(role=MessageRole.SYSTEM, content=content)


def _assistant(content: str) -> Message:
    return Message(role=MessageRole.ASSISTANT, content=content)


def _tool_result(content: str, call_id: str = "call_abc") -> Message:
    return Message(role=MessageRole.TOOL, content=content, tool_call_id=call_id)


def _make_cli_response(
    result: str = "Hello!",
    is_error: bool = False,
    stop_reason: str = "end_turn",
    input_tokens: int = 10,
    output_tokens: int = 5,
    cost: float = 0.001,
) -> dict[str, Any]:
    return {
        "type": "result",
        "subtype": "success",
        "is_error": is_error,
        "result": result,
        "stop_reason": stop_reason,
        "total_cost_usd": cost,
        "usage": {
            "input_tokens": input_tokens,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "output_tokens": output_tokens,
        },
    }


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
# _messages_to_prompt
# ---------------------------------------------------------------------------


class TestMessagesToPrompt:
    def test_simple_user_message(self) -> None:
        system, prompt = _messages_to_prompt([_user("hello")])
        assert system is None
        assert prompt == "hello"

    def test_system_extracted(self) -> None:
        system, prompt = _messages_to_prompt([_system("be nice"), _user("hi")])
        assert system == "be nice"
        assert prompt == "hi"

    def test_multi_turn_flattened(self) -> None:
        msgs = [_user("q1"), _assistant("a1"), _user("q2")]
        _system_out, prompt = _messages_to_prompt(msgs)
        assert "[assistant]" in prompt
        assert "q1" in prompt
        assert "a1" in prompt
        assert "q2" in prompt

    def test_tool_result_included(self) -> None:
        msgs = [_user("search"), _tool_result("result data", "call_123")]
        _, prompt = _messages_to_prompt(msgs)
        assert "call_123" in prompt
        assert "result data" in prompt


# ---------------------------------------------------------------------------
# _parse_tool_calls
# ---------------------------------------------------------------------------


class TestParseToolCalls:
    def test_no_tool_calls(self) -> None:
        assert _parse_tool_calls("just normal text") is None

    def test_single_tool_call(self) -> None:
        text = '<tool_calls>\n[{"name": "search", "arguments": {"query": "test"}}]\n</tool_calls>'
        calls = _parse_tool_calls(text)
        assert calls is not None
        assert len(calls) == 1
        assert calls[0].name == "search"
        assert calls[0].arguments == {"query": "test"}

    def test_multiple_tool_calls(self) -> None:
        text = (
            "<tool_calls>\n"
            '[{"name": "a", "arguments": {}}, {"name": "b", "arguments": {"x": 1}}]\n'
            "</tool_calls>"
        )
        calls = _parse_tool_calls(text)
        assert calls is not None
        assert len(calls) == 2

    def test_malformed_json_returns_none(self) -> None:
        text = "<tool_calls>\nnot json\n</tool_calls>"
        assert _parse_tool_calls(text) is None

    def test_missing_end_tag(self) -> None:
        text = '<tool_calls>\n[{"name": "x"}]'
        assert _parse_tool_calls(text) is None


# ---------------------------------------------------------------------------
# _format_tools_prompt
# ---------------------------------------------------------------------------


class TestFormatToolsPrompt:
    def test_formats_tool(self) -> None:
        result = _format_tools_prompt(SAMPLE_TOOLS)
        assert "search" in result
        assert "Search the web" in result
        assert "query" in result


# ---------------------------------------------------------------------------
# ClaudeCodeProvider.complete
# ---------------------------------------------------------------------------


class TestComplete:
    @pytest.mark.asyncio
    async def test_basic_completion(self) -> None:
        cli_resp = _make_cli_response(result="Hello world")
        proc = _mock_process(json.dumps(cli_resp).encode())

        provider = ClaudeCodeProvider(model="sonnet")
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            resp = await provider.complete([_user("hi")])

        assert resp.content == "Hello world"
        assert resp.finish_reason == "stop"
        assert resp.usage is not None
        assert resp.usage.output_tokens == 5

    @pytest.mark.asyncio
    async def test_tool_call_parsed(self) -> None:
        tool_text = (
            '<tool_calls>\n[{"name": "search", "arguments": {"query": "test"}}]\n</tool_calls>'
        )
        cli_resp = _make_cli_response(result=tool_text)
        proc = _mock_process(json.dumps(cli_resp).encode())

        provider = ClaudeCodeProvider()
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            resp = await provider.complete([_user("search for test")], tools=SAMPLE_TOOLS)

        assert resp.finish_reason == "tool_calls"
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "search"
        assert resp.content is None  # stripped

    @pytest.mark.asyncio
    async def test_nonzero_exit_raises(self) -> None:
        proc = _mock_process(b"", stderr=b"auth failed", returncode=1)

        provider = ClaudeCodeProvider()
        with (
            patch("asyncio.create_subprocess_exec", return_value=proc),
            pytest.raises(ProviderError, match="exited with code 1"),
        ):
            await provider.complete([_user("hi")])

    @pytest.mark.asyncio
    async def test_cli_not_found_raises(self) -> None:
        provider = ClaudeCodeProvider()
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
        provider = ClaudeCodeProvider(timeout=0.1)
        proc = _mock_process(b"")  # proc is created but communicate times out
        with (
            patch("asyncio.create_subprocess_exec", return_value=proc),
            patch("asyncio.wait_for", side_effect=TimeoutError),
            pytest.raises(ProviderError, match="timed out"),
        ):
            await provider.complete([_user("hi")])

    @pytest.mark.asyncio
    async def test_is_error_flag_raises(self) -> None:
        cli_resp = _make_cli_response(result="something went wrong", is_error=True)
        proc = _mock_process(json.dumps(cli_resp).encode())

        provider = ClaudeCodeProvider()
        with (
            patch("asyncio.create_subprocess_exec", return_value=proc),
            pytest.raises(ProviderError, match="returned an error"),
        ):
            await provider.complete([_user("hi")])

    @pytest.mark.asyncio
    async def test_bad_json_raises(self) -> None:
        proc = _mock_process(b"not json at all")

        provider = ClaudeCodeProvider()
        with (
            patch("asyncio.create_subprocess_exec", return_value=proc),
            pytest.raises(ProviderError, match="Failed to parse"),
        ):
            await provider.complete([_user("hi")])

    @pytest.mark.asyncio
    async def test_system_prompt_forwarded(self) -> None:
        cli_resp = _make_cli_response(result="ok")
        proc = _mock_process(json.dumps(cli_resp).encode())

        provider = ClaudeCodeProvider()
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await provider.complete([_system("be helpful"), _user("hi")])

        # System prompt is now passed via stdin (not --system-prompt flag)
        # to prevent argument injection via crafted system prompt content.
        call_args = mock_exec.call_args
        cmd_parts = list(call_args[0])
        assert "--system-prompt" not in cmd_parts
        # Verify system prompt is in the stdin payload
        stdin_data = proc.communicate.call_args[0][0].decode()
        assert "be helpful" in stdin_data

    @pytest.mark.asyncio
    async def test_max_tokens_stop_reason(self) -> None:
        cli_resp = _make_cli_response(result="truncated", stop_reason="max_tokens")
        proc = _mock_process(json.dumps(cli_resp).encode())

        provider = ClaudeCodeProvider()
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            resp = await provider.complete([_user("hi")])

        assert resp.finish_reason == "length"

    @pytest.mark.asyncio
    async def test_cost_in_usage(self) -> None:
        cli_resp = _make_cli_response(cost=0.05)
        proc = _mock_process(json.dumps(cli_resp).encode())

        provider = ClaudeCodeProvider()
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            resp = await provider.complete([_user("hi")])

        assert resp.usage is not None
        assert resp.usage.estimated_cost_usd == 0.05


# ---------------------------------------------------------------------------
# Properties & utilities
# ---------------------------------------------------------------------------


class TestProviderProperties:
    def test_provider_name(self) -> None:
        assert ClaudeCodeProvider().provider_name == "claude_code"

    def test_default_model(self) -> None:
        assert ClaudeCodeProvider().default_model == "sonnet"
        assert ClaudeCodeProvider(model="opus").default_model == "opus"

    def test_count_tokens(self) -> None:
        provider = ClaudeCodeProvider()
        tokens = provider.count_tokens([_user("hello world")])
        assert tokens > 0

    def test_model_cost_is_zero(self) -> None:
        cost = ClaudeCodeProvider().get_model_cost()
        assert cost.input_cost_per_1k == 0.0
        assert cost.output_cost_per_1k == 0.0

    def test_is_available_with_claude_on_path(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/claude"):
            assert ClaudeCodeProvider.is_available() is True

    def test_is_available_without_claude(self) -> None:
        with patch("shutil.which", return_value=None):
            assert ClaudeCodeProvider.is_available() is False

    @pytest.mark.asyncio
    async def test_aclose_is_noop(self) -> None:
        provider = ClaudeCodeProvider()
        await provider.aclose()  # should not raise
