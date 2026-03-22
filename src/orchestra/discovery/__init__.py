"""Orchestra auto-discovery layer.

Convention-based project scanning: define agents in YAML, tools as
``@tool`` Python functions, and workflows as YAML graphs. Run
``orchestra up`` to auto-discover everything and start serving.

Public API::

    from orchestra.discovery import ProjectScanner, discover_tools, load_agent, load_workflow
"""

from orchestra.discovery.agent_loader import load_agent
from orchestra.discovery.config import ProjectConfig, load_config
from orchestra.discovery.errors import (
    AgentLoadError,
    ConfigError,
    DiscoveryError,
    DuplicateToolError,
    ToolNotFoundError,
    WorkflowLoadError,
)
from orchestra.discovery.hotreload import DiscoveryHotReloader
from orchestra.discovery.scanner import ProjectScanner, ScanResult
from orchestra.discovery.tool_discovery import discover_tools
from orchestra.discovery.validation import did_you_mean, validate_project
from orchestra.discovery.workflow_loader import build_state_class, load_workflow

__all__ = [
    "AgentLoadError",
    "ConfigError",
    "DiscoveryError",
    "DiscoveryHotReloader",
    "DuplicateToolError",
    "ProjectConfig",
    "ProjectScanner",
    "ScanResult",
    "ToolNotFoundError",
    "WorkflowLoadError",
    "build_state_class",
    "did_you_mean",
    "discover_tools",
    "load_agent",
    "load_config",
    "load_workflow",
    "validate_project",
]
