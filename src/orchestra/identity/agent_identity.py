"""Agent Identity and cryptographic signatures.

Provides mechanisms for agents to prove their identity via DIDs and sign
messages or capability delegations (UCANs).
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import structlog
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from orchestra.core.errors import AgentRevokedException
from orchestra.identity.types import DelegationContext
from orchestra.messaging.peer_did import create_peer_did_numalgo_2

logger = structlog.get_logger(__name__)


class RevocationList:
    """In-memory revocation list for agent DIDs.

    Maintains a set of revoked DIDs and exposes a simple check/revoke API.
    Persistence (file, Redis, HSM) is deferred to Wave 4.

    Thread-safety note: This implementation is not thread-safe.  For
    concurrent workloads wrap instances with an external lock or use the
    RevocationList inside a single-threaded event loop.

    Usage::

        rl = RevocationList()
        rl.revoke("did:peer:2:...")
        rl.is_revoked("did:peer:2:...")  # True
        rl.unrevoke("did:peer:2:...")    # restore (e.g. after re-provisioning)
    """

    def __init__(self) -> None:
        self._revoked: set[str] = set()

    def revoke(self, did: str) -> None:
        """Add *did* to the revocation set."""
        self._revoked.add(did)
        logger.info("agent_revoked", did=did)

    def unrevoke(self, did: str) -> None:
        """Remove *did* from the revocation set (e.g. after re-provisioning)."""
        self._revoked.discard(did)
        logger.info("agent_unrevoked", did=did)

    def is_revoked(self, did: str) -> bool:
        """Return True if *did* is in the revocation set."""
        return did in self._revoked

    def __len__(self) -> int:
        return len(self._revoked)

    def __contains__(self, did: object) -> bool:
        return did in self._revoked


@runtime_checkable
class Signer(Protocol):
    """Protocol for cryptographic signing."""

    @property
    def own_did(self) -> str:
        """The DID associated with this signer."""
        ...

    def sign(self, data: bytes) -> bytes:
        """Sign raw bytes and return the signature."""
        ...

    def verify(self, data: bytes, signature: bytes, public_key_bytes: bytes) -> bool:
        """Verify a signature against raw bytes and a public key."""
        ...


class Ed25519Signer:
    """Signer implementation using Ed25519."""

    def __init__(self, private_key: Ed25519PrivateKey, did: str) -> None:
        self._private_key = private_key
        self._did = did
        self._public_key = private_key.public_key()

    @property
    def own_did(self) -> str:
        return self._did

    @property
    def public_key_bytes(self) -> bytes:
        return self._public_key.public_bytes_raw()

    def sign(self, data: bytes) -> bytes:
        return self._private_key.sign(data)

    def verify(self, data: bytes, signature: bytes, public_key_bytes: bytes) -> bool:
        try:
            pub = Ed25519PublicKey.from_public_bytes(public_key_bytes)
            pub.verify(signature, data)
            return True
        except Exception:
            return False


@dataclass
class AgentCard:
    """Publicly sharable metadata about an agent, signed by the agent's DID.

    A2A / Google ADK compatible structure for discovery and capability verification.
    """

    did: str
    name: str
    agent_type: str
    capabilities: list[str] = field(default_factory=list)
    version: int = 1  # NEW: incremented on rotation
    expires_at: float | None = None  # NEW: Unix timestamp (DD-3: 1h overlap)
    nats_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    signature: str | None = None  # JWS Compact Serialization

    def to_json(self) -> str:
        # Note: excludes signature from the canonical JSON representation for signing
        return json.dumps(
            {
                "did": self.did,
                "name": self.name,
                "agent_type": self.agent_type,
                "capabilities": self.capabilities,
                "version": self.version,
                "expires_at": self.expires_at,
                "nats_url": self.nats_url,
                "metadata": self.metadata,
            },
            sort_keys=True,
        )

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    def sign_jws(self, signing_key: Any) -> None:
        """Sign card using JWS Compact Serialization with EdDSA (DD-3).

        Args:
            signing_key: joserfc OKPKey instance.
        """
        from joserfc import jws

        payload = self.to_json().encode("utf-8")
        header = {"alg": "EdDSA"}
        # RFC 9864: algorithms=['EdDSA'] is mandatory for EdDSA in joserfc 1.6+
        self.signature = jws.serialize_compact(header, payload, signing_key, algorithms=["EdDSA"])

    def verify_jws(
        self,
        verification_key: Any,
        *,
        revocation_list: RevocationList | None = None,
    ) -> bool:
        """Verify JWS Compact signature (DD-3).

        Revocation is checked BEFORE the cryptographic verification so that
        a compromised agent is rejected as early as possible.

        Args:
            verification_key: joserfc OKPKey instance.
            revocation_list: Optional RevocationList.  When provided and the
                card's DID appears in the list, raises AgentRevokedException.
                When None (default), revocation is not checked — existing
                callers are unaffected.

        Raises:
            AgentRevokedException: If revocation_list is provided and the
                card's DID is revoked.
        """
        # Revocation gate — checked before any crypto work.
        if revocation_list is not None and revocation_list.is_revoked(self.did):
            raise AgentRevokedException(self.did)

        if not self.signature:
            return False
        from joserfc import jws

        try:
            result = jws.deserialize_compact(self.signature, verification_key, algorithms=["EdDSA"])
            return result.payload == self.to_json().encode("utf-8")
        except Exception:
            return False

    def sign_raw(self, signer: Signer) -> None:
        """Backward compatible raw signing."""
        payload = self.to_json().encode("utf-8")
        sig_bytes = signer.sign(payload)
        self.signature = base64.urlsafe_b64encode(sig_bytes).rstrip(b"=").decode()

    def verify_raw(
        self,
        public_key_bytes: bytes,
        *,
        revocation_list: RevocationList | None = None,
    ) -> bool:
        """Backward compatible raw verification.

        Args:
            public_key_bytes: Raw Ed25519 public key bytes (32 bytes).
            revocation_list: Optional RevocationList.  When provided and the
                card's DID appears in the list, raises AgentRevokedException.
                When None (default), revocation is not checked — existing
                callers are unaffected.

        Raises:
            AgentRevokedException: If revocation_list is provided and the
                card's DID is revoked.
        """
        # Revocation gate — checked before any crypto work.
        if revocation_list is not None and revocation_list.is_revoked(self.did):
            raise AgentRevokedException(self.did)

        if not self.signature:
            return False

        payload = self.to_json().encode("utf-8")
        try:
            sig_bytes = base64.urlsafe_b64decode(self.signature + "==")
            pub = Ed25519PublicKey.from_public_bytes(public_key_bytes)
            pub.verify(sig_bytes, payload)
            return True
        except Exception:
            return False


class AgentIdentityValidator:
    """Validates AgentCards against revocation lists and cryptographic signatures.

    Centralises the two-step validation pattern (revocation check → signature
    verification) so that callers do not need to call ``verify_jws`` /
    ``verify_raw`` directly when a revocation list is in scope.

    The revocation check is intentionally performed **before** the (more
    expensive) cryptographic verification so that a compromised agent is
    rejected as quickly as possible without wasting CPU cycles on crypto.

    Usage::

        validator = AgentIdentityValidator(revocation_list=rl)

        # JWS (joserfc OKPKey) path:
        ok = validator.validate_with_revocation(card, verification_key=okp_key)

        # Raw Ed25519 bytes path:
        ok = validator.validate_with_revocation(card, public_key_bytes=pub_bytes)
    """

    def __init__(self, revocation_list: RevocationList | None = None) -> None:
        self._revocation_list = revocation_list

    @property
    def revocation_list(self) -> RevocationList | None:
        return self._revocation_list

    @revocation_list.setter
    def revocation_list(self, value: RevocationList | None) -> None:
        self._revocation_list = value

    def validate_with_revocation(
        self,
        agent_card: AgentCard,
        *,
        verification_key: Any | None = None,
        public_key_bytes: bytes | None = None,
    ) -> bool:
        """Validate *agent_card*, checking revocation before cryptographic verification.

        Exactly one of *verification_key* (joserfc OKPKey for JWS) or
        *public_key_bytes* (raw Ed25519 bytes for the legacy ``verify_raw``
        path) must be provided.

        Revocation is checked first.  If the card's DID appears in
        ``self.revocation_list`` an :class:`~orchestra.core.errors.AgentRevokedException`
        is raised immediately, before any crypto work.

        Args:
            agent_card: The :class:`AgentCard` to validate.
            verification_key: A joserfc ``OKPKey`` (Ed25519 public key) for
                JWS signature verification.  Mutually exclusive with
                *public_key_bytes*.
            public_key_bytes: Raw 32-byte Ed25519 public key for the
                backward-compatible ``verify_raw`` path.  Mutually exclusive
                with *verification_key*.

        Returns:
            ``True`` if the DID is not revoked and the signature is valid;
            ``False`` if the signature is invalid (but the DID is not revoked).

        Raises:
            AgentRevokedException: If the card's DID is in the revocation list.
            ValueError: If neither or both of *verification_key* and
                *public_key_bytes* are provided.
        """
        if verification_key is None and public_key_bytes is None:
            raise ValueError("Provide exactly one of 'verification_key' or 'public_key_bytes'.")
        if verification_key is not None and public_key_bytes is not None:
            raise ValueError(
                "Provide exactly one of 'verification_key' or 'public_key_bytes', not both."
            )

        # Revocation gate — must fire before any crypto work.
        if self._revocation_list is not None and self._revocation_list.is_revoked(agent_card.did):
            raise AgentRevokedException(agent_card.did)

        if verification_key is not None:
            return agent_card.verify_jws(verification_key)
        # public_key_bytes path
        return agent_card.verify_raw(public_key_bytes)  # type: ignore[arg-type]


class AgentIdentity:
    """Full cryptographic identity for an Orchestra agent.

    Combines X25519 (for E2EE messaging) and Ed25519 (for signing and DIDs).
    """

    def __init__(
        self,
        signing_key: Ed25519PrivateKey,
        encryption_key_raw: bytes,  # Raw X25519 private key bytes
        nats_url: str = "nats://localhost:4222",
        max_delegation_depth: int = 3,
    ) -> None:
        self._signing_key = signing_key
        self._encryption_key_raw = encryption_key_raw
        self._max_delegation_depth = max_delegation_depth

        # Generate DID:peer:2
        ed_pub = signing_key.public_key().public_bytes_raw()
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

        x_priv = X25519PrivateKey.from_private_bytes(encryption_key_raw)
        x_pub = x_priv.public_key().public_bytes_raw()

        self._did = create_peer_did_numalgo_2(
            encryption_keys=[x_pub],
            signing_keys=[ed_pub],
            service={"type": "DIDCommMessaging", "serviceEndpoint": nats_url},
        )
        self._signer = Ed25519Signer(self._signing_key, self._did)

    @classmethod
    def create(cls, nats_url: str = "nats://localhost:4222") -> AgentIdentity:
        """Generate a fresh ephemeral identity."""
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

        ed_priv = Ed25519PrivateKey.generate()
        x_priv = X25519PrivateKey.generate()
        return cls(ed_priv, x_priv.private_bytes_raw(), nats_url)

    @property
    def did(self) -> str:
        return self._did

    @property
    def signer(self) -> Signer:
        return self._signer

    @property
    def delegation_context(self) -> DelegationContext:
        return DelegationContext.root(self._did, self._max_delegation_depth)

    def create_card(
        self, name: str, agent_type: str, capabilities: list[str], ttl: int = 3600
    ) -> AgentCard:
        """Create and sign an AgentCard for this identity using JWS (DD-3)."""
        card = AgentCard(
            did=self._did,
            name=name,
            agent_type=agent_type,
            capabilities=capabilities,
            expires_at=time.time() + ttl,
        )
        card.sign_jws(self._make_okp_key())
        return card

    def _make_okp_key(self) -> Any:
        """Convert cryptography Ed25519 key to joserfc OKPKey for JWS signing."""
        from joserfc.jwk import OKPKey

        def base64url_encode(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")

        d_bytes = self._signing_key.private_bytes_raw()
        x_bytes = self._signing_key.public_key().public_bytes_raw()
        return OKPKey.import_key(
            {
                "kty": "OKP",
                "crv": "Ed25519",
                "d": base64url_encode(d_bytes),
                "x": base64url_encode(x_bytes),
            }
        )
