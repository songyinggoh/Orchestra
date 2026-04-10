"""Qdrant cold-tier backend for TieredMemoryManager.

Requires ``qdrant-client``:

    pip install orchestra-agents[qdrant]

or directly::

    pip install qdrant-client
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

try:
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.models import (
        Distance,
        FieldCondition,
        Filter,
        MatchValue,
        PointIdsList,
        PointStruct,
        VectorParams,
    )

    HAS_QDRANT = True
except ImportError:  # pragma: no cover
    HAS_QDRANT = False


class QdrantColdBackend:
    """Qdrant implementation of :class:`~orchestra.memory.tiers.ColdTierBackend`.

    Stores agent memories as Qdrant points with COSINE distance, matching the
    semantics of the pgvector backend so backends are interchangeable.

    String keys are mapped to deterministic UUIDs via ``uuid.uuid5`` so each key
    always resolves to the same Qdrant point ID.  The original string key is kept
    in the point payload for round-trip retrieval.

    Example::

        from orchestra.memory import TieredMemoryManager
        from orchestra.memory.qdrant_backend import QdrantColdBackend
        from orchestra.memory.dedup import SemanticDeduplicator

        dedup = SemanticDeduplicator()
        cold = QdrantColdBackend(
            url="http://localhost:6333",
            collection_name="my_agent_memory",
            agent_id="researcher",
            dimensions=256,
            embedding_model=dedup.model_name,
        )
        memory = TieredMemoryManager(cold_backend=cold, deduplicator=dedup)
    """

    def __init__(
        self,
        url: str | None = None,
        *,
        api_key: str | None = None,
        collection_name: str = "orchestra_memory",
        agent_id: str = "default",
        dimensions: int = 256,
        embedding_model: str | None = None,
    ) -> None:
        """
        Args:
            url: Qdrant server URL (HTTP or gRPC).
            api_key: Optional API key for Qdrant Cloud.
            collection_name: Qdrant collection to use (created automatically).
            agent_id: Scopes all reads/writes to this agent. Stored in payload
                so multiple agents can share one collection safely.
            dimensions: Vector dimensionality. Must match the embedding model
                used by :class:`~orchestra.memory.tiers.TieredMemoryManager`.
            embedding_model: Name of the embedding model producing vectors.
                Stored in each point's payload for drift detection — if you
                swap models, stored vectors silently lose meaning. Log a warning
                if a retrieved point's ``_embedding_model`` differs from this value.
        """
        if not HAS_QDRANT:
            raise ImportError(
                "qdrant-client is required for QdrantColdBackend. "
                "Install it with: pip install qdrant-client"
            )

        resolved_url = url or os.environ.get("QDRANT_URL", "http://localhost:6333")
        self.url = resolved_url
        self.collection_name = collection_name
        self.agent_id = agent_id
        self.dimensions = dimensions
        self.embedding_model = embedding_model

        self._client_kwargs: dict[str, Any] = {"url": resolved_url}
        if api_key:
            self._client_kwargs["api_key"] = api_key

        self._client: AsyncQdrantClient | None = None
        self._init_lock = asyncio.Lock()
        self._initialized = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _ensure_initialized(self) -> AsyncQdrantClient:
        """Lazy-init client and collection (double-checked locking)."""
        if self._initialized and self._client:
            return self._client

        async with self._init_lock:
            if self._initialized and self._client:
                return self._client

            self._client = AsyncQdrantClient(**self._client_kwargs)

            collections = await self._client.get_collections()
            existing = {c.name for c in collections.collections}

            if self.collection_name not in existing:
                await self._client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=self.dimensions,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info(
                    "qdrant_collection_created",
                    collection=self.collection_name,
                    dimensions=self.dimensions,
                )

            self._initialized = True
            return self._client

    @staticmethod
    def _key_to_point_id(key: str) -> str:
        """Deterministically map a string key to a UUID string point ID."""
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, key))

    def _agent_filter(
        self,
        extra: dict[str, Any] | None = None,
        agent_id: str | None = None,
    ) -> Filter:
        """Build a Filter scoped to an agent, with optional extra conditions.

        Args:
            extra: Additional key/value pairs matched against the ``meta``
                sub-dict (dot-notation), e.g. ``{"session_id": "abc"}``.
            agent_id: Override the instance-level agent scope.  Defaults to
                ``self.agent_id`` when ``None``.
        """
        scope = agent_id or self.agent_id
        conditions: list[FieldCondition] = [
            FieldCondition(key="agent_id", match=MatchValue(value=scope)),
        ]
        if extra:
            for k, v in extra.items():
                conditions.append(FieldCondition(key=f"meta.{k}", match=MatchValue(value=v)))
        return Filter(must=conditions)

    # ------------------------------------------------------------------
    # ColdTierBackend protocol
    # ------------------------------------------------------------------

    async def store(
        self,
        key: str,
        value: Any,
        embedding: list[float] | None = None,
    ) -> None:
        """Upsert a memory point. Uses a zero vector when no embedding is given."""
        client = await self._ensure_initialized()

        payload: dict[str, Any] = {
            "key": key,
            "agent_id": self.agent_id,
            "content": str(value),
            "meta": {},
        }
        if self.embedding_model:
            payload["_embedding_model"] = self.embedding_model

        point = PointStruct(
            id=self._key_to_point_id(key),
            vector=embedding or [0.0] * self.dimensions,
            payload=payload,
        )
        await client.upsert(
            collection_name=self.collection_name,
            points=[point],
        )

    async def retrieve(self, key: str) -> Any | None:
        """Fetch a memory by key. Returns the stored content string, or None."""
        client = await self._ensure_initialized()

        results = await client.retrieve(
            collection_name=self.collection_name,
            ids=[self._key_to_point_id(key)],
            with_payload=True,
        )
        if not results:
            return None

        payload: dict[str, Any] = dict(results[0].payload or {})

        # Drift detection: warn if the stored model differs from the active one.
        stored_model = payload.get("_embedding_model")
        if stored_model and self.embedding_model and stored_model != self.embedding_model:
            logger.warning(
                "embedding_model_mismatch",
                stored=stored_model,
                active=self.embedding_model,
                key=key,
                hint="Stored vectors may be incompatible. Re-ingest to fix.",
            )

        return payload.get("content")

    async def search(
        self,
        embedding: list[float],
        limit: int = 10,
        *,
        filter_metadata: dict[str, Any] | None = None,
        agent_id: str | None = None,
    ) -> list[tuple[str, float]]:
        """Semantic search scoped to an agent.

        Args:
            embedding: Query vector.
            limit: Max results.
            filter_metadata: Optional key/value pairs matched against the
                ``meta`` sub-dict in each point's payload.
            agent_id: Override the instance-level ``agent_id`` scope for
                cross-agent searches in multi-tenant deployments.

        Returns:
            List of ``(key, score)`` tuples, highest score first.
        """
        client = await self._ensure_initialized()

        response = await client.query_points(
            collection_name=self.collection_name,
            query=embedding,
            query_filter=self._agent_filter(filter_metadata, agent_id=agent_id),
            limit=limit,
            with_payload=True,
        )
        results_list: list[tuple[str, float]] = []
        for p in response.points:
            if p.payload is not None:
                results_list.append((str(p.payload["key"]), p.score))
        return results_list

    async def delete(self, key: str) -> None:
        """Delete a point by key."""
        client = await self._ensure_initialized()
        await client.delete(
            collection_name=self.collection_name,
            points_selector=PointIdsList(points=[self._key_to_point_id(key)]),
        )

    async def count(self) -> int:
        """Count all points belonging to this agent."""
        client = await self._ensure_initialized()
        result = await client.count(
            collection_name=self.collection_name,
            count_filter=self._agent_filter(),
            exact=True,
        )
        return result.count
