"""DIDComm v2 E2EE wrapper for NATS JetStream.

Implements anoncrypt mode: ECDH-ES+A256KW key agreement with A256GCM content
encryption over X25519 keys embedded in did:peer:2 DID documents.

Every agent session generates a fresh X25519 keypair. Keys never leave the
process — the public key is embedded in the DID document, the private key
lives in memory only.
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from joserfc.jwk import OKPKey

log = structlog.get_logger(__name__)

# JWE protected header used for every encrypted message.
# Algorithm allowlisted at decrypt time via JWERegistry — do not change
# without updating _ALLOWED_ALGORITHMS below.
_PROTECTED_HEADER: dict[str, str] = {
    "alg": "ECDH-ES+A256KW",
    "enc": "A256GCM",
    "typ": "application/didcomm-encrypted+json",
}
_ALLOWED_ALGORITHMS = ["ECDH-ES+A256KW", "A256GCM"]


@dataclass
class AgentKeyMaterial:
    """Holds an agent's session X25519 keypair and associated DID."""

    did: str
    kid: str
    keypair: OKPKey
    _public_jwk: dict = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self._public_jwk = self.keypair.as_dict(private=False)

    @property
    def public_jwk(self) -> dict:
        return self._public_jwk


class SecureNatsProvider:
    """DIDComm v2 E2EE layer for NATS task messages.

    Usage::

        provider = SecureNatsProvider.create(nats_url="nats://localhost:4222")
        token = provider.encrypt_for({"task_id": "t1"}, recipient_did=bob_did)
        plaintext = provider.decrypt(token)   # {"id": "...", "body": {"task_id": "t1"}}

    The JWE compact token (opaque string) is what gets stored in NATS — never
    the plaintext. Decryption requires the matching private key.
    """

    def __init__(self, own_keys: AgentKeyMaterial) -> None:
        self._own_keys = own_keys
        # LRU-style cache of resolved recipient DIDs: did -> (kid, OKPKey)
        self._recipient_cache: dict[str, tuple[str, OKPKey]] = {}

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def create(cls, *, nats_url: str = "nats://localhost:4222") -> SecureNatsProvider:
        """Create a provider with a fresh session X25519 keypair.

        Generates a new did:peer:2 DID encoding the public key. Keys are
        ephemeral — a new set is created each time this is called.
        """
        try:
            import base58
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
            from joserfc.jwk import OKPKey
            from peerdid.dids import create_peer_did_numalgo_2
            from peerdid.keys import Ed25519VerificationKey, X25519KeyAgreementKey
        except ImportError as exc:
            raise ImportError(
                "messaging dependencies missing. "
                "Install with: pip install orchestra-agents[messaging]"
            ) from exc

        # X25519 keypair for JWE key agreement
        x_priv = X25519PrivateKey.generate()
        x_pub_raw = x_priv.public_key().public_bytes_raw()
        x_priv_raw = x_priv.private_bytes_raw()

        # Build joserfc OKPKey from raw bytes
        x_b64 = base64.urlsafe_b64encode(x_pub_raw).rstrip(b"=").decode()
        d_b64 = base64.urlsafe_b64encode(x_priv_raw).rstrip(b"=").decode()
        keypair: OKPKey = OKPKey.import_key(
            {"kty": "OKP", "crv": "X25519", "x": x_b64, "d": d_b64}
        )

        # Ed25519 keypair for signing (required by did:peer:2 spec)
        ed_priv = Ed25519PrivateKey.generate()
        ed_pub_raw = ed_priv.public_key().public_bytes_raw()

        # Create did:peer:2 (numalgo 2 — entire key material encoded in the DID string,
        # so resolution is local and requires no network call)
        did = create_peer_did_numalgo_2(
            encryption_keys=[X25519KeyAgreementKey.from_base58(base58.b58encode(x_pub_raw).decode())],
            signing_keys=[Ed25519VerificationKey.from_base58(base58.b58encode(ed_pub_raw).decode())],
            service={"type": "DIDCommMessaging", "serviceEndpoint": nats_url},
        )
        kid = f"{did}#key-1"
        log.info("agent_did_created", did=did[:48] + "…")
        return cls(AgentKeyMaterial(did=did, kid=kid, keypair=keypair))

    # ------------------------------------------------------------------
    # Encryption / decryption
    # ------------------------------------------------------------------

    def encrypt_for(self, body: dict, recipient_did: str) -> str:
        """Encrypt a task body dict for a recipient DID.

        Returns a JWE compact serialisation token — an opaque string safe to
        publish to NATS. The NATS store will only ever hold this ciphertext.
        """
        try:
            from joserfc import jwe
        except ImportError as exc:
            raise ImportError("joserfc is required. pip install joserfc>=1.6") from exc

        jwm = {
            "id": str(uuid.uuid4()),
            "type": "https://orchestra.ai/protocols/task/1.0/request",
            "created_time": int(time.time()),
            "body": body,
        }
        _, recipient_key = self._resolve_recipient(recipient_did)
        token: str = jwe.encrypt_compact(
            dict(_PROTECTED_HEADER),  # copy — joserfc may mutate
            json.dumps(jwm).encode("utf-8"),
            recipient_key,
        )
        return token

    def decrypt(self, jwe_token: str) -> dict:
        """Decrypt a JWE compact token fetched from NATS.

        Returns the full DIDComm JWM dict; the task payload is in ['body'].
        Raises on wrong key, tampered ciphertext, or disallowed algorithm.
        """
        try:
            from joserfc import jwe as jwe_mod
            from joserfc.jwe import JWERegistry
        except ImportError as exc:
            raise ImportError("joserfc is required. pip install joserfc>=1.6") from exc

        registry = JWERegistry(algorithms=_ALLOWED_ALGORITHMS)
        result = jwe_mod.decrypt_compact(jwe_token, self._own_keys.keypair, registry=registry)
        return json.loads(result.plaintext)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def own_did(self) -> str:
        return self._own_keys.did

    @property
    def own_public_jwk(self) -> dict:
        return self._own_keys.public_jwk

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve_recipient(self, did: str) -> tuple[str, OKPKey]:
        if did not in self._recipient_cache:
            self._recipient_cache[did] = extract_x25519_key_from_did(did)
        return self._recipient_cache[did]


