"""Tests for the enhanced ``orchestra init`` command (T-5.7)."""

from __future__ import annotations

import pytest
from pathlib import Path
from typer.testing import CliRunner

from orchestra.cli.main import app

runner = CliRunner()


def test_init_creates_convention_structure(tmp_path: Path):
    """init should create agents/, tools/, workflows/, lib/ directories."""
    result = runner.invoke(app, ["init", "myproj", "--directory", str(tmp_path)])
    assert result.exit_code == 0
    project = tmp_path / "myproj"
    assert (project / "agents").is_dir()
    assert (project / "tools").is_dir()
    assert (project / "workflows").is_dir()
    assert (project / "lib").is_dir()


def test_init_creates_orchestra_yaml(tmp_path: Path):
    result = runner.invoke(app, ["init", "myproj", "--directory", str(tmp_path)])
    assert result.exit_code == 0
    yaml_path = tmp_path / "myproj" / "orchestra.yaml"
    assert yaml_path.exists()
    content = yaml_path.read_text(encoding="utf-8")
    assert "myproj" in content
    assert "defaults:" in content


def test_init_creates_env_file(tmp_path: Path):
    result = runner.invoke(app, ["init", "myproj", "--directory", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "myproj" / ".env").exists()


def test_init_creates_example_agent(tmp_path: Path):
    result = runner.invoke(app, ["init", "myproj", "--directory", str(tmp_path)])
    assert result.exit_code == 0
    agent_file = tmp_path / "myproj" / "agents" / "assistant.yaml"
    assert agent_file.exists()
    content = agent_file.read_text(encoding="utf-8")
    assert "name: assistant" in content
    assert "tools:" in content


def test_init_creates_example_tool(tmp_path: Path):
    result = runner.invoke(app, ["init", "myproj", "--directory", str(tmp_path)])
    assert result.exit_code == 0
    tool_file = tmp_path / "myproj" / "tools" / "greet.py"
    assert tool_file.exists()
    content = tool_file.read_text(encoding="utf-8")
    assert "@tool" in content
    assert "async def greet" in content


def test_init_creates_example_workflow(tmp_path: Path):
    result = runner.invoke(app, ["init", "myproj", "--directory", str(tmp_path)])
    assert result.exit_code == 0
    wf_file = tmp_path / "myproj" / "workflows" / "hello.yaml"
    assert wf_file.exists()
    content = wf_file.read_text(encoding="utf-8")
    assert "entry_point:" in content
    assert "__end__" in content


def test_init_output_mentions_orchestra_up(tmp_path: Path):
    """init should suggest running orchestra up."""
    result = runner.invoke(app, ["init", "myproj", "--directory", str(tmp_path)])
    assert "orchestra up" in result.output
