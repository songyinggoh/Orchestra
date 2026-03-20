"""Tool discovery: glob, import, and collect @tool-decorated functions.

Two-pass approach:
1. AST scan to find files containing @tool decorators (no execution)
2. importlib to load only those files and collect ToolWrapper instances
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from typing import Any

import structlog

from orchestra.discovery.errors import DuplicateToolError
from orchestra.tools.base import ToolWrapper

logger = structlog.get_logger(__name__)


def _ast_has_tool_decorator(source: str) -> bool:
    """Check whether *source* contains a @tool decorator (without executing)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                # @tool
                if isinstance(decorator, ast.Name) and decorator.id == "tool":
                    return True
                # @tool(name="...")
                if isinstance(decorator, ast.Call):
                    func = decorator.func
                    if isinstance(func, ast.Name) and func.id == "tool":
                        return True
    return False


def discover_tools(
    tools_dir: Path,
) -> tuple[dict[str, ToolWrapper], list[str]]:
    """Discover ``@tool`` functions from *tools_dir*.

    Returns:
        A tuple of (tool_registry, errors) where *tool_registry* maps
        tool names to ``ToolWrapper`` instances, and *errors* collects
        human-readable messages for files that failed to import.

    Raises:
        DuplicateToolError: If two files define tools with the same name.
    """
    tools: dict[str, ToolWrapper] = {}
    sources: dict[str, Path] = {}  # tool_name -> file that defined it
    errors: list[str] = []

    if not tools_dir.exists():
        return tools, errors

    for py_file in sorted(tools_dir.rglob("*.py")):
        # Skip _-prefixed files (e.g. __init__.py, _helpers.py)
        if py_file.name.startswith("_"):
            continue

        try:
            source = py_file.read_text(encoding="utf-8")
        except Exception as exc:
            errors.append(f"Could not read {py_file}: {exc}")
            continue

        if not _ast_has_tool_decorator(source):
            continue

        # Import the file into an isolated namespace
        module_name = f"orchestra_user_tools.{py_file.stem}"
        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if spec is None or spec.loader is None:
            errors.append(f"Could not create import spec for {py_file}")
            continue

        try:
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception as exc:
            errors.append(f"Failed to import {py_file}: {exc}")
            # Clean up partial registration
            sys.modules.pop(module_name, None)
            continue

        # Collect ToolWrapper instances from the module
        for attr_name in dir(module):
            obj = getattr(module, attr_name, None)
            if isinstance(obj, ToolWrapper):
                if obj.name in tools:
                    raise DuplicateToolError(
                        f"Tool '{obj.name}' defined in both "
                        f"{sources[obj.name]} and {py_file}. "
                        f"Use @tool(name='unique_name') to disambiguate."
                    )
                tools[obj.name] = obj
                sources[obj.name] = py_file

    return tools, errors
