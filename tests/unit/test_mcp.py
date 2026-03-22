"""Unit tests for MCP client integration.

Tests MCPToolAdapter, MCPClient factory methods and connection lifecycle,
and the load_mcp_config() config loader.

Mock strategy: MCPToolAdapter is tested by constructing it with an AsyncMock
session and a MagicMock tool schema. MCPClient connection tests patch the
transport context managers so no real subprocess or network I/O occurs.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestra.core.errors import MCPTimeoutError, ToolNotFoundError
from orchestra.core.protocols import Tool
from orchestra.tools.mcp import MCPClient, MCPToolAdapter, load_mcp_config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_schema(
    name: str = "test_tool",
    description: str | None = "A test tool",
    input_schema: dict | None = None,
) -> MagicMock:
    """Return a MagicMock that looks like an mcp.types.Tool schema object."""
    schema = MagicMock()
    schema.name = name
    schema.description = description
    schema.inputSchema = (
        input_schema
        if input_schema is not None
        else {
            "type": "object",
            "properties": {},
        }
    )
    return schema


def _make_adapter(
    name: str = "test_tool",
    description: str | None = "A test tool",
    input_schema: dict | None = None,
    timeout: float = 30.0,
) -> tuple[MCPToolAdapter, AsyncMock]:
    """Construct an MCPToolAdapter with a mock session. Returns (adapter, session)."""
    session = AsyncMock()
    tool_schema = _make_tool_schema(name=name, description=description, input_schema=input_schema)
    adapter = MCPToolAdapter(session=session, tool_schema=tool_schema, timeout=timeout)
    return adapter, session


def _make_content_block(text: str) -> MagicMock:
    """Return a MagicMock content block with type='text'."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _make_call_tool_result(content_text: str = "ok", is_error: bool = False) -> MagicMock:
    """Return a MagicMock that looks like an mcp CallToolResult."""
    result = MagicMock()
    result.isError = is_error
    result.content = [_make_content_block(content_text)]
    return result


# ---------------------------------------------------------------------------
# TestMCPToolAdapter
# ---------------------------------------------------------------------------


class TestMCPToolAdapter:
    """Tests for MCPToolAdapter property accessors and execute()."""

    def test_name_property(self) -> None:
        """adapter.name returns the tool schema's name attribute."""
        adapter, _ = _make_adapter(name="list_files")
        assert adapter.name == "list_files"

    def test_description_property(self) -> None:
        """adapter.description returns the description string when present."""
        adapter, _ = _make_adapter(description="Lists files in a directory")
        assert adapter.description == "Lists files in a directory"

    def test_description_property_absent(self) -> None:
        """adapter.description returns '' when description is None."""
        adapter, _ = _make_adapter(description=None)
        assert adapter.description == ""

    def test_parameters_schema_property(self) -> None:
        """adapter.parameters_schema returns the inputSchema dict."""
        schema = {"type": "object", "properties": {"path": {"type": "string"}}}
        adapter, _ = _make_adapter(input_schema=schema)
        assert adapter.parameters_schema == schema

    def test_parameters_schema_none_returns_empty_object(self) -> None:
        """When inputSchema cannot be converted to dict, returns fallback schema."""

        class _Unconvertible:
            """An object that is not a dict and raises on dict() conversion."""

            def __iter__(self):
                raise TypeError("not iterable")

        session = AsyncMock()
        tool_schema = MagicMock()
        tool_schema.name = "bad_tool"
        tool_schema.description = "tool"
        tool_schema.inputSchema = _Unconvertible()
        adapter = MCPToolAdapter(session=session, tool_schema=tool_schema, timeout=30.0)
        result = adapter.parameters_schema
        assert result == {"type": "object", "properties": {}}

    def test_satisfies_tool_protocol(self) -> None:
        """isinstance(adapter, Tool) is True — structural subtyping check."""
        adapter, _ = _make_adapter()
        assert isinstance(adapter, Tool)

    @pytest.mark.asyncio
    async def test_execute_success(self) -> None:
        """execute() returns ToolResult with content set and error=None."""
        adapter, session = _make_adapter(name="echo")
        session.call_tool = AsyncMock(return_value=_make_call_tool_result("hello world"))

        result = await adapter.execute({"msg": "hello"})

        session.call_tool.assert_awaited_once_with("echo", {"msg": "hello"})
        assert result.content == "hello world"
        assert result.error is None
        assert result.name == "echo"

    @pytest.mark.asyncio
    async def test_execute_mcp_error(self) -> None:
        """execute() returns ToolResult with error set when isError=True."""
        adapter, session = _make_adapter(name="fail_tool")
        session.call_tool = AsyncMock(
            return_value=_make_call_tool_result("something went wrong", is_error=True)
        )

        result = await adapter.execute({})

        assert result.error == "something went wrong"
        assert result.content == ""

    @pytest.mark.asyncio
    async def test_execute_mcp_error_empty_content(self) -> None:
        """execute() uses fallback error message when error content is empty."""
        adapter, session = _make_adapter(name="fail_tool")
        error_result = MagicMock()
        error_result.isError = True
        error_result.content = []  # no content blocks → empty text
        session.call_tool = AsyncMock(return_value=error_result)

        result = await adapter.execute({})

        assert result.error == "MCP tool returned an error"


