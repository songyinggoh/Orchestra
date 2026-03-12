---
phase: 04-enterprise-scale
plan: wave2-B2
type: execute
wave: 2
depends_on: [wave2-B1]
files_modified:
  - src/orchestra/identity/agent_identity.py
  - src/orchestra/identity/did_web.py
  - src/orchestra/identity/discovery.py
  - src/orchestra/security/secrets.py
  - src/orchestra/identity/__init__.py
  - tests/unit/test_agent_identity.py
  - tests/unit/test_signed_discovery.py
autonomous: true
requirements: [T-4.6]
must_haves:
  truths:
    - "Gossip poisoning blocked by SignedDiscoveryProvider: unsigned and tampered cards rejected (S3)"
    - "AgentCards carry JWS Compact signatures using EdDSA/Ed25519 (DD-3)"
    - "did:web identities supported for long-lived agents; did:peer:2 for ephemeral agents (DD-7)"
    - "Custom orchestra.messaging.peer_did module used — no peerdid library imported (DD-8, DD-11)"
    - "AgentCard version and expires_at fields present for key rotation (DD-3 overlap window)"
    - "SecretProvider abstraction with InMemorySecretProvider and VaultSecretProvider"
  artifacts:
    - path: "src/orchestra/identity/agent_identity.py"
      provides: "Extended AgentIdentity with did:web support, JWS signing, delegation_context property"
      min_lines: 120
      contains: "sign_jws"
    - path: "src/orchestra/identity/did_web.py"
      provides: "DidWebManager: create did:web DID, build did.json document, resolve"
      min_lines: 60
    - path: "src/orchestra/identity/discovery.py"
      provides: "SignedDiscoveryProvider: register (verifies JWS), lookup, lookup_by_type, revoke"
      min_lines: 80
      contains: "InvalidSignatureError"
    - path: "src/orchestra/security/secrets.py"
      provides: "InMemorySecretProvider, VaultSecretProvider (hvac), both matching SecretProvider protocol"
      min_lines: 60
    - path: "tests/unit/test_agent_identity.py"
      provides: "8 tests: ephemeral identity, JWS sign/verify, tamper detection, versioning, expiry, delegation_context, did:web, backward compat"
    - path: "tests/unit/test_signed_discovery.py"
      provides: "9 tests: valid card accepted, unsigned rejected, tampered rejected, wrong key rejected, max_cards eviction, lookup_by_type, version ordering, expired card rejected, InMemory secrets"
  key_links:
    - from: "src/orchestra/identity/agent_identity.py"
      to: "src/orchestra/messaging/peer_did.py"
      via: "from orchestra.messaging.peer_did import create_peer_did_numalgo_2, resolve_peer_did"
      pattern: "from orchestra\\.messaging\\.peer_did import"
    - from: "src/orchestra/identity/agent_identity.py"
      to: "joserfc.jws"
      via: "from joserfc import jws; from joserfc.jwk import OKPKey"
      pattern: "from joserfc"
    - from: "src/orchestra/identity/discovery.py"
      to: "src/orchestra/core/errors.py"
      via: "from orchestra.core.errors import InvalidSignatureError"
      pattern: "InvalidSignatureError"
---

<objective>
Extend AgentIdentity with JWS signing, did:web support, and create SignedDiscoveryProvider and SecretProvider.

Purpose: Implements T-4.6 gossip poisoning defense (Observable Truth S3). The SignedDiscoveryProvider rejects any Agent Card without a valid cryptographic signature. AgentIdentity gains did:web support for long-lived orchestrator agents. SecretProvider abstraction enables Vault integration without coupling to hvac everywhere.
Output: Extended agent_identity.py, new did_web.py, discovery.py, secrets.py, updated __init__.py. 17 total tests across two test files.
</objective>

<execution_context>
@C:/Users/user/.claude/get-shit-done/workflows/execute-plan.md
@C:/Users/user/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/04-enterprise-scale/PLAN.md
@.planning/phases/04-enterprise-scale/WAVE2-DESIGN-DECISIONS.md

<interfaces>
<!-- From src/orchestra/messaging/peer_did.py (existing Wave 1, DD-11) -->
```python
# CRITICAL: This is the custom module, NOT the peerdid library (DD-8)
# Takes raw bytes directly, returns plain dict (not pydantic model)
from orchestra.messaging.peer_did import create_peer_did_numalgo_2, resolve_peer_did

did = create_peer_did_numalgo_2(
    encryption_keys=[x_pub_raw],   # list[bytes] — raw 32-byte X25519 keys
    signing_keys=[ed_pub_raw],     # list[bytes] — raw 32-byte Ed25519 keys
    service={"type": "DIDCommMessaging", "serviceEndpoint": "nats://..."},
)

doc = resolve_peer_did(did)  # returns plain dict, camelCase fields
# doc["verificationMethod"][0] = X25519 key (index 0)
# doc["verificationMethod"][1] = Ed25519 key (index 1)
# publicKeyMultibase is 'z' + base58(raw_32_bytes) — prefix already stripped by module
raw_bytes = base58.b58decode(vm["publicKeyMultibase"][1:])  # strip 'z', get 32 bytes
```

