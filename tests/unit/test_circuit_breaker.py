"""Tests for Orchestra AsyncCircuitBreaker."""

from __future__ import annotations

import pytest

from orchestra.security.circuit_breaker import (
    AsyncCircuitBreaker,
    CircuitOpenError,
    CircuitState,
)


class TestAsyncCircuitBreaker:
    """Tests for the AsyncCircuitBreaker."""

    def test_initial_state_closed(self):
        breaker = AsyncCircuitBreaker()
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_allow_request_when_closed(self):
        breaker = AsyncCircuitBreaker()
        assert await breaker.allow_request() is True

    @pytest.mark.asyncio
    async def test_opens_after_threshold_failures(self):
        """Circuit opens after N consecutive failures."""
        breaker = AsyncCircuitBreaker(failure_threshold=3)
        await breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED
        await breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED
        await breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_open_rejects_requests(self):
        """When OPEN, requests are not allowed."""
        breaker = AsyncCircuitBreaker(failure_threshold=2, reset_timeout=30.0)
        await breaker.record_failure()
        await breaker.record_failure()
        assert breaker.state == CircuitState.OPEN
        assert await breaker.allow_request() is False

    @pytest.mark.asyncio
    async def test_half_open_after_timeout(self):
        """After reset_timeout, allow_request transitions to HALF_OPEN."""
        breaker = AsyncCircuitBreaker(failure_threshold=2, reset_timeout=10.0)

        t0 = 1000.0  # Use high value to avoid monotonic clock interference
        await breaker.record_failure(now=t0)
        await breaker.record_failure(now=t0)
        assert breaker.state == CircuitState.OPEN

        # Before timeout: still OPEN
        t_before = t0 + 5.0
        assert await breaker.allow_request(now=t_before) is False
        assert breaker.state == CircuitState.OPEN

        # After 10 seconds, allow_request transitions to HALF_OPEN
        t1 = t0 + 10.0
        assert await breaker.allow_request(now=t1) is True
        assert breaker.state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_half_open_success_closes_circuit(self):
        """Success in HALF_OPEN returns circuit to CLOSED."""
        breaker = AsyncCircuitBreaker(failure_threshold=2, reset_timeout=5.0)

        t0 = 10000.0
        await breaker.record_failure(now=t0)
        await breaker.record_failure(now=t0)

        # Transition to HALF_OPEN
        t1 = t0 + 5.0
        await breaker.allow_request(now=t1)
        assert breaker.state == CircuitState.HALF_OPEN

        # Success in half-open
        await breaker.record_success()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens_circuit(self):
        """Failure in HALF_OPEN returns circuit to OPEN."""
        breaker = AsyncCircuitBreaker(failure_threshold=2, reset_timeout=5.0)

        t0 = 10000.0
        await breaker.record_failure(now=t0)
        await breaker.record_failure(now=t0)

        # Transition to HALF_OPEN
        t1 = t0 + 5.0
        await breaker.allow_request(now=t1)
        assert breaker.state == CircuitState.HALF_OPEN

        # Failure in half-open
        await breaker.record_failure(now=t1)
        assert breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_success_in_closed_stays_closed(self):
        breaker = AsyncCircuitBreaker()
        await breaker.record_success()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.success_count == 1

    @pytest.mark.asyncio
    async def test_reset(self):
        """Manual reset returns to CLOSED state."""
        breaker = AsyncCircuitBreaker(failure_threshold=1)
        await breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        breaker.reset()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0
        assert breaker.success_count == 0

    def test_properties(self):
        breaker = AsyncCircuitBreaker(
            failure_threshold=5,
            reset_timeout=30.0,
            name="test_breaker",
        )
        assert breaker.failure_threshold == 5
        assert breaker.reset_timeout == 30.0
        assert breaker.name == "test_breaker"

    def test_invalid_failure_threshold(self):
        with pytest.raises(ValueError, match="failure_threshold"):
            AsyncCircuitBreaker(failure_threshold=0)

    def test_invalid_reset_timeout(self):
        with pytest.raises(ValueError, match="reset_timeout"):
            AsyncCircuitBreaker(reset_timeout=0)


class TestAsyncCircuitBreakerContextManager:
    """Tests for the context manager interface."""

    @pytest.mark.asyncio
    async def test_success_records(self):
        breaker = AsyncCircuitBreaker()
        async with breaker:
            pass  # Success
        assert breaker.success_count == 1

    @pytest.mark.asyncio
    async def test_failure_records(self):
        breaker = AsyncCircuitBreaker(failure_threshold=5)
        with pytest.raises(ValueError):
            async with breaker:
                raise ValueError("boom")
        assert breaker.failure_count == 1

    @pytest.mark.asyncio
    async def test_open_raises_circuit_open_error(self):
        breaker = AsyncCircuitBreaker(failure_threshold=1, reset_timeout=60.0)
        await breaker.record_failure()

        with pytest.raises(CircuitOpenError, match="OPEN"):
            async with breaker:
                pass

    @pytest.mark.asyncio
    async def test_circuit_open_error_has_remaining(self):
        breaker = AsyncCircuitBreaker(failure_threshold=1, reset_timeout=60.0)
        await breaker.record_failure()

        try:
            async with breaker:
                pass
        except CircuitOpenError as e:
            assert e.remaining_seconds > 0

    @pytest.mark.asyncio
    async def test_context_manager_does_not_suppress_exceptions(self):
        """Exceptions propagate through the context manager."""
        breaker = AsyncCircuitBreaker()
        with pytest.raises(RuntimeError, match="test error"):
            async with breaker:
                raise RuntimeError("test error")

    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        """Full CLOSED -> OPEN -> HALF_OPEN -> CLOSED cycle."""
        breaker = AsyncCircuitBreaker(failure_threshold=2, reset_timeout=5.0)

        # Two failures -> OPEN
        for _ in range(2):
            with pytest.raises(ValueError):
                async with breaker:
                    raise ValueError("fail")

        assert breaker.state == CircuitState.OPEN

        # Cannot enter while OPEN
        with pytest.raises(CircuitOpenError):
            async with breaker:
                pass

        # Simulate time passing
        import time

        breaker._last_failure_time = time.monotonic() - 6.0

        # Should be HALF_OPEN now, one request allowed
        async with breaker:
            pass  # Success

        assert breaker.state == CircuitState.CLOSED


class TestCircuitState:
    def test_enum_values(self):
        assert CircuitState.CLOSED == "closed"
        assert CircuitState.OPEN == "open"
        assert CircuitState.HALF_OPEN == "half_open"