# ---------------------------------------------------------------------------
# TestMCPToolAdapterTimeout
# ---------------------------------------------------------------------------


class TestMCPToolAdapterTimeout:
    """Tests for timeout handling in MCPToolAdapter.execute()."""

    @pytest.mark.asyncio
    async def test_execute_timeout(self) -> None:
        """asyncio.TimeoutError from session.call_tool is re-raised as MCPTimeoutError."""
        adapter, session = _make_adapter(name="slow_tool", timeout=1.0)
        # Make call_tool raise asyncio.TimeoutError when awaited
        session.call_tool = AsyncMock(side_effect=TimeoutError())

        with pytest.raises(MCPTimeoutError, match="slow_tool"):
            await adapter.execute({})


# ---------------------------------------------------------------------------
# TestMCPClient
# ---------------------------------------------------------------------------


class TestMCPClient:
    """Tests for MCPClient factory methods and connect/tool-discovery lifecycle."""

    def test_stdio_factory(self) -> None:
        """MCPClient.stdio() returns MCPClient configured for stdio transport."""
        client = MCPClient.stdio("npx", args=["@mcp/server", "/tmp"], timeout=15.0)
        assert isinstance(client, MCPClient)
        assert client._transport == "stdio"
        assert client._command == "npx"
        assert client._args == ["@mcp/server", "/tmp"]
        assert client._timeout == 15.0

    def test_http_factory(self) -> None:
        """MCPClient.http() returns MCPClient configured for HTTP transport."""
        client = MCPClient.http(
            "http://localhost:8080/mcp",
            headers={"Authorization": "Bearer tok"},
            timeout=60.0,
        )
        assert isinstance(client, MCPClient)
        assert client._transport == "http"
        assert client._url == "http://localhost:8080/mcp"
        assert client._headers == {"Authorization": "Bearer tok"}
        assert client._timeout == 60.0

    @pytest.mark.asyncio
    async def test_get_tools_after_connect(self) -> None:
        """After connect(), get_tools() returns a list of MCPToolAdapter instances."""
        # Build a fake list_tools response
        tool_schema = _make_tool_schema(name="read_file", description="Reads a file")
        list_tools_response = MagicMock()
        list_tools_response.tools = [tool_schema]

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=list_tools_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_transport_cm = AsyncMock()
        mock_transport_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        mock_transport_cm.__aexit__ = AsyncMock(return_value=False)

        client = MCPClient.stdio("npx", args=["server"])

        async def patched_connect(self_inner):
            self_inner._cm = mock_transport_cm
            await mock_transport_cm.__aenter__()
            self_inner._session = mock_session
            await mock_session.__aenter__()
            await mock_session.initialize()

        with patch.object(MCPClient, "_connect_stdio", patched_connect):
            await client.connect()

        tools = client.get_tools()
        assert len(tools) == 1
        assert isinstance(tools[0], MCPToolAdapter)
        assert tools[0].name == "read_file"

    @pytest.mark.asyncio
    async def test_get_tool_by_name(self) -> None:
        """get_tool(name) returns the MCPToolAdapter for the named tool."""
        tool_schema = _make_tool_schema(name="write_file", description="Writes a file")
        list_tools_response = MagicMock()
        list_tools_response.tools = [tool_schema]

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=list_tools_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_transport_cm = AsyncMock()
        mock_transport_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        mock_transport_cm.__aexit__ = AsyncMock(return_value=False)

        client = MCPClient.stdio("npx")

        async def patched_connect(self_inner):
            self_inner._cm = mock_transport_cm
            await mock_transport_cm.__aenter__()
            self_inner._session = mock_session
            await mock_session.__aenter__()
            await mock_session.initialize()

        with patch.object(MCPClient, "_connect_stdio", patched_connect):
            await client.connect()

        adapter = client.get_tool("write_file")
        assert isinstance(adapter, MCPToolAdapter)
        assert adapter.name == "write_file"

    @pytest.mark.asyncio
    async def test_get_tool_missing_raises(self) -> None:
        """get_tool() raises ToolNotFoundError for an unknown tool name."""
        list_tools_response = MagicMock()
        list_tools_response.tools = []

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=list_tools_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_transport_cm = AsyncMock()
        mock_transport_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        mock_transport_cm.__aexit__ = AsyncMock(return_value=False)

        client = MCPClient.stdio("npx")

        async def patched_connect(self_inner):
            self_inner._cm = mock_transport_cm
            await mock_transport_cm.__aenter__()
            self_inner._session = mock_session
            await mock_session.__aenter__()
            await mock_session.initialize()

        with patch.object(MCPClient, "_connect_stdio", patched_connect):
            await client.connect()

        with pytest.raises(ToolNotFoundError):
            client.get_tool("nonexistent_tool")


