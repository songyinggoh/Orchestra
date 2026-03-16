---
phase: 03-production-readiness
verified: 2026-03-15T11:22:11Z
scope: Week 1 Critical Security Fixes (REVIEW_SUMMARY.md)
status: passed
score: 4/4 items verified
gaps: []
---

# Week 1 Critical Security Fixes — Verification Report

**Verified:** 2026-03-15T11:22:11Z
**Status:** PASSED
**Score:** 4/4 items verified (source fixes + integration tests)

---

## Items Under Verification

| # | Issue | File(s) | Status |
|---|-------|---------|--------|
| 1 | CRITICAL-4.4 — Dynamic import RCE | `src/orchestra/memory/serialization.py` | VERIFIED |
| 2 | CRITICAL-4.5 — Mutable allowlist | `src/orchestra/core/dynamic.py` | VERIFIED |
| 3 | CRITICAL-3.4 — UCAN narrowing not enforced | `src/orchestra/security/acl.py` | VERIFIED |
| 4 | CRITICAL-4.3 — Agent card revocation never checked | `src/orchestra/identity/agent_identity.py`, `src/orchestra/security/acl.py` | VERIFIED |
| — | Integration tests for all three | `tests/integration/test_security_attack_paths.py` | VERIFIED |

---

## Detailed Findings

### CRITICAL-4.4: Dynamic Import RCE via Deserialization

**File:** `src/orchestra/memory/serialization.py`

**What the fix required (CRITICAL_FIXES.md):**
Replace `importlib.import_module` with a static registry (`SERIALIZATION_REGISTRY`) keyed by
`"{module}.{classname}"`. Untrusted class names must not trigger any import.

**What is in the code:**

- Line 21–36: `SERIALIZATION_REGISTRY` is a `dict[str, Type[Any]]` containing exactly 10 allowed
  Orchestra types (AgentResult, LLMResponse, Message, ModelCost, Send, StreamChunk, TokenUsage,
  ToolCall, ToolCallRecord, ToolResult). All keys follow the `"{module}.{classname}"` pattern.
- Line 78–89: `_object_hook` performs a `SERIALIZATION_REGISTRY.get(lookup_key)` lookup. If the
  key is absent, the function logs a warning and returns `obj.get("data", obj)` — no import is
  attempted. There is no call to `importlib.import_module` anywhere in this file.
- Line 91–99: Only if the class is found in the registry does reconstruction proceed, and only if
  the class is a `BaseModel` (for pydantic) or a dataclass (checked with `is_dataclass`).

**Verdict:** VERIFIED. The vulnerability (arbitrary importlib path resolution) is eliminated.
`importlib` does not appear in `serialization.py` at all.

---

### CRITICAL-4.5: Mutable Allowlist at Runtime

**File:** `src/orchestra/core/dynamic.py`

**What the fix required (CRITICAL_FIXES.md):**
Freeze the allowlist using `types.MappingProxyType` so runtime callers cannot append new paths.

**What is in the code:**

- Line 24–29: `DEFAULT_ALLOWED_PREFIXES` is declared as `tuple[str, ...]` — an immutable type.
  The comment explicitly states "Immutable tuple — prevents runtime poisoning via .append()/.extend()".
- Line 41–43: `SubgraphBuilder.__init__` stores `self._allowed_prefixes` as a `tuple` regardless
  of whether the caller passes a list or tuple. Tuples have no `.append`, `.extend`, or item
  assignment methods; mutation is impossible without reassigning the entire attribute.
- Line 50–52: `resolve_ref` checks the prefix allowlist before calling `importlib.import_module`
  (line 56). An unallowed prefix raises `ImportError` immediately, before any import is attempted.

**Implementation vs. CRITICAL_FIXES.md recommendation:**
The fix document suggested `MappingProxyType` wrapping a `dict`. The actual implementation uses a
`tuple` of prefix strings, which is equally immutable and arguably simpler. The security property
— that no runtime caller can extend the allowlist — is satisfied by both approaches. The tuple
approach is the correct implementation for prefix matching and passes the security requirement.

**Verdict:** VERIFIED. The allowlist is immutable at runtime. Dynamic import is gated by prefix
check before any `importlib` call.

---

### CRITICAL-3.4: UCAN Capability Narrowing Not Enforced

**File:** `src/orchestra/security/acl.py`

