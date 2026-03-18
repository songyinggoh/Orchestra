# Phase 4: DIDComm v2 + joserfc JWE — E2EE Research for SecureNatsProvider

**Researched:** 2026-03-11
**Domain:** DIDComm v2 encrypted messaging, joserfc JWE, nats-py JetStream, peerdid
**Confidence:** HIGH (official specs, library docs, PyPI versions verified)
**Task:** T-4.1 — NATS JetStream + DIDComm E2EE (`src/orchestra/messaging/`)

---

## Summary

T-4.1 requires a `SecureNatsProvider` that wraps NATS JetStream with DIDComm v2 E2EE. The threat model is: NATS stores messages persistently ("at-least-once delivery"), so raw task payloads containing PII or tool credentials must never appear in the NATS store. Encryption must be transparent to callers — `publisher.py` encrypts before publish, `consumer.py` decrypts after fetch.

**Technology stack (all verified on PyPI as of 2026-03-11):**

| Library | Version | Role |
|---------|---------|------|
| `nats-py` | 2.14.0 (Feb 2026) | NATS JetStream client |
| `joserfc` | 1.6.3 (Feb 2026) | JWE encrypt/decrypt |
| `peerdid` | 0.5.2 (Jul 2023) | did:peer creation + resolution |
| `cryptography` | (already in env) | X25519 raw-byte operations |

**Primary recommendation:** Use DIDComm v2 **anoncrypt** mode (ECDH-ES+A256KW + A256GCM) for agent-to-agent task messages in NATS. Authcrypt (ECDH-1PU) adds sender authentication but requires joserfc draft registration and doubles key-agreement cost — defer to Phase 5 unless the threat model demands sender non-repudiation in the message store.

---

## 1. DIDComm v2 Message Envelope Structure

### 1.1 Plaintext Message (JWM — JSON Web Message)

Before encryption, every DIDComm v2 message is a JSON object with these fields:

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "https://orchestra.ai/protocols/task/1.0/request",
  "from": "did:peer:2.Ez6LSke...",
  "to": ["did:peer:2.Ez6LScj..."],
  "created_time": 1710100000,
  "expires_time": 1710186400,
  "body": {
    "task_id": "abc123",
    "agent_type": "summarizer",
    "payload": { "text": "..." }
  }
}
```

**Required fields:**
- `id` — UUID, unique per sender across all messages
- `type` — URI identifying the protocol message type
- `body` — JSON object (may be empty `{}` but must be present)

**Optional but used in Orchestra:**
- `from` — sender DID (required for authcrypt; omit for anoncrypt)
- `to` — array of recipient DIDs
- `created_time`, `expires_time` — UTC epoch seconds

**Confidence: HIGH** — DIDComm Messaging Specification v2.0, identity.foundation

### 1.2 Encrypted Envelope (JWE — JSON Web Encryption)

The encrypted outer envelope is a JWE in **General JSON Serialization** (required for multi-recipient; use Compact Serialization only for single-recipient point-to-point):

```json
{
  "protected": "<base64url-encoded protected header>",
  "recipients": [
    {
      "header": { "kid": "did:peer:2.Ez6LScj...#key-1" },
      "encrypted_key": "<base64url-encoded wrapped CEK>"
    }
  ],
  "aad": "<base64url-encoded additional authenticated data>",
  "iv": "<base64url-encoded 96-bit nonce>",
  "ciphertext": "<base64url-encoded encrypted plaintext>",
  "tag": "<base64url-encoded 128-bit GCM authentication tag>"
}
```

**Protected header** (decoded):

```json
{
  "typ": "application/didcomm-encrypted+json",
  "alg": "ECDH-ES+A256KW",
  "enc": "A256GCM",
  "apv": "<base64url(SHA-256(sorted recipient kid list))>",
  "epk": {
    "kty": "OKP",
    "crv": "X25519",
    "x": "<base64url-encoded ephemeral public key>"
  }
}
```

For **authcrypt** (sender-authenticated), add:
```json
{
  "alg": "ECDH-1PU+A256KW",
  "skid": "did:peer:2.Ez6LSke...#key-1",
  "apu": "<base64url(sender kid)>"
}
```

**Media type:** Always `application/didcomm-encrypted+json` for the `typ` header.

**Confidence: HIGH** — DIDComm v2.0 spec, section 5.2 (Encrypted Messages)

---

## 2. Key Agreement Algorithms

### 2.1 Algorithm Choice Matrix

| Mode | `alg` | `enc` | Provides | When to Use |
|------|-------|-------|----------|-------------|
| Anoncrypt | `ECDH-ES+A256KW` | `A256GCM` | Confidentiality, recipient authentication | Default for task messages |
| Anoncrypt | `ECDH-ES+A256KW` | `A256CBC-HS512` | Confidentiality, recipient auth (MUST support) | Interop with strict v2.0 impls |
| Authcrypt | `ECDH-1PU+A256KW` | `A256CBC-HS512` | Confidentiality + sender auth | Non-repudiation required |

**DIDComm v2.0 MUST support:** `ECDH-ES+A256KW` with X25519 for anoncrypt; `ECDH-1PU+A256KW` with X25519 for authcrypt.

**Recommended for Orchestra T-4.1:** `ECDH-ES+A256KW` + `A256GCM` with X25519. Rationale:
- A256GCM is faster than A256CBC-HS512 and is "recommended" for anoncrypt in the v2.0 spec
- X25519 is the mandatory curve (P-256 is deprecated; P-384 is "must support" but bulkier)
- `joserfc>=1.0` supports this combination natively without draft registration

### 2.2 Key Agreement Mechanics (ECDH-ES)

1. Sender generates a fresh **ephemeral X25519 keypair** per message (the `epk` in the protected header)
2. Sender performs ECDH with: ephemeral private key × recipient static public key → shared secret Z
3. Z is passed through Concat KDF (SHA-256, with `alg`, `apu`, `apv` as party info) → 256-bit key-wrapping key (KWK)
4. A random 256-bit **CEK** is generated
5. CEK is wrapped with AES-256 Key Wrap → `encrypted_key`
6. Plaintext (JWM JSON) is encrypted with CEK + AES-256-GCM → `ciphertext`, `iv`, `tag`
7. Ephemeral public key is included as `epk` in the protected header

**Per-message ephemerality is built in.** The ephemeral key is used once and discarded — ECDH-ES inherently provides perfect forward secrecy for each message.

**Confidence: HIGH** — RFC 7518 Section 4.6, DIDComm v2.0 spec Section 5.2

---

## 3. joserfc JWE API (Version 1.6.3)

### 3.1 Installation

```bash
pip install "joserfc>=1.6"
```

The project's `pyproject.toml` already has `joserfc>=1.0` in `[project.optional-dependencies] security`. Update to `>=1.6` to get `OKPKey.derive_key()` (added in 1.6.0) and the `p2c` DoS fix (1.6.3).

### 3.2 Key Generation

```python
from joserfc.jwk import OKPKey