# ---------------------------------------------------------------------------
# TestLoadMCPConfig
# ---------------------------------------------------------------------------


class TestLoadMCPConfig:
    """Tests for load_mcp_config() JSON config loader."""

    def test_load_missing_file_returns_empty(self) -> None:
        """load_mcp_config() with a nonexistent path returns []."""
        result = load_mcp_config("/tmp/does_not_exist_orchestra_mcp_test.json")
        assert result == []

    def test_load_stdio_config(self, tmp_path: Path) -> None:
        """Parses stdio server entries correctly, producing MCPClient instances."""
        config = {
            "mcpServers": {
                "filesystem": {
                    "command": "npx",
                    "args": ["@modelcontextprotocol/server-filesystem", "/"],
                    "transport": "stdio",
                    "timeout": 45.0,
                }
            }
        }
        config_file = tmp_path / "mcp.json"
        config_file.write_text(json.dumps(config))

        clients = load_mcp_config(str(config_file))

        assert len(clients) == 1
        client = clients[0]
        assert isinstance(client, MCPClient)
        assert client._transport == "stdio"
        assert client._command == "npx"
        assert client._args == ["@modelcontextprotocol/server-filesystem", "/"]
        assert client._timeout == 45.0

    def test_load_http_config(self, tmp_path: Path) -> None:
        """Parses HTTP server entries correctly."""
        config = {
            "mcpServers": {
                "remote": {
                    "url": "http://localhost:8080/mcp",
                    "transport": "http",
                    "headers": {"X-Custom": "value"},
                }
            }
        }
        config_file = tmp_path / "mcp.json"
        config_file.write_text(json.dumps(config))

        clients = load_mcp_config(str(config_file))

        assert len(clients) == 1
        client = clients[0]
        assert client._transport == "http"
        assert client._url == "http://localhost:8080/mcp"
        assert client._headers == {"X-Custom": "value"}

    def test_env_var_expansion(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Environment variable references in string values are expanded."""
        monkeypatch.setenv("MCP_SERVER_PATH", "/opt/mcp/server")
        config = {
            "mcpServers": {
                "my_server": {
                    "command": "python",
                    "args": ["$MCP_SERVER_PATH/main.py"],
                    "transport": "stdio",
                }
            }
        }
        config_file = tmp_path / "mcp.json"
        config_file.write_text(json.dumps(config))

        clients = load_mcp_config(str(config_file))

        assert len(clients) == 1
        assert clients[0]._args == ["/opt/mcp/server/main.py"]

    def test_load_multiple_servers(self, tmp_path: Path) -> None:
        """Multiple server entries produce multiple MCPClient instances."""
        config = {
            "mcpServers": {
                "server_a": {
                    "command": "npx",
                    "args": ["server-a"],
                    "transport": "stdio",
                },
                "server_b": {
                    "url": "http://localhost:9000/mcp",
                    "transport": "http",
                },
            }
        }
        config_file = tmp_path / "mcp.json"
        config_file.write_text(json.dumps(config))

        clients = load_mcp_config(str(config_file))

        assert len(clients) == 2
        transports = {c._transport for c in clients}
        assert transports == {"stdio", "http"}

    def test_load_unknown_transport_skipped(self, tmp_path: Path) -> None:
        """Server entries with unknown transport are skipped (logged as warning)."""
        config = {
            "mcpServers": {
                "weird": {
                    "transport": "websocket",
                    "url": "ws://localhost:1234",
                }
            }
        }
        config_file = tmp_path / "mcp.json"
        config_file.write_text(json.dumps(config))

        clients = load_mcp_config(str(config_file))

        assert clients == []

    def test_load_invalid_json_returns_empty(self, tmp_path: Path) -> None:
        """Malformed JSON in config file returns [] without raising."""
        config_file = tmp_path / "mcp.json"
        config_file.write_text("{ this is not valid json }")

        clients = load_mcp_config(str(config_file))

        assert clients == []
