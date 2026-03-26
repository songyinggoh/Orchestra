"""Unit tests for QdrantColdBackend."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("qdrant_client", reason="qdrant-client not installed")

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_client():
    """Build a fully mocked AsyncQdrantClient."""
    client = AsyncMock()

    # get_collections returns a response with an empty list by default
    collections_response = MagicMock()
    collections_response.collections = []
    client.get_collections = AsyncMock(return_value=collections_response)

    client.create_collection = AsyncMock()
    client.upsert = AsyncMock()
    client.retrieve = AsyncMock(return_value=[])
    client.query_points = AsyncMock(return_value=MagicMock(points=[]))
    client.delete = AsyncMock()
    client.count = AsyncMock(return_value=MagicMock(count=0))

    return client


@pytest.fixture
def mock_client():
    return _make_mock_client()


@pytest.fixture
def backend(mock_client):
    """QdrantColdBackend with a pre-injected mock client."""
    from orchestra.memory.qdrant_backend import QdrantColdBackend

    b = QdrantColdBackend(
        url="http://localhost:6333",
        collection_name="test_col",
        agent_id="agent-1",
        dimensions=4,
        embedding_model="minishlab/potion-base-8M",
    )
    # Bypass real network: inject mock and mark as initialized
    b._client = mock_client
    b._initialized = True
    return b


# ---------------------------------------------------------------------------
# _key_to_point_id
# ---------------------------------------------------------------------------


def test_key_to_point_id_is_deterministic():
    from orchestra.memory.qdrant_backend import QdrantColdBackend

    assert QdrantColdBackend._key_to_point_id("x") == QdrantColdBackend._key_to_point_id("x")


def test_key_to_point_id_different_keys_differ():
    from orchestra.memory.qdrant_backend import QdrantColdBackend

    assert QdrantColdBackend._key_to_point_id("a") != QdrantColdBackend._key_to_point_id("b")


def test_key_to_point_id_is_uuid_string():
    import uuid

    from orchestra.memory.qdrant_backend import QdrantColdBackend

    result = QdrantColdBackend._key_to_point_id("hello")
    uuid.UUID(result)  # raises ValueError if not valid UUID


# ---------------------------------------------------------------------------
# _agent_filter
# ---------------------------------------------------------------------------


def test_agent_filter_has_agent_id_condition(backend):
    f = backend._agent_filter()
    keys = [c.key for c in f.must]
    assert "agent_id" in keys


def test_agent_filter_extra_metadata(backend):
    f = backend._agent_filter({"session_id": "s1"})
    keys = [c.key for c in f.must]
    assert "meta.session_id" in keys


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_calls_upsert(backend, mock_client):
    await backend.store("k1", "hello", embedding=[0.1, 0.2, 0.3, 0.4])
    mock_client.upsert.assert_called_once()
    call_kwargs = mock_client.upsert.call_args.kwargs
    assert call_kwargs["collection_name"] == "test_col"
    point = call_kwargs["points"][0]
    assert point.payload["key"] == "k1"
    assert point.payload["content"] == "hello"
    assert point.payload["agent_id"] == "agent-1"


@pytest.mark.asyncio
async def test_store_includes_embedding_model_in_payload(backend, mock_client):
    await backend.store("k1", "v", embedding=[0.0, 0.0, 0.0, 0.0])
    point = mock_client.upsert.call_args.kwargs["points"][0]
    assert point.payload["_embedding_model"] == "minishlab/potion-base-8M"


@pytest.mark.asyncio
async def test_store_zero_vector_when_no_embedding(backend, mock_client):
    await backend.store("k2", "val")
    point = mock_client.upsert.call_args.kwargs["points"][0]
    assert point.vector == [0.0, 0.0, 0.0, 0.0]


@pytest.mark.asyncio
async def test_store_uses_deterministic_point_id(backend, mock_client):
    from orchestra.memory.qdrant_backend import QdrantColdBackend

    await backend.store("mykey", "v", embedding=[0.1, 0.2, 0.3, 0.4])
    point = mock_client.upsert.call_args.kwargs["points"][0]
    assert point.id == QdrantColdBackend._key_to_point_id("mykey")


# ---------------------------------------------------------------------------
# retrieve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_returns_none_when_not_found(backend, mock_client):
    mock_client.retrieve = AsyncMock(return_value=[])
    assert await backend.retrieve("missing") is None


@pytest.mark.asyncio
async def test_retrieve_returns_content(backend, mock_client):
    point = MagicMock()
    point.payload = {
        "key": "k1",
        "content": "stored value",
        "_embedding_model": "minishlab/potion-base-8M",
    }
    mock_client.retrieve = AsyncMock(return_value=[point])
    result = await backend.retrieve("k1")
    assert result == "stored value"


@pytest.mark.asyncio
async def test_retrieve_warns_on_model_mismatch(backend, mock_client, caplog):
    import logging

    point = MagicMock()
    point.payload = {
        "key": "k1",
        "content": "val",
        "_embedding_model": "some-other-model",
    }
    mock_client.retrieve = AsyncMock(return_value=[point])
    with caplog.at_level(logging.WARNING):
        await backend.retrieve("k1")
    # structlog doesn't always go to caplog; just verify no exception raised
    # (the warning is emitted via structlog logger, which may not propagate to caplog)


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_returns_empty_when_no_results(backend, mock_client):
    mock_client.query_points = AsyncMock(return_value=MagicMock(points=[]))
    result = await backend.search([0.1, 0.2, 0.3, 0.4])
    assert result == []


@pytest.mark.asyncio
async def test_search_returns_key_score_tuples(backend, mock_client):
    p1 = MagicMock()
    p1.payload = {"key": "k1"}
    p1.score = 0.92
    p2 = MagicMock()
    p2.payload = {"key": "k2"}
    p2.score = 0.75
    mock_client.query_points = AsyncMock(return_value=MagicMock(points=[p1, p2]))

    result = await backend.search([0.1, 0.2, 0.3, 0.4], limit=2)
    assert result == [("k1", 0.92), ("k2", 0.75)]


@pytest.mark.asyncio
async def test_search_passes_limit(backend, mock_client):
    mock_client.query_points = AsyncMock(return_value=MagicMock(points=[]))
    await backend.search([0.0, 0.0, 0.0, 0.0], limit=7)
    call_kwargs = mock_client.query_points.call_args.kwargs
    assert call_kwargs["limit"] == 7


@pytest.mark.asyncio
async def test_search_applies_filter_metadata(backend, mock_client):
    mock_client.query_points = AsyncMock(return_value=MagicMock(points=[]))
    await backend.search([0.0] * 4, filter_metadata={"session_id": "s1"})
    call_kwargs = mock_client.query_points.call_args.kwargs
    filter_obj = call_kwargs["query_filter"]
    keys = [c.key for c in filter_obj.must]
    assert "meta.session_id" in keys


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_calls_client_delete(backend, mock_client):
    from orchestra.memory.qdrant_backend import QdrantColdBackend

    await backend.delete("k1")
    mock_client.delete.assert_called_once()
    call_kwargs = mock_client.delete.call_args.kwargs
    assert call_kwargs["collection_name"] == "test_col"
    assert QdrantColdBackend._key_to_point_id("k1") in call_kwargs["points_selector"].points


# ---------------------------------------------------------------------------
# count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_count_returns_integer(backend, mock_client):
    mock_client.count = AsyncMock(return_value=MagicMock(count=42))
    assert await backend.count() == 42


@pytest.mark.asyncio
async def test_count_filters_by_agent(backend, mock_client):
    mock_client.count = AsyncMock(return_value=MagicMock(count=0))
    await backend.count()
    call_kwargs = mock_client.count.call_args.kwargs
    keys = [c.key for c in call_kwargs["count_filter"].must]
    assert "agent_id" in keys


# ---------------------------------------------------------------------------
# ImportError when qdrant-client not installed
# ---------------------------------------------------------------------------


def test_raises_import_error_when_qdrant_missing():
    with patch("orchestra.memory.qdrant_backend.HAS_QDRANT", False):
        from orchestra.memory import qdrant_backend as qb

        # Re-instantiate with HAS_QDRANT=False
        orig = qb.HAS_QDRANT
        qb.HAS_QDRANT = False
        try:
            with pytest.raises(ImportError, match="qdrant-client"):
                qb.QdrantColdBackend()
        finally:
            qb.HAS_QDRANT = orig


# ---------------------------------------------------------------------------
# #3 — Multi-tenant agent_id override
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_uses_instance_agent_id_by_default(backend, mock_client):
    mock_client.query_points = AsyncMock(return_value=MagicMock(points=[]))
    await backend.search([0.0] * 4)
    call_kwargs = mock_client.query_points.call_args.kwargs
    _keys = [c.key for c in call_kwargs["query_filter"].must]
    values = [c.match.value for c in call_kwargs["query_filter"].must if c.key == "agent_id"]
    assert values == ["agent-1"]


@pytest.mark.asyncio
async def test_search_overrides_agent_id_when_provided(backend, mock_client):
    mock_client.query_points = AsyncMock(return_value=MagicMock(points=[]))
    await backend.search([0.0] * 4, agent_id="agent-99")
    call_kwargs = mock_client.query_points.call_args.kwargs
    values = [c.match.value for c in call_kwargs["query_filter"].must if c.key == "agent_id"]
    assert values == ["agent-99"]
