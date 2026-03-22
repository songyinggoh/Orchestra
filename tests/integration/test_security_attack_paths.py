"""Security Integration Tests: Attack Paths and Enforcement (Week 1).

Verifies the remediation of:
1. CRITICAL-3.4: UCAN Capability Narrowing (DD-4).
2. CRITICAL-4.3: Agent Card Revocation.
3. CRITICAL-4.4/4.5: Serialization RCE via dynamic imports.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from orchestra.core.errors import AgentRevokedException, CapabilityDeniedError
from orchestra.core.types import AgentResult
from orchestra.identity.agent_identity import RevocationList
from orchestra.identity.types import UCANCapability, UCANToken
from orchestra.memory.serialization import pack, unpack
from orchestra.security.acl import ToolACL


@pytest.fixture
def mock_llm():
    """Mock LLM provider for security tests."""
    provider = MagicMock()
    # Default to a simple stop response
    from orchestra.core.types import LLMResponse

    provider.complete = asyncio.iscoroutinefunction(MagicMock())

    async def side_effect(*args, **kwargs):
        return LLMResponse(role="assistant", content="Done.", finish_reason="stop")

    provider.complete.side_effect = side_effect
    return provider


@pytest.mark.asyncio
async def test_ucan_narrowing_enforcement_integration():
    """Integration: Verify that UCAN narrowing is enforced during tool execution.

    Covers CRITICAL-3.4: A child token must not widen capabilities granted by parent.
    """
    # 1. Create a root capability (All tools)
    root_caps = (UCANCapability(resource="orchestra:tools/*", ability="tool/invoke"),)
    parent_token = UCANToken(
        raw="root_jwt",
        issuer_did="did:peer:root",
        audience_did="did:peer:child",
        capabilities=root_caps,
        not_before=0,
        expires_at=9999999999,
        nonce="n1",
        proofs=(),
    )

    # 2. Create a child token that tries to WIDEN or access something it shouldn't
    # (Here we just use valid narrowing first to confirm it works)
    child_caps_valid = (
        UCANCapability(resource="orchestra:tools/web_search", ability="tool/invoke"),
    )
    child_token_valid = UCANToken(
        raw="child_jwt_valid",
        issuer_did="did:peer:child",
        audience_did="did:peer:agent",
        capabilities=child_caps_valid,
        not_before=0,
        expires_at=9999999999,
        nonce="n2",
        proofs=(json_serialize_ucan(parent_token),),
    )

    # 3. Create a child token that tries to WIDEN (Parent has nothing, child claims tools)
    child_caps_invalid = (
        UCANCapability(resource="orchestra:tools/file_read", ability="tool/invoke"),
    )
    parent_token_empty = UCANToken(
        raw="empty_jwt",
        issuer_did="did:peer:root",
        audience_did="did:peer:child",
        capabilities=(),  # Empty!
        not_before=0,
        expires_at=9999999999,
        nonce="n3",
        proofs=(),
    )
    child_token_invalid = UCANToken(
        raw="child_jwt_invalid",
        issuer_did="did:peer:child",
        audience_did="did:peer:agent",
        capabilities=child_caps_invalid,
        not_before=0,
        expires_at=9999999999,
        nonce="n4",
        proofs=(json_serialize_ucan(parent_token_empty),),
    )

    acl = ToolACL(allow_all=True)

    # Valid narrowing should pass
    assert acl.is_authorized("web_search", ucan=child_token_valid) is True

    # Widening attempt should be REJECTED (CRITICAL-3.4)
    with pytest.raises(CapabilityDeniedError) as exc:
        acl.is_authorized("file_read", ucan=child_token_invalid)

    assert "widening detected" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_agent_revocation_enforcement_integration():
    """Integration: Verify that revoked agents are blocked from tool execution.

    Covers CRITICAL-4.3: Revocation list check must precede all other logic.
    """
    rl = RevocationList()
    agent_did = "did:peer:2:revoked_agent_123"

    # 1. Revoke the agent
    rl.revoke(agent_did)

    acl = ToolACL(allow_all=True)

    # 2. Attempt tool execution as revoked agent
    # ToolACL.is_authorized should raise AgentRevokedException
    with pytest.raises(AgentRevokedException) as exc:
        acl.is_authorized("any_tool", agent_did=agent_did, revocation_list=rl)

    assert agent_did in str(exc.value)

    # 3. Verify unrevoked agent works
    assert (
        acl.is_authorized("any_tool", agent_did="did:peer:2:safe_agent", revocation_list=rl) is True
    )


@pytest.mark.asyncio
async def test_serialization_rce_attack_prevention():
    """Integration: Verify that dynamic import deserialization is restricted.

    Covers CRITICAL-4.4/4.5: Prevent RCE via malicious msgpack payloads.
    """
    # This payload attempts to reconstruct a class from 'os' module
    malicious_payload = {
        "__type__": "pydantic",
        "module": "os",
        "name": "system",
        "data": {"command": "ls -la"},
    }

    # Pack it using the internal default (which would happen if an attacker crafts a message)
    import msgpack

    data = msgpack.packb(malicious_payload, use_bin_type=True)

    # Unpack it using our secure unpacker
    unpacked = unpack(data)

    # It should NOT be a function or have executed.
    # Current implementation (prefix check) returns the 'data' field if module not allowed.
    assert isinstance(unpacked, dict)
    assert unpacked == {"command": "ls -la"}
    assert "module" not in unpacked

    # Now try a valid Orchestra type
    valid_res = AgentResult(agent_name="test", output="hello")
    valid_data = pack(valid_res)

    unpacked_valid = unpack(valid_data)
    assert isinstance(unpacked_valid, AgentResult)
    assert unpacked_valid.output == "hello"


def json_serialize_ucan(token: UCANToken) -> str:
    """Helper to serialize UCANToken to JSON for proof inclusion."""
    import json

    return json.dumps(
        {
            "issuer_did": token.issuer_did,
            "audience_did": token.audience_did,
            "capabilities": [
                {"resource": c.resource, "ability": c.ability} for c in token.capabilities
            ],
            "expires_at": token.expires_at,
            "proofs": list(token.proofs),
        }
    )
