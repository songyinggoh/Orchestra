---
phase: 04-enterprise-scale
plan: wave2-B3
type: execute
wave: 3
depends_on: [wave2-B2]
files_modified:
  - src/orchestra/identity/ucan.py
  - src/orchestra/identity/delegation.py
  - tests/unit/test_ucan_ttls.py
autonomous: true
requirements: [T-4.7]
must_haves:
  truths:
    - "UCAN tokens expire and require refresh per TTL — expired tokens rejected (S7, DD-9)"
    - "Sub-agents receive delegated UCANs as proofs in prf array — delegation chain verifiable"
    - "Tampered or expired tokens raise UCANVerificationError (not silently denied)"
    - "Strict capability attenuation: child cannot escalate beyond parent's grants (DD-4)"
    - "No py-ucan anywhere in codebase — joserfc JWT used directly (DD-9)"
  artifacts:
    - path: "src/orchestra/identity/ucan.py"
      provides: "UCANService: issue(), verify(), delegate() using joserfc JWT (UCAN 0.8.1 format)"
      min_lines: 80
      contains: "from joserfc import jwt"
    - path: "src/orchestra/identity/delegation.py"
      provides: "DelegationChainVerifier: verify_chain(), check_attenuation(), effective_capabilities()"
      min_lines: 60
    - path: "tests/unit/test_ucan_ttls.py"
      provides: "10 tests covering TTL expiry, audience verification, delegation chain, attenuation, ACL intersection"
      min_lines: 120
  key_links:
    - from: "src/orchestra/identity/ucan.py"
      to: "joserfc.jwt"
      via: "from joserfc import jwt; from joserfc.jwk import OKPKey"
      pattern: "from joserfc import jwt"
    - from: "src/orchestra/identity/ucan.py"
      to: "src/orchestra/identity/types.py"
      via: "from orchestra.identity.types import UCANCapability, UCANToken"
      pattern: "from orchestra\\.identity\\.types import"
    - from: "src/orchestra/identity/ucan.py"
      to: "src/orchestra/core/errors.py"
      via: "from orchestra.core.errors import UCANVerificationError"
      pattern: "UCANVerificationError"
---

<objective>
Rewrite UCAN implementation using joserfc JWT directly, replacing the broken py-ucan library.

Purpose: py-ucan 1.0.0 is not functional (no working JWT serialization path, wrong version internally, poetry as runtime dep). This rewrite uses joserfc — already in the codebase from Wave 1 for DIDComm E2EE — to issue and verify UCAN 0.8.1 JWT tokens with short-lived TTLs (1-60 min) and inline proof delegation chains. Runs parallel to A4 since both are Wave 3 but touch different files.
Output: Rewritten ucan.py, new delegation.py, 10 tests passing.
</objective>

<execution_context>
@C:/Users/user/.claude/get-shit-done/workflows/execute-plan.md
@C:/Users/user/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/04-enterprise-scale/PLAN.md
@.planning/phases/04-enterprise-scale/WAVE2-DESIGN-DECISIONS.md

<interfaces>
<!-- DD-9: UCAN 0.8.1 JWT format via joserfc -->
```python
from joserfc import jwt
from joserfc.jwk import OKPKey

# Payload structure (UCAN 0.8.1):
payload = {
    "ucv": "0.8.1",
    "iss": issuer_did,      # did:peer:2... or did:web:...
    "aud": audience_did,
    "nbf": int(time.time()) - 60,   # 1 min clock skew tolerance
    "exp": int(time.time()) + ttl_seconds,
    "att": [{"with": resource_uri, "can": ability, ...}],  # capabilities
    "prf": [],              # list of inline JWT strings (parent tokens for delegation)
    "nnc": secrets.token_hex(8),
}
header = {"alg": "EdDSA", "typ": "JWT", "ucv": "0.8.1"}
token: str = jwt.encode(header, payload, okp_key)  # OKPKey(crv="Ed25519")

# Verification:
result = jwt.decode(token, okp_key, algorithms=["EdDSA"])
claims = result.claims
```

