---
phase: 02-differentiation
plan: "2.2"
subsystem: tools
tags: [mcp, model-context-protocol, tools, adapters, stdio, http, structlog]

# Dependency graph
requires:
  - phase: 02-differentiation
    provides: "errors.py base hierarchy (OrchestraError, ToolError, ToolNotFoundError)"
  - phase: 02-differentiation
    provides: "Tool protocol in protocols.py (runtime_checkable structural subtyping)"
  - phase: 02-differentiation
    provides: "ToolResult type in types.py"
provides:
  - MCPClient with stdio() and http() factory class methods and async context manager lifecycle
  - MCPToolAdapter satisfying Orchestra's Tool protocol via structural subtyping
  - load_mcp_config() loading Claude Desktop-compatible .orchestra/mcp.json
  - MCPError, MCPConnectionError, MCPToolError, MCPTimeoutError error hierarchy
  - 22 unit tests covering adapters, client lifecycle, config loading, and error paths
affects: [agents, tool-registry, phase-03-features]

# Tech tracking
tech-stack:
  added: ["mcp>=1.26,<2 (official MCP Python SDK)"]
  patterns:
    - "Structural subtyping: MCPToolAdapter satisfies Tool protocol without inheritance"
    - "AsyncExitStack-style transport lifecycle via _cm/_session pair in MCPClient"
    - "Auto-detect transport from constructor arguments (command vs url) with explicit factory methods"
    - "Error hierarchy branching: MCPError subclasses OrchestraError directly, not ToolError"

key-files:
  created:
    - src/orchestra/tools/mcp.py
    - tests/unit/test_mcp.py
  modified:
    - src/orchestra/core/errors.py
    - src/orchestra/tools/__init__.py
    - pyproject.toml

key-decisions:
  - "Use mcp SDK (stdio_client, streamablehttp_client, ClientSession) — do NOT implement raw JSON-RPC transport classes"
  - "MCPToolAdapter holds ClientSession directly (not MCPClient) — session is the API surface for tool calls"
  - "MCPError hierarchy subclasses OrchestraError directly, not ToolError — transport failures vs tool execution failures"
  - "get_tool() raises ToolNotFoundError (not KeyError) for clear Orchestra-consistent error messages"
  - "load_mcp_config() returns list[MCPClient] — callers get ready-to-use clients, not raw dicts"
  - "Claude Desktop mcpServers format for copy-paste compatibility; transport discriminated by command vs url key"
  - "Text-only content extraction from MCP result blocks; image/structured content deferred to Phase 3"

patterns-established:
  - "MCP tool discovery: eager on connect(), tools available immediately after __aenter__"
  - "Timeout wrapping: asyncio.wait_for() in execute() and discover_tools() raising MCPTimeoutError"
  - "Config env expansion: os.path.expandvars() on all string values in env/args/headers dicts"

requirements-completed: []

# Metrics
duration: 25min
completed: 2026-03-09
---

# Phase 2 Plan 2.2: MCP Client Integration Summary

**MCPClient and MCPToolAdapter connecting Orchestra agents to MCP servers via stdio subprocess and Streamable HTTP, using the official mcp Python SDK with full Tool protocol conformance**

## Performance

- **Duration:** 25 min
- **Started:** 2026-03-09T00:00:00Z
- **Completed:** 2026-03-09T00:25:00Z
- **Tasks:** 2 subtasks (2.2.1 implementation + 2.2.2 tests)
- **Files modified:** 5

## Accomplishments

- MCPToolAdapter wraps any MCP server tool as an Orchestra Tool protocol implementation — agents cannot distinguish it from a ToolWrapper
- MCPClient supports both stdio (subprocess) and Streamable HTTP transports via factory class methods, with full async context manager lifecycle
- load_mcp_config() reads Claude Desktop-compatible `.orchestra/mcp.json`, returning configured MCPClient instances with env var expansion
- 22 unit tests cover all execution paths: success, isError result, TimeoutError, exception propagation, config parsing, and protocol conformance
- MCPError hierarchy (MCPConnectionError, MCPToolError, MCPTimeoutError) correctly subclasses OrchestraError to preserve transport-vs-tool error conceptual distinction

## Task Commits

Each subtask was committed atomically:

1. **Subtask 2.2.1: MCP Client Implementation** - `d2f8e54` (feat: add MCP client with stdio and HTTP transport adapters)
2. **Subtask 2.2.2: Tests with Mock Server** - `bc4b044` (test: add 15 unit tests for MCPClient and MCPToolAdapter)
3. **Fix: export load_mcp_config + ToolNotFoundError** - `84ddae5` (fix: export load_mcp_config and raise ToolNotFoundError in get_tool)

**Plan metadata:** (this summary commit)

## Files Created/Modified

- `src/orchestra/tools/mcp.py` - MCPClient, MCPToolAdapter, load_mcp_config; ~425 lines
- `tests/unit/test_mcp.py` - 22 unit tests covering all public API paths; ~445 lines
- `src/orchestra/core/errors.py` - Appended MCPError, MCPConnectionError, MCPToolError, MCPTimeoutError
- `src/orchestra/tools/__init__.py` - Added MCPClient, MCPToolAdapter, load_mcp_config to imports and __all__
- `pyproject.toml` - Added mcp>=1.26,<2 to project.dependencies

## Decisions Made

- Used the official `mcp` Python SDK instead of raw JSON-RPC transport classes — the SDK handles all framing, initialization, and capability negotiation internally
- MCPToolAdapter holds `ClientSession` directly (not MCPClient reference) — decouples tool execution from connection concerns
- Transport selection in MCPClient done via explicit factory methods (`MCPClient.stdio()`, `MCPClient.http()`) and constructor validation; `_connect_stdio`/`_connect_http` private methods handle transport-specific setup
- `load_mcp_config()` returns `list[MCPClient]` rather than raw dicts — callers get ready-to-use objects without extra construction step

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Missing load_mcp_config export from orchestra.tools**
- **Found during:** Final verification pass
- **Issue:** `tools/__init__.py` imported `MCPClient` and `MCPToolAdapter` from `mcp` module but did not export `load_mcp_config`, causing `ImportError` on `from orchestra.tools import load_mcp_config`
- **Fix:** Added `load_mcp_config` to import line and `__all__` list in `tools/__init__.py`
- **Files modified:** `src/orchestra/tools/__init__.py`
- **Verification:** `from orchestra.tools import load_mcp_config` succeeds
- **Committed in:** `84ddae5`

**2. [Rule 1 - Bug] get_tool() raised KeyError instead of ToolNotFoundError**
- **Found during:** Final verification pass (plan Gap 6 resolution audit)
- **Issue:** Plan explicitly specified `get_tool()` should raise `ToolNotFoundError` for clear Orchestra-consistent error messages. Implementation raised raw `KeyError` (dict lookup miss), bypassing the error hierarchy.
- **Fix:** Added explicit name check in `get_tool()` to raise `ToolNotFoundError` with informative message including available tool names. Updated test to expect `ToolNotFoundError`.
- **Files modified:** `src/orchestra/tools/mcp.py`, `tests/unit/test_mcp.py`
- **Verification:** 22 tests pass; `ToolNotFoundError` inherits from `ToolError -> OrchestraError`
- **Committed in:** `84ddae5`

---

**Total deviations:** 2 auto-fixed (both Rule 1 — incorrect behavior vs plan spec)
**Impact on plan:** Both fixes necessary for correctness and API consistency. No scope creep.

## Issues Encountered

The subtask implementation was already partially executed by a prior agent session (commits `d2f8e54` and `bc4b044`). This execution session verified the implementation against the plan spec, ran all tests, and fixed the two gaps found. No blocking issues during the fix pass.

## User Setup Required

None — no external service configuration required. MCP server connections require user-provided server commands or URLs at runtime, but no static setup.

## Next Phase Readiness

- MCPClient and MCPToolAdapter are production-ready for agent integration
- Agents can receive `list[MCPToolAdapter]` alongside `list[ToolWrapper]` with no code changes
- ToolRegistry can store MCPToolAdapter instances (no registry changes needed)
- Integration tests against real MCP servers are a Phase 3 candidate (`@pytest.mark.integration`)
- Structured/image content from MCP result blocks is deferred to Phase 3 (documented TODO in mcp.py)

---
*Phase: 02-differentiation*
*Completed: 2026-03-09*