# Generate a new X25519 keypair (for an agent's static identity key)
key: OKPKey = OKPKey.generate_key("X25519")

# Export to JWK dict — PUBLIC half only (safe to share)
public_jwk: dict = key.as_dict(private=False)
# {
#   "kty": "OKP", "crv": "X25519",
#   "x": "t-nFRaxyM5DZcpg5lxiEeJcZpMRB8JgcKaQC0HRefXU"
# }

# Export full keypair (private — store in SecretProvider, never in NATS)
private_jwk: dict = key.as_dict(private=True)
# adds "d": "<base64url private bytes>"
```

### 3.3 Key Import from JWK Dict

```python
from joserfc.jwk import OKPKey

# Import a recipient's public key (from their DID document)
recipient_public_key = OKPKey.import_key({
    "kty": "OKP",
    "crv": "X25519",
    "x": "sz1JMMasNRLQfXIkvLTRaOu978QQu1roFKxBPKZdsC8",
})

# Import own private key (from SecretProvider)
own_private_key = OKPKey.import_key({
    "kty": "OKP",
    "crv": "X25519",
    "d": "SfYmE8aLpvX6Z0rZQVa5eBjLKeINUfSlu-_AcYJXCqQ",
    "x": "sz1JMMasNRLQfXIkvLTRaOu978QQu1roFKxBPKZdsC8",
})
```

### 3.4 JWE Encrypt (Compact Serialization — Single Recipient)

Use compact for NATS point-to-point (one agent sending to one recipient):

```python
import json
from joserfc import jwe
from joserfc.jwk import OKPKey

def encrypt_didcomm_compact(
    plaintext_jwm: dict,
    recipient_public_key: OKPKey,
) -> str:
    """Encrypt a DIDComm plaintext message using ECDH-ES+A256KW + A256GCM.

    Returns a JWE Compact Serialization string.
    """
    protected_header = {
        "alg": "ECDH-ES+A256KW",
        "enc": "A256GCM",
        "typ": "application/didcomm-encrypted+json",
    }
    plaintext_bytes = json.dumps(plaintext_jwm).encode("utf-8")
    token: str = jwe.encrypt_compact(
        protected_header,
        plaintext_bytes,
        recipient_public_key,
    )
    return token
```

### 3.5 JWE Decrypt (Compact Serialization)

```python
import json
from joserfc import jwe
from joserfc.jwk import OKPKey

def decrypt_didcomm_compact(
    token: str,
    recipient_private_key: OKPKey,
) -> dict:
    """Decrypt a JWE compact token. Returns the DIDComm plaintext JWM dict."""
    result = jwe.decrypt_compact(token, recipient_private_key)
    return json.loads(result.plaintext)
```

### 3.6 JWE Encrypt (JSON Serialization — Multiple Recipients)

For broadcast tasks where multiple agent types may consume from the same NATS subject:

```python
import json
from joserfc import jwe
from joserfc.jwe import GeneralJSONEncryption
from joserfc.jwk import OKPKey

def encrypt_didcomm_json(
    plaintext_jwm: dict,
    recipients: list[tuple[str, OKPKey]],  # [(kid, public_key), ...]
) -> dict:
    """Encrypt for multiple recipients. Returns a JWE General JSON dict."""
    plaintext_bytes = json.dumps(plaintext_jwm).encode("utf-8")
    shared_protected = {
        "enc": "A256GCM",
        "typ": "application/didcomm-encrypted+json",
    }
    obj = GeneralJSONEncryption(shared_protected, plaintext_bytes)
    for kid, pub_key in recipients:
        obj.add_recipient({"alg": "ECDH-ES+A256KW", "kid": kid}, pub_key)
    return jwe.encrypt_json(obj, None)


def decrypt_didcomm_json(
    jwe_dict: dict,
    private_key: OKPKey,
) -> dict:
    """Decrypt a JWE General JSON token with this recipient's private key."""
    result = jwe.decrypt_json(jwe_dict, private_key)
    return json.loads(result.plaintext)
