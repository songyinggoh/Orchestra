from unittest.mock import MagicMock

import pytest

from orchestra.core.context import ExecutionContext
from orchestra.identity.types import UCANCapability
from orchestra.security.attenuation import CapabilityAttenuator


def test_attenuator_triggers_restricted_mode():
    context = ExecutionContext()
    attenuator = CapabilityAttenuator(risk_threshold=0.8)

    # Low score
    attenuator.process_risk_score(context, 0.2)
    assert context.restricted_mode is False

    # High score
    attenuator.process_risk_score(context, 0.9)
    assert context.restricted_mode is True


def test_attenuator_filters_capabilities():
    context = ExecutionContext()
    attenuator = CapabilityAttenuator()

    base_caps = [
        UCANCapability("orchestra:tools/web_search", "tool/invoke"),
        UCANCapability("orchestra:secrets/api_keys", "read"),
        UCANCapability("orchestra:files", "write"),
    ]

    # Normal mode
    allowed1 = attenuator.get_allowed_capabilities(context, base_caps)
    assert len(allowed1) == 3

    # Restricted mode
    context.restricted_mode = True
    allowed2 = attenuator.get_allowed_capabilities(context, base_caps)

    # Should only have web_search
    assert len(allowed2) == 1
    assert allowed2[0].resource == "orchestra:tools/web_search"


@pytest.mark.asyncio
async def test_attenuate_token_delegation():
    context = ExecutionContext()
    context.restricted_mode = True
    attenuator = CapabilityAttenuator()

    ucan_mgr = MagicMock()
    # Mock ucan_mgr.delegate to return a dummy string
    ucan_mgr.delegate.return_value = "attenuated-token"

    caps = [
        UCANCapability("orchestra:tools", "invoke"),
        UCANCapability("orchestra:secrets", "read"),
    ]

    token = await attenuator.attenuate_token(context, ucan_mgr, "parent-jwt", "child-did", caps)

    assert token == "attenuated-token"
    # Verify only one cap was delegated
    args = ucan_mgr.delegate.call_args[1]
    assert len(args["capabilities"]) == 1
    assert args["capabilities"][0].resource == "orchestra:tools"
