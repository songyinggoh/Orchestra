"""Tests for orchestra.discovery.validation (T-5.8)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from orchestra.cli.main import app
from orchestra.discovery.validation import (
    _edit_distance,
    did_you_mean,
    format_validation_report,
    validate_project,
)

runner = CliRunner()


# ---- Edit distance ----


def test_edit_distance_identical():
    assert _edit_distance("hello", "hello") == 0


def test_edit_distance_one_char():
    assert _edit_distance("cat", "bat") == 1


def test_edit_distance_insertion():
    assert _edit_distance("cat", "cats") == 1


def test_edit_distance_empty():
    assert _edit_distance("", "abc") == 3
    assert _edit_distance("abc", "") == 3


def test_edit_distance_completely_different():
    assert _edit_distance("abc", "xyz") == 3


# ---- did_you_mean ----


def test_did_you_mean_exact_match():
    assert did_you_mean("search", ["search", "fetch"]) == "search"


def test_did_you_mean_close_match():
    assert did_you_mean("serch", ["search", "fetch"]) == "search"


def test_did_you_mean_no_close_match():
    assert did_you_mean("zzzzz", ["search", "fetch"]) is None


def test_did_you_mean_empty_candidates():
    assert did_you_mean("search", []) is None


# ---- validate_project ----


def test_validate_project_empty(tmp_path: Path):
    result = validate_project(tmp_path)
    assert result.errors == []


def test_validate_project_with_errors(tmp_path: Path):
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "bad.yaml").write_text(
        "name: bad\ntools:\n  - missing\n", encoding="utf-8"
    )
    (tmp_path / "tools").mkdir()
    result = validate_project(tmp_path)
    assert len(result.errors) >= 1


# ---- format_validation_report ----


def test_format_report_empty_project(tmp_path: Path):
    result = validate_project(tmp_path)
    report = format_validation_report(result)
    assert "OK" in report
    assert "Tools (0)" in report
    assert "Agents (0)" in report
    assert "Workflows (0)" in report


def test_format_report_with_errors(tmp_path: Path):
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "bad.yaml").write_text(
        "name: bad\ntools:\n  - missing\n", encoding="utf-8"
    )
    (tmp_path / "tools").mkdir()
    result = validate_project(tmp_path)
    report = format_validation_report(result)
    assert "FAILED" in report
    assert "error" in report.lower()


# ---- CLI command ----


def test_validate_command_exists():
    result = runner.invoke(app, ["validate", "--help"])
    assert result.exit_code == 0


def test_validate_command_empty_project(tmp_path: Path):
    result = runner.invoke(app, ["validate", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "OK" in result.output


def test_validate_command_exits_nonzero_on_error(tmp_path: Path):
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "bad.yaml").write_text(
        "name: bad\ntools:\n  - missing\n", encoding="utf-8"
    )
    (tmp_path / "tools").mkdir()
    result = runner.invoke(app, ["validate", "--dir", str(tmp_path)])
    assert result.exit_code != 0
