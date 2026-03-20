"""Tests for orchestra.discovery.agent_loader (T-5.3)."""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from orchestra.discovery.agent_loader import load_agent
from orchestra.discovery.config import DefaultsSection
from orchestra.discovery.errors import AgentLoadError, ToolNotFoundError
from orchestra.tools.base import ToolWrapper


def _make_tool(name: str) -> ToolWrapper:
    """Create a minimal ToolWrapper for testing."""

    async def _noop(x: str) -> str:
        return x

    return ToolWrapper(_noop, name=name, description=f"Mock {name}")


# ---- Basic loading ----


def test_load_agent_basic(tmp_path: Path):
    yaml_text = """\
name: researcher
model: gpt-4o
system_prompt: You are a researcher.
temperature: 0.3
max_iterations: 5
"""
    agent_file = tmp_path / "researcher.yaml"
    agent_file.write_text(yaml_text, encoding="utf-8")

    agent = load_agent(agent_file, tool_registry={})
    assert agent.name == "researcher"
    assert agent.model == "gpt-4o"
    assert agent.system_prompt == "You are a researcher."
    assert agent.temperature == 0.3
    assert agent.max_iterations == 5
    assert agent.tools == []


def test_load_agent_name_from_filename(tmp_path: Path):
    agent_file = tmp_path / "writer.yaml"
    agent_file.write_text("system_prompt: Write things.\n", encoding="utf-8")

    agent = load_agent(agent_file, tool_registry={})
    assert agent.name == "writer"


# ---- Tool resolution ----


def test_load_agent_resolves_tools(tmp_path: Path):
    yaml_text = """\
name: agent_with_tools
tools:
  - search
  - read_url
"""
    agent_file = tmp_path / "agent.yaml"
    agent_file.write_text(yaml_text, encoding="utf-8")

    registry = {
        "search": _make_tool("search"),
        "read_url": _make_tool("read_url"),
    }
    agent = load_agent(agent_file, tool_registry=registry)
    assert len(agent.tools) == 2
    assert agent.tools[0].name == "search"
    assert agent.tools[1].name == "read_url"


def test_load_agent_missing_tool_error(tmp_path: Path):
    yaml_text = """\
name: broken
tools:
  - nonexistent_tool
"""
    agent_file = tmp_path / "broken.yaml"
    agent_file.write_text(yaml_text, encoding="utf-8")

    registry = {"search": _make_tool("search")}
    with pytest.raises(ToolNotFoundError, match="nonexistent_tool"):
        load_agent(agent_file, tool_registry=registry)


def test_load_agent_missing_tool_lists_available(tmp_path: Path):
    yaml_text = "name: x\ntools:\n  - missing\n"
    agent_file = tmp_path / "x.yaml"
    agent_file.write_text(yaml_text, encoding="utf-8")

    registry = {"alpha": _make_tool("alpha"), "beta": _make_tool("beta")}
    with pytest.raises(ToolNotFoundError, match="alpha.*beta"):
        load_agent(agent_file, tool_registry=registry)


# ---- Defaults cascade ----


def test_load_agent_uses_project_defaults(tmp_path: Path):
    agent_file = tmp_path / "minimal.yaml"
    agent_file.write_text("name: minimal\n", encoding="utf-8")

    defaults = DefaultsSection(model="claude-3-opus", temperature=0.1, max_iterations=3)
    agent = load_agent(agent_file, tool_registry={}, defaults=defaults)
    assert agent.model == "claude-3-opus"
    assert agent.temperature == 0.1
    assert agent.max_iterations == 3


def test_load_agent_yaml_overrides_defaults(tmp_path: Path):
    yaml_text = """\
name: override
model: gpt-4o
temperature: 0.9
"""
    agent_file = tmp_path / "override.yaml"
    agent_file.write_text(yaml_text, encoding="utf-8")

    defaults = DefaultsSection(model="claude-3-opus", temperature=0.1)
    agent = load_agent(agent_file, tool_registry={}, defaults=defaults)
    assert agent.model == "gpt-4o"  # agent YAML wins
    assert agent.temperature == 0.9  # agent YAML wins


