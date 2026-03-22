"""Capability attenuation based on risk detection."""

from __future__ import annotations

from collections.abc import Sequence

import structlog

from orchestra.core.context import ExecutionContext
from orchestra.identity.types import UCANCapability
from orchestra.identity.ucan import UCANManager

logger = structlog.get_logger(__name__)


class CapabilityAttenuator:
    """Monitors risk and attenuates agent capabilities.

    If a high injection score is detected, the attenuator sets restricted_mode
    on the execution context and provides narrowed capability sets.
    """

    def __init__(self, risk_threshold: float = 0.8) -> None:
        self.risk_threshold = risk_threshold

    def process_risk_score(self, context: ExecutionContext, score: float) -> None:
        """Update context state based on a risk score."""
        if score >= self.risk_threshold and not context.restricted_mode:
            logger.warning("entering_restricted_mode", score=score, run_id=context.run_id)
            context.restricted_mode = True

    def get_allowed_capabilities(
        self, context: ExecutionContext, base_capabilities: Sequence[UCANCapability]
    ) -> list[UCANCapability]:
        """Filter/narrow capabilities if in restricted mode."""
        if not context.restricted_mode:
            return list(base_capabilities)

        # Restricted mode: only allow non-sensitive resources
        allowed = []
        for cap in base_capabilities:
            # Block secrets and destructive tool operations
            if "secrets" in cap.resource:
                continue
            if "delete" in cap.ability or "write" in cap.ability:
                continue

            allowed.append(cap)

        logger.debug("capabilities_attenuated", count=len(allowed))
        return allowed

    async def attenuate_token(
        self,
        context: ExecutionContext,
        ucan_manager: UCANManager,
        parent_token: str,
        audience_did: str,
        requested_caps: Sequence[UCANCapability],
    ) -> str:
        """Generate an attenuated UCAN token for a sub-agent."""
        final_caps = self.get_allowed_capabilities(context, requested_caps)

        return ucan_manager.delegate(
            parent_token=parent_token,
            audience_did=audience_did,
            capabilities=final_caps,
            ttl_seconds=300,  # Shorter TTL for attenuated tokens
        )