<!-- From src/orchestra/identity/types.py (B1) -->
```python
@dataclass(frozen=True)
class UCANCapability:
    resource: str   # "orchestra:tools/web_search"
    ability: str    # "tool/invoke"
    max_calls: int | None = None

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

<!-- From src/orchestra/core/errors.py (A1) -->
```python
class UCANVerificationError(AuthorizationError): ...
class CapabilityDeniedError(AuthorizationError): ...
```

<!-- DD-4: Attenuation rules -->
```
1. UCAN cannot grant capability not in issuer's own ACL/UCAN
2. UCAN can only narrow: lower max_calls, shorter ttl, fewer tools
3. If no UCAN on ExecutionContext: ACL-only (backward compatible)
4. If UCAN present but expired: DENY ALL (do not fall back to ACL)
Strict intersection: effective = min(ACL, UCAN) on every dimension
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true" id="B3.1" name="Rewrite UCAN with joserfc JWT and delegation chain verification">
  <files>src/orchestra/identity/ucan.py, src/orchestra/identity/delegation.py, tests/unit/test_ucan_ttls.py</files>
  <behavior>
    - test_issue_and_verify: Issue token with 15min TTL, verify() succeeds and returns UCANToken
    - test_expired_token_rejected: Token with ttl_seconds=1, wait 2s (or mock time), verify() raises UCANVerificationError
    - test_wrong_audience_rejected: Verify with wrong expected_audience raises UCANVerificationError
    - test_wrong_key_rejected: Verify with different OKPKey raises UCANVerificationError
    - test_delegate_creates_chain: delegate() returns token whose prf contains parent token string
    - test_attenuation_narrows_caps: Child max_calls=3 <= parent max_calls=5 passes check_attenuation()
    - test_attenuation_rejects_escalation: Child max_calls=10 > parent max_calls=5 fails check_attenuation()
    - test_effective_caps_intersection: ACL={'web_search','code_exec'}, UCAN grants {'web_search','file_read'} -> effective = {'web_search'} only
    - test_expired_ucan_denies_all: expired UCAN present -> effective_capabilities returns [] (deny all, DD-4 rule 4)
    - test_no_ucan_falls_back_to_acl: ucan=None passed to effective_capabilities -> returns all ACL caps (backward compatible)
  </behavior>
  <action>
Read src/orchestra/identity/ucan.py first to understand what needs to be removed (py-ucan calls).

REWRITE ucan.py completely (DD-9: drop py-ucan entirely):

