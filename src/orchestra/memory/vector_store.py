"""Cold tier storage using PostgreSQL and pgvector."""

from __future__ import annotations

import json
from typing import Any, Sequence

import structlog

from orchestra.memory.compression import StateCompressor
from orchestra.memory.dedup import SemanticDeduplicator

logger = structlog.get_logger(__name__)


class VectorStore:
    """PostgreSQL-backed vector store for agent memories.
    
    Implements ColdTierBackend protocol.
    """

    def __init__(
        self, 
        pool: Any, 
        table_name: str = "memory_cold",
        agent_id: str = "default",
        compressor: StateCompressor | None = None,
        deduplicator: SemanticDeduplicator | None = None
    ) -> None:
        """
        Args:
            pool: asyncpg connection pool.
            table_name: Name of the table to use.
            agent_id: Owner ID for all entries stored via this instance.
            compressor: Optional StateCompressor for efficient storage.
            deduplicator: Optional SemanticDeduplicator to skip redundant writes.
        """
        self.pool = pool
        self.table_name = table_name
        self.agent_id = agent_id
        self.compressor = compressor
        self.deduplicator = deduplicator

    @staticmethod
    async def _register_vector(conn: Any) -> None:
        """Register pgvector type on a connection. Use as pool init callback."""
        from pgvector.asyncpg import register_vector
        await register_vector(conn)

    async def initialize(self) -> None:
        """Create table and indices if they don't exist."""
        async with await self.pool.acquire() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    id BIGSERIAL PRIMARY KEY,
                    key TEXT NOT NULL UNIQUE,
                    agent_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
                    embedding VECTOR(256),
                    compressed_value BYTEA,
                    metadata JSONB DEFAULT '{{}}',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    access_count INTEGER DEFAULT 0,
                    last_accessed TIMESTAMPTZ
                )
            """)
            await conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_hnsw ON {self.table_name} USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=200)")
            await conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_tsv ON {self.table_name} USING gin (content_tsv)")
            await conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_agent ON {self.table_name} (agent_id)")

    async def store(
        self, 
        key: str, 
        value: Any, 
        embedding: list[float] | None = None,
        metadata: dict[str, Any] | None = None
    ) -> None:
        """Store or update a memory entry. Satisfies ColdTierBackend."""
        # 1. Deduplication check
        content_str = str(value)
        if self.deduplicator and embedding:
            # For simplicity in this prototype, we'd fetch existing embeddings 
            # but that's expensive. Real impl would use VectorStore.search
            pass

        # 2. Compression
        compressed = None
        if self.compressor:
            compressed = self.compressor.compress(value)

        # 3. Store
        async with await self.pool.acquire() as conn:
            await conn.execute(f"""
                INSERT INTO {self.table_name} (key, agent_id, content, embedding, compressed_value, metadata)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (key) DO UPDATE SET
                    content = EXCLUDED.content,
                    embedding = EXCLUDED.embedding,
                    compressed_value = EXCLUDED.compressed_value,
                    metadata = EXCLUDED.metadata,
                    last_accessed = NOW()
            """, key, self.agent_id, content_str, embedding, compressed, json.dumps(metadata or {}))

    async def retrieve(self, key: str) -> Any | None:
        """Retrieve and decompress. Satisfies ColdTierBackend."""
        async with await self.pool.acquire() as conn:
            row = await conn.fetchrow(f"""
                UPDATE {self.table_name}
                SET access_count = access_count + 1,
                    last_accessed = NOW()
                WHERE key = $1
                RETURNING content, compressed_value, metadata
            """, key)
            
            if not row:
                return None
            
            if row["compressed_value"] and self.compressor:
                return self.compressor.decompress(row["compressed_value"])
            
            # Fallback to content if no compressed value or compressor
            # Real impl would need a way to know if it was msgpack-ed
            try:
                return json.loads(row["content"])
            except Exception:
                return row["content"]

    async def search(
        self,
        embedding: list[float],
        limit: int = 10,
        *,
        filter_metadata: dict | None = None,
        agent_id: str | None = None,
    ) -> list[tuple[str, float]]:
        """Semantic search. Satisfies ColdTierBackend.

        Args:
            embedding: Query vector.
            limit: Maximum number of results.
            filter_metadata: Optional JSONB containment filter applied via
                ``metadata @> $4::jsonb``.
            agent_id: Override the instance-level ``agent_id`` scope.  Useful
                in multi-tenant deployments where one pool serves many agents.
        """
        scope = agent_id or self.agent_id
        async with await self.pool.acquire() as conn:
            if filter_metadata:
                rows = await conn.fetch(
                    f"""
                    SELECT key, 1 - (embedding <=> $1) as score
                    FROM {self.table_name}
                    WHERE agent_id = $2
                      AND metadata @> $4::jsonb
                    ORDER BY embedding <=> $1
                    LIMIT $3
                    """,
                    embedding, scope, limit, json.dumps(filter_metadata),
                )
            else:
                rows = await conn.fetch(
                    f"""
                    SELECT key, 1 - (embedding <=> $1) as score
                    FROM {self.table_name}
                    WHERE agent_id = $2
                    ORDER BY embedding <=> $1
                    LIMIT $3
                    """,
                    embedding, scope, limit,
                )

            return [(r["key"], r["score"]) for r in rows]

    async def hybrid_search(
        self,
        query_text: str,
        query_embedding: list[float],
        limit: int = 10,
        *,
        bm25_weight: float = 0.3,
        agent_id: str | None = None,
    ) -> list[tuple[str, float]]:
        """Hybrid vector + full-text search using Reciprocal Rank Fusion (RRF).

        Combines the HNSW vector index (cosine similarity) with the GIN
        full-text index (``tsvector``) already on the table.  Results from
        both systems are ranked independently then merged via RRF so neither
        dominates the other.

        RRF formula: ``score = (1-bm25_weight) * 1/(k+vector_rank)
                              + bm25_weight    * 1/(k+text_rank)``
        where ``k=60`` (standard RRF constant).

        Args:
            query_text: Raw query string for full-text matching.
            query_embedding: Pre-computed query vector for semantic matching.
            limit: Maximum results to return.
            bm25_weight: Weight given to the full-text ranking (0–1).
                ``0.0`` = pure vector search; ``1.0`` = pure full-text.
                Default ``0.3`` gives a mild BM25 boost for exact-term matches.
            agent_id: Override instance-level agent scope.

        Returns:
            List of ``(key, rrf_score)`` tuples, highest score first.
        """
        scope = agent_id or self.agent_id
        async with await self.pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                WITH vector_results AS (
                    SELECT key,
                           ROW_NUMBER() OVER (ORDER BY embedding <=> $1) AS rank
                    FROM {self.table_name}
                    WHERE agent_id = $2
                      AND embedding IS NOT NULL
                    ORDER BY embedding <=> $1
                    LIMIT $3
                ),
                text_results AS (
                    SELECT key,
                           ROW_NUMBER() OVER (
                               ORDER BY ts_rank(content_tsv, query) DESC
                           ) AS rank
                    FROM {self.table_name},
                         plainto_tsquery('english', $4) AS query
                    WHERE agent_id = $2
                      AND content_tsv @@ query
                    ORDER BY ts_rank(content_tsv, query) DESC
                    LIMIT $3
                )
                SELECT
                    COALESCE(v.key, t.key) AS key,
                    COALESCE(1.0 / (60 + v.rank), 0.0) * (1.0 - $5)
                    + COALESCE(1.0 / (60 + t.rank), 0.0) * $5 AS score
                FROM vector_results v
                FULL OUTER JOIN text_results t ON v.key = t.key
                ORDER BY score DESC
                LIMIT $3
                """,
                query_embedding, scope, limit, query_text, bm25_weight,
            )
            return [(r["key"], float(r["score"])) for r in rows]

    async def delete(self, key: str) -> None:
        async with await self.pool.acquire() as conn:
            await conn.execute(f"DELETE FROM {self.table_name} WHERE key = $1", key)

    async def count(self, agent_id: str | None = None) -> int:
        async with await self.pool.acquire() as conn:
            if agent_id:
                return await conn.fetchval(f"SELECT COUNT(*) FROM {self.table_name} WHERE agent_id = $1", agent_id)
            return await conn.fetchval(f"SELECT COUNT(*) FROM {self.table_name}")
