"""Hot-reloading for graph definitions (T-4.12).

Watches YAML files and atomically updates the GraphRegistry
without disrupting in-flight runs.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from watchfiles import awatch

from orchestra.core.dynamic import SubgraphBuilder, load_graph_yaml

if TYPE_CHECKING:
    from orchestra.server.lifecycle import GraphRegistry

logger = structlog.get_logger(__name__)


class GraphHotReloader:
    """Watches a directory for YAML graph changes and updates the registry."""

    def __init__(
        self, watch_dir: str | Path, registry: GraphRegistry, builder: SubgraphBuilder | None = None
    ) -> None:
        self._watch_dir = Path(watch_dir)
        self._registry = registry
        self._builder = builder or SubgraphBuilder()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the background watcher task."""
        if self._task is not None:
            return

        if not self._watch_dir.exists():
            self._watch_dir.mkdir(parents=True, exist_ok=True)

        self._task = asyncio.create_task(self._run_loop())
        logger.info("hot_reloader_started", dir=str(self._watch_dir))

    async def stop(self) -> None:
        """Stop the background watcher task."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("hot_reloader_stopped")

    async def _run_loop(self) -> None:
        """Main watch loop."""
        async for changes in awatch(self._watch_dir):
            for change_type, path_str in changes:
                path = Path(path_str)
                if path.suffix in (".yaml", ".yml"):
                    logger.info("graph_file_changed", path=path_str, type=change_type.name)
                    await self._reload_graph(path)

    async def _reload_graph(self, path: Path) -> None:
        """Load a graph from disk and swap it into the registry."""
        try:
            yaml_str = path.read_text(encoding="utf-8")
            compiled = load_graph_yaml(yaml_str, builder=self._builder)

            # Use filename (minus extension) as registry name if not set in YAML
            name = compiled._name or path.stem

            # Atomic registry swap
            self._registry.register(name, compiled)
            logger.info("graph_reloaded_successfully", name=name)
        except Exception as e:
            logger.error("graph_reload_failed", path=str(path), error=str(e))
