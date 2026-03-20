"""Orchestra auto-discovery layer.

Convention-based project scanning: define agents in YAML, tools as
``@tool`` Python functions, and workflows as YAML graphs. Run
``orchestra up`` to auto-discover everything and start serving.

Public API::

    from orchestra.discovery import ProjectScanner, discover_tools, load_agent, load_workflow
"""

from orchestra.discovery.scanner import ProjectScanner, ScanResult
from orchestra.discovery.tool_discovery import discover_tools
from orchestra.discovery.agent_loader import load_agent
from orchestra.discovery.workflow_loader import load_workflow, build_state_class
from orchestra.discovery.config import ProjectConfig, load_config
from orchestra.discovery.validation import validate_project, did_you_mean
from orchestra.discovery.hotreload import DiscoveryHotReloader
from orchestra.discovery.errors import (
    DiscoveryError,
    ToolNotFoundError,
    DuplicateToolError,
    AgentLoadError,
    WorkflowLoadError,
    ConfigError,
)

__all__ = [
    "ProjectScanner",
    "ScanResult",
    "discover_tools",
    "load_agent",
    "load_workflow",
    "build_state_class",
    "ProjectConfig",
    "load_config",
    "validate_project",
    "did_you_mean",
    "DiscoveryHotReloader",
    "DiscoveryError",
    "ToolNotFoundError",
    "DuplicateToolError",
    "AgentLoadError",
    "WorkflowLoadError",
    "ConfigError",
]