<!-- DD-3: JWS Compact signing with EdDSA -->
```python
from joserfc import jws
from joserfc.jwk import OKPKey

# Convert cryptography Ed25519 key to joserfc OKPKey:
d_bytes = signing_key.private_bytes_raw()
x_bytes = signing_key.public_key().public_bytes_raw()
okp_key = OKPKey.import_key({
    "kty": "OKP", "crv": "Ed25519",
    "d": base64url_no_padding(d_bytes),
    "x": base64url_no_padding(x_bytes)
})

# Sign: header.payload.signature (JWS Compact)
signature = jws.serialize_compact({"alg": "EdDSA"}, payload_bytes, okp_key)
# Verify:
result = jws.deserialize_compact(signature, verification_okp_key, algorithms=["EdDSA"])
```

<!-- From src/orchestra/identity/types.py (B1) -->
```python
class DelegationContext:
    @classmethod
    def root(cls, did: str, max_depth: int = 3) -> DelegationContext: ...

class UCANCapability: ...
class UCANToken: ...

@runtime_checkable
class SecretProvider(Protocol):
    async def get_secret(self, path: str) -> bytes: ...
    async def put_secret(self, path: str, value: bytes) -> None: ...
    async def delete_secret(self, path: str) -> None: ...
```

<!-- From src/orchestra/core/errors.py (A1) -->
```python
class InvalidSignatureError(IdentityError): ...
class DelegationDepthExceededError(IdentityError): ...
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true" id="B2.1" name="Extend AgentIdentity with did:web and JWS signing">
  <files>src/orchestra/identity/agent_identity.py, src/orchestra/identity/did_web.py, tests/unit/test_agent_identity.py</files>
  <behavior>
    - test_create_ephemeral_identity: AgentIdentity.create() produces valid did:peer:2 (DD-8: uses orchestra.messaging.peer_did)
    - test_agent_card_jws_sign_verify: Card signed with sign_jws(), verified with verify_jws() using OKPKey — returns True
    - test_agent_card_jws_tampered_rejected: Modified card content with original signature returns False from verify_jws()
    - test_agent_card_versioning: AgentCard.version field incremented on rotation
    - test_agent_card_expiry: AgentCard with past expires_at detected by is_expired property
    - test_delegation_context_from_identity: identity.delegation_context returns DelegationContext.root(did)
    - test_did_web_create_and_document: DidWebManager.create_did('orchestrator') returns did:web:... DID string
    - test_backward_compat_sign_raw: Old sign()/verify() methods still work (renamed to sign_raw()/verify_raw())
  </behavior>
  <action>
Read src/orchestra/identity/agent_identity.py first to understand existing structure.

EXTEND agent_identity.py — do NOT break the existing API:

1. Add version and expires_at to AgentCard:
```python
@dataclass
class AgentCard:
    did: str
    name: str
    agent_type: str
    capabilities: list[str] = field(default_factory=list)
    version: int = 1                            # NEW (DD-3): incremented on key rotation
    expires_at: float | None = None             # NEW (DD-3): Unix timestamp; 1h rotation overlap
    nats_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    signature: str | None = None                # JWS Compact Serialization string

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        import time
        return time.time() > self.expires_at

    def to_json(self) -> str:
        """Canonical JSON for signing (excludes signature field)."""
        import json
        d = {k: v for k, v in asdict(self).items() if k != 'signature'}
        return json.dumps(d, sort_keys=True, separators=(',', ':'))
```

2. Add JWS methods to AgentCard or AgentIdentity — prefer on AgentIdentity since it holds the key:
```python
def _make_okp_key(self) -> Any:  # OKPKey
    """Convert cryptography Ed25519 private key to joserfc OKPKey (DD-3)."""
    from joserfc.jwk import OKPKey
    import base64
    def b64u(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).rstrip(b'=').decode()
    d_bytes = self._signing_key.private_bytes_raw()
    x_bytes = self._signing_key.public_key().public_bytes_raw()
    return OKPKey.import_key({"kty": "OKP", "crv": "Ed25519", "d": b64u(d_bytes), "x": b64u(x_bytes)})

def sign_card(self, card: AgentCard) -> AgentCard:
    """Sign an AgentCard with JWS Compact Serialization (DD-3: EdDSA)."""
    from joserfc import jws
    okp = self._make_okp_key()
    payload = card.to_json().encode("utf-8")
    sig = jws.serialize_compact({"alg": "EdDSA"}, payload, okp)
    from dataclasses import replace
    return replace(card, signature=sig)