**What the fix required (CRITICAL_FIXES.md):**
Add `validate_narrowing(parent_capabilities, child_capabilities)` and call it inside
`ToolACL.is_authorized` when a proof chain is present. The predicate must reject a child capability
that is broader than any parent capability (privilege escalation / widening attempt).

**What is in the code:**

- Lines 18–82: `validate_narrowing(parent_caps, child_caps)` is implemented as a top-level
  function. For every child capability it finds a covering parent using a four-case resource
  check (exact match, explicit `orchestra:tools/*` wildcard, namespace-prefix wildcard ending in
  `/*`, or falling through to `False`). Ability narrowing is also enforced (`parent == "*"` or
  exact match; mismatches return `False`).
- Lines 157–185: `ToolACL.is_authorized` Step 5 uses only two resource-match branches:
  - `cap.resource == f"orchestra:tools/{tool_name}"` (exact)
  - `cap.resource == "orchestra:tools/*"` (explicit wildcard)
  The vulnerable branch `cap.resource == "orchestra:tools"` (bare parent scope) is **absent**.
- Lines 182–184: Step 6 calls `self._validate_proof_chain(ucan)` when `ucan.proofs` is non-empty.
- Lines 187–221: `_validate_proof_chain` parses proof tokens from `ucan.proofs`, builds the full
  delegation chain, and calls `validate_narrowing` on each adjacent parent–child pair. A widening
  attempt raises `CapabilityDeniedError` immediately.
- Lines 285–311: `check_ucan_call_limit` uses the same two-branch resource-match predicate (exact
  or `orchestra:tools/*`), eliminating the same vulnerability there too.

The debug file (`.planning/debug/critical-3-4-ucan-scope-narrowing.md`) confirms all three
vulnerable sites (acl.py, check_ucan_call_limit, ucan.py) were investigated; the resolution
section matches what is in the code.

**Verdict:** VERIFIED. The bare `"orchestra:tools"` implicit-wildcard branch is removed. Narrowing
validation is enforced on the proof chain via `_validate_proof_chain`.

---

### CRITICAL-4.3: Agent Card Revocation Never Checked

**Files:** `src/orchestra/identity/agent_identity.py`, `src/orchestra/security/acl.py`,
`src/orchestra/core/errors.py`

**What the fix required (CRITICAL_FIXES.md):**
Add a revocation list check in `AgentIdentityValidator.validate_with_revocation_check`. The
debug file (`.planning/debug/resolved/critical-4-3-agent-revocation.md`) elaborates: add
`AgentRevokedException`, add `RevocationList`, wire the revocation gate into `AgentCard.verify_jws`,
`AgentCard.verify_raw`, and `ToolACL.is_authorized`.

**What is in the code:**

`src/orchestra/core/errors.py`:
- Lines 219–234: `AgentRevokedException(IdentityError)` is defined with `did` attribute and a
  descriptive message.
- Lines 248–249: `CapabilityDeniedError(AuthorizationError)` is defined.

`src/orchestra/identity/agent_identity.py`:
- Lines 25–64: `RevocationList` class implements `revoke(did)`, `unrevoke(did)`, `is_revoked(did)`,
  `__len__`, and `__contains__`.
- Lines 160–193: `AgentCard.verify_jws` accepts `revocation_list: RevocationList | None = None`.
  Line 183: revocation gate fires before any `jws.deserialize_compact` call.
- Lines 201–234: `AgentCard.verify_raw` accepts the same parameter. Line 221: same gate pattern.
- Lines 237–321: `AgentIdentityValidator.validate_with_revocation` centralises the two-step
  pattern (revocation check → crypto verification). Line 315: gate fires before verification_key
  or public_key_bytes paths are invoked.

`src/orchestra/security/acl.py`:
- Lines 95–185: `ToolACL.is_authorized` accepts `agent_did: str | None = None` and
  `revocation_list: RevocationList | None = None`. Lines 131–135: Step 0 revocation gate raises
  `AgentRevokedException` before any deny-list or UCAN check.

**Verdict:** VERIFIED. All four required components (exception class, RevocationList, card-level
gate, ACL-level gate) are implemented and wired correctly. Default `None` parameters preserve
backward compatibility.

---

### Integration Tests for All Three Fixes

**File:** `tests/integration/test_security_attack_paths.py`

Three integration tests are present, each cross-cutting two or more modules:

