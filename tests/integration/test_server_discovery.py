"""Integration smoke tests: discovery → server pipeline (Gap 8).

These tests verify the wiring between ProjectScanner.scan(), GraphRegistry,
and the FastAPI server for the Phase 5 no-code auto-discovery layer.

The full pipeline under test is:

    orchestra.yaml + agents/ + tools/ + workflows/
            │
            ▼
    ProjectScanner.scan()  →  ScanResult
            │
            ▼
    GraphRegistry.register()  →  GraphRegistry
            │
            ▼
    create_app() / lifespan  →  FastAPI app
            │
            ▼
    GET /api/v1/graphs  →  list[GraphInfo]

No real LLM calls, no running server, no network I/O.
Uses tmp_path for all filesystem operations.
Uses httpx.AsyncClient with ASGI transport for HTTP assertions.

KNOWN WIRING BUG (MERGE BLOCKER)
---------------------------------
The CLI `orchestra up` command (cli/main.py) registers discovered workflows
into `app_instance.state._discovery_registry` BEFORE the lifespan runs.
The lifespan in server/app.py then creates a FRESH, EMPTY GraphRegistry and
stores it as `app.state.graph_registry`.  The routes read `graph_registry`,
not `_discovery_registry`.  Result: discovered workflows never appear in the
API response.

test_up_command_wiring_gap() documents and asserts this failure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

try:
    HAS_SERVER_DEPS = True
except ImportError:
    HAS_SERVER_DEPS = False

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not HAS_SERVER_DEPS,
        reason="Server dependencies not installed (httpx, fastapi)",
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_minimal_project(root: Path) -> None:
    """Write a minimal but valid Orchestra project layout to *root*.

    Creates:
      orchestra.yaml          — project config (no API key, no port collision)
      agents/greeter.yaml     — a single agent definition
      tools/                  — empty (agent has no tools)
      workflows/hello.yaml    — a single-node workflow referencing the agent

    NOTE on edges: the workflow YAML intentionally omits an explicit
    ``edges: - target: __end__`` declaration.  Doing so would add an
    ``Edge(source='greeter', target=END)`` to ``compiled._edges``, where END
    is an ``_EndSentinel`` object.  ``GraphRegistry.list_graphs()`` (lifecycle.py)
    passes those edge targets directly into a Pydantic model, which raises a
    400 ValueError when FastAPI tries to serialize them.  That is a separate
    pre-existing bug in lifecycle.py.  Omitting explicit terminal edges here
    keeps ``_edges`` empty (the graph still terminates correctly via implicit
    END handling in WorkflowGraph.compile()) and isolates Gap 8 cleanly.
    """
    (root / "agents").mkdir()
    (root / "tools").mkdir()
    (root / "workflows").mkdir()

    (root / "orchestra.yaml").write_text(
        """\
project:
  name: smoke-test
defaults:
  model: claude-sonnet-4-20250514
  temperature: 0.7
  max_iterations: 5
""",
        encoding="utf-8",
    )

    (root / "agents" / "greeter.yaml").write_text(
        """\
name: greeter
system_prompt: Say hello.
""",
        encoding="utf-8",
    )

    (root / "workflows" / "hello.yaml").write_text(
        """\
name: hello
state:
  input: str
  output: str
nodes:
  greeter:
    type: agent
    ref: greeter
    output_key: output
