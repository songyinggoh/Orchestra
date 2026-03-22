import json
import time

import pytest

from orchestra.identity.types import UCANCapability, UCANToken
from orchestra.security.acl import ToolACL, validate_narrowing


def create_mock_ucan(capabilities, expired=False, ttl=3600):
    return UCANToken(
        raw="mock-jwt",
        issuer_did="did:peer:issuer",
        audience_did="did:peer:audience",
        capabilities=tuple(capabilities),
        not_before=int(time.time()) - 60,
        expires_at=int(time.time()) + (-ttl if expired else ttl),
        nonce="nonce",
        proofs=(),
    )


def test_acl_only_backward_compatible():
    acl = ToolACL.allow_list(["web_search", "calculator"])

    # Existing behavior: True if in allow_list
    assert acl.is_authorized("web_search") is True
    assert acl.is_authorized("calculator") is True
    assert acl.is_authorized("shell") is False


def test_ucan_intersection_allows():
    # ACL allows {web_search, calculator, shell}
    acl = ToolACL.allow_list(["web_search", "calculator", "shell"])

    # UCAN only grants {calculator, shell}
    ucan = create_mock_ucan(
        [
            UCANCapability("orchestra:tools/calculator", "tool/invoke"),
            UCANCapability("orchestra:tools/shell", "tool/invoke"),
        ]
    )

    # Intersection: calculator and shell allowed, web_search denied
    assert acl.is_authorized("calculator", ucan=ucan) is True
    assert acl.is_authorized("shell", ucan=ucan) is True
    assert acl.is_authorized("web_search", ucan=ucan) is False


def test_ucan_not_in_acl_denied():
    # ACL only allows web_search
    acl = ToolACL.allow_list(["web_search"])

    # UCAN grants shell
    ucan = create_mock_ucan(
        [
            UCANCapability("orchestra:tools/shell", "tool/invoke"),
        ]
    )

    # Even if UCAN grants it, ACL must also allow it
    assert acl.is_authorized("shell", ucan=ucan) is False


def test_expired_ucan_denies_all():
    acl = ToolACL.open()  # Allows everything

    # Expired UCAN that grants everything
    ucan = create_mock_ucan([UCANCapability("orchestra:tools", "*")], expired=True)

    # Expired UCAN must deny ALL, even if ACL is open
    assert acl.is_authorized("web_search", ucan=ucan) is False
    assert acl.is_authorized("any_tool", ucan=ucan) is False


def test_deny_list_overrides_ucan():
    # ACL denies 'rm'
    acl = ToolACL.deny_list(["rm"])

    # UCAN grants everything — must use explicit wildcard "orchestra:tools/*"
    # (bare "orchestra:tools" no longer counts as an implicit wildcard per DD-4)
    ucan = create_mock_ucan([UCANCapability("orchestra:tools/*", "*")])

    # 'rm' is denied by ACL, so intersection is False
    assert acl.is_authorized("rm", ucan=ucan) is False
    assert acl.is_authorized("ls", ucan=ucan) is True


# ---------------------------------------------------------------------------
# CRITICAL-3.4 regression tests — DD-4 scope-narrowing enforcement
# ---------------------------------------------------------------------------


def test_broad_ucan_does_not_authorize_specific_tool():
    """Bare parent scope 'orchestra:tools' must NOT authorize a specific tool.

    DD-4 rule 2: capabilities can only narrow.  A UCAN that names the
    namespace root without an explicit wildcard is NOT a grant for child
    resources.  This is the privilege-escalation vector fixed by CRITICAL-3.4.
    """
    acl = ToolACL.open()  # ACL is fully open — only UCAN check matters

    broad_ucan = create_mock_ucan(
        [
            UCANCapability("orchestra:tools", "tool/invoke"),
        ]
    )

    # Must be denied: broad scope is not an implicit wildcard
    assert acl.is_authorized("my_specific_tool", ucan=broad_ucan) is False
    assert acl.is_authorized("web_search", ucan=broad_ucan) is False
    assert acl.is_authorized("calculator", ucan=broad_ucan) is False


