---
phase: 04-enterprise-scale
plan: wave2-A3
type: execute
wave: 2
depends_on: [wave2-A1]
files_modified:
  - src/orchestra/providers/failover.py
  - tests/unit/test_provider_failover.py
autonomous: true
requirements: [T-4.4]
must_haves:
  truths:
    - "ProviderFailover uses the canonical AsyncCircuitBreaker from security/circuit_breaker.py — no duplicate implementation (DD-6)"
    - "Failover completes within 5s of primary provider failure"
    - "TERMINAL errors (auth failures) raise immediately without trying remaining providers"
    - "MODEL_MISMATCH errors (context window) raise immediately — caller handles model selection"
    - "TTFT latency per provider tracked in sliding window, exposed via get_provider_health()"
  artifacts:
    - path: "src/orchestra/providers/failover.py"
      provides: "ProviderFailover using security.AsyncCircuitBreaker, ErrorClassifier with RETRYABLE/TERMINAL/MODEL_MISMATCH"
      min_lines: 100
      contains: "from orchestra.security.circuit_breaker import AsyncCircuitBreaker"
    - path: "tests/unit/test_provider_failover.py"
      provides: "8 tests covering failover, circuit breaker, error classification, TTFT tracking"
      min_lines: 90
  key_links:
    - from: "src/orchestra/providers/failover.py"
      to: "src/orchestra/security/circuit_breaker.py"
      via: "from orchestra.security.circuit_breaker import AsyncCircuitBreaker, CircuitOpenError, CircuitState"
      pattern: "from orchestra\\.security\\.circuit_breaker import"
    - from: "src/orchestra/providers/failover.py"
      to: "src/orchestra/core/errors.py"
      via: "from orchestra.core.errors import AllProvidersUnavailableError"
      pattern: "AllProvidersUnavailableError"
---

<objective>
Rewrite ProviderFailover to use the canonical AsyncCircuitBreaker from security/ and add proper error classification.

Purpose: The current failover.py has a duplicate AsyncCircuitBreaker implementation (DD-6 identifies this as a maintenance burden). The rewrite consolidates to a single implementation, adds RETRYABLE/TERMINAL/MODEL_MISMATCH error classification, and tracks per-provider TTFT latency. This runs parallel to A2 since they touch different files.
Output: Rewritten failover.py with no duplicate circuit breaker, new test_provider_failover.py with 8 tests passing.
</objective>

<execution_context>
@C:/Users/user/.claude/get-shit-done/workflows/execute-plan.md
@C:/Users/user/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/04-enterprise-scale/PLAN.md
@.planning/phases/04-enterprise-scale/WAVE2-DESIGN-DECISIONS.md

<interfaces>
<!-- From src/orchestra/security/circuit_breaker.py (existing, Phase 3) -->
```python
class AsyncCircuitBreaker:
    """185-line async circuit breaker. Already integrated, fully tested (DD-6)."""
    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout: float = 60.0,
        name: str = "",
        now: Callable[[], float] | None = None,  # Injectable for deterministic testing
    ) -> None: ...
    def allow_request(self) -> bool: ...
    def record_success(self) -> None: ...
    def record_failure(self) -> None: ...
    # Also supports async context manager usage

class CircuitOpenError(Exception): ...
class CircuitState(enum.Enum): ...
```

<!-- From src/orchestra/core/errors.py (extended in A1) -->
```python
class AllProvidersUnavailableError(RoutingError): ...
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true" id="A3.1" name="Rewrite ProviderFailover with canonical AsyncCircuitBreaker and error classification">
  <files>src/orchestra/providers/failover.py, tests/unit/test_provider_failover.py</files>
  <behavior>
    - test_first_provider_succeeds: Normal path — first provider called and result returned
    - test_failover_to_second: First fails with retryable error — second provider succeeds
    - test_circuit_breaker_opens: After failure_threshold failures, provider is skipped (allow_request() returns False)
    - test_circuit_breaker_half_open_recovery: After reset_timeout, circuit transitions to HALF_OPEN, provider retried
    - test_terminal_error_raises_immediately: AuthenticationError-like exception raises immediately, second provider not tried
    - test_model_mismatch_raises_immediately: ContextWindowError-like exception raises immediately
    - test_all_providers_fail_raises: AllProvidersUnavailableError raised when all providers exhausted
    - test_latency_tracking: TTFT values recorded per provider, get_provider_health() returns p50/p95
  </behavior>
  <action>
Read src/orchestra/providers/failover.py first to understand the current structure. Also read src/orchestra/security/circuit_breaker.py to confirm the exact API.

REWRITE failover.py with these changes per DD-6:

1. REMOVE the duplicate CircuitState and AsyncCircuitBreaker from failover.py entirely. Import from the canonical location:
```python
from orchestra.security.circuit_breaker import AsyncCircuitBreaker, CircuitOpenError, CircuitState
from orchestra.core.errors import AllProvidersUnavailableError
```

2. Add ErrorClassifier:
```python
import enum

class ErrorCategory(enum.Enum):
    RETRYABLE = "retryable"           # Rate limit, timeout, 5xx -> try next provider
    TERMINAL = "terminal"             # Auth failure -> fail immediately, do not retry
    MODEL_MISMATCH = "model_mismatch" # Context window exceeded -> fail immediately, caller re-routes


