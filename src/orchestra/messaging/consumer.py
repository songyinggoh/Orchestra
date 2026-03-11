"""NATS JetStream pull consumer with DIDComm E2EE transparent decryption."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from nats.js import JetStreamContext

    from orchestra.messaging.secure_provider import SecureNatsProvider

log = structlog.get_logger(__name__)


class TaskConsumer:
    """Durable pull consumer that decrypts and dispatches NATS task messages.

    Pull consumers are preferred over push consumers for task queues because
    they prevent message flooding and require explicit ack before the broker
    removes the message from the stream.
    """

    def __init__(
        self,
        js: JetStreamContext,
        provider: SecureNatsProvider,
        agent_type: str,
        durable_name: str,
    ) -> None:
        self._js = js
        self._provider = provider
        self._agent_type = agent_type
        self._durable_name = durable_name
        self._psub: Any = None

    async def start(self) -> None:
        """Subscribe to ``orchestra.tasks.{agent_type}`` with a durable consumer.

        Durable consumers survive process restarts — NATS tracks delivery
        position per durable name across reconnects.
        """
        subject = f"orchestra.tasks.{self._agent_type}"
        self._psub = await self._js.pull_subscribe(subject, self._durable_name)
        log.info(
            "consumer_started",
            agent_type=self._agent_type,
            durable=self._durable_name,
            subject=subject,
        )

    async def fetch_and_process(
        self,
        handler: Callable[[dict], Awaitable[Any]],
        *,
        batch_size: int = 1,
        timeout: float = 1.0,
    ) -> int:
        """Fetch a batch, decrypt each message, call *handler*, and ack.

        On decryption failure the message is NAK'd (triggering redelivery up
        to the stream's ``max_deliver`` limit). Handler exceptions are also
        NAK'd so the message is not silently dropped.

        Returns:
            Number of messages successfully processed and ack'd.
        """
        if self._psub is None:
            raise RuntimeError("Call start() before fetch_and_process()")

        try:
            msgs = await self._psub.fetch(batch_size, timeout=timeout)
        except Exception:
            # Timeout or transient error — not a failure
            return 0

        processed = 0
        for msg in msgs:
            try:
                plaintext = self._provider.decrypt(msg.data.decode("utf-8"))
                await handler(plaintext)
                await msg.ack()
                processed += 1
            except Exception as exc:
                log.error(
                    "message_processing_failed",
                    agent_type=self._agent_type,
                    error=str(exc),
                )
                await msg.nak()

        return processed
