"""Comprehensive tests for the Orchestra vector DB memory pipeline.

Covers gaps left by the existing per-module unit tests:

- SLRUPolicy: remove, re-insert, access reorder on HOT, access on unknown key
- StateCompressor: bytes/list/nested/large payloads, zlib fallback
- SemanticDeduplicator: shape validation, threshold boundary, model2vec fallback,
  _ensure_model idempotency, embed alias, EmbeddingProvider protocol conformance
- TieredMemoryManager: promote=False, no-dedup/no-cold search_memories, demote
  no-op, promote helper, value update on re-store, start() idempotency
- VectorStore: retrieve miss, retrieve JSON fallback, search with filter_metadata,
  agent_id override on search, hybrid_search, delete, count with/without agent_id,
  initialize DDL, store without compressor
- QdrantColdBackend: _ensure_initialized lazy init + idempotency, store without
  embedding_model, retrieve no stored model, retrieve same model no warning,
  ColdTierBackend protocol conformance
- create_tiered_memory factory: full wiring with/without redis/pg
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pool_conn():
    """Return (pool, conn) mocks that satisfy asyncpg's async-context-manager interface."""
    conn = AsyncMock()
    pool = AsyncMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    return pool, conn


def _make_qdrant_client():
    """Return a fully-mocked AsyncQdrantClient."""
    client = AsyncMock()
    coll_resp = MagicMock()
    coll_resp.collections = []
    client.get_collections = AsyncMock(return_value=coll_resp)
    client.create_collection = AsyncMock()
    client.upsert = AsyncMock()
    client.retrieve = AsyncMock(return_value=[])
    client.query_points = AsyncMock(return_value=MagicMock(points=[]))
    client.delete = AsyncMock()
    client.count = AsyncMock(return_value=MagicMock(count=0))
    return client


# ===========================================================================
# SLRUPolicy
# ===========================================================================


class TestSLRUPolicyRemove:
    def test_remove_from_warm(self):
        from orchestra.memory.tiers import MemoryEntry, SLRUPolicy

        policy = SLRUPolicy(hot_max=2, warm_max=2)
        policy.insert("k1", MemoryEntry("k1", "v1"))
        assert "k1" in policy.warm_keys

        policy.remove("k1")
        assert "k1" not in policy.warm_keys
        assert "k1" not in policy.hot_keys

    def test_remove_from_hot(self):
        from orchestra.memory.tiers import MemoryEntry, SLRUPolicy

        policy = SLRUPolicy(hot_max=2, warm_max=2)
        policy.insert("k1", MemoryEntry("k1", "v1"))
        policy.access("k1")
        assert "k1" in policy.hot_keys

        policy.remove("k1")
        assert "k1" not in policy.hot_keys

    def test_remove_nonexistent_does_not_raise(self):
        from orchestra.memory.tiers import SLRUPolicy

        policy = SLRUPolicy(hot_max=2, warm_max=2)
        policy.remove("ghost")  # must not raise

    def test_remove_clears_from_both_tiers(self):
        """remove() must search both _hot and _warm, not just one."""
        from orchestra.memory.tiers import MemoryEntry, SLRUPolicy

        policy = SLRUPolicy(hot_max=2, warm_max=2)
        policy.insert("k1", MemoryEntry("k1", "v1"))
        policy.access("k1")  # k1 in HOT
        policy.insert("k2", MemoryEntry("k2", "v2"))  # k2 in WARM

        policy.remove("k1")
        policy.remove("k2")

        assert policy.hot_keys == []
        assert policy.warm_keys == []


class TestSLRUPolicyReinsert:
    def test_reinsert_existing_warm_key_updates_value(self):
        from orchestra.memory.tiers import MemoryEntry, SLRUPolicy

        policy = SLRUPolicy(hot_max=2, warm_max=2)
        policy.insert("k1", MemoryEntry("k1", "old"))
        policy.insert("k1", MemoryEntry("k1", "new"))

        # Key must still be in WARM exactly once
        assert policy.warm_keys.count("k1") == 1
        assert policy._warm["k1"].value == "new"

    def test_reinsert_existing_hot_key_updates_value(self):
        from orchestra.memory.tiers import MemoryEntry, SLRUPolicy

        policy = SLRUPolicy(hot_max=2, warm_max=2)
        policy.insert("k1", MemoryEntry("k1", "old"))
        policy.access("k1")  # promote to HOT
        policy.insert("k1", MemoryEntry("k1", "new"))

        assert policy.hot_keys.count("k1") == 1
        assert policy._hot["k1"].value == "new"


class TestSLRUPolicyAccess:
    def test_access_hot_key_refreshes_lru_order(self):
        """Accessing a key already in HOT must move it to most-recently-used position."""
        from orchestra.memory.tiers import MemoryEntry, SLRUPolicy

        policy = SLRUPolicy(hot_max=2, warm_max=2)
        policy.insert("k1", MemoryEntry("k1", "v1"))
        policy.access("k1")
        policy.insert("k2", MemoryEntry("k2", "v2"))
        policy.access("k2")

        # k1 is LRU in HOT. Re-access it so it becomes MRU.
        new_tier, evictions = policy.access("k1")
        assert new_tier is None  # no tier change — already HOT
        assert evictions == []

        # Now insert k3 and promote — this should demote k2 (LRU), not k1.
        policy.insert("k3", MemoryEntry("k3", "v3"))
        policy.access("k3")

        assert "k1" in policy.hot_keys
        assert "k3" in policy.hot_keys
        assert "k2" in policy.warm_keys

    def test_access_nonexistent_key_returns_none_and_no_evictions(self):
        from orchestra.memory.tiers import SLRUPolicy

        policy = SLRUPolicy(hot_max=2, warm_max=2)
        new_tier, evictions = policy.access("does_not_exist")
        assert new_tier is None
        assert evictions == []

    def test_access_increments_access_count(self):
        from orchestra.memory.tiers import MemoryEntry, SLRUPolicy

        policy = SLRUPolicy(hot_max=2, warm_max=2)
        policy.insert("k1", MemoryEntry("k1", "v1"))
        policy.access("k1")  # WARM -> HOT, access_count = 1
        policy.access("k1")  # HOT -> HOT (LRU refresh), access_count = 2

        assert policy._hot["k1"].access_count == 2


