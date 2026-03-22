"""ProjectConfig: Pydantic model for orchestra.yaml.

All fields are optional with sensible defaults. Uses ``extra="forbid"``
to catch typos in the config file early.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from ruamel.yaml import YAML

from orchestra.discovery.errors import ConfigError


class ProjectSection(BaseModel):
    """Project metadata."""

    model_config = {"extra": "forbid"}

    name: str = "orchestra-project"
    version: str = "1.0"


class DefaultsSection(BaseModel):
    """Default agent parameters (cascaded into agent YAML)."""

    model_config = {"extra": "forbid"}

    model: str = "claude-sonnet-4-20250514"
    temperature: float = 0.7
    max_iterations: int = 10
    provider: str = "anthropic"


class DirectoriesSection(BaseModel):
    """Override default directory names."""

    model_config = {"extra": "forbid"}

    agents: str = "agents"
    tools: str = "tools"
    workflows: str = "workflows"
    lib: str = "lib"


class ServerSection(BaseModel):
    """Server configuration for ``orchestra up``."""

    model_config = {"extra": "forbid"}

    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = Field(default_factory=list)


class SecuritySection(BaseModel):
    """Security constraints for discovery."""

    model_config = {"extra": "forbid"}

    allowed_imports: list[str] = Field(default_factory=list)


class ProjectConfig(BaseModel):
    """Root schema for ``orchestra.yaml``.

    Every section is optional -- sensible defaults apply when omitted.
    ``extra="forbid"`` catches typos such as ``defautls:`` immediately.
    """

    model_config = {"extra": "forbid"}

    project: ProjectSection = Field(default_factory=ProjectSection)
    defaults: DefaultsSection = Field(default_factory=DefaultsSection)
    directories: DirectoriesSection = Field(default_factory=DirectoriesSection)
    server: ServerSection = Field(default_factory=ServerSection)
    security: SecuritySection = Field(default_factory=SecuritySection)


def load_config(project_dir: Path) -> ProjectConfig:
    """Load ``orchestra.yaml`` from *project_dir*, or return defaults.

    Raises :class:`ConfigError` on validation failure.
    """
    yaml_path = project_dir / "orchestra.yaml"
    if not yaml_path.exists():
        return ProjectConfig()

    try:
        yaml = YAML(typ="safe")
        data: dict[str, Any] | None = yaml.load(yaml_path.read_text(encoding="utf-8"))
        if data is None:
            return ProjectConfig()
        return ProjectConfig.model_validate(data)
    except Exception as exc:
        raise ConfigError(f"Invalid orchestra.yaml: {exc}") from exc
