# Wave 1 Research: DIDComm v2 End-to-End Encryption

**Task:** T-4.1 (NATS JetStream + DIDComm E2EE)
**Sources:** DIDComm Messaging Spec v2.1 (identity.foundation/didcomm-messaging/spec/v2.1/), DIDComm.org Book, Phase 4 PLAN.md
**Date:** 2026-03-12

---

## 1. Core DIDComm v2 Concepts

### Message Structure
DIDComm v2 messages are JSON objects with standard headers:
```json
{
  "id": "unique-message-id",
  "type": "https://orchestra.dev/protocols/task/1.0/submit",
  "from": "did:peer:2..sender",
  "to": ["did:peer:2..recipient"],
  "created_time": 1710000000,
  "body": { "task_id": "...", "payload": "..." }
}
```

### Encryption Envelope
Messages are encrypted into JWE (JSON Web Encryption) envelopes before transmission. The plaintext JSON message is never visible on the wire or in storage (NATS JetStream).

### Two Encryption Modes

| Mode | Algorithm | Use Case |
|------|-----------|----------|
| **Authcrypt** | ECDH-1PU+A256KW | Sender-authenticated. Agent-to-agent task messages. Recipient knows who sent it. |
| **Anoncrypt** | ECDH-ES+A256KW | Anonymous sender. Routing envelopes, privacy-sensitive scenarios. |

**Recommendation for Orchestra:** Use authcrypt for all task messages (agents must authenticate). Use anoncrypt for routing/forwarding if multi-hop is needed.

---

## 2. JWE Structure & Wire Format

### JWE General JSON Serialization
DIDComm v2 uses JWE General JSON Serialization (not Compact), which supports **multiple recipients per message** — critical for multi-instance agents behind KEDA.

```json
{
  "protected": "eyJ0eXAiOiJhcHBsaWNhdGlvbi9kaWRjb21tLWVuY3J5cHRlZCtqc29uIiwiYWxnIjoiRUNESC0xUFUrQTI1NktXIiwiZW5jIjoiQTI1NkNCLUhTNTEyIn0",
  "recipients": [
    {
      "header": { "kid": "did:peer:2..recipient#key-1" },
      "encrypted_key": "base64url..."
    }
  ],
  "iv": "base64url...",
  "ciphertext": "base64url...",
  "tag": "base64url..."
}
```

### Protected Header Fields
- `typ`: `"application/didcomm-encrypted+json"`
- `alg`: Key wrapping algorithm (ECDH-1PU+A256KW or ECDH-ES+A256KW)
- `enc`: Content encryption (A256CBC-HS512 — spec-required)
- `skid`: Sender key ID (authcrypt only)
- `apu`: Agreement PartyUInfo (sender key ID, base64url)
- `apv`: Agreement PartyVInfo — **sorted hash of all recipient key IDs** (prevents key substitution attacks)

---

## 3. Key Agreement & Algorithms

### Required Algorithms
| Component | Algorithm | Notes |
|-----------|-----------|-------|
| Key type | X25519 | Exclusively. Ed25519 for signing only. |
| Key agreement (authcrypt) | ECDH-1PU | Authenticated key agreement |
| Key agreement (anoncrypt) | ECDH-ES | Ephemeral-static ECDH |
| Key wrapping | A256KW | AES-256 Key Wrap |
| Content encryption | A256CBC-HS512 | Spec-required, 512-bit key |

### Key Agreement Flow (Authcrypt)
1. Sender generates ephemeral X25519 key pair
2. ECDH between ephemeral private + recipient public → Ze
3. ECDH between sender static private + recipient public → Zs
4. Concatenate Ze || Zs → input to KDF
5. KDF derives CEK wrapping key
6. Wrap CEK with A256KW
7. Encrypt message body with CEK using A256CBC-HS512

### `apv` Computation (Security-Critical)
```python
import hashlib, base64

def compute_apv(recipient_kids: list[str]) -> str:
    """Sorted hash of recipient key IDs — prevents key substitution."""
    sorted_kids = sorted(recipient_kids)
    combined = ".".join(sorted_kids)
    digest = hashlib.sha256(combined.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
```

---

## 4. DID Method: `did:peer:2`

### Why `did:peer:2`
- No external infrastructure (no blockchain, no registry)
- Self-contained: DID document encoded in the DID itself
- Supports multiple keys (encryption + signing)
- Ideal for closed agent networks like Orchestra

