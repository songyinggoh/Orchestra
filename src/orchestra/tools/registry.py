"""Tool registry for registration, lookup, and management."""

from __future__ import annotations

from typing import Any

from orchestra.core.errors import ToolNotFoundError


class ToolRegistry:
    """Central registry for tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Any] = {}

    def register(self, tool_instance: Any) -> None:
        """Register a tool."""
        name = tool_instance.name
        if name in self._tools:
            raise ValueError(f"Tool '{name}' is already registered.")
        self._tools[name] = tool_instance

    def get(self, name: str) -> Any:
        """Get a tool by name."""
        if name not in self._tools:
            raise ToolNotFoundError(
                f"Tool '{name}' not found in registry.\n"
                f"  Available tools: {list(self._tools.keys())}\n"
                f"  Fix: Register the tool with registry.register(tool)."
            )
        return self._tools[name]

    def has(self, name: str) -> bool:
        return name in self._tools

    def list_tools(self) -> list[dict[str, str]]:
        return [{"name": t.name, "description": t.description} for t in self._tools.values()]

    def get_schemas(self, tool_names: list[str] | None = None) -> list[dict[str, Any]]:
        """Get OpenAI function-calling schemas for tools."""
        tools = list(self._tools.values())
        if tool_names:
            tools = [self._tools[n] for n in tool_names if n in self._tools]

        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters_schema,
                },
            }
            for t in tools
        ]

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def clear(self) -> None:
        self._tools.clear()

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
