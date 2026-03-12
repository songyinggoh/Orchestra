---
phase: 04-enterprise-scale
plan: wave2-B4
type: execute
wave: 4
depends_on: [wave2-B3]
files_modified:
  - src/orchestra/security/acl.py
  - tests/unit/test_ucan_acl_integration.py
autonomous: true
requirements: [T-4.7]
must_haves:
  truths:
    - "ToolACL.is_authorized() backward compatible: no UCAN = same behavior as before (DD-4 rule 3)"
    - "Expired UCAN denies ALL tools, even ACL-allowed ones (DD-4 rule 4)"
    - "ACL deny-list takes precedence over UCAN grants (DD-4 rule 1)"
    - "UCAN max_calls tracked and enforced via check_ucan_call_limit() (DD-4)"
    - "Effective capability = min(ACL, UCAN) on every dimension (DD-4 strict intersection)"
  artifacts:
    - path: "src/orchestra/security/acl.py"
      provides: "Extended ToolACL.is_authorized() with optional ucan param, check_ucan_call_limit()"
      min_lines: 10
      contains: "ucan: UCANToken | None = None"
    - path: "tests/unit/test_ucan_acl_integration.py"
      provides: "7 tests covering all ACL/UCAN intersection scenarios"
      min_lines: 80
  key_links:
    - from: "src/orchestra/security/acl.py"
      to: "src/orchestra/identity/types.py"
      via: "from orchestra.identity.types import UCANToken"
      pattern: "from orchestra\\.identity\\.types import"
    - from: "src/orchestra/security/acl.py"
      to: "src/orchestra/identity/delegation.py"
      via: "DelegationChainVerifier.effective_capabilities() called for intersection"
      pattern: "effective_capabilities\\|DelegationChainVerifier"
---

<objective>
Integrate UCAN capability intersection into ToolACL per DD-4 strict intersection rules.

Purpose: ToolACL currently ignores UCAN tokens. This plan adds optional UCAN awareness while maintaining full backward compatibility. When a UCAN is provided, the effective capability is the intersection of what ACL allows AND what UCAN grants. An expired UCAN denies all tools — no fallback to ACL-only. This is the security-critical gate for T-4.7.
Output: Extended acl.py with ucan parameter, 7 integration tests.
</objective>

<execution_context>
@C:/Users/user/.claude/get-shit-done/workflows/execute-plan.md
@C:/Users/user/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/04-enterprise-scale/PLAN.md
@.planning/phases/04-enterprise-scale/WAVE2-DESIGN-DECISIONS.md

<interfaces>
<!-- From src/orchestra/identity/types.py (B1) -->
```python
@dataclass(frozen=True)
class UCANToken:
    raw: str
    issuer_did: str
    audience_did: str
    capabilities: tuple[UCANCapability, ...]
    not_before: int
    expires_at: int
    nonce: str
    proofs: tuple[str, ...]

    @property
    def is_expired(self) -> bool: ...
```

<!-- DD-4 ToolACL integration rules -->
```
Step 1: ACL deny-list always wins (tool in denied_tools or deny_patterns -> False)
Step 2: If ucan is None -> ACL-only mode (backward compatible)
Step 3: If ucan is not None AND ucan.is_expired -> deny ALL (do not fall back to ACL)
Step 4: ACL allows it? (_check_acl_only logic)
Step 5: UCAN grants it? (resource = "orchestra:tools/{tool_name}", ability = "tool/invoke")
Step 6: Both pass -> True, else -> False
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true" id="B4.1" name="Extend ToolACL with UCAN intersection (DD-4)">
  <files>src/orchestra/security/acl.py, tests/unit/test_ucan_acl_integration.py</files>
  <behavior>
    - test_acl_only_backward_compatible: Calling is_authorized(tool_name) with no ucan kwarg behaves identically to before
    - test_ucan_intersection_allows: ACL allows {A,B,C}, UCAN grants {B,C} -> B and C allowed, A denied
    - test_ucan_not_in_acl_denied: UCAN grants tool X but ACL does not allow X -> X denied
    - test_expired_ucan_denies_all: Expired UCAN (is_expired=True) -> all tools denied, even ACL-allowed ones
    - test_deny_list_overrides_ucan: ACL deny-list for tool D -> D denied even if UCAN grants it
    - test_max_calls_enforcement: UCAN max_calls=3 for tool X -> 4th call via check_ucan_call_limit() returns False
    - test_allow_all_acl_with_ucan: ACL allow_all=True + UCAN grants {web_search only} -> only web_search allowed (UCAN narrows)
  </behavior>
  <action>
Read src/orchestra/security/acl.py first to understand the current ToolACL structure (allowed_tools, denied_tools, deny_patterns, allow_all).

EXTEND acl.py — do NOT break backward compatibility:

1. Add import at top of file (after existing imports):
```python
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from orchestra.identity.types import UCANToken
```
(Use TYPE_CHECKING to avoid circular imports — UCANToken type is only needed for type hints.)

2. Factor existing authorization logic into a private method:
```python
def _check_acl_only(self, tool_name: str) -> bool:
    """Original ACL-only authorization logic (now a private method)."""
    # Move existing is_authorized() logic here
