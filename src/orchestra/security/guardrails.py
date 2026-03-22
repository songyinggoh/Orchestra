"""Guardrails: lightweight input/output validation hooks.

Provides a composable guardrail framework with configurable failure actions.
Guardrails are optional and configured via ExecutionContext.config or
GuardedAgent's input_guardrails / output_guardrails chains.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Protocol, runtime_checkable

import structlog
from pydantic import BaseModel, Field, ValidationError

from orchestra.core.types import Message

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------


class OnFail(str, Enum):
    """Actions to take when a guardrail validation fails."""

    BLOCK = "block"  # Stop processing, return violation
    FIX = "fix"  # Attempt to fix the content and continue
    LOG = "log"  # Log the violation but continue
    RETRY = "retry"  # Ask the LLM to retry (used at GuardedAgent level)
    EXCEPTION = "exception"  # Raise an exception


@dataclass(frozen=True)
class GuardrailViolation:
    """Single violation produced by a guardrail check."""

    guardrail: str
    message: str


@dataclass
class GuardrailResult:
    """Result from running a guardrail (or a chain of guardrails)."""

    passed: bool
    output: Any = None
    violation: str | None = None
    violations: list[GuardrailViolation] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class GuardrailError(Exception):
    """Raised when a guardrail with on_fail=EXCEPTION fires."""

    def __init__(self, message: str, violations: list[GuardrailViolation] | None = None) -> None:
        super().__init__(message)
        self.violations = violations or []


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Guardrail(Protocol):
    """Protocol for guardrail implementations."""

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
# Built-in guardrail implementations
# ---------------------------------------------------------------------------


class PromptShield:
    """Detects prompt injections and jailbreaks using ONNX models."""

    def __init__(
        self,
        model_id: str = "meta-llama/Llama-Prompt-Guard-86M",
        threshold: float = 0.5,
        on_fail: OnFail = OnFail.BLOCK,
    ) -> None:
        self.model_id = model_id
        self.threshold = threshold
        self._on_fail = on_fail
        self._model = None
        self._tokenizer = None
        self._lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return "prompt_shield"

    @property
    def on_fail(self) -> OnFail:
        return self._on_fail

    async def _ensure_model(self) -> None:
        async with self._lock:
            if self._model is not None:
                return
            try:
                from optimum.onnxruntime import ORTModelForSequenceClassification
                from transformers import AutoTokenizer

                self._tokenizer = await asyncio.to_thread(
                    AutoTokenizer.from_pretrained, self.model_id
                )
                self._model = await asyncio.to_thread(
                    ORTModelForSequenceClassification.from_pretrained, self.model_id, export=True
                )
            except ImportError:
                self._model = False

    async def validate(self, text: str, **kwargs: Any) -> GuardrailResult:
        await self._ensure_model()
        if not self._model:
            if "ignore all previous instructions" in text.lower():
                violation = "Mock PromptShield: Potential injection detected"
                return GuardrailResult(
                    passed=False,
                    output=text,
                    violation=violation,
                    violations=[GuardrailViolation(self.name, violation)],
                    metadata={"score": 1.0},
                )
            return GuardrailResult(passed=True, output=text)

        import torch

        inputs = self._tokenizer(text, return_tensors="pt")
        outputs = await asyncio.to_thread(self._model, **inputs)
        probs = torch.softmax(outputs.logits, dim=-1)
        score = probs[0][1].item()

        if score >= self.threshold:
            violation = f"Injection detected (score: {score:.4f})"
            return GuardrailResult(
                passed=False,
                output=text,
                violation=violation,
                violations=[GuardrailViolation(self.name, violation)],
                metadata={"score": score},
            )
        return GuardrailResult(passed=True, output=text, metadata={"score": score})

    async def validate_input(
        self, *, messages: list[Message], **kwargs: Any
    ) -> list[GuardrailViolation]:
        violations = []
        for msg in messages:
            res = await self.validate(msg.content)
            violations.extend(res.violations)
        return violations

    async def validate_output(self, *, output_text: str, **kwargs: Any) -> list[GuardrailViolation]:
        res = await self.validate(output_text)
        return res.violations


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
        violations = []
        content = text.lower()
        for word in self.banned_words:
            if word in content:
                violations.append(GuardrailViolation(self.name, f"Banned word found: {word}"))
        for pattern in self.patterns:
            if pattern.search(text):
                violations.append(
                    GuardrailViolation(self.name, f"Banned pattern found: {pattern.pattern}")
                )

        if violations:
            return GuardrailResult(
                passed=False, output=text, violation=violations[0].message, violations=violations
            )
        return GuardrailResult(passed=True, output=text)

    async def validate_input(
        self, *, messages: list[Message], **kwargs: Any
    ) -> list[GuardrailViolation]:
        violations = []
        for msg in messages:
            res = await self.validate(msg.content)
            violations.extend(res.violations)
        return violations

    async def validate_output(self, *, output_text: str, **kwargs: Any) -> list[GuardrailViolation]:
        res = await self.validate(output_text)
        return res.violations


class PIIDetector:
    """Basic PII detection using regex patterns."""

    _PATTERNS: ClassVar[dict[str, str]] = {
        "email": r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
        "phone": r"\b(?:\+?(\d{1,3}))?[-. (]*(\d{3})[-. )]*(\d{3})[-. ]*(\d{4})\b",
        "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    }

    def __init__(self, detect: list[str] | None = None, on_fail: OnFail = OnFail.BLOCK) -> None:
        to_detect = detect or list(self._PATTERNS.keys())
        self.regexes = {n: re.compile(self._PATTERNS[n]) for n in to_detect if n in self._PATTERNS}
        self._on_fail = on_fail

    @property
    def name(self) -> str:
        return "pii_detector"

    @property
    def on_fail(self) -> OnFail:
        return self._on_fail

    async def validate(self, text: str, **kwargs: Any) -> GuardrailResult:
        violations = []
        for pii_type, regex in self.regexes.items():
            if regex.search(text):
                violations.append(GuardrailViolation(self.name, f"PII detected: {pii_type}"))
        if violations:
            return GuardrailResult(
                passed=False, output=text, violation=violations[0].message, violations=violations
            )
        return GuardrailResult(passed=True, output=text)

    async def validate_input(
        self, *, messages: list[Message], **kwargs: Any
    ) -> list[GuardrailViolation]:
        violations = []
        for msg in messages:
            res = await self.validate(msg.content)
            violations.extend(res.violations)
        return violations

    async def validate_output(self, *, output_text: str, **kwargs: Any) -> list[GuardrailViolation]:
        res = await self.validate(output_text)
        return res.violations


class SchemaValidator:
    """Validates that output can be parsed into a Pydantic model."""

    def __init__(self, schema: type[BaseModel], on_fail: OnFail = OnFail.BLOCK) -> None:
        self.schema = schema
        self._on_fail = on_fail

    @property
    def name(self) -> str:
        return f"schema_validator[{self.schema.__name__}]"

    @property
    def on_fail(self) -> OnFail:
        return self._on_fail

    async def validate(self, text: str, **kwargs: Any) -> GuardrailResult:
        import json

        try:
            data = json.loads(text)
            self.schema.model_validate(data)
            return GuardrailResult(passed=True, output=text)
        except (json.JSONDecodeError, ValidationError) as e:
            violation = f"Output failed schema validation: {e!s}"
            return GuardrailResult(
                passed=False,
                output=text,
                violation=violation,
                violations=[GuardrailViolation(self.name, violation)],
            )

    async def validate_input(self, **kwargs: Any) -> list[GuardrailViolation]:
        return []

    async def validate_output(self, *, output_text: str, **kwargs: Any) -> list[GuardrailViolation]:
        res = await self.validate(output_text)
        return res.violations


class GuardrailChain:
    """Run a sequence of guardrails."""

    def __init__(self, guardrails: list[Any] | None = None) -> None:
        self._guardrails: list[Any] = list(guardrails or [])

    def add(self, guardrail: Any) -> GuardrailChain:
        self._guardrails.append(guardrail)
        return self

    def __len__(self) -> int:
        return len(self._guardrails)

    @property
    def guardrails(self) -> list[Any]:
        return list(self._guardrails)

    async def run(self, text: str, **kwargs: Any) -> GuardrailResult:
        current_text = text
        all_violations: list[GuardrailViolation] = []
        for g in self._guardrails:
            result = await g.validate(current_text, **kwargs)
            if result.passed:
                if result.output is not None:
                    current_text = result.output
                continue

            on_fail = getattr(g, "on_fail", OnFail.BLOCK)
            all_violations.extend(result.violations)

            if on_fail == OnFail.BLOCK:
                return GuardrailResult(
                    passed=False,
                    output=current_text,
                    violation=result.violation,
                    violations=all_violations,
                    metadata=result.metadata,
                )
            elif on_fail == OnFail.EXCEPTION:
                raise GuardrailError(
                    f"Guardrail '{g.name}' failed: {result.violation}", violations=all_violations
                )
            elif on_fail == OnFail.FIX:
                if result.output is not None:
                    current_text = result.output
                # Continue with the fixed text
                continue
            elif on_fail == OnFail.RETRY:
                # Signal failure so the agent can retry
                return GuardrailResult(
                    passed=False,
                    output=current_text,
                    violation=result.violation,
                    violations=all_violations,
                    metadata=result.metadata,
                )
            elif on_fail == OnFail.LOG:
                logger.warning(
                    "guardrail_violation_logged", guardrail=g.name, violation=result.violation
                )
        return GuardrailResult(passed=True, output=current_text, violations=all_violations)


class GuardedAgent(BaseModel):
    """BaseAgent subclass that runs guardrail chains on input and output."""

    name: str = "guarded_agent"
    model: str = "gpt-4o-mini"
    system_prompt: str = "You are a helpful assistant."
    tools: list[Any] = Field(default_factory=list)
    acl: Any = None
    max_iterations: int = 10
    temperature: float = 0.7
    output_type: Any = None
    provider: str | None = None
    input_guardrails: Any = None
    output_guardrails: Any = None
    max_retries: int = 2

    model_config = {"arbitrary_types_allowed": True}

    async def run(self, input: str | list[Message], context: Any) -> Any:
        from orchestra.core.agent import BaseAgent
        from orchestra.core.types import AgentResult

        if self.input_guardrails is not None:
            input_text = self._extract_input_text(input)
            input_result = await self.input_guardrails.run(input_text)
            if not input_result.passed:
                return AgentResult(
                    agent_name=self.name,
                    output=f"Input blocked by guardrail: {input_result.violation}",
                )
            if input_result.output is not None and isinstance(input, str):
                input = input_result.output

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

            on_fail = self._get_chain_blocking_action(self.output_guardrails)
            if on_fail == OnFail.RETRY and attempt < self.max_retries:
                continue
            return AgentResult(
                agent_name=self.name,
                output=f"Output blocked by guardrail: {output_result.violation}",
            )
        return result

    def _extract_input_text(self, input: str | list[Message]) -> str:
        if isinstance(input, str):
            return input
        return " ".join(msg.content for msg in input if msg.content)

    @staticmethod
    def _get_chain_blocking_action(chain: GuardrailChain) -> OnFail:
        for g in chain.guardrails:
            action = getattr(g, "on_fail", OnFail.BLOCK)
            if action != OnFail.LOG:
                return action
        return OnFail.BLOCK
