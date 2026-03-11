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
_STREAM_SUBJECTS = ["orchestra.tasks.>"]


@dataclass
class NATSClientConfig:
    servers: list[str] = field(default_factory=lambda: ["nats://localhost:4222"])
    max_reconnect_attempts: int = 5
    reconnect_time_wait: float = 2.0
    stream_name: str = _STREAM_NAME
    stream_subjects: list[str] = field(default_factory=lambda: list(_STREAM_SUBJECTS))
    # Task messages expire after 1 hour
    max_age_seconds: int = 3600
    # Deduplication window — 2 minutes
    duplicate_window_seconds: int = 120


async def create_nats_client(
    config: NATSClientConfig | None = None,
) -> tuple[NATSClient, JetStreamContext]:
    """Connect to NATS and ensure the ORCHESTRA_TASKS stream exists.

    Creates the stream on first call; updates config on subsequent calls if
    the stream already exists. Uses WorkQueue retention so each message is
    consumed exactly once and discarded after ack.
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
        reconnected_cb=_reconnected_cb,
        max_reconnect_attempts=config.max_reconnect_attempts,
        reconnect_time_wait=config.reconnect_time_wait,
    )
    js = nc.jetstream()

    stream_cfg = StreamConfig(
        name=config.stream_name,
        subjects=config.stream_subjects,
        storage=StorageType.FILE,
        retention=RetentionPolicy.WORK_QUEUE,
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


async def _reconnected_cb() -> None:
    log.info("nats_reconnected")