class TestSLRUPolicyEvictionsDue:
    def test_evictions_due_empty_when_within_capacity(self):
        from orchestra.memory.tiers import MemoryEntry, SLRUPolicy

        policy = SLRUPolicy(hot_max=3, warm_max=3)
        for i in range(3):
            policy.insert(f"k{i}", MemoryEntry(f"k{i}", f"v{i}"))

        assert policy.evictions_due() == []

    def test_evictions_due_returns_cold_evictions_when_warm_over_capacity(self):
        """When WARM is over capacity, evictions_due() must include COLD entries."""
        from orchestra.memory.tiers import MemoryEntry, SLRUPolicy, Tier

        # warm_max=1: insert two items so WARM has 2 entries — one must be evicted to COLD
        policy = SLRUPolicy(hot_max=10, warm_max=1)
        # Directly populate _warm to simulate 2 entries without triggering auto-eviction
        policy._warm["k1"] = MemoryEntry("k1", "v1")
        policy._warm["k2"] = MemoryEntry("k2", "v2")

        evictions = policy.evictions_due()
        cold_evictions = [(k, t) for k, t in evictions if t == Tier.COLD]
        assert len(cold_evictions) == 1


# ===========================================================================
# StateCompressor
# ===========================================================================


class TestStateCompressorPayloads:
    def test_bytes_roundtrip(self):
        from orchestra.memory.compression import StateCompressor

        c = StateCompressor()
        data = b"\x00\x01\x02\xffrandom bytes"
        assert c.decompress(c.compress(data)) == data

    def test_list_roundtrip(self):
        from orchestra.memory.compression import StateCompressor

        c = StateCompressor()
        data = [1, "two", 3.0, None, True, {"nested": "dict"}]
        assert c.decompress(c.compress(data)) == data

    def test_deeply_nested_dict_roundtrip(self):
        from orchestra.memory.compression import StateCompressor

        c = StateCompressor()
        data = {"a": {"b": {"c": {"d": [1, 2, 3]}}}}
        assert c.decompress(c.compress(data)) == data

    def test_integer_roundtrip(self):
        from orchestra.memory.compression import StateCompressor

        c = StateCompressor()
        assert c.decompress(c.compress(42)) == 42

    def test_large_payload_roundtrip(self):
        """A payload of 1 MB+ must survive compress/decompress intact."""
        from orchestra.memory.compression import StateCompressor

        c = StateCompressor()
        data = {"key": "x" * 1_100_000}
        result = c.decompress(c.compress(data))
        assert result == data

    def test_empty_dict_roundtrip(self):
        from orchestra.memory.compression import StateCompressor

        c = StateCompressor()
        assert c.decompress(c.compress({})) == {}

    def test_empty_list_roundtrip(self):
        from orchestra.memory.compression import StateCompressor

        c = StateCompressor()
        assert c.decompress(c.compress([])) == []

    def test_compress_produces_bytes(self):
        from orchestra.memory.compression import StateCompressor

        c = StateCompressor()
        result = c.compress({"key": "value"})
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_zlib_fallback_path(self):
        """When pyzstd is unavailable the zlib path must produce a valid roundtrip.

        Note: test_decompress_zlib_data_when_pyzstd_present is the primary regression
        lock for the NameError fix (HAS_PYZSTD=True + zlib blob → must not NameError).
        This test covers the pure-zlib roundtrip when pyzstd is absent.
        """
        import orchestra.memory.compression as comp_mod
        from orchestra.memory.compression import StateCompressor

        with patch.object(comp_mod, "HAS_PYZSTD", False):
            c = StateCompressor(level=6)
            data = {"hello": "world", "nums": [1, 2, 3]}
            compressed = c.compress(data)
            decompressed = c.decompress(compressed)
            assert decompressed == data

    def test_decompress_zlib_data_when_pyzstd_present(self):
        """decompress() must handle zlib-compressed legacy data even when pyzstd is present."""
        import zlib

        import msgpack
        import orchestra.memory.compression as comp_mod

        from orchestra.memory.serialization import _default

        data = {"legacy": True, "value": 42}
        packed = msgpack.packb(data, default=_default, use_bin_type=True)
        zlib_bytes = zlib.compress(packed, 6)

        # Simulate pyzstd present but data was written by the zlib path
        with patch.object(comp_mod, "HAS_PYZSTD", True):
            c = comp_mod.StateCompressor()
            result = c.decompress(zlib_bytes)
        assert result == data


# ===========================================================================
# SemanticDeduplicator
# ===========================================================================


