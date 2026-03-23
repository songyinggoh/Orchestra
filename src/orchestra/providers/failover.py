"""Provider failover with circuit breaking.

Implements a failover chain of LLM providers using the canonical
AsyncCircuitBreaker from security/circuit_breaker.py (per DD-6).
"""

from __future__ import annotations

import enum
import time
from collections.abc import Sequence
from typing import Any, cast

import structlog

from orchestra.core.errors import AllProvidersUnavailableError
from orchestra.core.types import LLMResponse
from orchestra.security.circuit_breaker import (
    AsyncCircuitBreaker,
)

logger = structlog.get_logger(__name__)


class ErrorCategory(enum.Enum):
    """Categories for provider errors to determine failover behavior."""

    RETRYABLE = "retryable"  # Rate limit, timeout, 5xx -> try next provider
    TERMINAL = "terminal"  # Auth failure -> fail immediately
    MODEL_MISMATCH = "model_mismatch"  # Context window exceeded -> fail/retry smaller model


def classify_error(exc: Exception) -> ErrorCategory:
    """Classify an exception into a retryable or terminal category."""
    from orchestra.core.errors import AuthenticationError, ContextWindowError, RateLimitError

    if isinstance(exc, AuthenticationError):
        return ErrorCategory.TERMINAL
    if isinstance(exc, ContextWindowError):
        return ErrorCategory.MODEL_MISMATCH
    if isinstance(exc, RateLimitError):
        return ErrorCategory.RETRYABLE

    msg = str(exc).lower()
    # Terminal errors
    if any(kw in msg for kw in ["unauthorized", "invalid api key", "401", "403"]):
        return ErrorCategory.TERMINAL

    # Model mismatch errors
    if any(kw in msg for kw in ["context_length_exceeded", "max tokens", "too long"]):
        return ErrorCategory.MODEL_MISMATCH

    # Default to retryable for most network/server issues
    retryable_keywords = [
        "rate_limit",
        "429",
        "timeout",
        "deadline",
        "500",
        "502",
        "503",
        "504",
        "server error",
        "connection",
        "unavailable",
        "overloaded",
    ]
    if any(kw in msg for kw in retryable_keywords):
        return ErrorCategory.RETRYABLE

    return (
        ErrorCategory.TERMINAL
    )  # Unknown errors should surface, not be silently swallowed by failover


class ProviderFailover:
    """Wrapper for multiple LLMProviders that handles failover.

    Iterates through a list of providers until one succeeds or the chain
    is exhausted. Each provider is protected by its own circuit breaker.
    """

    def __init__(
        self,
        providers: Sequence[Any],  # list[LLMProvider]
        failure_threshold: int = 3,
        reset_timeout: float = 60.0,
    ) -> None:
        """Initialize failover chain.

        Args:
            providers: Sequence of LLMProvider instances in priority order.
            failure_threshold: Failures before opening a provider's circuit.
            reset_timeout: Seconds before retrying a failed provider.
        """
        import asyncio

        self._providers = list(providers)
        self._breakers = [
            AsyncCircuitBreaker(
                failure_threshold=failure_threshold,
                reset_timeout=reset_timeout,
                name=getattr(p, "provider_name", f"provider-{i}"),
            )
            for i, p in enumerate(providers)
        ]
        # TTFT tracking per provider (index -> list of latencies)
        self._latency_tracker: dict[int, list[float]] = {i: [] for i in range(len(providers))}
        self._max_history = 20
        # Lock to protect concurrent access to latency tracker
        self._latency_lock = asyncio.Lock()

    async def complete(self, *args: Any, **kwargs: Any) -> LLMResponse:
        """Attempt completion across the failover chain."""
        errors: list[tuple[Exception, ErrorCategory]] = []

        for i, provider in enumerate(self._providers):
            breaker = self._breakers[i]

            if not breaker.allow_request():
                continue

            try:
                start = time.monotonic()
                result = await provider.complete(*args, **kwargs)
                latency_ms = (time.monotonic() - start) * 1000

                breaker.record_success()
                await self._track_latency(i, latency_ms)

                logger.debug(
                    "provider_call_success",
                    provider=getattr(provider, "provider_name", i),
                    latency_ms=round(latency_ms),
                )
                return cast(LLMResponse, result)
            except Exception as exc:
                breaker.record_failure()
                category = classify_error(exc)
                errors.append((exc, category))

                logger.warning(
                    "provider_failover_attempt_failed",
                    provider=getattr(provider, "provider_name", i),
                    category=category.value,
                    error=str(exc),
                )

                if category == ErrorCategory.TERMINAL:
                    raise
                if category == ErrorCategory.MODEL_MISMATCH:
                    raise

                # Continue to next provider for RETRYABLE errors

        raise AllProvidersUnavailableError(
            f"All {len(self._providers)} providers failed: {[str(e) for e, _ in errors]}"
        )

    async def _track_latency(self, index: int, latency_ms: float) -> None:
        """Track latency for a provider (thread-safe)."""
        async with self._latency_lock:
            history = self._latency_tracker[index]
            history.append(latency_ms)
            if len(history) > self._max_history:
                history.pop(0)

    async def get_provider_health(self, index: int) -> dict[str, Any]:
        """Get health and performance metrics for a provider."""
        if index < 0 or index >= len(self._providers):
            return {}

        breaker = self._breakers[index]
        async with self._latency_lock:
            history = list(self._latency_tracker[index])  # Snapshot to avoid races

        health: dict[str, Any] = {
            "name": breaker.name,
            "state": breaker.state.value,
            "failure_count": breaker.failure_count,
            "success_count": breaker.success_count,
            "latency_history_size": len(history),
        }

        if history:
            import numpy as np

            latency_stats: dict[str, Any] = {
                "p50_latency_ms": float(np.percentile(history, 50)),
                "p95_latency_ms": float(np.percentile(history, 95)),
                "avg_latency_ms": float(np.mean(history)),
            }
            health.update(latency_stats)

        return health

    @property
    def providers(self) -> list[Any]:
        return self._providers

    @property
    def breakers(self) -> list[AsyncCircuitBreaker]:
        return self._breakers