```

3. Update is_authorized() signature and logic per DD-4:
```python
def is_authorized(self, tool_name: str, *, ucan: UCANToken | None = None) -> bool:
    """Check if a tool is authorized.

    DD-4 rules (applied in order):
    1. ACL deny-list always wins (deny_patterns and denied_tools).
    2. If ucan is None: ACL-only mode (backward compatible, no behavior change).
    3. If ucan is provided AND expired: DENY ALL tools (do NOT fall back to ACL).
    4. If ucan is provided AND valid: effective = strict intersection(ACL, UCAN).
       Tool must appear in ucan.capabilities with resource=orchestra:tools/{name}
       and ability=tool/invoke.
    """
    # Step 1: deny-list always wins
    import fnmatch
    if tool_name in getattr(self, 'denied_tools', set()):
        return False
    for pattern in getattr(self, 'deny_patterns', []):
        if fnmatch.fnmatch(tool_name, pattern):
            return False

    # Step 2: ACL-only mode
    if ucan is None:
        return self._check_acl_only(tool_name)

    # Step 3: expired UCAN = deny all (DD-4 rule 4)
    if ucan.is_expired:
        return False

    # Step 4: must pass ACL check first
    if not self._check_acl_only(tool_name):
        return False

    # Step 5: must also appear in UCAN grants
    resource = f"orchestra:tools/{tool_name}"
    for cap in ucan.capabilities:
        if cap.resource == resource and cap.ability == "tool/invoke":
            return True

    return False  # Not in UCAN = denied
```

4. Add max_calls tracking method:
```python
def check_ucan_call_limit(
    self,
    tool_name: str,
    ucan: UCANToken,
    call_counts: dict[str, int],
) -> bool:
    """Check and decrement UCAN max_calls for a tool.

    call_counts is a mutable dict on ExecutionContext (not persisted, scoped to single run).
    Returns True if call is within limit (and decrements counter).
    Returns False if max_calls exhausted.
    If max_calls is None (unlimited) for this tool in UCAN, always returns True.
    """
    resource = f"orchestra:tools/{tool_name}"
    for cap in ucan.capabilities:
        if cap.resource == resource and cap.ability == "tool/invoke":
            if cap.max_calls is None:
                return True  # Unlimited
            current = call_counts.get(tool_name, 0)
            if current >= cap.max_calls:
                return False
            call_counts[tool_name] = current + 1
            return True
    return False  # Tool not found in UCAN
```

For tests, construct UCANToken instances directly (frozen dataclass) to test different scenarios without needing a real JWT. Use a future expires_at for valid tokens and a past expires_at for expired ones. Create ToolACL with specific allowed_tools sets.
  </action>
  <verify>
    <automated>pytest tests/unit/test_ucan_acl_integration.py -x -v</automated>
  </verify>
  <done>ToolACL integrates UCAN with strict intersection. Expired UCANs deny all. ACL deny-list overrides UCAN grants. max_calls enforced. All 7 tests pass. Existing ACL tests still pass.</done>
</task>

</tasks>

<verification>
pytest tests/unit/test_ucan_acl_integration.py -v
# Confirm backward compatibility:
pytest tests/unit/ -x -q -k "acl" 2>/dev/null || true
</verification>

<success_criteria>
- All 7 test_ucan_acl_integration.py tests pass
- Existing ToolACL behavior unchanged when ucan=None (backward compatible)
- is_authorized() signature uses keyword-only ucan parameter (no positional arg changes)
- Expired UCAN causes deny-all (verified by test_expired_ucan_denies_all)
- check_ucan_call_limit() returns False on 4th call when max_calls=3
- No circular imports (TYPE_CHECKING guard for UCANToken import)
</success_criteria>

<output>
After completion, create .planning/phases/04-enterprise-scale/04-wave2-B4-SUMMARY.md
</output>
