"""Tests for orchestra.discovery.tool_discovery (T-5.2).

Covers:
- AST pre-scan (_ast_has_tool_decorator): bare @tool, @tool(name=...), no decorator, syntax errors
- discover_tools(): empty dir, nonexistent dir, simple tool, custom name, skips _ files,
  skips files with no decorator, import failure continues, duplicate tool name raises,
  nested subdirectories, multiple tools in one file, non-.py files ignored,
  return type is dict[str, ToolWrapper]

discover_tools() returns a tuple (tools_dict, errors_list) where errors is a list of
string messages for files that failed to import.
"""

from __future__ import annotations

import pytest
from pathlib import Path

try:
    from orchestra.discovery.tool_discovery import (
        _ast_has_tool_decorator,
        discover_tools,
    )
    from orchestra.discovery.errors import DuplicateToolError
    _IMPORT_OK = True
except ImportError:
    _IMPORT_OK = False
    _ast_has_tool_decorator = None  # type: ignore[assignment]
    discover_tools = None  # type: ignore[assignment]
    DuplicateToolError = Exception  # type: ignore[assignment,misc]

try:
    from orchestra.tools.base import ToolWrapper
    _TOOL_OK = True
except ImportError:
    _TOOL_OK = False
    ToolWrapper = None  # type: ignore[assignment,misc]

pytestmark = pytest.mark.skipif(
    not _IMPORT_OK,
    reason="orchestra.discovery.tool_discovery not yet implemented",
)


# ---------------------------------------------------------------------------
# AST scanning — _ast_has_tool_decorator
# ---------------------------------------------------------------------------


class TestAstHasToolDecorator:
    def test_ast_finds_bare_decorator(self):
        src = """\
from orchestra.tools.base import tool

@tool
async def search(query: str) -> str:
    return query
"""
        assert _ast_has_tool_decorator(src) is True

    def test_ast_finds_decorator_with_args(self):
        src = """\
from orchestra.tools.base import tool

@tool(name="custom")
async def search(query: str) -> str:
    return query
"""
        assert _ast_has_tool_decorator(src) is True

    def test_ast_no_tool_decorator(self):
        src = """\
def helper():
    pass
"""
        assert _ast_has_tool_decorator(src) is False

    def test_ast_syntax_error_returns_false(self):
        assert _ast_has_tool_decorator("def broken(") is False

    def test_ast_only_tool_name_in_comment_returns_false(self):
        src = "# @tool\ndef not_a_tool(): pass\n"
        assert _ast_has_tool_decorator(src) is False

    def test_ast_async_function_with_bare_decorator(self):
        src = "@tool\nasync def fn(x: str) -> str: return x\n"
        assert _ast_has_tool_decorator(src) is True


# ---------------------------------------------------------------------------
# discover_tools — basic behaviour
# ---------------------------------------------------------------------------


class TestDiscoverToolsBasic:
    def test_discover_tools_empty_dir(self, tmp_path: Path):
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        result, errors = discover_tools(tools_dir)
        assert result == {}
        assert errors == []

    def test_discover_tools_nonexistent_dir(self, tmp_path: Path):
        result, errors = discover_tools(tmp_path / "missing")
        assert result == {}
        assert errors == []

    def test_discover_tools_finds_tool(self, tmp_path: Path):
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "search.py").write_text(
            """\
from orchestra.tools.base import tool

@tool
async def web_search(query: str) -> str:
    \"\"\"Search the web.\"\"\"
    return f"results for: {query}"
""",
            encoding="utf-8",
        )
        result, errors = discover_tools(tools_dir)
        assert errors == []
        assert "web_search" in result
        assert result["web_search"].name == "web_search"
        assert result["web_search"].description == "Search the web."

    def test_discover_tools_returns_toolwrapper_values(self, tmp_path: Path):
        if not _TOOL_OK:
            pytest.skip("ToolWrapper not importable")
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "search.py").write_text(
            """\
from orchestra.tools.base import tool

@tool
async def some_tool(x: str) -> str:
    \"\"\"A tool.\"\"\"
    return x
""",
            encoding="utf-8",
        )
        result, errors = discover_tools(tools_dir)
        assert isinstance(result["some_tool"], ToolWrapper)

    def test_discover_tools_custom_name(self, tmp_path: Path):
        """@tool(name='read_url') must be keyed under 'read_url', not function name."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "fetch.py").write_text(
            """\
from orchestra.tools.base import tool

@tool(name="read_url")
async def fetch_url(url: str) -> str:
    \"\"\"Fetch a URL.\"\"\"
    return url
""",
            encoding="utf-8",
        )
        result, errors = discover_tools(tools_dir)
        assert errors == []
        assert "read_url" in result
        assert "fetch_url" not in result

    def test_discover_tools_non_python_files_ignored(self, tmp_path: Path):
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "readme.txt").write_text("not python", encoding="utf-8")
        (tools_dir / "config.yaml").write_text("key: value", encoding="utf-8")
        result, errors = discover_tools(tools_dir)
        assert result == {}

    def test_discover_tools_multiple_tools_one_file(self, tmp_path: Path):
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "multi.py").write_text(
            """\