def extract_x25519_key_from_did(did: str) -> tuple[str, OKPKey]:
    """Resolve a did:peer DID and return (kid, X25519 public OKPKey).

    Strips the 2-byte multicodec prefix (0xec 0x01) from the base58btc-encoded
    public key in the DID document's X25519KeyAgreementKey2020 verification
    method.
    """
    try:
        import base58
        from joserfc.jwk import OKPKey
        from peerdid.dids import resolve_peer_did
    except ImportError as exc:
        raise ImportError(
            "peerdid and base58 are required. pip install peerdid>=0.5.2 base58>=2.1"
        ) from exc

    did_doc = resolve_peer_did(did)
    doc_json: dict = did_doc.to_dict()

    for vm in doc_json.get("verificationMethod", []):
        if vm.get("type") == "X25519KeyAgreementKey2020":
            kid: str = vm["id"]
            multibase: str = vm.get("publicKeyMultibase", "")
            if not multibase.startswith("z"):
                raise ValueError(
                    f"Expected base58btc (z-prefix) publicKeyMultibase in DID {did!r}"
                )
            raw = base58.b58decode(multibase[1:])
            # Strip 2-byte multicodec prefix if present (total length > 32 bytes)
            if len(raw) > 32:
                raw = raw[2:]
            x_b64 = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
            key: OKPKey = OKPKey.import_key({"kty": "OKP", "crv": "X25519", "x": x_b64})
            return kid, key

    raise ValueError(f"No X25519KeyAgreementKey2020 found in DID document for {did!r}")