def test_load_agent_falls_back_to_base_defaults(tmp_path: Path):
    agent_file = tmp_path / "bare.yaml"
    agent_file.write_text("name: bare\n", encoding="utf-8")

    agent = load_agent(agent_file, tool_registry={}, defaults=None)
    assert agent.model == "gpt-4o-mini"  # BaseAgent default
    assert agent.temperature == 0.7
    assert agent.max_iterations == 10


# ---- Error cases ----


def test_load_agent_empty_file_raises(tmp_path: Path):
    agent_file = tmp_path / "empty.yaml"
    agent_file.write_text("", encoding="utf-8")
    with pytest.raises(AgentLoadError, match="empty"):
        load_agent(agent_file, tool_registry={})


def test_load_agent_invalid_yaml_raises(tmp_path: Path):
    agent_file = tmp_path / "bad.yaml"
    agent_file.write_text("  invalid:\n bad: [yaml", encoding="utf-8")
    with pytest.raises(AgentLoadError, match="Cannot parse"):
        load_agent(agent_file, tool_registry={})


# ---- Additional coverage ----


def test_load_agent_multiline_system_prompt(tmp_path: Path):
    """Multiline YAML literal block scalars must be preserved in full."""
    yaml_text = """\
name: analyst
system_prompt: |
  You are a research analyst.
  Be thorough and cite your sources.
  Always verify facts.
"""
    agent_file = tmp_path / "analyst.yaml"
    agent_file.write_text(yaml_text, encoding="utf-8")

    agent = load_agent(agent_file, tool_registry={})
    assert "Be thorough and cite your sources." in agent.system_prompt
    assert "Always verify facts." in agent.system_prompt


def test_load_agent_empty_tools_list(tmp_path: Path):
    """An explicit empty tools list must result in an agent with no tools."""
    yaml_text = "name: notoolsagent\ntools: []\n"
    agent_file = tmp_path / "notoolsagent.yaml"
    agent_file.write_text(yaml_text, encoding="utf-8")

    agent = load_agent(agent_file, tool_registry={})
    assert list(agent.tools) == []


def test_load_agent_tool_order_preserved(tmp_path: Path):
    """Tools must be attached in the order listed in the YAML file."""
    yaml_text = "name: ordered\ntools:\n  - beta\n  - alpha\n  - gamma\n"
    agent_file = tmp_path / "ordered.yaml"
    agent_file.write_text(yaml_text, encoding="utf-8")

    registry = {
        "alpha": _make_tool("alpha"),
        "beta": _make_tool("beta"),
        "gamma": _make_tool("gamma"),
    }
    agent = load_agent(agent_file, tool_registry=registry)
    names = [t.name for t in agent.tools]
    assert names == ["beta", "alpha", "gamma"]


def test_load_agent_missing_tool_names_all_listed(tmp_path: Path):
    """When multiple tools are missing, all missing names should appear in the error."""
    yaml_text = "name: multi_miss\ntools:\n  - no_such_tool_1\n  - no_such_tool_2\n"
    agent_file = tmp_path / "multi_miss.yaml"
    agent_file.write_text(yaml_text, encoding="utf-8")

    with pytest.raises(ToolNotFoundError) as exc_info:
        load_agent(agent_file, tool_registry={})
    # At least one of the missing tool names should appear
    msg = str(exc_info.value)
    assert "no_such_tool_1" in msg or "no_such_tool_2" in msg


def test_load_agent_max_iterations_from_yaml(tmp_path: Path):
    """max_iterations specified in YAML must be set on the resulting agent."""
    yaml_text = "name: limited\nmax_iterations: 2\n"
    agent_file = tmp_path / "limited.yaml"
    agent_file.write_text(yaml_text, encoding="utf-8")

    agent = load_agent(agent_file, tool_registry={}, defaults=None)
    assert agent.max_iterations == 2