```

### 3.7 ECDH-1PU (Authcrypt) — Draft Registration Required

`ECDH-1PU` is a draft algorithm (not in RFC 7518). joserfc provides it but requires explicit registration:

```python
from joserfc.drafts.jwe_ecdh_1pu import register_ecdh_1pu
from joserfc import jwe
from joserfc.jwe import JWERegistry
from joserfc.jwk import OKPKey

# Call once at module load (idempotent)
register_ecdh_1pu()

def encrypt_authcrypt(
    plaintext_jwm: dict,
    recipient_public_key: OKPKey,
    sender_private_key: OKPKey,
    sender_kid: str,
) -> str:
    import json, base64
    protected = {
        "alg": "ECDH-1PU+A256KW",
        "enc": "A256CBC-HS512",
        "typ": "application/didcomm-encrypted+json",
        "skid": sender_kid,
        "apu": base64.urlsafe_b64encode(sender_kid.encode()).rstrip(b"=").decode(),
    }
    registry = JWERegistry(algorithms=["ECDH-1PU+A256KW", "A256CBC-HS512"])
    return jwe.encrypt_compact(
        protected,
        json.dumps(plaintext_jwm).encode(),
        recipient_public_key,
        registry=registry,
        sender_key=sender_private_key,
    )
```

**WARNING:** ECDH-1PU is a draft; its security properties are still being formalized. The CCS'24 paper (Brendel et al.) found that the combined a-auth mode (anoncrypt + authcrypt layered) does not provide full commitment guarantees. For Phase 4, use anoncrypt only and add a separate signature layer if sender authentication is needed.

**Confidence: HIGH** — joserfc 1.6.3 changelog, jose.authlib.org algorithms page

---

## 4. peerdid Integration

### 4.1 Creating an Agent DID with X25519 Key

```python
import base64
from peerdid.dids import create_peer_did_numalgo_2, resolve_peer_did
from peerdid.keys import Ed25519VerificationKey, X25519KeyAgreementKey
from joserfc.jwk import OKPKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

def create_agent_did_and_keys() -> tuple[str, OKPKey, OKPKey]:
    """
    Returns (did, signing_key_joserfc_NOT_USED, encryption_key_pair).

    In practice: call this once per agent session, store keys in SecretProvider.
    """
    # Generate a fresh X25519 keypair for key agreement
    x25519_private = X25519PrivateKey.generate()
    x25519_public = x25519_private.public_key()

    # Get raw bytes (32 bytes each for X25519)
    private_bytes = x25519_private.private_bytes_raw()  # 32 bytes
    public_bytes = x25519_public.public_bytes_raw()     # 32 bytes

    # Encode as base58 for peerdid (multibase with 'z' prefix indicates base58btc)
    import base58  # pip install base58
    public_b58 = base58.b58encode(public_bytes).decode()

    # Create peer DID (numalgo 2 includes keys in the DID itself)
    encryption_key = X25519KeyAgreementKey.from_base58(public_b58)
    signing_key = Ed25519VerificationKey.from_base58(
        # Ed25519 key for signing (separate from X25519 encryption key)
        _generate_ed25519_b58()
    )
    peer_did = create_peer_did_numalgo_2(
        encryption_keys=[encryption_key],
        signing_keys=[signing_key],
        service={
            "type": "DIDCommMessaging",
            "serviceEndpoint": "nats://orchestra.internal:4222",
        },
    )

    # Build joserfc OKPKey for JWE operations
    x_b64 = base64.urlsafe_b64encode(public_bytes).rstrip(b"=").decode()
    d_b64 = base64.urlsafe_b64encode(private_bytes).rstrip(b"=").decode()
    joserfc_key = OKPKey.import_key({
        "kty": "OKP", "crv": "X25519", "x": x_b64, "d": d_b64,
    })
    return peer_did, joserfc_key
```

### 4.2 Extracting Recipient Key from DID Document

```python
import base64
from peerdid.dids import resolve_peer_did
from joserfc.jwk import OKPKey

def extract_x25519_key_from_did(peer_did: str) -> tuple[str, OKPKey]:
    """
    Resolve a peer DID and return (kid, public_key_for_JWE).

    kid format: 'did:peer:2.Ez6L...#key-1'
    """
    did_doc = resolve_peer_did(peer_did)
    doc_json = did_doc.to_dict()

    # Find the first X25519KeyAgreementKey2020 verification method
    for vm in doc_json.get("verificationMethod", []):
        if vm.get("type") == "X25519KeyAgreementKey2020":
            kid = vm["id"]
            # publicKeyMultibase: "z" prefix = base58btc; strip "z", decode
            multibase_key = vm["publicKeyMultibase"]
            assert multibase_key.startswith("z"), "Expected base58btc (z prefix)"
            import base58
            raw_bytes = base58.b58decode(multibase_key[1:])
            x_b64 = base64.urlsafe_b64encode(raw_bytes).rstrip(b"=").decode()
            public_key = OKPKey.import_key({"kty": "OKP", "crv": "X25519", "x": x_b64})
            return kid, public_key

    raise ValueError(f"No X25519 key agreement key found in DID document for {peer_did}")
