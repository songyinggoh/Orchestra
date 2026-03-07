# Research: MCP Client Integration

**Research Date:** 2026-03-07
**Phase:** 2 - Differentiation
**Confidence:** HIGH

---

## 1. MCP Specification (Current State)

### Protocol Version
- Latest spec: **2025-11-25** (with transport update 2025-03-26)
- JSON-RPC 2.0 based protocol
- Three core primitives: **Tools**, **Resources**, **Prompts**
- Orchestra Phase 2 focuses on **Tools** (Resources and Prompts deferred)

### Tool Discovery Flow
1. Client opens transport (stdio subprocess or HTTP connection)
2. Client sends `initialize` request with capabilities
3. Server responds with capabilities (including `tools` if supported)
4. Client sends `tools/list` to discover available tools
5. Each tool has: `name`, `description`, `inputSchema` (JSON Schema)
6. Client calls tools via `tools/call` with `name` and `arguments`

### SSE is DEPRECATED
As of spec revision 2025-03-26, the SSE transport was deprecated in favor of **Streamable HTTP**. The CONTEXT.md says "SSE as a second transport" — the implementation should target `streamablehttp_client` from the MCP SDK, not legacy SSE.

---

## 2. Python MCP SDK

### Package
- **`mcp`** on PyPI (v1.26+, maintained by Anthropic)
- Pin to `>=1.26,<2` (v2 is pre-alpha with breaking changes)
- All major frameworks use this same SDK: OpenAI Agents SDK, Pydantic AI, LangChain

### Key Classes
```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
```

### Basic Usage Pattern
```python
async with stdio_client(StdioServerParameters(
    command="npx",
    args=["-y", "@modelcontextprotocol/server-filesystem", "/path"],
    env={"NODE_PATH": ...},
)) as (read_stream, write_stream):
    async with ClientSession(read_stream, write_stream) as session:
        await session.initialize()
        tools = await session.list_tools()
        result = await session.call_tool("read_file", {"path": "/tmp/test.txt"})
```

---

## 3. stdio Transport Implementation

### Process Lifecycle
1. **Start:** Launch subprocess with `asyncio.create_subprocess_exec` (the MCP SDK handles this via `stdio_client`)
2. **Health:** Monitor subprocess health via `process.returncode`
3. **Communication:** JSON-RPC messages over stdin/stdout
4. **Shutdown:** Send graceful close, then `process.terminate()`, then `process.kill()` after timeout
5. **Crash recovery:** Detect process exit, attempt restart with backoff

### Process Management
```python
params = StdioServerParameters(
    command="npx",
    args=["-y", "@modelcontextprotocol/server-filesystem", "/allowed/path"],
    env=None,  # Inherit parent env, or provide explicit env dict
)
```

### Claude Desktop / Cursor Pattern
- Both manage MCP server processes as child subprocesses
- Servers are started lazily (on first tool access) or eagerly (at session start)
- Graceful shutdown on parent exit (SIGTERM -> wait -> SIGKILL)
- Stderr from MCP servers is captured for debugging

---

## 4. Streamable HTTP Transport

### Replaces SSE
- Uses standard HTTP POST for requests, optional SSE for server-initiated messages
- Supports session management via `Mcp-Session-Id` header
- Reconnection: client can resume session if server supports it

### Usage
```python
async with streamablehttp_client(
    url="http://localhost:8080/mcp",
    headers={"Authorization": "Bearer ..."},
) as (read_stream, write_stream):
    async with ClientSession(read_stream, write_stream) as session:
        await session.initialize()
        # Same API as stdio from here
```

### When to Use
- Remote MCP servers (not local subprocesses)
- Shared infrastructure (multiple clients connecting to one server)
- Authentication required

---

## 5. Tool Schema Mapping (MCP -> Orchestra)

### Schema Compatibility
MCP tool schemas are **nearly 1:1** with Orchestra's existing tool system:

| MCP Tool Field | Orchestra Tool Protocol | Notes |
|---|---|---|
| `name` | `Tool.name` | Direct mapping |
| `description` | `Tool.description` | Direct mapping |
| `inputSchema` | `Tool.parameters_schema` | Both use JSON Schema |