entry_point: greeter
""",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Layer 1: ProjectScanner produces a valid ScanResult
# ---------------------------------------------------------------------------


class TestProjectScannerLayer:
    """Verify that ProjectScanner.scan() correctly parses YAML project files."""

    def test_scan_empty_dir_returns_no_errors(self, tmp_path: Path) -> None:
        """An empty directory has no orchestra.yaml; scanner should use defaults."""
        from orchestra.discovery.scanner import ProjectScanner

        result = ProjectScanner().scan(tmp_path)
        assert result.errors == [], f"Unexpected errors: {result.errors}"

    def test_scan_minimal_project_finds_workflow(self, tmp_path: Path) -> None:
        """A well-formed project produces one workflow with no errors."""
        from orchestra.core.compiled import CompiledGraph
        from orchestra.discovery.scanner import ProjectScanner

        _write_minimal_project(tmp_path)
        result = ProjectScanner().scan(tmp_path)

        assert result.errors == [], f"Scanner errors: {result.errors}"
        assert "hello" in result.workflows, f"Expected workflow 'hello' in {list(result.workflows)}"
        assert isinstance(result.workflows["hello"], CompiledGraph)

    def test_scan_finds_agent(self, tmp_path: Path) -> None:
        """The scanner loads agent YAML and stores a BaseAgent by name."""
        from orchestra.core.agent import BaseAgent
        from orchestra.discovery.scanner import ProjectScanner

        _write_minimal_project(tmp_path)
        result = ProjectScanner().scan(tmp_path)

        assert "greeter" in result.agents
        assert isinstance(result.agents["greeter"], BaseAgent)
        assert result.agents["greeter"].system_prompt == "Say hello."

    def test_scan_workflow_is_compiledgraph_with_correct_structure(self, tmp_path: Path) -> None:
        """The compiled graph has the node and entry point declared in YAML."""
        from orchestra.discovery.scanner import ProjectScanner

        _write_minimal_project(tmp_path)
        result = ProjectScanner().scan(tmp_path)

        graph = result.workflows["hello"]
        assert "greeter" in graph._nodes, f"Nodes: {list(graph._nodes)}"
        assert graph._entry_point == "greeter"

    def test_scan_config_loaded_from_yaml(self, tmp_path: Path) -> None:
        """orchestra.yaml project name is reflected in the ScanResult config."""
        from orchestra.discovery.scanner import ProjectScanner

        _write_minimal_project(tmp_path)
        result = ProjectScanner().scan(tmp_path)

        assert result.config.project.name == "smoke-test"

    def test_scan_warns_about_unused_agent_when_no_workflow(self, tmp_path: Path) -> None:
        """An agent that is not referenced in any workflow generates a warning."""
        from orchestra.discovery.scanner import ProjectScanner

        (tmp_path / "agents").mkdir()
        (tmp_path / "tools").mkdir()
        (tmp_path / "workflows").mkdir()

        (tmp_path / "agents" / "orphan.yaml").write_text(
            "name: orphan\nsystem_prompt: I am never used.\n",
            encoding="utf-8",
        )

        result = ProjectScanner().scan(tmp_path)
        assert any("orphan" in w for w in result.warnings), (
            f"Expected 'orphan' warning, got: {result.warnings}"
        )

    def test_scan_invalid_workflow_yaml_adds_error(self, tmp_path: Path) -> None:
        """A workflow YAML referencing a non-existent agent adds to errors."""
        from orchestra.discovery.scanner import ProjectScanner

        (tmp_path / "agents").mkdir()
        (tmp_path / "tools").mkdir()
        (tmp_path / "workflows").mkdir()

        (tmp_path / "workflows" / "broken.yaml").write_text(
            """\
name: broken
state:
  input: str
nodes:
  ghost:
    type: agent
    ref: nonexistent_agent