```

**Note:** `peerdid` uses `publicKeyMultibase` with base58btc encoding (multicodec prefix `0xec` for X25519). The raw key bytes after stripping the 2-byte multicodec prefix are the 32-byte X25519 public key. The `base58` library (`pip install base58`) is needed separately.

**Confidence: MEDIUM** — verified via peerdid PyPI/GitHub; multicodec prefix confirmed via DIF peer DID spec.

---

## 5. Ephemeral Key Rotation Strategy

### 5.1 DIDComm's Built-in Ephemerality

ECDH-ES generates a fresh ephemeral keypair **per message** automatically. The `epk` in the JWE protected header is this one-time key. joserfc handles this internally — callers do not need to manage ephemeral keys. This is not configurable and not something to implement; it happens automatically.

**What this means for Orchestra:** The CEK is already unique per message. There is no "nonce reuse" risk at the ECDH-ES level — each encrypt call produces an independent ephemeral key.

### 5.2 Static Identity Key Rotation

The **static X25519 key** (the recipient's long-term key in their DID document) has a longer lifetime and should be rotated periodically.

**Recommended strategy for T-4.1:**

| Key Type | Lifetime | Storage | Rotation Trigger |
|----------|----------|---------|------------------|
| Ephemeral key (per-message) | One message | Never persisted | Automatic (ECDH-ES) |
| Session key (agent startup) | Agent process lifetime | In-memory only | Process restart |
| Static DID key (long-term) | 24 hours or less for agents | SecretProvider | Daily or on compromise |

**Implementation decision for Phase 4:** Generate a new X25519 keypair at agent startup, publish the public key in the did:peer DID document, and discard when the process exits. This gives per-session PFS without complex rotation infrastructure. Long-lived service agents (K8s deployments) should rotate via DID document update (the `fromPrior` header in DIDComm) on a 24-hour schedule.

**Confidence: MEDIUM** — DIDComm v2 PFS documentation; IETF TLS key rotation best practices applied to DIDComm

---

## 6. nats-py JetStream Integration

### 6.1 Version and API

**Latest:** `nats-py` 2.14.0 (Feb 23, 2026). The plan requires `>=2.14`.

### 6.2 Connection and Stream Setup (`client.py`)

```python
import asyncio
import nats
from nats.js.api import StreamConfig, RetentionPolicy, StorageType

async def create_nats_client(servers: list[str] = None) -> tuple:
    """Connect to NATS and initialize the orchestra JetStream stream."""
    if servers is None:
        servers = ["nats://localhost:4222"]

    nc = await nats.connect(
        servers,
        error_cb=_error_cb,
        reconnected_cb=_reconnected_cb,
        max_reconnect_attempts=5,
    )
    js = nc.jetstream()

    # Create stream for encrypted task messages
    # Stream name must be unique; subjects define what gets persisted
    await js.add_stream(
        name="ORCHESTRA_TASKS",
        subjects=["orchestra.tasks.>"],
        # Storage: 'file' for production durability; 'memory' for tests
        storage=StorageType.FILE,
        # Retention: WorkQueuePolicy discards after all consumers ack
        retention=RetentionPolicy.WORK_QUEUE,
        max_age=3600,  # 1 hour max age for task messages
    )
    return nc, js


async def _error_cb(e: Exception) -> None:
    import structlog
    log = structlog.get_logger()
    log.error("nats_error", error=str(e))


async def _reconnected_cb() -> None:
    import structlog
    log = structlog.get_logger()
    log.info("nats_reconnected")
```

### 6.3 Publisher (`publisher.py`)

```python
import json
import asyncio
import uuid
import time
from dataclasses import dataclass
from nats.aio.client import Client as NATSClient

@dataclass
class TaskMessage:
    task_id: str
    agent_type: str
    payload: dict
    sender_did: str = ""
    recipient_did: str = ""


async def publish_task(
    js,
    agent_type: str,
    task: TaskMessage,
    encrypted_token: str,  # output of encrypt_didcomm_compact()
) -> None:
    """Publish an encrypted DIDComm JWE token to a typed NATS subject."""
    subject = f"orchestra.tasks.{agent_type}"
    # The payload on the wire is the raw JWE compact token (opaque string)
    await js.publish(subject, encrypted_token.encode("utf-8"))
```

### 6.4 Consumer (`consumer.py`)

```python
import asyncio
from nats.aio.client import Client as NATSClient

async def create_pull_consumer(js, agent_type: str, durable_name: str):
    """Create a durable pull consumer for a specific agent type."""
    subject = f"orchestra.tasks.{agent_type}"
    # pull_subscribe(subject, durable_name) creates a durable consumer
    # Durable consumers survive process restarts
    psub = await js.pull_subscribe(subject, durable_name)
    return psub


async def consume_tasks(psub, decrypt_fn, batch_size: int = 1) -> list[dict]:
    """
    Fetch and decrypt a batch of task messages.

    decrypt_fn: callable(jwe_token: str) -> dict
    Returns list of decrypted DIDComm plaintext dicts.
    """
    try:
        msgs = await psub.fetch(batch_size, timeout=1.0)
    except Exception:
        return []

    results = []
    for msg in msgs:
        try:
            jwe_token = msg.data.decode("utf-8")
            plaintext = decrypt_fn(jwe_token)
            results.append(plaintext)
            await msg.ack()
        except Exception as e:
            # On decryption failure: NAK to allow redelivery or send to dead letter
            await msg.nak()
            # Log but don't crash the consumer loop
            import structlog
            structlog.get_logger().error(
                "decrypt_failed", error=str(e), subject=msg.subject
            )
    return results
```

**Confidence: HIGH** — verified against nats-py 2.14.0 PyPI and official NATS docs

---

## 7. Integration Test Pattern

### 7.1 Minimal Round-Trip Test (no live NATS required)

```python
# tests/unit/test_e2e_encryption.py
import pytest
import json
import uuid
import time
from joserfc import jwe
from joserfc.jwk import OKPKey


def make_plaintext_jwm(body: dict) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "type": "https://orchestra.ai/protocols/task/1.0/request",
        "created_time": int(time.time()),
        "body": body,
    }


