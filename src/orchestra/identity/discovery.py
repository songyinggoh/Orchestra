"""Registry for discovering agents via signed AgentCards."""

from __future__ import annotations
import structlog
from typing import Any
from joserfc.jwk import OKPKey
from orchestra.core.errors import InvalidSignatureError
from orchestra.identity.agent_identity import AgentCard

logger = structlog.get_logger(__name__)

class SignedDiscoveryProvider:
    """Registry that only accepts agent cards with valid cryptographic signatures.
    Rejects unsigned or tampered cards to prevent gossip poisoning."""

    def __init__(self, max_cards_per_did: int = 2) -> None:
        self._cards: dict[str, list[AgentCard]] = {}  # did -> [current, previous]
        self._max_cards_per_did = max_cards_per_did

    def register(self, card: AgentCard, verification_key: OKPKey | None = None) -> bool:
        """Verify signature, then register. Returns False if signature invalid.
        
        Args:
            card: The AgentCard to register.
            verification_key: Optional pre-resolved public key. If None, it will be resolved from the DID.
        """
        if not card.signature:
            logger.warning("discovery_registration_failed_no_signature", did=card.did)
            return False

        # 1. Resolve key if not provided
        if verification_key is None:
            verification_key = self._resolve_key_from_did(card.did)
        
        # 2. Verify JWS signature
        if not card.verify_jws(verification_key):
            logger.error("discovery_registration_failed_invalid_signature", did=card.did)
            return False

        # 3. Check expires_at
        if card.is_expired:
            logger.warning("discovery_registration_failed_expired", did=card.did)
            return False

        # 4. Check version and store
        existing = self._cards.get(card.did, [])
        if existing:
            # Must be newer than current highest version
            current_best = max(existing, key=lambda x: x.version)
            if card.version < current_best.version:
                logger.warning("discovery_registration_ignored_stale_version", 
                               did=card.did, current=current_best.version, new=card.version)
                return False
            
            # If same version, just update (e.g. metadata change but version not bumped)
            if card.version == current_best.version:
                 existing.remove(current_best)

        # 5. Add to store and enforce capacity
        existing.append(card)
        existing.sort(key=lambda x: x.version, reverse=True)
        self._cards[card.did] = existing[:self._max_cards_per_did]
        
        logger.info("discovery_registration_success", did=card.did, version=card.version)
        return True

    def _resolve_key_from_did(self, did: str) -> OKPKey:
        """Simple resolver for did:peer:2 (public key is inline) and others."""
        import base64
        from orchestra.messaging.peer_did import resolve_peer_did
        
        def base64url_encode(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")
        
        if did.startswith("did:peer:2"):
            doc = resolve_peer_did(did)
            # Find an Ed25519 verification method
            vm = next((m for m in doc.get("verificationMethod", []) 
                      if m.get("type") == "Ed25519VerificationKey2020"), None)
            
            if not vm:
                raise ValueError(f"No Ed25519 verification method found in {did}")
            
            import base58
            # Strip 'z' multibase prefix
            pub_bytes = base58.b58decode(vm["publicKeyMultibase"][1:])
            
            return OKPKey.import_key({
                "kty": "OKP", 
                "crv": "Ed25519",
                "x": base64url_encode(pub_bytes)
            })
            
        raise NotImplementedError(f"Automated resolution for {did} not yet fully implemented in discovery.py")

    def lookup(self, did: str) -> AgentCard | None:
        """Get the current (highest version) card for a DID."""
        cards = self._cards.get(did)
        return cards[0] if cards else None

    def lookup_by_type(self, agent_type: str) -> list[AgentCard]:
        """Find all agents of a given type."""
        results = []
        for cards in self._cards.values():
            best = cards[0]
            if best.agent_type == agent_type:
                results.append(best)
        return results

    def revoke(self, did: str) -> None:
        """Remove all cards for a DID."""
        if did in self._cards:
            del self._cards[did]

    @property
    def registered_count(self) -> int:
        return len(self._cards)