@staticmethod
def verify_card(card: AgentCard, verification_key: Any) -> bool:
    """Verify AgentCard JWS signature (DD-3). Returns False on any failure."""
    if card.signature is None:
        return False
    from joserfc import jws
    try:
        result = jws.deserialize_compact(card.signature, verification_key, algorithms=["EdDSA"])
        return result.payload == card.to_json().encode("utf-8")
    except Exception:
        return False
```

3. Add delegation_context property to AgentIdentity:
```python
@property
def delegation_context(self) -> Any:  # DelegationContext
    from orchestra.identity.types import DelegationContext
    return DelegationContext.root(self._did, getattr(self, '_max_delegation_depth', 3))
```

4. Rename existing sign()/verify() to sign_raw()/verify_raw() with the old names calling the new names for backward compatibility.

5. Create did_web.py:
```python
class DidWebManager:
    """Manages did:web identities for long-lived agents (DD-7)."""

    def __init__(self, base_url: str) -> None:
        """base_url e.g. 'orchestra.example.com' (no scheme)."""
        self._base_url = base_url.rstrip('/')

    def create_did(self, agent_name: str) -> str:
        """Returns did:web:{base_url}:agents:{agent_name}"""
        return f"did:web:{self._base_url}:agents:{agent_name}"

    def build_did_document(self, did: str, ed_pub_raw: bytes, x_pub_raw: bytes, service_endpoint: str) -> dict:
        """Build the did.json document for HTTP hosting.
        ed_pub_raw: 32-byte raw Ed25519 public key
        x_pub_raw: 32-byte raw X25519 public key
        """
        import base64
        def b64u(b: bytes) -> str:
            return base64.urlsafe_b64encode(b).rstrip(b'=').decode()
        return {
            "@context": ["https://www.w3.org/ns/did/v1"],
            "id": did,
            "verificationMethod": [
                {"id": f"{did}#key-1", "type": "Ed25519VerificationKey2020", "controller": did,
                 "publicKeyMultibase": "z" + _b58encode(ed_pub_raw)},
                {"id": f"{did}#key-2", "type": "X25519KeyAgreementKey2020", "controller": did,
                 "publicKeyMultibase": "z" + _b58encode(x_pub_raw)},
            ],
            "authentication": [f"{did}#key-1"],
            "keyAgreement": [f"{did}#key-2"],
            "service": [{"id": f"{did}#messaging", "type": "DIDCommMessaging",
                         "serviceEndpoint": service_endpoint}],
        }

    async def resolve(self, did: str) -> dict:
        """Resolve did:web by fetching {base_url}/.well-known/did.json or path-based did.json.
        Uses aiohttp or httpx if available, else raises ImportError with instructions.
        """
        # Parse did:web:{domain}:path... -> https://{domain}/path.../did.json
        ...
```

For tests, mock the cryptography keys using cryptography.hazmat.primitives.asymmetric.ed25519.Ed25519PrivateKey.generate().
  </action>
  <verify>
    <automated>pytest tests/unit/test_agent_identity.py -x -v</automated>
  </verify>
  <done>AgentIdentity.sign_card() and verify_card() work with JWS Compact EdDSA. did:web DIDs created correctly. delegation_context property returns root DelegationContext. All 8 tests pass.</done>
</task>

<task type="auto" tdd="true" id="B2.2" name="Create SignedDiscoveryProvider and SecretProvider">
  <files>src/orchestra/identity/discovery.py, src/orchestra/security/secrets.py, src/orchestra/identity/__init__.py, tests/unit/test_signed_discovery.py</files>
  <behavior>
    - test_register_signed_card: Valid JWS-signed AgentCard accepted, register() returns True
    - test_reject_unsigned_card: Card with signature=None rejected, register() returns False
    - test_reject_tampered_card: Card with modified content but original signature returns False
    - test_reject_wrong_key_card: Card signed by different Ed25519 key returns False
    - test_max_cards_per_did: Third card for same DID evicts the oldest (max_cards_per_did=2 default per DD-3)
    - test_lookup_by_type: Multiple agents, lookup_by_type('researcher') returns only researcher cards
    - test_version_ordering: Higher-version card replaces lower-version card
    - test_expired_card_rejected: Card with expires_at in the past rejected at registration
    - test_in_memory_secret_provider: put_secret/get_secret/delete_secret round-trips correctly
  </behavior>
  <action>
Create discovery.py:
```python
from orchestra.core.errors import InvalidSignatureError

