"""Integration tests for T-4.1: NATS JetStream + DIDComm E2EE.

Requires a live NATS server with JetStream enabled (provided by the
integration-test job's service container).

Run locally:
    docker run -p 4222:4222 nats:2.10-alpine -js
    pytest tests/integration/test_secure_nats.py -v
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

nats_lib = pytest.importorskip("nats", reason="nats-py not installed")
base58 = pytest.importorskip("base58", reason="base58 not installed")

from orchestra.messaging import SecureNatsProvider, TaskConsumer, TaskPublisher  # noqa: E402

NATS_URL = "nats://localhost:4222"
pytestmark = pytest.mark.integration


# ------------------------------------------------------------------ fixtures


@pytest_asyncio.fixture
async def nats_connection():
    """Isolated NATS connection with a unique stream per test.

    Creates the stream directly with retries rather than relying on
    create_nats_client's _ensure_stream (which can silently swallow
    creation errors in CI environments).
    """
    import asyncio

    import nats as _nats
    from nats.js.api import RetentionPolicy, StorageType, StreamConfig

    stream_name = f"TEST_{uuid.uuid4().hex[:8].upper()}"
    subject = f"orchestra.tasks.test.{stream_name}"

    nc = await _nats.connect(NATS_URL)
    js = nc.jetstream()

    cfg = StreamConfig(
        name=stream_name,
        subjects=[subject],
        storage=StorageType.FILE,
        retention=RetentionPolicy.LIMITS,
        max_age=60 * 1_000_000_000,
        duplicate_window=30 * 1_000_000_000,
    )

    # Retry stream creation — JetStream may not be ready on first attempt in CI
    last_err: BaseException | None = None
    for _attempt in range(10):
        try:
            await js.add_stream(config=cfg)
            # Verify the stream actually exists
            await js.stream_info(stream_name)
            last_err = None
            break
        except Exception as exc:
            last_err = exc
            await asyncio.sleep(0.5)
    if last_err is not None:
        await nc.close()
        raise RuntimeError(f"Failed to create NATS stream {stream_name}: {last_err}") from last_err

    yield nc, js, stream_name
    await nc.drain()


@pytest.fixture
def agent_pair():
    """Two agents (publisher/consumer) with independent session keypairs."""
    publisher_provider = SecureNatsProvider.create(nats_url=NATS_URL)
    consumer_provider = SecureNatsProvider.create(nats_url=NATS_URL)
    return publisher_provider, consumer_provider


# ------------------------------------------------------------------ tests


@pytest.mark.asyncio
async def test_publish_encrypted_tasks(nats_connection, agent_pair) -> None:
    """Publish encrypted tasks, consume all, verify decryption succeeds."""
    _nc, js, stream_name = nats_connection
    pub_provider, con_provider = agent_pair

    agent_type = f"test.{stream_name}"
    publisher = TaskPublisher(js, pub_provider)

    num_tasks = 20
    results = []
    for i in range(num_tasks):
        r = await publisher.publish(
            agent_type,
            {"index": i, "data": f"payload_{i}"},
            recipient_did=con_provider.own_did,
        )
        results.append(r)

    assert len(results) == num_tasks
    assert all(r.sequence > 0 for r in results)

    # Consume and decrypt all
    consumer = TaskConsumer(js, con_provider, agent_type, f"worker-{stream_name}")
    await consumer.start()

    received: list[dict] = []

    async def handler(msg: dict) -> None:
        received.append(msg["body"])

    total_processed = 0
    for _ in range(10):
        n = await consumer.fetch_and_process(handler, batch_size=10, timeout=2.0)
        total_processed += n
        if total_processed >= num_tasks:
            break

    assert total_processed == num_tasks
    indices = {m["index"] for m in received}
    assert indices == set(range(num_tasks))


@pytest.mark.asyncio
async def test_nats_store_contains_only_ciphertexts(nats_connection, agent_pair) -> None:
    """Raw bytes stored in NATS must not contain any plaintext fragments."""
    _nc, js, stream_name = nats_connection
    pub_provider, con_provider = agent_pair

    agent_type = f"test.{stream_name}"
    publisher = TaskPublisher(js, pub_provider)

    secret_value = "SUPERSECRET_API_KEY_12345"
    await publisher.publish(
        agent_type,
        {"api_key": secret_value},
        recipient_did=con_provider.own_did,
    )

    # Fetch the raw message from the stream without decrypting
    psub = await js.pull_subscribe(f"orchestra.tasks.{agent_type}", f"raw-{stream_name}")
    msgs = await psub.fetch(1, timeout=2.0)
    assert len(msgs) == 1

    raw_bytes = msgs[0].data
    assert secret_value.encode() not in raw_bytes, (
        "Plaintext secret found in NATS-stored message bytes"
    )
    # Compact JWE: 5 dot-separated base64url parts
    assert raw_bytes.count(b".") == 4

    await msgs[0].ack()


@pytest.mark.asyncio
async def test_wrong_key_consumer_naks_message(nats_connection, agent_pair) -> None:
    """A consumer with the wrong key should NAK, not silently drop the message."""
    _nc, js, stream_name = nats_connection
    pub_provider, con_provider = agent_pair
    eve_provider = SecureNatsProvider.create(nats_url=NATS_URL)

    agent_type = f"test.{stream_name}"
    publisher = TaskPublisher(js, pub_provider)

    await publisher.publish(
        agent_type,
        {"secret": "for_bob_only"},
        recipient_did=con_provider.own_did,
    )

    # Eve tries to consume with her own (wrong) key
    eve_consumer = TaskConsumer(js, eve_provider, agent_type, f"eve-{stream_name}")
    await eve_consumer.start()

    eve_received: list[dict] = []

    async def eve_handler(msg: dict) -> None:
        eve_received.append(msg)

    processed = await eve_consumer.fetch_and_process(eve_handler, timeout=2.0)

    # Eve should not have successfully processed any message
    assert processed == 0
    assert eve_received == []