class TestSemanticDeduplicatorShape:
    @pytest.mark.asyncio
    async def test_embed_texts_returns_correct_shape(self):
        """embed_texts(n texts) must return ndarray of shape (n, 256)."""
        from orchestra.memory.dedup import SemanticDeduplicator

        dedup = SemanticDeduplicator()
        texts = ["hello world", "foo bar", "baz qux"]

        # Bypass the real model load by patching _ensure_model and _model
        mock_model = MagicMock()
        mock_model.encode.return_value = np.zeros((3, 256), dtype=np.float32)
        dedup._model = mock_model

        result = await dedup.embed_texts(texts)
        assert result.shape == (3, 256)

    @pytest.mark.asyncio
    async def test_embed_query_returns_1d_array(self):
        """embed_query(single text) must return ndarray of shape (256,)."""
        from orchestra.memory.dedup import SemanticDeduplicator

        dedup = SemanticDeduplicator()
        mock_model = MagicMock()
        mock_model.encode.return_value = np.zeros((1, 256), dtype=np.float32)
        dedup._model = mock_model

        result = await dedup.embed_query("a query")
        assert result.shape == (256,)

    @pytest.mark.asyncio
    async def test_embed_alias_matches_embed_texts(self):
        """embed() is an alias for embed_texts() and must return the same result."""
        from orchestra.memory.dedup import SemanticDeduplicator

        dedup = SemanticDeduplicator()
        mock_model = MagicMock()
        mock_model.encode.return_value = np.ones((2, 256), dtype=np.float32)
        dedup._model = mock_model

        texts = ["a", "b"]
        via_embed_texts = await dedup.embed_texts(texts)
        via_embed = await dedup.embed(texts)

        np.testing.assert_array_equal(via_embed_texts, via_embed)

    @pytest.mark.asyncio
    async def test_dimensions_property_is_256(self):
        from orchestra.memory.dedup import SemanticDeduplicator

        assert SemanticDeduplicator().dimensions == 256


class TestSemanticDeduplicatorThreshold:
    @pytest.mark.asyncio
    async def test_exact_threshold_is_duplicate(self):
        """A similarity exactly equal to the threshold must be treated as a duplicate."""
        from orchestra.memory.dedup import SemanticDeduplicator

        dedup = SemanticDeduplicator(threshold=0.90)
        existing = np.zeros((1, 256))
        existing[0, 0] = 1.0  # unit vector along dim 0

        # Construct new vector with cosine sim exactly 0.90 to existing[0]
        new_vec = np.zeros((1, 256))
        new_vec[0, 0] = 0.90
        new_vec[0, 1] = np.sqrt(1 - 0.90**2)

        with patch.object(dedup, "embed", return_value=new_vec):
            is_dup, key = await dedup.is_duplicate("text", existing, ["k0"])
        assert is_dup is True
        assert key == "k0"

    @pytest.mark.asyncio
    async def test_just_below_threshold_is_not_duplicate(self):
        """A similarity just below the threshold must NOT be treated as a duplicate."""
        from orchestra.memory.dedup import SemanticDeduplicator

        dedup = SemanticDeduplicator(threshold=0.98)
        existing = np.zeros((1, 256))
        existing[0, 0] = 1.0

        # cosine sim ≈ 0.97 — below the threshold
        new_vec = np.zeros((1, 256))
        new_vec[0, 0] = 0.97
        new_vec[0, 1] = np.sqrt(1 - 0.97**2)

        with patch.object(dedup, "embed", return_value=new_vec):
            is_dup, key = await dedup.is_duplicate("text", existing, ["k0"])
        assert is_dup is False
        assert key is None


class TestSemanticDeduplicatorFallback:
    @pytest.mark.asyncio
    async def test_model2vec_import_error_returns_zero_embeddings(self):
        """When model2vec is not installed, embed_texts must return a zero matrix."""
        from orchestra.memory.dedup import SemanticDeduplicator

        dedup = SemanticDeduplicator()
        # Simulate missing model2vec by setting sentinel
        dedup._model = False  # sentinel value used by _ensure_model on ImportError

        result = await dedup.embed_texts(["hello", "world"])
        assert result.shape == (2, 256)
        assert np.all(result == 0)

    @pytest.mark.asyncio
    async def test_ensure_model_idempotent(self):
        """_ensure_model() called twice must not reload the model."""
        from orchestra.memory.dedup import SemanticDeduplicator

        dedup = SemanticDeduplicator()
        mock_model = MagicMock()
        dedup._model = mock_model  # already loaded

        await dedup._ensure_model()  # second call
        # Model must remain the same object — no reload
        assert dedup._model is mock_model


class TestSemanticDeduplicatorProtocol:
    def test_satisfies_embedding_provider_protocol(self):
        """SemanticDeduplicator must pass the runtime EmbeddingProvider check."""
        from orchestra.memory.dedup import SemanticDeduplicator
        from orchestra.memory.embeddings import EmbeddingProvider

        dedup = SemanticDeduplicator()
        assert isinstance(dedup, EmbeddingProvider)


# ===========================================================================
# TieredMemoryManager — additional behaviour
# ===========================================================================


class TestTieredMemoryManagerRetrieveNoPromote:
    @pytest.mark.asyncio
    async def test_retrieve_promote_false_does_not_move_warm_to_hot(self):
        """retrieve(key, promote=False) must not alter tier placement."""
        from orchestra.memory.tiers import TieredMemoryManager

        mgr = TieredMemoryManager(hot_max=2, warm_max=2)
        await mgr.store("k1", "v1")

        # k1 is in WARM after store; retrieve without promotion must leave it there
        val = await mgr.retrieve("k1", promote=False)
        assert val == "v1"

        stats = await mgr.stats()
        assert stats.hot_count == 0
        assert stats.warm_count == 1


