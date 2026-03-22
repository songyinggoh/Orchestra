"""Orchestra security module — guardrails, rate limiting, circuit breakers.

Core guardrails framework:
  OnFail              — enum of failure actions (BLOCK, FIX, LOG, RETRY, EXCEPTION)
  GuardrailResult     — result from guardrail validation
  Guardrail           — runtime-checkable protocol
  GuardrailChain      — sequential validator runner
  GuardedAgent        — BaseAgent subclass with input/output hooks
  GuardrailError      — exception raised by EXCEPTION on_fail
  GuardrailViolation  — single violation record

Built-in validators:
  ContentFilter       — banned words/patterns
  PIIDetector         — regex-based PII detection
  SchemaValidator     — Pydantic schema validation

Extended validators (orchestra.security.validators):
  MaxLengthGuardrail      — length limit enforcement
  RegexGuardrail          — pattern matching/blocking
  PIIRedactionGuardrail   — PII detection with optional redaction

Rate limiting:
  TokenBucket         — per-identity token-bucket rate limiter

Circuit breaker:
  AsyncCircuitBreaker — CLOSED/OPEN/HALF_OPEN circuit breaker
  CircuitOpenError    — raised when circuit is open
  CircuitState        — circuit state enum

Prompt injection (requires rebuff):
  RebuffChecker, InjectionDetectionResult, InjectionReport,
  PromptInjectionAgent, InjectionAuditorAgent,
  make_injection_guard_node, rebuff_tool
"""

from orchestra.security.attenuation import CapabilityAttenuator
from orchestra.security.circuit_breaker import (
    AsyncCircuitBreaker,
    CircuitOpenError,
    CircuitState,
)
from orchestra.security.guardrails import (
    ContentFilter,
    GuardedAgent,
    Guardrail,
    GuardrailChain,
    GuardrailError,
    GuardrailResult,
    GuardrailViolation,
    OnFail,
    PIIDetector,
    PromptShield,
    SchemaValidator,
)
from orchestra.security.rate_limit import TokenBucket
from orchestra.security.validators import (
    MaxLengthGuardrail,
    PIIRedactionGuardrail,
    RegexGuardrail,
)

# Rebuff is optional — guarded import
try:
    from orchestra.security.rebuff import (
        InjectionAuditorAgent,
        InjectionDetectionResult,
        InjectionReport,
        PromptInjectionAgent,
        RebuffChecker,
        make_injection_guard_node,
        rebuff_tool,
    )
except ImportError:
    pass

__all__ = [
    "AsyncCircuitBreaker",
    "CapabilityAttenuator",
    "CircuitOpenError",
    "CircuitState",
    "ContentFilter",
    "GuardedAgent",
    "Guardrail",
    "GuardrailChain",
    "GuardrailError",
    "GuardrailResult",
    "GuardrailViolation",
    "InjectionAuditorAgent",
    "InjectionDetectionResult",
    "InjectionReport",
    "MaxLengthGuardrail",
    "OnFail",
    "PIIDetector",
    "PIIRedactionGuardrail",
    "PromptInjectionAgent",
    "PromptShield",
    "RebuffChecker",
    "RegexGuardrail",
    "SchemaValidator",
    "TokenBucket",
    "make_injection_guard_node",
    "rebuff_tool",
]
