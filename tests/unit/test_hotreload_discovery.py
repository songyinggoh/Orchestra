"""Tests for orchestra.discovery.hotreload (T-5.9)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

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
    agent_file.write_text("name: test_agent\nsystem_prompt: Hello.\n", encoding="utf-8")

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


# ---- Atomicity tests (Gap-6 fix) ----

_WORKFLOW_YAML_TEMPLATE = """\
name: {name}
nodes:
  {agent}:
    type: agent
    ref: {agent}
    output_key: out
edges:
  - source: {agent}
    target: __end__
entry_point: {agent}
"""


def _make_reloader(tmp_path: Path, agent_name: str) -> tuple[DiscoveryHotReloader, MagicMock]:
    """Helper: build a DiscoveryHotReloader with a pre-configured registry mock."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir(exist_ok=True)
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir(exist_ok=True)
    registry = _make_registry()
    agent_registry = {agent_name: BaseAgent(name=agent_name)}
    reloader = DiscoveryHotReloader(
        agents_dir=agents_dir,
        tools_dir=tmp_path / "tools",
        workflows_dir=wf_dir,
        registry=registry,
        agent_registry=agent_registry,
        tool_registry={},
    )
    return reloader, registry


@pytest.mark.asyncio
async def test_atomic_commit_both_workflows_registered(tmp_path: Path):
    """Test 1: Two workflows reference same agent; both compile OK → both registered."""
    reloader, registry = _make_reloader(tmp_path, "shared_agent")
    wf_dir = tmp_path / "workflows"

    # Create two valid workflow YAML files that both reference 'shared_agent'
    for wf_name in ("wf_alpha", "wf_beta"):
        (wf_dir / f"{wf_name}.yaml").write_text(
            _WORKFLOW_YAML_TEMPLATE.format(name=wf_name, agent="shared_agent"),
            encoding="utf-8",
        )
        reloader._workflow_files[wf_name] = wf_dir / f"{wf_name}.yaml"

    result = await reloader._recompile_affected_workflows("shared_agent")

    assert result is True, "Expected success when all workflows compile"
    assert registry.register.call_count == 2, (
        "Both workflows should be registered after a fully successful recompile"
    )
    registered_names = {call[0][0] for call in registry.register.call_args_list}
    assert registered_names == {"wf_alpha", "wf_beta"}


@pytest.mark.asyncio
async def test_atomic_abort_neither_workflow_registered_on_failure(tmp_path: Path):
    """Test 2: Two workflows reference same agent; one fails → NEITHER is updated."""
    reloader, registry = _make_reloader(tmp_path, "shared_agent")
    wf_dir = tmp_path / "workflows"

    # wf_good: valid YAML that should compile fine
    (wf_dir / "wf_good.yaml").write_text(
        _WORKFLOW_YAML_TEMPLATE.format(name="wf_good", agent="shared_agent"),
        encoding="utf-8",
    )
    reloader._workflow_files["wf_good"] = wf_dir / "wf_good.yaml"

    # wf_bad: deliberately malformed YAML that will fail to compile
    (wf_dir / "wf_bad.yaml").write_text(
        "name: wf_bad\nnodes: {shared_agent: !!python/object/apply:os.system ['echo pwned']}\n",
        encoding="utf-8",
    )
    reloader._workflow_files["wf_bad"] = wf_dir / "wf_bad.yaml"

    result = await reloader._recompile_affected_workflows("shared_agent")

    assert result is False, "Expected failure when any workflow fails to compile"
    (
        registry.register.assert_not_called(),
        ("No workflow should be registered when the batch compilation fails"),
    )


@pytest.mark.asyncio
async def test_no_op_when_no_workflows_reference_agent(tmp_path: Path):
    """Test 3: Agent changes but no workflow references it → no-op, no errors."""
    reloader, registry = _make_reloader(tmp_path, "unused_agent")
    wf_dir = tmp_path / "workflows"

    # A workflow that does NOT mention 'unused_agent'
    (wf_dir / "wf_other.yaml").write_text(
        _WORKFLOW_YAML_TEMPLATE.format(name="wf_other", agent="other_agent"),
        encoding="utf-8",
    )
    reloader._workflow_files["wf_other"] = wf_dir / "wf_other.yaml"

    result = await reloader._recompile_affected_workflows("unused_agent")

    assert result is True, "No-op counts as success — nothing to update"
    (
        registry.register.assert_not_called(),
        ("Registry must not be touched when no workflows reference the changed agent"),
    )