def test_exact_ucan_authorizes_specific_tool():
    """Exact resource pointer 'orchestra:tools/{name}' must authorize that tool only."""
    acl = ToolACL.open()

    exact_ucan = create_mock_ucan(
        [
            UCANCapability("orchestra:tools/web_search", "tool/invoke"),
        ]
    )

    assert acl.is_authorized("web_search", ucan=exact_ucan) is True
    # Other tools must still be denied
    assert acl.is_authorized("calculator", ucan=exact_ucan) is False
    assert acl.is_authorized("shell", ucan=exact_ucan) is False


def test_wildcard_ucan_authorizes_any_tool():
    """Explicit wildcard 'orchestra:tools/*' must authorize any tool."""
    acl = ToolACL.open()

    wildcard_ucan = create_mock_ucan(
        [
            UCANCapability("orchestra:tools/*", "tool/invoke"),
        ]
    )

    assert acl.is_authorized("web_search", ucan=wildcard_ucan) is True
    assert acl.is_authorized("calculator", ucan=wildcard_ucan) is True
    assert acl.is_authorized("shell", ucan=wildcard_ucan) is True
    assert acl.is_authorized("any_arbitrary_tool", ucan=wildcard_ucan) is True


def test_max_calls_enforcement():
    acl = ToolACL.open()
    ucan = create_mock_ucan([UCANCapability("orchestra:tools/count", "tool/invoke", max_calls=3)])

    counts = {}

    # First 3 calls succeed
    assert acl.check_ucan_call_limit("count", ucan, counts) is True
    assert acl.check_ucan_call_limit("count", ucan, counts) is True
    assert acl.check_ucan_call_limit("count", ucan, counts) is True

    # 4th call fails
    assert acl.check_ucan_call_limit("count", ucan, counts) is False
    assert counts["count"] == 3


def test_allow_all_acl_with_ucan():
    # ACL allow_all=True
    acl = ToolACL.open()

    # UCAN only grants web_search
    ucan = create_mock_ucan([UCANCapability("orchestra:tools/web_search", "tool/invoke")])

    # UCAN narrows the open ACL
    assert acl.is_authorized("web_search", ucan=ucan) is True
    assert acl.is_authorized("calculator", ucan=ucan) is False


# ---------------------------------------------------------------------------
# CRITICAL-3.4 — validate_narrowing() unit tests (DD-4 delegation chain)
# ---------------------------------------------------------------------------


def _cap(resource: str, ability: str, max_calls: int | None = None) -> UCANCapability:
    return UCANCapability(resource=resource, ability=ability, max_calls=max_calls)


def test_validate_narrowing_exact_match_passes():
    """Child capability exactly mirrors parent — always valid."""
    parent = [_cap("orchestra:tools/web_search", "tool/invoke")]
    child = [_cap("orchestra:tools/web_search", "tool/invoke")]
    assert validate_narrowing(parent, child) is True


def test_validate_narrowing_child_subset_passes():
    """Parent grants wildcard; child grants one specific tool — valid narrowing."""
    parent = [_cap("orchestra:tools/*", "tool/invoke")]
    child = [_cap("orchestra:tools/web_search", "tool/invoke")]
    assert validate_narrowing(parent, child) is True


def test_validate_narrowing_wildcard_parent_grants_specific_child():
    """Parent wildcard ability '*' covers any child ability — valid."""
    parent = [_cap("orchestra:tools/*", "*")]
    child = [_cap("orchestra:tools/calculator", "tool/invoke")]
    assert validate_narrowing(parent, child) is True


def test_validate_narrowing_invalid_widening_rejected():
    """Child claims a broader resource than the parent — should be rejected."""
    # Parent grants only web_search; child claims the whole tools namespace.
    parent = [_cap("orchestra:tools/web_search", "tool/invoke")]
    child = [_cap("orchestra:tools/*", "tool/invoke")]
    assert validate_narrowing(parent, child) is False


def test_validate_narrowing_ability_mismatch_rejected():
    """Child claims ability not covered by parent's specific ability."""
    parent = [_cap("orchestra:tools/web_search", "tool/invoke")]
    child = [_cap("orchestra:tools/web_search", "tool/delete")]
    assert validate_narrowing(parent, child) is False


def test_validate_narrowing_cross_namespace_rejected():
    """Child claims a resource in a completely different namespace — rejected."""
    parent = [_cap("orchestra:tools/web_search", "tool/invoke")]
    child = [_cap("finance:payments/transfer", "payment/send")]
    assert validate_narrowing(parent, child) is False


