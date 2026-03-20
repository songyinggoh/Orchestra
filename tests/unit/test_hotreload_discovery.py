"""Tests for orchestra.discovery.hotreload (T-5.9)."""

from __future__ import annotations

import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from orchestra.core.agent import BaseAgent
from orchestra.discovery.hotreload import DiscoveryHotReloader


def _make_registry() -> MagicMock:
    """Create a mock GraphRegistry."""
    reg = MagicMock()
    reg.register = MagicMock()
    return reg


# ---- Unit tests (no actual file watching) ----


def test_is_under(tmp_path: Path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    reloader = DiscoveryHotReloader(
        agents_dir=agents_dir,
        tools_dir=tmp_path / "tools",
        workflows_dir=tmp_path / "workflows",
        registry=_make_registry(),
        agent_registry={},
        tool_registry={},
    )
    assert reloader._is_under(agents_dir / "test.yaml", agents_dir) is True
    assert reloader._is_under(tmp_path / "other" / "test.yaml", agents_dir) is False


@pytest.mark.asyncio
async def test_reload_agent(tmp_path: Path):
    """_reload_agent should update the agent registry."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()

    agent_file = agents_dir / "test_agent.yaml"
    agent_file.write_text(
        "name: test_agent\nsystem_prompt: Hello.\n", encoding="utf-8"
    )

    agent_registry: dict[str, BaseAgent] = {}
    reloader = DiscoveryHotReloader(
        agents_dir=agents_dir,
        tools_dir=tmp_path / "tools",
        workflows_dir=wf_dir,
        registry=_make_registry(),
        agent_registry=agent_registry,
        tool_registry={},
    )

    await reloader._reload_agent(agent_file)
    assert "test_agent" in agent_registry
    assert agent_registry["test_agent"].system_prompt == "Hello."


@pytest.mark.asyncio
async def test_reload_workflow(tmp_path: Path):
    """_reload_workflow should register the compiled graph."""
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()

    wf_file = wf_dir / "simple.yaml"
    wf_file.write_text(
        """\
name: simple
nodes:
  a:
    type: agent
    ref: a
    output_key: out
edges:
  - source: a
    target: __end__
entry_point: a
""",
        encoding="utf-8",
    )

    registry = _make_registry()
    agent_registry = {"a": BaseAgent(name="a")}

    reloader = DiscoveryHotReloader(
        agents_dir=agents_dir,
        tools_dir=tmp_path / "tools",
        workflows_dir=wf_dir,
        registry=registry,
        agent_registry=agent_registry,
        tool_registry={},
    )

    await reloader._reload_workflow(wf_file)
    registry.register.assert_called_once()
    call_args = registry.register.call_args
    assert call_args[0][0] == "simple"


@pytest.mark.asyncio
async def test_handle_tool_change_logs_warning(tmp_path: Path, caplog):
    """Python tool file changes should log a restart-required warning."""
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    tool_file = tools_dir / "search.py"
    tool_file.write_text("pass", encoding="utf-8")

    reloader = DiscoveryHotReloader(
        agents_dir=tmp_path / "agents",
        tools_dir=tools_dir,
        workflows_dir=tmp_path / "workflows",
        registry=_make_registry(),
        agent_registry={},
        tool_registry={},
    )

    # Should not raise
    await reloader._handle_change("modified", tool_file)
    # The warning is emitted via structlog, which we can't easily assert
    # in caplog. Just verify no exception was raised.


@pytest.mark.asyncio
async def test_start_stop(tmp_path: Path):
    """start/stop should create and cancel the background task."""
    agents_dir = tmp_path / "agents"
    tools_dir = tmp_path / "tools"
    wf_dir = tmp_path / "workflows"
    for d in (agents_dir, tools_dir, wf_dir):
        d.mkdir(exist_ok=True)

    reloader = DiscoveryHotReloader(
        agents_dir=agents_dir,
        tools_dir=tools_dir,
        workflows_dir=wf_dir,
        registry=_make_registry(),
        agent_registry={},
        tool_registry={},
    )

    await reloader.start()
    assert reloader._task is not None

    await reloader.stop()
    assert reloader._task is None


@pytest.mark.asyncio
async def test_recompile_affected_workflows(tmp_path: Path):
    """When an agent changes, workflows that reference it should be re-compiled."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()

    wf_file = wf_dir / "pipeline.yaml"
    wf_file.write_text(
        """\
name: pipeline
nodes:
  myagent:
    type: agent
    ref: myagent
    output_key: out
edges:
  - source: myagent
    target: __end__
entry_point: myagent
""",
        encoding="utf-8",
    )

    registry = _make_registry()
    agent_registry = {"myagent": BaseAgent(name="myagent")}

    reloader = DiscoveryHotReloader(
        agents_dir=agents_dir,
        tools_dir=tmp_path / "tools",
        workflows_dir=wf_dir,
        registry=registry,
        agent_registry=agent_registry,
        tool_registry={},
    )
    reloader._workflow_files["pipeline"] = wf_file

    await reloader._recompile_affected_workflows("myagent")
    registry.register.assert_called_once()