| Test | Covers | Assertions |
|------|--------|------------|
| `test_ucan_narrowing_enforcement_integration` | CRITICAL-3.4 | Valid narrowing passes; widening raises `CapabilityDeniedError` with "widening detected" in message |
| `test_agent_revocation_enforcement_integration` | CRITICAL-4.3 | Revoked DID raises `AgentRevokedException`; non-revoked DID is allowed |
| `test_serialization_rce_attack_prevention` | CRITICAL-4.4/4.5 | Malicious `os.system` payload returns raw dict; valid `AgentResult` roundtrip works |

**Unit-level test coverage (supplementary):**

| File | Tests | Covers |
|------|-------|--------|
| `tests/unit/test_memory_serialization.py` | 7 tests including `test_allowlist_blocks_untrusted_module`, `test_serialization_blocks_dangerous_module_paths` (parametrized x6), `test_allowlist_blocks_non_basemodel` | CRITICAL-4.4 |
| `tests/unit/test_agent_identity.py` | 8 new tests (`test_revoked_agent_card_fails_verification_jws`, `test_revoked_agent_card_fails_verification_raw`, `test_non_revoked_agent_card_passes`, `test_revocation_check_skipped_when_list_is_none`, `test_revocation_list_unrevoke`, `test_tool_acl_blocks_revoked_agent`, `test_tool_acl_revocation_skipped_when_no_list`, `test_tool_acl_revocation_skipped_when_no_did` + 7 `AgentIdentityValidator` tests) | CRITICAL-4.3 |
| `tests/unit/test_ucan_acl_integration.py` | `test_broad_ucan_does_not_authorize_specific_tool`, `test_exact_ucan_authorizes_specific_tool`, `test_wildcard_ucan_authorizes_any_tool`, `test_delegation_chain_valid_narrowing_passes`, `test_delegation_chain_widening_raises`, 10 `validate_narrowing` unit tests | CRITICAL-3.4 |

**Verdict:** VERIFIED. The integration test file is substantive (not a stub). All three critical
issues are covered by integration tests with meaningful assertions. Unit-level tests provide
additional depth.

---

## Anti-Pattern Scan

Scanned all four source files and the integration test file for stubs and incomplete
implementations:

| File | Finding |
|------|---------|
| `src/orchestra/memory/serialization.py` | Clean. Registry is populated, fallback path is logged and returns data safely. |
| `src/orchestra/core/dynamic.py` | `importlib.import_module` is present (line 56) but is only reachable after the allowlist prefix check passes — not a vulnerability. The `load_graph_yaml` subgraph branch (line 89–91) is a stub (`pass`) but is unrelated to CRITICAL-4.5. |
| `src/orchestra/security/acl.py` | `_parse_proof` silently returns `None` for opaque JWT strings (documented, intentional). No stubs in the fix logic. |
| `src/orchestra/identity/agent_identity.py` | Thread-safety warning documented in `RevocationList` docstring — acknowledged, not a blocker for the security fix. |
| `tests/integration/test_security_attack_paths.py` | All three tests contain real assertions; no `pass`-body or placeholder tests. |

---

## Summary

All four Week 1 security items from `REVIEW_SUMMARY.md` are fully implemented and tested:

1. **CRITICAL-4.4** (Dynamic import RCE): `serialization.py` uses a static registry; `importlib`
   is absent from that file entirely. VERIFIED.

2. **CRITICAL-4.5** (Mutable allowlist): `dynamic.py` stores prefixes as an immutable `tuple`.
   `resolve_ref` enforces the allowlist before any import. VERIFIED.

3. **CRITICAL-3.4** (UCAN narrowing): `acl.py` removes the implicit parent-scope wildcard, adds
   `validate_narrowing`, and enforces it on the proof chain via `_validate_proof_chain`. VERIFIED.

4. **CRITICAL-4.3** (Agent card revocation): `errors.py` defines `AgentRevokedException`;
   `agent_identity.py` adds `RevocationList` and gates both `verify_jws`/`verify_raw`; `acl.py`
   adds a Step 0 revocation gate in `is_authorized`. VERIFIED.

5. **Integration tests**: `tests/integration/test_security_attack_paths.py` covers all three
   issues with end-to-end assertions. Unit-level coverage is also comprehensive. VERIFIED.

---

_Verified: 2026-03-15T11:22:11Z_
_Verifier: Claude (gsd-verifier)_
