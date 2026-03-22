"""Tests for UCAN TTLs and delegation chains."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from orchestra.core.errors import CapabilityDeniedError, UCANVerificationError
from orchestra.identity.agent_identity import AgentIdentity
from orchestra.identity.delegation import verify_delegation_chain
from orchestra.identity.types import UCANCapability
from orchestra.identity.ucan import UCANManager


@pytest.fixture
def alice():
    return AgentIdentity.create()


@pytest.fixture
def bob():
    return AgentIdentity.create()


@pytest.fixture
def charlie():
    return AgentIdentity.create()


@pytest.mark.asyncio
async def test_ucan_expiry(alice, bob):
    manager = UCANManager(signing_key=alice._make_okp_key(), issuer_did=alice.did)

    # 1. Valid token
    token = manager.issue(
        audience_did=bob.did, capabilities=[UCANCapability("res", "can")], ttl_seconds=60
    )
    payload = UCANManager.verify(token, alice._make_okp_key(), expected_audience=bob.did)
    assert payload["iss"] == alice.did

    # 2. Expired token (negative TTL)
    expired_token = manager.issue(
        audience_did=bob.did, capabilities=[UCANCapability("res", "can")], ttl_seconds=-10
    )
    with pytest.raises(UCANVerificationError, match="expired"):
        UCANManager.verify(expired_token, alice._make_okp_key())


@pytest.mark.asyncio
async def test_delegation_chain_verification(alice, bob, charlie):
    # Alice delegates to Bob
    alice_mgr = UCANManager(signing_key=alice._make_okp_key(), issuer_did=alice.did)
    cap = UCANCapability("orchestra:tools/web_search", "tool/invoke")

    token_a_b = alice_mgr.issue(audience_did=bob.did, capabilities=[cap], ttl_seconds=3600)

    # Bob delegates to Charlie (attenuated)
    bob_mgr = UCANManager(signing_key=bob._make_okp_key(), issuer_did=bob.did)
    token_b_c = bob_mgr.delegate(
        parent_token=token_a_b, audience_did=charlie.did, capabilities=[cap], ttl_seconds=1800
    )

    # Mock DID resolution
    async def mock_resolve(did):
        from orchestra.messaging.peer_did import resolve_peer_did

        doc_dict = resolve_peer_did(did)
        from orchestra.identity.did import DIDDocument

        return DIDDocument(
            id=doc_dict["id"],
            verification_methods=doc_dict["verificationMethod"],
            key_agreements=doc_dict["keyAgreement"],
            services=doc_dict["service"],
        )

    with patch("orchestra.identity.did.DIDManager.resolve", side_effect=mock_resolve):
        # Verify Charlie's token
        verified = await verify_delegation_chain(
            token_str=token_b_c, required_capability=cap, expected_audience=charlie.did
        )
        assert verified.issuer_did == bob.did
        assert verified.audience_did == charlie.did
        assert len(verified.proofs) == 1


@pytest.mark.asyncio
async def test_delegation_attenuation_violation(alice, bob, charlie):
    alice_mgr = UCANManager(signing_key=alice._make_okp_key(), issuer_did=alice.did)

    # Alice grants ONLY 'read'
    token_a_b = alice_mgr.issue(
        audience_did=bob.did, capabilities=[UCANCapability("res", "read")], ttl_seconds=3600
    )

    # Bob tries to delegate 'write'
    bob_mgr = UCANManager(signing_key=bob._make_okp_key(), issuer_did=bob.did)
    token_b_c = bob_mgr.delegate(
        parent_token=token_a_b,
        audience_did=charlie.did,
        capabilities=[UCANCapability("res", "write")],
        ttl_seconds=1800,
    )

    async def mock_resolve(did):
        from orchestra.messaging.peer_did import resolve_peer_did

        doc_dict = resolve_peer_did(did)
        from orchestra.identity.did import DIDDocument

        return DIDDocument(
            id=doc_dict["id"],
            verification_methods=doc_dict["verificationMethod"],
            key_agreements=doc_dict["keyAgreement"],
            services=doc_dict["service"],
        )

    # Should fail because 'write' is not in the leaf or the proof chain
    with (
        patch("orchestra.identity.did.DIDManager.resolve", side_effect=mock_resolve),
        pytest.raises(CapabilityDeniedError),
    ):
        await verify_delegation_chain(
            token_str=token_b_c,
            required_capability=UCANCapability("res", "write"),
            expected_audience=charlie.did,
        )
