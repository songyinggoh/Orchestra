"""Tests for orchestra.discovery.config (T-5.1)."""

from __future__ import annotations

import pytest
from pathlib import Path

from orchestra.discovery.config import (
    ProjectConfig,
    DefaultsSection,
    DirectoriesSection,
    ServerSection,
    SecuritySection,
    load_config,
)
from orchestra.discovery.errors import ConfigError


# ---- Defaults ----


def test_project_config_all_defaults():
    cfg = ProjectConfig()
    assert cfg.project.name == "orchestra-project"
    assert cfg.defaults.model == "claude-sonnet-4-20250514"
    assert cfg.defaults.temperature == 0.7
    assert cfg.defaults.max_iterations == 10
    assert cfg.directories.agents == "agents"
    assert cfg.directories.tools == "tools"
    assert cfg.directories.workflows == "workflows"
    assert cfg.server.host == "0.0.0.0"
    assert cfg.server.port == 8000
    assert cfg.security.allowed_imports == ["lib."]


def test_defaults_section_override():
    d = DefaultsSection(model="gpt-4o", temperature=0.3, max_iterations=5)
    assert d.model == "gpt-4o"
    assert d.temperature == 0.3
    assert d.max_iterations == 5


def test_directories_section_override():
    d = DirectoriesSection(agents="my_agents", tools="my_tools")
    assert d.agents == "my_agents"
    assert d.tools == "my_tools"
    assert d.workflows == "workflows"  # default preserved


# ---- extra="forbid" ----


def test_extra_forbid_rejects_unknown_fields():
    with pytest.raises(Exception):
        ProjectConfig.model_validate({"unknown_key": 123})


def test_extra_forbid_nested():
    with pytest.raises(Exception):
        ProjectConfig.model_validate({"defaults": {"unknown": True}})


# ---- load_config from disk ----


def test_load_config_no_file(tmp_path: Path):
    cfg = load_config(tmp_path)
    assert cfg == ProjectConfig()


def test_load_config_empty_file(tmp_path: Path):
    (tmp_path / "orchestra.yaml").write_text("", encoding="utf-8")
    cfg = load_config(tmp_path)
    assert cfg == ProjectConfig()


def test_load_config_partial(tmp_path: Path):
    (tmp_path / "orchestra.yaml").write_text(
        "project:\n  name: my-app\ndefaults:\n  temperature: 0.1\n",
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    assert cfg.project.name == "my-app"
    assert cfg.defaults.temperature == 0.1
    assert cfg.defaults.model == "claude-sonnet-4-20250514"  # default


def test_load_config_invalid_raises(tmp_path: Path):
    (tmp_path / "orchestra.yaml").write_text(
        "typo_section:\n  foo: bar\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="Invalid orchestra.yaml"):
        load_config(tmp_path)


def test_load_config_full(tmp_path: Path):
    yaml_text = """\
project:
  name: full-project
  version: "2.0"
defaults:
  model: gpt-4o
  temperature: 0.5
  max_iterations: 20
  provider: openai
directories:
  agents: custom_agents
  tools: custom_tools
  workflows: custom_workflows
  lib: custom_lib
server:
  host: 127.0.0.1
  port: 9000
  cors_origins:
    - http://localhost:3000
security:
  allowed_imports:
    - lib.
    - mypackage.
"""
    (tmp_path / "orchestra.yaml").write_text(yaml_text, encoding="utf-8")
    cfg = load_config(tmp_path)
    assert cfg.project.name == "full-project"
    assert cfg.project.version == "2.0"
    assert cfg.defaults.model == "gpt-4o"
    assert cfg.defaults.provider == "openai"
    assert cfg.directories.agents == "custom_agents"
    assert cfg.server.host == "127.0.0.1"
    assert cfg.server.port == 9000
    assert cfg.server.cors_origins == ["http://localhost:3000"]
    assert "mypackage." in cfg.security.allowed_imports