class SignedDiscoveryProvider:
    """Agent card registry that only accepts cryptographically signed cards (DD-3).

    Prevents gossip poisoning: any card without a valid Ed25519 JWS signature is rejected.
    Observable Truth S3: Inject unsigned/fake card -> rejected in logs.
    """

    def __init__(self, max_cards_per_did: int = 2) -> None:
        self._cards: dict[str, list[AgentCard]] = {}  # did -> [current, previous]
        self._max_cards = max_cards_per_did

    def _get_verification_key(self, did: str) -> Any:
        """Resolve the Ed25519 verification key for a DID.
        For did:peer:2: use resolve_peer_did() from orchestra.messaging.peer_did
        For did:web: defer to DidWebManager.resolve() (sync approximation for now)
        """

    def register(self, card: AgentCard) -> bool:
        """Verify signature then register. Returns False (not raises) for invalid signature.

        DD-3 rules:
        - card.signature must not be None
        - JWS EdDSA signature must verify against the DID's public key
        - card.expires_at must be None or in the future
        - card.version must be >= current version for this DID
        - Keeps at most max_cards_per_did cards per DID (evict oldest)
        """

    def lookup(self, did: str) -> AgentCard | None:
        """Get highest-version card for a DID."""

    def lookup_by_type(self, agent_type: str) -> list[AgentCard]:
        """Find all agents of a given type (searching all registered DIDs)."""

    def revoke(self, did: str) -> None:
        """Remove all cards for a DID."""

    @property
    def registered_count(self) -> int:
        return sum(len(cards) for cards in self._cards.values())
```

Create secrets.py:
```python
class InMemorySecretProvider:
    """In-memory secret store for testing and local development.
    Implements SecretProvider protocol from identity/types.py.
    """
    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    async def get_secret(self, path: str) -> bytes:
        if path not in self._store:
            raise KeyError(f"Secret not found: {path}")
        return self._store[path]

    async def put_secret(self, path: str, value: bytes) -> None:
        self._store[path] = value

    async def delete_secret(self, path: str) -> None:
        self._store.pop(path, None)


class VaultSecretProvider:
    """HashiCorp Vault KV v2 backend. Requires hvac library.

    Usage: VaultSecretProvider(url="http://vault:8200", token="s.xxx")
    """
    def __init__(self, url: str, token: str, mount_point: str = "secret") -> None:
        try:
            import hvac
            self._client = hvac.Client(url=url, token=token)
        except ImportError:
            raise ImportError("hvac is required for VaultSecretProvider: pip install hvac")
        self._mount = mount_point

    async def get_secret(self, path: str) -> bytes:
        import asyncio
        resp = await asyncio.to_thread(
            self._client.secrets.kv.v2.read_secret_version,
            path=path, mount_point=self._mount
        )
        value = resp["data"]["data"].get("value", "")
        return value.encode() if isinstance(value, str) else value

    async def put_secret(self, path: str, value: bytes) -> None:
        import asyncio
        await asyncio.to_thread(
            self._client.secrets.kv.v2.create_or_update_secret,
            path=path, secret={"value": value.decode()}, mount_point=self._mount
        )

    async def delete_secret(self, path: str) -> None:
        import asyncio
        await asyncio.to_thread(
            self._client.secrets.kv.v2.delete_latest_version_of_secret,
            path=path, mount_point=self._mount
        )
```

Update src/orchestra/identity/__init__.py to export:
```python
from orchestra.identity.agent_identity import AgentIdentity, AgentCard
from orchestra.identity.types import DelegationContext, UCANCapability, UCANToken, SecretProvider
from orchestra.identity.discovery import SignedDiscoveryProvider
from orchestra.identity.did_web import DidWebManager
```
  </action>
  <verify>
    <automated>pytest tests/unit/test_signed_discovery.py -x -v</automated>
  </verify>
  <done>Gossip poisoning blocked: unsigned/tampered/expired cards rejected by SignedDiscoveryProvider. InMemorySecretProvider fully functional. All 9 tests pass.</done>
</task>

</tasks>

<verification>
pytest tests/unit/test_agent_identity.py tests/unit/test_signed_discovery.py -v
python -c "
from orchestra.identity import AgentIdentity, AgentCard, SignedDiscoveryProvider, DelegationContext
print('identity package imports OK')
from orchestra.security.secrets import InMemorySecretProvider
from orchestra.identity.types import SecretProvider
import asyncio
p = InMemorySecretProvider()
asyncio.run(p.put_secret('test', b'value'))
assert asyncio.run(p.get_secret('test')) == b'value'
print('SecretProvider round-trip OK')
"
</verification>

<success_criteria>
- All 8 test_agent_identity.py tests pass
- All 9 test_signed_discovery.py tests pass
- agent_identity.py imports from orchestra.messaging.peer_did (DD-8), NOT from peerdid library
- discovery.py raises InvalidSignatureError for tampered cards
- No 'import peerdid' anywhere in new files
- AgentCard has version and expires_at fields
- identity/__init__.py exports all public types
</success_criteria>

<output>
After completion, create .planning/phases/04-enterprise-scale/04-wave2-B2-SUMMARY.md
</output>
