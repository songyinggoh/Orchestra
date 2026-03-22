"""Additional guardrail validators for the Orchestra framework.

Provides reusable validators that conform to the Guardrail protocol:
    MaxLengthGuardrail     - blocks or truncates text exceeding a length limit
    RegexGuardrail         - validates text matches (or doesn't match) a pattern
    PIIRedactionGuardrail  - detects PII and optionally redacts it (Presidio wrapper)
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from orchestra.security.guardrails import (
    GuardrailResult,
    GuardrailViolation,
    OnFail,
)


class MaxLengthGuardrail:
    """Blocks or truncates text that exceeds a character limit.

    With on_fail=BLOCK (default): rejects text over the limit.
    With on_fail=FIX: truncates text to the limit and continues.
    """

    def __init__(
        self,
        max_length: int,
        on_fail: OnFail = OnFail.BLOCK,
    ) -> None:
        if max_length < 1:
            raise ValueError("max_length must be >= 1")
        self._max_length = max_length
        self._on_fail = on_fail

    @property
    def name(self) -> str:
        return "max_length"

    @property
    def on_fail(self) -> OnFail:
        return self._on_fail

    async def validate(self, text: str, **kwargs: Any) -> GuardrailResult:
        """Check text length against the configured limit."""
        if len(text) <= self._max_length:
            return GuardrailResult(passed=True, output=text)

        violation_msg = f"Text length {len(text)} exceeds maximum {self._max_length}"
        violation = GuardrailViolation(self.name, violation_msg)

        if self._on_fail == OnFail.FIX:
            truncated = text[: self._max_length]
            return GuardrailResult(
                passed=False,
                output=truncated,
                violation=violation_msg,
                violations=[violation],
            )

        return GuardrailResult(
            passed=False,
            output=text,
            violation=violation_msg,
            violations=[violation],
        )


class RegexGuardrail:
    """Validates text against a regex pattern.

    Args:
        pattern: Regex pattern string.
        must_match: If True (default), text must match the pattern to pass.
                    If False, text must NOT match the pattern to pass.
        on_fail: Action on violation (default: BLOCK).
    """

    def __init__(
        self,
        pattern: str,
        must_match: bool = True,
        on_fail: OnFail = OnFail.BLOCK,
    ) -> None:
        self._pattern = re.compile(pattern)
        self._must_match = must_match
        self._on_fail = on_fail

    @property
    def name(self) -> str:
        return "regex_guardrail"

    @property
    def on_fail(self) -> OnFail:
        return self._on_fail

    async def validate(self, text: str, **kwargs: Any) -> GuardrailResult:
        """Validate text against the configured regex pattern."""
        matches = bool(self._pattern.search(text))

        if self._must_match and matches:
            return GuardrailResult(passed=True, output=text)
        if not self._must_match and not matches:
            return GuardrailResult(passed=True, output=text)

        # Violation
        if self._must_match:
            violation_msg = f"Text does not match required pattern: {self._pattern.pattern}"
        else:
            violation_msg = f"Text matches forbidden pattern: {self._pattern.pattern}"

        return GuardrailResult(
            passed=False,
            output=text,
            violation=violation_msg,
            violations=[GuardrailViolation(self.name, violation_msg)],
        )


class PIIRedactionGuardrail:
    """Detects and optionally redacts PII in text.

    If presidio_analyzer and presidio_anonymizer are installed, uses them
    for accurate PII detection and redaction. Otherwise, falls back to
    basic regex patterns.

    With on_fail=FIX (recommended): redacts detected PII and continues.
    With on_fail=BLOCK: rejects text containing PII.
    """

    # Fallback regex patterns when Presidio is not available
    _FALLBACK_PATTERNS: ClassVar[dict[str, re.Pattern[str]]] = {
        "email": re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
        "phone": re.compile(r"\b(?:\+?(\d{1,3}))?[-. (]*(\d{3})[-. )]*(\d{3})[-. ]*(\d{4})\b"),
        "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "credit_card": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
    }

    _REPLACEMENT_MAP: ClassVar[dict[str, str]] = {
        "email": "[EMAIL_REDACTED]",
        "phone": "[PHONE_REDACTED]",
        "ssn": "[SSN_REDACTED]",
        "credit_card": "[CC_REDACTED]",
    }

    def __init__(
        self,
        on_fail: OnFail = OnFail.FIX,
        entities: list[str] | None = None,
    ) -> None:
        self._on_fail = on_fail
        self._entities = entities  # Presidio entity types

        # Try to import Presidio
        self._presidio_available = False
        self._analyzer: Any = None
        self._anonymizer: Any = None
        try:
            from presidio_analyzer import AnalyzerEngine  # type: ignore[import-untyped]
            from presidio_anonymizer import AnonymizerEngine  # type: ignore[import-untyped]

            self._analyzer = AnalyzerEngine()
            self._anonymizer = AnonymizerEngine()
            self._presidio_available = True
        except ImportError:
            pass

    @property
    def name(self) -> str:
        return "pii_redaction"

    @property
    def on_fail(self) -> OnFail:
        return self._on_fail

    async def validate(self, text: str, **kwargs: Any) -> GuardrailResult:
        """Detect PII and optionally redact it."""
        if self._presidio_available:
            return await self._validate_with_presidio(text)
        return await self._validate_with_regex(text)

    async def _validate_with_presidio(self, text: str) -> GuardrailResult:
        """Use Presidio for PII detection and redaction."""
        entities = self._entities or [
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
            "CREDIT_CARD",
            "US_SSN",
        ]
        results = self._analyzer.analyze(text=text, language="en", entities=entities)

        if not results:
            return GuardrailResult(passed=True, output=text)

        violation_types = list({r.entity_type for r in results})
        violation_msg = f"PII detected: {', '.join(violation_types)}"
        violations = [
            GuardrailViolation(self.name, f"PII detected: {r.entity_type}") for r in results
        ]

        if self._on_fail == OnFail.FIX:
            anonymized = self._anonymizer.anonymize(text=text, analyzer_results=results)
            return GuardrailResult(
                passed=False,
                output=anonymized.text,
                violation=violation_msg,
                violations=violations,
            )

        return GuardrailResult(
            passed=False,
            output=text,
            violation=violation_msg,
            violations=violations,
        )

    async def _validate_with_regex(self, text: str) -> GuardrailResult:
        """Fallback: use regex patterns for PII detection."""
        violations: list[GuardrailViolation] = []
        redacted_text = text

        for pii_type, pattern in self._FALLBACK_PATTERNS.items():
            if pattern.search(text):
                violations.append(GuardrailViolation(self.name, f"PII detected: {pii_type}"))
                if self._on_fail == OnFail.FIX:
                    redacted_text = pattern.sub(self._REPLACEMENT_MAP[pii_type], redacted_text)

        if not violations:
            return GuardrailResult(passed=True, output=text)

        violation_msg = violations[0].message

        if self._on_fail == OnFail.FIX:
            return GuardrailResult(
                passed=False,
                output=redacted_text,
                violation=violation_msg,
                violations=violations,
            )

        return GuardrailResult(
            passed=False,
            output=text,
            violation=violation_msg,
            violations=violations,
        )
