---
status: resolved
trigger: "CRITICAL-4.3 — No Revocation Check for Agent Cards in AgentIdentity"
created: 2026-03-15T00:00:00Z
updated: 2026-03-15T00:01:00Z
---

## Current Focus

hypothesis: CONFIRMED — AgentCard.verify_jws / verify_raw had no revocation check.
test: Wrote 8 new tests; 7 target the gap directly. All 28 tests pass.
expecting: n/a
next_action: DONE — fix verified, session complete

## Symptoms

expected: A revoked agent's DID should be rejected during card verification and ACL check.
actual: No revocation mechanism exists in AgentCard or ToolACL. discovery.py has a
        `revoke()` method that deletes the registry entry, but that does NOT propagate
        to ToolACL.is_authorized() — an out-of-band caller with a cached card/UCAN is
        not blocked.
errors: No error raised for revoked DID; authorization proceeds normally.
reproduction: Create AgentIdentity, create AgentCard, add DID to RevocationList, call
              card.verify_jws() — returns True with no revocation check performed.
started: Always been absent; CRITICAL-4.3 was identified during Wave 1 security review.

## Eliminated

- hypothesis: SignedDiscoveryProvider.revoke() blocks downstream auth
  evidence: discovery.revoke() only removes the card from the registry dict. It does not
            maintain a revocation set, nor is it consulted by ToolACL.is_authorized().
            A cached AgentCard or UCAN issued before revocation remains valid.
  timestamp: 2026-03-15

## Evidence

- timestamp: 2026-03-15
  checked: src/orchestra/identity/agent_identity.py
  found: AgentCard.verify_jws / verify_raw perform signature + expiry checks only.
         No revocation_list parameter, no RevocationList class anywhere in the file.
  implication: Revocation is a complete gap at the card level.

- timestamp: 2026-03-15
  checked: src/orchestra/security/acl.py ToolACL.is_authorized()
  found: Checks deny_tools, deny_patterns, UCAN expiry, ACL allow list, UCAN capabilities.
         No agent DID revocation check at any point in the chain.
  implication: Even if a RevocationList existed, it is not consulted before granting access.

- timestamp: 2026-03-15
  checked: src/orchestra/identity/discovery.py
  found: revoke(did) exists — deletes the card from the in-memory registry.
         This is a registry-level tombstone, not a blocking revocation check.
  implication: Callers who already hold a signed card bypass this entirely.

- timestamp: 2026-03-15
  checked: src/orchestra/core/errors.py
  found: IdentityError and AuthorizationError hierarchies exist.
         No AgentRevokedException defined anywhere.
  implication: We need to add AgentRevokedException under IdentityError.

## Resolution

root_cause: No RevocationList class existed. AgentCard.verify_jws / verify_raw and
            ToolACL.is_authorized() had no revocation hook. discovery.revoke() only
            removed a card from the registry dict — not a blocking gate for downstream
            callers holding cached cards or UCANs.
fix: (1) Added AgentRevokedException(did) to core/errors.py under IdentityError.
     (2) Added RevocationList class to agent_identity.py (revoke/unrevoke/is_revoked).
     (3) Added revocation_list kwarg to AgentCard.verify_jws and verify_raw —
         raises AgentRevokedException before any crypto work. Default None = backward compat.
     (4) Added agent_did + revocation_list kwargs to ToolACL.is_authorized() —
         revocation gate runs at Step 0, before deny-lists or UCAN checks.
         Default None/None = backward compat.
     (5) Added 8 new tests (7 directly target the gap, 1 tests unrevoke).
verification: 28/28 tests pass — test_agent_identity.py, test_acl.py, test_ucan_acl_integration.py
files_changed:
  - src/orchestra/core/errors.py
  - src/orchestra/identity/agent_identity.py
  - src/orchestra/security/acl.py
  - tests/unit/test_agent_identity.py