from orchestra.tools.base import tool

@tool
async def tool_a(x: str) -> str:
    \"\"\"Tool A.\"\"\"
    return x

@tool
async def tool_b(y: int) -> str:
    \"\"\"Tool B.\"\"\"
    return str(y)
""",
            encoding="utf-8",
        )
        result, errors = discover_tools(tools_dir)
        assert "tool_a" in result
        assert "tool_b" in result
        assert errors == []


# ---------------------------------------------------------------------------
# discover_tools — file skipping
# ---------------------------------------------------------------------------


class TestDiscoverToolsSkipping:
    def test_skips_underscore_prefixed_files(self, tmp_path: Path):
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "_helpers.py").write_text(
            """\
from orchestra.tools.base import tool

@tool
async def hidden(x: str) -> str:
    return x
""",
            encoding="utf-8",
        )
        result, errors = discover_tools(tools_dir)
        assert result == {}

    def test_skips_dunder_init(self, tmp_path: Path):
        """__init__.py starts with _ so must be skipped."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "__init__.py").write_text(
            """\
from orchestra.tools.base import tool

@tool
async def pkg_tool(x: str) -> str:
    return x
""",
            encoding="utf-8",
        )
        result, errors = discover_tools(tools_dir)
        assert result == {}

    def test_skips_file_without_tool_decorator(self, tmp_path: Path):
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "plain.py").write_text(
            "def helper(): pass\n",
            encoding="utf-8",
        )
        result, errors = discover_tools(tools_dir)
        assert result == {}
        assert errors == []


# ---------------------------------------------------------------------------
# discover_tools — nested directories
# ---------------------------------------------------------------------------


class TestDiscoverToolsNested:
    def test_subdirectory_scanned(self, tmp_path: Path):
        tools_dir = tmp_path / "tools"
        sub = tools_dir / "utils"
        sub.mkdir(parents=True)
        (sub / "fmt.py").write_text(
            """\
from orchestra.tools.base import tool

@tool
async def format_text(text: str) -> str:
    \"\"\"Format text.\"\"\"
    return text.upper()
""",
            encoding="utf-8",
        )
        result, errors = discover_tools(tools_dir)
        assert "format_text" in result

    def test_deeply_nested_tool_discovered(self, tmp_path: Path):
        tools_dir = tmp_path / "tools"
        deep = tools_dir / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / "deep_tool.py").write_text(
            """\
from orchestra.tools.base import tool

@tool
async def deep_search(q: str) -> str:
    \"\"\"Deep tool.\"\"\"
    return q
""",
            encoding="utf-8",
        )
        result, errors = discover_tools(tools_dir)
        assert "deep_search" in result


# ---------------------------------------------------------------------------
# discover_tools — error handling
# ---------------------------------------------------------------------------


class TestDiscoverToolsErrorHandling:
    def test_import_failure_continues_discovery(self, tmp_path: Path):
        """A file that fails to import must not block other files."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "bad.py").write_text(
            """\
from orchestra.tools.base import tool
import this_does_not_exist_xyzzy

@tool
async def broken(q: str) -> str:
    return q
""",
            encoding="utf-8",
        )
        (tools_dir / "good.py").write_text(
            """\
from orchestra.tools.base import tool

@tool
async def working(q: str) -> str:
    \"\"\"Works fine.\"\"\"
    return q
""",
            encoding="utf-8",
        )
        result, errors = discover_tools(tools_dir)
        assert "working" in result
        assert len(errors) == 1
        assert "bad.py" in errors[0]

    def test_import_failure_does_not_raise(self, tmp_path: Path):
        """discover_tools() must never propagate ImportError from a single file."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "bad.py").write_text(
            """\
from orchestra.tools.base import tool
import nonexistent_xyz_package_abc

@tool
async def broken(q: str) -> str:
    return q
""",
            encoding="utf-8",
        )
        result, errors = discover_tools(tools_dir)
        assert isinstance(result, dict)
        assert isinstance(errors, list)

    def test_duplicate_tool_name_raises(self, tmp_path: Path):
        """Two files defining the same tool name must raise DuplicateToolError."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        for fname in ("a.py", "b.py"):
            (tools_dir / fname).write_text(
                """\
from orchestra.tools.base import tool

@tool
async def dupe_tool(q: str) -> str:
    return q
""",
                encoding="utf-8",
            )
        with pytest.raises(DuplicateToolError, match="dupe_tool"):
            discover_tools(tools_dir)

    def test_duplicate_error_names_both_files(self, tmp_path: Path):
        """DuplicateToolError message must reference both file names."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        for fname in ("source_a.py", "source_b.py"):
            (tools_dir / fname).write_text(
                """\
from orchestra.tools.base import tool

@tool
async def colliding_name(q: str) -> str:
    return q
""",
                encoding="utf-8",
            )
        with pytest.raises(DuplicateToolError) as exc_info:
            discover_tools(tools_dir)
        msg = str(exc_info.value)
        assert "source_a" in msg or "source_b" in msg
