"""ProjectScanner: orchestrates the full discovery pipeline.

Usage::

    scanner = ProjectScanner()
    result = scanner.scan(Path("."))
    # result.tools, result.agents, result.workflows, result.errors
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from orchestra.core.agent import BaseAgent
from orchestra.core.compiled import CompiledGraph
from orchestra.core.dynamic import SubgraphBuilder, DEFAULT_ALLOWED_PREFIXES
from orchestra.discovery.config import ProjectConfig, load_config
from orchestra.discovery.errors import DiscoveryError
from orchestra.discovery.tool_discovery import discover_tools
from orchestra.discovery.agent_loader import load_agent
from orchestra.discovery.workflow_loader import load_workflow
from orchestra.tools.base import ToolWrapper

logger = structlog.get_logger(__name__)


@dataclass
class ScanResult:
    """Result of a full project scan."""

    config: ProjectConfig = field(default_factory=ProjectConfig)
    tools: dict[str, ToolWrapper] = field(default_factory=dict)
    agents: dict[str, BaseAgent] = field(default_factory=dict)
    workflows: dict[str, CompiledGraph] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class ProjectScanner:
    """Orchestrates config loading, tool discovery, agent loading,
    and workflow compilation for a project directory."""

    def scan(self, project_dir: Path) -> ScanResult:
        """Scan *project_dir* and return a populated :class:`ScanResult`.

        The scan collects all errors before failing so that the user
        sees every problem at once rather than one at a time.
        """
        result = ScanResult()

        # 1. Load config
        try:
            result.config = load_config(project_dir)
        except DiscoveryError as exc:
            result.errors.append(str(exc))
            return result

        cfg = result.config
        dirs = cfg.directories

        # 2. Discover tools
        tools_dir = project_dir / dirs.tools
        try:
            tools, tool_errors = discover_tools(tools_dir)
            result.tools = tools
            result.errors.extend(tool_errors)
        except DiscoveryError as exc:
            result.errors.append(str(exc))

        # 3. Load agents
        agents_dir = project_dir / dirs.agents
        if agents_dir.exists():
            for yaml_file in sorted(agents_dir.rglob("*.yaml")) + sorted(
                agents_dir.rglob("*.yml")
            ):
                try:
                    agent = load_agent(
                        yaml_file,
                        tool_registry=result.tools,
                        defaults=cfg.defaults,
                    )
                    result.agents[agent.name] = agent
                except DiscoveryError as exc:
                    result.errors.append(str(exc))

        # 4. Load workflows
        workflows_dir = project_dir / dirs.workflows
        # Build a SubgraphBuilder with project-level allowed prefixes
        allowed = list(DEFAULT_ALLOWED_PREFIXES) + list(
            cfg.security.allowed_imports
        )
        builder = SubgraphBuilder(allowed_prefixes=allowed)

        if workflows_dir.exists():
            for yaml_file in sorted(workflows_dir.rglob("*.yaml")) + sorted(
                workflows_dir.rglob("*.yml")
            ):
                try:
                    compiled = load_workflow(
                        yaml_file,
                        agent_registry=result.agents,
                        tool_registry=result.tools,
                        builder=builder,
                    )
                    name = compiled._name or yaml_file.stem
                    result.workflows[name] = compiled
                except DiscoveryError as exc:
                    result.errors.append(str(exc))

        # 5. Cross-reference validation
        self._validate_cross_refs(result)

        return result

    def _validate_cross_refs(self, result: ScanResult) -> None:
        """Check cross-references and add warnings for unused items."""
        # Warn about agents that are not used in any workflow
        used_agents: set[str] = set()
        for wf_name, compiled in result.workflows.items():
            for node_id in compiled._nodes:
                if node_id in result.agents:
                    used_agents.add(node_id)

        unused = set(result.agents.keys()) - used_agents
        for name in sorted(unused):
            result.warnings.append(
                f"Agent '{name}' is defined but not referenced in any workflow"
            )
