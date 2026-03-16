# Wave 2 Combined Research: Identity, Security, Interoperability & Observability

> **Research Date:** 2026-03-12 to 2026-03-13
> **Scope:** T-4.4 through T-4.7 — CostAwareRouter, PersistentBudget, AgentIdentity, UCAN
> **Sources:** 6 research agents (identity, agent_cards, otel, gossip, did_ucan, security_otel_deep_dive)
> **Status:** Synthesized, deduplicated, ready for implementation planning

---

## Table of Contents

1. [Part 1: Identity & Encryption](#part-1-identity--encryption)
   - [1.1 W3C DID Core v1.1 (Syntax, Data Model, Resolution)](#11-w3c-did-core-v11-syntax-data-model-resolution)
   - [1.2 DID Methods: did:peer and did:web](#12-did-methods-didpeer-and-didweb)
   - [1.3 DIDComm Messaging v2.1](#13-didcomm-messaging-v21)
   - [1.4 Ed25519 with Python cryptography Library](#14-ed25519-with-python-cryptography-library)
   - [1.5 Ed25519 Algorithm Security Properties](#15-ed25519-algorithm-security-properties)
   - [1.6 joserfc JWS with Ed25519](#16-joserfc-jws-with-ed25519)
   - [1.7 peerdid Python Library](#17-peerdid-python-library)

2. [Part 2: Agent Interoperability](#part-2-agent-interoperability)
   - [2.1 A2A Protocol & Agent Cards](#21-a2a-protocol--agent-cards)
   - [2.2 Google Cloud Agentic AI Design Patterns](#22-google-cloud-agentic-ai-design-patterns)
   - [2.3 UCAN Specification (v0.10 / v1.0)](#23-ucan-specification-v010--v10)
   - [2.4 py-ucan Python Library](#24-py-ucan-python-library)
   - [2.5 UCAN vs zcap-ld](#25-ucan-vs-zcap-ld)
   - [2.6 Awesome Agentic Patterns](#26-awesome-agentic-patterns)

3. [Part 3: Distributed Security](#part-3-distributed-security)
   - [3.1 AgentPoison & LLM Memory Attacks](#31-agentpoison--llm-memory-attacks)
   - [3.2 Gossip Protocol Security](#32-gossip-protocol-security)
   - [3.3 HashiCorp Vault with hvac](#33-hashicorp-vault-with-hvac)
   - [3.4 SecretProvider Abstraction Pattern](#34-secretprovider-abstraction-pattern)

4. [Part 4: Observability & Context Propagation](#part-4-observability--context-propagation)
   - [4.1 OpenTelemetry Baggage Specification](#41-opentelemetry-baggage-specification)
   - [4.2 W3C Baggage Header Format](#42-w3c-baggage-header-format)
   - [4.3 OTel Python Baggage API](#43-otel-python-baggage-api)
   - [4.4 Baggage Over Non-HTTP Transports (NATS)](#44-baggage-over-non-http-transports-nats)
   - [4.5 Baggage Security Analysis](#45-baggage-security-analysis)
   - [4.6 Hybrid Baggage + UCAN Strategy](#46-hybrid-baggage--ucan-strategy)

5. [Part 5: Implications for Orchestra Wave 2](#part-5-implications-for-orchestra-wave-2)
   - [5.1 T-4.4: CostAwareRouter + ProviderFailover](#51-t-44-costawarerouter--providerfailover)
   - [5.2 T-4.5: PersistentBudget](#52-t-45-persistentbudget)
   - [5.3 T-4.6: AgentIdentity + SignedAgentCards](#53-t-46-agentidentity--signedagentcards)
   - [5.4 T-4.7: UCAN + Short-Lived Capabilities](#54-t-47-ucan--short-lived-capabilities)

6. [References](#references)

---

## Part 1: Identity & Encryption

### 1.1 W3C DID Core v1.1 (Syntax, Data Model, Resolution)

**Status:** W3C Candidate Recommendation Snapshot (March 5, 2026). Layers on W3C Controlled Identifiers v1.0 (May 2025 Recommendation).

#### DID Syntax

DIDs follow the format `did:<method>:<method-specific-id>`:

```abnf
did = "did:" method-name ":" method-specific-id
method-name = 1*method-char
method-char = %x61-7A / DIGIT  ; a-z / 0-9
method-specific-id = *( *idchar ":" ) 1*idchar
idchar = ALPHA / DIGIT / "." / "-" / "_" / pct-encoded
```

Examples:
- `did:peer:2.Ez6LSqPZfn...Vz6MkrCD1c...`
- `did:web:example.com`
- `did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK`

#### DID Document Core Properties

| Property | Purpose |
|---|---|
| `id` | The DID itself |
| `controller` | DID(s) authorized to change the Document |
| `verificationMethod` | Array of cryptographic keys (type + encoding) |
| `authentication` | Keys for authenticating the DID subject — used for JWS signing |
| `assertionMethod` | Keys for making assertions / issuing credentials |
| `keyAgreement` | Keys for encrypted communication (X25519, JWE) |
| `capabilityInvocation` | Keys for invoking capabilities — used for UCAN invocation validation |
| `capabilityDelegation` | Keys for delegating capabilities — used for UCAN delegation chains |
| `service` | Service endpoints for interacting with the DID subject |

**Verification Method structure (Multikey type, preferred in DID v1.1):**

```json
{
  "id": "did:peer:2.Ez6...#key-1",
  "type": "Multikey",
  "controller": "did:peer:2.Ez6...",
  "publicKeyMultibase": "z6MkrCD1csqtgdj8sjrsu8jxcbeyP6m7LiK7Z3pqBN2Rze7b"
}
```

Key encoding options:
- `publicKeyMultibase` — multibase-encoded key bytes (preferred for `Multikey` type)
- `publicKeyJwk` — JSON Web Key representation (preferred for `JsonWebKey2020` type)

#### Verification Method Types

| Type | Curve | Purpose | Key Encoding |
|------|-------|---------|-------------|
| `Ed25519VerificationKey2020` | Ed25519 | Signing, authentication | `publicKeyMultibase` |
| `X25519KeyAgreementKey2020` | X25519 | Key agreement (JWE) | `publicKeyMultibase` |
| `JsonWebKey2020` | Any (via JWK) | General purpose | `publicKeyJwk` |
| `Multikey` (DID v1.1) | Any | Unified, preferred in v1.1 | `publicKeyMultibase` |

**Key encoding for `publicKeyMultibase`:**
- `z` prefix = base58btc multibase encoding
- Following bytes: multicodec prefix identifying key type:
  - `0xed01` = Ed25519 public key
  - `0xec01` = X25519 public key
- Remaining 32 bytes = raw public key

#### DID Resolution Process

1. Parse the DID to extract the method name
2. Look up the appropriate method resolver
3. Execute method-specific resolution:
   - `did:peer` — decode the DID string itself (self-contained, no network)
   - `did:web` — fetch `did.json` via HTTPS
   - `did:key` — derive from the public key encoded in the DID
4. Return: `{ didDocument, didDocumentMetadata, didResolutionMetadata }`

#### Changes from v1.0 to v1.1

| Change | Detail |
|--------|--------|
| Media type | Unified to `application/did` (IANA-registered) |
| Controlled Identifiers | Explicitly layers on W3C Controlled Identifiers v1.0 (May 2025) |
| Resolution | Factored out to DID Resolution v0.3 (Feb 2026 separate spec) |
| JSON-LD Context | New URL: `https://www.w3.org/ns/did/v1.1` |
| AI agent identity | Acknowledged as use case: autonomous agents proving identity without human intervention |

---

### 1.2 DID Methods: did:peer and did:web

#### did:peer Method

**Characteristics:**
- **Self-certifying:** DID value derived from inception key material — only the key holder could have created it
- **No network needed for resolution:** Purely local; decode the DID string
- **Pairwise:** Typically used between two parties; not publicly resolvable
- **Immutable:** Peer DIDs cannot be updated; use DID Rotation instead

**Numalgo variants:**

| Variant | Description | Use Case |
|---------|-------------|----------|
| **numalgo 0** | Single keypair. DID = multibase-encoded public key. Equivalent to `did:key`. | Simple agent identity |
| **numalgo 1** | SHA-256 hash of genesis DID document. Stored variant. | Complex documents, rarely used |
| **numalgo 2** | Multiple keys + services encoded directly in DID string. Purpose-coded prefixes. | **Recommended for Orchestra** — supports signing + encryption keys + service endpoints |
| **numalgo 3** | SHA-256 hash of a numalgo 2 DID. Short form. | Compact references |

**Numalgo 2 DID string construction:**

```
did:peer:2
  .Ez6LSqPZfn...     <-- E = keyAgreement (X25519 encryption key)
  .Vz6MkrCD1c...     <-- V = authentication (Ed25519 signing key)
  .SeyJ0IjoiZ...     <-- S = service (base64url-encoded JSON)
```

**Purpose codes:**

| Prefix | Verification Relationship |
|--------|--------------------------|
| `A` | assertionMethod |
| `E` | keyAgreement (encryption) |
| `V` | authentication (verification/signing) |
| `I` | capabilityInvocation |
| `D` | capabilityDelegation |
| `S` | service |

**Service encoding in numalgo 2:** JSON abbreviated (`type`→`t`, `serviceEndpoint`→`s`, `routingKeys`→`r`, `accept`→`a`), then base64url-encoded (no padding), prefixed with `.S`.

**Key rotation for did:peer:** Since keys are embedded in the DID string, rotation requires issuing a new DID entirely via DIDComm's DID Rotation protocol:
1. Generate new DID
2. Send rotation message signed with old DID
3. Counterparty verifies and updates their records
4. Old DID is retired

**[OPEN QUESTION]:** For long-lived agent identities that need periodic key rotation, options are: (a) accept DID churn, (b) use `did:web` for agents needing rotation, (c) wait for numalgo 1 (rolling updates via microledger).

**Caching strategy:**
- `did:peer`: Self-contained and immutable. Resolution is local lookup. Store once, resolve forever.
- `did:web`: Use HTTP `Cache-Control` headers. Recommended `max-age=3600`. For agent systems, in-memory TTL of 5–15 min is reasonable.

#### did:web Method

**Resolution:**

| DID | Resolved URL |
|-----|-------------|
| `did:web:example.com` | `https://example.com/.well-known/did.json` |
| `did:web:example.com:users:alice` | `https://example.com/users/alice/did.json` |

**CRUD operations:**

| Operation | Mechanism |
|-----------|-----------|
| Create | Generate keypair, write `did.json` to web server |
| Read | HTTP GET to resolved URL |
| Update | Replace `did.json` — **supports key rotation** (unlike `did:peer`) |
| Deactivate | Remove `did.json` or return HTTP 410 |

**Security considerations:**
- DNS attacks can intercept resolution; use DNS over HTTPS (RFC 8484)
- No authentication/authorization mechanism specified by the method; implementations must protect `did.json`
- HTTPS provides transport security but not content integrity
- `did:webs` (with `s`) is a proposed successor adding KERI-based event log verification

#### Comparison: did:peer vs did:web

| Feature | did:peer | did:web |
|---------|----------|--------|
| Network required | No (self-contained) | Yes (HTTPS fetch) |
| Self-certifying | Yes | No (DNS-dependent) |
| Key rotation | No (DID rotation only) | Yes (update did.json) |
| Public resolution | No (pairwise only) | Yes (anyone can resolve) |
| Hosting required | No | Yes (web server) |
| Trust model | Peer-to-peer | DNS/TLS PKI |
| Offline capability | Full | None |
| Orchestra use | Agent-to-agent identity (T-4.1, T-4.6) | Public agent discovery (T-4.6 well-known) |

---

### 1.3 DIDComm Messaging v2.1

#### Message Structure

DIDComm v2.1 messages follow JWM (JSON Web Messages) format. Media type `application/didcomm-plain+json`:

```json
{
  "id": "1234567890",
  "type": "https://didcomm.org/basicmessage/2.0/message",
  "from": "did:peer:2.Ez6LS...sender",
  "to": ["did:peer:2.Ez6LS...recipient"],
  "created_time": 1516269022,
  "expires_time": 1516385931,
  "body": { "content": "Hello, agent!" },
  "attachments": []
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique message identifier per sender |
| `type` | Yes | URI identifying message category and body schema |
| `from` | Conditional | Sender DID. Required for authcrypt, optional for anoncrypt |
| `to` | No | Array of recipient DIDs |
| `expires_time` | No | UTC epoch seconds when message expires (TTL mechanism) |
| `thid` | No | Thread identifier |
| `pthid` | No | Parent thread identifier |

#### Encryption: JWE

DIDComm encrypted messages use JWE in **General JSON Serialization** format. Media type `application/didcomm-encrypted+json`.

**Authcrypt (Authenticated Sender Encryption):**
- Algorithm: ECDH-1PU + A256KW (key wrapping)
- Content Encryption: A256CBC-HS512 (mandatory per ECDH-1PU draft4)
- Purpose: Encrypts to recipients AND authenticates the sender (repudiable externally, authenticated to recipients)

**JWE Protected Headers (authcrypt):**

```json
{
  "typ": "application/didcomm-encrypted+json",
  "alg": "ECDH-1PU+A256KW",
  "enc": "A256CBC-HS512",
  "epk": { "kty": "OKP", "crv": "X25519", "x": "<base64url>" },
  "apu": "<base64url of sender kid>",
  "apv": "<base64url of SHA-256 hash of sorted, concatenated recipient kids>",
  "skid": "<sender key ID referencing keyAgreement in sender DID doc>"
}
```

**Anoncrypt (Anonymous Sender Encryption):**
- Algorithm: ECDH-ES + A256KW
- Content Encryption: A256GCM (recommended) or XC20P (optional)
- No `apu`, `from`, or `skid` headers

#### Signing: JWS

DIDComm signed messages use JWS for non-repudiation. Media type `application/didcomm-signed+json`.

- "Sign first, then encrypt" when combining
- `kid` header MUST reference a key in signer's DID Document `authentication` section
- Supported algorithms: **EdDSA (Ed25519)**, ES256, ES256K

#### Key Agreement Curves

| Curve | Support Level |
|-------|--------------|
| X25519 | Mandatory |
| P-384 | Mandatory |
| P-256 | Mandatory |
| P-521 | Optional |

#### Media Types Summary

| Message Form | Media Type | Extension |
|---|---|---|
| Plaintext | `application/didcomm-plain+json` | `.dcpm` |
| Signed | `application/didcomm-signed+json` | `.dcsm` |
| Encrypted | `application/didcomm-encrypted+json` | `.dcem` |

**Note on joserfc:** joserfc's ECDH-1PU support is draft-only and requires manual registration (`from joserfc.drafts import register_ecdh_1pu_algorithms`). For production DIDComm authcrypt, use the `didcomm-python` library (SICPA-DLab).

---

### 1.4 Ed25519 with Python cryptography Library

#### Key Generation

```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

# Generate a new key pair
private_key = Ed25519PrivateKey.generate()
public_key = private_key.public_key()
```

#### Signing and Verification

```python
# Sign data — returns a 64-byte signature
# CRITICAL: Do NOT pre-hash the data. Ed25519 uses its own internal SHA-512.
signature = private_key.sign(b"my authenticated message")

# Verify — raises InvalidSignature on failure, returns None on success
from cryptography.exceptions import InvalidSignature

try:
    public_key.verify(signature, b"my authenticated message")
except InvalidSignature:
    pass  # Invalid
```

**API signatures:**

```python
Ed25519PrivateKey.sign(data: bytes) -> bytes
# Returns 64-byte deterministic signature.

Ed25519PublicKey.verify(signature: bytes, data: bytes) -> None
# NOTE: signature comes FIRST, data comes SECOND.
```

#### Key Serialization

```python
from cryptography.hazmat.primitives import serialization

# Raw format (32 bytes — just the seed)
raw_private = private_key.private_bytes_raw()  # convenience method, cryptography v40+
raw_public  = public_key.public_bytes_raw()    # convenience method, cryptography v40+

# PEM (PKCS#8 envelope)
pem_private = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption()
)

# PEM (SubjectPublicKeyInfo)
pem_public = public_key.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo
)
```

**Serialization format matrix:**

| Encoding | Private Format | Public Format |
|----------|---------------|---------------|
| `Raw` | `Raw` | `Raw` |
| `PEM` | `PKCS8`, `OpenSSH` | `SubjectPublicKeyInfo`, `OpenSSH` |
| `DER` | `PKCS8` | `SubjectPublicKeyInfo` |

#### Loading Keys from Bytes

```python
private_key = Ed25519PrivateKey.from_private_bytes(raw_private)  # Must be exactly 32 bytes
public_key  = Ed25519PublicKey.from_public_bytes(raw_public)     # Must be exactly 32 bytes
```

#### Converting Between Ed25519 and X25519 Keys

The `pyca/cryptography` library does **NOT** natively support Ed25519-to-X25519 key conversion (GitHub issue #5557, open since 2020). Use PyNaCl (wraps libsodium):

```python
import nacl.signing
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey, X25519PublicKey,
)

# Step 1: Get the Ed25519 raw seed
ed25519_seed = private_key.private_bytes_raw()  # 32 bytes

# Step 2: Import into PyNaCl as a SigningKey
signing_key = nacl.signing.SigningKey(seed=ed25519_seed)

# Step 3: Convert to X25519/Curve25519
x25519_nacl_private = signing_key.to_curve25519_private_key()
x25519_nacl_public  = signing_key.verify_key.to_curve25519_public_key()

# Step 4: Import back into pyca/cryptography for ECDH operations
x25519_private = X25519PrivateKey.from_private_bytes(bytes(x25519_nacl_private))
x25519_public  = X25519PublicKey.from_public_bytes(bytes(x25519_nacl_public))
```

**Mathematical basis:** Ed25519 (twisted Edwards) and X25519 (Montgomery) are birationally equivalent over `GF(2^255 - 19)`. One 32-byte seed can serve both signing (Ed25519) and encryption (X25519) via this birational map.

#### Converting Raw Bytes to JWK (for joserfc)

```python
import base64
from joserfc.jwk import OKPKey

def ed25519_raw_to_jwk(private_bytes: bytes, public_bytes: bytes) -> dict:
    """Convert raw Ed25519 bytes to JWK format for joserfc."""
    return {
        "kty": "OKP",
        "crv": "Ed25519",
        "x": base64.urlsafe_b64encode(public_bytes).rstrip(b"=").decode(),
        "d": base64.urlsafe_b64encode(private_bytes).rstrip(b"=").decode(),
    }

okp_key = OKPKey.import_key(ed25519_raw_to_jwk(raw_private, raw_public))
```

#### JWK Format for Ed25519 and X25519

```json
// Ed25519 signing key
{
  "kty": "OKP",
  "crv": "Ed25519",
  "x": "<base64url-encoded 32-byte public key>",
  "d": "<base64url-encoded 32-byte private key seed — omit for public-only>"
}

// X25519 key agreement key
{
  "kty": "OKP",
  "crv": "X25519",
  "x": "<base64url-encoded 32-byte public key>",
  "d": "<base64url-encoded 32-byte private key — omit for public-only>"
}
```

Both use `kty: "OKP"` (Octet Key Pair). An X25519 key cannot be used for signing and an Ed25519 key cannot be used for ECDH key agreement — the JWK types enforce this distinction even though the keys are mathematically related.

---

### 1.5 Ed25519 Algorithm Security Properties

#### Key and Signature Sizes

| Component | Size | Notes |
|-----------|------|-------|
| Private key (seed) | 32 bytes (256 bits) | Cryptographically random seed |
| Public key | 32 bytes (256 bits) | Compressed Edwards point |
| Signature | 64 bytes (512 bits) | (R, S) pair |
| Security level | ~128 bits | Equivalent to AES-128, RSA-3072, ECDSA P-256 |

#### Performance Benchmarks

| Algorithm | Key Gen | Sign | Verify | Sig Size | Pub Key Size |
|-----------|---------|------|--------|----------|--------------|
| Ed25519 | ~15 µs | ~15 µs | ~45 µs | 64 B | 32 B |
| ECDSA P-256 | ~30 µs | ~30 µs | ~90 µs | 64 B | 33 B |
| ECDSA P-384 | ~60 µs | ~60 µs | ~180 µs | 96 B | 49 B |
| RSA-2048 | ~500 ms | ~500 µs | ~15 µs | 256 B | 256 B |

**Ed25519 signing is ~30x faster than RSA-2048 signing** — critical for high-throughput agent message signing.

#### Security Properties

1. **Deterministic signatures (no RNG at signing time):**
   `r = SHA-512(nonce_prefix || message) mod l`
   Eliminates the catastrophic nonce reuse vulnerability in ECDSA (PS3 hack, 2010).

2. **Constant-time implementation:** All field arithmetic in constant time; no secret-dependent branches. Inherent timing side-channel resistance.

3. **Cofactor safety:** Cofactor = 8. Ed25519 includes cofactor multiplication during verification to prevent small-subgroup attacks. Key clamping: `scalar[0] &= 248` ensures the scalar is divisible by 8.

4. **Nothing-up-my-sleeve parameters:** `p = 2^255 - 19` (largest 255-bit prime). No hidden backdoor parameters (contrast with NIST P-curves).

5. **SUF-CMA (Strong Unforgeability under Chosen Message Attack):** An adversary cannot produce any valid (message, signature) pair without the private key.

6. **PureEdDSA vs HashEdDSA:**

| Variant | Prehash | Collision Resilience |
|---------|---------|---------------------|
| **PureEdDSA** (Ed25519) | None | **Yes** — collision in SHA-512 does not break security |
| **HashEdDSA** (Ed25519ph) | SHA-512 | **No** — collision breaks scheme |

**Always use PureEdDSA (pass raw bytes, never pre-hash).**

#### Key Clamping

```python
# Applied to first 32 bytes of SHA-512(seed):
scalar[0]  &= 248   # Clear bits 0,1,2 — makes scalar divisible by cofactor 8
scalar[31] &= 63    # Clear bits 254, 255 — keeps scalar below 2^255
scalar[31] |= 64    # Set bit 254 — constant-time Montgomery ladder
```

**Implication:** Key clamping breaks additive hierarchical derivation (BIP32-style). If Orchestra needs hierarchical agent key derivation, use HKDF from a master seed instead.

#### Ed25519 vs X25519 Relationship

| Property | Ed25519 | X25519 |
|----------|---------|--------|
| Curve form | Twisted Edwards | Montgomery |
| Operation | Digital signatures (EdDSA) | Diffie-Hellman key exchange |
| Base curve | Curve25519 (`GF(2^255 - 19)`) | Curve25519 |
| Key size | 32 bytes | 32 bytes |
| Standard | RFC 8032 | RFC 7748 |
| Conversion | Possible via birational map | Possible via birational map |

---

### 1.6 joserfc JWS with Ed25519

**Library:** `joserfc` (by Authlib/lepture). Implements JWS (RFC 7515), JWE (RFC 7516), JWK (RFC 7517), JWA (RFC 7518), JWT (RFC 7519), RFC 8037 (OKP key type), RFC 9864 (Ed25519/Ed448 as distinct identifiers — since v1.5.0).

**Installation:** `pip install joserfc>=1.5.0`

#### OKPKey Generation and Import

```python
from joserfc.jwk import OKPKey

# Generate
ed25519_key = OKPKey.generate_key("Ed25519")
x25519_key  = OKPKey.generate_key("X25519")

# Import from JWK dict
private_key = OKPKey.import_key({
    "kty": "OKP", "crv": "Ed25519",
    "x": "t-nFRaxyM5DZcpg5lxiEeJcZpMRB8JgcKaQC0HRefXU",
    "d": "gUF17HCe-pbN7Ej2rDSXl-e7uSj7rQW5u2dNu0KINP0",
    "kid": "agent-signing-key-v1"
})

# Import from PEM
key = OKPKey.import_key("-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n")

# Export
public_jwk  = key.as_dict(private=False)
private_jwk = key.as_dict(private=True)
private_pem = key.as_pem(private=True)
thumbprint  = key.thumbprint()           # RFC 7638 SHA-256 thumbprint
thumbprint_uri = key.thumbprint_uri()   # urn:ietf:params:oauth:jwk-thumbprint:sha-256:...

# Deterministic key from secret string (useful for stable agent identity)
key = OKPKey.derive_key("agent-secret-seed-string", "Ed25519", kdf_name="HKDF")
```

#### JWS Compact Serialization with Ed25519

**Signing:**

```python
from joserfc import jws
from joserfc.jwk import OKPKey

private_key = OKPKey.generate_key("Ed25519")
protected   = {"alg": "Ed25519"}  # RFC 9864: use "Ed25519" not deprecated "EdDSA"
payload     = b'{"agent_id":"agent-001","capabilities":["reason","search"]}'

token = jws.serialize_compact(
    protected, payload, private_key,
    algorithms=["Ed25519"]  # Explicit allowlist — prevents downgrade attacks
)
# token: "eyJhbGciOiJFZDI1NTE5In0.<payload>.<signature>"
```

**Verification:**

```python
public_key = OKPKey.import_key(private_key.as_dict(private=False))
result = jws.deserialize_compact(
    token, public_key,
    algorithms=["Ed25519"]  # MUST specify to prevent algorithm confusion
)
print(result.protected)  # {"alg": "Ed25519"}
print(result.payload)    # bytes
```

Raises `joserfc.errors.BadSignatureError` on invalid signature; `joserfc.errors.DecodeError` on algorithm mismatch.

**With KeySet (key rotation):**

```python
from joserfc.jwk import KeySet, OKPKey

key1 = OKPKey.generate_key("Ed25519", kid="v1")
key2 = OKPKey.generate_key("Ed25519", kid="v2")
key_set = KeySet([key1, key2])

# Sign with specific key
protected = {"alg": "Ed25519", "kid": "v2"}
token = jws.serialize_compact(protected, payload, key_set, algorithms=["Ed25519"])

# Verify against key set (joserfc picks the right key via kid)
result = jws.deserialize_compact(token, key_set, algorithms=["Ed25519"])
```

#### RFC 9864: Ed25519 as Distinct Algorithm Identifier

RFC 9864 (2024) eliminates the ambiguity of the older `"EdDSA"` identifier.

```python
# Old way (deprecated, still works):
protected = {"alg": "EdDSA"}  # Ambiguous — Ed25519 or Ed448?

# New way (RFC 9864, always preferred):
protected = {"alg": "Ed25519"}  # Unambiguous

# Backward compat during migration:
result = jws.deserialize_compact(token, key, algorithms=["Ed25519", "EdDSA"])
```

joserfc added explicit support in **v1.5.0**. For new code, always use `"Ed25519"`, not `"EdDSA"`.

#### JWT with Ed25519 (for UCAN tokens)

```python
from joserfc import jwt
from joserfc.jwk import OKPKey

private_key = OKPKey.generate_key("Ed25519")

claims = {
    "iss": "did:peer:2.Ez6LS...agent-001",
    "aud": "did:peer:2.Ez6LS...orchestrator",
    "iat": 1700000000,
    "exp": 1700003600,
    "att": [{"with": "tool:search", "can": "invoke"}],
    "prf": []
}
token = jwt.encode({"alg": "Ed25519"}, claims, private_key, algorithms=["Ed25519"])

# Verify with claims registry
from joserfc.jwt import JWTClaimsRegistry
result = jwt.decode(token, private_key.as_dict(private=False), algorithms=["Ed25519"])
claims_requests = JWTClaimsRegistry(
    iss={"essential": True},
    exp={"essential": True},
    aud={"essential": True, "value": "did:peer:2.Ez6LS...orchestrator"},
)
claims_requests.validate(result.claims)
```

---

### 1.7 peerdid Python Library

**Library:** `peerdid` (by SICPA-DLab). Supports numalgo 0 and numalgo 2. Does NOT support numalgo 1.

**Installation:** `pip install peerdid`

**Key imports:**

```python
from peerdid.dids import (
    create_peer_did_numalgo_0,
    create_peer_did_numalgo_2,
    resolve_peer_did,
)
from peerdid.keys import (
    Ed25519VerificationKey,
    X25519KeyAgreementKey,
)
```

#### Creating Key Objects and a did:peer:2

```python
import base58  # pip install base58
import nacl.signing
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# Generate Ed25519 key pair
ed_private    = Ed25519PrivateKey.generate()
ed_pub_bytes  = ed_private.public_key().public_bytes_raw()

# Derive X25519 from same seed
nacl_key         = nacl.signing.SigningKey(seed=ed_private.private_bytes_raw())
x25519_pub_bytes = bytes(nacl_key.verify_key.to_curve25519_public_key())

# Create peerdid key objects (base58-encoded)
signing_key    = Ed25519VerificationKey.from_base58(base58.b58encode(ed_pub_bytes).decode())
encryption_key = X25519KeyAgreementKey.from_base58(base58.b58encode(x25519_pub_bytes).decode())

# Create did:peer:2
peer_did = create_peer_did_numalgo_2(
    encryption_keys=[encryption_key],
    signing_keys=[signing_key],
    service={
        "type": "DIDCommMessaging",
        "serviceEndpoint": "https://agents.example.com/orchestrator",
        "routingKeys": [],
        "accept": ["didcomm/v2"],
    }
)
# "did:peer:2.Ez6LSqPZfn9krvgXma2icTMKf2uVcYhKXsudCmPoUzqGYW24U
#             .Vz6MkrCD1csqtgdj8sjrsu8jxcbeyP6m7LiK7Z3pqBN2Rze7b
#             .SeyJ0IjoiRElEQ29tbU1lc3NhZ2luZyIs..."
```

#### Resolving and Extracting Keys

```python
did_doc = resolve_peer_did(peer_did)
doc_dict = json.loads(did_doc.to_json())

# Resolved document excerpt:
# verificationMethod[0]: type "X25519KeyAgreementKey2020" -> in keyAgreement
# verificationMethod[1]: type "Ed25519VerificationKey2020" -> in authentication + assertionMethod
```

**Key extraction from resolved DID Document:**

```python
import json, base58

def extract_keys_from_did_doc(did_doc_str: str) -> dict:
    doc = json.loads(did_doc_str)
    vm_by_id = {vm["id"]: vm for vm in doc.get("verificationMethod", [])}
    result = {}

    for ka_ref in doc.get("keyAgreement", []):
        key_id = ka_ref if isinstance(ka_ref, str) else ka_ref.get("id")
        if vm := vm_by_id.get(key_id):
            raw = base58.b58decode(vm["publicKeyMultibase"][1:])  # skip 'z' prefix
            result["encryption_key_bytes"] = raw[2:]  # skip 2-byte multicodec prefix 0xec01

    for auth_ref in doc.get("authentication", []):
        key_id = auth_ref if isinstance(auth_ref, str) else auth_ref.get("id")
        if vm := vm_by_id.get(key_id):
            raw = base58.b58decode(vm["publicKeyMultibase"][1:])
            result["signing_key_bytes"] = raw[2:]  # skip 2-byte multicodec prefix 0xed01

    return result
```

#### Dependency Summary

| Library | Purpose | Status |
|---------|---------|--------|
| `cryptography` | Ed25519 key generation, signing, serialization | Already in project deps |
| `PyNaCl` | Ed25519-to-X25519 key conversion via libsodium | **New dependency needed** |
| `joserfc>=1.5.0` | JWS with Ed25519 (RFC 9864), JWT for UCANs | Already in project deps |
| `peerdid` | did:peer:0 and did:peer:2 creation and resolution | Already in project deps |
| `base58` | Base58btc encoding for peerdid key objects | May need to add |

**[OPEN QUESTION]:** `peerdid` (SICPA-DLab) vs `did-peer-2` (DIF — newer, simpler). Which should Orchestra standardize on? The DIF `did-peer-2` package may be better maintained going forward.

---

## Part 2: Agent Interoperability

### 2.1 A2A Protocol & Agent Cards

**Protocol:** Agent2Agent (A2A) — open standard by Google (April 2025), governed by Linux Foundation under Apache 2.0. As of v0.3.0 (July 2025), supported by 150+ organizations including Atlassian, Salesforce, SAP, LangChain.

**Python SDK:** `a2a-sdk` on PyPI (v0.3.25 as of March 2026), Python 3.10+.

Key design principles:
- Built on HTTP(S), JSON-RPC 2.0, and SSE
- Optional gRPC transport (v0.3.0+)
- Capability discovery via Agent Cards
- Task management with defined lifecycle states
- Signed Agent Cards (JWS, RFC 7515) added in v0.3.0

#### Agent Card JSON Schema

An Agent Card is a JSON document published at `/.well-known/agent-card.json` (RFC 8615).

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Human-readable name |
| `description` | string | What the agent does |
| `version` | string | Semver |
| `supported_interfaces` | AgentInterface[] | Communication endpoints |
| `capabilities` | AgentCapabilities | Feature flags |
| `default_input_modes` | string[] | Input MIME types |
| `default_output_modes` | string[] | Output MIME types |
| `skills` | AgentSkill[] | List of discrete capabilities |

**Optional fields (relevant to Orchestra):**

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique agent identifier — can be a DID (e.g., `"did:key:z6Mk..."`) |
| `provider` | AgentProvider | Organization info |
| `security_schemes` | map[string, SecurityScheme] | Authentication methods |
| `signatures` | AgentCardSignature[] | JWS digital signatures (v0.3.0+) |

**Complete example:**

```json
{
  "id": "did:key:z6Mk...",
  "name": "Orchestra Framework Agent",
  "description": "Multi-agent orchestration with capability-based authorization",
  "version": "1.0.0",
  "supported_interfaces": [{"type": "json-rpc", "version": "2.0", "url": "https://orchestra.example.com/a2a"}],
  "capabilities": {"streaming": true, "push_notifications": true, "extended_agent_card": true},
  "default_input_modes": ["text/plain", "application/json"],
  "default_output_modes": ["application/json"],
  "skills": [{
    "id": "orchestrate_workflow",
    "name": "Orchestrate Multi-Agent Workflow",
    "description": "Coordinates multiple agents",
    "tags": ["orchestration", "workflow"]
  }],
  "security_schemes": {
    "bearer": {"type": "http", "scheme": "bearer", "bearerFormat": "UCAN"}
  },
  "security": [{"bearer": []}],
  "signatures": [{"protected": "...", "signature": "base64url-encoded-jws-signature"}]
}
```

#### Agent Card Signing (v0.3.0+)

1. Canonicalize the Agent Card JSON using **JCS** (JSON Canonicalization Scheme, RFC 8785)
2. Compute JWS signature over the canonicalized bytes
3. Append `AgentCardSignature` to `signatures` array

```python
from a2a.client import A2ACardResolver

def my_signature_verifier(card, signatures):
    verify_jws(card, signatures, trusted_keys)  # raises on failure

resolver = A2ACardResolver(
    base_url="https://orchestra.example.com",
    signature_verifier=my_signature_verifier,
)
card = await resolver.get_card()
```

**Sigstore integration** (`sigstore-a2a` on PyPI): Keyless signing using short-lived OIDC certificates. Enables CI-signed cards with cryptographic provenance of the agent's origin.

**DID integration:** The A2A spec does not mandate DID-based identity, but they are complementary:
- Agent Cards can carry a DID in the `id` field
- JWS signing key can be a DID-associated key
- For Orchestra, map existing `did:key` identities (from T-4.1) to Agent Card `id` fields — creating a continuous chain of trust from discovery through messaging

#### Task States

| State | Terminal? |
|-------|-----------|
| `SUBMITTED` | No |
| `WORKING` | No |
| `INPUT_REQUIRED` | No (interrupted) |
| `AUTH_REQUIRED` | No (interrupted) |
| `COMPLETED` | Yes |
| `FAILED` | Yes |
| `CANCELED` | Yes |
| `REJECTED` | Yes |

#### Authentication Mechanisms

The spec defines five `SecurityScheme` types: `APIKeySecurityScheme`, `HTTPAuthSecurityScheme`, `OAuth2SecurityScheme`, `OpenIdConnectSecurityScheme`, `MutualTlsSecurityScheme`.

For Orchestra: `HTTPAuthSecurityScheme` with `scheme: bearer` and `bearerFormat: UCAN` is the natural fit.

#### Python SDK Example

```python
from a2a.types import AgentSkill, AgentCard, AgentCapabilities
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue

class OrchestraAgentExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        result = await self.runner.run(context.message.parts[0].text)
        await event_queue.enqueue_event(result)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        pass

card = AgentCard(
    name="Orchestra Agent",
    description="Multi-agent orchestration",
    url="https://orchestra.example.com/a2a",
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=True, push_notifications=True),
    default_input_modes=["text/plain", "application/json"],
    default_output_modes=["application/json"],
    skills=[AgentSkill(id="orchestrate", name="Orchestrate", description="...", tags=["orchestration"])],
)

app = A2AStarletteApplication(agent_card=card, http_handler=DefaultRequestHandler(
    agent_executor=OrchestraAgentExecutor(), task_store=InMemoryTaskStore(),
))
```

---

### 2.2 Google Cloud Agentic AI Design Patterns

Google's Agent Development Kit (ADK) defines eight multi-agent design patterns built on three primitives: `SequentialAgent`, `LoopAgent`, `ParallelAgent`.

1. **Sequential Pipeline** — Assembly line. Agent A completes, passes to Agent B. Linear, deterministic.
2. **Parallel Fanout** — Multiple agents work simultaneously on independent subtasks. Aggregate results at end.
3. **Supervisor** — Orchestrator delegates to specialist subagents based on task type.
4. **Hierarchical** — Multi-level delegation. Orchestrator → Supervisors → Workers.
5. **Loop (Self-Critique)** — Agent runs, evaluates its output, iterates until quality threshold met.
6. **Dynamic Subgraph** — Agent generates its own subagent configuration at runtime based on task.
7. **Stateful Workflow** — Long-running multi-turn workflows with persistent state across sessions.
8. **Human-in-the-Loop** — Workflow pauses at `INPUT_REQUIRED` for human review before continuing.

**Relevance to Orchestra:** Orchestra already implements patterns 1-4. Patterns 6-7 are in Wave 4 scope (T-4.12 Dynamic Subgraphs). Pattern 5 (Self-Critique) is relevant to Phase 3's reasoning subsystem.

---

### 2.3 UCAN Specification (v0.10 / v1.0)

**UCAN** (User Controlled Authorization Networks): Trustless, secure, local-first, user-originated distributed authorization. Current spec: v1.0.0-rc.1 (Release Candidate, 2024).

Key properties:
- **Public-key verifiable** — no central auth server
- **Delegable** — authority can be passed down, never up
- **Expressively scoped** — fine-grained resource + action control
- **Transport-agnostic** — works offline, P2P, federated, or centralized

#### JWT Format (0.9.x / 0.10.x — used by py-ucan)

**Header:**

| Field | Required | Description |
|-------|----------|-------------|
| `alg` | Yes | MUST be `"EdDSA"` (Ed25519) or `"ES256"` (P-256) |
| `typ` | Yes | MUST be `"JWT"` |
| `ucv` | Yes | UCAN semantic version, e.g., `"0.9.1"` |

**Payload:**

| Field | Required | Description |
|-------|----------|-------------|
| `iss` | Yes | Issuer DID |
| `aud` | Yes | Audience DID |
| `exp` | Yes | Expiration UTC Unix timestamp. `null` = no expiry (strongly discouraged) |
| `nbf` | No | Not Before UTC Unix timestamp |
| `nnc` | No | Nonce (prevents replay) |
| `att` | Yes | Attenuations — array of `{with, can}` capability objects |
| `prf` | Yes | Proofs — array of CIDs establishing authority chain |
| `fct` | No | Facts — arbitrary signed metadata assertions |

**Decoded payload example (0.9.x with `orchestra:` scheme):**

```json
{
  "iss": "did:key:z6MkiTBz1ymuepAQ4HEHYSF1H8quG5GLVVQR3djdX3mDooWp",
  "aud": "did:key:z6MknGc3omqSANLNpX4vkHFGZezNa3K5y2KUFnMuXpnxfJNG",
  "exp": 1735689600,
  "nbf": 1704153600,
  "nnc": "d24e765c8b3f4a2e",
  "att": [
    {"with": "orchestra:tools/web_search", "can": "tool/invoke"},
    {"with": "orchestra:tools/code_execution", "can": "tool/invoke"}
  ],
  "prf": ["bafyreig3..."],
  "fct": [{"delegation_depth": 2, "cost_budget_remaining_usd": 1.50, "workflow_id": "wf-abc123"}]
}
```

#### DAG-CBOR Format (v1.0.0-rc.1)

The 1.0 spec moves to DAG-CBOR as canonical encoding:
- More compact than JWT (binary, not base64url text)
- Hash-consistent — same bytes always produce same CID
- Envelope tag: `ucan/dlg@1.0.0-rc.1`
- Signature encoded as **varsig** multiformat
- Capability format changes from `{with, can}` to `{sub, cmd, pol}`

**Version comparison:**

| Feature | 0.9.x | 0.10.x | 1.0.0-rc.1 |
|---------|-------|--------|-------------|
| Wire encoding | JWT | JWT | DAG-CBOR (binary IPLD) |
| Capability format | `{with: URI, can: ability}` | Same | `{sub: DID, cmd: path, pol: predicates}` |
| Policy language | None | None | Full predicate logic (jq-style selectors) |
| Python library support | `py-ucan 1.0.0` | `py-ucan 1.0.0` | None yet |

#### Delegation Chain Mechanics

```
Root UCAN (Alice -> Bob)
  prf: []                     <- Root: no proofs, Alice owns the resource
  iss: did:key:alice
  aud: did:key:bob
  att: [{ with: "orchestra:tools/*", can: "tool/invoke" }]
  CID: bafyreig3abc...

Delegation UCAN (Bob -> Carol)
  prf: [bafyreig3abc...]      <- References Alice->Bob root
  iss: did:key:bob            <- MUST match aud of referenced proof
  aud: did:key:carol
  exp: 1704240000             <- Cannot exceed root's exp
  att: [{ with: "orchestra:tools/web_search", can: "tool/invoke" }]
                               <- Narrower than root (specific tool, not *)
```

**Chain validation algorithm:**
1. Parse the outermost UCAN and extract `prf` CIDs
2. For each proof, retrieve and parse the referenced UCAN
3. Verify `aud` of proof MUST match `iss` of child
4. Verify each capability in child exists in (or is a subset of) the proof's `att`
5. Recurse until reaching a root UCAN (`prf: []`)
6. Verify time bounds: max(all `nbf`) to min(all `exp`) across the chain
7. Check each CID against the revocation store

#### Attenuation Rules

1. **Capability subsetting:** Child capabilities MUST be a subset of parent capabilities
2. **Command hierarchy:** Delegating `/store` grants both `/store/add` and `/store/remove`
3. **Policy narrowing only:** Policies can only ADD constraints, never remove
4. **Time bound contraction:** Child `exp` ≤ parent `exp`; child `nbf` ≥ parent `nbf`
5. **Powerline pattern** (`sub: null` in 1.0): Pass-through delegation where subject is substituted

#### TTL Enforcement

| Aspect | Specification |
|--------|--------------|
| `exp` field | REQUIRED. UTC Unix timestamp. `null` = no expiry (strongly discouraged) |
| Clock drift | Spec says "SHOULD account for expected clock drift." Common: ±60 seconds |
| Chain validity | max(all `nbf`) to min(all `exp`) across chain. Narrowest window wins. |
| Best practice | Tool invocations: minutes. Sessions: hours. Never `null` in production. |

```python
def is_ucan_time_valid(nbf: int, exp: int, skew_seconds: int = 60) -> bool:
    now = int(time.time())
    return (nbf - skew_seconds) <= now <= (exp + skew_seconds)
```

#### Revocation

- The issuer of ANY delegation in the proof chain can revoke that specific delegation
- Revocations identified by CID of the target delegation
- Irreversible
- Strategies:

| Strategy | Use Case |
|----------|----------|
| In-memory set | Single-process, development |
| Redis sorted set | Distributed, production (TTL-aware) |
| Bitstring Status List (W3C) | Privacy-preserving, large scale |
| Database (SQLite/PostgreSQL) | Durable, auditable |

For Orchestra: Redis-backed revocation cache. Key schema: `ucan:revoked:{cid}` → `{issuer_did}:{revoked_at_timestamp}`.

#### Custom Resource Schemes for Orchestra

Recommended `orchestra:` URI hierarchy:

| Resource URI | Description |
|--------------|-------------|
| `orchestra:*` | Full access (root authority only) |
| `orchestra:tools/*` | All tool invocations |
| `orchestra:tools/web_search` | Specific tool |
| `orchestra:agents/*` | Invoke any agent |
| `orchestra:workflows/*` | All workflow operations |
| `orchestra:budget/team-alpha` | Budget scope |
| `orchestra:memory/*` | All memory operations |

Ability hierarchy:
```
tool/invoke, tool/invoke/stream, tool/admin
agent/invoke, agent/spawn
workflow/run, workflow/cancel
memory/read, memory/write, memory/admin
budget/read, budget/debit
```

---

### 2.4 py-ucan Python Library

| Attribute | Value |
|-----------|-------|
| Package | `py-ucan` |
| Version | 1.0.0 (August 9, 2024) |
| Repository | github.com/fileverse/py-ucan |
| Python | >=3.10, <4.0 |
| Key dependency | Pydantic v2 |
| Install | `pip install -U py-ucan` |
| License | MIT |

**Critical caveat:** Despite the "1.0.0" version number, py-ucan implements the **older 0.9.x-style format** using `with`/`can` capability objects. It does NOT implement the UCAN 1.0 spec's `sub`/`cmd`/`pol` format.

#### Core API

```python
import ucan

# Generate Ed25519 keypair
keypair = ucan.EdKeypair.generate()
did = keypair.did()  # "did:key:z6MkiTBz1ymuepAQ4HEHYSF1H8quG5GLVVQR3djdX3mDooWp"

# Construct capability objects
from ucan import Capability, ResourcePointer, Ability

cap = Capability(
    with_=ResourcePointer(scheme="orchestra", hier_part="tools/web_search"),
    can=Ability(namespace="tool", segments=["invoke"]),
)
# Note: Python uses "with_" (trailing underscore) because "with" is reserved

# Parse/validate tokens
parsed = ucan.parse(encoded_token)          # decode without crypto verification
result = await ucan.validate(encoded_token) # validate signature + structure + time bounds

# Full verification with delegation chain
result = await ucan.verify(
    token,
    audience=server_did,
    required_capabilities=[
        ucan.RequiredCapability(
            capability=ucan.Capability(
                with_=ucan.ResourcePointer(scheme="orchestra", hier_part="tools/web_search"),
                can=ucan.Ability(namespace="tool", segments=["invoke"]),
            ),
            root_issuer=resource_owner_did,
        ),
    ],
)
if result.ok:
    # authorized
    pass
```

#### Limitations

1. **0.9.x format only:** Uses `with`/`can` style. Migration needed when 1.0-compatible Python library exists.
2. **No built-in revocation:** Must implement externally and call before/after `verify()`
3. **Async API:** `validate()` and `verify()` are async
4. **Small maintainer surface (fileverse):** Risk of abandonment. Mitigation: thin wrapper abstraction or vendor a copy
5. **No builder API in public docs:** `UcanBuilder` API not fully documented publicly; inspect library source
6. **Proof resolution:** How proofs referenced by CID are provided to verifier needs empirical testing

---

### 2.5 UCAN vs zcap-ld

| Aspect | UCAN | zcap-ld |
|--------|------|---------|
| Wire format | JWT (text) or DAG-CBOR (binary) | JSON-LD (verbose text) |
| Addressing | CID (hash-based, content-addressed) | URL (location-based) |
| Signing | JWS (JWT) / varsig (1.0) | Linked Data Proofs |
| DID support | Native (`iss`, `aud` are DIDs) | Native (JSON-LD `@context`) |
| Encoding size | ~200-500 bytes JWT | ~1-5 KB JSON-LD |
| Offline verification | Yes (CID-based) | Partial (URL-based requires network) |
| Python library | `py-ucan` (exists, MIT) | No dedicated library |

**Python library gap:** No production-ready Python zcap-ld library exists. Implementing from scratch requires `PyLD` + custom Linked Data Proofs + custom capability model: 2-4 weeks of engineering.

**Verdict:** UCAN is the correct choice for Orchestra. The absence of a Python zcap-ld library alone makes zcap-ld a non-starter. UCAN's JWT format, DID-native design, and Pydantic v2 compatibility align with Orchestra's existing architecture.

---

### 2.6 Awesome Agentic Patterns

**OWASP Top 10 for Agentic Applications (2026)** — released December 2025, 100+ expert review:

| Risk | Description | Orchestra Mitigation |
|------|-------------|---------------------|
| **ASI01: Agent Goal Hijack** | Redirect agent objectives via poisoned instructions or tool outputs | Input validation, OOD detection |
| **ASI03: Identity & Privilege Abuse** | Exploit inherited/cached credentials, delegated permissions, agent-to-agent trust | DID-based identity (T-4.6), UCAN TTLs (T-4.7), Vault dynamic secrets |
| **ASI04: Supply Chain Vulnerabilities** | Malicious/tampered tools, descriptors, or agent personas | Signed Agent Cards + signature verification (T-4.6) |
| **ASI06: Memory & Context Poisoning** | Corrupt agent memory, RAG stores, or contextual knowledge | Schema validation, TTL expiry, provenance tracking (T-4.6) |
| **ASI10: Rogue Agents** | Compromised agents diverge from intended behavior | UCAN revocation, allowlist mode, rate limiting (T-4.7) |

---

## Part 3: Distributed Security

### 3.1 AgentPoison & LLM Memory Attacks

#### AgentPoison (NeurIPS 2024)

**Paper:** Chen et al., NeurIPS 2024 (arXiv 2407.12784). Code: github.com/AI-secure/AgentPoison.

**Attack methodology:** The first backdoor attack specifically targeting RAG-based LLM agents. Requires **no model training or fine-tuning**. Operates purely by poisoning the agent's external knowledge base.

**Core technique:** Constrained optimization to find trigger strings that, when embedded in poisoned documents, cause those documents to map to a unique, compact region in embedding space:

```
Objective: Find trigger t such that:
  1. embed(query + t) ∈ R*   (triggered queries map to unique target region)
  2. R* contains only poisoned demonstrations
  3. embed(query_benign) ∉ R* (benign queries do not enter the target region)
```

**Key properties:**
- Transferability across different embedding models
- In-context coherence — triggers appear natural, resist human detection
- Benign performance degradation < 1%
- Poison rate required: < 0.1% of knowledge base
- Average attack success rate: ≥ 80%
- Minimum effective attack: **1 poisoned instance + 1 trigger token**

#### MemoryGraft (arXiv 2512.16962, Dec 2025)

Distinct from AgentPoison: targets **long-term experience memory** (procedural) rather than RAG knowledge base (factual).

| Aspect | AgentPoison | MemoryGraft |
|---|---|---|
| Target | RAG knowledge base | Long-term experience memory |
| Trigger required? | Yes — optimized adversarial trigger | No — semantic similarity sufficient |
| Injection vector | Direct knowledge base poisoning | Benign-looking content (READMEs, docs) |
| Persistence | Single-session | **Cross-session** (behavioral drift) |

#### Zombie Agents (arXiv 2602.15654, Feb 2026)

Agents **actively rewrite their own memory** with attacker-controlled instructions. Unlike simple prompt injection (transient), this survives session boundaries because the backdoor is written to long-term memory and retrieved via normal RAG on future tasks.

**Defense implication:** Agents must treat their own memory write operations with the same scrutiny as external inputs.

#### PoisonedRAG (USENIX Security 2025)

**90% attack success rate** with only 5 poisoned documents among millions. Perplexity-based filtering fails. Paraphrase detection fails. All evaluated defenses deemed insufficient by authors.

#### Attack Vectors for Orchestra

| Attack Vector | Description | Orchestra Component at Risk |
|---|---|---|
| RAG corpus poisoning | Injecting malicious documents with optimized triggers | Agent memory stores (T-4.8 Redis L2) |
| Gossip poisoning | Injecting fake agent metadata into discovery | SignedDiscoveryProvider (T-4.6) registry |
| Prompt injection via poisoned context | Retrieved poisoned docs hijack agent behavior | Any agent using shared knowledge bases |
| Memory injection / sleeper agents | Poisoned memory entries activate later | Long-term memory (T-4.8) |

#### Defense Strategy for Orchestra

**Layer 1 — Schema Validation (mandatory):**
- JSON Schema validation for all Agent Cards (reject malformed structure)
- Content length limits on capability descriptions
- Allowlist for known-safe capability types

**Layer 2 — Cryptographic Signatures on Cards (mandatory):**
- Require all Agent Cards signed with agent DID key
- Verify on every lookup (or with cached TTL-based verification)
- No exceptions, no fallback to unsigned Cards

**Layer 3 — Provenance Tracking:**
- Every Card records: registering DID, registration timestamp, signature, version number, content hash
- Cards without valid provenance are rejected

**Layer 4 — TTL Expiry:**
- All Cards have `valid_until` timestamp
- Expired Cards automatically purged
- Agents must re-sign before expiry

**Layer 5 — Rate Limiting:**
- Max 1 Card update per DID per 30 seconds (configurable)
- DID temporarily blacklisted after N consecutive invalid Cards

**Layer 6 — Memory Segmentation:**
- Signed, verified Cards in the **trusted registry**
- Gossip-sourced, unverified Cards in the **staging buffer**
- Staging buffer entries have short TTLs, never used for security decisions

**Layer 7 — Embedding Anomaly Detection (optional, high-security deployments):**
- Compare incoming Card capability embeddings against distribution of known-good Cards
- Flag Cards whose embeddings are far from the cluster

---

### 3.2 Gossip Protocol Security

**Papers:**
- arXiv 2512.03285 — "A Gossip-Enhanced Communication Substrate for Agentic AI"
- arXiv 2508.01531 — "Revisiting Gossip Protocols: A Vision for Emergent Coordination in Agentic Multi-Agent Systems"
- arXiv 2512.17913 — "Byzantine Fault-Tolerant Multi-Agent System for Healthcare"

#### Gossip for Agent Discovery

Gossip provides a background layer beneath structured protocols (MCP, A2A):

```
┌─────────────────────────────────────────────┐
│         Application Layer (Agent Logic)      │
├──────────────┬──────────────┬───────────────┤
│     MCP      │     A2A      │      ACP      │  ← Structured protocols
├──────────────┴──────────────┴───────────────┤
│         Gossip Substrate Layer               │  ← Background awareness
│  (discovery, load signals, failure detect)   │
├─────────────────────────────────────────────┤
│         Transport (NATS, gRPC, HTTP)         │
└─────────────────────────────────────────────┘
```

**Convergence:** O(log n) rounds. In a 25,000-node network: ~30 rounds total (15 to spread, 15 to sync).

**Anti-entropy mechanisms for agent registries:**
- **OR-Set CRDT** — Additions tagged with unique tokens; concurrent add/remove resolved deterministically
- **Vector clock versioning** — Agent Cards carry Lamport timestamps; accept only newer versions
- **Merkle tree synchronization** — Periodic hash exchange triggers targeted sync of divergent subtrees

**Important caveat for Wave 2:** Full gossip implementation is NOT needed for the MVP. Direct NATS-based discovery with signed Cards is sufficient. Gossip becomes valuable when agent count exceeds ~50.

#### Attack Taxonomy and Defenses

**Sybil Attacks:** Attacker creates many pseudonymous identities. In agent systems: fake Agent Cards with fabricated capabilities flood the registry.

**Eclipse Attacks:** Attacker controls all peer connections of a target node, feeding false state.

**Hub Attacks:** Malicious nodes manipulate the Peer Sampling Service (PSS) such that honest nodes' views converge to contain only attacker-controlled entries.

**BFT Gossip message structure (signed):**

```json
{
  "type": "agent_card_update",
  "payload": { "...agent card data..." },
  "sender_did": "did:peer:z6Mkf5rG...abc",
  "timestamp": "2026-03-12T10:00:00Z",
  "nonce": "unique-per-message-uuid",
  "signature": "base64url(sign(sender_private_key, hash(type+payload+timestamp+nonce)))"
}
```

Upon receipt: resolve sender DID → verify signature → check timestamp window (±5 min) → check nonce not seen before.

**Defense algorithms:**
- **S-Gossip** (Tetarave & Tripathy, 2015): Nodes maintain trust scores for peers; gossip only with nodes above threshold; identified malicious nodes blacklisted
- **SybilWall** (arXiv 2306.15044, 2023): Sybil-resistant aggregation function + probabilistic gossiping; diminishes utility of creating many Sybils

---

### 3.3 HashiCorp Vault with hvac

**Library:** `hvac` v2.4.0 (Oct 2025). Apache 2.0. Python 3.x. Vault v1.4.7+. Synchronous (uses `requests`).

**PyPI:** https://pypi.org/project/hvac/
**Docs:** https://python-hvac.org/en/stable/

#### Authentication Methods

**Token Auth (dev/testing only):**

```python
import hvac
client = hvac.Client(url='http://127.0.0.1:8200', token='s.xxxxxxxxxx')
assert client.is_authenticated()
```

**AppRole Auth (recommended for services):**

```python
client = hvac.Client(url='http://vault.example.com:8200')
response = client.auth.approle.login(
    role_id='b4a68549-1464-7aac-b0cd-d22954985aa8',
    secret_id='6039e2e2-6017-8db9-2e1b-dd6bd449f901'
)
assert client.is_authenticated()

# Secret ID wrapping (best practice for Secret ID delivery):
wrap_response = client.auth.approle.generate_secret_id(role_name='orchestra-agent', wrap_ttl='5m')
wrapping_token = wrap_response['wrap_info']['token']
# Agent unwraps it to get the actual Secret ID:
unwrap_response = client.sys.unwrap(wrapping_token)
secret_id = unwrap_response['data']['secret_id']
```

**Kubernetes Auth (for K8s pods — integrates with T-4.2):**

```python
from hvac.api.auth_methods import Kubernetes
client = hvac.Client(url='http://vault.vault.svc.cluster.local:8200')
with open('/var/run/secrets/kubernetes.io/serviceaccount/token') as f:
    jwt = f.read()
Kubernetes(client.adapter).login(role='orchestra-agent', jwt=jwt)
```

#### KV v2 Secrets Engine

```python
# Write
client.secrets.kv.v2.create_or_update_secret(
    path='agents/did:key:z6Mk.../signing_key',
    secret={'private_key': 'base64-encoded-key', 'algorithm': 'Ed25519'},
    mount_point='secret'
)

# Read latest version
response    = client.secrets.kv.v2.read_secret_version(path='agents/did:key:z6Mk.../signing_key', mount_point='secret')
secret_data = response['data']['data']      # {'private_key': '...'}
version     = response['data']['metadata']['version']

# Read specific version
response = client.secrets.kv.v2.read_secret_version(path='...', version=2, mount_point='secret')

# Patch (partial update)
client.secrets.kv.v2.patch(path='...', secret={'last_rotated': '2026-03-12T00:00:00Z'}, mount_point='secret')

# List
list_response = client.secrets.kv.v2.list_secrets(path='agents/', mount_point='secret')
agent_paths   = list_response['data']['keys']

# Soft delete / undelete / permanent destroy
client.secrets.kv.v2.delete_latest_version_of_secret(path='...', mount_point='secret')
client.secrets.kv.v2.undelete_secret_versions(path='...', versions=[3], mount_point='secret')
client.secrets.kv.v2.destroy_secret_versions(path='...', versions=[1, 2], mount_point='secret')

# Configure max versions
client.secrets.kv.v2.configure(max_versions=10, mount_point='secret')

# Per-key auto-delete after 720 hours
client.secrets.kv.v2.update_metadata(path='...', delete_version_after='720h', mount_point='secret')
```

#### Async Support

**hvac does NOT have native async.** The `async-hvac` library is **unmaintained** (broken docs link from HashiCorp itself) — do not use.

**Recommended: `asyncio.to_thread()` wrapping sync calls:**

```python
async def get_secret(path: str) -> dict:
    client = hvac.Client(url='http://vault:8200', token=token)
    result = await asyncio.to_thread(
        client.secrets.kv.v2.read_secret_version,
        path=path, mount_point='secret'
    )
    return result['data']['data']
```

This is sufficient because secret operations are infrequent (not in the hot path).

#### Retry Configuration

```python
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

retry_strategy = Retry(
    total=3, backoff_factor=1,
    status_forcelist=[412, 500, 502, 503, 504],  # 412 = Vault replication lag
    allowed_methods=["GET", "POST", "PUT", "DELETE", "LIST"],
)
adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=20)
session = requests.Session()
session.mount("http://", adapter)
session.mount("https://", adapter)
client = hvac.Client(url='https://vault.example.com', session=session)
```

**Why 412:** Vault returns HTTP 412 (Precondition Failed) during cluster replication lag. Safe and necessary to retry.

#### Vault Dev Server for Testing

```python
import subprocess, time, hvac, pytest

@pytest.fixture(scope='session')
def vault_dev_server():
    proc = subprocess.Popen(
        ['vault', 'server', '-dev', '-dev-root-token-id=test-root-token'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    time.sleep(2)
    client = hvac.Client(url='http://127.0.0.1:8200', token='test-root-token')
    assert client.is_authenticated()
    yield client
    proc.terminate(); proc.wait()
```

**Testcontainers (recommended for integration tests):**

```python
from testcontainers.vault import VaultContainer

@pytest.fixture(scope='session')
def vault_client():
    with VaultContainer("hashicorp/vault:1.16.1") as vault:
        client = hvac.Client(url=vault.get_connection_url(), token=vault.root_token)
        client.sys.enable_secrets_engine('kv', path='secret', options={'version': '2'})
        yield client
```

#### Agent DID to Secret Path Mapping

```
# Path structure:
{mount_point}/orchestra/agents/{did_method}/{did_id}/{secret_type}

# Example for DID: did:peer:z6Mkf5rGYosrgYLDeNHzirSU47S8awkmFhF7Lxrq9e1BGPRf
secret/orchestra/agents/peer/z6Mkf5rG.../keys        ← Ed25519 signing keys
secret/orchestra/agents/peer/z6Mkf5rG.../credentials ← API keys, NATS creds
secret/orchestra/agents/peer/z6Mkf5rG.../config      ← agent configuration secrets
```

From the 6th source (security/OTel deep dive):

```
secret/
  agents/{did_hash}/
    signing_key       # Ed25519 private key
    encryption_key    # X25519 key
    ucan_root         # Root UCAN token
  services/
    nats/credentials, tls_cert, tls_key
    vault/approle_secret_id
  providers/{name}/
    api_key, org_id
```

---

### 3.4 SecretProvider Abstraction Pattern

```python
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

class SecretProvider(ABC):
    """Abstract interface for secret management in Orchestra."""

    @abstractmethod
    async def get_secret(self, path: str) -> Dict[str, Any]: ...

    @abstractmethod
    async def set_secret(self, path: str, data: Dict[str, Any]) -> None: ...

    @abstractmethod
    async def delete_secret(self, path: str) -> None: ...

    @abstractmethod
    async def health_check(self) -> bool: ...

    async def list_secrets(self, prefix: str) -> list[str]:
        raise NotImplementedError(f"{type(self).__name__} does not support listing")

    def on_rotation(self, path: str, callback) -> None:
        raise NotImplementedError(f"{type(self).__name__} does not support rotation callbacks")


class SecretNotFoundError(Exception): pass
class SecretProviderError(Exception): pass
```

**CachedSecretProvider (TTL-based in-memory cache):**

```python
class CachedSecretProvider:
    def __init__(self, backend: SecretProvider, default_ttl: int = 300):
        self._backend = backend
        self._cache: dict[str, tuple[dict, float]] = {}
        self._default_ttl = default_ttl

    async def get_secret(self, path: str) -> dict:
        if path in self._cache:
            value, expiry = self._cache[path]
            if time.monotonic() < expiry:
                return value
            del self._cache[path]
        value = await self._backend.get_secret(path)
        self._cache[path] = (value, time.monotonic() + self._default_ttl)
        return value

    def invalidate(self, path: str) -> None:
        self._cache.pop(path, None)
```

**Concrete implementations:**

| Backend | Use Case | Notes |
|---------|----------|-------|
| `InMemorySecretProvider` | Unit tests, CI | Zero dependencies, deterministic |
| `FileSecretProvider` | Local development | JSON files in `.secrets/` (gitignored) |
| `VaultSecretProvider` | Staging, production | Uses `asyncio.to_thread()` with hvac |

**Environment selection matrix:**

| Environment | Backend | Auth Method |
|---|---|---|
| Unit tests | `InMemorySecretProvider` | N/A |
| Local development | `FileSecretProvider` | N/A |
| CI/CD pipeline | `VaultSecretProvider` (dev) | Token |
| Kubernetes staging | `VaultSecretProvider` | Kubernetes auth |
| Production | `VaultSecretProvider` | AppRole + K8s |

**What NOT to add:**
- `async-hvac`: Unmaintained
- `aioboto3`, `google-cloud-secret-manager`, `azure-keyvault-secrets`: Not in Wave 2 scope

---

## Part 4: Observability & Context Propagation

### 4.1 OpenTelemetry Baggage Specification

**What is Baggage?** A set of application-defined key-value pairs contextually associated with a distributed request. A **propagation mechanism**, not a storage mechanism.

Key distinction: Baggage values are **not automatically added** to spans, metrics, or logs. They travel alongside the context but require explicit reading and attribution (preventing accidental leakage).

#### API Operations

| Operation | Input | Output | Behavior |
|-----------|-------|--------|----------|
| **Get Value** | `name: string` | `value` or `null` | Returns value for key, or null |
| **Get All Values** | (none) | `Map<string, value>` | Returns all name/value pairs |
| **Set Value** | `name: string, value: string` | `Context` (new) | Returns **new** Context with value set |
| **Remove Value** | `name: string` | `Context` (new) | Returns **new** Context with key removed |

#### Immutability Invariant

The Baggage container is **immutable**. All write operations return a **new Context**. Ensures:
- Thread safety across concurrent execution paths
- Modifications in nested contexts do not affect parent contexts
- Safe use in async/await patterns (Python `contextvars`)

This maps perfectly to Orchestra's delegation chains where each agent invocation creates a new execution scope.

---

### 4.2 W3C Baggage Header Format

```abnf
baggage-string = list-member 0*179( OWS "," OWS list-member )
list-member    = key OWS "=" OWS value *( OWS ";" OWS property )
```

Example:
```
baggage: orchestra.tenant_id=tenant-42,orchestra.delegation_depth=2,orchestra.request_id=abc123;ttl=300
```

**Key naming:** Use alphanumeric + dots + underscores for maximum interoperability. Orchestra convention: `orchestra.` prefix namespace.

**Value encoding:** Limited to `baggage-octet` range (subset of printable ASCII). Characters outside this range MUST be percent-encoded.

**Size Limits:**

| Limit | Value |
|-------|-------|
| Maximum baggage header size | **8192 bytes** total |
| Maximum list-members | **180** key-value pairs |
| Per-member practical limit | **4096 bytes** |

With 8192 bytes total, there is ample room for metadata like tenant IDs and short delegation chains. Full UCAN tokens (500+ bytes each, growing with delegation depth) would quickly exhaust this limit.

---

### 4.3 OTel Python Baggage API

```python
from opentelemetry import baggage
from opentelemetry.context import Context

def set_baggage(name: str, value: object, context: Optional[Context] = None) -> Context: ...
def get_baggage(name: str, context: Optional[Context] = None) -> Optional[object]: ...
def get_all(context: Optional[Context] = None) -> Dict[str, object]: ...
def remove_baggage(name: str, context: Optional[Context] = None) -> Context: ...
def clear(context: Optional[Context] = None) -> Context: ...
```

When `context=None`, all functions operate on the **current active Context** (from `contextvars`).

#### Basic Usage Pattern

```python
from opentelemetry import baggage, trace
from opentelemetry.context import attach, detach

# Set baggage and attach to current context
ctx   = baggage.set_baggage("orchestra.tenant_id", "tenant-42")
ctx   = baggage.set_baggage("orchestra.request_id", "req-abc123", context=ctx)
ctx   = baggage.set_baggage("orchestra.delegation_depth", "0", context=ctx)
token = attach(ctx)
try:
    with tracer.start_as_current_span("process_task") as span:
        tenant = baggage.get_baggage("orchestra.tenant_id")
        span.set_attribute("tenant.id", tenant)  # Explicit attribution
finally:
    detach(token)
```

#### BaggageSpanProcessor

Automatically copies Baggage entries to span attributes on span start:

```bash
pip install opentelemetry-processor-baggage
```

```python
from opentelemetry.processor.baggage import BaggageSpanProcessor
from opentelemetry.sdk.trace import TracerProvider

provider = TracerProvider()

# Option 1: All baggage keys (not recommended in prod — security risk)
from opentelemetry.processor.baggage import ALLOW_ALL_BAGGAGE_KEYS
provider.add_span_processor(BaggageSpanProcessor(ALLOW_ALL_BAGGAGE_KEYS))

# Option 2: Filter with predicate (recommended)
orchestra_only = lambda key: key.startswith("orchestra.")
provider.add_span_processor(BaggageSpanProcessor(orchestra_only))

# Option 3: Exact allowlist (most restrictive, most secure)
from orchestra.observability.baggage_keys import ORCHESTRA_KEY_FILTER
provider.add_span_processor(BaggageSpanProcessor(ORCHESTRA_KEY_FILTER))
```

#### Propagator Setup

```python
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.baggage.propagation import W3CBaggagePropagator

set_global_textmap(CompositePropagator([
    TraceContextTextMapPropagator(),   # traceparent + tracestate headers
    W3CBaggagePropagator(),            # baggage header
]))
```

Note: `OTEL_PROPAGATORS=tracecontext,baggage` in the environment configures this automatically.

---

### 4.4 Baggage Over Non-HTTP Transports (NATS)

#### In-Process Propagation via contextvars

```python
async def orchestrate_workflow(tenant_id: str, delegation_chain: list[str]):
    ctx   = baggage.set_baggage("orchestra.tenant_id", tenant_id)
    ctx   = baggage.set_baggage("orchestra.delegation_chain", ",".join(delegation_chain), context=ctx)
    ctx   = baggage.set_baggage("orchestra.delegation_depth", "0", context=ctx)
    token = attach(ctx)
    try:
        result = await runner.run(workflow, initial_state)
    finally:
        detach(token)
```

**Key behavior with asyncio:** `asyncio.Task` automatically **copies** `contextvars` at task creation time (Python 3.7+). Baggage set before `create_task()` propagates into the new task. Baggage set inside a task does NOT propagate back to the parent. Maps perfectly to Orchestra's fan-out/fan-in parallel node patterns.

#### NATS JetStream Propagation

**Publisher side** — Orchestra's `TaskPublisher._inject_trace_context()` already calls `inject(headers)`:

```python
def _inject_otel_context(headers: dict[str, str]) -> None:
    """Inject OTel W3C trace context + baggage headers."""
    try:
        from opentelemetry.propagate import inject
        inject(headers)  # writes traceparent + baggage when composite propagator is configured
    except ImportError:
        pass
# NOTE: Rename from _inject_trace_context to _inject_otel_context to reflect scope
```

**Consumer side** — CURRENT GAP. `TaskConsumer` does NOT extract context from incoming messages. This breaks distributed traces at the NATS boundary and loses all Baggage:

```python
from opentelemetry.propagate import extract
from opentelemetry.context import attach, detach

async def fetch_and_process(self, handler, batch_size: int = 10):
    msgs = await self._sub.fetch(batch_size, timeout=5.0)
    for msg in msgs:
        incoming_ctx = extract(msg.headers or {})    # reads traceparent + baggage
        incoming_ctx = _sanitize_baggage(incoming_ctx)  # strip unknown keys
        token = attach(incoming_ctx)
        try:
            plaintext = self._provider.decrypt(msg.data.decode("utf-8"))
            await handler(plaintext)
            await msg.ack()
        except Exception:
            await msg.nak()
            raise
        finally:
            detach(token)
```

**Custom NATS header getter** (if NATS returns multi-valued headers):

```python
from opentelemetry.propagators.textmap import Getter

class NatsHeaderGetter(Getter):
    def get(self, carrier: dict, key: str):
        value = carrier.get(key)
        if value is None: return None
        return value if isinstance(value, list) else [value]
    def keys(self, carrier: dict): return list(carrier.keys())

ctx = extract(msg.headers, getter=NatsHeaderGetter())
```

#### Gap Summary for Orchestra

| Gap | Severity | File | Required Change |
|-----|----------|------|-----------------|
| No `BaggageSpanProcessor` registered | Medium | `_otel_setup.py` | Add with `orchestra.*` filter |
| No propagator configuration | Medium | `_otel_setup.py` | Register `CompositePropagator` |
| Context not extracted in consumer | **High** | `consumer.py` | Add `extract()` + `attach()`/`detach()` |
| No Baggage set at workflow entry | **High** | `runner.py` | Set `orchestra.tenant_id`, `request_id` |
| No identity fields in ExecutionContext | Medium | `context.py` | Add `tenant_id`, `delegation_chain`, `ucan_token` |
| No Baggage validation on receipt | Medium | `consumer.py` | Add allowlist + value format validation |
| No Baggage stripping before LLM calls | Medium | `providers/` | Clear Baggage before external HTTP calls |

---

### 4.5 Baggage Security Analysis

Baggage is **plaintext** in HTTP and NATS headers. **Not encrypted, signed, or integrity-protected** by the OTel spec.

| Threat | Risk for Orchestra |
|--------|---------------------|
| Tampering | **High** — a compromised agent could change `delegation_chain` to misrepresent authority |
| Third-party leakage | **High** — auto-instrumented HTTP clients propagate Baggage to external APIs (OpenAI, Anthropic) |
| Injection | Medium — external clients can inject arbitrary keys into incoming requests |
| Eavesdropping | Medium — any intermediary can read Baggage values |

#### Mitigations

**Mitigation 1: Never Put Secrets in Baggage**

```python
# WRONG
ctx = baggage.set_baggage("orchestra.api_key", "sk-...")          # NEVER
ctx = baggage.set_baggage("orchestra.ucan_token", "<500+ byte JWT>")  # NEVER

# RIGHT — non-sensitive correlation identifiers only
ctx = baggage.set_baggage("orchestra.tenant_id", "tenant-42")
ctx = baggage.set_baggage("orchestra.delegation_depth", "2")
```

**Mitigation 2: Validate with Allowlist at Trust Boundaries**

```python
ALLOWED_BAGGAGE_KEYS = frozenset({
    "orchestra.tenant_id",
    "orchestra.delegation_chain",
    "orchestra.request_id",
    "orchestra.cost_center",
    "orchestra.delegation_depth",
    "orchestra.origin_service",
    "orchestra.agent_did",
})

def sanitize_incoming_baggage(ctx: Context) -> Context:
    all_entries = baggage.get_all(ctx)
    for key in list(all_entries.keys()):
        if key not in ALLOWED_BAGGAGE_KEYS:
            ctx = baggage.remove_baggage(key, ctx)
    return ctx
```

**Mitigation 3: Strip Baggage Before External Calls**

```python
def call_external_llm(prompt: str) -> str:
    clean_ctx = baggage.clear()  # Returns new Context with no baggage entries
    token = attach(clean_ctx)
    try:
        response = llm_client.complete(prompt)  # No Orchestra baggage propagated
        return response
    finally:
        detach(token)
```

**Mitigation 4: Value Format Validation**

```python
_VALIDATORS = {
    "orchestra.tenant_id":        re.compile(r"^[a-zA-Z0-9_-]{1,64}$"),
    "orchestra.request_id":       re.compile(r"^[0-9a-f]{32}$"),
    "orchestra.delegation_depth": re.compile(r"^[0-9]{1,3}$"),
    "orchestra.cost_center":      re.compile(r"^[a-zA-Z0-9_-]{1,32}$"),
    "orchestra.agent_did":        re.compile(r"^did:key:z[1-9A-HJ-NP-Za-km-z]{44,}$"),
    "orchestra.delegation_chain": re.compile(
        r"^(did:key:z[1-9A-HJ-NP-Za-km-z]{44,})(,did:key:z[1-9A-HJ-NP-Za-km-z]{44,})*$"
    ),
}
```

**Official OTel guidance:** "Baggage is not encrypted or signed. Sensitive Baggage items can be shared with unintended resources. Validate incoming baggage and use allowlists to strip keys not in the allowlist."

**Mantra: Baggage for observability, UCAN for security.**

---

### 4.6 Hybrid Baggage + UCAN Strategy

```
Layer 1 — Observability Context (OTel Baggage)
  Transport:     HTTP headers / NATS headers / contextvars
  Integrity:     None (unsigned)
  Contents:      tenant_id, request_id, delegation_depth, cost_center
  Purpose:       Span annotation, dashboard queries, cost attribution
  Risk:          Tamperable — NEVER use for authorization decisions

Layer 2 — Security Context (UCAN Token)
  Transport:     ExecutionContext.ucan_token field (in-process)
                 Encrypted NATS message body (cross-process)
  Integrity:     Ed25519 signature + proof chain verification
  Contents:      att (capabilities), fct (budget, delegation facts), prf (chain)
  Purpose:       Authorization decisions, privilege verification, audit trail
  Risk:          Tamper-evident — modification invalidates signature
```

**Why both are needed:**
- Baggage alone is insufficient: any compromised agent can set `orchestra.delegation_chain` to any value
- UCAN alone is insufficient: tokens don't integrate with OTel propagators; too large for transport headers at depth > 2; re-signing overhead

**UCAN `fct` field for signed context propagation:**
- `cost_budget_remaining_usd` in `fct` can be **attenuated** (reduced, never increased) at each hop
- `delegation_depth`, `workflow_id` embedded in `fct` are cryptographically signed
- Cannot be modified without invalidating the Ed25519 signature
- Provides complete, verifiable audit trail of the delegation chain

**Baggage size budget:** Target < 2048 bytes total (25% of W3C max). Recommended keys at typical values consume ~200-400 bytes.

#### Recommended Baggage Keys for Orchestra

| Key | Value Format | Max Length | In Baggage? |
|-----|-------------|-----------|-------------|
| `orchestra.tenant_id` | `[a-zA-Z0-9_-]+` | 64 chars | Yes |
| `orchestra.request_id` | UUID hex | 32 chars | Yes |
| `orchestra.delegation_chain` | Comma-separated DID suffixes | 512 chars | Yes (truncated if needed) |
| `orchestra.delegation_depth` | Integer string `0`-`999` | 3 chars | Yes |
| `orchestra.cost_center` | `[a-zA-Z0-9_-]+` | 32 chars | Yes |
| `orchestra.agent_did` | `did:key:z...` | ~55 chars | Yes (issuing agent only) |
| `orchestra.ucan_token` | Ed25519-signed JWT | 500-2000+ bytes | **No** — in ExecutionContext and encrypted NATS body |

#### Canonical Baggage Keys Module

Place in `src/orchestra/observability/baggage_keys.py`:

```python
"""Orchestra Baggage key constants and validation predicates."""
from __future__ import annotations
import re
from typing import Callable

TENANT_ID        = "orchestra.tenant_id"
REQUEST_ID       = "orchestra.request_id"
DELEGATION_CHAIN = "orchestra.delegation_chain"
DELEGATION_DEPTH = "orchestra.delegation_depth"
COST_CENTER      = "orchestra.cost_center"
ORIGIN_SERVICE   = "orchestra.origin_service"
AGENT_DID        = "orchestra.agent_did"

ALLOWED_KEYS: frozenset[str] = frozenset({
    TENANT_ID, REQUEST_ID, DELEGATION_CHAIN, DELEGATION_DEPTH,
    COST_CENTER, ORIGIN_SERVICE, AGENT_DID,
})

ORCHESTRA_KEY_FILTER: Callable[[str], bool] = lambda key: key in ALLOWED_KEYS

_VALIDATORS: dict[str, re.Pattern] = {
    TENANT_ID:        re.compile(r"^[a-zA-Z0-9_-]{1,64}$"),
    REQUEST_ID:       re.compile(r"^[0-9a-f]{32}$"),
    DELEGATION_DEPTH: re.compile(r"^[0-9]{1,3}$"),
    COST_CENTER:      re.compile(r"^[a-zA-Z0-9_-]{1,32}$"),
    ORIGIN_SERVICE:   re.compile(r"^[a-zA-Z0-9._-]{1,64}$"),
    AGENT_DID:        re.compile(r"^did:key:z[1-9A-HJ-NP-Za-km-z]{44,}$"),
    DELEGATION_CHAIN: re.compile(r"^(did:key:z[1-9A-HJ-NP-Za-km-z]{44,})(,did:key:z[1-9A-HJ-NP-Za-km-z]{44,})*$"),
}

def validate_value(key: str, value: str) -> bool:
    pattern = _VALIDATORS.get(key)
    if pattern is None: return True
    return bool(pattern.match(value))
```

---

## Part 5: Implications for Orchestra Wave 2

### 5.1 T-4.4: CostAwareRouter + ProviderFailover

**From UCAN research:** Encode cost budgets in UCAN `fct` field so budget constraints are cryptographically tied to delegation authority:

```json
{
  "fct": [{
    "cost_budget_remaining_usd": 1.50,
    "cost_budget_initial_usd": 5.00,
    "cost_center": "team-alpha"
  }]
}
```

Attenuation rules ensure child agents cannot grant themselves more budget than their parent received.

**From Baggage research:** Use `orchestra.cost_center` Baggage key to propagate cost attribution across service boundaries for observability. This key flows automatically through NATS headers and is picked up by `BaggageSpanProcessor` to annotate all spans.

**From Vault research:** Provider API keys should be stored in Vault at `secret/orchestra/providers/{provider_name}/api_key` with short TTLs (5 min) and rotated dynamically. The `VaultSecretProvider` fetches them at invocation time, not at startup.

**Key constraint:** Cost budget enforcement (authorization) goes through UCAN `fct`. Cost attribution (observability) goes through OTel Baggage. Do not mix these layers.

---

### 5.2 T-4.5: PersistentBudget

**From UCAN research:** Budget state persists across sessions via UCAN `fct` values. Delegation chain can encode cumulative spending:

```json
"fct": [{
  "budget_initial_usd": 10.00,
  "budget_consumed_usd": 3.75,
  "budget_remaining_usd": 6.25,
  "session_id": "sess-abc123",
  "reset_policy": "daily"
}]
```

**From Vault research:** Persist budget state at `secret/orchestra/agents/{did}/budget`:

```python
await secret_provider.set_secret(
    f"orchestra/agents/{did_id}/budget",
    {"initial_usd": 10.00, "consumed_usd": 3.75, "last_reset": "2026-03-13T00:00:00Z"}
)
```

**From Baggage research:** Do NOT store budget balances in Baggage. Budget enforcement requires cryptographic integrity (UCAN `fct`) and durable persistence (Vault or database). Baggage is for observability only.

**TTL strategy for budget tokens:**

| Scope | TTL | Rationale |
|-------|-----|-----------|
| Root budget UCAN | 24 hours | Single session initialization |
| Orchestrator UCAN | 1 hour | Single orchestration session |
| Tool invocation UCAN | 5 minutes | Per-task, short-lived |
| Vault dynamic secret | 5 minutes | Forces frequent re-auth |

---

### 5.3 T-4.6: AgentIdentity + SignedAgentCards

#### Key Management Pipeline

1. Generate Ed25519 private key: `Ed25519PrivateKey.generate()`
2. Derive X25519 public key from same seed via PyNaCl `to_curve25519_public_key()`
3. Create `did:peer:2` using `peerdid.create_peer_did_numalgo_2()` with both key types
4. Store Ed25519 private key in Vault at `secret/orchestra/agents/{did_id}/keys`
5. For signing cards: `joserfc.jws.serialize_compact()` with `OKPKey` built from Ed25519 key
6. For verifying cards: extract Ed25519 public key from signer's resolved DID Document, then `joserfc.jws.deserialize_compact()`

#### OrchestraAgentCard Schema

```python
from a2a.types import AgentSkill, AgentCapabilities
from pydantic import BaseModel

class OrchestraAgentCard(BaseModel):
    # Standard A2A fields
    name: str
    description: str
    version: str
    url: str
    capabilities: AgentCapabilities
    skills: list[AgentSkill]
    default_input_modes: list[str] = ["text/plain", "application/json"]
    default_output_modes: list[str] = ["application/json"]

    # Orchestra extensions
    did_identity: str          # "did:peer:2.Ez6..." from T-4.1 DIDComm keys
    ucan_root_issuer: str      # DID of the Orchestra root authority for UCAN
    agent_type: str            # "orchestrator" | "tool_agent" | "specialist"
    trust_level: int           # 1-5 trust classification
    valid_until: int           # UTC epoch seconds (TTL)
```

#### SignedDiscoveryProvider

```python
class SignedDiscoveryProvider:
    async def register(self, card: OrchestraAgentCard, signature: bytes, did: str) -> None:
        # 1. Schema validation (JSON Schema)
        # 2. Resolve DID document to get verification key
        # 3. Verify Ed25519 signature over canonical JSON (JCS, RFC 8785)
        # 4. Check rate limits (max 10 registrations/hour per DID)
        # 5. Verify card.valid_until within policy bounds (max 30 days)
        # 6. Store card + provenance: {did, timestamp, signature, content_hash}
        ...

    async def lookup(self, capability: str) -> list[OrchestraAgentCard]:
        # 1. Query matching cards
        # 2. Filter expired cards
        # 3. Check revocation list
        # 4. Verify signatures (or use TTL-cached verification)
        # 5. Return only verified, non-expired, non-revoked cards
        ...

    async def revoke(self, did: str, reason: str) -> None:
        # Add DID to revocation list with timestamp and reason
        ...
```

**Anti-poisoning defense layers apply at registration time** (see Section 3.1 defense strategy).

**Signing flow:**
```
1. Serialize OrchestraAgentCard to JSON
2. Canonicalize using JCS (RFC 8785)
3. Sign with agent's Ed25519 private key → JWS compact serialization
   {"alg": "Ed25519", "kid": "did:peer:2.Ez6...#key-2"}
4. Attach to card.signatures[]
5. Serve at /.well-known/agent-card.json
```

#### Secret Rotation for Signing Keys

1. Generate new Ed25519 key pair
2. Store as new Vault KV v2 version (old version remains during grace period)
3. Create new `did:peer:2` with new keys (DID rotation)
4. Issue new root UCAN signed with new DID key
5. Broadcast rotation event via NATS `orchestra.keys.rotated`
6. Grace period (default 1 hour): accept tokens signed with old or new key
7. After grace period: soft-delete old key version in Vault
8. Add old DID's UCAN CIDs to revocation list

---

### 5.4 T-4.7: UCAN + Short-Lived Capabilities

#### Delegation Topology

```
Admin (root authority)
  |-- issues: orchestra:* / *
  v
Orchestrator Agent (did:key:orchestrator)
  |-- receives root-level UCAN for session (1 hour TTL)
  |-- issues: orchestra:tools/X / tool/invoke  [5 min TTL]
  v
Tool Agent (did:key:tool-agent)
  |-- receives per-tool UCAN from orchestrator
  |-- further delegates: orchestra:tools/X / tool/invoke to subagents [2 min TTL]
  v
Sub-agent (did:key:subagent)
  -- invokes tool with delegated UCAN as Bearer token
```

#### UcanRevocationStore

```python
class UcanRevocationStore:
    """Redis-backed revocation store for UCAN CIDs."""

    def __init__(self, redis_client):
        self.redis = redis_client
        self.local_cache: set[str] = set()

    async def revoke(self, delegation_cid: str, issuer_did: str) -> None:
        key   = f"ucan:revoked:{delegation_cid}"
        value = f"{issuer_did}:{int(time.time())}"
        await self.redis.set(key, value)
        self.local_cache.add(delegation_cid)

    async def is_revoked(self, delegation_cid: str) -> bool:
        if delegation_cid in self.local_cache:
            return True
        return await self.redis.exists(f"ucan:revoked:{delegation_cid}")
```

#### UCAN Verification Pipeline

```
Request with Bearer token (UCAN)
  ↓
1. Extract Bearer token from Authorization header
2. Parse token (ucan.parse) — decode without crypto verification
3. Check token.exp for expiry (fast pre-check)
4. Check CID in revocation store (Redis lookup)
5. Validate delegation chain (ucan.verify):
   a. Verify each Ed25519 signature in chain
   b. Verify aud(proof) == iss(child) at each link
   c. Verify capability attenuation (subset at each hop)
   d. Verify time bound contraction
6. Check fct.cost_budget_remaining_usd >= required cost
7. Dispatch to tool/agent
```

#### UCAN Transport

- UCANs must NOT be propagated via OTel Baggage (size exceeds 4096-byte limit at depth > 2)
- Pass UCANs in dedicated NATS message envelope field (inside encrypted body)
- In-process: via `ExecutionContext.ucan_token`

#### Dependencies for T-4.7

| Package | Version | Purpose |
|---------|---------|---------|
| `py-ucan` | 1.0.0 | UCAN token creation and verification |
| `a2a-sdk` | ~0.3.25 | A2A protocol types for Agent Cards |
| `hvac` | >=2.4.0 | Secret management (VaultSecretProvider) |
| `opentelemetry-processor-baggage` | >=0.48b0 | BaggageSpanProcessor |
| `PyNaCl` | latest | Ed25519-to-X25519 conversion |
| `base58` | latest | Base58btc encoding for peerdid |

#### 5-Layer Security Architecture

```
Layer 1: Transport Security
  → mTLS between services, NATS TLS (T-4.1)

Layer 2: Identity & Auth
  → DID-based identity (T-4.6)
  → UCAN in NATS encrypted envelope (T-4.7)
  → Vault-backed secrets with 5-min TTLs

Layer 3: Data Integrity
  → Signed Agent Cards (Ed25519 JWS, T-4.6)
  → Provenance tracking with content hashes
  → Schema validation on all Cards

Layer 4: Observability Context
  → OTel Baggage for tenant_id/workflow_id/delegation_chain
  → BaggageSpanProcessor auto-enriches all spans
  → Strip Baggage before external LLM calls

Layer 5: Poisoning Defense (T-4.6)
  → Input validation + anomaly detection on Card ingestion
  → Rate limiting per DID (max 10 registrations/hour)
  → Revocation lists checked on every lookup
  → TTL expiry on all Cards and UCAN tokens
```

---

## References

### W3C DID Specifications
- [W3C DID v1.1 Specification](https://www.w3.org/TR/did-1.1/)
- [W3C DID v1.1 Editor's Draft](https://w3c.github.io/did/)
- [DID Specification Registries](https://www.w3.org/TR/did-spec-registries/)
- [DID Resolution v0.3](https://w3c.github.io/did-resolution/)
- [W3C Controlled Identifiers v1.0 (May 2025)](https://www.w3.org/TR/controller-document/)

### DID Methods
- [Peer DID Method Specification](https://identity.foundation/peer-did-method-spec/)
- [did:web Method Specification](https://w3c-ccg.github.io/did-method-web/)
- [did:key Method v0.9](https://w3c-ccg.github.io/did-key-spec/)
- [did:webs Method Specification (Trust over IP)](https://trustoverip.github.io/tswg-did-method-webs-specification/)
- [did-peer-2 (DIF implementation)](https://github.com/decentralized-identity/did-peer-2)
- [peer-did-method-spec GitHub](https://github.com/decentralized-identity/peer-did-method-spec)

### DIDComm
- [DIDComm Messaging v2.1 Specification](https://identity.foundation/didcomm-messaging/spec/v2.1/)
- [DIDComm Messaging Spec on GitHub](https://github.com/decentralized-identity/didcomm-messaging)
- [ECDH-1PU draft4 update (PR #212)](https://github.com/decentralized-identity/didcomm-messaging/pull/212)
- [didcomm-python Library (SICPA)](https://github.com/sicpa-dlab/didcomm-python)

### Ed25519 & Cryptography
- [Ed25519 Official Site (Bernstein et al.)](https://ed25519.cr.yp.to/)
- [RFC 8032: Edwards-Curve Digital Signature Algorithm (EdDSA)](https://datatracker.ietf.org/doc/html/rfc8032)
- [RFC 7748: Elliptic Curves for Diffie-Hellman (X25519/X448)](https://datatracker.ietf.org/doc/html/rfc7748)
- [RFC 8037: CFRG ECDH and Signatures in JOSE (OKP)](https://datatracker.ietf.org/doc/html/rfc8037)
- [RFC 9864: Fully-Specified Algorithms for JOSE (Ed25519/Ed448)](https://datatracker.ietf.org/doc/html/rfc9864)
- [pyca/cryptography Ed25519 Documentation](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/)
- [pyca/cryptography Ed25519-to-X25519 Issue #5557](https://github.com/pyca/cryptography/issues/5557)
- [PyNaCl Documentation](https://pynacl.readthedocs.io/en/latest/)
- [XEdDSA and VXEdDSA Signature Schemes (Signal)](https://signal.org/docs/specifications/xeddsa/)

### JOSE / joserfc
- [joserfc Official Documentation](https://jose.authlib.org/en/)
- [joserfc JWS Guide](https://jose.authlib.org/en/guide/jws/)
- [joserfc RFC 8037 (OKP/EdDSA)](https://jose.authlib.org/en/rfc/8037/)
- [joserfc RFC 9864 (Ed25519/Ed448)](https://jose.authlib.org/en/rfc/9864/)
- [joserfc GitHub Repository](https://github.com/authlib/joserfc)
- [peerdid Python Library (SICPA GitHub)](https://github.com/sicpa-dlab/peer-did-python)

### A2A Protocol & Agent Cards
- [A2A Protocol Specification (latest)](https://a2a-protocol.org/latest/specification/)
- [A2A v0.3 Specification](https://a2a-protocol.org/v0.3.0/specification/)
- [A2A Python SDK (GitHub)](https://github.com/a2aproject/a2a-python)
- [A2A Python SDK (PyPI)](https://pypi.org/project/a2a-sdk/)
- [A2A v0.3 Upgrade Announcement](https://cloud.google.com/blog/products/ai-machine-learning/agent2agent-protocol-is-getting-an-upgrade)
- [Sigstore A2A Agent Signing](https://github.com/sigstore/sigstore-a2a)

### UCAN
- [UCAN Specification (ucan.xyz)](https://ucan.xyz/specification/)
- [UCAN Working Group (GitHub)](https://github.com/ucan-wg)
- [UCAN Delegation Spec](https://github.com/ucan-wg/delegation)
- [UCAN Invocation Spec](https://github.com/ucan-wg/invocation)
- [UCAN Revocation Specification](https://ucan.xyz/revocation/)
- [py-ucan on PyPI](https://pypi.org/project/py-ucan/)
- [zcap-ld Specification (W3C CCG)](https://w3c-ccg.github.io/zcap-spec/)
- [Bitstring Status List (W3C)](https://w3c.github.io/vc-bitstring-status-list/)

### Google Agentic AI Design Patterns
- [Building Scalable AI Agents — Google Cloud Blog](https://cloud.google.com/blog/topics/partners/building-scalable-ai-agents-design-patterns-with-agent-engine-on-google-cloud)
- [Multi-Agent Design Patterns in ADK](https://developers.googleblog.com/developers-guide-to-multi-agent-patterns-in-adk/)

### Agent Memory Poisoning
- [AgentPoison: Red-teaming LLM Agents (NeurIPS 2024, arXiv 2407.12784)](https://arxiv.org/abs/2407.12784)
- [AgentPoison GitHub (AI-secure)](https://github.com/AI-secure/AgentPoison)
- [MemoryGraft: Persistent Compromise of LLM Agents (arXiv 2512.16962)](https://arxiv.org/abs/2512.16962)
- [Zombie Agents: Persistent Control of Self-Evolving LLM Agents (arXiv 2602.15654)](https://arxiv.org/html/2602.15654v1)
- [PoisonedRAG: Knowledge Corruption Attacks (USENIX Security 2025)](https://www.usenix.org/conference/usenixsecurity25/presentation/zou-poisonedrag)
- [Agent Security Bench (ICLR 2025)](https://proceedings.iclr.cc/paper_files/paper/2025/file/5750f91d8fb9d5c02bd8ad2c3b44456b-Paper-Conference.pdf)
- [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/)

### Gossip Protocols for Agentic Systems
- [A Gossip-Enhanced Communication Substrate for Agentic AI (arXiv 2512.03285)](https://arxiv.org/abs/2512.03285)
- [Revisiting Gossip Protocols: Emergent Coordination in Agentic MAS (arXiv 2508.01531)](https://arxiv.org/abs/2508.01531)
- [Byzantine Fault-Tolerant Multi-Agent System (arXiv 2512.17913)](https://arxiv.org/abs/2512.17913)
- [SybilWall — Towards Sybil Resilience in Decentralized Learning (arXiv 2306.15044)](https://arxiv.org/abs/2306.15044)
- [S-Gossip: Security Enhanced Gossip Protocol (Springer)](https://link.springer.com/chapter/10.1007/978-3-319-14977-6_28)

### HashiCorp Vault & Secret Management
- [hvac 2.4.0 Documentation](https://python-hvac.org/en/stable/overview.html)
- [hvac KV v2 Usage Documentation](https://python-hvac.org/en/stable/usage/secrets_engines/kv_v2.html)
- [hvac Auth Methods Documentation](https://python-hvac.org/en/stable/usage/auth_methods/index.html)
- [hvac GitHub](https://github.com/hvac/hvac)
- [Vault KV v2 API Docs (HashiCorp Developer)](https://developer.hashicorp.com/vault/api-docs/secret/kv/kv-v2)
- [Vault Kubernetes Auth Method](https://developer.hashicorp.com/vault/docs/auth/kubernetes)
- [Secure AI Agent Authentication with Vault — Validated Pattern](https://developer.hashicorp.com/validated-patterns/vault/ai-agent-identity-with-hashicorp-vault)
- [Testcontainers Vault Module](https://testcontainers.com/modules/vault/)

### OpenTelemetry Baggage
- [Baggage API | OpenTelemetry](https://opentelemetry.io/docs/specs/otel/baggage/api/)
- [Baggage Concepts | OpenTelemetry](https://opentelemetry.io/docs/concepts/signals/baggage/)
- [W3C Baggage Specification](https://www.w3.org/TR/baggage/)
- [opentelemetry.baggage API docs](https://opentelemetry-python.readthedocs.io/en/stable/api/baggage.html)
- [opentelemetry-processor-baggage on PyPI](https://pypi.org/project/opentelemetry-processor-baggage/)
- [OTel Trace Context Propagation with Message Brokers | Tracetest](https://tracetest.io/blog/opentelemetry-trace-context-propagation-with-message-brokers-and-go)
- [Baggage Security Warnings | OpenTelemetry](https://opentelemetry.io/docs/concepts/signals/baggage/)
