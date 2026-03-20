"""Tests for orchestra.discovery.tool_discovery (T-5.2)."""

from __future__ import annotations

import pytest
from pathlib import Path

from orchestra.discovery.tool_discovery import (
    _ast_has_tool_decorator,
    discover_tools,
)
from orchestra.discovery.errors import DuplicateToolError


# ---- AST scanning ----


def test_ast_finds_bare_decorator():
    src = """\
from orchestra.tools.base import tool

@tool
async def search(query: str) -> str:
    return query
"""
    assert _ast_has_tool_decorator(src) is True


def test_ast_finds_decorator_with_args():
    src = """\
from orchestra.tools.base import tool

@tool(name="custom")
async def search(query: str) -> str:
    return query
"""
    assert _ast_has_tool_decorator(src) is True


def test_ast_no_tool_decorator():
    src = """\
def helper():
    pass
"""
    assert _ast_has_tool_decorator(src) is False


def test_ast_syntax_error_returns_false():
    assert _ast_has_tool_decorator("def broken(") is False


# ---- discover_tools ----


def test_discover_tools_empty_dir(tmp_path: Path):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    result, errors = discover_tools(tools_dir)
    assert result == {}
    assert errors == []


def test_discover_tools_nonexistent_dir(tmp_path: Path):
    result, errors = discover_tools(tmp_path / "missing")
    assert result == {}
    assert errors == []


def test_discover_tools_finds_tool(tmp_path: Path):
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


def test_discover_tools_custom_name(tmp_path: Path):
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


def test_discover_tools_skips_underscore_prefixed(tmp_path: Path):
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


def test_discover_tools_skips_no_decorator(tmp_path: Path):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "plain.py").write_text(
        "def helper(): pass\n",
        encoding="utf-8",
    )
    result, errors = discover_tools(tools_dir)
    assert result == {}
    assert errors == []


def test_discover_tools_import_failure_continues(tmp_path: Path):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    # File that has @tool decorator but will fail on import
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
    # Good file
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


def test_discover_tools_duplicate_raises(tmp_path: Path):
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


def test_discover_tools_subdirectory(tmp_path: Path):
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


def test_discover_tools_multiple_tools_one_file(tmp_path: Path):
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
