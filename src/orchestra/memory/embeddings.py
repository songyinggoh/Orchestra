"""EmbeddingProvider protocol for pluggable embedding models."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import numpy as np


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for embedding models used in memory and retrieval.

    Implement this to plug in any embedding backend — local (model2vec, sentence-
    transformers) or API-based (OpenAI, Cohere).  :class:`SemanticDeduplicator`
    satisfies this protocol out of the box.

    Example::

        class MyEmbedder:
            @property
            def dimensions(self) -> int:
                return 1536

            async def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
                # call your model/API here
                ...

            async def embed_query(self, query: str) -> np.ndarray:
                return (await self.embed_texts([query]))[0]
    """

    @property
    def dimensions(self) -> int:
        """Number of dimensions produced by this model.

        Both :class:`~orchestra.memory.vector_store.VectorStore` (pgvector) and
        future backends (Qdrant, etc.) validate stored vectors against this value
        at construction time, so they fail fast with a clear error rather than a
        cryptic database exception when the model is swapped.
        """
        ...

    async def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        """Embed a batch of documents for storage.

        Args:
            texts: Sequence of strings to embed.

        Returns:
            Float32 array of shape ``(len(texts), dimensions)``.
        """
        ...

    async def embed_query(self, query: str) -> np.ndarray:
        """Embed a single query string for retrieval.

        For symmetric models (e.g. model2vec) this is identical to
        ``embed_texts([query])[0]``.  Asymmetric bi-encoder models (E5, BGE)
        apply a different query prefix here to improve retrieval quality.

        Args:
            query: The search query to embed.

        Returns:
            Float32 array of shape ``(dimensions,)``.
        """
        ...