```python
"""UCAN implementation using joserfc JWT directly (DD-9: py-ucan dropped).

UCAN 0.8.1 JWT format. No py-ucan dependency anywhere in this file.
Short-lived TTLs: 1-60 minutes as per PLAN.md T-4.7 requirement.
"""
import secrets
import time
from joserfc import jwt
from joserfc.jwk import OKPKey
from orchestra.identity.types import UCANCapability, UCANToken
from orchestra.core.errors import UCANVerificationError


class UCANService:
    """Issues, verifies, and delegates UCAN tokens using joserfc directly."""

    def __init__(self, signing_key: OKPKey, issuer_did: str) -> None:
        self._key = signing_key
        self._issuer_did = issuer_did

    def issue(
        self,
        audience_did: str,
        capabilities: list[UCANCapability],
        ttl_seconds: int = 900,   # Default 15 min. Range: 60-3600 (1-60 min per spec)
        proofs: list[str] | None = None,
    ) -> str:
        """Issue a UCAN token as a signed JWT.

        Returns the raw JWT string. Store in UCANToken.raw or pass to delegate().
        """
        now = int(time.time())
        payload = {
            "ucv": "0.8.1",
            "iss": self._issuer_did,
            "aud": audience_did,
            "nbf": now - 60,       # 1 min clock skew tolerance
            "exp": now + ttl_seconds,
            "att": [
                {
                    "with": cap.resource,
                    "can": cap.ability,
                    **({"max_calls": cap.max_calls} if cap.max_calls is not None else {}),
                }
                for cap in capabilities
            ],
            "prf": proofs or [],
            "nnc": secrets.token_hex(8),
        }
        header = {"alg": "EdDSA", "typ": "JWT", "ucv": "0.8.1"}
        return jwt.encode(header, payload, self._key)

    @staticmethod
    def verify(
        token: str,
        verification_key: OKPKey,
        expected_audience: str,
    ) -> UCANToken:
        """Verify a UCAN token.

        Raises UCANVerificationError if:
        - Signature invalid
        - Token expired (exp < now)
        - Audience mismatch
        Returns UCANToken on success.
        """
        try:
            result = jwt.decode(token, verification_key, algorithms=["EdDSA"])
        except Exception as exc:
            raise UCANVerificationError(f"Signature verification failed: {exc}") from exc

        claims = result.claims
        now = int(time.time())

        if claims.get("exp", 0) < now:
            raise UCANVerificationError(
                f"Token expired at {claims.get('exp')}, now={now}"
            )
        if claims.get("aud") != expected_audience:
            raise UCANVerificationError(
                f"Audience mismatch: got {claims.get('aud')!r}, expected {expected_audience!r}"
            )

        capabilities = tuple(
            UCANCapability(
                resource=att["with"],
                ability=att["can"],
                max_calls=att.get("max_calls"),
            )
            for att in claims.get("att", [])
        )
        return UCANToken(
            raw=token,
            issuer_did=claims["iss"],
            audience_did=claims["aud"],
            capabilities=capabilities,
            not_before=claims.get("nbf", 0),
            expires_at=claims["exp"],
            nonce=claims.get("nnc", ""),
            proofs=tuple(claims.get("prf", [])),
        )

    def delegate(
        self,
        parent_token: str,
        child_audience: str,
        child_capabilities: list[UCANCapability],
        ttl_seconds: int = 900,
    ) -> str:
        """Delegate a subset of capabilities to a child audience.

        The parent token is included as an inline proof in the child token (DD-4).
        Caller is responsible for ensuring child_capabilities is a subset of parent's.
        (Use DelegationChainVerifier.check_attenuation() to verify before calling.)
        """
        return self.issue(
            audience_did=child_audience,
            capabilities=child_capabilities,
            ttl_seconds=ttl_seconds,
            proofs=[parent_token],
        )
```

Create delegation.py for chain verification and ACL intersection:

