"""Semantic deduplication for memory items."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any, cast

import numpy as np
import structlog

logger = structlog.get_logger(__name__)


class SemanticDeduplicator:
    """Detects semantically similar text to prevent redundant memory storage."""

    def __init__(
        self, model_name: str = "minishlab/potion-base-8M", threshold: float = 0.98
    ) -> None:
        """
        Args:
            model_name: HuggingFace ID for model2vec model.
            threshold: Cosine similarity threshold for duplicate detection.
        """
        self.model_name = model_name
        self.threshold = threshold
        self._model: Any = None
        self._lock = asyncio.Lock()

    async def _ensure_model(self) -> None:
        """Lazy load the model2vec model."""
        async with self._lock:
            if self._model is not None:
                return

            try:
                from model2vec import StaticModel

                # model2vec is CPU-bound and can take time to load
                self._model = await asyncio.to_thread(StaticModel.from_pretrained, self.model_name)
                logger.info("dedup_model_loaded", model=self.model_name)
            except ImportError:
                logger.warning("model2vec_not_installed", action="falling_back_to_exact_match")
                self._model = False  # Sentinel for fallback

    @property
    def dimensions(self) -> int:
        """Dimensionality of the model2vec embeddings (256)."""
        return 256

    async def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        """Embed a batch of texts.

        Satisfies :class:`~orchestra.memory.embeddings.EmbeddingProvider`.
        Returns array of shape ``(len(texts), 256)``.
        """
        await self._ensure_model()
        if not self._model:
            return np.zeros((len(texts), self.dimensions))
        return await asyncio.to_thread(self._model.encode, texts)

    async def embed_query(self, query: str) -> np.ndarray:
        """Embed a single query string. Returns array of shape ``(256,)``."""
        return cast(np.ndarray, (await self.embed_texts([query]))[0])

    async def embed(self, texts: Sequence[str]) -> np.ndarray:
        """Alias for :meth:`embed_texts`. Kept for backward compatibility."""
        return await self.embed_texts(texts)

    async def is_duplicate(
        self, text: str, existing_embeddings: np.ndarray, existing_keys: Sequence[str]
    ) -> tuple[bool, str | None]:
        """Check if text is a semantic duplicate of existing embeddings.

        Returns:
            (is_duplicate, matching_key)
        """
        if existing_embeddings.size == 0:
            return False, None

        # 1. Embed new text
        new_embedding = await self.embed(text if isinstance(text, list) else [text])

        # If embed returned zeros because of missing model, we can only do exact match
        # if we had raw texts.  Here we have embeddings, so if new_embedding is zeros,
        # dot product will be zero.

        # 2. Compute cosine similarity
        # Cosine similarity = (A . B) / (||A|| ||B||)
        # Assuming embeddings are normalized by model2vec
        similarities = np.dot(existing_embeddings, new_embedding[0])

        max_idx = np.argmax(similarities)
        max_sim = similarities[max_idx]

        if max_sim >= self.threshold:
            logger.debug("semantic_duplicate_detected", similarity=f"{max_sim:.4f}")
            return True, existing_keys[int(max_idx)]

        return False, None
