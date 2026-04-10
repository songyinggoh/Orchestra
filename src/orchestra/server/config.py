"""Server configuration via Pydantic Settings."""

from __future__ import annotations

import os

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_CORS_ORIGINS = ["http://localhost:3000", "http://localhost:5173"]


class ServerConfig(BaseSettings):
    """Configuration for the Orchestra HTTP server.

    All fields can be set via environment variables prefixed with ``ORCHESTRA_``.
    For example, ``ORCHESTRA_CORS_ORIGINS='["https://app.example.com"]'``.
    """

    model_config = SettingsConfigDict(env_prefix="ORCHESTRA_", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = Field(default_factory=list)
    cors_credentials: bool = False
    api_prefix: str = "/api/v1"
    sse_heartbeat_interval: int = 15
    sse_retry_ms: int = 5000
    rate_limit_per_minute: int = 60
    max_request_body_bytes: int = 1 * 1024 * 1024  # 1 MB

    @model_validator(mode="after")
    def _default_cors_origins(self) -> "ServerConfig":
        """Default CORS origins to localhost dev ports when none are configured."""
        if not self.cors_origins:
            orchestra_env = os.environ.get("ORCHESTRA_ENV", "dev")
            if orchestra_env != "prod":
                self.cors_origins = list(_DEV_CORS_ORIGINS)
        return self

    @model_validator(mode="after")
    def _reject_wildcard_credentials(self) -> "ServerConfig":
        if "*" in self.cors_origins and self.cors_credentials:
            raise ValueError(
                "CORS misconfiguration: cors_credentials=True cannot be combined "
                "with cors_origins=['*']. Set ORCHESTRA_CORS_ORIGINS to explicit "
                "origins, or set ORCHESTRA_CORS_CREDENTIALS=false."
            )
        return self