```python
"""UCAN delegation chain verification and ACL intersection (DD-4, DD-5)."""
from joserfc.jwk import OKPKey
from orchestra.identity.types import UCANCapability, UCANToken


class DelegationChainVerifier:
    """Verifies UCAN delegation chains and enforces capability attenuation (DD-4)."""

    @staticmethod
    def verify_chain(
        tokens: list[str],
        keys: dict[str, OKPKey],  # did -> OKPKey for each issuer
    ) -> list[UCANToken]:
        """Verify a chain of UCAN tokens.

        Rules:
        - Each token's issuer must be the previous token's audience (or first token is root)
        - Each token's capabilities must be a subset of its proof's capabilities (attenuation)
        - All tokens must be non-expired

        Raises UCANVerificationError on any failure.
        Returns list of parsed UCANToken objects, root-to-leaf order.
        """
        from orchestra.identity.ucan import UCANService
        parsed = []
        for i, token in enumerate(tokens):
            # For each token, find the verification key by decoding header (unverified)
            # to get iss, then look up in keys dict
            import base64, json
            header_b64 = token.split('.')[1]
            # Pad base64
            padding = 4 - len(header_b64) % 4
            payload_json = base64.urlsafe_b64decode(header_b64 + '=' * padding)
            claims = json.loads(payload_json)
            iss = claims.get("iss", "")
            if iss not in keys:
                from orchestra.core.errors import UCANVerificationError
                raise UCANVerificationError(f"No key found for issuer: {iss}")
            # Expected audience: if not first, should be previous token's audience
            expected_aud = parsed[-1].audience_did if parsed else claims.get("aud", "")
            tok = UCANService.verify(token, keys[iss], expected_aud)
            parsed.append(tok)
        return parsed

    @staticmethod
    def check_attenuation(
        parent_caps: list[UCANCapability],
        child_caps: list[UCANCapability],
    ) -> bool:
        """DD-4: Child capabilities must be a subset of parent capabilities.

        For each child capability:
        - resource must exactly match a parent capability's resource
        - ability must exactly match
        - max_calls: child.max_calls <= parent.max_calls (None = unlimited)

        Returns True if valid attenuation, False if child tries to escalate.
        """
        parent_map = {(c.resource, c.ability): c for c in parent_caps}
        for child_cap in child_caps:
            key = (child_cap.resource, child_cap.ability)
            if key not in parent_map:
                return False  # Resource/ability not in parent = escalation
            parent_cap = parent_map[key]
            if child_cap.max_calls is not None and parent_cap.max_calls is not None:
                if child_cap.max_calls > parent_cap.max_calls:
                    return False  # Child requests more calls than parent allows
        return True

    @staticmethod
    def effective_capabilities(
        acl_tools: set[str],           # Tool names from ToolACL (e.g., {"web_search", "code_exec"})
        ucan_token: UCANToken | None,  # UCAN token (None = ACL-only mode)
    ) -> list[UCANCapability]:
        """DD-4 strict intersection of ACL and UCAN.

        Rules:
        1. ucan_token is None: return ACL-only capabilities as UCANCapability list
        2. ucan_token is expired: return [] (deny-all, DD-4 rule 4)
        3. ucan_token is valid: return intersection(ACL, UCAN) — only tools in BOTH
        """
        if ucan_token is None:
            # Backward compatible: ACL-only, wrap as UCANCapability
            return [
                UCANCapability(f"orchestra:tools/{t}", "tool/invoke")
                for t in acl_tools
            ]
        if ucan_token.is_expired:
            return []  # DD-4 rule 4: expired UCAN = deny all, no ACL fallback
        # Strict intersection
        result = []
        for cap in ucan_token.capabilities:
            if cap.ability == "tool/invoke":
                tool_name = cap.resource.removeprefix("orchestra:tools/")
                if tool_name in acl_tools:
                    result.append(cap)
        return result
```

For the expiry test, use a mock or monkeypatch on time.time() rather than sleeping — use pytest's monkeypatch or pass a future timestamp directly in the UCANToken constructor.
  </action>
  <verify>
    <automated>pytest tests/unit/test_ucan_ttls.py -x -v</automated>
  </verify>
  <done>UCAN tokens issued via joserfc, expire correctly, delegation chains with inline proofs work, attenuation enforced, ACL intersection correct. All 10 tests pass. No py-ucan import anywhere.</done>
</task>

</tasks>

<verification>
pytest tests/unit/test_ucan_ttls.py -v
# Confirm no py-ucan import:
python -c "
import pathlib
src = pathlib.Path('src/orchestra/identity/ucan.py').read_text()
assert 'import ucan' not in src and 'from ucan' not in src, 'FAIL: py-ucan still imported'
assert 'from joserfc import jwt' in src, 'FAIL: joserfc not used'
print('DD-9 compliance: OK')
"
</verification>

<success_criteria>
- All 10 test_ucan_ttls.py tests pass
- ucan.py imports from joserfc (not from ucan/py-ucan)
- UCANVerificationError raised for expired, wrong audience, wrong key
- delegation.py check_attenuation() correctly blocks escalation
- effective_capabilities() with expired UCAN returns [] (deny-all, not ACL fallback)
- effective_capabilities() with None UCAN returns ACL-wrapped capabilities
</success_criteria>

<output>
After completion, create .planning/phases/04-enterprise-scale/04-wave2-B3-SUMMARY.md
</output>
