"""Tool Access Control Lists (ACLs) for agent security.

Enables fine-grained control over which tools an agent is authorized
to execute based on name, patterns, or namespaces.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class ToolACL:
    """Access control list for tool execution."""

    allowed_tools: set[str] = field(default_factory=set)
    denied_tools: set[str] = field(default_factory=set)
    allow_patterns: list[str] = field(default_factory=list)
    deny_patterns: list[str] = field(default_factory=list)
    allow_all: bool = False

    def is_authorized(self, tool_name: str) -> bool:
        """Check if a tool is authorized by this ACL."""
        # 1. Explicit denial takes precedence
        if tool_name in self.denied_tools:
            return False

        for pattern in self.deny_patterns:
            if fnmatch.fnmatch(tool_name, pattern):
                return False

        # 2. Check allow-all
        if self.allow_all:
            return True

        # 3. Explicit allowance
        if tool_name in self.allowed_tools:
            return True

        for pattern in self.allow_patterns:
            if fnmatch.fnmatch(tool_name, pattern):
                return True

        return False

    @classmethod
    def allow_list(cls, tools: Iterable[str]) -> ToolACL:
        """Create an ACL that only allows specified tools."""
        return cls(allowed_tools=set(tools), allow_all=False)

    @classmethod
    def deny_list(cls, tools: Iterable[str]) -> ToolACL:
        """Create an ACL that allows everything except specified tools."""
        return cls(denied_tools=set(tools), allow_all=True)

    @classmethod
    def open(cls) -> ToolACL:
        """Create an ACL that allows all tools."""
        return cls(allow_all=True)


class UnauthorizedToolError(Exception):
    """Raised when an agent attempts to call a tool not authorized by its ACL."""

    def __init__(self, tool_name: str, agent_name: str) -> None:
        self.tool_name = tool_name
        self.agent_name = agent_name
        super().__init__(
            f"Agent '{agent_name}' is not authorized to execute tool '{tool_name}'."
        )
