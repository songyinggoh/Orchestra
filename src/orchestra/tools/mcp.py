"""MCP (Model Context Protocol) client integration for Orchestra.

Provides MCPClient for connecting to MCP servers via stdio or HTTP transports,
and MCPToolAdapter which wraps discovered MCP tools as Orchestra Tool protocol
implementations.

Usage:
    async with MCPClient.stdio("npx", ["@modelcontextprotocol/server-filesystem", "/"]) as client:
        tools = client.get_tools()
        result = await tools[0].execute({"path": "/"})
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, cast

from orchestra.core.context import ExecutionContext
from orchestra.core.errors import (
    MCPConnectionError,
    MCPTimeoutError,
    MCPToolError,
    ToolNotFoundError,
)
from orchestra.core.types import ToolResult

logger = logging.getLogger(__name__)


class MCPToolAdapter:
    """Wraps an MCP tool as an Orchestra Tool protocol implementation.

    Holds a reference to the live ClientSession and the tool schema discovered
    from the MCP server. Satisfies the Tool protocol via structural subtyping
    (no inheritance required).
    """

    def __init__(
        self,
        session: Any,  # mcp.ClientSession
        tool_schema: Any,  # mcp.types.Tool
        timeout: float = 30.0,
    ) -> None:
        self._session = session
        self._tool_schema = tool_schema
        self._timeout = timeout

    @property
    def name(self) -> str:
        return cast(str, self._tool_schema.name)

    @property
    def description(self) -> str:
        return self._tool_schema.description or ""

    @property
    def parameters_schema(self) -> dict[str, Any]:
        schema = self._tool_schema.inputSchema
        if isinstance(schema, dict):
            return schema
        # Pydantic model or similar — convert to dict
        try:
            return dict(schema)
        except Exception:
            return {"type": "object", "properties": {}}

    async def execute(
        self,
        arguments: dict[str, Any],
        *,
        context: ExecutionContext | None = None,
    ) -> ToolResult:
        """Execute the MCP tool by calling session.call_tool with a timeout."""
        try:
            raw = await asyncio.wait_for(
                self._session.call_tool(self.name, arguments),
                timeout=self._timeout,
            )
        except TimeoutError as exc:
            raise MCPTimeoutError(
                f"MCP tool '{self.name}' timed out after {self._timeout}s"
            ) from exc
        except Exception as exc:
            raise MCPToolError(f"MCP tool '{self.name}' call failed: {exc}") from exc

        # Handle MCP error response
        if getattr(raw, "isError", False):
            error_text = _extract_text(raw.content)
            return ToolResult(
                tool_call_id="",
                name=self.name,
                content="",
                error=error_text or "MCP tool returned an error",
            )

        # Extract text from content blocks
        str_result = _extract_text(raw.content)
        return ToolResult(
            tool_call_id="",
            name=self.name,
            content=str_result,
            error=None,
        )

    def __repr__(self) -> str:
        return f"MCPToolAdapter({self.name!r})"


def _extract_text(content_blocks: Any) -> str:
    """Extract text from MCP content blocks.

    Handles TextContent blocks. Image and resource content types are logged
    and skipped.
    # TODO: add image/resource content handling when use-cases emerge
    """
    if content_blocks is None:
        return ""

    parts: list[str] = []
    for block in content_blocks:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            parts.append(getattr(block, "text", ""))
        else:
            logger.debug(
                "MCP content block of type %r skipped (only 'text' is currently handled)",
                block_type,
            )
    return "".join(parts)


class MCPClient:
    """Client for connecting to MCP servers.

    Supports stdio and HTTP transports. Use the class-method factories to
    construct instances, then use as an async context manager or call
    connect()/disconnect() manually.

    Example (stdio):
        async with MCPClient.stdio("npx", ["@modelcontextprotocol/server-filesystem", "/"]) as c:
            tools = c.get_tools()

    Example (HTTP):
        async with MCPClient.http("http://localhost:8080/mcp") as c:
            tools = c.get_tools()
    """

    def __init__(
        self,
        transport: str,  # "stdio" | "http"
        *,
        command: str | None = None,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        url: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._transport = transport
        self._command = command
        self._args = args or []
        self._env = env
        self._url = url
        self._headers = headers or {}
        self._timeout = timeout

        self._session: Any = None
        self._cm: Any = None  # async context manager from transport helper
        self._tools: dict[str, MCPToolAdapter] = {}

    # ------------------------------------------------------------------
    # Factory class methods
    # ------------------------------------------------------------------

    @classmethod
    def stdio(
        cls,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> MCPClient:
        """Create an MCPClient that connects via stdio transport.

        Args:
            command: Executable to launch (e.g. "npx", "python").
            args: Command-line arguments passed to the executable.
            env: Extra environment variables for the subprocess. Merged with
                 the current process environment by the MCP SDK.
            timeout: Per-call timeout in seconds (also used for connect).
        """
        return cls(
            "stdio",
            command=command,
            args=args,
            env=env,
            timeout=timeout,
        )

    @classmethod
    def http(
        cls,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> MCPClient:
        """Create an MCPClient that connects via streamable HTTP transport.

        Args:
            url: Base URL of the MCP HTTP server (e.g. "http://localhost:8080/mcp").
            headers: Extra HTTP headers (e.g. Authorization).
            timeout: Per-call timeout in seconds.
        """
        return cls(
            "http",
            url=url,
            headers=headers,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Establish connection to the MCP server and run initial discovery."""
        try:
            if self._transport == "stdio":
                await self._connect_stdio()
            elif self._transport == "http":
                await self._connect_http()
            else:
                raise MCPConnectionError(f"Unknown transport: {self._transport!r}")
        except MCPConnectionError:
            raise
        except Exception as exc:
            raise MCPConnectionError(
                f"Failed to connect to MCP server ({self._transport}): {exc}"
            ) from exc

        await self.discover_tools()

    async def _connect_stdio(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=self._command,
            args=self._args,
            env=self._env,
        )
        self._cm = stdio_client(params)
        read, write = await self._cm.__aenter__()
        self._session = ClientSession(read, write)
        await self._session.__aenter__()
        await self._session.initialize()

    async def _connect_http(self) -> None:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        self._cm = streamablehttp_client(self._url, headers=self._headers)  # type: ignore[arg-type]
        read, write, _ = await self._cm.__aenter__()
        self._session = ClientSession(read, write)
        await self._session.__aenter__()
        await self._session.initialize()

    async def disconnect(self) -> None:
        """Cleanly close the MCP session and transport."""
        self._tools = {}
        if self._session is not None:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception:
                logger.debug("Error closing MCP session", exc_info=True)
            self._session = None
        if self._cm is not None:
            try:
                await self._cm.__aexit__(None, None, None)
            except Exception:
                logger.debug("Error closing MCP transport", exc_info=True)
            self._cm = None

    # ------------------------------------------------------------------
    # Tool discovery
    # ------------------------------------------------------------------

    async def discover_tools(self) -> None:
        """Query the MCP server for available tools and cache them."""
        if self._session is None:
            raise MCPConnectionError("Not connected. Call connect() first.")
        try:
            response = await asyncio.wait_for(
                self._session.list_tools(),
                timeout=self._timeout,
            )
        except TimeoutError as exc:
            raise MCPTimeoutError(f"list_tools() timed out after {self._timeout}s") from exc

        self._tools = {
            tool.name: MCPToolAdapter(self._session, tool, timeout=self._timeout)
            for tool in response.tools
        }
        logger.debug("MCP: discovered %d tools from server", len(self._tools))

    # ------------------------------------------------------------------
    # Tool accessors
    # ------------------------------------------------------------------

    def get_tools(self) -> list[MCPToolAdapter]:
        """Return all discovered tools as a list."""
        return list(self._tools.values())

    def get_tool(self, name: str) -> MCPToolAdapter:
        """Return a specific tool by name.

        Raises:
            ToolNotFoundError: If no tool with that name was discovered.
        """
        if name not in self._tools:
            available = list(self._tools.keys())
            raise ToolNotFoundError(
                f"MCP tool '{name}' not found. Available tools: {available}. "
                "Call discover_tools() again if the server's tool list changed."
            )
        return self._tools[name]

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> MCPClient:
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.disconnect()

    def __repr__(self) -> str:
        if self._transport == "stdio":
            return f"MCPClient(stdio, command={self._command!r})"
        return f"MCPClient(http, url={self._url!r})"