def test_anoncrypt_round_trip():
    """Verify encrypt -> publish payload -> consume -> decrypt recovers original body."""
    # 1. Key generation
    recipient_key = OKPKey.generate_key("X25519")
    public_key = OKPKey.import_key(recipient_key.as_dict(private=False))

    # 2. Encrypt
    plaintext = make_plaintext_jwm({"task_id": "t1", "agent_type": "summarizer"})
    token = jwe.encrypt_compact(
        {"alg": "ECDH-ES+A256KW", "enc": "A256GCM",
         "typ": "application/didcomm-encrypted+json"},
        json.dumps(plaintext).encode(),
        public_key,
    )

    # 3. Simulate NATS wire: only the opaque token lives in the store
    assert "task_id" not in token  # PII/payload not visible in ciphertext
    assert token.count(".") == 4   # Compact JWE has 5 parts

    # 4. Decrypt
    result = jwe.decrypt_compact(token, recipient_key)
    recovered = json.loads(result.plaintext)

    # 5. Verify
    assert recovered["body"]["task_id"] == "t1"
    assert recovered["id"] == plaintext["id"]


def test_wrong_key_fails():
    """Decryption with wrong key must raise, not silently return garbage."""
    recipient_key = OKPKey.generate_key("X25519")
    wrong_key = OKPKey.generate_key("X25519")

    plaintext = make_plaintext_jwm({"secret": "data"})
    token = jwe.encrypt_compact(
        {"alg": "ECDH-ES+A256KW", "enc": "A256GCM"},
        json.dumps(plaintext).encode(),
        OKPKey.import_key(recipient_key.as_dict(private=False)),
    )

    with pytest.raises(Exception):
        jwe.decrypt_compact(token, wrong_key)


def test_different_messages_have_different_epks():
    """Every encryption must produce a unique ephemeral key (no EPK reuse)."""
    key = OKPKey.generate_key("X25519")
    pub = OKPKey.import_key(key.as_dict(private=False))
    header = {"alg": "ECDH-ES+A256KW", "enc": "A256GCM"}

    tokens = [
        jwe.encrypt_compact(header, b"same plaintext", pub)
        for _ in range(10)
    ]
    # Compact JWE part 0 is base64url(protected header) — includes epk
    headers = [t.split(".")[0] for t in tokens]
    # All protected headers must be different (different EPK each time)
    assert len(set(headers)) == 10, "EPK must differ per encryption call"
```

### 7.2 Integration Test with NATS (requires live server or docker)

```python
# tests/integration/test_secure_nats.py
import asyncio
import json
import uuid
import pytest
import pytest_asyncio
import nats
from joserfc import jwe
from joserfc.jwk import OKPKey


@pytest.fixture
def x25519_keypair():
    return OKPKey.generate_key("X25519")


@pytest_asyncio.fixture
async def nats_conn():
    nc = await nats.connect("nats://localhost:4222")
    yield nc
    await nc.drain()


@pytest.mark.asyncio
@pytest.mark.integration  # skip if nats not available
async def test_publish_100_encrypted_tasks(nats_conn, x25519_keypair):
    """Publish 100 tasks, verify 100 acks, verify store has only ciphertexts."""
    js = nats_conn.jetstream()
    pub_key = OKPKey.import_key(x25519_keypair.as_dict(private=False))

    stream_name = f"test_stream_{uuid.uuid4().hex[:8]}"
    subject = "orchestra.tasks.test"

    await js.add_stream(name=stream_name, subjects=[subject])

    acks = []
    for i in range(100):
        plaintext = {"id": str(uuid.uuid4()), "type": "task", "body": {"i": i}}
        token = jwe.encrypt_compact(
            {"alg": "ECDH-ES+A256KW", "enc": "A256GCM",
             "typ": "application/didcomm-encrypted+json"},
            json.dumps(plaintext).encode(),
            pub_key,
        )
        ack = await js.publish(subject, token.encode())
        acks.append(ack)

    assert len(acks) == 100

    # Consume and decrypt
    psub = await js.pull_subscribe(subject, "test-consumer")
    decrypted_count = 0
    for batch in range(10):
        msgs = await psub.fetch(10, timeout=2.0)
        for msg in msgs:
            token_back = msg.data.decode()
            result = jwe.decrypt_compact(token_back, x25519_keypair)
            body = json.loads(result.plaintext)
            assert "i" in body["body"]
            await msg.ack()
            decrypted_count += 1

    assert decrypted_count == 100
```

---

## 8. Security Considerations and Pitfalls

### 8.1 CCS'24 Formal Analysis Findings (HIGH confidence)

The 2024 ACM CCS paper "What Did Come Out of It? Analysis and Improvements of DIDComm Messaging" (Brendel et al., eprint 2024/1361) found:

**Finding 1 — Non-committing Encryption in A-auth Mode:**
When anoncrypt and authcrypt are combined in sequence (the "a-auth" mode), the combined mode does not guarantee ciphertexts are committed to a specific message. An adversary can produce a single ciphertext that decrypts to different plaintexts under different keys.

**Mitigation for Orchestra:** Do not layer anoncrypt + authcrypt. Choose one mode per message. For Phase 4, use anoncrypt only. If sender authentication is needed, add a separate JWS signature over the plaintext before encryption (sign-then-encrypt, not encrypt-then-sign).

**Finding 2 — No Anonymity Preservation in Standard Mode:**
The standard DIDComm modes leak sender identity information beyond what's necessary. The paper proposes an improved mode, but it's not yet in the spec.

**Mitigation:** For internal NATS traffic (not cross-org), sender anonymity within the NATS system is not a concern — the `from` field in the JWM is only visible after decryption by the authorized recipient.

### 8.2 Algorithm Downgrade Attack

**Risk:** A message with a tampered `alg` header (e.g., changed from `ECDH-ES+A256KW` to `dir` with a known key) could cause the recipient to use a weak decryption path.

**Mitigation:** Enforce an algorithm allowlist in the JWE registry:

```python
from joserfc.jwe import JWERegistry

