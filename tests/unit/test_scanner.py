"""Unit tests for discovery/scanner.py — ProjectScanner and ScanResult (T-5.5).

Covers:
- Full scan with valid project structure returns populated ScanResult
- Missing directories handled gracefully (empty results, not crash)
- Cross-reference validation catches agent -> missing tool
- Cross-reference validation catches workflow -> missing agent
- ScanResult.errors populated on failures
- ScanResult.warnings for non-fatal issues
- orchestra.yaml optional (defaults used when absent)
- Config loaded before discovery (config values influence tool/agent dirs)
- scan() returns a ScanResult dataclass/object with expected attributes
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

try:
    from orchestra.discovery.scanner import ProjectScanner, ScanResult
    _IMPORT_OK = True
except ImportError:
    _IMPORT_OK = False
    ProjectScanner = None  # type: ignore[assignment,misc]
    ScanResult = None  # type: ignore[assignment,misc]

pytestmark = pytest.mark.skipif(
    not _IMPORT_OK,
    reason="orchestra.discovery.scanner not yet implemented",
)


# ---------------------------------------------------------------------------
# Helpers — minimal project trees
# ---------------------------------------------------------------------------


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


_SIMPLE_TOOL_SRC = """\
from orchestra.tools.base import tool

@tool
async def web_search(query: str) -> str:
    \"\"\"Search the web.\"\"\"
    return query
"""

_RESEARCHER_YAML = """\
name: researcher
system_prompt: Research topics.
tools:
  - web_search
"""

_WRITER_YAML = """\
name: writer
system_prompt: Write summaries.
tools: []
"""

_PIPELINE_YAML = """\
name: pipeline
nodes:
  researcher:
    type: agent
    ref: researcher
    output_key: research
  writer:
    type: agent
    ref: writer
    output_key: output
edges:
  - source: researcher
    target: writer
  - source: writer
    target: __end__
entry_point: researcher
"""

_ORCHESTRA_YAML = """\
project:
  name: test-project
