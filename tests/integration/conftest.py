"""Shared fixtures for integration tests."""

from __future__ import annotations

from typing import Any

import pytest

from orchestra.core.types import LLMResponse, TokenUsage


class ScriptedLLM:
    """Simple scripted LLM provider for integration tests.

    Returns a fixed response on every call. Counts calls so tests can assert
    whether the cache avoided redundant provider invocations.
    """

    provider_name: str = "scripted"
    default_model: str = "test-model"

    def __init__(self, response: str = "test response") -> None:
        self.response = response
        self.call_count = 0

    async def complete(self, *args: Any, **kwargs: Any) -> LLMResponse:
        self.call_count += 1
        return LLMResponse(
            content=self.response,
            usage=TokenUsage(
                input_tokens=10,
                output_tokens=5,
                total_tokens=15,
                estimated_cost_usd=0.001,
            ),
        )

    def count_tokens(self, *args: Any, **kwargs: Any) -> int:
        return 10

    def get_model_cost(self, *args: Any, **kwargs: Any) -> Any:
        return None


@pytest.fixture()
def scripted_llm() -> ScriptedLLM:
    """Return a fresh ScriptedLLM for each test."""
    return ScriptedLLM()


@pytest.fixture()
def app() -> Any:
    """Create a FastAPI app for integration tests (same pattern as test_fastapi_endpoints)."""
    from orchestra.server.app import create_app
    from orchestra.server.config import ServerConfig

    config = ServerConfig()
    return create_app(config)
