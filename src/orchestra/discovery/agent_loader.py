"""Agent loader: YAML -> BaseAgent with tool resolution and defaults cascade.

Cascade order: agent YAML > orchestra.yaml defaults > BaseAgent defaults.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
from ruamel.yaml import YAML

from orchestra.core.agent import BaseAgent
from orchestra.discovery.config import DefaultsSection
from orchestra.discovery.errors import AgentLoadError, ToolNotFoundError
from orchestra.tools.base import ToolWrapper

logger = structlog.get_logger(__name__)

# BaseAgent class-level defaults (used as final fallback)
_AGENT_DEFAULTS = {
    "model": "gpt-4o-mini",
    "temperature": 0.7,
    "max_iterations": 10,
    "system_prompt": "You are a helpful assistant.",
}


def load_agent(
    yaml_path: Path,
    tool_registry: dict[str, ToolWrapper],
    defaults: DefaultsSection | None = None,
) -> BaseAgent:
    """Load an agent definition from a YAML file.

    Args:
        yaml_path: Path to the agent YAML file.
        tool_registry: Discovered tools keyed by name.
        defaults: Project-level defaults from ``orchestra.yaml``.

    Returns:
        A configured :class:`BaseAgent` instance.

    Raises:
        AgentLoadError: If the YAML is invalid.
        ToolNotFoundError: If the agent references an undiscovered tool.
    """
    try:
        yaml = YAML(typ="safe")
        data: dict[str, Any] | None = yaml.load(
            yaml_path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise AgentLoadError(f"Cannot parse {yaml_path}: {exc}") from exc

    if not data or not isinstance(data, dict):
        raise AgentLoadError(f"Agent YAML {yaml_path} is empty or not a mapping")

    # Guard: output_type_ref / output_type are not yet supported in YAML agent
    # definitions.  Silently ignoring them would make users believe structured
    # output is active when it is not — a correctness hazard.
    for _unsupported_key in ("output_type_ref", "output_type"):
        if _unsupported_key in data:
            raise AgentLoadError(
                f"'{_unsupported_key}' is not yet supported in YAML agent definitions. "
                "Define the agent in Python and register it manually."
            )

    # Resolve tool references
    tool_names: list[str] = data.get("tools", [])
    resolved_tools: list[ToolWrapper] = []
    for name in tool_names:
        if name not in tool_registry:
            available = sorted(tool_registry.keys())
            raise ToolNotFoundError(
                f"Agent '{data.get('name', yaml_path.stem)}' references tool "
                f"'{name}' which was not found. Available: {available}"
            )
        resolved_tools.append(tool_registry[name])

    # Build cascaded values: agent YAML > orchestra.yaml defaults > BaseAgent defaults
    def _get(key: str) -> Any:
        """Cascade lookup: agent data -> project defaults -> class defaults."""
        if key in data:
            return data[key]
        if defaults is not None and hasattr(defaults, key):
            return getattr(defaults, key)
        return _AGENT_DEFAULTS.get(key)

    return BaseAgent(
        name=data.get("name", yaml_path.stem),
        model=_get("model"),
        system_prompt=_get("system_prompt"),
        tools=resolved_tools,
        max_iterations=_get("max_iterations"),
        temperature=_get("temperature"),
    )