### MCPToolAdapter Design
```python
class MCPToolAdapter:
    """Wraps an MCP tool to satisfy Orchestra's Tool protocol."""

    def __init__(self, session: ClientSession, tool_info: MCPTool):
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
        return self._tool_info.inputSchema or {}

    async def execute(
        self, arguments: dict[str, Any], *, context: ExecutionContext | None = None
    ) -> ToolResult:
        result = await self._session.call_tool(self.name, arguments)
        # Extract text content from MCP result
        content = "\n".join(
            block.text for block in result.content
            if hasattr(block, "text")
        )
        return ToolResult(
            tool_call_id="",
            name=self.name,
            content=content,
            error=None if not result.isError else content,
        )
```

This adapter is transparent — agents see it as a regular `Tool` protocol implementor.

---

## 6. MCP Server Configuration

### Code-First API
```python
from orchestra.tools.mcp import MCPClient

# stdio server
mcp = MCPClient.stdio("npx", ["-y", "@modelcontextprotocol/server-filesystem", "/path"])

# Streamable HTTP server
mcp = MCPClient.http("http://localhost:8080/mcp", headers={"Authorization": "Bearer ..."})

# Register tools with workflow
graph = WorkflowGraph()
graph.add_mcp(mcp)  # All MCP tools available to opt-in agents

# Agent opts in to specific tools
agent = BaseAgent(
    name="researcher",
    tools=[mcp.get_tool("read_file"), mcp.get_tool("search")],
)
```

### Config File Format (`.orchestra/mcp.json`)
Match Claude Desktop format for copy-paste compatibility:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"],
      "env": {}
    },
    "database": {
      "command": "python",
      "args": ["-m", "mcp_server_sqlite", "--db", "./data.db"]
    },
    "remote-api": {
      "url": "http://localhost:8080/mcp",
      "headers": {
        "Authorization": "Bearer ${MCP_API_KEY}"
      }
    }
  }
}
```

- `command` + `args` → stdio transport
- `url` → Streamable HTTP transport
- `env` → environment variables for subprocess (supports `${VAR}` expansion)

### Discovery Priority
1. Code-based `MCPClient` instances (explicit)
2. `.orchestra/mcp.json` in project root (auto-discovered)
3. Code overrides config file settings for same server name

---

## 7. Error Handling and Lifecycle

### Server Crash Recovery
- Detect subprocess exit via `process.returncode`
- Attempt restart with exponential backoff (1s, 2s, 4s, max 30s)
- After 3 failed restarts, mark server as unavailable
- Tools from unavailable servers raise `ToolExecutionError` with clear message

### Tool Execution Timeout
- Default: 30 seconds per tool call
- Configurable per-server: `MCPClient.stdio(..., timeout=60)`
- On timeout: cancel the pending JSON-RPC request, raise `ToolTimeoutError`

### Connection Lifecycle
```python
class MCPClient:
    async def __aenter__(self):
        # Start subprocess / open HTTP connection
        # Initialize session
        # Discover tools
        return self

    async def __aexit__(self, *exc):
        # Graceful shutdown
        # Terminate subprocess
        pass
```

Use `AsyncExitStack` to manage multiple MCP server lifecycles:
```python
async with AsyncExitStack() as stack:
    fs = await stack.enter_async_context(MCPClient.stdio("npx", [...]))
    db = await stack.enter_async_context(MCPClient.stdio("python", [...]))
    # Both cleaned up on exit
```

---

## 8. Open Questions

1. **Structured content** — MCP tools can return `structuredContent` (JSON) alongside text. Orchestra's `ToolResult.content` is string-only. Options: add `structured_content: dict | None` to `ToolResult`, or serialize to JSON string.
2. **Non-text content** — MCP tools can return images (base64). How to handle in Orchestra? Likely: store as-is in tool result, let the agent's LLM process it.
3. **MCP SDK v2** — Pre-alpha with breaking changes. Pin to `<2` and monitor.
4. **Resource and Prompt primitives** — MCP also defines Resources (data the server exposes) and Prompts (reusable prompt templates). Deferred to a future phase.

---

## 9. Dependencies

- `mcp>=1.26,<2` — official Python MCP SDK (core dependency for MCP feature)
- No additional dependencies — the SDK handles transport, JSON-RPC, and session management

---

*Research: 2026-03-07*
*Researcher: gsd-phase-researcher agent*
