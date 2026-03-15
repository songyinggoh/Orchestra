import pytest
import time
from joserfc.errors import JoseError, BadSignatureError, DecodeError
from orchestra.identity.agent_identity import AgentIdentity
from orchestra.identity.ucan import UCANManager, UCANCapability
from orchestra.core.errors import UCANVerificationError


def test_issue_and_verify_ucan():
    issuer = AgentIdentity.create()
    audience = AgentIdentity.create()

    manager = UCANManager(issuer._make_okp_key(), issuer.did)

    cap = UCANCapability("orchestra:tools/web_search", "tool/invoke")
    token = manager.issue(audience.did, [cap], ttl_seconds=60)

    # Verify
    payload = UCANManager.verify(token, issuer._make_okp_key(), expected_audience=audience.did)
    assert payload["iss"] == issuer.did
    assert payload["aud"] == audience.did
    assert len(payload["att"]) == 1
    assert payload["att"][0]["with"] == "orchestra:tools/web_search"


def test_ucan_expiry():
    issuer = AgentIdentity.create()
    manager = UCANManager(issuer._make_okp_key(), issuer.did)

    # Expired token
    token = manager.issue("did:example:123", [], ttl_seconds=-10)

    with pytest.raises(UCANVerificationError) as exc:
        UCANManager.verify(token, issuer._make_okp_key())
    assert "expired" in str(exc.value)


def test_ucan_audience_mismatch():
    issuer = AgentIdentity.create()
    manager = UCANManager(issuer._make_okp_key(), issuer.did)

    token = manager.issue("did:example:123", [])

    with pytest.raises(UCANVerificationError) as exc:
        UCANManager.verify(token, issuer._make_okp_key(), expected_audience="did:example:wrong")
    assert "Audience mismatch" in str(exc.value)


def test_check_capability():
    """UCANManager.check_capability enforces DD-4 scope-narrowing rules.

    Granted resource must be an exact match OR an explicit wildcard ("ns/*").
    A bare parent scope ("orchestra:tools") does NOT implicitly grant child
    resources — that was the CRITICAL-3.4 privilege-escalation vector.
    """
    manager = UCANManager()

    # ---- exact-match payload (no wildcards) --------------------------------
    exact_payload = {
        "att": [
            {"with": "orchestra:tools", "can": "tool/invoke"},
        ]
    }

    # Exact match on the granted resource itself — still valid
    assert manager.check_capability(exact_payload, UCANCapability("orchestra:tools", "tool/invoke")) is True

    # CRITICAL-3.4: bare parent scope must NOT grant child resources (DD-4)
    assert manager.check_capability(exact_payload, UCANCapability("orchestra:tools/web_search", "tool/invoke")) is False

    # Ability mismatch
    assert manager.check_capability(exact_payload, UCANCapability("orchestra:tools", "delete")) is False

    # Resource mismatch
    assert manager.check_capability(exact_payload, UCANCapability("orchestra:other", "tool/invoke")) is False

    # ---- wildcard payload --------------------------------------------------
    wildcard_payload = {
        "att": [
            {"with": "orchestra:tools/*", "can": "tool/invoke"},
            {"with": "orchestra:secrets/*", "can": "*"},
        ]
    }

    # Explicit wildcard grants child resources
    assert manager.check_capability(wildcard_payload, UCANCapability("orchestra:tools/web_search", "tool/invoke")) is True
    assert manager.check_capability(wildcard_payload, UCANCapability("orchestra:tools/calculator", "tool/invoke")) is True

    # Explicit wildcard ability grant ("*") matches any ability
    assert manager.check_capability(wildcard_payload, UCANCapability("orchestra:secrets/api_key", "read")) is True

    # Wildcard does NOT grant its own namespace root (no exact match)
    assert manager.check_capability(wildcard_payload, UCANCapability("orchestra:tools", "tool/invoke")) is False

    # Cross-namespace isolation
    assert manager.check_capability(wildcard_payload, UCANCapability("orchestra:other/thing", "tool/invoke")) is False


def test_ucan_delegation():
    root = AgentIdentity.create()
    sub_agent = AgentIdentity.create()

    manager_root = UCANManager(root._make_okp_key(), root.did)

    # Root issues to sub_agent with explicit wildcard (DD-4: "orchestra:tools/*")
    root_cap = UCANCapability("orchestra:tools/*", "*")
    token_root = manager_root.issue(sub_agent.did, [root_cap])

    # Sub-agent delegates a narrowed cap to another DID
    manager_sub = UCANManager(sub_agent._make_okp_key(), sub_agent.did)
    narrowed_cap = UCANCapability("orchestra:tools/web_search", "tool/invoke")
    token_delegated = manager_sub.delegate(token_root, "did:example:final", [narrowed_cap])

    # Verify the delegated token (it's signed by sub_agent)
    payload = UCANManager.verify(token_delegated, sub_agent._make_okp_key(), expected_audience="did:example:final")
    assert payload["iss"] == sub_agent.did
    assert payload["prf"][0] == token_root
    assert manager_sub.check_capability(payload, narrowed_cap) is True


# ---------------------------------------------------------------------------
# CRITICAL-3.3 regression tests — narrow exception handling in verify()
# ---------------------------------------------------------------------------

def test_ucan_verification_legitimate_errors_caught():
    """JoseError subclasses from joserfc are caught and re-raised as UCANVerificationError.

    A garbled token string causes joserfc to raise DecodeError (a JoseError subclass).
    The fix must still convert this to UCANVerificationError so callers see a clean
    security-domain error, not a raw library exception.
    """
    issuer = AgentIdentity.create()
    verification_key = issuer._make_okp_key()
    garbled_token = "not.a.valid.jwt.at.all"

    with pytest.raises(UCANVerificationError) as exc_info:
        UCANManager.verify(garbled_token, verification_key)

    assert "JWT verification failed" in str(exc_info.value)
    # Exception chain must be preserved so error reporters can inspect the root cause.
    assert exc_info.value.__cause__ is not None
    assert isinstance(exc_info.value.__cause__, JoseError)


def test_ucan_verification_bad_signature_caught():
    """BadSignatureError (JoseError subclass) from a wrong key is caught correctly."""
    issuer = AgentIdentity.create()
    wrong_issuer = AgentIdentity.create()
    manager = UCANManager(issuer._make_okp_key(), issuer.did)
    token = manager.issue("did:example:audience", [])

    # Verify with a different (wrong) key — joserfc raises BadSignatureError
    with pytest.raises(UCANVerificationError) as exc_info:
        UCANManager.verify(token, wrong_issuer._make_okp_key())

    assert "JWT verification failed" in str(exc_info.value)
    # __cause__ must be BadSignatureError, not None — needed for audit log detail.
    assert isinstance(exc_info.value.__cause__, BadSignatureError)


def test_ucan_verification_programmer_errors_propagate():
    """Programmer errors (TypeError, AttributeError) must NOT be caught.

    Passing None as the token string causes a TypeError deep inside joserfc's
    bytes-conversion. Before the fix this was silently converted to
    UCANVerificationError, masking the real bug. After the fix it propagates
    as-is so the programmer can see the root cause immediately.
    """
    issuer = AgentIdentity.create()
    verification_key = issuer._make_okp_key()

    # None token_str -> TypeError: cannot convert 'NoneType' object to bytes
    with pytest.raises(TypeError):
        UCANManager.verify(None, verification_key)  # type: ignore[arg-type]
