"""NATS JetStream connection management and stream lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from nats.aio.client import Client as NATSClient
    from nats.js import JetStreamContext

log = structlog.get_logger(__name__)

_STREAM_NAME = "ORCHESTRA_TASKS"
_STREAM_SUBJECTS = [
    "orchestra.tasks.>",
    "orchestra.events.>",
    "orchestra.handoffs.>",
]


@dataclass
class NATSClientConfig:
    servers: list[str] = field(default_factory=lambda: ["nats://localhost:4222"])
    max_reconnect_attempts: int = 5
    reconnect_time_wait: float = 2.0
    # Heartbeat: disconnect after max_outstanding_pings missed pings
    ping_interval: int = 20
    max_outstanding_pings: int = 3
    stream_name: str = _STREAM_NAME
    stream_subjects: list[str] = field(default_factory=lambda: list(_STREAM_SUBJECTS))
    # LIMITS retention: keep messages until capacity/age thresholds are exceeded
    max_age_seconds: int = 7 * 24 * 3600  # 7 days
    duplicate_window_seconds: int = 120   # 2-minute dedup window
    max_msgs: int = 1_000_000
    max_bytes: int = 1 * 1024**3          # 1 GB
    max_msg_size: int = 1 * 1024**2       # 1 MB per message
    num_replicas: int = 1


async def create_nats_client(
    config: NATSClientConfig | None = None,
) -> tuple[NATSClient, JetStreamContext]:
    """Connect to NATS and ensure the ORCHESTRA_TASKS stream exists.

    Creates the stream on first call; updates config on subsequent calls if
    the stream already exists. Uses LIMITS retention so messages are replayable
    until capacity/age thresholds are exceeded — enables crash recovery and
    consumer-group fan-out across KEDA-scaled replicas.
    """
    try:
        import nats as nats_lib
        from nats.js.api import RetentionPolicy, StorageType, StreamConfig
    except ImportError as exc:
        raise ImportError(
            "nats-py is required. Install with: pip install orchestra-agents[messaging]"
        ) from exc

    if config is None:
        config = NATSClientConfig()

    nc = await nats_lib.connect(
        config.servers,
        error_cb=_error_cb,
        disconnected_cb=_disconnected_cb,
        reconnected_cb=_reconnected_cb,
        max_reconnect_attempts=config.max_reconnect_attempts,
        reconnect_time_wait=config.reconnect_time_wait,
        ping_interval=config.ping_interval,
        max_outstanding_pings=config.max_outstanding_pings,
    )
    js = nc.jetstream()

    stream_cfg = StreamConfig(
        name=config.stream_name,
        subjects=config.stream_subjects,
        storage=StorageType.FILE,
        retention=RetentionPolicy.LIMITS,
        max_msgs=config.max_msgs,
        max_bytes=config.max_bytes,
        max_msg_size=config.max_msg_size,
        num_replicas=config.num_replicas,
        # nats-py uses nanoseconds for time-based fields
        max_age=config.max_age_seconds * 1_000_000_000,
        duplicate_window=config.duplicate_window_seconds * 1_000_000_000,
    )
    await _ensure_stream(js, stream_cfg, config.stream_name)

    log.info("nats_connected", servers=config.servers, stream=config.stream_name)
    return nc, js


async def _ensure_stream(js: JetStreamContext, cfg: object, stream_name: str) -> None:
    """Create the stream, or update it if it already exists."""
    try:
        await js.add_stream(config=cfg)
        log.info("nats_stream_created", stream=stream_name)
    except Exception as exc:
        msg = str(exc).lower()
        if "already in use" in msg or "bad request" in msg or "400" in msg:
            try:
                await js.update_stream(config=cfg)
                log.debug("nats_stream_updated", stream=stream_name)
            except Exception:
                # Stream config unchanged — safe to ignore
                log.debug("nats_stream_unchanged", stream=stream_name)
        else:
            raise


async def _error_cb(exc: Exception) -> None:
    log.error("nats_error", error=str(exc))


async def _disconnected_cb() -> None:
    log.warning("nats_disconnected")


async def _reconnected_cb() -> None:
    log.info("nats_reconnected")
