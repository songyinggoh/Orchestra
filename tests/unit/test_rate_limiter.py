"""Tests for Orchestra TokenBucket rate limiter."""

from __future__ import annotations

import pytest

from orchestra.security.rate_limit import TokenBucket


class TestTokenBucket:
    """Tests for the TokenBucket rate limiter."""

    def test_basic_allow(self):
        """Requests within capacity are allowed."""
        limiter = TokenBucket(max_tokens=5, window_seconds=60)
        assert limiter.allow("agent:test") is True

    def test_exhaust_capacity(self):
        """After exhausting tokens, requests are denied."""
        limiter = TokenBucket(max_tokens=3, window_seconds=60)
        assert limiter.allow("agent:test") is True
        assert limiter.allow("agent:test") is True
        assert limiter.allow("agent:test") is True
        assert limiter.allow("agent:test") is False

    def test_per_identity_isolation(self):
        """Different identities have separate buckets."""
        limiter = TokenBucket(max_tokens=1, window_seconds=60)
        assert limiter.allow("agent:alice") is True
        assert limiter.allow("agent:bob") is True
        # alice is now exhausted but bob just started
        assert limiter.allow("agent:alice") is False
        assert limiter.allow("agent:bob") is False

    def test_token_refill(self):
        """Tokens refill over time."""
        limiter = TokenBucket(max_tokens=2, window_seconds=10)

        t0 = 100.0
        assert limiter.allow("agent:x", now=t0) is True
        assert limiter.allow("agent:x", now=t0) is True
        assert limiter.allow("agent:x", now=t0) is False

        # After 5 seconds, half the tokens should have refilled (1 token)
        t1 = t0 + 5.0
        assert limiter.allow("agent:x", now=t1) is True
        assert limiter.allow("agent:x", now=t1) is False

    def test_full_refill(self):
        """After a full window, bucket is at max capacity again."""
        limiter = TokenBucket(max_tokens=3, window_seconds=10)

        t0 = 100.0
        # Exhaust all tokens
        for _ in range(3):
            limiter.allow("agent:x", now=t0)

        # After full window, all tokens should be back
        t1 = t0 + 10.0
        assert limiter.allow("agent:x", now=t1) is True
        assert limiter.allow("agent:x", now=t1) is True
        assert limiter.allow("agent:x", now=t1) is True
        assert limiter.allow("agent:x", now=t1) is False

    def test_remaining_tokens(self):
        """remaining() reports correct token count without consuming."""
        limiter = TokenBucket(max_tokens=5, window_seconds=60)
        t0 = 100.0

        # New identity should have full capacity
        assert limiter.remaining("agent:new", now=t0) == 5.0

        # Consume 2 tokens
        limiter.allow("agent:new", now=t0)
        limiter.allow("agent:new", now=t0)
        assert limiter.remaining("agent:new", now=t0) == pytest.approx(3.0)

    def test_reset_specific_identity(self):
        """reset() clears a specific identity's bucket."""
        limiter = TokenBucket(max_tokens=1, window_seconds=60)
        limiter.allow("agent:x")
        assert limiter.allow("agent:x") is False

        limiter.reset("agent:x")
        assert limiter.allow("agent:x") is True

    def test_reset_all(self):
        """reset() with no args clears all buckets."""
        limiter = TokenBucket(max_tokens=1, window_seconds=60)
        limiter.allow("agent:a")
        limiter.allow("agent:b")

        limiter.reset()
        assert limiter.tracked_identities == 0
        assert limiter.allow("agent:a") is True
        assert limiter.allow("agent:b") is True

    def test_tracked_identities(self):
        """tracked_identities counts unique identities."""
        limiter = TokenBucket(max_tokens=10, window_seconds=60)
        limiter.allow("agent:a")
        limiter.allow("agent:b")
        limiter.allow("user:c")
        assert limiter.tracked_identities == 3

    def test_properties(self):
        """Public properties are accessible."""
        limiter = TokenBucket(max_tokens=10, window_seconds=30)
        assert limiter.max_tokens == 10
        assert limiter.window_seconds == 30

    def test_invalid_max_tokens(self):
        """max_tokens < 1 raises ValueError."""
        with pytest.raises(ValueError, match="max_tokens"):
            TokenBucket(max_tokens=0, window_seconds=10)

    def test_invalid_window_seconds(self):
        """window_seconds <= 0 raises ValueError."""
        with pytest.raises(ValueError, match="window_seconds"):
            TokenBucket(max_tokens=5, window_seconds=0)

    def test_tokens_per_request(self):
        """Custom tokens_per_request consumes multiple tokens per allow()."""
        limiter = TokenBucket(max_tokens=10, window_seconds=60, tokens_per_request=3)
        assert limiter.allow("agent:x") is True  # 10 - 3 = 7
        assert limiter.allow("agent:x") is True  # 7 - 3 = 4
        assert limiter.allow("agent:x") is True  # 4 - 3 = 1
        assert limiter.allow("agent:x") is False  # 1 < 3

    def test_scoping_conventions(self):
        """Different scoping patterns work correctly."""
        limiter = TokenBucket(max_tokens=1, window_seconds=60)

        # Per-agent
        assert limiter.allow("agent:researcher") is True
        assert limiter.allow("agent:researcher") is False

        # Per-user
        assert limiter.allow("user:alice") is True
        assert limiter.allow("user:alice") is False

        # Per-run
        assert limiter.allow("run:abc123") is True
        assert limiter.allow("run:abc123") is False

    def test_partial_refill(self):
        """Partial time windows refill proportionally."""
        limiter = TokenBucket(max_tokens=100, window_seconds=100)

        t0 = 1000.0
        # Consume all 100 tokens
        for _ in range(100):
            limiter.allow("agent:x", now=t0)

        # After 10 seconds, should have refilled ~10 tokens
        t1 = t0 + 10.0
        remaining = limiter.remaining("agent:x", now=t1)
        assert remaining == pytest.approx(10.0, abs=0.1)

    def test_burst_then_steady(self):
        """Bucket allows burst, then steady state at refill rate."""
        limiter = TokenBucket(max_tokens=5, window_seconds=5)

        t0 = 0.0
        # Burst: consume all 5
        for _ in range(5):
            assert limiter.allow("x", now=t0) is True
        assert limiter.allow("x", now=t0) is False

        # After 1 second, 1 token refilled
        assert limiter.allow("x", now=t0 + 1.0) is True
        assert limiter.allow("x", now=t0 + 1.0) is False
