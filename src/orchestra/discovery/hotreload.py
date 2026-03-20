"""Discovery-aware hot-reload extension (T-5.9).

Extends :class:`GraphHotReloader` to also watch agent YAML files.
On agent change, reloads the agent and re-compiles affected workflows.
On Python tool file change, logs a "restart required" warning.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
from watchfiles import awatch, Change

from orchestra.core.agent import BaseAgent
from orchestra.core.dynamic import SubgraphBuilder
from orchestra.discovery.agent_loader import load_agent
from orchestra.discovery.config import DefaultsSection
from orchestra.discovery.workflow_loader import load_workflow
from orchestra.tools.base import ToolWrapper

if TYPE_CHECKING:
    from orchestra.server.lifecycle import GraphRegistry

logger = structlog.get_logger(__name__)


class DiscoveryHotReloader:
    """Watches agents/, tools/, and workflows/ for changes.

    - Agent YAML changes: reload agent, re-compile affected workflows
    - Workflow YAML changes: re-compile workflow
    - Tool Python changes: log a restart-required warning
    """

    def __init__(
        self,
        agents_dir: Path,
        tools_dir: Path,
        workflows_dir: Path,
        registry: "GraphRegistry",
        agent_registry: dict[str, BaseAgent],
        tool_registry: dict[str, ToolWrapper],
        defaults: DefaultsSection | None = None,
        builder: SubgraphBuilder | None = None,
    ) -> None:
        self._agents_dir = Path(agents_dir)
        self._tools_dir = Path(tools_dir)
        self._workflows_dir = Path(workflows_dir)
        self._registry = registry
        self._agent_registry = agent_registry
        self._tool_registry = tool_registry
        self._defaults = defaults
        self._builder = builder or SubgraphBuilder()
        self._task: asyncio.Task[None] | None = None

        # Track which workflows reference which agents
        self._workflow_files: dict[str, Path] = {}

    async def start(self) -> None:
        """Start background file watchers."""
        if self._task is not None:
            return

        # Ensure directories exist
        for d in (self._agents_dir, self._tools_dir, self._workflows_dir):
            if not d.exists():
                d.mkdir(parents=True, exist_ok=True)

        # Index workflow files
        for yaml_file in list(self._workflows_dir.rglob("*.yaml")) + list(
            self._workflows_dir.rglob("*.yml")
        ):
            self._workflow_files[yaml_file.stem] = yaml_file

        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "discovery_hot_reloader_started",
            agents_dir=str(self._agents_dir),
            workflows_dir=str(self._workflows_dir),
        )

    async def stop(self) -> None:
        """Stop the background watcher."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("discovery_hot_reloader_stopped")

    async def _run_loop(self) -> None:
        """Watch all three directories for changes."""
        watch_dirs = [
            d for d in (self._agents_dir, self._tools_dir, self._workflows_dir)
            if d.exists()
        ]
        if not watch_dirs:
            return

        async for changes in awatch(*watch_dirs):
            for change_type, path_str in changes:
                path = Path(path_str)
                await self._handle_change(change_type, path)

    async def _handle_change(self, change_type: Any, path: Path) -> None:
        """Route a file change to the appropriate handler."""
        if path.suffix == ".py" and self._is_under(path, self._tools_dir):
            logger.warning(
                "tool_file_changed_restart_required",
                path=str(path),
                message="Tool Python file changed. Restart the server to pick up changes.",
            )
            return

        if path.suffix in (".yaml", ".yml"):
            if self._is_under(path, self._agents_dir):
                await self._reload_agent(path)
            elif self._is_under(path, self._workflows_dir):
                await self._reload_workflow(path)

    def _is_under(self, path: Path, directory: Path) -> bool:
        """Check if *path* is under *directory*."""
        try:
            path.resolve().relative_to(directory.resolve())
            return True
        except ValueError:
            return False

    async def _reload_agent(self, path: Path) -> None:
        """Reload an agent from YAML and re-compile affected workflows."""
        try:
            agent = load_agent(path, self._tool_registry, self._defaults)
            old_name = path.stem
            self._agent_registry[agent.name] = agent
            # Also update under old name if different
            if old_name != agent.name:
                self._agent_registry[old_name] = agent
            logger.info("agent_reloaded", name=agent.name, path=str(path))

            # Re-compile workflows that reference this agent
            await self._recompile_affected_workflows(agent.name)
        except Exception as exc:
            logger.error("agent_reload_failed", path=str(path), error=str(exc))

    async def _reload_workflow(self, path: Path) -> None:
        """Reload a workflow YAML and update the registry."""
        try:
            compiled = load_workflow(
                path,
                agent_registry=self._agent_registry,
                tool_registry=self._tool_registry,
                builder=self._builder,
            )
            name = compiled._name or path.stem
            self._registry.register(name, compiled)
            self._workflow_files[path.stem] = path
            logger.info("workflow_reloaded", name=name, path=str(path))
        except Exception as exc:
            logger.error("workflow_reload_failed", path=str(path), error=str(exc))

    async def _recompile_affected_workflows(self, agent_name: str) -> bool:
        """Re-compile all workflows that may reference the changed agent.

        Uses a stage-then-commit pattern to ensure atomicity:

        1. **Stage**: compile every affected workflow into a temporary list.
        2. **Commit**: only if ALL compilations succeed, register all new
           graphs in one pass.
        3. **Abort**: if any compilation fails, log the error and leave the
           registry untouched — old graphs remain in service.

        Returns:
            ``True`` when all affected workflows were successfully recompiled
            and registered; ``False`` when a compilation error prevented the
            update (no graphs were changed in that case).
        """
        # --- Pass 1: collect affected workflows and compile them into staging ---
        staged: list[tuple[str, object]] = []  # (registry_name, compiled_graph)

        for wf_stem, wf_path in self._workflow_files.items():
            if not wf_path.exists():
                continue

            content = wf_path.read_text(encoding="utf-8")
            if agent_name not in content:
                continue

            try:
                compiled = load_workflow(
                    wf_path,
                    agent_registry=self._agent_registry,
                    tool_registry=self._tool_registry,
                    builder=self._builder,
                )
                name = compiled._name or wf_stem
                staged.append((name, compiled))
            except Exception as exc:
                logger.error(
                    "workflow_recompile_failed",
                    workflow=wf_stem,
                    agent=agent_name,
                    error=str(exc),
                    detail=(
                        "No workflows were updated — old graphs remain in service "
                        "until all affected workflows compile successfully."
                    ),
                )
                # Abort: leave the registry completely unchanged.
                return False

        # --- Pass 2: all compilations succeeded — commit atomically ---
        for name, compiled in staged:
            self._registry.register(name, compiled)
            logger.info(
                "workflow_recompiled_after_agent_change",
                workflow=name,
                agent=agent_name,
            )

        return True
