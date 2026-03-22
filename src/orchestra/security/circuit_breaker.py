"""Async circuit breaker for Orchestra agents and providers.

Implements the circuit breaker pattern with three states:
  CLOSED    - Normal operation. Failures are counted.
  OPEN      - Requests are rejected immediately. After reset_timeout,
              transitions to HALF_OPEN.
  HALF_OPEN - A single request is allowed through. On success, returns
              to CLOSED. On failure, returns to OPEN.

Usage:
    breaker = AsyncCircuitBreaker(failure_threshold=3, reset_timeout=30.0)

    async with breaker:
        result = await some_unreliable_call()

    # Or explicit API:
    if breaker.allow_request():
        try:
            result = await some_call()
            breaker.record_success()
        except Exception:
            breaker.record_failure()
"""

from __future__ import annotations

import time
from enum import Enum
from types import TracebackType


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is open and requests are rejected."""

    def __init__(
        self, message: str = "Circuit breaker is OPEN", remaining_seconds: float = 0.0
    ) -> None:
        super().__init__(message)
        self.remaining_seconds = remaining_seconds


class AsyncCircuitBreaker:
    """Async-compatible circuit breaker.

    Args:
        failure_threshold: Number of consecutive failures before opening.
        reset_timeout: Seconds to wait in OPEN state before transitioning
                       to HALF_OPEN.
        name: Optional name for logging/identification.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout: float = 60.0,
        name: str = "circuit_breaker",
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if reset_timeout <= 0:
            raise ValueError("reset_timeout must be > 0")

        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._name = name

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None

    @property
    def state(self) -> CircuitState:
        """Current state.

        Note: the OPEN -> HALF_OPEN transition happens lazily when
        allow_request() is called, not when state is read. This ensures
        deterministic behavior with injectable timestamps.
        """
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def success_count(self) -> int:
        return self._success_count

    @property
    def name(self) -> str:
        return self._name

    @property
    def failure_threshold(self) -> int:
        return self._failure_threshold

    @property
    def reset_timeout(self) -> float:
        return self._reset_timeout

    def allow_request(self, *, now: float | None = None) -> bool:
        """Check if a request is allowed through the circuit breaker.

        Returns True if allowed, False if the circuit is OPEN.
        In HALF_OPEN state, allows exactly one request.
        """
        current_time = now if now is not None else time.monotonic()

        if self._state == CircuitState.CLOSED:
            return True

        if self._state == CircuitState.OPEN:
            if self._last_failure_time is not None:
                elapsed = current_time - self._last_failure_time
                if elapsed >= self._reset_timeout:
                    self._state = CircuitState.HALF_OPEN
                    return True
            return False

        # HALF_OPEN: allow the test request
        return True

    def record_success(self) -> None:
        """Record a successful call. Resets circuit to CLOSED if in HALF_OPEN."""
        self._success_count += 1
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED
            self._failure_count = 0

    def record_failure(self, *, now: float | None = None) -> None:
        """Record a failed call. May open the circuit."""
        current_time = now if now is not None else time.monotonic()
        self._failure_count += 1
        self._last_failure_time = current_time

        if self._state == CircuitState.HALF_OPEN:
            # Failed in half-open => back to open
            self._state = CircuitState.OPEN
        elif self._state == CircuitState.CLOSED:
            if self._failure_count >= self._failure_threshold:
                self._state = CircuitState.OPEN

    def reset(self) -> None:
        """Manually reset the circuit breaker to CLOSED state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None

    async def __aenter__(self) -> AsyncCircuitBreaker:
        """Context manager entry: check if request is allowed."""
        if not self.allow_request():
            remaining = 0.0
            if self._last_failure_time is not None:
                elapsed = time.monotonic() - self._last_failure_time
                remaining = max(0.0, self._reset_timeout - elapsed)
            raise CircuitOpenError(
                f"Circuit breaker '{self._name}' is OPEN. Retry in {remaining:.1f}s.",
                remaining_seconds=remaining,
            )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        """Context manager exit: record success or failure."""
        if exc_type is None:
            self.record_success()
        else:
            self.record_failure()
        # Do NOT suppress exceptions
        return False