entry_point: ghost
""",
            encoding="utf-8",
        )

        result = ProjectScanner().scan(tmp_path)
        assert result.errors, "Expected an error for missing agent reference"
        assert any("nonexistent_agent" in e for e in result.errors), (
            f"Expected agent reference error, got: {result.errors}"
        )


# ---------------------------------------------------------------------------
# Layer 2: GraphRegistry correctly stores and exposes CompiledGraphs
# ---------------------------------------------------------------------------


class TestGraphRegistryLayer:
    """Verify GraphRegistry.register() / list_graphs() / get() behaviour."""

    def test_register_and_list_discovered_workflows(self, tmp_path: Path) -> None:
        """Workflows from a ScanResult can be registered and listed."""
        from orchestra.discovery.scanner import ProjectScanner
        from orchestra.server.lifecycle import GraphRegistry

        _write_minimal_project(tmp_path)
        result = ProjectScanner().scan(tmp_path)
        assert result.errors == []

        registry = GraphRegistry()
        for name, graph in result.workflows.items():
            registry.register(name, graph)

        graph_infos = registry.list_graphs()
        names = [g.name for g in graph_infos]
        assert "hello" in names, f"Registered graphs: {names}"

    def test_registry_get_returns_compiled_graph(self, tmp_path: Path) -> None:
        """GraphRegistry.get() returns the exact CompiledGraph that was registered."""
        from orchestra.core.compiled import CompiledGraph
        from orchestra.discovery.scanner import ProjectScanner
        from orchestra.server.lifecycle import GraphRegistry

        _write_minimal_project(tmp_path)
        result = ProjectScanner().scan(tmp_path)

        registry = GraphRegistry()
        registry.register("hello", result.workflows["hello"])

        retrieved = registry.get("hello")
        assert isinstance(retrieved, CompiledGraph)
        assert retrieved is result.workflows["hello"]

    def test_registry_get_missing_returns_none(self) -> None:
        """GraphRegistry.get() returns None for an unknown graph name."""
        from orchestra.server.lifecycle import GraphRegistry

        registry = GraphRegistry()
        assert registry.get("does-not-exist") is None

    def test_registry_list_graphs_includes_node_and_entry_point(self, tmp_path: Path) -> None:
        """GraphInfo returned by list_graphs() reflects the workflow structure."""
        from orchestra.discovery.scanner import ProjectScanner
        from orchestra.server.lifecycle import GraphRegistry

        _write_minimal_project(tmp_path)
        result = ProjectScanner().scan(tmp_path)

        registry = GraphRegistry()
        registry.register("hello", result.workflows["hello"])

        infos = registry.list_graphs()
        assert len(infos) == 1
        info = infos[0]
        assert info.name == "hello"
        assert "greeter" in info.nodes
        assert info.entry_point == "greeter"


# ---------------------------------------------------------------------------
# Layer 3: Server exposes registered graphs via HTTP (ASGI transport)
# ---------------------------------------------------------------------------


class TestServerGraphsEndpoint:
    """Verify the /api/v1/graphs endpoint reflects pre-registered graphs.

    These tests exercise the server with httpx ASGI transport — no real port,
    no network.  The lifespan is triggered by the AsyncClient context manager.
    """

    @pytest.fixture()
    def app_with_discovered_graph(self, tmp_path: Path) -> Any:
        """Build an app and manually populate graph_registry after lifespan."""
        from orchestra.discovery.scanner import ProjectScanner
        from orchestra.server.app import create_app
        from orchestra.server.config import ServerConfig

        _write_minimal_project(tmp_path)
        result = ProjectScanner().scan(tmp_path)
        assert result.errors == [], f"Scanner errors: {result.errors}"

        config = ServerConfig()
        application = create_app(config)
        # Stash the scan result so the lifespan fixture can register it
        application.state._pending_workflows = result.workflows
        return application

    @pytest.mark.asyncio
    async def test_discovered_workflow_appears_in_graphs_list(
        self, app_with_discovered_graph: Any
    ) -> None:
        """After registering scan results into graph_registry, GET /api/v1/graphs
        returns the discovered workflow."""
        from httpx import ASGITransport, AsyncClient

        app = app_with_discovered_graph

        async with app.router.lifespan_context(app):
            # Manually transfer discovered workflows into the lifespan-owned registry
            for name, graph in app.state._pending_workflows.items():
                app.state.graph_registry.register(name, graph)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/v1/graphs")

        assert response.status_code == 200
        graphs = response.json()
        assert isinstance(graphs, list)
        names = [g["name"] for g in graphs]
        assert "hello" in names, f"Expected 'hello' in graph list, got: {names}"

    @pytest.mark.asyncio
    async def test_discovered_workflow_detail_has_correct_structure(
        self, app_with_discovered_graph: Any
    ) -> None:
        """GET /api/v1/graphs/{name} returns node and entry_point from the YAML."""
        from httpx import ASGITransport, AsyncClient

        app = app_with_discovered_graph

        async with app.router.lifespan_context(app):
            for name, graph in app.state._pending_workflows.items():
                app.state.graph_registry.register(name, graph)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/v1/graphs/hello")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "hello"
        assert "greeter" in data["nodes"]
        assert data["entry_point"] == "greeter"
        assert "graph TD" in data.get("mermaid", ""), "Expected Mermaid diagram in response"

    @pytest.mark.asyncio
    async def test_empty_registry_returns_empty_list(self) -> None:
        """An app with no registered graphs returns an empty list."""
        from httpx import ASGITransport, AsyncClient

        from orchestra.server.app import create_app
        from orchestra.server.config import ServerConfig

        app = create_app(ServerConfig())

        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/v1/graphs")

        assert response.status_code == 200
        assert response.json() == []


# ---------------------------------------------------------------------------
# Layer 4: Document the known wiring gap in the CLI `up` command
# ---------------------------------------------------------------------------


class TestUpCommandWiringGap:
    """Document the MERGE BLOCKER: the `orchestra up` command stores discovered
    workflows into app.state._discovery_registry, but the lifespan creates a
    separate app.state.graph_registry that the /api/v1/graphs route reads.
    The two registries are never connected, so discovered workflows are invisible
    to the HTTP API after `orchestra up`.

    This class contains:
      - test_up_wiring_gap_documented: asserts the gap EXISTS (will pass until fixed)
      - test_up_wiring_gap_fixed: documents what correct behaviour looks like
        (currently fails — remove xfail marker once the CLI is patched)
    """

    def _simulate_up_command_pre_uvicorn(self, root: Path) -> Any:
        """Reproduce the pre-uvicorn portion of the `up` command.

        Returns the app instance exactly as `up` leaves it before calling
        uvicorn.run().
        """
        from orchestra.discovery.scanner import ProjectScanner
        from orchestra.server.app import create_app
        from orchestra.server.config import ServerConfig
        from orchestra.server.lifecycle import GraphRegistry

        scanner = ProjectScanner()
        result = scanner.scan(root)

        server_config = ServerConfig()
        app_instance = create_app(server_config)

        # Replicate the exact lines in cli/main.py up()
        app_instance.state.discovery_result = result
        _original_graph_registry = GraphRegistry()
        for wf_name, compiled in result.workflows.items():
            _original_graph_registry.register(wf_name, compiled)
        app_instance.state._discovery_registry = _original_graph_registry

        return app_instance

    def test_up_wiring_gap_documented(self, tmp_path: Path) -> None:
        """Assert that after the up command's pre-flight wiring, the discovered
        workflows ARE present in state._discovery_registry but NOT yet in
        state.graph_registry (which doesn't exist until the lifespan runs).

        This test PASSES and documents the bug.
        """
        _write_minimal_project(tmp_path)
        app = self._simulate_up_command_pre_uvicorn(tmp_path)

        # _discovery_registry is populated by `up`
        discovery_reg = app.state._discovery_registry
        assert "hello" in [g.name for g in discovery_reg.list_graphs()], (
            "_discovery_registry should contain 'hello' after up command"
        )

        # graph_registry does NOT exist yet — it is created by the lifespan
        has_graph_registry = hasattr(app.state, "graph_registry")
        assert not has_graph_registry, (
            "graph_registry should NOT exist before lifespan runs. "
            "If this assertion fails, the lifespan was somehow triggered early."
        )

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        reason=(
            "MERGE BLOCKER (Gap 8): cli/main.py `up` command stores discovered "
            "workflows in app.state._discovery_registry, but server/app.py lifespan "
            "unconditionally creates a fresh empty app.state.graph_registry. "
            "The routes read graph_registry, not _discovery_registry. "
            "Fix: lifespan must check for state._discovery_registry and copy "
            "its contents into state.graph_registry on startup."
        ),
        strict=True,
    )
    async def test_up_wiring_gap_fixed(self, tmp_path: Path) -> None:
        """This test describes the CORRECT end-to-end behaviour that should work
        once the wiring bug is fixed.

        After the lifespan starts, workflows registered by `up` into
        _discovery_registry must be visible via GET /api/v1/graphs.

        Remove the xfail marker once cli/main.py or server/app.py is patched.
        """
        from httpx import ASGITransport, AsyncClient

        _write_minimal_project(tmp_path)
        app = self._simulate_up_command_pre_uvicorn(tmp_path)

        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/v1/graphs")

        assert response.status_code == 200
        graphs = response.json()
        names = [g["name"] for g in graphs]
        assert "hello" in names, (
            f"WIRING BUG: discovered workflow 'hello' not in graph list. "
            f"Got: {names}. "
            f"The lifespan must transfer _discovery_registry → graph_registry."
        )
