"""Tests that service URLs respect environment variable overrides."""
from __future__ import annotations

import os
import sys

import pytest


def _clear(monkeypatch, *prefixes: str) -> None:
    """Remove cached modules so env vars are re-read on fresh import."""
    for mod in list(sys.modules):
        if any(mod == p or mod.startswith(p + ".") for p in prefixes):
            monkeypatch.delitem(sys.modules, mod, raising=False)


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------


def test_ollama_base_url_default() -> None:
    """OllamaProvider without env var uses localhost:11434."""
    from orchestra.providers.ollama import OllamaProvider

    p = OllamaProvider()
    assert p._base_url == "http://localhost:11434"


def test_ollama_base_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """OllamaProvider respects OLLAMA_BASE_URL env var."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://myollama:11434")
    _clear(monkeypatch, "orchestra.providers.ollama")
    from orchestra.providers.ollama import OllamaProvider

    p = OllamaProvider()
    assert "myollama" in p._base_url, (
        f"Expected 'myollama' in _base_url, got {p._base_url!r}"
    )


def test_ollama_explicit_arg_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit base_url argument takes precedence over env var."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://envollama:11434")
    _clear(monkeypatch, "orchestra.providers.ollama")
    from orchestra.providers.ollama import OllamaProvider

    p = OllamaProvider(base_url="http://explicit:11434")
    assert "explicit" in p._base_url
    assert "envollama" not in p._base_url


# ---------------------------------------------------------------------------
# NATS
# ---------------------------------------------------------------------------


def test_nats_url_default() -> None:
    """NATSClientConfig without env var uses localhost:4222."""
    from orchestra.messaging.client import NATSClientConfig

    cfg = NATSClientConfig()
    assert cfg.servers == ["nats://localhost:4222"]


def test_nats_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """NATSClientConfig respects NATS_URL env var."""
    monkeypatch.setenv("NATS_URL", "nats://mynats:4222")
    _clear(monkeypatch, "orchestra.messaging.client")
    from orchestra.messaging.client import NATSClientConfig

    cfg = NATSClientConfig()
    assert len(cfg.servers) == 1
    assert "mynats" in cfg.servers[0], (
        f"Expected 'mynats' in servers[0], got {cfg.servers[0]!r}"
    )


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------


def test_redis_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """RedisMemoryBackend respects REDIS_URL env var (lazy-import, no connection)."""
    monkeypatch.setenv("REDIS_URL", "redis://myredis:6379/0")

    # Patch BlockingConnectionPool so no real Redis connection is attempted
    import unittest.mock as mock

    fake_pool = object()
    fake_redis_client = mock.MagicMock()

    with (
        mock.patch(
            "redis.asyncio.connection.BlockingConnectionPool.from_url",
            return_value=fake_pool,
        ) as mock_pool,
        mock.patch("redis.asyncio.Redis", return_value=fake_redis_client),
    ):
        _clear(monkeypatch, "orchestra.memory.backends")
        from orchestra.memory.backends import RedisMemoryBackend

        RedisMemoryBackend()
        call_url = mock_pool.call_args[0][0]

    assert "myredis" in call_url, f"Expected 'myredis' in Redis URL, got {call_url!r}"


# ---------------------------------------------------------------------------
# Qdrant
# ---------------------------------------------------------------------------


def test_qdrant_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """QdrantColdBackend respects QDRANT_URL env var (no live Qdrant needed)."""
    monkeypatch.setenv("QDRANT_URL", "http://myqdrant:6333")
    _clear(monkeypatch, "orchestra.memory.qdrant_backend")

    # Patch AsyncQdrantClient import so the backend can be imported without
    # the qdrant-client package installed.
    import unittest.mock as mock

    qdrant_mod = mock.MagicMock()
    qdrant_mod.AsyncQdrantClient = mock.MagicMock
    qdrant_mod.models = mock.MagicMock()

    with mock.patch.dict(sys.modules, {"qdrant_client": qdrant_mod, "qdrant_client.models": qdrant_mod.models}):
        from orchestra.memory.qdrant_backend import QdrantColdBackend

        # Force HAS_QDRANT so the import guard is bypassed
        import orchestra.memory.qdrant_backend as qb

        qb.HAS_QDRANT = True
        backend = QdrantColdBackend()

    assert "myqdrant" in backend.url, (
        f"Expected 'myqdrant' in QdrantColdBackend.url, got {backend.url!r}"
    )


# ---------------------------------------------------------------------------
# KEDA stream name alignment (static check)
# ---------------------------------------------------------------------------


def test_keda_stream_name_matches_client_constant() -> None:
    """KEDA ScaledObject stream name must match the messaging client constant."""
    import pathlib
    import re

    from orchestra.messaging.client import _STREAM_NAME

    yaml_path = (
        pathlib.Path(__file__).parent.parent.parent
        / "deploy" / "base" / "orchestra-agent.yaml"
    )
    assert yaml_path.exists(), f"KEDA YAML not found at {yaml_path}"

    content = yaml_path.read_text()
    match = re.search(r'stream:\s*"([^"]+)"', content)
    assert match, "Could not find stream: field in KEDA YAML"

    yaml_stream = match.group(1)
    assert yaml_stream == _STREAM_NAME, (
        f"KEDA stream name {yaml_stream!r} != client constant {_STREAM_NAME!r}"
    )
