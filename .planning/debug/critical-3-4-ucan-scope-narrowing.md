---
status: resolved
trigger: "Investigate, re-assess, reproduce, and fix CRITICAL-3.4 — No Capability Scope Narrowing Check in acl.py:60-71"
created: 2026-03-15T00:00:00Z
updated: 2026-03-15T00:00:00Z
---

## Current Focus

hypothesis: acl.py lines 60-71 allow cap.resource == "orchestra:tools" to authorize any specific tool, violating DD-4 attenuation; the same pattern is duplicated in check_ucan_call_limit (lines 101-105) and in UCANManager.check_capability in ucan.py (lines 106-108)
test: write pytest showing broad UCAN passes is_authorized for specific tool before fix
expecting: test fails (PASSES when it should FAIL) before fix, passes after fix
next_action: create debug file, write reproduction test, apply fix, update tests

## Symptoms

expected: A UCAN with resource "orchestra:tools" should NOT authorize calls to "orchestra:tools/my_tool" unless it also carries an explicit wildcard "orchestra:tools/*"
actual: cap.resource == "orchestra:tools" is a literal match condition in the resource_match predicate, so any broad-scope UCAN passes ACL checks for any specific tool
errors: no runtime error — silent privilege escalation
reproduction: create UCANToken with UCANCapability("orchestra:tools", "tool/invoke"), call ToolACL.open().is_authorized("specific_tool", ucan=broad_ucan) — returns True
started: introduced with initial UCAN+ACL implementation

## Eliminated

- hypothesis: the code comment says "Resource can be exact 'orchestra:tools/name' or parent 'orchestra:tools'" suggesting this was intentional backward-compat
  evidence: DD-4 rule 2 explicitly states "A UCAN can only narrow — lower max_calls, shorter ttl_seconds, fewer tools"; DD-4 resource format table shows only exact "orchestra:tools/{tool_name}" as the valid resource pointer for tools; no mention of parent-scope passthrough; the backward-compat comment contradicts the design decision
  timestamp: 2026-03-15

## Evidence

- timestamp: 2026-03-15
  checked: acl.py lines 59-71
  found: resource_match predicate has three OR branches: (1) exact match, (2) cap.resource == "orchestra:tools" literal, (3) startswith(cap.resource + "/") prefix match. Branch 2 means any token with resource "orchestra:tools" passes for all tools. Branch 3 is the right general form but only needed for sub-namespaces like "orchestra:tools/my_tool/sub" — for one-level tool names it is equivalent to branch 1.
  implication: CRITICAL-3.4 is confirmed. The literal "orchestra:tools" match is the vulnerability.

- timestamp: 2026-03-15
  checked: acl.py lines 101-105 (check_ucan_call_limit)
  found: identical three-branch predicate — same vulnerability present here too
  implication: the fix must be applied to BOTH predicates in acl.py

- timestamp: 2026-03-15
  checked: ucan.py lines 106-108 (UCANManager.check_capability)
  found: uses only two branches: (1) exact match, (2) required.resource.startswith(granted_resource + "/"). No explicit "orchestra:tools" literal — but the prefix logic means granted_resource="orchestra:tools" DOES match required.resource="orchestra:tools/my_tool" via startswith. This is the SAME problem, expressed differently.
  implication: UCANManager.check_capability also has the vulnerability — but this method is used by delegation chain verification (verify_delegation_chain), not directly by ToolACL. Fixing acl.py is the primary gate; ucan.py is secondary.

- timestamp: 2026-03-15
  checked: DD-4 design decision (WAVE2-DESIGN-DECISIONS.md lines 109-132)
  found: rules state "can only narrow", resource format table specifies "orchestra:tools/{tool_name}" for specific tools. No mention of parent "orchestra:tools" being a valid wildcard. The correct wildcard form is not defined in DD-4 — we need to infer it. The fix task description specifies "orchestra:tools/*" as the explicit wildcard form.
  implication: DD-4 mandates exact-match only (or explicit wildcard). The current code contradicts DD-4 by treating the namespace root as an implicit wildcard.

- timestamp: 2026-03-15
  checked: test_ucan_acl_integration.py — test_deny_list_overrides_ucan and test_allow_all_acl_with_ucan
  found: test_deny_list_overrides_ucan uses UCANCapability("orchestra:tools", "*") and asserts acl.is_authorized("ls", ucan=ucan) is True. This test RELIES on the broad-scope behaviour. After the fix, "orchestra:tools" must not match "ls" — but "orchestra:tools/*" should. This test must be updated to use "orchestra:tools/*".
  implication: one existing test uses the broken behaviour and must be updated alongside the fix.

- timestamp: 2026-03-15
  checked: test_expired_ucan_denies_all — uses UCANCapability("orchestra:tools", "*")
  found: this test checks expiry behaviour only and never reaches the resource_match predicate (expired check fires first). Safe to leave unchanged.
  implication: no change needed for expired test.

## Resolution

root_cause: acl.py lines 62-64 treat cap.resource == "orchestra:tools" as a valid match for any "orchestra:tools/{tool_name}" request. This is equivalent to an implicit wildcard on the namespace root, violating DD-4 rule 2 (capabilities can only narrow). The same pattern is in check_ucan_call_limit (lines 103-105) and in ucan.py UCANManager.check_capability (lines 106-108).

fix: |
  In acl.py: replace the three-branch predicate with a two-branch one that only allows
  (1) exact match: cap.resource == f"orchestra:tools/{tool_name}"
  (2) explicit wildcard: cap.resource == f"orchestra:tools/*"
  Remove the implicit "orchestra:tools" parent-scope branch and the generic startswith prefix branch.
  Apply the same fix to check_ucan_call_limit.
  In ucan.py: replace the prefix-based startswith with explicit wildcard matching for the orchestra:tools namespace.
  Update test_deny_list_overrides_ucan to use "orchestra:tools/*" instead of "orchestra:tools".

verification: pending
files_changed:
  - src/orchestra/security/acl.py
  - src/orchestra/identity/ucan.py
  - tests/unit/test_ucan_acl_integration.py