# ------------------------------------------------------------------
# Config loader
# ------------------------------------------------------------------


def load_mcp_config(config_path: str | Path | None = None) -> list[MCPClient]:
    """Load MCP server configuration from a JSON file (Claude Desktop format).

    Reads ``.orchestra/mcp.json`` by default (relative to cwd). Returns an
    empty list (never raises) when the file is missing.

    Config format example::

        {
            "mcpServers": {
                "filesystem": {
                    "command": "npx",
                    "args": ["@modelcontextprotocol/server-filesystem", "/"],
                    "transport": "stdio"
                },
                "remote": {
                    "url": "http://localhost:8080/mcp",
                    "transport": "http"
                }
            }
        }

    String values in args/env fields have environment variables expanded via
    ``os.path.expandvars``.

    Args:
        config_path: Path to the config JSON. Defaults to ``.orchestra/mcp.json``.

    Returns:
        List of configured (but not yet connected) MCPClient instances.
    """
    if config_path is None:
        config_path = Path.cwd() / ".orchestra" / "mcp.json"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        return []

    try:
        with config_path.open() as fh:
            raw = json.load(fh)
    except Exception as exc:
        logger.warning("Failed to load MCP config from %s: %s", config_path, exc)
        return []

    servers = raw.get("mcpServers", {})
    clients: list[MCPClient] = []

    for name, cfg in servers.items():
        transport = cfg.get("transport", "stdio")
        timeout = float(cfg.get("timeout", 30.0))

        try:
            if transport == "stdio":
                command = _expand(cfg.get("command", ""))
                args = [_expand(a) for a in cfg.get("args", [])]
                env_raw = cfg.get("env", {})
                env = {k: _expand(v) for k, v in env_raw.items()} if env_raw else None
                clients.append(MCPClient.stdio(command, args=args, env=env, timeout=timeout))

            elif transport == "http":
                url = _expand(cfg.get("url", ""))
                headers_raw = cfg.get("headers", {})
                headers = {k: _expand(v) for k, v in headers_raw.items()} if headers_raw else None
                clients.append(MCPClient.http(url, headers=headers, timeout=timeout))

            else:
                logger.warning("MCP server %r has unknown transport %r — skipped", name, transport)

        except Exception as exc:
            logger.warning("Failed to configure MCP server %r: %s — skipped", name, exc)

    return clients


def _expand(value: str) -> str:
    """Expand environment variables in a string value."""
    return os.path.expandvars(value)
