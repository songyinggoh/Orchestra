import asyncio
from unittest.mock import AsyncMock, patch
import numpy as np
import pytest
from orchestra.memory.dedup import SemanticDeduplicator

@pytest.mark.asyncio
async def test_dedup_is_duplicate():
    dedup = SemanticDeduplicator(threshold=0.9)
    
    # Mock embeddings: 2 items, 256 dimensions
    # normalized so dot product = cosine similarity
    existing_embeddings = np.zeros((2, 256))
    existing_embeddings[0, 0] = 1.0  # Item 1
    existing_embeddings[1, 1] = 1.0  # Item 2
    
    existing_keys = ["k1", "k2"]
    
    # Mock embed() to return a vector very similar to Item 1
    new_vector = np.zeros((1, 256))
    new_vector[0, 0] = 0.95
    new_vector[0, 2] = 0.31 # sqrt(1 - 0.95^2) approx
    
    with patch.object(dedup, 'embed', return_value=new_vector):
        is_dup, key = await dedup.is_duplicate("some text", existing_embeddings, existing_keys)
        assert is_dup is True
        assert key == "k1"

@pytest.mark.asyncio
async def test_dedup_not_duplicate():
    dedup = SemanticDeduplicator(threshold=0.98)
    
    existing_embeddings = np.zeros((1, 256))
    existing_embeddings[0, 0] = 1.0
    
    # Mock embed() to return something different
    new_vector = np.zeros((1, 256))
    new_vector[0, 1] = 1.0
    
    with patch.object(dedup, 'embed', return_value=new_vector):
        is_dup, key = await dedup.is_duplicate("different", existing_embeddings, ["k1"])
        assert is_dup is False
        assert key is None

@pytest.mark.asyncio
async def test_dedup_empty_existing():
    dedup = SemanticDeduplicator()
    is_dup, key = await dedup.is_duplicate("any", np.array([]), [])
    assert is_dup is False