### DID Format
```
did:peer:2.Ez6LSbysY2xFMRpGMhb7tFTLMpeuPR84h5GBaoLfVcG..Vz6MkqRYqQiSgvZQdnBytw86Qbs2ZWUkGv22od935YF6..
```
Prefix meanings:
- `E` → X25519 key agreement key (for encryption)
- `V` → Ed25519 verification key (for signing)

### Python Implementation
```python
from peerdid import create_peer_did_numalgo_2
from peerdid.keys import X25519KeyAgreement, Ed25519Verification

# Create agent DID with encryption + signing keys
encryption_key = X25519KeyAgreement.from_secret(secret_bytes)
signing_key = Ed25519Verification.from_secret(secret_bytes)

agent_did = create_peer_did_numalgo_2(
    encryption_keys=[encryption_key],
    signing_keys=[signing_key],
    service=None  # No service endpoint — NATS handles routing
)
```

---

## 5. Python Library Recommendations

### Primary Stack

| Library | Version | Role |
|---------|---------|------|
| `didcomm-python` | >=0.3.1 | Pack/unpack engine (spec-compliant authcrypt/anoncrypt) |
| `peerdid` | >=0.5.2 | DID creation and resolution for did:peer:2 |
| `joserfc` | >=1.0 | JWK management, UCAN JWT operations (T-4.7) |

### Why `didcomm-python` over raw `joserfc`
PLAN.md specifies `joserfc>=1.0`, but joserfc **lacks native ECDH-1PU support**. The `didcomm-python` library:
- Implements full DIDComm v2 pack/unpack with spec compliance
- Handles ECDH-1PU key agreement natively
- Manages recipient key resolution via DID resolver interface
- Provides both authcrypt and anoncrypt modes

**Retain `joserfc`** for:
- JWK serialization/deserialization
- UCAN token creation/validation (T-4.7)
- Generic JWS/JWE operations outside DIDComm

### Pack/Unpack API
```python
from didcomm import pack_encrypted, unpack, DIDCommMessage
from didcomm.secrets.secrets_resolver import SecretsResolver
from didcomm.did_doc.did_resolver import DIDResolver

# Pack (encrypt) a message
packed = await pack_encrypted(
    resolvers_config=ResolversConfig(
        secrets_resolver=agent_secrets,
        did_resolver=agent_did_resolver
    ),
    message=DIDCommMessage(
        id="msg-001",
        type="https://orchestra.dev/protocols/task/1.0/submit",
        frm="did:peer:2..sender",
        to=["did:peer:2..recipient"],
        body={"task_id": "t-123", "payload": encrypted_task_data}
    ),
    pack_config=PackEncryptedConfig(
        protect_sender_id=False,  # authcrypt (sender known)
        enc_alg_auth=AuthCryptAlg.A256CBC_HS512_ECDH_1PU_A256KW
    )
)

jwe_string = packed.packed_msg  # This goes to NATS

# Unpack (decrypt) a message
unpacked = await unpack(
    resolvers_config=resolvers,
    packed_msg=jwe_from_nats
)
plaintext = unpacked.message  # Original DIDComm message
```

---

## 6. NATS Integration Pattern

### SecureNatsProvider Design
```python
class SecureNatsProvider:
    """Wraps NATS publish/consume with transparent DIDComm E2EE."""

    def __init__(self, nats_client, agent_did: str,
                 secrets_resolver, did_resolver):
        self.nc = nats_client
        self.agent_did = agent_did
        self.resolvers = ResolversConfig(secrets_resolver, did_resolver)

    async def publish_encrypted(self, subject: str,
                                 recipient_did: str, body: dict):
        """Encrypt with DIDComm authcrypt, publish to NATS."""
        packed = await pack_encrypted(
            resolvers_config=self.resolvers,
            message=DIDCommMessage(
                id=str(uuid4()),
                type="https://orchestra.dev/task/submit",
                frm=self.agent_did,
                to=[recipient_did],
                body=body
            ),
            pack_config=PackEncryptedConfig(
                enc_alg_auth=AuthCryptAlg.A256CBC_HS512_ECDH_1PU_A256KW
            )
        )
        # JetStream stores only opaque JWE ciphertext
        await self.js.publish(subject, packed.packed_msg.encode())

    async def consume_decrypted(self, subject: str):
        """Pull from NATS, transparently decrypt."""
        sub = await self.js.pull_subscribe(subject)
        msgs = await sub.fetch(batch=10, timeout=5)
        for msg in msgs:
            unpacked = await unpack(
                resolvers_config=self.resolvers,
                packed_msg=msg.data.decode()
            )
            yield unpacked.message
            await msg.ack()
```

