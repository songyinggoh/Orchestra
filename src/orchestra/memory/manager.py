"""Memory management for Orchestra."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class MemoryManager(Protocol):
    """Simplified protocol for session and cross-run persistence."""

    async def store(self, key: str, value: Any) -> None:
        """Store a value in memory."""
        ...

    async def retrieve(self, key: str) -> Any | None:
        """Retrieve a value from memory."""
        ...


class InMemoryMemoryManager:
    """Simple in-memory implementation of MemoryManager.

    All data is backed by a dictionary and is not persisted across restarts.
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def store(self, key: str, value: Any) -> None:
        self._data[key] = value

    async def retrieve(self, key: str) -> Any | None:
        return self._data.get(key)
