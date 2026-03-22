"""Tests for Orchestra guardrails framework.

Tests cover:
- ContentFilter, PIIDetector, SchemaValidator (legacy + new validate API)
- OnFail enum
- GuardrailResult
- GuardrailChain with all OnFail actions
- GuardedAgent with input/output guardrails and retries
- MaxLengthGuardrail, RegexGuardrail, PIIRedactionGuardrail
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from orchestra.core.types import Message, MessageRole
from orchestra.security.guardrails import (
    ContentFilter,
    GuardedAgent,
    GuardrailChain,
    GuardrailError,
    GuardrailResult,
    GuardrailViolation,
    OnFail,
    PIIDetector,
    SchemaValidator,
)
from orchestra.security.validators import (
    MaxLengthGuardrail,
    PIIRedactionGuardrail,
    RegexGuardrail,
)


def _user(content: str) -> Message:
    return Message(role=MessageRole.USER, content=content)


# ---------------------------------------------------------------------------
# Existing tests (backward-compatible)
# ---------------------------------------------------------------------------


class TestContentFilter:
    @pytest.mark.asyncio
    async def test_validate_input_banned_word(self):
        gf = ContentFilter(banned_words=["apple"])
        messages = [_user("I like apples")]
        violations = await gf.validate_input(messages=messages)
        assert len(violations) == 1
        assert "apple" in violations[0].message

    @pytest.mark.asyncio
    async def test_validate_output_banned_pattern(self):
        gf = ContentFilter(patterns=[r"\d{3}-\d{2}-\d{4}"])
        violations = await gf.validate_output(output_text="My SSN is 123-45-6789")
        assert len(violations) == 1
        assert "pattern" in violations[0].message

    @pytest.mark.asyncio
    async def test_validate_clean_text(self):
        gf = ContentFilter(banned_words=["banned"])
        result = await gf.validate("This is clean text")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_validate_banned_word(self):
        gf = ContentFilter(banned_words=["secret"])
        result = await gf.validate("This is a secret message")
        assert result.passed is False
        assert "secret" in result.violation

    @pytest.mark.asyncio
    async def test_on_fail_property(self):
        gf = ContentFilter(banned_words=["x"], on_fail=OnFail.EXCEPTION)
        assert gf.on_fail == OnFail.EXCEPTION


class TestPIIDetector:
    @pytest.mark.asyncio
    async def test_detect_email(self):
        gf = PIIDetector(detect=["email"])
        violations = await gf.validate_output(output_text="Contact me at test@example.com")
        assert len(violations) == 1
        assert "email" in violations[0].message

    @pytest.mark.asyncio
    async def test_detect_phone(self):
        gf = PIIDetector(detect=["phone"])
        violations = await gf.validate_input(messages=[_user("Call me at 555-123-4567")])
        assert len(violations) == 1
        assert "phone" in violations[0].message

    @pytest.mark.asyncio
    async def test_validate_api_clean(self):
        gf = PIIDetector(detect=["email"])
        result = await gf.validate("No PII here")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_validate_api_detects_pii(self):
        gf = PIIDetector(detect=["ssn"])
        result = await gf.validate("My SSN is 123-45-6789")
        assert result.passed is False
        assert "ssn" in result.violation.lower()


class TestSchemaValidator:
    class UserProfile(BaseModel):
        name: str
        age: int

    @pytest.mark.asyncio
    async def test_valid_json_output(self):
        gf = SchemaValidator(self.UserProfile)
        violations = await gf.validate_output(output_text='{"name": "Alice", "age": 30}')
        assert len(violations) == 0

    @pytest.mark.asyncio
    async def test_invalid_json_output(self):
        gf = SchemaValidator(self.UserProfile)
        violations = await gf.validate_output(output_text='{"name": "Alice"}')  # Missing age
        assert len(violations) == 1
        assert "schema_validator" in violations[0].guardrail
        assert "age" in violations[0].message

    @pytest.mark.asyncio
    async def test_validate_api_valid(self):
        gf = SchemaValidator(self.UserProfile)
        result = await gf.validate('{"name": "Bob", "age": 25}')
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_validate_api_invalid(self):
        gf = SchemaValidator(self.UserProfile)
        result = await gf.validate("not json")
        assert result.passed is False


# ---------------------------------------------------------------------------
# OnFail enum
# ---------------------------------------------------------------------------


class TestOnFail:
    def test_all_values_exist(self):
        assert OnFail.BLOCK == "block"
        assert OnFail.FIX == "fix"
        assert OnFail.LOG == "log"
        assert OnFail.RETRY == "retry"
        assert OnFail.EXCEPTION == "exception"


# ---------------------------------------------------------------------------
# GuardrailResult
# ---------------------------------------------------------------------------


class TestGuardrailResult:
    def test_passed_result(self):
        result = GuardrailResult(passed=True, output="clean text")
        assert result.passed is True
        assert result.violation is None
        assert result.violations == []

    def test_failed_result(self):
        v = GuardrailViolation("test", "bad content")
        result = GuardrailResult(
            passed=False,
            output="bad content",
            violation="bad content",
            violations=[v],
        )
        assert result.passed is False
        assert result.violation == "bad content"
        assert len(result.violations) == 1


# ---------------------------------------------------------------------------
# GuardrailChain
# ---------------------------------------------------------------------------


class TestGuardrailChain:
    @pytest.mark.asyncio
    async def test_empty_chain_passes(self):
        chain = GuardrailChain()
        result = await chain.run("any text")
        assert result.passed is True
        assert result.output == "any text"

    @pytest.mark.asyncio
    async def test_single_passing_guardrail(self):
        chain = GuardrailChain([ContentFilter(banned_words=["bomb"])])
        result = await chain.run("Hello world")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_single_blocking_guardrail(self):
        chain = GuardrailChain([ContentFilter(banned_words=["secret"])])
        result = await chain.run("This is a secret")
        assert result.passed is False
        assert "secret" in result.violation

    @pytest.mark.asyncio
    async def test_chain_block_short_circuits(self):
        g1 = ContentFilter(banned_words=["first"], on_fail=OnFail.BLOCK)
        g2 = ContentFilter(banned_words=["second"], on_fail=OnFail.BLOCK)
        chain = GuardrailChain([g1, g2])
        result = await chain.run("first and second are banned")
        assert result.passed is False
        # Should have stopped at first guardrail
        assert "first" in result.violation

    @pytest.mark.asyncio
    async def test_chain_log_continues(self):
        g1 = ContentFilter(banned_words=["warning"], on_fail=OnFail.LOG)
        g2 = ContentFilter(banned_words=["danger"], on_fail=OnFail.BLOCK)
        chain = GuardrailChain([g1, g2])

        # Text triggers LOG guardrail but not BLOCK guardrail
        result = await chain.run("This has a warning but is safe")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_chain_exception_raises(self):
        chain = GuardrailChain([ContentFilter(banned_words=["danger"], on_fail=OnFail.EXCEPTION)])
        with pytest.raises(GuardrailError, match="danger"):
            await chain.run("This is danger")

    @pytest.mark.asyncio
    async def test_chain_fix_applies_output(self):
        g = MaxLengthGuardrail(max_length=5, on_fail=OnFail.FIX)
        chain = GuardrailChain([g])
        result = await chain.run("Hello World!")
        assert result.passed is True
        assert result.output == "Hello"

    @pytest.mark.asyncio
    async def test_chain_retry_returns_failure(self):
        chain = GuardrailChain([ContentFilter(banned_words=["retry_me"], on_fail=OnFail.RETRY)])
        result = await chain.run("retry_me please")
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_chain_add_builder(self):
        chain = GuardrailChain()
        chain.add(ContentFilter(banned_words=["bad"])).add(MaxLengthGuardrail(max_length=100))
        assert len(chain) == 2

    @pytest.mark.asyncio
    async def test_chain_multiple_validators_all_pass(self):
        chain = GuardrailChain(
            [
                ContentFilter(banned_words=["bomb"]),
                MaxLengthGuardrail(max_length=100),
                RegexGuardrail(r"\d{3}-\d{2}-\d{4}", must_match=False),
            ]
        )
        result = await chain.run("Hello, this is safe text")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_chain_fix_then_validate(self):
        """FIX guardrail truncates, then next guardrail validates the fixed output."""
        chain = GuardrailChain(
            [
                MaxLengthGuardrail(max_length=10, on_fail=OnFail.FIX),
                ContentFilter(banned_words=["bomb"]),
            ]
        )
        # "bomb" is at position 15+, after truncation it won't be in the text
        result = await chain.run("Safe text bomb is here")
        assert result.passed is True
        assert result.output == "Safe text "


# ---------------------------------------------------------------------------
# GuardedAgent
# ---------------------------------------------------------------------------


class TestGuardedAgent:
    @pytest.mark.asyncio
    async def test_input_guardrail_blocks(self):
        agent = GuardedAgent(
            name="test_agent",
            input_guardrails=GuardrailChain([ContentFilter(banned_words=["forbidden"])]),
        )
        from orchestra.core.context import ExecutionContext
        from orchestra.testing import ScriptedLLM

        ctx = ExecutionContext(
            run_id="test",
            provider=ScriptedLLM(["Should not be called"]),
        )
        result = await agent.run("This is forbidden", ctx)
        assert "blocked" in result.output.lower()

    @pytest.mark.asyncio
    async def test_output_guardrail_blocks(self):
        from orchestra.core.context import ExecutionContext
        from orchestra.testing import ScriptedLLM

        agent = GuardedAgent(
            name="test_agent",
            output_guardrails=GuardrailChain([ContentFilter(banned_words=["secret"])]),
        )
        ctx = ExecutionContext(
            run_id="test",
            provider=ScriptedLLM(["This contains a secret"]),
        )
        result = await agent.run("Tell me something", ctx)
        assert "blocked" in result.output.lower()

    @pytest.mark.asyncio
    async def test_output_guardrail_passes(self):
        from orchestra.core.context import ExecutionContext
        from orchestra.testing import ScriptedLLM

        agent = GuardedAgent(
            name="test_agent",
            output_guardrails=GuardrailChain([ContentFilter(banned_words=["bomb"])]),
        )
        ctx = ExecutionContext(
            run_id="test",
            provider=ScriptedLLM(["Safe response"]),
        )
        result = await agent.run("Hello", ctx)
        assert result.output == "Safe response"

    @pytest.mark.asyncio
    async def test_no_guardrails_passes_through(self):
        from orchestra.core.context import ExecutionContext
        from orchestra.testing import ScriptedLLM

        agent = GuardedAgent(name="test_agent")
        ctx = ExecutionContext(
            run_id="test",
            provider=ScriptedLLM(["Direct response"]),
        )
        result = await agent.run("Hello", ctx)
        assert result.output == "Direct response"

    @pytest.mark.asyncio
    async def test_output_guardrail_retry(self):
        """RETRY on_fail causes the agent to re-prompt the LLM."""
        from orchestra.core.context import ExecutionContext
        from orchestra.testing import ScriptedLLM

        agent = GuardedAgent(
            name="retry_agent",
            max_retries=2,
            output_guardrails=GuardrailChain(
                [ContentFilter(banned_words=["bad"], on_fail=OnFail.RETRY)]
            ),
        )
        # First response fails, second response succeeds
        ctx = ExecutionContext(
            run_id="test",
            provider=ScriptedLLM(["bad response", "good response"]),
        )
        result = await agent.run("Tell me something", ctx)
        assert result.output == "good response"

    @pytest.mark.asyncio
    async def test_output_guardrail_retry_exhausted(self):
        """After max_retries, the agent returns a blocked message."""
        from orchestra.core.context import ExecutionContext
        from orchestra.testing import ScriptedLLM

        agent = GuardedAgent(
            name="retry_agent",
            max_retries=1,
            output_guardrails=GuardrailChain(
                [ContentFilter(banned_words=["bad"], on_fail=OnFail.RETRY)]
            ),
        )
        ctx = ExecutionContext(
            run_id="test",
            provider=ScriptedLLM(["bad one", "bad two"]),
        )
        result = await agent.run("Hello", ctx)
        assert "blocked" in result.output.lower()

    @pytest.mark.asyncio
    async def test_input_guardrail_exception(self):
        """EXCEPTION on_fail raises GuardrailError."""
        from orchestra.core.context import ExecutionContext
        from orchestra.testing import ScriptedLLM

        agent = GuardedAgent(
            name="exception_agent",
            input_guardrails=GuardrailChain(
                [ContentFilter(banned_words=["error"], on_fail=OnFail.EXCEPTION)]
            ),
        )
        ctx = ExecutionContext(
            run_id="test",
            provider=ScriptedLLM(["unused"]),
        )
        with pytest.raises(GuardrailError):
            await agent.run("This triggers an error", ctx)

    @pytest.mark.asyncio
    async def test_output_guardrail_fix_applied(self):
        """FIX on_fail modifies the output."""
        from orchestra.core.context import ExecutionContext
        from orchestra.testing import ScriptedLLM

        agent = GuardedAgent(
            name="fix_agent",
            output_guardrails=GuardrailChain(
                [MaxLengthGuardrail(max_length=5, on_fail=OnFail.FIX)]
            ),
        )
        ctx = ExecutionContext(
            run_id="test",
            provider=ScriptedLLM(["Hello World!"]),
        )
        result = await agent.run("Greet me", ctx)
        assert result.output == "Hello"

    @pytest.mark.asyncio
    async def test_default_max_retries(self):
        agent = GuardedAgent(name="default")
        assert agent.max_retries == 2

    @pytest.mark.asyncio
    async def test_guarded_agent_with_message_list_input(self):
        from orchestra.core.context import ExecutionContext
        from orchestra.testing import ScriptedLLM

        agent = GuardedAgent(
            name="msg_agent",
            input_guardrails=GuardrailChain([ContentFilter(banned_words=["blocked"])]),
        )
        ctx = ExecutionContext(
            run_id="test",
            provider=ScriptedLLM(["unused"]),
        )
        msgs = [_user("This is blocked content")]
        result = await agent.run(msgs, ctx)
        assert "blocked" in result.output.lower()


# ---------------------------------------------------------------------------
# MaxLengthGuardrail
# ---------------------------------------------------------------------------


class TestMaxLengthGuardrail:
    @pytest.mark.asyncio
    async def test_under_limit_passes(self):
        g = MaxLengthGuardrail(max_length=100)
        result = await g.validate("Short text")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_at_limit_passes(self):
        g = MaxLengthGuardrail(max_length=5)
        result = await g.validate("Hello")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_over_limit_blocks(self):
        g = MaxLengthGuardrail(max_length=5)
        result = await g.validate("Hello World")
        assert result.passed is False
        assert "exceeds" in result.violation.lower()

    @pytest.mark.asyncio
    async def test_over_limit_fix_truncates(self):
        g = MaxLengthGuardrail(max_length=5, on_fail=OnFail.FIX)
        result = await g.validate("Hello World!")
        assert result.output == "Hello"
        assert len(result.violations) == 1

    def test_invalid_max_length(self):
        with pytest.raises(ValueError, match="max_length"):
            MaxLengthGuardrail(max_length=0)


# ---------------------------------------------------------------------------
# RegexGuardrail
# ---------------------------------------------------------------------------


class TestRegexGuardrail:
    @pytest.mark.asyncio
    async def test_must_match_passes(self):
        g = RegexGuardrail(r"^\d{3}-\d{3}-\d{4}$", must_match=True)
        result = await g.validate("555-123-4567")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_must_match_fails(self):
        g = RegexGuardrail(r"^\d{3}-\d{3}-\d{4}$", must_match=True)
        result = await g.validate("not a phone number")
        assert result.passed is False
        assert "does not match" in result.violation.lower()

    @pytest.mark.asyncio
    async def test_must_not_match_passes(self):
        g = RegexGuardrail(r"\d{3}-\d{2}-\d{4}", must_match=False)
        result = await g.validate("No SSN here")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_must_not_match_fails(self):
        g = RegexGuardrail(r"\d{3}-\d{2}-\d{4}", must_match=False)
        result = await g.validate("My SSN is 123-45-6789")
        assert result.passed is False
        assert "forbidden" in result.violation.lower()

    @pytest.mark.asyncio
    async def test_on_fail_property(self):
        g = RegexGuardrail(r"test", on_fail=OnFail.LOG)
        assert g.on_fail == OnFail.LOG


# ---------------------------------------------------------------------------
# PIIRedactionGuardrail
# ---------------------------------------------------------------------------


class TestPIIRedactionGuardrail:
    @pytest.mark.asyncio
    async def test_clean_text_passes(self):
        g = PIIRedactionGuardrail(on_fail=OnFail.FIX)
        result = await g.validate("No PII here, just normal text.")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_email_detected_and_redacted(self):
        g = PIIRedactionGuardrail(on_fail=OnFail.FIX)
        result = await g.validate("Contact me at alice@example.com today")
        # Regardless of presidio availability, PII should be handled
        assert "alice@example.com" not in result.output
        assert len(result.violations) >= 1

    @pytest.mark.asyncio
    async def test_ssn_detected_and_redacted(self):
        g = PIIRedactionGuardrail(on_fail=OnFail.FIX)
        result = await g.validate("SSN: 123-45-6789")
        assert "123-45-6789" not in result.output
        assert len(result.violations) >= 1

    @pytest.mark.asyncio
    async def test_phone_detected_and_redacted(self):
        g = PIIRedactionGuardrail(on_fail=OnFail.FIX)
        result = await g.validate("Call 555-123-4567 for info")
        assert "555-123-4567" not in result.output

    @pytest.mark.asyncio
    async def test_block_mode(self):
        g = PIIRedactionGuardrail(on_fail=OnFail.BLOCK)
        result = await g.validate("My email is test@example.com")
        assert result.passed is False
        assert result.output == "My email is test@example.com"  # Not redacted

    @pytest.mark.asyncio
    async def test_name_property(self):
        g = PIIRedactionGuardrail()
        assert g.name == "pii_redaction"
