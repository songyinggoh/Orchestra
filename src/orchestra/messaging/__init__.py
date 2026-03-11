"""Orchestra messaging module — NATS JetStream with DIDComm v2 E2EE.

Provides end-to-end encrypted task dispatch over NATS JetStream.
Every message published to NATS is a JWE compact token; raw task
payloads never appear in the message store.

Typical usage::

    from orchestra.messaging import SecureNatsProvider, TaskPublisher, TaskConsumer
    from orchestra.messaging.client import NATSClientConfig, create_nats_client

    # Publisher side
    nc, js = await create_nats_client()
    provider = SecureNatsProvider.create(nats_url="nats://localhost:4222")
    publisher = TaskPublisher(js, provider)
    result = await publisher.publish("summarizer", {"text": "..."}, recipient_did=bob_did)

    # Consumer side
    consumer = TaskConsumer(js, provider, agent_type="summarizer", durable_name="worker-1")
    await consumer.start()
    processed = await consumer.fetch_and_process(my_handler)

Optional dependencies (install with ``pip install orchestra-agents[messaging]``):
    nats-py>=2.14, joserfc>=1.6, peerdid>=0.5.2, base58>=2.1, cryptography>=42.0
"""

from orchestra.messaging.consumer import TaskConsumer
from orchestra.messaging.publisher import PublishResult, TaskPublisher
from orchestra.messaging.secure_provider import (
    AgentKeyMaterial,
    SecureNatsProvider,
    extract_x25519_key_from_did,
)

__all__ = [
    "AgentKeyMaterial",
    "PublishResult",
    "SecureNatsProvider",
    "TaskConsumer",
    "TaskPublisher",
    "extract_x25519_key_from_did",
]
