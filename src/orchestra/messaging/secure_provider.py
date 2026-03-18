"""DIDComm v2 E2EE wrapper for NATS JetStream.

Implements anoncrypt mode: ECDH-ES+A256KW key agreement with A256GCM content
encryption over X25519 keys embedded in did:peer:2 DID documents.

Every agent session generates a fresh X25519 keypair. Keys never leave the
process — the public key is embedded in the DID document, the private key
lives in memory only.

Key rotation
~~~~~~~~~~~~
Session keys are rotated automatically after ``key_rotation_interval`` seconds
(default: 3600 s).  On each ``encrypt_for()`` call the provider checks whether
the current key has exceeded its lifetime; if so a new X25519 keypair and a new
did:peer:2 DID are generated in-place, and the old key material is discarded.

A ``kid`` field (e.g. ``"key-1715000000"``) derived from the key's creation
timestamp is added to every JWE protected header so recipients can identify
which key version was used for audit purposes.  Decryption is unaffected —
the recipient's private key is selected by the JWE standard EPK mechanism, not
by ``kid``.
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

# Base JWE protected header — kid is added per-call to reflect key version.
# Algorithm allowlisted at decrypt time via JWERegistry — do not change
# without updating _ALLOWED_ALGORITHMS below.
_BASE_PROTECTED_HEADER: dict[str, str] = {
    "alg": "ECDH-ES+A256KW",
    "enc": "A256GCM",
    "typ": "application/didcomm-encrypted+json",
}
_ALLOWED_ALGORITHMS = ["ECDH-ES+A256KW", "A256GCM"]

# Back-compat alias — external code that imported _PROTECTED_HEADER directly
# still works; it just won't have the kid field (acceptable for old callers).
_PROTECTED_HEADER = _BASE_PROTECTED_HEADER


@dataclass
class AgentKeyMaterial:
    """Holds an agent's session X25519 keypair and associated DID."""

    did: str
    kid: str
    keypair: OKPKey
    created_at: float = field(default_factory=time.time)  # wall-clock creation time
    version: int = 1                                       # incremented on each rotation
    rotated_at: float | None = None                        # wall-clock time of last rotation
    _public_jwk: dict = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self._public_jwk = self.keypair.as_dict(private=False)

    @property
    def public_jwk(self) -> dict:
        return self._public_jwk

    def needs_rotation(self, max_age_seconds: float) -> bool:
        """Return True when the key has exceeded *max_age_seconds* since creation.

        Uses ``time.time()`` (wall clock) rather than a monotonic timer so
        that callers can reason about calendar-time lifetimes.

        Args:
            max_age_seconds: Maximum allowed age in seconds.  Pass 0 or a
                negative value to always return False (rotation disabled).
        """
        if max_age_seconds <= 0:
            return False
        return (time.time() - self.created_at) > max_age_seconds


