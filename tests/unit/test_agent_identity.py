import pytest

from orchestra.core.errors import AgentRevokedException
from orchestra.identity.agent_identity import (
    AgentCard,
    AgentIdentity,
    AgentIdentityValidator,
    RevocationList,
)
from orchestra.identity.did_web import DidWebManager


def test_create_ephemeral_identity():
    identity = AgentIdentity.create()
    assert identity.did.startswith("did:peer:2")
    assert identity.signer.own_did == identity.did
    assert identity.delegation_context.current_did == identity.did
    assert identity.delegation_context.depth == 0


def test_agent_card_jws_sign_verify():
    identity = AgentIdentity.create()
    card = identity.create_card("agent-1", "worker", ["web_search"])

    # Sign manually with internal helper to verify
    okp_key = identity._make_okp_key()
    assert card.signature is not None
    assert card.verify_jws(okp_key) is True


def test_agent_card_jws_tampered_rejected():
    identity = AgentIdentity.create()
    card = identity.create_card("agent-1", "worker", ["web_search"])
    _original_signature = card.signature

    # Tamper with content
    card.name = "malicious-agent"
    okp_key = identity._make_okp_key()
    assert card.verify_jws(okp_key) is False


def test_agent_card_versioning():
    identity = AgentIdentity.create()
    card = identity.create_card("agent-1", "worker", ["web_search"])
    assert card.version == 1

    card.version = 2
    card.sign_jws(identity._make_okp_key())
    assert card.version == 2
    assert card.verify_jws(identity._make_okp_key()) is True


def test_agent_card_expiry():
    identity = AgentIdentity.create()
    # Expired card (ttl = -10)
    card = identity.create_card("agent-1", "worker", ["web_search"], ttl=-10)
    assert card.is_expired is True

    # Valid card
    card2 = identity.create_card("agent-1", "worker", ["web_search"], ttl=3600)
    assert card2.is_expired is False


def test_did_web_create_and_document():
    manager = DidWebManager("orchestra.dev")
    did = manager.create_did("worker-1")
    assert did == "did:web:orchestra.dev:agents:worker-1"

    doc = manager.build_did_document(
        did=did,
        ed_pub_bytes=b"ed-pub-32-bytes-length-exactly--",
        x_pub_bytes=b"x-pub-32-bytes-length-exactly---",
        service_endpoint="nats://localhost:4222",
    )
    assert doc["id"] == did
    assert doc["verificationMethod"][0]["publicKeyJwk"]["x"] is not None
    assert doc["service"][0]["serviceEndpoint"] == "nats://localhost:4222"


def test_backward_compat_sign_raw():
    identity = AgentIdentity.create()
    card = AgentCard(did=identity.did, name="old", agent_type="legacy")
    card.sign_raw(identity.signer)
    assert card.signature is not None
    assert card.verify_raw(identity.signer.public_key_bytes) is True


# ---------------------------------------------------------------------------
# CRITICAL-4.3 — Revocation tests
# ---------------------------------------------------------------------------


def test_revoked_agent_card_fails_verification_jws():
    """A DID that is revoked must raise AgentRevokedException on verify_jws,
    regardless of whether the cryptographic signature is valid."""
    identity = AgentIdentity.create()
    card = identity.create_card("compromised-agent", "worker", ["web_search"])
    okp_key = identity._make_okp_key()

    rl = RevocationList()
    rl.revoke(identity.did)

    # Signature is cryptographically valid — but the DID is revoked.
    # The revocation gate must fire before signature verification.
    with pytest.raises(AgentRevokedException) as exc_info:
        card.verify_jws(okp_key, revocation_list=rl)

    assert exc_info.value.did == identity.did


def test_revoked_agent_card_fails_verification_raw():
    """Same gate for the backward-compatible verify_raw path."""
    identity = AgentIdentity.create()
    card = AgentCard(did=identity.did, name="old-compromised", agent_type="legacy")
    card.sign_raw(identity.signer)

    rl = RevocationList()
    rl.revoke(identity.did)

    with pytest.raises(AgentRevokedException):
        card.verify_raw(identity.signer.public_key_bytes, revocation_list=rl)


def test_non_revoked_agent_card_passes():
    """A DID that is NOT in the revocation list must pass verification normally."""
    identity = AgentIdentity.create()
    card = identity.create_card("clean-agent", "worker", ["web_search"])
    okp_key = identity._make_okp_key()

    other_identity = AgentIdentity.create()
    rl = RevocationList()
    rl.revoke(other_identity.did)  # Different DID revoked — should not affect this agent.

    # Must not raise and must return True.
    assert card.verify_jws(okp_key, revocation_list=rl) is True


def test_revocation_check_skipped_when_list_is_none():
    """When revocation_list is None (default), no revocation check is performed.
    This ensures all existing callers are backward compatible."""
    identity = AgentIdentity.create()
    card = identity.create_card("agent-no-rl", "worker", ["web_search"])
    okp_key = identity._make_okp_key()

    # No revocation_list passed — must behave exactly as before this change.
    result = card.verify_jws(okp_key)  # default: revocation_list=None
    assert result is True


def test_revocation_list_unrevoke():
    """Unrevoking a DID removes it from the revocation set."""
    rl = RevocationList()
    did = "did:peer:2:test"
    rl.revoke(did)
    assert rl.is_revoked(did) is True

    rl.unrevoke(did)
    assert rl.is_revoked(did) is False


