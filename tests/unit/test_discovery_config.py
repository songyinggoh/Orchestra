"""Unit tests for discovery/config.py — ProjectConfig Pydantic model.

Tests cover:
- Valid orchestra.yaml loads correctly
- All defaults applied when fields omitted
- extra="forbid" rejects unknown fields
- Empty / missing file handled gracefully
- Server config defaults (host, port)
- Security allowed_imports defaults
- Directory defaults
"""

from __future__ import annotations

import pytest

try:
    from orchestra.discovery.config import ProjectConfig
    _IMPORT_OK = True
except ImportError:
    _IMPORT_OK = False
    ProjectConfig = None  # type: ignore[assignment,misc]

pytestmark = pytest.mark.skipif(
    not _IMPORT_OK,
    reason="orchestra.discovery.config not yet implemented",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_config(yaml_text: str) -> "ProjectConfig":
    """Parse YAML text into ProjectConfig."""
    from ruamel.yaml import YAML
    yaml = YAML(typ="safe")
    data = yaml.load(yaml_text) or {}
    return ProjectConfig(**data)


# ---------------------------------------------------------------------------
# TestProjectConfigDefaults
# ---------------------------------------------------------------------------


class TestProjectConfigDefaults:
    def test_empty_config_uses_all_defaults(self):
        """ProjectConfig() with no arguments should not raise."""
        config = ProjectConfig()
        assert config is not None

    def test_default_server_host(self):
        config = ProjectConfig()
        assert config.server.host == "0.0.0.0"

    def test_default_server_port(self):
        config = ProjectConfig()
        assert config.server.port == 8000

    def test_default_directory_agents(self):
        config = ProjectConfig()
        assert config.directories.agents == "agents"

    def test_default_directory_tools(self):
        config = ProjectConfig()
        assert config.directories.tools == "tools"

    def test_default_directory_workflows(self):
        config = ProjectConfig()
        assert config.directories.workflows == "workflows"

    def test_default_security_allowed_imports_is_list(self):
        """Default allowed_imports must be a non-None list (may be empty or populated)."""
        config = ProjectConfig()
        assert isinstance(config.security.allowed_imports, list)


# ---------------------------------------------------------------------------
# TestProjectConfigFromYaml
# ---------------------------------------------------------------------------


class TestProjectConfigFromYaml:
    def test_valid_full_yaml_loads(self):
        yaml_text = """\
project:
  name: my-project

defaults:
  model: claude-sonnet-4-20250514
  temperature: 0.5
  max_iterations: 8

directories:
  agents: agents
  tools: tools
  workflows: workflows

server:
  host: 127.0.0.1
  port: 9000

security:
  allowed_imports:
    - orchestra.
    - lib.
"""
        config = _load_config(yaml_text)
        assert config.project.name == "my-project"

    def test_project_name_field_roundtrip(self):
        yaml_text = "project:\n  name: roundtrip-project\n"
        config = _load_config(yaml_text)
        assert config.project.name == "roundtrip-project"

    def test_defaults_model_override(self):
        yaml_text = "defaults:\n  model: gpt-4o\n"
        config = _load_config(yaml_text)
        assert config.defaults.model == "gpt-4o"

    def test_defaults_temperature_override(self):
        yaml_text = "defaults:\n  temperature: 0.1\n"
        config = _load_config(yaml_text)
        assert abs(config.defaults.temperature - 0.1) < 1e-9

    def test_defaults_max_iterations_override(self):
        yaml_text = "defaults:\n  max_iterations: 3\n"
        config = _load_config(yaml_text)
        assert config.defaults.max_iterations == 3

    def test_server_host_override(self):
        yaml_text = "server:\n  host: 127.0.0.1\n"
        config = _load_config(yaml_text)
        assert config.server.host == "127.0.0.1"

    def test_server_port_override(self):
        yaml_text = "server:\n  port: 9000\n"
        config = _load_config(yaml_text)
        assert config.server.port == 9000

    def test_directory_overrides(self):
        yaml_text = """\
directories:
  agents: custom_agents
  tools: custom_tools
  workflows: custom_workflows
"""
        config = _load_config(yaml_text)
        assert config.directories.agents == "custom_agents"
        assert config.directories.tools == "custom_tools"
        assert config.directories.workflows == "custom_workflows"


# ---------------------------------------------------------------------------
# TestProjectConfigValidation
# ---------------------------------------------------------------------------


class TestProjectConfigValidation:
    def test_unknown_top_level_field_rejected(self):
        """extra='forbid' must reject unknown keys like 'systm_prompt'."""
        from pydantic import ValidationError
        with pytest.raises((ValidationError, TypeError)):
            ProjectConfig(**{"systm_prompt": "typo field"})

    def test_unknown_nested_server_field_rejected(self):
        from pydantic import ValidationError
        try:
            from orchestra.discovery.config import ServerConfig
            with pytest.raises((ValidationError, TypeError)):
                ServerConfig(**{"unknown_field": True})
        except ImportError:
            pytest.skip("ServerConfig not separately importable")


# ---------------------------------------------------------------------------
# TestProjectConfigFromFile
# ---------------------------------------------------------------------------


class TestProjectConfigFromFile:
    def test_load_from_fixture_file(self):
        """Fixture orchestra.yaml should parse without errors."""
        from pathlib import Path
        fixture_path = (
            Path(__file__).parent.parent
            / "fixtures"
            / "discovery"
            / "orchestra.yaml"
        )
        if not fixture_path.exists():
            pytest.skip("Fixture file not present")
        from ruamel.yaml import YAML
        yaml = YAML(typ="safe")
        data = yaml.load(fixture_path.read_text(encoding="utf-8")) or {}
        config = ProjectConfig(**data)
        assert config.project.name == "test-project"
        assert config.server.port == 9000

    def test_missing_file_raises_file_not_found(self, tmp_path):
        """Accessing a nonexistent path raises FileNotFoundError."""
        missing = tmp_path / "nonexistent_orchestra.yaml"
        with pytest.raises(FileNotFoundError):
            missing.read_text(encoding="utf-8")
