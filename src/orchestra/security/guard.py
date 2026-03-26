"""Integrated security guard for prompt injection and capability attenuation (T-4.10).

Combines Rebuff (detection) with CapabilityAttenuator (mitigation)
and post-execution output scanning for secrets/PII leaks.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import structlog

from orchestra.core.context import ExecutionContext
from orchestra.core.types import AgentResult, MessageRole
from orchestra.identity.types import UCANCapability
from orchestra.security.attenuation import CapabilityAttenuator
from orchestra.security.rebuff import RebuffChecker

logger = structlog.get_logger(__name__)


class PromptShieldGuard:
    """Orchestrates multi-layer security for an agent execution.

    Layers:
      1. Pre-execution: Rebuff scan for injection.
      2. Dynamic: Attenuate capabilities if risk is detected.
      3. Execution: Run the agent with restricted context.
      4. Post-execution: Scan output for leaked secrets or PII.
    """

    def __init__(
        self,
        checker: RebuffChecker | None = None,
        attenuator: CapabilityAttenuator | None = None,
        risk_threshold: float = 0.8,
    ) -> None:
        self._checker = checker
        self._attenuator = attenuator or CapabilityAttenuator(risk_threshold=risk_threshold)
        self._risk_threshold = risk_threshold

    async def pre_execute_scan(
        self,
        context: ExecutionContext,
        user_input: str,
        base_capabilities: Sequence[UCANCapability],
    ) -> list[UCANCapability]:
        """Check for injection and return allowed (potentially attenuated) capabilities."""
        if not self._checker:
            return list(base_capabilities)

        detection = await self._checker.check_injection(user_input)

        was_restricted = context.restricted_mode

        # Score-based attenuation (sync, no await — atomic in asyncio cooperative model).
        self._attenuator.process_risk_score(context, detection.model_score)

        if detection.injection_detected:
            # Rebuff's combined 'injection_detected' is a hard block regardless of score.
            logger.warning("injection_blocked_pre_execute", run_id=context.run_id)
            context.restricted_mode = True

        # Emit a dedicated RestrictedModeEntered event when restricted_mode is
        # *newly* entered so monitoring systems can subscribe by event type
        # (isinstance check) rather than string-matching violation_type.
        if not was_restricted and context.restricted_mode and context.event_bus is not None:
            from orchestra.storage.events import RestrictedModeEntered

            await context.event_bus.emit(
                RestrictedModeEntered(
                    run_id=context.run_id,
                    node_id=context.node_id,
                    risk_score=detection.model_score,
                    injection_detected=detection.injection_detected,
                    trigger="injection_detected" if detection.injection_detected else "risk_score",
                )
            )

        return self._attenuator.get_allowed_capabilities(context, base_capabilities)

    async def post_execute_scan(
        self, context: ExecutionContext, result: AgentResult
    ) -> AgentResult:
        """Scan agent output for anomalies or leaks."""
        if not context.restricted_mode:
            # In normal mode, we might still do a light PII scan
            return result

        # In restricted mode, we are extra paranoid about the output
        output = result.output
        if any(secret_word in output.lower() for secret_word in ["sk-", "password", "key-"]):
            logger.error("secret_leak_detected_in_restricted_mode", run_id=context.run_id)
            result.output = "[REDACTED] Output blocked due to potential security leak."
            result.state_updates["security_violation"] = "leaked_secret_in_restricted_mode"

        return result


def make_security_guard_middleware(
    guard: PromptShieldGuard,
) -> Callable[..., Awaitable[AgentResult]]:
    """Factory for middleware that applies PromptShieldGuard to every run."""

    async def security_middleware(run_func: Any, input: Any, context: Any) -> AgentResult:
        # 1. Identify user input
        user_text = ""
        if isinstance(input, str):
            user_text = input
        elif isinstance(input, list):
            user_text = next((m.content for m in reversed(input) if m.role == MessageRole.USER), "")

        # 2. Pre-scan & Attenuate
        # Note: In a real system, base_caps would come from the context's UCAN
        base_caps = getattr(context, "capabilities", [])
        allowed_caps = await guard.pre_execute_scan(context, user_text, base_caps)

        # Override context capabilities for this run
        context.capabilities = allowed_caps

        # 3. Execute
        result = await run_func(input, context)

        # 4. Post-scan
        return await guard.post_execute_scan(context, result)

    return security_middleware