class SecureNatsProvider:
    """DIDComm v2 E2EE layer for NATS task messages.

    Usage::

        provider = SecureNatsProvider.create(nats_url="nats://localhost:4222")
        token = provider.encrypt_for({"task_id": "t1"}, recipient_did=bob_did)
        plaintext = provider.decrypt(token)   # {"id": "...", "body": {"task_id": "t1"}}

    The JWE compact token (opaque string) is what gets stored in NATS — never
    the plaintext. Decryption requires the matching private key.

    Key rotation
    ~~~~~~~~~~~~
    Pass ``key_rotation_interval`` (seconds) to control how long a session key
    lives before it is replaced.  The default is 3600 s (1 hour).  Set to 0 to
    disable rotation entirely (useful in tests that need a stable DID).
    """

    def __init__(
        self,
        own_keys: AgentKeyMaterial,
        *,
        key_rotation_interval: int = 3600,
        _nats_url: str = "nats://localhost:4222",
    ) -> None:
        self._own_keys = own_keys
        self._key_rotation_interval = key_rotation_interval
        self._nats_url = _nats_url
        # Monotonic timestamp for elapsed-time comparison (rotation trigger).
        self._key_created_at: float = time.monotonic()
        # Wall-clock timestamp used as a stable, human-readable key-version label
        # in the JWE kid field.  time.time() advances continuously even within the
        # same monotonic second, ensuring kid uniqueness across rapid rotations.
        self._key_wall_time: float = time.time()
        # LRU-style cache of resolved recipient DIDs: did -> (kid, OKPKey)
        self._recipient_cache: dict[str, tuple[str, OKPKey]] = {}
        # Key history: archived (superseded) AgentKeyMaterial instances kept so
        # that out-of-order or delayed messages can still be decrypted.
        # The list is ordered oldest → newest; the active key is in _own_keys.
        self._key_history: list[AgentKeyMaterial] = []

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        *,
        nats_url: str = "nats://localhost:4222",
        key_rotation_interval: int = 3600,
    ) -> SecureNatsProvider:
        """Create a provider with a fresh session X25519 keypair.

        Generates a new did:peer:2 DID encoding the public key. Keys are
        ephemeral — a new set is created each time this is called.

        Args:
            nats_url: NATS server URL embedded in the DID service endpoint.
            key_rotation_interval: Seconds between automatic key rotations.
                Pass 0 to disable rotation (e.g. in stable-DID test scenarios).
        """
        try:
            import base58  # noqa: F401 — needed by create_peer_did_numalgo_2
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
            from joserfc.jwk import OKPKey
            from orchestra.messaging.peer_did import create_peer_did_numalgo_2
        except ImportError as exc:
            raise ImportError(
                "messaging dependencies missing. "
                "Install with: pip install orchestra-agents[messaging]"
            ) from exc

        own_keys = cls._generate_key_material(
            nats_url=nats_url,
            X25519PrivateKey=X25519PrivateKey,
            Ed25519PrivateKey=Ed25519PrivateKey,
            OKPKey=OKPKey,
            create_peer_did_numalgo_2=create_peer_did_numalgo_2,
        )
        log.info("agent_did_created", did=own_keys.did[:48] + "…")
        return cls(
            own_keys,
            key_rotation_interval=key_rotation_interval,
            _nats_url=nats_url,
        )

    @staticmethod
    def _generate_key_material(
        *,
        nats_url: str,
        X25519PrivateKey,
        Ed25519PrivateKey,
        OKPKey,
        create_peer_did_numalgo_2,
    ) -> AgentKeyMaterial:
        """Generate a fresh X25519 keypair and a matching did:peer:2 DID.

        Extracted as a static helper so that both ``create()`` and
        ``_rotate_keys_if_needed()`` share the same key-generation logic
        without duplication.
        """
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
            encryption_keys=[x_pub_raw],
            signing_keys=[ed_pub_raw],
            service={"type": "DIDCommMessaging", "serviceEndpoint": nats_url},
        )
        kid = f"{did}#key-1"
        return AgentKeyMaterial(did=did, kid=kid, keypair=keypair)

    # ------------------------------------------------------------------
    # Encryption / decryption
    # ------------------------------------------------------------------

    def encrypt_for(self, body: dict, recipient_did: str) -> str:
        """Encrypt a task body dict for a recipient DID.

        Returns a JWE compact serialisation token — an opaque string safe to
        publish to NATS. The NATS store will only ever hold this ciphertext.

        Key rotation is checked on every call.  If the current session key has
        exceeded ``key_rotation_interval`` seconds, new key material is generated
        transparently before encrypting.
        """
        try:
            from joserfc import jwe
        except ImportError as exc:
            raise ImportError("joserfc is required. pip install joserfc>=1.6") from exc

        self._rotate_keys_if_needed()

        jwm = {
            "id": str(uuid.uuid4()),
            "type": "https://orchestra.ai/protocols/task/1.0/request",
            "created_time": int(time.time()),
            "body": body,
        }
        # Build a per-call header that includes the sender's key version as kid.
        # Recipients use the EPK embedded by joserfc for key agreement — kid is
        # purely informational (audit trail, key-version correlation).
        # _key_wall_time (time.time()) is used here rather than the monotonic
        # _key_created_at so that the kid value is a readable Unix timestamp and
        # is guaranteed to differ between rotations even within the same second.
        header = {
            **_BASE_PROTECTED_HEADER,
            "kid": f"key-{int(self._key_wall_time)}",
        }
        _, recipient_key = self._resolve_recipient(recipient_did)
        token: str = jwe.encrypt_compact(
            header,
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

    @property
    def key_version(self) -> str:
        """Opaque string identifying the current key version.

        Format: ``"key-<unix-wall-epoch-of-creation>"``.  Changes on every
        rotation.  Exposed for testing and audit logging.
        """
        return f"key-{int(self._key_wall_time)}"

    @property
    def key_version_number(self) -> int:
        """Integer version counter for the current key (starts at 1, increments on rotation)."""
        return self._own_keys.version

    def needs_rotation(self, max_age_seconds: float) -> bool:
        """Return True when the current session key has exceeded *max_age_seconds*.

        Delegates to :meth:`AgentKeyMaterial.needs_rotation` on the active key
        material so that callers do not need to reach into ``_own_keys`` directly.

        Args:
            max_age_seconds: Key lifetime threshold in seconds.  Pass 0 or a
                negative value to always return False (rotation disabled).
        """
        return self._own_keys.needs_rotation(max_age_seconds)

    def rotate_keys(self) -> None:
        """Unconditionally rotate session key material.

        Generates a new X25519 keypair and a new did:peer:2 DID, increments the
        version counter, records ``rotated_at`` on the new key material, and
        archives the old key in ``_key_history`` so that messages encrypted
        before the rotation boundary can still be decrypted.

        This is the *explicit* rotation API.  Automatic interval-based rotation
        continues to fire via :meth:`_rotate_keys_if_needed` on every
        :meth:`encrypt_for` call.
        """
        try:
            import base58  # noqa: F401 — needed by create_peer_did_numalgo_2
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
            from joserfc.jwk import OKPKey
            from orchestra.messaging.peer_did import create_peer_did_numalgo_2
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "messaging dependencies missing. "
                "Install with: pip install orchestra-agents[messaging]"
            ) from exc

        old_keys = self._own_keys
        new_keys = self._generate_key_material(
            nats_url=self._nats_url,
            X25519PrivateKey=X25519PrivateKey,
            Ed25519PrivateKey=Ed25519PrivateKey,
            OKPKey=OKPKey,
            create_peer_did_numalgo_2=create_peer_did_numalgo_2,
        )
        # Increment version and stamp rotation time
        new_keys.version = old_keys.version + 1
        new_keys.rotated_at = time.time()

        # Archive old key material before replacing it
        self._key_history.append(old_keys)

        self._own_keys = new_keys
        self._key_created_at = time.monotonic()
        self._key_wall_time = time.time()
        self._recipient_cache.clear()
        log.info(
            "session_key_rotated_explicit",
            old_did=old_keys.did[:48] + "…",
            new_did=new_keys.did[:48] + "…",
            version=new_keys.version,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _rotate_keys_if_needed(self) -> None:
        """Rotate session key material if the rotation interval has elapsed.

        When rotation fires:
        1. A fresh X25519 keypair and did:peer:2 DID are generated.
        2. ``self._own_keys`` is replaced atomically.
        3. ``self._key_created_at`` is reset to ``time.monotonic()``.
        4. The recipient DID cache is cleared (senders who cached our old DID
           will need to re-resolve; this is handled by normal DID resolution).

        If ``key_rotation_interval`` is 0, rotation is disabled.
        """
        if self._key_rotation_interval <= 0:
            return
        elapsed = time.monotonic() - self._key_created_at
        if elapsed < self._key_rotation_interval:
            return

        try:
            import base58  # noqa: F401 — required by create_peer_did_numalgo_2
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
            from joserfc.jwk import OKPKey
            from orchestra.messaging.peer_did import create_peer_did_numalgo_2
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "messaging dependencies missing. "
                "Install with: pip install orchestra-agents[messaging]"
            ) from exc

        old_keys = self._own_keys
        new_keys = self._generate_key_material(
            nats_url=self._nats_url,
            X25519PrivateKey=X25519PrivateKey,
            Ed25519PrivateKey=Ed25519PrivateKey,
            OKPKey=OKPKey,
            create_peer_did_numalgo_2=create_peer_did_numalgo_2,
        )
        # Carry forward version counter and stamp rotation time.
        new_keys.version = old_keys.version + 1
        new_keys.rotated_at = time.time()

        # Archive old key material so that in-flight messages encrypted with
        # the previous key can still be decrypted.
        self._key_history.append(old_keys)

        self._own_keys = new_keys
        self._key_created_at = time.monotonic()
        self._key_wall_time = time.time()
        # Flush recipient cache — it holds resolved public keys for *outbound*
        # recipients and is not keyed on our own DID, so clearing is optional;
        # we do it anyway to stay consistent.
        self._recipient_cache.clear()
        log.info(
            "session_key_rotated",
            old_did=old_keys.did[:48] + "…",
            new_did=new_keys.did[:48] + "…",
            version=new_keys.version,
        )

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
        from orchestra.messaging.peer_did import resolve_peer_did
    except ImportError as exc:
        raise ImportError(
            "base58 and joserfc are required. pip install base58>=2.1 joserfc>=1.6"
        ) from exc

    doc_json = resolve_peer_did(did)

    for vm in doc_json.get("verificationMethod", []):
        if vm.get("type") == "X25519KeyAgreementKey2020":
            kid: str = vm["id"]
            multibase: str = vm.get("publicKeyMultibase", "")
            if not multibase.startswith("z"):
                raise ValueError(
                    f"Expected base58btc (z-prefix) publicKeyMultibase in DID {did!r}"
                )
            raw = base58.b58decode(multibase[1:])
            # resolve_peer_did already stripped multicodec prefix for multibase
            x_b64 = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
            key: OKPKey = OKPKey.import_key({"kty": "OKP", "crv": "X25519", "x": x_b64})
            return kid, key

    raise ValueError(f"No X25519KeyAgreementKey2020 found in DID document for {did!r}")