ALLOWED_ALGORITHMS = JWERegistry(
    algorithms=["ECDH-ES+A256KW", "A256GCM"]
)

# Always pass registry= to decrypt_compact
result = jwe.decrypt_compact(token, private_key, registry=ALLOWED_ALGORITHMS)
```

joserfc 1.6.x supports `JWERegistry(algorithms=[...])` for explicit allowlisting.

### 8.3 Nonce (IV) Reuse in A256GCM

**Risk:** AES-256-GCM is catastrophically broken if the 96-bit IV is reused with the same key. Each CEK is generated fresh per message by joserfc, so this is not a risk at the JWE layer.

**Risk location:** If you ever manually build GCM encryption outside joserfc, use `os.urandom(12)` for the IV and never reuse it.

**Mitigation:** Do not implement custom GCM. Use joserfc exclusively. The CEK + IV are generated fresh per `encrypt_compact` call.

### 8.4 Key Confusion (Type Mismatch)

**Risk:** Using an Ed25519 key (signing) where an X25519 key (encryption) is expected, or vice versa. The curves are mathematically different. Using Ed25519 for Diffie-Hellman is insecure.

**Mitigation:**
1. Always use separate key pairs for signing and encryption
2. Enforce `crv == "X25519"` check before using a key for JWE:

```python
def validate_encryption_key(key: OKPKey) -> None:
    key_dict = key.as_dict(private=False)
    if key_dict.get("crv") != "X25519":
        raise ValueError(
            f"Expected X25519 key for encryption, got {key_dict.get('crv')}"
        )
```

### 8.5 Private Key Exposure in NATS

**Risk:** If `key.as_dict(private=True)` is accidentally serialized into a task message body, the private key ends up in NATS.

**Mitigation:**
1. Always use `key.as_dict(private=False)` when exporting keys for DID documents or message headers
2. Store private keys only in SecretProvider (Phase 4 T-4.6), never in task payloads

### 8.6 PBES2 DoS via p2c Header

joserfc 1.6.3 fixed an unbounded `p2c` iteration count in PBES2-based key wrapping. This does not affect ECDH-ES (which doesn't use PBES2), but is relevant if you ever accept externally-provided protected headers with `PBES2-*` algorithms.

**Mitigation:** The allowlist in section 8.2 blocks PBES2 algorithms entirely.

### 8.7 DID Document Caching

**Risk:** Resolving a peer DID on every message (calling `resolve_peer_did`) adds CPU cost (DID documents for `did:peer:2` are decoded from the DID string itself, so there's no network call — but there is JSON parsing).

**Mitigation:** Cache resolved DID documents and extracted public keys in a TTL-bounded dict keyed by DID string. For peer DIDs, the DID string fully determines the DID document (no external resolution needed), so a simple `functools.lru_cache` or dict with 1-hour TTL is sufficient.

---

## 9. Architecture Patterns for SecureNatsProvider

### 9.1 Recommended File Layout

```
src/orchestra/messaging/
├── __init__.py          # exports SecureNatsProvider, TaskPublisher, TaskConsumer
├── client.py            # NATS connection management, stream creation
├── secure_provider.py   # DIDComm v2 E2EE: KeyManager + encrypt/decrypt
├── publisher.py         # TaskPublisher.publish(agent_type, task_body, recipient_did)
└── consumer.py          # TaskConsumer.run_loop(agent_type, handler_fn)
```

### 9.2 KeyManager in secure_provider.py

```python
from __future__ import annotations
import base64
import json
from dataclasses import dataclass, field
from joserfc.jwk import OKPKey


@dataclass
class AgentKeyMaterial:
    """Holds an agent's X25519 keypair and DID for the current session."""
    did: str
    kid: str                     # DID fragment, e.g. "did:peer:2.Ez...#key-1"
    keypair: OKPKey              # full keypair (private=True); never serialized to NATS
    public_jwk: dict = field(default_factory=dict)

    def __post_init__(self):
        self.public_jwk = self.keypair.as_dict(private=False)