def test_tool_acl_blocks_revoked_agent():
    """ToolACL.is_authorized must raise AgentRevokedException for a revoked DID
    BEFORE ACL or UCAN checks are applied."""
    from orchestra.core.errors import AgentRevokedException
    from orchestra.security.acl import ToolACL

    identity = AgentIdentity.create()
    rl = RevocationList()
    rl.revoke(identity.did)

    acl = ToolACL.open()  # Allow-all ACL — would normally permit everything.

    with pytest.raises(AgentRevokedException) as exc_info:
        acl.is_authorized(
            "web_search",
            agent_did=identity.did,
            revocation_list=rl,
        )

    assert exc_info.value.did == identity.did


def test_tool_acl_revocation_skipped_when_no_list():
    """ToolACL.is_authorized with no revocation_list does not raise,
    preserving backward compatibility."""
    from orchestra.security.acl import ToolACL

    identity = AgentIdentity.create()
    acl = ToolACL.open()

    # agent_did provided but no revocation_list — must not raise.
    result = acl.is_authorized("web_search", agent_did=identity.did)
    assert result is True


def test_tool_acl_revocation_skipped_when_no_did():
    """ToolACL.is_authorized with no agent_did does not perform revocation check
    even if a RevocationList is provided."""
    from orchestra.security.acl import ToolACL

    rl = RevocationList()
    rl.revoke("did:peer:2:doesnotmatter")

    acl = ToolACL.open()

    # No agent_did — revocation check must be silently skipped.
    result = acl.is_authorized("web_search", revocation_list=rl)
    assert result is True


# ---------------------------------------------------------------------------
# CRITICAL-4.3 — AgentIdentityValidator tests
# ---------------------------------------------------------------------------


def test_validator_valid_unrevoked_agent_passes_jws():
    """AgentIdentityValidator accepts a valid, unrevoked JWS-signed card."""
    identity = AgentIdentity.create()
    card = identity.create_card("clean-agent", "worker", ["web_search"])
    okp_key = identity._make_okp_key()

    rl = RevocationList()  # empty — nothing revoked
    validator = AgentIdentityValidator(revocation_list=rl)

    result = validator.validate_with_revocation(card, verification_key=okp_key)
    assert result is True


def test_validator_revoked_did_raises_before_signature_check():
    """Revoked DID raises AgentRevokedException without running signature verification.

    We verify the 'before signature' ordering by using a card with an
    intentionally bad signature — if signature check ran first it would return
    False, not raise.  The fact that the exception fires proves the revocation
    gate ran first.
    """
    identity = AgentIdentity.create()
    # Create a card but corrupt the signature so crypto verification would fail.
    card = identity.create_card("compromised", "worker", [])
    card.signature = "bad-signature-data"

    rl = RevocationList()
    rl.revoke(identity.did)

    validator = AgentIdentityValidator(revocation_list=rl)
    okp_key = identity._make_okp_key()

    # Must raise AgentRevokedException, NOT return False from a failed sig check.
    with pytest.raises(AgentRevokedException) as exc_info:
        validator.validate_with_revocation(card, verification_key=okp_key)

    assert exc_info.value.did == identity.did


def test_validator_revoked_did_raw_path_raises():
    """Same revocation gate on the verify_raw (Ed25519 bytes) path."""
    identity = AgentIdentity.create()
    card = AgentCard(did=identity.did, name="old-compromised", agent_type="legacy")
    card.sign_raw(identity.signer)

    rl = RevocationList()
    rl.revoke(identity.did)

    validator = AgentIdentityValidator(revocation_list=rl)

    with pytest.raises(AgentRevokedException):
        validator.validate_with_revocation(card, public_key_bytes=identity.signer.public_key_bytes)


def test_validator_no_revocation_list_skips_check():
    """When no revocation list is provided, validation is purely crypto-based."""
    identity = AgentIdentity.create()
    card = identity.create_card("agent-no-rl", "worker", [])
    okp_key = identity._make_okp_key()

    validator = AgentIdentityValidator()  # revocation_list=None by default

    # Must succeed without raising
    result = validator.validate_with_revocation(card, verification_key=okp_key)
    assert result is True


def test_validator_requires_exactly_one_key_type():
    """Passing neither or both key arguments raises ValueError."""
    identity = AgentIdentity.create()
    card = identity.create_card("x", "worker", [])
    okp_key = identity._make_okp_key()

    validator = AgentIdentityValidator()

    # Neither key type
    with pytest.raises(ValueError):
        validator.validate_with_revocation(card)

    # Both key types at once
    with pytest.raises(ValueError):
        validator.validate_with_revocation(
            card,
            verification_key=okp_key,
            public_key_bytes=identity.signer.public_key_bytes,
        )


def test_validator_different_did_not_affected_by_revocation():
    """Revoking one DID must not affect validation of a different agent's card."""
    alice = AgentIdentity.create()
    bob = AgentIdentity.create()

    alice_card = alice.create_card("alice", "worker", [])
    alice_okp = alice._make_okp_key()

    rl = RevocationList()
    rl.revoke(bob.did)  # Bob revoked, not Alice

    validator = AgentIdentityValidator(revocation_list=rl)

    # Alice's card must still validate
    result = validator.validate_with_revocation(alice_card, verification_key=alice_okp)
    assert result is True
