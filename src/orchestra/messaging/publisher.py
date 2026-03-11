"""NATS JetStream task publisher with DIDComm E2EE."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from nats.js import JetStreamContext

    from orchestra.messaging.secure_provider import SecureNatsProvider

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class PublishResult:
    subject: str
    sequence: int


class TaskPublisher:
    """Encrypts task bodies and publishes them to NATS JetStream.

    The subject pattern is ``orchestra.tasks.{agent_type}``, which the
    ORCHESTRA_TASKS stream captures via the ``orchestra.tasks.>`` wildcard.
    """

    def __init__(self, js: JetStreamContext, provider: SecureNatsProvider) -> None:
        self._js = js
        self._provider = provider

    async def publish(
        self,
        agent_type: str,
        body: dict,
        recipient_did: str,
        *,
        dedup_id: str | None = None,
    ) -> PublishResult:
        """Encrypt *body* for *recipient_did* and publish to NATS.

        Injects the active OpenTelemetry W3C trace context (``traceparent`` /
        ``tracestate``) into NATS headers so distributed traces span the
        publish/consume boundary. If opentelemetry-api is not installed the
        injection is skipped silently.

        Args:
            agent_type: Routing key — determines the NATS subject suffix.
            body: Plaintext task payload dict.
            recipient_did: DID of the consuming agent (used to look up their
                           X25519 public key for JWE encryption).
            dedup_id: Optional ``Nats-Msg-Id`` header value for idempotent
                      publishing within the stream's ``duplicate_window``.

        Returns:
            PublishResult with the NATS subject and sequence number.
        """
        subject = f"orchestra.tasks.{agent_type}"
        token = self._provider.encrypt_for(body, recipient_did)

        headers: dict[str, str] = {}
        if dedup_id:
            headers["Nats-Msg-Id"] = dedup_id
        _inject_trace_context(headers)

        ack = await self._js.publish(
            subject, token.encode("utf-8"), headers=headers or None
        )
        log.debug("task_published", subject=subject, seq=ack.seq)
        return PublishResult(subject=subject, sequence=ack.seq)


def _inject_trace_context(headers: dict[str, str]) -> None:
    """Inject OTel W3C trace context headers if opentelemetry-api is available."""
    try:
        from opentelemetry.propagate import inject

        inject(headers)
    except ImportError:
        pass