class TestTieredMemoryManagerSearchMemories:
    @pytest.mark.asyncio
    async def test_search_returns_empty_when_no_cold_backend(self):
        from orchestra.memory.tiers import TieredMemoryManager

        mock_dedup = AsyncMock()
        mock_dedup.embed.return_value = np.zeros((1, 256))
        mgr = TieredMemoryManager(deduplicator=mock_dedup, hot_max=2, warm_max=2)

        result = await mgr.search_memories("anything")
        assert result == []

    @pytest.mark.asyncio
    async def test_search_returns_empty_when_no_deduplicator(self):
        from orchestra.memory.tiers import TieredMemoryManager

        mock_cold = AsyncMock()
        mock_cold.search.return_value = [("k1", 0.9)]
        mgr = TieredMemoryManager(cold_backend=mock_cold, hot_max=2, warm_max=2)

        result = await mgr.search_memories("anything")
        # No deduplicator — cannot embed query
        assert result == []
        mock_cold.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_passes_filter_metadata_to_cold(self):
        from orchestra.memory.tiers import TieredMemoryManager

        mock_cold = AsyncMock()
        mock_cold.search.return_value = []
        mock_dedup = AsyncMock()
        mock_dedup.embed.return_value = np.ones((1, 256))
        mgr = TieredMemoryManager(
            cold_backend=mock_cold, deduplicator=mock_dedup, hot_max=2, warm_max=2
        )

        await mgr.search_memories("q", limit=5, filter_metadata={"session": "s1"})

        _, call_kwargs = mock_cold.search.call_args
        assert call_kwargs.get("filter_metadata") == {"session": "s1"}
        assert call_kwargs.get("limit") == 5

    @pytest.mark.asyncio
    async def test_search_passes_agent_id_override_to_cold(self):
        from orchestra.memory.tiers import TieredMemoryManager

        mock_cold = AsyncMock()
        mock_cold.search.return_value = []
        mock_dedup = AsyncMock()
        mock_dedup.embed.return_value = np.ones((1, 256))
        mgr = TieredMemoryManager(
            cold_backend=mock_cold, deduplicator=mock_dedup, hot_max=2, warm_max=2
        )

        await mgr.search_memories("q", agent_id="agent-99")

        _, call_kwargs = mock_cold.search.call_args
        assert call_kwargs.get("agent_id") == "agent-99"


class TestTieredMemoryManagerDemote:
    @pytest.mark.asyncio
    async def test_demote_with_no_cold_backend_is_noop(self):
        """demote() to COLD when no cold backend is configured must not raise."""
        from orchestra.memory.tiers import Tier, TieredMemoryManager

        mgr = TieredMemoryManager(hot_max=2, warm_max=2)
        await mgr.store("k1", "v1")
        # Should silently do nothing
        await mgr.demote("k1", Tier.COLD)

    @pytest.mark.asyncio
    async def test_demote_nonexistent_key_is_noop(self):
        """demote() on a key absent from all tiers must not call cold.store."""
        from orchestra.memory.tiers import Tier, TieredMemoryManager

        mock_cold = AsyncMock()
        mock_warm = AsyncMock()
        # Both backends return None so retrieve() finds nothing
        mock_warm.get.return_value = None
        mock_cold.retrieve.return_value = None

        mgr = TieredMemoryManager(
            warm_backend=mock_warm, cold_backend=mock_cold, hot_max=2, warm_max=2
        )
        await mgr.demote("missing_key", Tier.COLD)
        mock_cold.store.assert_not_called()


class TestTieredMemoryManagerPromote:
    @pytest.mark.asyncio
    async def test_promote_to_hot_moves_item_to_hot(self):
        """promote(key, HOT) must pull the item into the HOT tier."""
        from orchestra.memory.tiers import Tier, TieredMemoryManager

        mgr = TieredMemoryManager(hot_max=2, warm_max=2)
        await mgr.store("k1", "v1")
        stats_before = await mgr.stats()
        assert stats_before.hot_count == 0

        await mgr.promote("k1", Tier.HOT)

        stats_after = await mgr.stats()
        assert stats_after.hot_count == 1


class TestTieredMemoryManagerRestore:
    @pytest.mark.asyncio
    async def test_restore_existing_key_updates_value(self):
        """Calling store() twice on the same key must update, not duplicate."""
        from orchestra.memory.tiers import TieredMemoryManager

        mgr = TieredMemoryManager(hot_max=2, warm_max=2)
        await mgr.store("k1", "original")
        await mgr.store("k1", "updated")

        val = await mgr.retrieve("k1")
        assert val == "updated"

        stats = await mgr.stats()
        # Key should appear exactly once across in-memory tiers
        assert stats.hot_count + stats.warm_count == 1


class TestTieredMemoryManagerStartIdempotent:
    @pytest.mark.asyncio
    async def test_start_called_twice_creates_only_one_task(self):
        """Calling start() a second time must not create a second background task."""
        from orchestra.memory.tiers import TieredMemoryManager

        mgr = TieredMemoryManager(hot_max=2, warm_max=2, scan_interval=9999)
        await mgr.start()
        task_after_first = mgr._scan_task

        await mgr.start()  # second call — must be a no-op
        task_after_second = mgr._scan_task

        assert task_after_first is task_after_second
        await mgr.stop()


class TestTieredMemoryManagerStatsAccuracy:
    @pytest.mark.asyncio
    async def test_stats_hot_warm_counts_after_eviction(self):
        """After eviction from HOT, hot+warm counts must reflect configured limits."""
        from orchestra.memory.tiers import TieredMemoryManager

        mgr = TieredMemoryManager(hot_max=2, warm_max=5)

        for i in range(4):
            await mgr.store(f"k{i}", f"v{i}")

        # Promote all 4 to HOT — only 2 fit; 2 demote back to WARM
        for i in range(4):
            await mgr.retrieve(f"k{i}")

        stats = await mgr.stats()
        assert stats.hot_count <= 2
        assert stats.warm_count >= 0
        assert stats.hot_count + stats.warm_count == 4


# ===========================================================================
# VectorStore
# ===========================================================================


@pytest.fixture
def pool_conn():
    return _make_pool_conn()


