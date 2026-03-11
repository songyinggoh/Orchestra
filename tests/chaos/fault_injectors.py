"""Fault injection utilities for chaos engineering tests.

FaultInjector wraps any LLM provider with configurable failure rates
to test graceful degradation under adverse conditions.
"""
from __future__ import annotations

import asyncio
import random

from orchestra.core.types import LLMResponse, TokenUsage


class FaultInjector:
    """Wraps an LLM provider with configurable failure injection.

    Args:
        provider: The underlying LLM provider to wrap.
        timeout_rate: Probability (0.0-1.0) of simulating a timeout.
        error_rate: Probability of raising a RuntimeError.
        malformed_rate: Probability of returning a malformed response.
        latency_ms: Additional latency in milliseconds (added to all calls).
        timeout_seconds: Seconds to sleep when simulating timeout (default 30).
    """

    def __init__(
        self,
        provider=None,
        *,
        timeout_rate: float = 0.0,
        error_rate: float = 0.0,
        malformed_rate: float = 0.0,
        latency_ms: float = 0.0,
        timeout_seconds: float = 30.0,
    ):
        self._provider = provider
        self.timeout_rate = timeout_rate
        self.error_rate = error_rate
        self.malformed_rate = malformed_rate
        self.latency_ms = latency_ms
        self.timeout_seconds = timeout_seconds
        self.call_count = 0
        self.fault_count = 0

    async def complete(self, *args, **kwargs) -> LLMResponse:
        self.call_count += 1

        # Simulate latency
        if self.latency_ms > 0:
            await asyncio.sleep(self.latency_ms / 1000)

        roll = random.random()

        # Timeout fault
        if roll < self.timeout_rate:
            self.fault_count += 1
            raise asyncio.TimeoutError("Injected timeout fault")

        roll = random.random()

        # Error fault (rate limit style)
        if roll < self.error_rate:
            self.fault_count += 1
            raise RuntimeError("429: Rate limit exceeded (injected fault)")

        roll = random.random()

        # Malformed response
        if roll < self.malformed_rate:
            self.fault_count += 1
            # Return response with no content (malformed)
            return LLMResponse(content="", usage=TokenUsage())

        # Normal call
        if self._provider is not None:
            return await self._provider.complete(*args, **kwargs)

        return LLMResponse(content="ok", usage=TokenUsage(estimated_cost_usd=0.001))