### Key Property
JetStream stores **only opaque JWE ciphertexts**. Even with full NATS access, an attacker sees only encrypted blobs. This satisfies the T-4.1 done criterion: "NATS store contains only opaque ciphertexts."

---

## 7. Security Requirements (from Spec)

| Requirement | Implementation |
|-------------|---------------|
| Fresh ephemeral key per message | ECDH-1PU generates new ephemeral for each pack() |
| CSPRNG for IVs | Use `os.urandom()` or `secrets` module |
| Curve validation | `didcomm-python` validates key points on curve |
| `apv` from sorted recipients | Prevents key substitution attacks |
| DID consistency | Verify `from` matches `skid`, `to` matches recipient `kid` |
| No key reuse across algorithms | X25519 for encryption only, Ed25519 for signing only |
| Forward secrecy | Ephemeral keys provide per-message forward secrecy |

---

## 8. Implementation Phases

### Phase A: Anoncrypt MVP
- Implement ECDH-ES anoncrypt (simpler, no sender authentication)
- Prove NATS integration works with E2EE
- Validate JWE storage in JetStream is opaque
- Benchmark encryption overhead

### Phase B: Authcrypt with Sender Authentication
- Switch to ECDH-1PU authcrypt
- Add sender DID verification on unpack
- Implement DID resolver for agent registry lookup
- Add `from`/`skid` consistency validation

### Phase C: Production Hardening
- Key rotation (new DID keys, re-announce to registry)
- DID document caching (avoid repeated resolution)
- Bulk encryption optimization for high-throughput subjects
- Key material protection (integrate with T-4.9 HSM tier)

---

## 9. Integration with Other Wave 1 Tasks

| Task | Integration Point |
|------|------------------|
| T-4.1 NATS JetStream | SecureNatsProvider wraps JS publish/consume |
| T-4.2 K8s + gVisor | Agent DIDs created at pod startup, secrets mounted via K8s Secrets |
| T-4.3 Wasm Sandbox | Wasm tools receive pre-decrypted data; no key material in sandbox |

---

## 10. Resolved Decisions

### Library Choice (Gap 1 — RESOLVED)
- **Decision:** Use `joserfc>=1.6` directly. Do NOT add `didcomm-python` (unmaintained, pins attrs<23).
- `joserfc` 1.6+ supports ECDH-1PU via `joserfc.drafts.jwe_ecdh_1pu.register_ecdh_1pu()` at startup
- ECDH-ES (anoncrypt) also supported natively, no registration needed
- Same library reused for T-4.7 UCAN JWT operations
- No `pycryptodome` needed for A256CBC-HS512 content encryption

### Key Distribution (Gap 2 — RESOLVED)
- **Decision:** Use NATS JetStream KV Store (`KV:agent-keys/{agent_type}`)
- One X25519 public key per agent TYPE (not per instance) in Wave 1
- Bootstrapping: `kv.create()` with first-writer-wins (atomic, `KeyWrongLastSequenceError` for races)
- All replicas of same type converge to same public key via `kv.get()` after failed `kv.create()`
- KV entries persist across KEDA scale-to-zero
- T-4.6 upgrade: swap raw JWK value → signed Agent Card (same bucket, same key scheme)
- Security: add NATS NKeys with per-type write ACLs on `agent-keys.*` subject

### Encryption Mode (Gap 2 corollary — RESOLVED)
- **Wave 1:** ECDH-ES (anoncrypt) — unsigned KV discovery makes ECDH-1PU sender auth redundant
- **Wave 2:** Upgrade to ECDH-1PU (authcrypt) alongside T-4.6 Signed Agent Cards
- Not a security regression: ECDH-ES satisfies T-4.1 done criterion (opaque ciphertexts in NATS)

## 11. Remaining Open Questions

1. **Performance:** JWE pack/unpack adds latency per message. Need benchmarks for high-throughput subjects.
2. **Key rotation:** Atomic via `kv.update(key, new_value, last=revision)` (CAS). TTL can auto-expire. But how to handle in-flight messages encrypted with old key during rotation window?
