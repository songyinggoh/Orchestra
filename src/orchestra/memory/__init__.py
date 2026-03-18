"""Memory module for Orchestra."""

from orchestra.memory.manager import InMemoryMemoryManager, MemoryManager
from orchestra.memory.backends import MemoryBackend, InMemoryMemoryBackend, RedisMemoryBackend
from orchestra.memory.embeddings import EmbeddingProvider
from orchestra.memory.tools import rag_tool
from orchestra.memory.tiers import (
    TieredMemoryManager,
    ColdTierBackend,
    Tier,
    MemoryEntry,
    TierStats,
    create_tiered_memory,
)

# Optional/Extra components — require asyncpg + pgvector (and optionally model2vec)
try:
    from orchestra.memory.vector_store import VectorStore
    from orchestra.memory.dedup import SemanticDeduplicator
    from orchestra.memory.compression import StateCompressor
    HAS_VECTORDB = True
except ImportError:
    HAS_VECTORDB = False

__all__ = [
    # Core protocols
    "MemoryManager",
    "MemoryBackend",
    "ColdTierBackend",
    "EmbeddingProvider",
    # Implementations
    "InMemoryMemoryManager",
    "InMemoryMemoryBackend",
    "RedisMemoryBackend",
    # Tiered memory
    "TieredMemoryManager",
    "create_tiered_memory",
    "rag_tool",
    "Tier",
    "MemoryEntry",
    "TierStats",
    # Vector DB (optional — requires asyncpg + pgvector)
    "VectorStore",
    "SemanticDeduplicator",
    "StateCompressor",
    "HAS_VECTORDB",
]
