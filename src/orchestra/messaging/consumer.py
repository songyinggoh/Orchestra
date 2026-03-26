"""NATS JetStream pull consumer with DIDComm E2EE transparent decryption."""

from __future__ import annotations

import asyncio
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
        handler: Callable[[dict[str, Any]], Awaitable[Any]],
        *,
        batch_size: int = 1,
        timeout: float = 1.0,
        heartbeat_interval: float = 0.0,
    ) -> int:
        """Fetch a batch, decrypt each message, call *handler*, and ack.

        Args:
            handler: Async callable that processes the decrypted message dict.
            batch_size: Number of messages to fetch per call.
            timeout: Pull timeout in seconds.
            heartbeat_interval: If > 0, call ``msg.in_progress()`` every this
                many seconds while the handler is running. Use for tasks that
                may exceed the stream's ``ack_wait`` (default 30 s). A value of
                10.0 is a safe default for long-running agent work.

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
                if heartbeat_interval > 0:
                    await self._run_with_heartbeat(handler, plaintext, msg, heartbeat_interval)
                else:
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

    @staticmethod
    async def terminate(msg: Any) -> None:
        """Terminate a poison message — do not redeliver.

        Use when a message is permanently unprocessable (e.g. malformed data,
        unsupported schema version). Unlike NAK which schedules redelivery,
        ``term()`` removes the message from the consumer's delivery queue
        permanently without counting against ``max_deliver``.
        """
        await msg.term()

    @staticmethod
    async def _run_with_heartbeat(
        handler: Callable[[dict[str, Any]], Awaitable[Any]],
        plaintext: dict[str, Any],
        msg: Any,
        heartbeat_interval: float,
    ) -> None:
        """Run *handler* while sending periodic ``in_progress()`` heartbeats."""

        async def _heartbeat() -> None:
            while True:
                await asyncio.sleep(heartbeat_interval)
                await msg.in_progress()

        hb_task = asyncio.create_task(_heartbeat())
        try:
            await handler(plaintext)
        finally:
            hb_task.cancel()
