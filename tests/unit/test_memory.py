"""Tests for Orchestra memory management."""

from __future__ import annotations

import pytest

from orchestra.memory.manager import InMemoryMemoryManager


class TestInMemoryMemoryManager:
    """Tests for InMemoryMemoryManager."""

    @pytest.mark.asyncio
    async def test_store_and_retrieve(self):
        # Setup
        memory = InMemoryMemoryManager()

        # Act
        await memory.store("user_pref", {"theme": "dark"})
        result = await memory.retrieve("user_pref")

        # Assert
        assert result == {"theme": "dark"}

    @pytest.mark.asyncio
    async def test_retrieve_non_existent_returns_none(self):
        # Setup
        memory = InMemoryMemoryManager()

        # Act
        result = await memory.retrieve("non_existent")

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_overwrite_existing_key(self):
        # Setup
        memory = InMemoryMemoryManager()

        # Act
        await memory.store("key", "value1")
        await memory.store("key", "value2")
        result = await memory.retrieve("key")

        # Assert
        assert result == "value2"