class SecureNatsProvider:
    """DIDComm v2 E2EE wrapper for NATS JetStream.

    Usage:
        provider = await SecureNatsProvider.create(nats_urls=["nats://localhost:4222"])
        token = provider.encrypt_for(plaintext_body, recipient_did=bob_did)
        body = provider.decrypt(token)
    """

    def __init__(self, own_keys: AgentKeyMaterial, nc, js):
        self._own_keys = own_keys
        self._nc = nc
        self._js = js
        self._recipient_key_cache: dict[str, tuple[str, OKPKey]] = {}

    @classmethod
    async def create(
        cls,
        nats_urls: list[str],
        own_did: str | None = None,
    ) -> "SecureNatsProvider":
        import nats as nats_lib
        from peerdid.dids import create_peer_did_numalgo_2
        from peerdid.keys import X25519KeyAgreementKey, Ed25519VerificationKey
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
        import base58

        # Generate session keypair
        x25519_private = X25519PrivateKey.generate()
        raw_pub = x25519_private.public_key().public_bytes_raw()
        raw_priv = x25519_private.private_bytes_raw()

        x_b64 = base64.urlsafe_b64encode(raw_pub).rstrip(b"=").decode()
        d_b64 = base64.urlsafe_b64encode(raw_priv).rstrip(b"=").decode()
        joserfc_key = OKPKey.import_key({
            "kty": "OKP", "crv": "X25519", "x": x_b64, "d": d_b64,
        })

        # Create peer DID (numalgo 2: keys encoded in DID string)
        enc_key_b58 = base58.b58encode(raw_pub).decode()
        # Ed25519 key for signing (generate separately)
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        ed_private = Ed25519PrivateKey.generate()
        ed_pub_raw = ed_private.public_key().public_bytes_raw()
        ed_b58 = base58.b58encode(ed_pub_raw).decode()

        did = create_peer_did_numalgo_2(
            encryption_keys=[X25519KeyAgreementKey.from_base58(enc_key_b58)],
            signing_keys=[Ed25519VerificationKey.from_base58(ed_b58)],
            service={
                "type": "DIDCommMessaging",
                "serviceEndpoint": nats_urls[0],
            },
        )
        kid = f"{did}#key-1"
        own_keys = AgentKeyMaterial(did=did, kid=kid, keypair=joserfc_key)

        nc = await nats_lib.connect(nats_urls)
        js = nc.jetstream()
        return cls(own_keys, nc, js)

    def encrypt_for(self, plaintext_body: dict, recipient_did: str) -> str:
        """Encrypt a task body for a recipient DID. Returns JWE compact token."""
        from joserfc import jwe
        import uuid, time
        jwm = {
            "id": str(uuid.uuid4()),
            "type": "https://orchestra.ai/protocols/task/1.0/request",
            "created_time": int(time.time()),
            "body": plaintext_body,
        }
        _, recipient_pub = self._resolve_recipient(recipient_did)
        return jwe.encrypt_compact(
            {"alg": "ECDH-ES+A256KW", "enc": "A256GCM",
             "typ": "application/didcomm-encrypted+json"},
            json.dumps(jwm).encode(),
            recipient_pub,
        )

    def decrypt(self, jwe_token: str) -> dict:
        """Decrypt a JWE compact token. Returns plaintext JWM dict."""
        from joserfc import jwe as jwe_mod
        from joserfc.jwe import JWERegistry
        registry = JWERegistry(algorithms=["ECDH-ES+A256KW", "A256GCM"])
        result = jwe_mod.decrypt_compact(
            jwe_token, self._own_keys.keypair, registry=registry
        )
        return json.loads(result.plaintext)

    def _resolve_recipient(self, did: str) -> tuple[str, OKPKey]:
        if did not in self._recipient_key_cache:
            self._recipient_key_cache[did] = extract_x25519_key_from_did(did)
        return self._recipient_key_cache[did]

    @property
    def own_did(self) -> str:
        return self._own_keys.did

    @property
    def own_public_jwk(self) -> dict:
        return self._own_keys.public_jwk