def test_validate_narrowing_empty_child_always_valid():
    """Empty child capability set is always a valid (trivial) subset."""
    parent = [_cap("orchestra:tools/*", "*")]
    assert validate_narrowing(parent, []) is True


def test_validate_narrowing_empty_parent_rejects_any_child():
    """No parent grants means any child capability is a widening attempt."""
    child = [_cap("orchestra:tools/web_search", "tool/invoke")]
    assert validate_narrowing([], child) is False


def test_validate_narrowing_multi_cap_all_covered():
    """Multiple child capabilities all covered by parent — passes."""
    parent = [_cap("orchestra:tools/*", "tool/invoke")]
    child = [
        _cap("orchestra:tools/web_search", "tool/invoke"),
        _cap("orchestra:tools/calculator", "tool/invoke"),
    ]
    assert validate_narrowing(parent, child) is True


def test_validate_narrowing_multi_cap_one_uncovered_fails():
    """Even one uncovered child capability causes rejection."""
    parent = [_cap("orchestra:tools/web_search", "tool/invoke")]
    child = [
        _cap("orchestra:tools/web_search", "tool/invoke"),
        _cap("orchestra:tools/shell", "tool/invoke"),  # not covered
    ]
    assert validate_narrowing(parent, child) is False


def _make_proof_ucan(capabilities, parent_proofs=()) -> UCANToken:
    """Helper: create a UCANToken whose proofs list contains serialised parent data."""
    return UCANToken(
        raw="mock-jwt",
        issuer_did="did:peer:issuer",
        audience_did="did:peer:audience",
        capabilities=tuple(capabilities),
        not_before=int(time.time()) - 60,
        expires_at=int(time.time()) + 3600,
        nonce="nonce",
        proofs=parent_proofs,
    )


def _serialise_caps(ucan: UCANToken) -> str:
    """Serialise a UCANToken to the JSON format understood by _parse_proof."""
    return json.dumps(
        {
            "issuer_did": ucan.issuer_did,
            "audience_did": ucan.audience_did,
            "capabilities": [
                {"resource": c.resource, "ability": c.ability, "max_calls": c.max_calls}
                for c in ucan.capabilities
            ],
            "not_before": ucan.not_before,
            "expires_at": ucan.expires_at,
            "nonce": ucan.nonce,
            "proofs": list(ucan.proofs),
        }
    )


def test_delegation_chain_valid_narrowing_passes():
    """A UCAN whose proof grants more and the leaf narrows — authorized."""

    acl = ToolACL.open()

    # Root / parent proof: grants all tools
    parent_ucan = _make_proof_ucan([_cap("orchestra:tools/*", "tool/invoke")])
    # Leaf UCAN: narrowed to web_search only, with parent as proof
    leaf_ucan = _make_proof_ucan(
        [_cap("orchestra:tools/web_search", "tool/invoke")],
        parent_proofs=(_serialise_caps(parent_ucan),),
    )

    # Should succeed — no CapabilityDeniedError
    assert acl.is_authorized("web_search", ucan=leaf_ucan) is True


def test_delegation_chain_widening_raises():
    """A UCAN whose leaf claims more than the proof grants raises CapabilityDeniedError."""
    from orchestra.core.errors import CapabilityDeniedError

    acl = ToolACL.open()

    # Parent proof grants only web_search
    parent_ucan = _make_proof_ucan([_cap("orchestra:tools/web_search", "tool/invoke")])
    # Leaf UCAN widens to all tools — privilege escalation attempt
    leaf_ucan = _make_proof_ucan(
        [_cap("orchestra:tools/*", "tool/invoke")],
        parent_proofs=(_serialise_caps(parent_ucan),),
    )

    with pytest.raises(CapabilityDeniedError):
        acl.is_authorized("web_search", ucan=leaf_ucan)


def test_delegation_chain_no_proofs_skips_chain_check():
    """When proofs is empty the chain check is silently skipped (normal path)."""
    acl = ToolACL.open()
    ucan = _make_proof_ucan([_cap("orchestra:tools/web_search", "tool/invoke")])
    assert ucan.proofs == ()
    assert acl.is_authorized("web_search", ucan=ucan) is True
