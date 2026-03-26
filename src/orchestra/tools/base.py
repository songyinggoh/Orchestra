"""Tool Protocol implementation and @tool decorator.

Tools are functions that agents can call. The @tool decorator
auto-generates JSON Schema from Python type hints.

Usage:
    @tool
    async def web_search(query: str, max_results: int = 5) -> str:
        '''Search the web for information.'''
        return f"Results for: {query}"
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Awaitable, Callable
from typing import Any, get_type_hints

from orchestra.core.context import ExecutionContext
from orchestra.core.types import ToolResult


def _python_type_to_json_schema(type_hint: Any) -> dict[str, Any]:
    """Convert a Python type hint to JSON Schema type."""
    type_map: dict[Any, dict[str, Any]] = {
        str: {"type": "string"},
        int: {"type": "integer"},
        float: {"type": "number"},
        bool: {"type": "boolean"},
        list: {"type": "array"},
        dict: {"type": "object"},
    }

    if type_hint in type_map:
        return type_map[type_hint]

    origin = getattr(type_hint, "__origin__", None)
    if origin is list:
        args = getattr(type_hint, "__args__", ())
        items = _python_type_to_json_schema(args[0]) if args else {}
        return {"type": "array", "items": items}

    if origin is dict:
        return {"type": "object"}

    return {"type": "string"}


def _generate_parameters_schema(func: Callable[..., Any]) -> dict[str, Any]:
    """Generate JSON Schema for function parameters."""
    sig = inspect.signature(func)
    hints = get_type_hints(func)

    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "context"):
            continue

        if param_name in hints:
            prop = _python_type_to_json_schema(hints[param_name])
        else:
            prop = {"type": "string"}

        properties[param_name] = prop

        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required

    return schema


class ToolWrapper:
    """Wraps an async function as a Tool protocol implementation."""

    def __init__(
        self,
        func: Callable[..., Awaitable[Any]],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        self._func = func
        self._name = name or func.__name__
        self._description = description or inspect.getdoc(func) or ""
        self._parameters_schema = _generate_parameters_schema(func)
        functools.update_wrapper(self, func)  # type: ignore[arg-type]

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return self._parameters_schema

    async def execute(
        self,
        arguments: dict[str, Any],
        *,
        context: ExecutionContext | None = None,
    ) -> ToolResult:
        """Execute the wrapped function with given arguments."""
        try:
            sig = inspect.signature(self._func)
            # Filter arguments to only known parameter names to prevent
            # injection of unexpected keyword arguments from LLM output.
            known_params = set(sig.parameters.keys()) - {"self"}
            has_var_keyword = any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
            )
            if not has_var_keyword:
                arguments = {k: v for k, v in arguments.items() if k in known_params}
            if "context" in sig.parameters:
                arguments = {**arguments, "context": context}

            result = await self._func(**arguments)
            return ToolResult(
                tool_call_id="",
                name=self.name,
                content=str(result),
            )
        except Exception as e:
            return ToolResult(
                tool_call_id="",
                name=self.name,
                content="",
                error=str(e),
            )

    def __repr__(self) -> str:
        return f"Tool({self._name})"


def tool(
    func: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Any:
    """Decorator to create a Tool from an async function.

    Can be used with or without arguments:

        @tool
        async def search(query: str) -> str: ...

        @tool(name="custom_search")
        async def search(query: str) -> str: ...
    """
    if func is not None:
        return ToolWrapper(func)

    def wrapper(f: Callable[..., Any]) -> ToolWrapper:
        return ToolWrapper(f, name=name, description=description)

    return wrapper
