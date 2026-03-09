# Task 2.2: MCP Client Integration -- Detailed Execution Plan

**Phase:** 02-differentiation
**Task:** 2.2 (DIFF-08)
**Created:** 2026-03-08
**Status:** Ready for execution
**Estimated effort:** 2 subtasks across 2 waves

---

## Table of Contents

1. [Code Walkthrough: Existing Tool System Integration Points](#1-code-walkthrough-existing-tool-system-integration-points)
2. [Logic Errors and Design Gaps](#2-logic-errors-and-design-gaps)
3. [Resolved Design Decisions](#3-resolved-design-decisions)
4. [Subtask Breakdown](#4-subtask-breakdown)
5. [Dependency Graph](#5-dependency-graph)
6. [File Inventory](#6-file-inventory)
7. [Testing Strategy](#7-testing-strategy)

---

## 1. Code Walkthrough: Existing Tool System Integration Points

### 1.1 The Tool Protocol (protocols.py, lines 49-67)

```
Location: src/orchestra/core/protocols.py

@runtime_checkable
class Tool(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def description(self) -> str: ...
    @property
    def parameters_schema(self) -> dict[str, Any]: ...
    async def execute(
        self,
        arguments: dict[str, Any],
        *,
        context: ExecutionContext | None = None,
    ) -> ToolResult: ...
```

**Integration requirement:** `MCPToolAdapter` must implement all four members
(`name`, `description`, `parameters_schema`, `execute`) to satisfy this protocol.
Because the protocol is `@runtime_checkable`, the test `isinstance(adapter, Tool)`
works without inheritance -- structural subtyping only.

### 1.2 ToolWrapper as the Reference Implementation (base.py, lines 82-136)

```
Location: src/orchestra/tools/base.py

class ToolWrapper:
    def __init__(self, func, name=None, description=None) -> None
    @property name -> str
    @property description -> str
    @property parameters_schema -> dict[str, Any]  # JSON Schema object format
    async def execute(arguments, *, context=None) -> ToolResult
```

Key patterns for `MCPToolAdapter` to mirror:

1. `parameters_schema` returns a JSON Schema dict with `"type": "object"` at root
   and `"properties"` and optional `"required"` keys.
   MCP's `inputSchema` is already in this format -- direct pass-through, no
   conversion needed.

2. `execute()` returns `ToolResult(tool_call_id="", name=self.name, content=str(result))`.
   On error: `ToolResult(tool_call_id="", name=self.name, content="", error=str(e))`.
   MCPToolAdapter must use the same `ToolResult` fields.

3. On success, errors are surfaced via `ToolResult.error` (not raised as exceptions).
   MCP `result.isError` maps to this field.

### 1.3 ToolResult Shape (from core/types.py, referenced in base.py)

```python
ToolResult(
    tool_call_id="",          # Empty string for MCP tools (no LLM call_id context)
    name=self.name,           # Tool name -- must match exactly
    content=str(result),      # String content from MCP text blocks
    error=None,               # Set when result.isError is True
)
```

### 1.4 tools/__init__.py -- Current Exports

```
from orchestra.tools.base import ToolWrapper, tool
from orchestra.tools.registry import ToolRegistry
__all__ = ["ToolRegistry", "ToolWrapper", "tool"]
```

After this task: adds `MCPClient` and `MCPToolAdapter` to both imports and `__all__`.

### 1.5 errors.py -- Existing Error Hierarchy

```
OrchestraError
  ToolError
    ToolNotFoundError
    ToolTimeoutError        <-- existing timeout pattern (no server_name field)
    ToolPermissionError
    ToolExecutionError      <-- existing execution failure pattern
```

The MCP errors do NOT subclass `ToolError`. They subclass `OrchestraError` directly
via a new `MCPError` branch. This preserves the conceptual distinction: `ToolError`
means "the tool failed to run", `MCPError` means "the MCP transport or server failed".
An agent's tool-calling loop catches `ToolError`; infrastructure code catches `MCPError`.

### 1.6 How Agents Consume Tools (agent.py pattern)

Agents hold `self.tools: list[Tool]`. During the tool-calling loop, the agent:
1. Calls `tool.name` and `tool.parameters_schema` to build the LLM tool list.
2. Calls `await tool.execute(arguments, context=context)` to invoke.
3. Reads `tool_result.content` and `tool_result.error`.

`MCPToolAdapter` slots in at step 1-3 without any agent code changes. The adapter
is indistinguishable from a `ToolWrapper` to the agent loop.

---

## 2. Logic Errors and Design Gaps

### Gap 1: PLAN.md spec shows custom transports; research shows mcp SDK handles transport

**Problem:** PLAN.md task 2.1 shows `MCPTransport` protocol, `StdioTransport`, and
`StreamableHTTPTransport` as custom classes with manual JSON-RPC. The research document
(section 2-4) clarifies that the `mcp` Python SDK (`mcp>=1.26,<2`) already provides
`stdio_client`, `streamablehttp_client`, and `ClientSession` -- these handle all
JSON-RPC framing, initialization, and capability negotiation internally.

**Resolution:** Do NOT implement raw JSON-RPC transport classes. Use the SDK:
```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
```
`MCPClient` wraps `ClientSession` as a context manager. Transport selection is an
implementation detail inside `MCPClient.__aenter__` based on whether a URL or command
was provided. The `MCPTransport` protocol in PLAN.md is superseded by the SDK's
transport context managers.

### Gap 2: PLAN.md uses "servers" key; research shows Claude Desktop uses "mcpServers" key

**Problem:** PLAN.md config format uses `{ "servers": [...] }` (array). Research
section 6 shows Claude Desktop uses `{ "mcpServers": { "name": {...} } }` (object/dict).

**Resolution:** Use Claude Desktop format (`mcpServers` object keyed by server name)
for copy-paste compatibility. This is explicitly stated as a design goal in
RESEARCH-mcp.md section 6: "Match Claude Desktop format for copy-paste compatibility."

Config discriminant: entry has `url` key -> HTTP transport; entry has `command` key ->
stdio transport.

### Gap 3: MCPToolAdapter holds `ClientSession` reference, not `MCPClient` reference

**Problem:** PLAN.md task 2.1 shows `MCPToolAdapter.__init__(self, client: MCPClient, ...)`.
Research section 5 shows `MCPToolAdapter.__init__(self, session: ClientSession, ...)`.
The session is the actual object that has `call_tool()`.

**Resolution:** `MCPToolAdapter` holds the `ClientSession` directly (not `MCPClient`).
`MCPClient` is responsible for managing the session lifecycle and creating adapters.
`MCPClient.get_tools()` creates `MCPToolAdapter(session=self._session, tool_info=t)`
for each discovered tool. This keeps `MCPToolAdapter` decoupled from connection concerns.

### Gap 4: `ToolResult.content` is string-only; MCP can return structured content

**Problem:** MCP tools can return `structuredContent` (JSON object) and non-text
content (images as base64). `ToolResult.content` is a `str` field.

**Resolution (for Phase 2 scope):** Extract only text blocks from `result.content`:
```python
content = "\n".join(
    block.text for block in result.content
    if hasattr(block, "text")
)
```
Structured/image content is silently omitted. This is acceptable for Phase 2 --
structured content support is deferred per research section 8. Document this
limitation with a `# TODO(Phase 3): handle structuredContent` comment.

### Gap 5: `_jsonrpc_request` / `_jsonrpc_notification` helpers are unused

**Problem:** PLAN.md mentions these JSON-RPC helper functions. Since we use the
`mcp` SDK, these are never needed -- the SDK constructs all JSON-RPC messages
internally.

**Resolution:** Do not implement these helpers. They have no callers when using
the SDK correctly.

### Gap 6: No `get_tool(name)` method on `MCPClient`

**Problem:** Research section 6 shows `mcp.get_tool("read_file")` usage pattern
in the code-first API example. PLAN.md does not list this method.

**Resolution:** Add `get_tool(name: str) -> MCPToolAdapter` to `MCPClient`. Raises
`ToolNotFoundError` (from `orchestra.core.errors`) if the tool name is not in the
discovered set. This makes agent code ergonomic without requiring the caller to
filter `get_tools()`.

### Gap 7: Environment variable expansion in config

**Problem:** Research section 6 shows `"Authorization": "Bearer ${MCP_API_KEY}"` in
config headers. This must be expanded before use.

**Resolution:** `load_mcp_config()` expands `${VAR}` patterns using `os.path.expandvars()`
on all string values in `headers` and `env` dicts. Unexpanded variables (env var not
set) are left as-is and a warning is logged via structlog.

---

## 3. Resolved Design Decisions

| Decision | Chosen Approach | Rationale |
|---|---|---|
| Transport implementation | Use `mcp` SDK (`stdio_client`, `streamablehttp_client`) | SDK handles JSON-RPC, framing, capability negotiation; no raw socket code needed |
| MCPClient transport selection | Auto-detect: `url` key → HTTP, `command` key → stdio; explicit factory methods `MCPClient.stdio()` and `MCPClient.http()` | Ergonomic for code-first use, config-compatible |
| MCPToolAdapter holds session or client | Holds `ClientSession` directly | Session is the API surface for tool calls; client manages lifecycle separately |
| Config file format | Claude Desktop format: `{ "mcpServers": { "name": {...} } }` | Copy-paste compatibility is explicit design goal |
| Structured content handling | Extract text blocks only, skip image/structured | Phase 2 scope; documented TODO for Phase 3 |
| `MCPError` hierarchy placement | Subclass `OrchestraError` directly, NOT `ToolError` | Conceptual distinction: transport failures vs tool execution failures |
| `MCPTimeoutError` vs `ToolTimeoutError` | Use `MCPTimeoutError` for server timeouts | Timeout is at MCP session level, not at tool-call level; different recovery path |
| `get_tool(name)` method | Add to `MCPClient` | Ergonomic single-tool access; raises `ToolNotFoundError` for clear error messages |
| Env var expansion | `os.path.expandvars()` on header/env string values | Standard Python pattern; matches Claude Desktop behavior |
| SDK version pin | `mcp>=1.26,<2` in `pyproject.toml` | v2 is pre-alpha with breaking changes; pin protects against accidental upgrade |
| SSE transport | Not implemented | Deprecated as of 2025-03-26; Streamable HTTP is the current spec |
| Session lifecycle | `AsyncExitStack` inside `MCPClient.__aenter__` | Cleanly manages both transport and session context managers; proper teardown |
| Tool discovery timing | Eager on `connect()` / `__aenter__` | Tools available immediately after context manager entry; no lazy-load complexity |

---

## 4. Subtask Breakdown

### Subtask 2.2.1 — MCP Client Implementation

**Wave:** 1
**Files created:** `src/orchestra/tools/mcp.py`
**Files modified:** `src/orchestra/core/errors.py`, `src/orchestra/tools/__init__.py`, `pyproject.toml`

#### 4.1.1 Modify `src/orchestra/core/errors.py`

Append the MCP error hierarchy after the existing `# --- Persistence Errors ---` block:

```python
# --- MCP Errors ---


class MCPError(OrchestraError):
    """Base for MCP (Model Context Protocol) errors.

    What: An MCP server interaction failed.
    Where: MCPClient or MCPToolAdapter in orchestra.tools.mcp.
    Fix: Check server is running, transport config is correct, and mcp>=1.26 is installed.
    """


class MCPConnectionError(MCPError):
    """Raised when MCP server connection or initialization fails.

    What: Could not establish a session with the MCP server.
    Where: MCPClient.__aenter__ or MCPClient.connect().
    Fix: Verify the command/URL is correct and the server process starts successfully.
    """


class MCPToolError(MCPError):
    """Raised when an MCP tool call returns an error result.

    What: The MCP server executed the tool but returned isError=True.
    Where: MCPToolAdapter.execute().
    Fix: Check tool arguments match the tool's inputSchema; inspect server logs.
    """


class MCPTimeoutError(MCPError):
    """Raised when an MCP server does not respond within the configured timeout.

    What: tools/list or tools/call exceeded the timeout threshold.
    Where: MCPClient.discover_tools() or MCPClient.call_tool().
    Fix: Increase timeout parameter or check server health.
    """
```

#### 4.1.2 Create `src/orchestra/tools/mcp.py`

Full module structure with all public symbols:

```python
"""MCP (Model Context Protocol) client integration for Orchestra.

Connects to MCP servers via stdio subprocess or Streamable HTTP.
MCP tools are adapted to satisfy Orchestra's Tool protocol -- agents
cannot distinguish MCPToolAdapter from ToolWrapper.

Usage (stdio):
    async with MCPClient.stdio("npx", ["-y", "@modelcontextprotocol/server-filesystem", "/path"]) as mcp:
        tools = mcp.get_tools()   # list[MCPToolAdapter], usable as Tool protocol
        agent = BaseAgent(name="researcher", tools=tools)

Usage (HTTP):
    async with MCPClient.http("http://localhost:8080/mcp", headers={"Authorization": "Bearer ..."}) as mcp:
        tool = mcp.get_tool("read_file")   # raises ToolNotFoundError if not found

Usage (config file):
    servers = load_mcp_config()   # reads .orchestra/mcp.json
    # returns list[dict] with keys: name, transport, command/url, args, env, headers
"""
```

**Imports:**

```python
from __future__ import annotations

import json
import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import structlog
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from orchestra.core.context import ExecutionContext
from orchestra.core.errors import MCPConnectionError, MCPTimeoutError, MCPToolError, ToolNotFoundError
from orchestra.core.types import ToolResult

log = structlog.get_logger(__name__)
```

**`MCPToolAdapter` class:**

```python
class MCPToolAdapter:
    """Adapts an MCP tool to Orchestra's Tool protocol.

    Agents cannot distinguish MCPToolAdapter from ToolWrapper.
    Holds a reference to the active ClientSession; do not use after
    the parent MCPClient context manager exits.
    """

    def __init__(self, session: ClientSession, tool_info: Any) -> None:
        # tool_info is mcp.types.Tool (has .name, .description, .inputSchema)
        self._session = session
        self._tool_info = tool_info

    @property
    def name(self) -> str:
        return self._tool_info.name

    @property
    def description(self) -> str:
        return self._tool_info.description or ""

    @property
    def parameters_schema(self) -> dict[str, Any]:
        # MCP inputSchema is already JSON Schema with "type": "object" at root.
        # Direct pass-through -- no conversion needed.
        schema = self._tool_info.inputSchema
        if schema is None:
            return {"type": "object", "properties": {}}
        # inputSchema may be a dict or a Pydantic model depending on mcp SDK version
        if hasattr(schema, "model_dump"):
            return schema.model_dump()
        return dict(schema)

    async def execute(
        self,
        arguments: dict[str, Any],
        *,
        context: ExecutionContext | None = None,
    ) -> ToolResult:
        """Execute MCP tool via tools/call. Returns ToolResult identical to ToolWrapper output."""
        try:
            result = await self._session.call_tool(self.name, arguments)
        except TimeoutError as exc:
            raise MCPTimeoutError(
                f"MCP tool '{self.name}' timed out. "
                "Increase timeout on MCPClient or check server health."
            ) from exc
        except Exception as exc:
            raise MCPToolError(
                f"MCP tool '{self.name}' invocation failed: {exc}. "
                "Check tool arguments match the inputSchema and inspect server logs."
            ) from exc

        # Extract text blocks only. Structured/image content is omitted.
        # TODO(Phase 3): handle structuredContent and image blocks.
        content = "\n".join(
            block.text
            for block in result.content
            if hasattr(block, "text")
        )

        if result.isError:
            return ToolResult(
                tool_call_id="",
                name=self.name,
                content=content,
                error=content or f"MCP tool '{self.name}' returned an error result.",
            )

        return ToolResult(
            tool_call_id="",
            name=self.name,
            content=content,
        )

    def __repr__(self) -> str:
        return f"MCPTool({self.name!r})"
```

**`MCPClient` class:**

```python
class MCPClient:
    """Client for MCP (Model Context Protocol) servers.

    Discovers tools via tools/list on connect, invokes via tools/call.
    Adapted tools are indistinguishable from @tool-decorated Orchestra tools.

    Use as an async context manager:

        async with MCPClient.stdio("npx", ["-y", "@modelcontextprotocol/server-filesystem"]) as mcp:
            tools = mcp.get_tools()

    Or with AsyncExitStack for multiple servers:

        async with AsyncExitStack() as stack:
            fs  = await stack.enter_async_context(MCPClient.stdio("npx", [...]))
            api = await stack.enter_async_context(MCPClient.http("https://api.example.com/mcp"))
    """

    def __init__(
        self,
        *,
        command: str | None = None,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        url: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        if command is None and url is None:
            raise ValueError("MCPClient requires either 'command' (stdio) or 'url' (HTTP).")
        if command is not None and url is not None:
            raise ValueError("MCPClient: provide 'command' OR 'url', not both.")

        self._command = command
        self._args = args or []
        self._env = env
        self._url = url
        self._headers = headers or {}
        self._timeout = timeout

        self._session: ClientSession | None = None
        self._tools: list[MCPToolAdapter] = []
        self._exit_stack: AsyncExitStack | None = None

    # --- Factory methods (ergonomic code-first API) ---

    @classmethod
    def stdio(
        cls,
        command: str,
        args: list[str] | None = None,
        *,
        env: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> MCPClient:
        """Create an MCPClient using stdio transport (subprocess)."""
        return cls(command=command, args=args, env=env, timeout=timeout)

    @classmethod
    def http(
        cls,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> MCPClient:
        """Create an MCPClient using Streamable HTTP transport."""
        return cls(url=url, headers=headers, timeout=timeout)

    # --- Context manager ---

    async def __aenter__(self) -> MCPClient:
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.disconnect()

    # --- Lifecycle ---

    async def connect(self) -> None:
        """Open transport, initialize MCP session, discover tools.

        Raises MCPConnectionError if the server cannot be reached or
        initialization fails.
        """
        self._exit_stack = AsyncExitStack()
        try:
            if self._command is not None:
                params = StdioServerParameters(
                    command=self._command,
                    args=self._args,
                    env=self._env,
                )
                read_stream, write_stream = await self._exit_stack.enter_async_context(
                    stdio_client(params)
                )
            else:
                assert self._url is not None
                read_stream, write_stream = await self._exit_stack.enter_async_context(
                    streamablehttp_client(self._url, headers=self._headers)
                )

            session = await self._exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await session.initialize()
            self._session = session

            await self.discover_tools()
            log.info(
                "mcp.connected",
                server=self._command or self._url,
                tool_count=len(self._tools),
            )
        except Exception as exc:
            await self._exit_stack.aclose()
            self._exit_stack = None
            raise MCPConnectionError(
                f"Failed to connect to MCP server "
                f"'{self._command or self._url}': {exc}. "
                "Check the command/URL and ensure the server process starts correctly."
            ) from exc

    async def disconnect(self) -> None:
        """Gracefully close the MCP session and transport."""
        self._tools = []
        self._session = None
        if self._exit_stack is not None:
            await self._exit_stack.aclose()
            self._exit_stack = None
        log.info("mcp.disconnected", server=self._command or self._url)

    # --- Tool discovery ---

    async def discover_tools(self) -> list[dict[str, Any]]:
        """Send tools/list request; populate internal tool list.

        Returns raw tool schema dicts for inspection. Prefer get_tools()
        for MCPToolAdapter instances.
        """
        if self._session is None:
            raise MCPConnectionError(
                "MCPClient not connected. Call connect() or use as async context manager."
            )
        response = await self._session.list_tools()
        self._tools = [
            MCPToolAdapter(self._session, t) for t in response.tools
        ]
        # Return raw dicts for callers that want the raw schema
        return [
            {
                "name": t.name,
                "description": t.description or "",
                "inputSchema": (
                    t.inputSchema.model_dump()
                    if hasattr(t.inputSchema, "model_dump")
                    else dict(t.inputSchema or {})
                ),
            }
            for t in response.tools
        ]

    # --- Tool access ---

    def get_tools(self) -> list[MCPToolAdapter]:
        """Return all discovered tools as Orchestra-compatible adapters.

        Returns an empty list if connect() has not been called yet.
        Tools are valid only while the MCPClient context manager is active.
        """
        return list(self._tools)

    def get_tool(self, name: str) -> MCPToolAdapter:
        """Return a single tool by name.

        Raises ToolNotFoundError if no tool with that name was discovered.
        """
        for t in self._tools:
            if t.name == name:
                return t
        available = [t.name for t in self._tools]
        raise ToolNotFoundError(
            f"MCP tool '{name}' not found on server '{self._command or self._url}'. "
            f"Available tools: {available}. "
            "Call discover_tools() again if the server's tool list changed."
        )

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Low-level tool call returning the raw MCP result object.

        Prefer MCPToolAdapter.execute() for Orchestra-compatible ToolResult.
        """
        if self._session is None:
            raise MCPConnectionError("MCPClient not connected.")
        return await self._session.call_tool(name, arguments)

    def __repr__(self) -> str:
        server = self._command or self._url
        status = "connected" if self._session is not None else "disconnected"
        return f"MCPClient({server!r}, {status}, tools={len(self._tools)})"
```

**Config loader:**

```python
def load_mcp_config(config_path: str | None = None) -> list[dict[str, Any]]:
    """Load MCP server configs from .orchestra/mcp.json.

    Returns a list of server config dicts. Each dict has:
      - name (str): server name key from mcpServers
      - transport ("stdio" | "http"): derived from presence of "command" vs "url"
      - command (str, stdio only): executable
      - args (list[str], stdio only): arguments
      - env (dict[str, str] | None, stdio only): env vars (${VAR} expanded)
      - url (str, http only): endpoint URL
      - headers (dict[str, str], http only): HTTP headers (${VAR} expanded)

    Format (.orchestra/mcp.json) -- Claude Desktop compatible:
    {
      "mcpServers": {
        "filesystem": {
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"],
          "env": {}
        },
        "remote-api": {
          "url": "http://localhost:8080/mcp",
          "headers": {"Authorization": "Bearer ${MCP_API_KEY}"}
        }
      }
    }

    Returns [] if config file does not exist (no error -- config is optional).
    """
    if config_path is None:
        config_path = str(Path(".orchestra") / "mcp.json")

    path = Path(config_path)
    if not path.exists():
        log.debug("mcp.config_not_found", path=str(path))
        return []

    with path.open() as f:
        data = json.load(f)

    servers_raw: dict[str, Any] = data.get("mcpServers", {})
    servers: list[dict[str, Any]] = []

    for name, cfg in servers_raw.items():
        if "url" in cfg:
            headers = {
                k: os.path.expandvars(v) if isinstance(v, str) else v
                for k, v in cfg.get("headers", {}).items()
            }
            servers.append({
                "name": name,
                "transport": "http",
                "url": cfg["url"],
                "headers": headers,
            })
        elif "command" in cfg:
            env = cfg.get("env") or {}
            expanded_env = {
                k: os.path.expandvars(v) if isinstance(v, str) else v
                for k, v in env.items()
            } or None
            servers.append({
                "name": name,
                "transport": "stdio",
                "command": cfg["command"],
                "args": cfg.get("args", []),
                "env": expanded_env,
            })
        else:
            log.warning(
                "mcp.config_invalid_entry",
                name=name,
                reason="Entry has neither 'command' nor 'url'; skipping.",
            )

    log.info("mcp.config_loaded", path=str(path), server_count=len(servers))
    return servers
```

**Public exports at module level:**

```python
__all__ = [
    "MCPClient",
    "MCPToolAdapter",
    "load_mcp_config",
]
```

#### 4.1.3 Modify `src/orchestra/tools/__init__.py`

```python
"""Orchestra tool system."""

from orchestra.tools.base import ToolWrapper, tool
from orchestra.tools.mcp import MCPClient, MCPToolAdapter, load_mcp_config
from orchestra.tools.registry import ToolRegistry

__all__ = [
    "MCPClient",
    "MCPToolAdapter",
    "ToolRegistry",
    "ToolWrapper",
    "load_mcp_config",
    "tool",
]
```

#### 4.1.4 Modify `pyproject.toml`

Add to `[project.dependencies]`:
```toml
"mcp>=1.26,<2",
```

**Verify (Subtask 2.2.1):**

```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -c "
from orchestra.tools.mcp import MCPClient, MCPToolAdapter, load_mcp_config
from orchestra.tools import MCPClient, MCPToolAdapter
from orchestra.core.errors import MCPError, MCPConnectionError, MCPToolError, MCPTimeoutError
from orchestra.core.protocols import Tool
print('All imports OK')
print('MCPToolAdapter satisfies Tool protocol (structural):', issubclass(MCPToolAdapter, object))
"
```

Additional protocol conformance check:
```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -c "
from orchestra.core.protocols import Tool
from orchestra.tools.mcp import MCPToolAdapter, MCPClient
import inspect
# Verify all required protocol members are present on MCPToolAdapter
required = ['name', 'description', 'parameters_schema', 'execute']
missing = [m for m in required if not hasattr(MCPToolAdapter, m)]
assert not missing, f'MCPToolAdapter missing Tool protocol members: {missing}'
print('Protocol conformance OK, missing nothing:', missing)
print('execute is coroutine function:', inspect.iscoroutinefunction(MCPToolAdapter.execute))
"
```

**Done:** Module imports without errors. `MCPToolAdapter` has all four `Tool` protocol members. Error hierarchy is importable. `tools/__init__.py` exports `MCPClient` and `MCPToolAdapter`.

---

### Subtask 2.2.2 — Tests with Mock Server

**Wave:** 2
**Depends on:** Subtask 2.2.1
**Files created:** `tests/unit/test_mcp.py`

#### 4.2.1 MockMCPServer Design

The test suite uses `unittest.mock.AsyncMock` and `unittest.mock.MagicMock` to patch
`mcp.client.stdio.stdio_client` and `mcp.client.streamable_http.streamablehttp_client`.

A `MockMCPServer` helper class provides canned `list_tools` and `call_tool` responses
by building mock `ClientSession` objects that return pre-configured data.

```python
class MockMCPServer:
    """Builds a mock ClientSession that responds with configured tools.

    Provides a context manager that yields (read_stream, write_stream)
    usable as the transport mock, and a pre-initialized session.
    """

    def __init__(self, tools: list[dict[str, Any]]) -> None:
        self.tools = tools  # raw schema dicts: {name, description, inputSchema}
        self._call_results: dict[str, Any] = {}  # name -> result override
        self._call_errors: set[str] = set()      # names that should return isError=True

    def add_call_result(self, tool_name: str, content: str) -> None:
        self._call_results[tool_name] = content

    def add_call_error(self, tool_name: str, error_message: str) -> None:
        self._call_errors.add(tool_name)
        self._call_results[tool_name] = error_message

    def make_session(self) -> AsyncMock:
        """Return a fully configured mock ClientSession."""
        ...
```

Tests patch `MCPClient.connect` at the session level using `mock.patch.object` or
patch the transport context managers. The safest approach for unit tests is to patch
`ClientSession` directly to avoid spawning actual subprocesses.

#### 4.2.2 Test Inventory (minimum 10 tests)

```python
# tests/unit/test_mcp.py

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from orchestra.tools.mcp import MCPClient, MCPToolAdapter, load_mcp_config
from orchestra.core.protocols import Tool
from orchestra.core.errors import (
    MCPConnectionError, MCPToolError, MCPTimeoutError, ToolNotFoundError
)
from orchestra.core.types import ToolResult
```

**Test 1: `test_mcp_tool_adapter_satisfies_tool_protocol`**
```python
# Build MCPToolAdapter with a mock session and tool_info
# Assert: isinstance(adapter, Tool) is True
# Rationale: @runtime_checkable protocol check; most critical contract
```

**Test 2: `test_mcp_tool_adapter_properties`**
```python
# Build adapter with tool_info having name="read_file", description="Read a file",
#   inputSchema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
# Assert: adapter.name == "read_file"
# Assert: adapter.description == "Read a file"
# Assert: adapter.parameters_schema == {"type": "object", ...}
```

**Test 3: `test_mcp_tool_adapter_execute_returns_tool_result`**
```python
# Mock session.call_tool to return a result with content=[TextContent(text="file contents")]
#   and isError=False
# Call: result = await adapter.execute({"path": "/tmp/test.txt"})
# Assert: isinstance(result, ToolResult)
# Assert: result.content == "file contents"
# Assert: result.error is None
```

**Test 4: `test_mcp_tool_adapter_execute_error_result`**
```python
# Mock session.call_tool to return result with isError=True and content=[TextContent(text="permission denied")]
# Call: result = await adapter.execute({"path": "/etc/shadow"})
# Assert: result.error == "permission denied"
# Assert: result.content == "permission denied"
```

**Test 5: `test_mcp_tool_adapter_execute_timeout`**
```python
# Mock session.call_tool to raise TimeoutError
# Call: await adapter.execute({})
# Assert: raises MCPTimeoutError
```

**Test 6: `test_mcp_tool_adapter_execute_exception`**
```python
# Mock session.call_tool to raise RuntimeError("server crashed")
# Call: await adapter.execute({})
# Assert: raises MCPToolError
# Assert: "server crashed" in str(exc)
```

**Test 7: `test_mcpclient_get_tools_returns_adapters`**
```python
# Patch MCPClient.connect() to set self._session = mock_session
# Patch mock_session.list_tools() to return two tool schemas
# Call: async with MCPClient.stdio("npx", []) as mcp:
#           tools = mcp.get_tools()
# Assert: len(tools) == 2
# Assert: all(isinstance(t, MCPToolAdapter) for t in tools)
```

**Test 8: `test_mcpclient_get_tool_by_name`**
```python
# Same setup as test 7 with tools "read_file" and "write_file"
# Assert: mcp.get_tool("read_file").name == "read_file"
# Assert: raises ToolNotFoundError for mcp.get_tool("nonexistent")
```

**Test 9: `test_mcpclient_connection_error`**
```python
# Patch stdio_client context manager to raise OSError("command not found")
# Call: async with MCPClient.stdio("nonexistent-command") as mcp: pass
# Assert: raises MCPConnectionError
# Assert: "nonexistent-command" in str(exc)
```

**Test 10: `test_mcpclient_disconnect_clears_tools`**
```python
# Build connected MCPClient with two tools
# Call: await mcp.disconnect()
# Assert: mcp.get_tools() == []
# Assert: mcp._session is None
```

**Test 11: `test_mcpclient_http_factory`**
```python
# Call: client = MCPClient.http("http://localhost:8080/mcp", headers={"Authorization": "Bearer test"})
# Assert: client._url == "http://localhost:8080/mcp"
# Assert: client._headers == {"Authorization": "Bearer test"}
# Assert: client._command is None
```

**Test 12: `test_load_mcp_config_not_found`**
```python
# Call: result = load_mcp_config("/nonexistent/path/mcp.json")
# Assert: result == []  (returns empty list, does not raise)
```

**Test 13: `test_load_mcp_config_stdio_entry`**
```python
# Write a temp .orchestra/mcp.json with mcpServers containing a stdio entry
# Call: result = load_mcp_config(str(tmp_path / "mcp.json"))
# Assert: result[0]["transport"] == "stdio"
# Assert: result[0]["command"] == "npx"
# Assert: result[0]["args"] == ["-y", "@modelcontextprotocol/server-filesystem"]
```

**Test 14: `test_load_mcp_config_http_entry_with_env_expansion`**
```python
# Set os.environ["MCP_TOKEN"] = "secret-value"
# Write temp mcp.json with headers: {"Authorization": "Bearer ${MCP_TOKEN}"}
# Assert: result[0]["headers"]["Authorization"] == "Bearer secret-value"
```

**Test 15: `test_mcp_tool_adapter_empty_inputschema`**
```python
# Build adapter with tool_info.inputSchema = None
# Assert: adapter.parameters_schema == {"type": "object", "properties": {}}
# Rationale: guards against None from optional MCP server implementations
```

**Verify (Subtask 2.2.2):**

```bash
cd "C:/Users/user/Desktop/multi-agent orchestration framework" && python -m pytest tests/unit/test_mcp.py -v --tb=short
```

Expected output:
```
tests/unit/test_mcp.py::test_mcp_tool_adapter_satisfies_tool_protocol PASSED
tests/unit/test_mcp.py::test_mcp_tool_adapter_properties PASSED
tests/unit/test_mcp.py::test_mcp_tool_adapter_execute_returns_tool_result PASSED
tests/unit/test_mcp.py::test_mcp_tool_adapter_execute_error_result PASSED
tests/unit/test_mcp.py::test_mcp_tool_adapter_execute_timeout PASSED
tests/unit/test_mcp.py::test_mcp_tool_adapter_execute_exception PASSED
tests/unit/test_mcp.py::test_mcpclient_get_tools_returns_adapters PASSED
tests/unit/test_mcp.py::test_mcpclient_get_tool_by_name PASSED
tests/unit/test_mcp.py::test_mcpclient_connection_error PASSED
tests/unit/test_mcp.py::test_mcpclient_disconnect_clears_tools PASSED
tests/unit/test_mcp.py::test_mcpclient_http_factory PASSED
tests/unit/test_mcp.py::test_load_mcp_config_not_found PASSED
tests/unit/test_mcp.py::test_load_mcp_config_stdio_entry PASSED
tests/unit/test_mcp.py::test_load_mcp_config_http_entry_with_env_expansion PASSED
tests/unit/test_mcp.py::test_mcp_tool_adapter_empty_inputschema PASSED

15 passed in X.XXs
```

**Done:** All 15 tests pass. `MCPToolAdapter` satisfies `Tool` protocol. Error hierarchy is tested. Config loading tested with env var expansion.

---

## 5. Dependency Graph

```
Subtask 2.2.1: MCP client implementation
  Needs:
    - src/orchestra/core/errors.py (read, then extend with MCPError hierarchy)
    - src/orchestra/tools/__init__.py (read, then update exports)
    - src/orchestra/core/protocols.py (Tool protocol -- read only, no modification)
    - src/orchestra/core/types.py (ToolResult -- read only, no modification)
    - pyproject.toml (add mcp dependency)
  Creates:
    - src/orchestra/tools/mcp.py (new file)
  Modifies:
    - src/orchestra/core/errors.py (append MCP error classes)
    - src/orchestra/tools/__init__.py (add MCPClient, MCPToolAdapter to exports)
    - pyproject.toml (add mcp>=1.26,<2 dependency)

Subtask 2.2.2: Tests
  Needs:
    - src/orchestra/tools/mcp.py (created in 2.2.1)
    - src/orchestra/core/errors.py (MCPError hierarchy from 2.2.1)
    - src/orchestra/core/protocols.py (Tool -- for isinstance assertion)
    - src/orchestra/core/types.py (ToolResult -- for isinstance assertion)
  Creates:
    - tests/unit/test_mcp.py (new file)

Wave structure:
  Wave 1: Subtask 2.2.1  (no blocking dependencies)
  Wave 2: Subtask 2.2.2  (depends on Wave 1 output)

Parallel opportunity:
  None within this plan -- tests depend on the implementation.
  This plan (Wave 1 in phase) can run in parallel with other Phase 2 Wave 1 plans
  (DIFF-01 persistence, DIFF-10 providers) since file ownership does not overlap.
```

**File ownership -- no conflicts with other Phase 2 plans:**

| File | This Plan | PLAN-2.1 (persistence) | PLAN-2.3 (providers) |
|---|---|---|---|
| `src/orchestra/tools/mcp.py` | Creates | -- | -- |
| `src/orchestra/core/errors.py` | Modifies (append) | Modifies (append) | -- |
| `src/orchestra/tools/__init__.py` | Modifies | -- | -- |
| `tests/unit/test_mcp.py` | Creates | -- | -- |

**Note on `errors.py` conflict:** Both PLAN-2.1 and PLAN-2.2 append to `errors.py`.
These are independent appends to different sections. If both plans run in the same
wave, sequence them: run 2.1 error additions first (persistence errors), then 2.2
error additions (MCP errors). The file is small enough that a sequential read-modify-
write is safe. Alternatively, the executor can combine both appends in one write if
running both plans in the same session.

---

## 6. File Inventory

### Created (new files)

| File | Purpose | Lines (estimate) |
|---|---|---|
| `src/orchestra/tools/mcp.py` | MCPClient, MCPToolAdapter, load_mcp_config | ~250 |
| `tests/unit/test_mcp.py` | 15 unit tests with mock session | ~300 |

### Modified (existing files)

| File | Change | Impact |
|---|---|---|
| `src/orchestra/core/errors.py` | Append 4 MCP error classes after persistence errors | +28 lines |
| `src/orchestra/tools/__init__.py` | Add MCPClient, MCPToolAdapter, load_mcp_config to imports + `__all__` | +4 lines |
| `pyproject.toml` | Add `mcp>=1.26,<2` to `[project.dependencies]` | +1 line |

### Not modified

| File | Reason |
|---|---|
| `src/orchestra/core/protocols.py` | Tool protocol already satisfies MCPToolAdapter contract -- no changes needed |
| `src/orchestra/core/types.py` | ToolResult shape is already correct -- no changes needed |
| `src/orchestra/tools/base.py` | ToolWrapper is the reference, not modified |
| `src/orchestra/tools/registry.py` | MCPToolAdapter can be registered here by callers; no changes needed for this plan |

---

## 7. Testing Strategy

### Mock Boundary Decision

**Choice: Mock `ClientSession` directly (not the transport context managers).**

Rationale:
- The `mcp` SDK internals (JSON-RPC framing, subprocess management) are not under
  test here. We test Orchestra's adapter layer.
- Patching `ClientSession.list_tools` and `ClientSession.call_tool` is stable against
  internal SDK changes.
- No subprocess is spawned; tests are fast and deterministic.

Avoid: patching `stdio_client` / `streamablehttp_client` context managers directly.
These are complex async context managers that are fragile to mock correctly.
Instead, patch at the `MCPClient.connect()` level by replacing `self._session` with
a configured mock before `discover_tools()` runs.

**Recommended mock pattern:**

```python
@pytest.fixture
def mock_session():
    session = AsyncMock(spec=ClientSession)
    session.initialize = AsyncMock()
    # list_tools returns an object with .tools list
    tool_response = MagicMock()
    tool_response.tools = []  # override per-test
    session.list_tools = AsyncMock(return_value=tool_response)
    return session

@pytest.fixture
def make_tool_info():
    def _make(name: str, description: str = "", input_schema: dict | None = None):
        info = MagicMock()
        info.name = name
        info.description = description
        info.inputSchema = input_schema or {"type": "object", "properties": {}}
        return info
    return _make
```

To inject the mock into `MCPClient.connect()`:
```python
async def patched_connect(self):
    self._session = mock_session
    self._tools = [MCPToolAdapter(mock_session, t) for t in mock_session.list_tools.return_value.tools]

with patch.object(MCPClient, "connect", patched_connect):
    async with MCPClient.stdio("npx", []) as mcp:
        ...
```

### Coverage Goals

| Component | Target coverage |
|---|---|
| `MCPToolAdapter` | 100% (all branches: success, isError, timeout, exception, None schema) |
| `MCPClient` | 85%+ (context manager, factory methods, get_tool, disconnect) |
| `load_mcp_config` | 90%+ (not found, stdio, http, env expansion, invalid entry) |
| Error hierarchy | Importability only (no logic to test) |

### What is NOT tested (intentional exclusions)

- Actual stdio subprocess spawning (integration test territory)
- Real Streamable HTTP connection (integration test territory)
- MCP SDK internal behavior (SDK's own test suite covers this)
- `ToolRegistry` integration (tested in registry tests, not MCP tests)

### Future integration tests (Phase 3 candidate)

When a stable MCP test server is available (e.g., `mcp-server-echo` test utility):
```python
@pytest.mark.integration
async def test_stdio_real_connection():
    async with MCPClient.stdio("python", ["-m", "mcp_test_server"]) as mcp:
        tools = mcp.get_tools()
        assert len(tools) > 0
```

These are marked `@pytest.mark.integration` and excluded from the default test run.

---

*Plan created: 2026-03-08*
*Executor: gsd-plan-phase agent*
*Roadmap task: DIFF-08*
