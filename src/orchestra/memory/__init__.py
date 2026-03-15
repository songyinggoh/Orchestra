"""Memory module for Orchestra."""

from orchestra.memory.manager import InMemoryMemoryManager, MemoryManager
from orchestra.memory.backends import MemoryBackend, InMemoryMemoryBackend, RedisMemoryBackend
from orchestra.memory.tiers import TieredMemoryManager, Tier, MemoryEntry, TierStats

# Optional/Extra components
try:
    from orchestra.memory.vector_store import VectorStore
    from orchestra.memory.dedup import SemanticDeduplicator
    from orchestra.memory.compression import StateCompressor
    HAS_VECTORDB = True
except ImportError:
    HAS_VECTORDB = False

__all__ = [
    "MemoryManager",
    "InMemoryMemoryManager",
    "MemoryBackend",
    "InMemoryMemoryBackend",
    "RedisMemoryBackend",
    "TieredMemoryManager",
    "Tier",
    "MemoryEntry",
    "TierStats",
    "VectorStore",
    "SemanticDeduplicator",
    "StateCompressor",
]