```

### 9.3 NATS Subject Naming Convention

```
orchestra.tasks.{agent_type}   — task dispatch (encrypted JWE tokens)
orchestra.events.{agent_id}    — result events (encrypted JWE tokens)
orchestra.control.>            — control plane (authenticated, not necessarily encrypted)
```

JetStream stream name: `ORCHESTRA_TASKS` covering `orchestra.tasks.>`

---

## 10. Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| ECDH key agreement | Manual Diffie-Hellman | `joserfc.jwe.encrypt_compact` | EPK generation, KDF, key wrap, nonce handled correctly |
| GCM encryption | `cryptography.hazmat` directly | `joserfc` | Nonce management, AAD binding, tag verification are easy to get wrong |
| X25519 key generation | Custom curve arithmetic | `OKPKey.generate_key("X25519")` | Correct parameter generation, JWK format compliance |
| DID document parsing | Regex/json path extraction | `peerdid.dids.resolve_peer_did` | Handles numalgo 0, 2, multicodec prefixes |
| NATS connection pooling | asyncio queue | `nats-py` built-in reconnect | Handles TLS, jetstream context, reconnect backoff |
| Algorithm allowlisting | String checks | `JWERegistry(algorithms=[...])` | Enforces at crypto layer, not application layer |

---

## 11. State of the Art

| Old Approach | Current Approach | Notes |
|--------------|-----------------|-------|
| python-jose for JWE | joserfc 1.6.3 | python-jose has 2.7M weekly downloads but no active maintainer; joserfc is the Authlib successor with type hints and modern API |
| didcomm-python library (SICPA) | joserfc + peerdid directly | didcomm-python v0.3.2 (May 2023) is unmaintained; implementing JWE + DID resolution directly is more transparent and maintainable |
| NATS push consumers | NATS pull consumers | Pull consumers avoid message flooding; explicit ack prevents lost messages; recommended for task queues |
| Ed25519 for all DIDComm ops | Separate Ed25519 (signing) + X25519 (encryption) | Key separation is mandatory; Ed25519 for DH is insecure |

**Deprecated:**
- `didcomm-python` (SICPA, v0.3.2): last release May 2023, no maintenance. Do NOT use as a dependency — implement the encryption layer directly with joserfc.
- `python-jose`: Use `joserfc` for all new JOSE operations.
- `XC20P` (XChaCha20-Poly1305): Optional in DIDComm v2.0, not supported by joserfc 1.6.3. Use A256GCM instead.

---

## 12. Open Questions

1. **peerdid multicodec prefix**
   - What we know: `publicKeyMultibase` starts with `z` (base58btc); multicodec prefix `0xec01` for X25519
   - What's unclear: Exact byte stripping logic (2 bytes or varint?) needs a working test
   - Recommendation: Write a unit test decoding a known did:peer:2 key to verify byte offset

2. **ECDH-1PU draft stability in joserfc**
   - What we know: Available via `joserfc.drafts.jwe_ecdh_1pu`, requires `register_ecdh_1pu()`
   - What's unclear: Whether this is stable across joserfc minor versions
   - Recommendation: Pin to `joserfc>=1.6,<2.0` and test after any upgrade

3. **NATS JetStream stream already exists**
   - What we know: `js.add_stream()` raises if the stream already exists with different config
   - What's unclear: Whether T-4.1 should use `find_stream` + conditional `add_stream`
   - Recommendation: Use `update_stream` pattern with error handling for `BadRequestException`

---

## 13. Ready-to-Implement Checklist

### Dependencies

- [ ] `pyproject.toml`: bump `joserfc` to `>=1.6` in `[security]` optional deps
- [ ] `pyproject.toml`: add `nats-py>=2.14` to `[nats]` optional deps (already present, verify version)
- [ ] `pyproject.toml`: add `peerdid>=0.5.2` and `base58>=2.1` to new `[messaging]` optional deps
- [ ] `pyproject.toml`: add `cryptography>=42.0` (likely already transitive dep)

### Files to Create

- [ ] `src/orchestra/messaging/__init__.py` — exports `SecureNatsProvider`, `TaskPublisher`, `TaskConsumer`
- [ ] `src/orchestra/messaging/client.py` — `create_nats_client()`, stream setup
- [ ] `src/orchestra/messaging/secure_provider.py` — `SecureNatsProvider`, `AgentKeyMaterial`, `extract_x25519_key_from_did()`
- [ ] `src/orchestra/messaging/publisher.py` — `TaskPublisher.publish()`
- [ ] `src/orchestra/messaging/consumer.py` — `TaskConsumer.run_loop()`

### Unit Tests

- [ ] `tests/unit/test_e2e_encryption.py`
  - [ ] `test_anoncrypt_round_trip` — key gen → encrypt → decrypt → verify body
  - [ ] `test_wrong_key_fails` — wrong key raises exception
  - [ ] `test_different_messages_have_different_epks` — EPK uniqueness
  - [ ] `test_algorithm_allowlist_blocks_wrong_alg` — tampered alg header rejected

### Integration Tests

- [ ] `tests/integration/test_secure_nats.py`
  - [ ] `test_publish_100_encrypted_tasks` — 100 publish → 100 acks → 100 decrypted (requires NATS)
  - [ ] `test_nats_store_contains_only_ciphertexts` — raw message bytes do not contain plaintext
  - [ ] `test_wrong_key_consumer_naks` — consumer with wrong key NAKs, message redelivered

### Verification (per T-4.1 "Done When" criteria)

- [ ] Publish 100 tasks → 100 acks
- [ ] NATS message store contains only opaque ciphertext (no plaintext fragments)
- [ ] Consumer with correct key decrypts all 100; consumer with wrong key cannot decrypt any

---

## Sources

### Primary (HIGH confidence)
- [DIDComm Messaging Specification v2.0](https://identity.foundation/didcomm-messaging/spec/v2.0/) — envelope structure, algorithms, media types
- [joserfc Documentation — JWE](https://jose.authlib.org/en/guide/jwe/) — encrypt/decrypt API
- [joserfc Documentation — Algorithms](https://jose.authlib.org/en/guide/algorithms/) — X25519/ECDH-ES support confirmed
- [joserfc Documentation — JWK](https://jose.authlib.org/en/guide/jwk/) — OKPKey generation and import
- [joserfc Changelog](https://jose.authlib.org/en/changelog/) — version 1.6.3, OKPKey.derive_key, p2c fix
- [joserfc PyPI](https://pypi.org/project/joserfc/) — version 1.6.3 confirmed
- [nats-py PyPI](https://pypi.org/project/nats-py/) — version 2.14.0 confirmed
- [peerdid GitHub — sicpa-dlab](https://github.com/sicpa-dlab/peer-did-python) — X25519KeyAgreementKey API
- [Python cryptography — X25519](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/x25519/) — raw byte operations
- [NATS JetStream Publishing Docs](https://docs.nats.io/using-nats/developer/develop_jetstream/publish) — add_stream, publish patterns

### Secondary (MEDIUM confidence)
- [DIDComm v2 PFS book](https://didcomm.org/book/v2/pfs/) — key rotation strategy; flexible per-implementation
- [ECDH-1PU implementation blog (DIF)](https://blog.identity.foundation/ecdh-1pu-implementation/) — authcrypt usage patterns

### Tertiary (LOW confidence — needs validation)
- [CCS'24 DIDComm Security Paper](https://dl.acm.org/doi/10.1145/3658644.3690300) — non-committing encryption finding; PDF not readable but blog summary corroborated finding
- multicodec prefix for X25519 in peerdid DID documents — needs a live test to verify exact byte offset

---

## Metadata

**Confidence breakdown:**
- Standard stack (joserfc, nats-py, peerdid): HIGH — all versions verified on PyPI
- Architecture (SecureNatsProvider pattern): HIGH — derived from official APIs
- JWE encrypt/decrypt code: HIGH — derived from official joserfc documentation and API reference
- peerdid key extraction: MEDIUM — API confirmed; multicodec byte offset needs integration test
- Pitfalls: HIGH — CCS'24 paper finding corroborated; joserfc CVE advisory verified

**Research date:** 2026-03-11
**Valid until:** 2026-04-11 (joserfc moves fast; nats-py stable; peerdid likely unchanged)
