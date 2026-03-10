"""Guardrails: lightweight input/output validation hooks.

Provides a composable guardrail framework with configurable failure actions.
Guardrails are optional and configured via ExecutionContext.config or
GuardedAgent's input_guardrails / output_guardrails chains.

Classes:
    OnFail          - enum of failure actions (BLOCK, FIX, LOG, RETRY, EXCEPTION)
    GuardrailResult - result from a single guardrail validation
    Guardrail       - runtime-checkable protocol for guardrail implementations
    GuardrailChain  - runs validators sequentially with OnFail-driven actions
    GuardedAgent    - BaseAgent subclass with input/output guardrail hooks
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable

import structlog
from pydantic import BaseModel, Field, ValidationError

from orchestra.core.types import Message, MessageRole

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------


class OnFail(str, Enum):
    """Actions to take when a guardrail validation fails."""

    BLOCK = "block"          # Stop processing, return violation
    FIX = "fix"              # Attempt to fix the content and continue
    LOG = "log"              # Log the violation but continue
    RETRY = "retry"          # Ask the LLM to retry (used at GuardedAgent level)
    EXCEPTION = "exception"  # Raise an exception


@dataclass(frozen=True)
class GuardrailViolation:
    """Single violation produced by a guardrail check."""

    guardrail: str
    message: str


@dataclass
class GuardrailResult:
    """Result from running a guardrail (or a chain of guardrails).

    Attributes:
        passed: True if validation passed (no blocking violations).
        output: The (possibly fixed) content after guardrail processing.
        violation: Human-readable violation message, if any.
        violations: Full list of GuardrailViolation objects.
    """

    passed: bool
    output: Any = None
    violation: Optional[str] = None
    violations: list[GuardrailViolation] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Guardrail(Protocol):
    """Protocol for guardrail implementations.

    Every guardrail exposes:
      - name: identifier
      - on_fail: what to do when validation fails
      - validate: async validation of a text string
    """

    @property
    def name(self) -> str: ...

    @property
    def on_fail(self) -> OnFail: ...

    async def validate(self, text: str, **kwargs: Any) -> GuardrailResult: ...

    # Legacy interface kept for compiled.py backward compat
    async def validate_input(
        self,
        *,
        messages: list[Message],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> list[GuardrailViolation]: ...

    async def validate_output(
        self,
        *,
        output_text: str,
        model: str | None = None,
    ) -> list[GuardrailViolation]: ...


# ---------------------------------------------------------------------------
# GuardrailChain
# ---------------------------------------------------------------------------


class GuardrailChain:
    """Run a sequence of guardrails with per-guardrail OnFail actions.

    The chain processes validators in order. Each validator's on_fail
    determines what happens when it reports a violation:
      - BLOCK: stop immediately, return failure
      - FIX: use the validator's fixed output and continue
      - LOG: log the violation and continue
      - EXCEPTION: raise a GuardrailError
      - RETRY: mark for retry (caller handles retry logic)
    """

    def __init__(self, guardrails: list[Any] | None = None) -> None:
        self._guardrails: list[Any] = list(guardrails or [])

    def add(self, guardrail: Any) -> "GuardrailChain":
        """Add a guardrail to the chain (builder pattern)."""
        self._guardrails.append(guardrail)
        return self

    @property
    def guardrails(self) -> list[Any]:
        return list(self._guardrails)

    def __len__(self) -> int:
        return len(self._guardrails)

    async def run(self, text: str, **kwargs: Any) -> GuardrailResult:
        """Run all guardrails in sequence against *text*.

        Returns a GuardrailResult. If any guardrail with on_fail=BLOCK or
        on_fail=EXCEPTION fires, the chain short-circuits.
        """
        current_text = text
        all_violations: list[GuardrailViolation] = []

        for g in self._guardrails:
            result = await g.validate(current_text, **kwargs)
            if result.passed:
                # If the guardrail returned fixed output, use it
                if result.output is not None:
                    current_text = result.output
                continue

            # Validation failed -- apply on_fail policy
            on_fail = getattr(g, "on_fail", OnFail.BLOCK)
            all_violations.extend(result.violations)

            if on_fail == OnFail.BLOCK:
                return GuardrailResult(
                    passed=False,
                    output=current_text,
                    violation=result.violation,
                    violations=all_violations,
                )

            elif on_fail == OnFail.EXCEPTION:
                raise GuardrailError(
                    f"Guardrail '{g.name}' failed: {result.violation}",
                    violations=all_violations,
                )

            elif on_fail == OnFail.FIX:
                if result.output is not None:
                    current_text = result.output
                    logger.info(
                        "guardrail_fix_applied",
                        guardrail=g.name,
                        violation=result.violation,
                    )
                else:
                    # FIX requested but no fixed output provided -- treat as BLOCK
                    return GuardrailResult(
                        passed=False,
                        output=current_text,
                        violation=result.violation,
                        violations=all_violations,
                    )

            elif on_fail == OnFail.LOG:
                logger.warning(
                    "guardrail_violation_logged",
                    guardrail=g.name,
                    violation=result.violation,
                )

            elif on_fail == OnFail.RETRY:
                # Signal that a retry is needed (caller handles)
                return GuardrailResult(
                    passed=False,
                    output=current_text,
                    violation=result.violation,
                    violations=all_violations,
                )

        return GuardrailResult(passed=True, output=current_text, violations=all_violations)


class GuardrailError(Exception):
    """Raised when a guardrail with on_fail=EXCEPTION fires."""

    def __init__(self, message: str, violations: list[GuardrailViolation] | None = None) -> None:
        super().__init__(message)
        self.violations = violations or []


# ---------------------------------------------------------------------------
# GuardedAgent
# ---------------------------------------------------------------------------


class GuardedAgent(BaseModel):
    """BaseAgent subclass that runs guardrail chains on input and output.

    Configure input_guardrails and output_guardrails as GuardrailChain
    instances. When a guardrail with on_fail=RETRY fires, the agent
    re-prompts the LLM up to max_retries times.
    """

    name: str = "guarded_agent"
    model: str = "gpt-4o-mini"
    system_prompt: str = "You are a helpful assistant."
    tools: list[Any] = Field(default_factory=list)
    acl: Any = None
    max_iterations: int = 10
    temperature: float = 0.7
    output_type: Any = None
    provider: str | None = None

    # Guardrail configuration
    input_guardrails: Any = None   # GuardrailChain or None
    output_guardrails: Any = None  # GuardrailChain or None
    max_retries: int = 2

    model_config = {"arbitrary_types_allowed": True}

    async def run(
        self,
        input: str | list[Message],
        context: Any,
    ) -> Any:
        """Execute the agent with guardrail hooks.

        1. Run input guardrails
        2. Call LLM (delegating to BaseAgent.run logic)
        3. Run output guardrails with retry on RETRY failures
        """
        from orchestra.core.agent import BaseAgent
        from orchestra.core.types import AgentResult

        # -- Input guardrails --
        if self.input_guardrails is not None:
            input_text = self._extract_input_text(input)
            input_result = await self.input_guardrails.run(input_text)
            if not input_result.passed:
                on_fail_action = self._get_chain_blocking_action(self.input_guardrails)
                if on_fail_action == OnFail.EXCEPTION:
                    raise GuardrailError(
                        f"Input guardrail failed: {input_result.violation}",
                        violations=input_result.violations,
                    )
                return AgentResult(
                    agent_name=self.name,
                    output=f"Input blocked by guardrail: {input_result.violation}",
                )
            # Use potentially fixed input
            if input_result.output is not None:
                if isinstance(input, str):
                    input = input_result.output
                # If list[Message], we keep original messages (fix applies to text only)

        # -- LLM call with output guardrails + retry --
        # Create a temporary BaseAgent to reuse the run logic
        base = BaseAgent(
            name=self.name,
            model=self.model,
            system_prompt=self.system_prompt,
            tools=self.tools,
            acl=self.acl,
            max_iterations=self.max_iterations,
            temperature=self.temperature,
            output_type=self.output_type,
            provider=self.provider,
        )

        for attempt in range(1 + self.max_retries):
            result: AgentResult = await base.run(input, context)

            if self.output_guardrails is None:
                return result

            output_result = await self.output_guardrails.run(result.output)
            if output_result.passed:
                # Apply any fixed output
                if output_result.output is not None and output_result.output != result.output:
                    result = AgentResult(
                        agent_name=result.agent_name,
                        output=output_result.output,
                        structured_output=result.structured_output,
                        messages=result.messages,
                        tool_calls_made=result.tool_calls_made,
                        token_usage=result.token_usage,
                    )
                return result

            # Output failed -- check if we should retry
            on_fail_action = self._get_chain_blocking_action(self.output_guardrails)
            if on_fail_action == OnFail.RETRY and attempt < self.max_retries:
                logger.info(
                    "guardrail_retry",
                    agent=self.name,
                    attempt=attempt + 1,
                    violation=output_result.violation,
                )
                continue

            if on_fail_action == OnFail.EXCEPTION:
                raise GuardrailError(
                    f"Output guardrail failed: {output_result.violation}",
                    violations=output_result.violations,
                )

            # BLOCK or exhausted retries
            return AgentResult(
                agent_name=self.name,
                output=f"Output blocked by guardrail: {output_result.violation}",
            )

        # Should not reach here, but safety net
        return result  # type: ignore[possibly-undefined]

    def _extract_input_text(self, input: str | list[Message]) -> str:
        """Extract plain text from input for guardrail validation."""
        if isinstance(input, str):
            return input
        return " ".join(msg.content for msg in input if msg.content)

    @staticmethod
    def _get_chain_blocking_action(chain: GuardrailChain) -> OnFail:
        """Determine the on_fail action that caused the chain to stop."""
        # Return the on_fail of the first guardrail with a non-LOG action
        for g in chain.guardrails:
            action = getattr(g, "on_fail", OnFail.BLOCK)
            if action != OnFail.LOG:
                return action
        return OnFail.BLOCK



# ---------------------------------------------------------------------------
# Built-in guardrail implementations
# ---------------------------------------------------------------------------


class ContentFilter:
    """Blocks messages containing banned keywords or patterns."""

    def __init__(
        self,
        banned_words: list[str] | None = None,
        patterns: list[str] | None = None,
        on_fail: OnFail = OnFail.BLOCK,
    ) -> None:
        self.banned_words = [w.lower() for w in (banned_words or [])]
        self.patterns = [re.compile(p, re.IGNORECASE) for p in (patterns or [])]
        self._on_fail = on_fail

    @property
    def name(self) -> str:
        return "content_filter"

    @property
    def on_fail(self) -> OnFail:
        return self._on_fail

    async def validate(self, text: str, **kwargs: Any) -> GuardrailResult:
        """Validate text against banned words/patterns."""
        violations = []
        content = text.lower()
        for word in self.banned_words:
            if word in content:
                violations.append(
                    GuardrailViolation(self.name, f"Banned word found: {word}")
                )
        for pattern in self.patterns:
            if pattern.search(text):
                violations.append(
                    GuardrailViolation(self.name, f"Banned pattern found: {pattern.pattern}")
                )
        if violations:
            return GuardrailResult(
                passed=False,
                output=text,
                violation=violations[0].message,
                violations=violations,
            )
        return GuardrailResult(passed=True, output=text)

    # Legacy interface for compiled.py backward compat
    async def validate_input(
        self,
        *,
        messages: list[Message],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> list[GuardrailViolation]:
        violations = []
        for msg in messages:
            result = await self.validate(msg.content)
            violations.extend(result.violations)
        return violations

    async def validate_output(
        self,
        *,
        output_text: str,
        model: str | None = None,
    ) -> list[GuardrailViolation]:
        result = await self.validate(output_text)
        return result.violations


class PIIDetector:
    """Basic PII detection using regex patterns."""

    _PATTERNS = {
        "email": r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
        "phone": r"\b(?:\+?(\d{1,3}))?[-. (]*(\d{3})[-. )]*(\d{3})[-. ]*(\d{4})\b",
        "credit_card": r"\b(?:\d[ -]*?){13,16}\b",
        "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    }

    def __init__(
        self,
        detect: list[str] | None = None,
        on_fail: OnFail = OnFail.BLOCK,
    ) -> None:
        to_detect = detect or list(self._PATTERNS.keys())
        self.regexes = {
            name: re.compile(self._PATTERNS[name])
            for name in to_detect
            if name in self._PATTERNS
        }
        self._on_fail = on_fail

    @property
    def name(self) -> str:
        return "pii_detector"

    @property
    def on_fail(self) -> OnFail:
        return self._on_fail

    async def validate(self, text: str, **kwargs: Any) -> GuardrailResult:
        """Check text for PII patterns."""
        violations = []
        for pii_type, regex in self.regexes.items():
            if regex.search(text):
                violations.append(
                    GuardrailViolation(self.name, f"PII detected: {pii_type}")
                )
        if violations:
            return GuardrailResult(
                passed=False,
                output=text,
                violation=violations[0].message,
                violations=violations,
            )
        return GuardrailResult(passed=True, output=text)

    # Legacy interface
    async def _check_content(self, text: str) -> list[GuardrailViolation]:
        result = await self.validate(text)
        return result.violations

    async def validate_input(
        self,
        *,
        messages: list[Message],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> list[GuardrailViolation]:
        violations = []
        for msg in messages:
            violations.extend(await self._check_content(msg.content))
        return violations

    async def validate_output(
        self,
        *,
        output_text: str,
        model: str | None = None,
    ) -> list[GuardrailViolation]:
        return await self._check_content(output_text)


class SchemaValidator:
    """Validates that output can be parsed into a Pydantic model."""

    def __init__(
        self,
        schema: type[BaseModel],
        on_fail: OnFail = OnFail.BLOCK,
    ) -> None:
        self.schema = schema
        self._on_fail = on_fail

    @property
    def name(self) -> str:
        return f"schema_validator[{self.schema.__name__}]"

    @property
    def on_fail(self) -> OnFail:
        return self._on_fail

    async def validate(self, text: str, **kwargs: Any) -> GuardrailResult:
        """Validate text as JSON against the schema."""
        import json
        try:
            data = json.loads(text)
            self.schema.model_validate(data)
            return GuardrailResult(passed=True, output=text)
        except (json.JSONDecodeError, ValidationError) as e:
            violation = f"Output failed schema validation: {str(e)}"
            return GuardrailResult(
                passed=False,
                output=text,
                violation=violation,
                violations=[GuardrailViolation(self.name, violation)],
            )

    # Legacy interface
    async def validate_input(
        self,
        *,
        messages: list[Message],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> list[GuardrailViolation]:
        return []

    async def validate_output(
        self,
        *,
        output_text: str,
        model: str | None = None,
    ) -> list[GuardrailViolation]:
        result = await self.validate(output_text)
        return result.violations
