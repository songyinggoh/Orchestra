"""Memory module for Orchestra."""

from orchestra.memory.backends import InMemoryMemoryBackend, MemoryBackend, RedisMemoryBackend
from orchestra.memory.embeddings import EmbeddingProvider
from orchestra.memory.manager import InMemoryMemoryManager, MemoryManager
from orchestra.memory.tiers import (
    ColdTierBackend,
    MemoryEntry,
    Tier,
    TieredMemoryManager,
    TierStats,
    create_tiered_memory,
)
from orchestra.memory.tools import rag_tool

# Optional: pgvector backend — requires asyncpg + pgvector (+ model2vec for dedup)
try:
    from orchestra.memory.compression import StateCompressor
    from orchestra.memory.dedup import SemanticDeduplicator
    from orchestra.memory.vector_store import VectorStore

    HAS_VECTORDB = True
except ImportError:
    HAS_VECTORDB = False

# Optional: Qdrant backend — requires qdrant-client
try:
    from orchestra.memory.qdrant_backend import QdrantColdBackend

    HAS_QDRANT = True
except ImportError:
    HAS_QDRANT = False

__all__ = [
    "ColdTierBackend",
    "EmbeddingProvider",
    "HAS_QDRANT",
    "HAS_VECTORDB",
    "InMemoryMemoryBackend",
    "InMemoryMemoryManager",
    "MemoryBackend",
    "MemoryEntry",
    "MemoryManager",
    "QdrantColdBackend",
    "RedisMemoryBackend",
    "SemanticDeduplicator",
    "StateCompressor",
    "Tier",
    "TieredMemoryManager",
    "TierStats",
    "VectorStore",
    "create_tiered_memory",
    "rag_tool",
]
