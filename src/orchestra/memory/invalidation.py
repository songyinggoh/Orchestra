"""Pub/Sub based cache invalidation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

CHANNEL = "orchestra:mem:inv"


async def publish_invalidation(redis_client: Any, key: str) -> None:
    """Publish an invalidation message for a key."""
    try:
        await redis_client.publish(CHANNEL, key)
    except Exception as e:
        logger.warning("publish_invalidation_failed", key=key, error=str(e))


class InvalidationSubscriber:
    """Subscribes to invalidation messages and triggers a callback."""

    def __init__(self, redis_client: Any, on_invalidate: Callable[[str], Any]) -> None:
        self._redis = redis_client
        self._on_invalidate = on_invalidate
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        """Start the subscriber task."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._listen_loop())
        logger.debug("invalidation_subscriber_started")

    async def stop(self) -> None:
        """Stop the subscriber task gracefully."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Clear flag AFTER task is fully stopped to avoid race
        self._running = False
        logger.debug("invalidation_subscriber_stopped")

    async def _listen_loop(self) -> None:
        """Main loop for listening to Pub/Sub messages."""
        while self._running:
            try:
                pubsub = self._redis.pubsub()
                async with pubsub as ps:
                    await ps.subscribe(CHANNEL)

                    # On initial connect/reconnect, we should probably flush everything
                    # because we might have missed messages.
                    if asyncio.iscoroutinefunction(self._on_invalidate):
                        await self._on_invalidate("*")
                    else:
                        self._on_invalidate("*")

                    async for message in ps.listen():
                        if message["type"] == "message":
                            key = message["data"].decode("utf-8")
                            logger.debug("invalidation_received", key=key)

                            if asyncio.iscoroutinefunction(self._on_invalidate):
                                await self._on_invalidate(key)
                            else:
                                self._on_invalidate(key)

                        if not self._running:
                            break
            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._running:
                    logger.error("invalidation_loop_error", error=str(e))
                    await asyncio.sleep(1)  # Backoff
