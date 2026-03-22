"""Tests for the ``orchestra up`` CLI command (T-5.6)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from orchestra.cli.main import app

runner = CliRunner()


def _setup_project(tmp_path: Path) -> Path:
    """Create a minimal valid project."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / "agents").mkdir()
    (project / "tools").mkdir()
    (project / "workflows").mkdir()
    return project


def test_up_command_exists():
    """The 'up' command should be registered on the CLI app."""
    result = runner.invoke(app, ["up", "--help"])
    assert result.exit_code == 0
    assert "auto-discover" in result.output.lower() or "Auto-discover" in result.output


@patch("uvicorn.run")
def test_up_scans_project(mock_run: MagicMock, tmp_path: Path):
    """up should scan the project dir and call uvicorn.run."""
    project = _setup_project(tmp_path)

    result = runner.invoke(app, ["up", "--dir", str(project)])
    assert result.exit_code == 0
    assert "Scanning project" in result.output
    mock_run.assert_called_once()


@patch("uvicorn.run")
def test_up_reports_discovery_counts(mock_run: MagicMock, tmp_path: Path):
    """up should print tool/agent/workflow counts."""
    project = _setup_project(tmp_path)

    result = runner.invoke(app, ["up", "--dir", str(project)])
    assert "Tools:" in result.output
    assert "Agents:" in result.output
    assert "Workflows:" in result.output


def test_up_exits_on_errors(tmp_path: Path):
    """up should exit non-zero when discovery finds errors."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / "agents").mkdir()
    (project / "tools").mkdir()
    (project / "workflows").mkdir()
    # Agent referencing a tool that doesn't exist
    (project / "agents" / "bad.yaml").write_text(
        "name: bad\ntools:\n  - nonexistent\n", encoding="utf-8"
    )

    result = runner.invoke(app, ["up", "--dir", str(project)])
    assert result.exit_code != 0
    assert "error" in result.output.lower()


@patch("uvicorn.run")
def test_up_registers_workflows(mock_run: MagicMock, tmp_path: Path):
    """Discovered workflows should be registered before server starts."""
    project = _setup_project(tmp_path)
    (project / "agents" / "a.yaml").write_text("name: a\n", encoding="utf-8")
    (project / "workflows" / "wf.yaml").write_text(
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

    result = runner.invoke(app, ["up", "--dir", str(project)])
    assert result.exit_code == 0
    assert "Registered workflow" in result.output
