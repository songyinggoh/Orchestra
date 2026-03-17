"""Fixtures for live LLM backend tests.

Each fixture skips automatically when the required credential / service is absent.
Run the suite with:

    pytest tests/live/ -m live -v

Or pick a single backend:

    pytest tests/live/ -m live -k anthropic -v
    pytest tests/live/ -m live -k openai -v
    pytest tests/live/ -m live -k ollama -v
"""
from __future__ import annotations

import os

import pytest

from orchestra.providers.anthropic import AnthropicProvider
from orchestra.providers.http import HttpProvider


def pytest_configure(config):
    config.addinivalue_line("markers", "live: tests that hit real LLM APIs (requires credentials)")


# ---------------------------------------------------------------------------
# Per-backend fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def anthropic_provider():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        pytest.skip("ANTHROPIC_API_KEY not set")
    return AnthropicProvider(api_key=key, default_model="claude-haiku-4-5-20251001")


@pytest.fixture
def anthropic_model():
    return "claude-haiku-4-5-20251001"


@pytest.fixture
def openai_provider():
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        pytest.skip("OPENAI_API_KEY not set")
    return HttpProvider(api_key=key, default_model="gpt-4o-mini")


@pytest.fixture
def openai_model():
    return "gpt-4o-mini"


@pytest.fixture
def google_provider():
    key = os.environ.get("GOOGLE_API_KEY", "")
    if not key:
        pytest.skip("GOOGLE_API_KEY not set")
    from orchestra.providers.google import GoogleProvider
    return GoogleProvider(api_key=key, default_model="gemini-2.0-flash")


@pytest.fixture
def google_model():
    return "gemini-2.0-flash"


@pytest.fixture
async def ollama_provider():
    from orchestra.providers.ollama import OllamaProvider
    p = OllamaProvider()
    if not await p.health_check():
        pytest.skip("Ollama not running — start with: ollama serve")
    models = await p.list_models()
    if not models:
        pytest.skip("No Ollama models pulled — run: ollama pull llama3.1")
    return p


@pytest.fixture
async def ollama_model(ollama_provider):
    """Return the first available Ollama model."""
    models = await ollama_provider.list_models()
    return models[0]


# ---------------------------------------------------------------------------
# 'any_provider' — first available, used for provider-agnostic tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def any_provider_and_model():
    """Return (provider, model) for the first available backend.

    Priority:
        ORCHESTRA_BASE_URL + ORCHESTRA_API_KEY  → any OpenAI-compatible backend
        ANTHROPIC_API_KEY                        → Anthropic
        OPENAI_API_KEY                           → OpenAI
        GOOGLE_API_KEY                           → Google
        Ollama running locally                   → Ollama (no key needed)

    Skips the test if nothing is available.
    """
    from orchestra.providers import auto_provider

    try:
        provider = auto_provider()
    except RuntimeError as e:
        pytest.skip(str(e))

    # Resolve the default model for the chosen provider
    model = os.environ.get("ORCHESTRA_MODEL") or getattr(provider, "default_model", None)
    return provider, model
