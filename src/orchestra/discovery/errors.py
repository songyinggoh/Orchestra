"""Discovery-specific error types."""

from __future__ import annotations


class DiscoveryError(Exception):
    """Base error for all discovery-related failures."""


class ToolNotFoundError(DiscoveryError):
    """Raised when an agent references a tool that was not discovered."""


class DuplicateToolError(DiscoveryError):
    """Raised when two files define tools with the same name."""


class AgentLoadError(DiscoveryError):
    """Raised when an agent YAML file cannot be parsed or validated."""


class WorkflowLoadError(DiscoveryError):
    """Raised when a workflow YAML file cannot be loaded."""


class ConfigError(DiscoveryError):
    """Raised when orchestra.yaml is invalid."""