def classify_error(exc: Exception) -> ErrorCategory:
    """Classify exception for failover routing decision.
    Check known exception type names first, then fall back to message inspection.
    """
    type_name = type(exc).__name__.lower()
    message = str(exc).lower()

    # Terminal: auth failures should never be retried
    if any(k in type_name for k in ("authentication", "authorization", "permission", "apikey")):
        return ErrorCategory.TERMINAL
    if any(k in message for k in ("api key", "authentication failed", "invalid key", "unauthorized")):
        return ErrorCategory.TERMINAL

    # Model mismatch: context window — caller should select a smaller model
    if any(k in type_name for k in ("contextwindow", "contextlength", "tokenlimit")):
        return ErrorCategory.MODEL_MISMATCH
    if any(k in message for k in ("context window", "context length", "maximum tokens", "token limit")):
        return ErrorCategory.MODEL_MISMATCH

    # Default: retryable (rate limits, timeouts, 5xx)
    return ErrorCategory.RETRYABLE
```

3. ProviderFailover rewrite:
```python
import time
import statistics
from typing import Any

class ProviderFailover:
    """Executes LLM calls with ordered provider failover and per-provider circuit breakers.

    Uses security.AsyncCircuitBreaker (DD-6: canonical implementation, not a duplicate).
    """

    def __init__(
        self,
        providers: list[Any],  # LLMProvider instances
        failure_threshold: int = 3,
        reset_timeout: float = 60.0,
    ) -> None:
        self._providers = list(providers)
        self._breakers = [
            AsyncCircuitBreaker(
                failure_threshold=failure_threshold,
                reset_timeout=reset_timeout,
                name=getattr(p, "provider_name", f"provider_{i}"),
            )
            for i, p in enumerate(providers)
        ]
        self._latency_window: dict[int, list[float]] = {}  # Sliding window, last 20 TTFT values

    def _track_latency(self, idx: int, latency_ms: float) -> None:
        window = self._latency_window.setdefault(idx, [])
        window.append(latency_ms)
        if len(window) > 20:
            window.pop(0)

    def get_provider_health(self, idx: int) -> dict:
        """Returns p50/p95 latency stats for a provider index."""
        window = self._latency_window.get(idx, [])
        if not window:
            return {"p50_ms": None, "p95_ms": None, "sample_count": 0}
        sorted_w = sorted(window)
        p50 = sorted_w[int(len(sorted_w) * 0.5)]
        p95 = sorted_w[int(len(sorted_w) * 0.95)]
        return {"p50_ms": p50, "p95_ms": p95, "sample_count": len(window)}

    async def complete(self, *args: Any, **kwargs: Any) -> Any:
        """Execute with ordered failover. Tries each provider in sequence."""
        errors = []
        for i, (provider, breaker) in enumerate(zip(self._providers, self._breakers)):
            if not breaker.allow_request():
                continue
            try:
                t0 = time.monotonic()
                result = await provider.complete(*args, **kwargs)
                latency_ms = (time.monotonic() - t0) * 1000
                breaker.record_success()
                self._track_latency(i, latency_ms)
                return result
            except Exception as exc:
                breaker.record_failure()
                category = classify_error(exc)
                errors.append((exc, category))
                if category == ErrorCategory.TERMINAL:
                    raise  # Auth failures propagate immediately
                if category == ErrorCategory.MODEL_MISMATCH:
                    raise  # Caller should select a different model
                # RETRYABLE: continue to next provider

        raise AllProvidersUnavailableError(
            f"All {len(self._providers)} providers failed or circuit-broken: "
            f"{[str(e) for e, _ in errors]}"
        )
```

Write tests to tests/unit/test_provider_failover.py. Use unittest.mock.AsyncMock for provider.complete(). For circuit breaker tests, configure failure_threshold=2 and use a mock provider that raises exceptions. For latency tracking, check that get_provider_health() returns non-None p50/p95 after calls.
  </action>
  <verify>
    <automated>pytest tests/unit/test_provider_failover.py -x -v</automated>
  </verify>
  <done>ProviderFailover uses the canonical AsyncCircuitBreaker (no duplicate). Error classification works for TERMINAL and MODEL_MISMATCH. TTFT tracking functional. All 8 tests pass.</done>
</task>

</tasks>

<verification>
pytest tests/unit/test_provider_failover.py -v
python -c "from orchestra.providers.failover import ProviderFailover, ErrorCategory, classify_error; print('failover imports OK')"
# Confirm no duplicate CircuitBreaker in failover.py:
python -c "
import ast, pathlib
src = pathlib.Path('src/orchestra/providers/failover.py').read_text()
assert 'class AsyncCircuitBreaker' not in src, 'FAIL: duplicate CircuitBreaker still in failover.py'
assert 'from orchestra.security.circuit_breaker import' in src, 'FAIL: not using canonical import'
print('DD-6 compliance: OK')
"
</verification>

<success_criteria>
- All 8 test_provider_failover.py tests pass
- failover.py imports AsyncCircuitBreaker from orchestra.security.circuit_breaker (DD-6)
- No class AsyncCircuitBreaker definition in failover.py
- TERMINAL errors raise immediately (no retry)
- MODEL_MISMATCH errors raise immediately (no retry)
- RETRYABLE errors try next provider
- AllProvidersUnavailableError raised when all providers exhausted/circuit-broken
</success_criteria>

<output>
After completion, create .planning/phases/04-enterprise-scale/04-wave2-A3-SUMMARY.md
</output>