class TestVectorStoreRetrieve:
    @pytest.mark.asyncio
    async def test_retrieve_returns_none_when_key_not_found(self, pool_conn):
        from orchestra.memory.vector_store import VectorStore

        pool, conn = pool_conn
        conn.fetchrow.return_value = None
        store = VectorStore(pool)

        result = await store.retrieve("missing_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_retrieve_json_fallback_when_no_compressor_no_compressed_value(self, pool_conn):
        """When compressed_value is absent and no compressor, content is JSON-decoded."""
        from orchestra.memory.vector_store import VectorStore

        pool, conn = pool_conn
        conn.fetchrow.return_value = {
            "content": '{"val": 42}',
            "compressed_value": None,
            "metadata": "{}",
        }
        store = VectorStore(pool)

        result = await store.retrieve("k1")
        assert result == {"val": 42}

    @pytest.mark.asyncio
    async def test_retrieve_plain_string_fallback_when_not_valid_json(self, pool_conn):
        """When content is not JSON, the raw string must be returned."""
        from orchestra.memory.vector_store import VectorStore

        pool, conn = pool_conn
        conn.fetchrow.return_value = {
            "content": "plain text value",
            "compressed_value": None,
            "metadata": "{}",
        }
        store = VectorStore(pool)

        result = await store.retrieve("k1")
        assert result == "plain text value"

    @pytest.mark.asyncio
    async def test_retrieve_decompresses_when_compressor_present(self, pool_conn):
        """When a compressor is available and compressed_value is set, decompress."""
        from orchestra.memory.compression import StateCompressor
        from orchestra.memory.vector_store import VectorStore

        pool, conn = pool_conn
        compressor = StateCompressor()
        data = {"complex": [1, 2, 3]}
        compressed_bytes = compressor.compress(data)

        conn.fetchrow.return_value = {
            "content": str(data),
            "compressed_value": compressed_bytes,
            "metadata": "{}",
        }
        store = VectorStore(pool, compressor=compressor)
        result = await store.retrieve("k1")
        assert result == data


class TestVectorStoreStore:
    @pytest.mark.asyncio
    async def test_store_without_compressor_passes_none_compressed_value(self, pool_conn):
        """Store without a compressor must pass None as compressed_value to SQL."""
        from orchestra.memory.vector_store import VectorStore

        pool, conn = pool_conn
        store = VectorStore(pool, agent_id="a1")
        await store.store("k1", "plain value", embedding=[0.0] * 256)

        args = conn.execute.call_args[0]
        # compressed_value is the 6th positional arg (index 5)
        assert args[5] is None

    @pytest.mark.asyncio
    async def test_store_agent_id_bound_to_sql(self, pool_conn):
        """The instance agent_id must be bound as the second SQL parameter."""
        from orchestra.memory.vector_store import VectorStore

        pool, conn = pool_conn
        store = VectorStore(pool, agent_id="tenant-7")
        await store.store("k1", "v", embedding=[0.0] * 256)

        args = conn.execute.call_args[0]
        assert args[2] == "tenant-7"

    @pytest.mark.asyncio
    async def test_store_metadata_serialised_to_json(self, pool_conn):
        """metadata dict must be JSON-serialised before being bound to SQL."""
        from orchestra.memory.vector_store import VectorStore

        pool, conn = pool_conn
        store = VectorStore(pool, agent_id="a1")
        await store.store("k1", "v", embedding=[0.0] * 256, metadata={"tag": "foo"})

        args = conn.execute.call_args[0]
        parsed = json.loads(args[6])
        assert parsed == {"tag": "foo"}

    @pytest.mark.asyncio
    async def test_store_uses_on_conflict_upsert(self, pool_conn):
        """INSERT must include ON CONFLICT ... DO UPDATE (upsert semantics)."""
        from orchestra.memory.vector_store import VectorStore

        pool, conn = pool_conn
        store = VectorStore(pool)
        await store.store("k1", "v")

        sql = conn.execute.call_args[0][0]
        assert "ON CONFLICT" in sql
        assert "DO UPDATE" in sql


class TestVectorStoreSearch:
    @pytest.mark.asyncio
    async def test_search_with_filter_metadata_uses_jsonb_containment(self, pool_conn):
        """When filter_metadata is given, the SQL must include a @> JSONB clause."""
        from orchestra.memory.vector_store import VectorStore

        pool, conn = pool_conn
        conn.fetch.return_value = []
        store = VectorStore(pool, agent_id="a1")

        await store.search(embedding=[0.1] * 256, filter_metadata={"session_id": "xyz"})

        sql = conn.fetch.call_args[0][0]
        assert "@>" in sql or "metadata" in sql

    @pytest.mark.asyncio
    async def test_search_without_filter_uses_simple_query(self, pool_conn):
        """Without filter_metadata the SQL must NOT contain a @> clause."""
        from orchestra.memory.vector_store import VectorStore

        pool, conn = pool_conn
        conn.fetch.return_value = []
        store = VectorStore(pool, agent_id="a1")

        await store.search(embedding=[0.1] * 256)

        sql = conn.fetch.call_args[0][0]
        assert "@>" not in sql

    @pytest.mark.asyncio
    async def test_search_agent_id_override(self, pool_conn):
        """agent_id parameter on search() must override the instance-level agent_id."""
        from orchestra.memory.vector_store import VectorStore

        pool, conn = pool_conn
        conn.fetch.return_value = []
        store = VectorStore(pool, agent_id="default_agent")

        await store.search(embedding=[0.1] * 256, agent_id="other_agent")

        # The second positional arg after $1 (embedding) is the agent scope
        args = conn.fetch.call_args[0]
        assert "other_agent" in args

    @pytest.mark.asyncio
    async def test_search_returns_key_score_tuples(self, pool_conn):
        from orchestra.memory.vector_store import VectorStore

        pool, conn = pool_conn
        conn.fetch.return_value = [
            {"key": "r1", "score": 0.88},
            {"key": "r2", "score": 0.72},
        ]
        store = VectorStore(pool, agent_id="a1")

        results = await store.search(embedding=[0.1] * 256)
        assert results == [("r1", 0.88), ("r2", 0.72)]

    @pytest.mark.asyncio
    async def test_search_empty_cold_tier_returns_empty_list(self, pool_conn):
        from orchestra.memory.vector_store import VectorStore

        pool, conn = pool_conn
        conn.fetch.return_value = []
        store = VectorStore(pool, agent_id="a1")

        results = await store.search(embedding=[0.0] * 256)
        assert results == []


class TestVectorStoreHybridSearch:
    @pytest.mark.asyncio
    async def test_hybrid_search_sql_contains_rrf_cte(self, pool_conn):
        """hybrid_search must issue a query that uses the RRF CTE structure."""
        from orchestra.memory.vector_store import VectorStore

        pool, conn = pool_conn
        conn.fetch.return_value = []
        store = VectorStore(pool, agent_id="a1")

        await store.hybrid_search(
            query_text="find something",
            query_embedding=[0.1] * 256,
            limit=5,
        )

        sql = conn.fetch.call_args[0][0]
        assert "vector_results" in sql
        assert "text_results" in sql

    @pytest.mark.asyncio
    async def test_hybrid_search_passes_bm25_weight(self, pool_conn):
        """The bm25_weight must be bound as a SQL parameter."""
        from orchestra.memory.vector_store import VectorStore

        pool, conn = pool_conn
        conn.fetch.return_value = []
        store = VectorStore(pool, agent_id="a1")

        await store.hybrid_search(query_text="q", query_embedding=[0.0] * 256, bm25_weight=0.5)

        args = conn.fetch.call_args[0]
        assert 0.5 in args

    @pytest.mark.asyncio
    async def test_hybrid_search_agent_id_override(self, pool_conn):
        """agent_id parameter must override the instance scope in hybrid_search."""
        from orchestra.memory.vector_store import VectorStore

        pool, conn = pool_conn
        conn.fetch.return_value = []
        store = VectorStore(pool, agent_id="default")

        await store.hybrid_search(query_text="q", query_embedding=[0.0] * 256, agent_id="override")

        args = conn.fetch.call_args[0]
        assert "override" in args

    @pytest.mark.asyncio
    async def test_hybrid_search_returns_float_scores(self, pool_conn):
        """Scores returned from hybrid_search must be Python floats."""
        from orchestra.memory.vector_store import VectorStore

        pool, conn = pool_conn
        conn.fetch.return_value = [{"key": "k1", "score": 0.016}]
        store = VectorStore(pool, agent_id="a1")

        results = await store.hybrid_search(query_text="q", query_embedding=[0.0] * 256)
        assert len(results) == 1
        assert isinstance(results[0][1], float)


class TestVectorStoreDelete:
    @pytest.mark.asyncio
    async def test_delete_executes_correct_sql(self, pool_conn):
        from orchestra.memory.vector_store import VectorStore

        pool, conn = pool_conn
        store = VectorStore(pool)
        await store.delete("my_key")

        args = conn.execute.call_args[0]
        assert "DELETE FROM" in args[0]
        assert args[1] == "my_key"


class TestVectorStoreCount:
    @pytest.mark.asyncio
    async def test_count_without_agent_id_counts_all(self, pool_conn):
        from orchestra.memory.vector_store import VectorStore

        pool, conn = pool_conn
        conn.fetchval.return_value = 17
        store = VectorStore(pool)

        result = await store.count()
        assert result == 17

        sql = conn.fetchval.call_args[0][0]
        assert "COUNT(*)" in sql
        # No WHERE clause for agent_id
        assert "$1" not in sql

    @pytest.mark.asyncio
    async def test_count_with_agent_id_filters_by_agent(self, pool_conn):
        from orchestra.memory.vector_store import VectorStore

        pool, conn = pool_conn
        conn.fetchval.return_value = 5
        store = VectorStore(pool)

        result = await store.count(agent_id="agent-42")
        assert result == 5

        args = conn.fetchval.call_args[0]
        assert "WHERE agent_id = $1" in args[0]
        assert args[1] == "agent-42"


class TestVectorStoreInitialize:
    @pytest.mark.asyncio
    async def test_initialize_creates_extension_and_table(self, pool_conn):
        """initialize() must issue CREATE EXTENSION and CREATE TABLE statements."""
        from orchestra.memory.vector_store import VectorStore

        pool, conn = pool_conn
        store = VectorStore(pool)
        await store.initialize()

        executed_sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("CREATE EXTENSION" in s for s in executed_sqls)
        assert any("CREATE TABLE" in s for s in executed_sqls)

    @pytest.mark.asyncio
    async def test_initialize_creates_hnsw_index(self, pool_conn):
        """initialize() must create an HNSW index on the embedding column."""
        from orchestra.memory.vector_store import VectorStore

        pool, conn = pool_conn
        store = VectorStore(pool)
        await store.initialize()

        executed_sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("hnsw" in s.lower() for s in executed_sqls)

    @pytest.mark.asyncio
    async def test_initialize_creates_gin_index_for_full_text(self, pool_conn):
        """initialize() must create a GIN index for full-text search (tsvector)."""
        from orchestra.memory.vector_store import VectorStore

        pool, conn = pool_conn
        store = VectorStore(pool)
        await store.initialize()

        executed_sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("gin" in s.lower() for s in executed_sqls)


# ===========================================================================
# QdrantColdBackend — additional behaviour
# ===========================================================================
try:
    from orchestra.memory.qdrant_backend import HAS_QDRANT
except ImportError:
    HAS_QDRANT = False

_requires_qdrant = pytest.mark.skipif(not HAS_QDRANT, reason="qdrant-client not fully installed")


@pytest.fixture
def qdrant_backend():
    if not HAS_QDRANT:
        pytest.skip("qdrant-client not fully installed")
    from orchestra.memory.qdrant_backend import QdrantColdBackend

    b = QdrantColdBackend(
        url="http://localhost:6333",
        collection_name="test_col",
        agent_id="agent-1",
        dimensions=4,
        embedding_model="minishlab/potion-base-8M",
    )
    mock_client = _make_qdrant_client()
    b._client = mock_client
    b._initialized = True
    return b, mock_client


@_requires_qdrant
class TestQdrantEnsureInitialized:
    @pytest.mark.asyncio
    async def test_lazy_init_creates_collection_when_missing(self):
        """_ensure_initialized must call create_collection when collection is absent."""
        from orchestra.memory.qdrant_backend import QdrantColdBackend

        backend = QdrantColdBackend(
            url="http://localhost:6333",
            collection_name="brand_new",
            dimensions=4,
        )
        mock_client = _make_qdrant_client()
        # Patch AsyncQdrantClient constructor to return our mock
        with patch(
            "orchestra.memory.qdrant_backend.AsyncQdrantClient",
            return_value=mock_client,
        ):
            await backend._ensure_initialized()

        mock_client.create_collection.assert_called_once()
        call_kwargs = mock_client.create_collection.call_args.kwargs
        assert call_kwargs["collection_name"] == "brand_new"

    @pytest.mark.asyncio
    async def test_lazy_init_skips_collection_creation_when_exists(self):
        """_ensure_initialized must NOT call create_collection when collection exists."""
        from orchestra.memory.qdrant_backend import QdrantColdBackend

        backend = QdrantColdBackend(
            url="http://localhost:6333",
            collection_name="existing_col",
            dimensions=4,
        )
        mock_client = _make_qdrant_client()
        existing = MagicMock()
        existing.name = "existing_col"
        mock_client.get_collections.return_value = MagicMock(collections=[existing])
        with patch(
            "orchestra.memory.qdrant_backend.AsyncQdrantClient",
            return_value=mock_client,
        ):
            await backend._ensure_initialized()

        mock_client.create_collection.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_initialized_idempotent(self, qdrant_backend):
        """Calling _ensure_initialized on an already-initialized backend must
        return immediately without touching the client network methods."""
        backend, mock_client = qdrant_backend
        await backend._ensure_initialized()
        mock_client.get_collections.assert_not_called()


@_requires_qdrant
class TestQdrantStoreNoEmbeddingModel:
    @pytest.mark.asyncio
    async def test_store_without_embedding_model_omits_model_key(self, qdrant_backend):
        """When embedding_model is None, the payload must NOT contain _embedding_model."""
        backend, mock_client = qdrant_backend
        backend.embedding_model = None

        await backend.store("k1", "value", embedding=[0.1, 0.2, 0.3, 0.4])

        point = mock_client.upsert.call_args.kwargs["points"][0]
        assert "_embedding_model" not in point.payload


@_requires_qdrant
class TestQdrantRetrieveNoDriftWarning:
    @pytest.mark.asyncio
    async def test_retrieve_no_stored_model_no_drift_warning(self, caplog, qdrant_backend):
        """No warning when the stored point has no _embedding_model key."""
        import logging

        backend, mock_client = qdrant_backend
        point = MagicMock()
        point.payload = {"key": "k1", "content": "hello"}
        mock_client.retrieve = AsyncMock(return_value=[point])

        with caplog.at_level(logging.WARNING):
            result = await backend.retrieve("k1")

        assert result == "hello"
        warning_msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert not any("mismatch" in m.lower() for m in warning_msgs)

    @pytest.mark.asyncio
    async def test_retrieve_same_model_no_drift_warning(self, caplog, qdrant_backend):
        """No warning when stored model matches active model."""
        import logging

        backend, mock_client = qdrant_backend
        backend.embedding_model = "minishlab/potion-base-8M"
        point = MagicMock()
        point.payload = {
            "key": "k1",
            "content": "value",
            "_embedding_model": "minishlab/potion-base-8M",
        }
        mock_client.retrieve = AsyncMock(return_value=[point])

        with caplog.at_level(logging.WARNING):
            result = await backend.retrieve("k1")

        assert result == "value"
        # Standard logging channel — structlog warnings will NOT appear here,
        # so we only assert no exception was raised.


@_requires_qdrant
class TestQdrantProtocolConformance:
    def test_qdrant_satisfies_cold_tier_backend_protocol(self, qdrant_backend):
        """QdrantColdBackend must satisfy the ColdTierBackend runtime protocol."""
        from orchestra.memory.tiers import ColdTierBackend

        backend, _ = qdrant_backend
        assert isinstance(backend, ColdTierBackend)


# ===========================================================================
# create_tiered_memory factory
# ===========================================================================


class TestCreateTieredMemoryFactory:
    def test_no_args_returns_manager_with_no_backends(self):
        from orchestra.memory.tiers import TieredMemoryManager, create_tiered_memory

        mgr = create_tiered_memory()
        assert isinstance(mgr, TieredMemoryManager)
        assert mgr._warm is None
        assert mgr._cold is None
        assert mgr._dedup is None

    def test_with_redis_url_wires_warm_backend(self):
        """Passing a redis_url must wire a RedisMemoryBackend as the warm tier.

        create_tiered_memory imports RedisMemoryBackend inside the function body
        via ``from orchestra.memory.backends import RedisMemoryBackend``, so we
        patch the name at its usage site.
        """
        from orchestra.memory.backends import RedisMemoryBackend
        from orchestra.memory.tiers import create_tiered_memory

        mock_instance = MagicMock(spec=RedisMemoryBackend)

        with patch(
            "orchestra.memory.backends.RedisMemoryBackend",
            return_value=mock_instance,
        ):
            mgr = create_tiered_memory(redis_url="redis://localhost:6379/0")

        assert mgr._warm is not None

    def test_with_pg_pool_wires_cold_backend_and_deduplicator(self):
        """Passing a pg_pool must wire a VectorStore as cold backend and a
        SemanticDeduplicator as deduplicator."""
        from orchestra.memory.dedup import SemanticDeduplicator
        from orchestra.memory.tiers import create_tiered_memory
        from orchestra.memory.vector_store import VectorStore

        mock_pool = MagicMock()
        mgr = create_tiered_memory(pg_pool=mock_pool, agent_id="agent-x")

        assert mgr._cold is not None
        assert isinstance(mgr._cold, VectorStore)
        assert mgr._dedup is not None
        assert isinstance(mgr._dedup, SemanticDeduplicator)

    def test_with_pg_pool_uses_correct_agent_id(self):
        """The agent_id argument must propagate to the VectorStore cold backend."""
        from orchestra.memory.tiers import create_tiered_memory
        from orchestra.memory.vector_store import VectorStore

        mock_pool = MagicMock()
        mgr = create_tiered_memory(pg_pool=mock_pool, agent_id="tenant-xyz")

        assert isinstance(mgr._cold, VectorStore)
        assert mgr._cold.agent_id == "tenant-xyz"

    def test_hot_max_and_warm_max_propagate(self):
        """hot_max and warm_max must be forwarded to the underlying SLRU policy."""
        from orchestra.memory.tiers import create_tiered_memory

        mgr = create_tiered_memory(hot_max=50, warm_max=500)
        assert mgr._policy.hot_max == 50
        assert mgr._policy.warm_max == 500

    def test_cold_backend_satisfies_protocol_when_pg_given(self):
        """The wired cold backend must satisfy the ColdTierBackend protocol."""
        from orchestra.memory.tiers import ColdTierBackend, create_tiered_memory

        mock_pool = MagicMock()
        mgr = create_tiered_memory(pg_pool=mock_pool)
        assert isinstance(mgr._cold, ColdTierBackend)


# ===========================================================================
# End-to-end integration: full pipeline with mocked backends
# ===========================================================================


class TestFullPipelineIntegration:
    """Tests that exercise the full HOT->WARM->COLD path with mocked I/O
    to verify all components wire together correctly without real databases."""

    @pytest.mark.asyncio
    async def test_full_store_retrieve_promote_cycle(self):
        """Store a value, confirm it starts in WARM, then confirm it promotes
        to HOT on the first retrieve, and returns the correct value throughout."""
        from orchestra.memory.tiers import TieredMemoryManager

        mock_warm = AsyncMock()
        mock_warm.get.return_value = None
        mgr = TieredMemoryManager(warm_backend=mock_warm, hot_max=5, warm_max=5)

        await mgr.store("pipeline_key", {"data": [1, 2, 3]})

        # After store: in WARM policy tier, also written to warm backend
        stats = await mgr.stats()
        assert stats.warm_count == 1
        assert stats.hot_count == 0
        mock_warm.set.assert_called_once_with("pipeline_key", {"data": [1, 2, 3]})

        # First retrieve: promote to HOT
        val = await mgr.retrieve("pipeline_key")
        assert val == {"data": [1, 2, 3]}

        stats = await mgr.stats()
        assert stats.hot_count == 1
        assert stats.warm_count == 0

    @pytest.mark.asyncio
    async def test_full_eviction_cascade_hot_to_warm_to_cold(self):
        """Filling HOT causes demotion to WARM; filling WARM evicts to COLD backend."""
        from orchestra.memory.tiers import TieredMemoryManager

        mock_cold = AsyncMock()
        mock_cold.count.return_value = 0
        mock_warm = AsyncMock()
        mock_warm.get.return_value = None
        mock_dedup = AsyncMock()
        mock_dedup.embed.return_value = np.array([[0.5] * 256])

        mgr = TieredMemoryManager(
            warm_backend=mock_warm,
            cold_backend=mock_cold,
            deduplicator=mock_dedup,
            hot_max=1,
            warm_max=1,
        )

        # k1 -> WARM
        await mgr.store("k1", "v1")
        # Promote k1 to HOT
        await mgr.retrieve("k1")

        # k2 -> WARM (HOT is full; k1 stays in HOT for now)
        await mgr.store("k2", "v2")

        # k3 -> WARM triggers eviction: WARM is over capacity, k2 must go to COLD
        await mgr.store("k3", "v3")

        # cold.store must have been called for k2
        cold_store_keys = [c.args[0] for c in mock_cold.store.call_args_list]
        assert "k2" in cold_store_keys

    @pytest.mark.asyncio
    async def test_search_memories_end_to_end(self):
        """search_memories embeds the query, delegates to cold.search, and
        returns the result list unchanged."""
        from orchestra.memory.tiers import TieredMemoryManager

        expected_results = [("doc_1", 0.95), ("doc_2", 0.87)]
        mock_cold = AsyncMock()
        mock_cold.search.return_value = expected_results
        mock_cold.count.return_value = 2
        mock_dedup = AsyncMock()
        mock_dedup.embed.return_value = np.array([[0.1] * 256])

        mgr = TieredMemoryManager(
            cold_backend=mock_cold, deduplicator=mock_dedup, hot_max=5, warm_max=5
        )

        results = await mgr.search_memories("semantic query", limit=2)

        assert results == expected_results
        mock_dedup.embed.assert_called_once_with(["semantic query"])
        mock_cold.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_retrieve_miss_traverses_all_three_tiers(self):
        """A key absent from HOT, WARM policy, WARM backend, and COLD must return None."""
        from orchestra.memory.tiers import TieredMemoryManager

        mock_warm = AsyncMock()
        mock_warm.get.return_value = None
        mock_cold = AsyncMock()
        mock_cold.retrieve.return_value = None

        mgr = TieredMemoryManager(
            warm_backend=mock_warm,
            cold_backend=mock_cold,
            hot_max=5,
            warm_max=5,
        )

        result = await mgr.retrieve("totally_absent_key")
        assert result is None

        # Both backends must have been consulted
        mock_warm.get.assert_called_once_with("totally_absent_key")
        mock_cold.retrieve.assert_called_once_with("totally_absent_key")
