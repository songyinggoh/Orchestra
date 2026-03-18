"""Token-bucket rate limiter for Orchestra agents.

Provides per-agent, per-user, or per-run rate limiting with O(1) per-check
overhead and ~50 bytes per tracked identity.

Usage:
    limiter = TokenBucket(max_tokens=10, window_seconds=60)
    allowed = limiter.allow("agent:researcher")  # True/False
    allowed = limiter.allow("user:alice")
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class _BucketState:
    """Per-identity bucket state. ~50 bytes per instance."""

    tokens: float
    last_refill: float


class TokenBucket:
    """Token-bucket rate limiter.

    Each identity (agent, user, run) gets its own bucket that refills
    at a constant rate. Checking is O(1) per call.

    Args:
        max_tokens: Maximum number of tokens in the bucket (burst capacity).
        window_seconds: Time window in seconds for full bucket refill.
        tokens_per_request: Tokens consumed per request (default: 1).
    """

    def __init__(
        self,
        max_tokens: int,
        window_seconds: float,
        tokens_per_request: int = 1,
    ) -> None:
        if max_tokens < 1:
            raise ValueError("max_tokens must be >= 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")

        self._max_tokens = max_tokens
        self._window_seconds = window_seconds
        self._tokens_per_request = tokens_per_request
        self._refill_rate = max_tokens / window_seconds  # tokens per second

        self._buckets: dict[str, _BucketState] = {}

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    @property
    def window_seconds(self) -> float:
        return self._window_seconds

    def allow(self, identity: str, *, now: float | None = None) -> bool:
        """Check if a request from *identity* is allowed.

        Consumes tokens_per_request tokens from the bucket if allowed.
        O(1) time and space per call.

        Args:
            identity: Identifier for rate limiting scope.
                      Conventions: "agent:<name>", "user:<id>", "run:<id>".
            now: Current timestamp (for testing). Defaults to time.monotonic().

        Returns:
            True if allowed, False if rate limited.
        """
        current_time = now if now is not None else time.monotonic()

        if identity not in self._buckets:
            self._buckets[identity] = _BucketState(
                tokens=float(self._max_tokens),
                last_refill=current_time,
            )

        bucket = self._buckets[identity]

        # Refill tokens based on elapsed time
        elapsed = current_time - bucket.last_refill
        if elapsed > 0:
            refill = elapsed * self._refill_rate
            bucket.tokens = min(self._max_tokens, bucket.tokens + refill)
            bucket.last_refill = current_time

        # Try to consume
        if bucket.tokens >= self._tokens_per_request:
            bucket.tokens -= self._tokens_per_request
            return True

        return False

    def remaining(self, identity: str, *, now: float | None = None) -> float:
        """Return the number of tokens remaining for *identity*.

        Does NOT consume tokens. Returns max_tokens if identity is unknown.
        """
        current_time = now if now is not None else time.monotonic()

        if identity not in self._buckets:
            return float(self._max_tokens)

        bucket = self._buckets[identity]
        elapsed = current_time - bucket.last_refill
        if elapsed > 0:
            refill = elapsed * self._refill_rate
            return min(self._max_tokens, bucket.tokens + refill)

        return bucket.tokens

    def reset(self, identity: str | None = None) -> None:
        """Reset bucket(s) to full capacity.

        Args:
            identity: Specific identity to reset. If None, resets all.
        """
        if identity is None:
            self._buckets.clear()
        elif identity in self._buckets:
            del self._buckets[identity]

    @property
    def tracked_identities(self) -> int:
        """Number of identities currently tracked."""
        return len(self._buckets)