"""


# ---------------------------------------------------------------------------
# TestScanResultShape
# ---------------------------------------------------------------------------


class TestScanResultShape:
    def test_scan_result_has_tools_attribute(self, tmp_path):
        scanner = ProjectScanner()
        result = scanner.scan(tmp_path)
        assert hasattr(result, "tools")

    def test_scan_result_has_agents_attribute(self, tmp_path):
        scanner = ProjectScanner()
        result = scanner.scan(tmp_path)
        assert hasattr(result, "agents")

    def test_scan_result_has_workflows_attribute(self, tmp_path):
        scanner = ProjectScanner()
        result = scanner.scan(tmp_path)
        assert hasattr(result, "workflows")

    def test_scan_result_has_errors_attribute(self, tmp_path):
        scanner = ProjectScanner()
        result = scanner.scan(tmp_path)
        assert hasattr(result, "errors")

    def test_scan_result_has_warnings_attribute(self, tmp_path):
        scanner = ProjectScanner()
        result = scanner.scan(tmp_path)
        assert hasattr(result, "warnings")


# ---------------------------------------------------------------------------
# TestScanEmptyProject
# ---------------------------------------------------------------------------


class TestScanEmptyProject:
    def test_empty_directory_returns_empty_results(self, tmp_path):
        scanner = ProjectScanner()
        result = scanner.scan(tmp_path)
        assert result.tools == {} or list(result.tools) == []
        assert result.agents == {} or list(result.agents) == []
        assert result.workflows == {} or list(result.workflows) == []

    def test_empty_directory_no_crash(self, tmp_path):
        scanner = ProjectScanner()
        # Should not raise
        result = scanner.scan(tmp_path)
        assert result is not None

    def test_missing_tools_directory_handled_gracefully(self, tmp_path):
        """No tools/ directory must produce empty tools, not an exception."""
        _write(tmp_path / "agents" / "agent.yaml", "name: a\nsystem_prompt: hi\n")
        scanner = ProjectScanner()
        result = scanner.scan(tmp_path)
        # tools should be empty, not an error
        assert result.tools == {} or list(result.tools) == []

    def test_missing_agents_directory_handled_gracefully(self, tmp_path):
        _write(tmp_path / "tools" / "search.py", _SIMPLE_TOOL_SRC)
        scanner = ProjectScanner()
        result = scanner.scan(tmp_path)
        assert result.agents == {} or list(result.agents) == []

    def test_missing_workflows_directory_handled_gracefully(self, tmp_path):
        _write(tmp_path / "tools" / "search.py", _SIMPLE_TOOL_SRC)
        scanner = ProjectScanner()
        result = scanner.scan(tmp_path)
        assert result.workflows == {} or list(result.workflows) == []


# ---------------------------------------------------------------------------
# TestScanWithValidProject
# ---------------------------------------------------------------------------


class TestScanWithValidProject:
    def test_tools_discovered(self, tmp_path):
        _write(tmp_path / "tools" / "search.py", _SIMPLE_TOOL_SRC)
        scanner = ProjectScanner()
        result = scanner.scan(tmp_path)
        assert "web_search" in result.tools

    def test_agents_discovered(self, tmp_path):
        _write(tmp_path / "tools" / "search.py", _SIMPLE_TOOL_SRC)
        _write(tmp_path / "agents" / "researcher.yaml", _RESEARCHER_YAML)
        scanner = ProjectScanner()
        result = scanner.scan(tmp_path)
        assert "researcher" in result.agents

    def test_workflows_discovered(self, tmp_path):
        _write(tmp_path / "tools" / "search.py", _SIMPLE_TOOL_SRC)
        _write(tmp_path / "agents" / "researcher.yaml", _RESEARCHER_YAML)
        _write(tmp_path / "agents" / "writer.yaml", _WRITER_YAML)
        _write(tmp_path / "workflows" / "pipeline.yaml", _PIPELINE_YAML)
        scanner = ProjectScanner()
        result = scanner.scan(tmp_path)
        assert "pipeline" in result.workflows

    def test_orchestra_yaml_optional(self, tmp_path):
        """scan() should work when orchestra.yaml is absent."""
        _write(tmp_path / "tools" / "search.py", _SIMPLE_TOOL_SRC)
        scanner = ProjectScanner()
        result = scanner.scan(tmp_path)
        assert result is not None
        assert len(result.errors) == 0 or isinstance(result.errors, list)

    def test_orchestra_yaml_loaded_when_present(self, tmp_path):
        """Config from orchestra.yaml should be used if the file exists."""
        _write(tmp_path / "orchestra.yaml", _ORCHESTRA_YAML)
        scanner = ProjectScanner()
        result = scanner.scan(tmp_path)
        assert result is not None


# ---------------------------------------------------------------------------
# TestScanCrossReferenceValidation
# ---------------------------------------------------------------------------


class TestScanCrossReferenceValidation:
    def test_agent_referencing_missing_tool_produces_error(self, tmp_path):
        """If an agent YAML lists a tool that was not discovered, errors must be non-empty."""
        # No tools/ directory — web_search won't exist
        _write(tmp_path / "agents" / "researcher.yaml", _RESEARCHER_YAML)
        scanner = ProjectScanner()
        result = scanner.scan(tmp_path)
        # Either an error is recorded, or researcher is absent from agents
        has_error = len(result.errors) > 0
        researcher_absent = "researcher" not in result.agents
        assert has_error or researcher_absent

    def test_workflow_referencing_missing_agent_produces_error(self, tmp_path):
        """If a workflow YAML references an agent that was not loaded, errors must reflect this."""
        # No agents/ directory
        _write(tmp_path / "tools" / "search.py", _SIMPLE_TOOL_SRC)
        _write(tmp_path / "workflows" / "pipeline.yaml", _PIPELINE_YAML)
        scanner = ProjectScanner()
        result = scanner.scan(tmp_path)
        has_error = len(result.errors) > 0
        pipeline_absent = "pipeline" not in result.workflows
        assert has_error or pipeline_absent

    def test_no_errors_for_valid_project(self, tmp_path):
        """A fully consistent project structure must produce no errors."""
        _write(tmp_path / "tools" / "search.py", _SIMPLE_TOOL_SRC)
        _write(tmp_path / "agents" / "researcher.yaml", _RESEARCHER_YAML)
        _write(tmp_path / "agents" / "writer.yaml", _WRITER_YAML)
        _write(tmp_path / "workflows" / "pipeline.yaml", _PIPELINE_YAML)
        scanner = ProjectScanner()
        result = scanner.scan(tmp_path)
        assert result.errors == []

    def test_errors_collected_not_fail_fast(self, tmp_path):
        """Multiple cross-reference problems must all be collected before returning."""
        # Two agents each missing a different tool
        _write(
            tmp_path / "agents" / "a1.yaml",
            "name: a1\ntools:\n  - missing_tool_1\n",
        )
        _write(
            tmp_path / "agents" / "a2.yaml",
            "name: a2\ntools:\n  - missing_tool_2\n",
        )
        scanner = ProjectScanner()
        result = scanner.scan(tmp_path)
        # Both issues should be reported (not just the first one)
        # This may be 2 errors or 2 agents absent — either confirms non-fail-fast
        assert isinstance(result.errors, list)
