"""A2A (Agent-to-Agent) Protocol and Discovery (T-4.11).

Provides secure envelopes for cross-organizational state transfer
and discovery mechanisms for agent capabilities.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import structlog
from joserfc.jwk import OKPKey
from joserfc.jws import sign_compact, verify_compact

from orchestra.identity.agent_identity import AgentIdentity
from orchestra.identity.did import DIDManager
from orchestra.interop.zkp import StateCommitment

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class A2AStateTransfer:
    """Secure envelope for transferring agent state between organizations."""

    state: dict[str, Any]
    commitment: bytes
    nonce: bytes
    chain_root: bytes
    sender_did: str
    signature: str  # JWS compact serialization

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "commitment": base64.b64encode(self.commitment).decode(),
            "nonce": base64.b64encode(self.nonce).decode(),
            "chain_root": base64.b64encode(self.chain_root).decode(),
            "sender_did": self.sender_did,
            "signature": self.signature,
        }

    @classmethod
    def create(
        cls, state: dict[str, Any], chain_root: bytes, identity: AgentIdentity
    ) -> A2AStateTransfer:
        """Create a signed A2A state transfer envelope."""
        # 1. Create Tier 1 commitment
        res = StateCommitment.commit(state)

        # 2. Prepare payload for signing: (commitment || chain_root)
        payload = {
            "cmt": base64.b64encode(res.commitment).decode(),
            "root": base64.b64encode(chain_root).decode(),
            "iss": identity.did,
        }

        # 3. Sign with Agent's Ed25519 key
        # In a real system, we'd use the identity.signer directly with joserfc
        signer_key = identity._make_okp_key()
        protected = {"alg": "EdDSA", "typ": "JWM"}
        signature = sign_compact(protected, payload, signer_key)

        return cls(
            state=state,
            commitment=res.commitment,
            nonce=res.nonce,
            chain_root=chain_root,
            sender_did=identity.did,
            signature=signature,
        )

    async def verify(self) -> bool:
        """Verify the envelope's signature and commitment integrity."""
        # 1. Verify Tier 1 commitment matches state
        if not StateCommitment.verify(self.state, self.commitment, self.nonce):
            logger.error("a2a_commitment_mismatch")
            return False

        # 2. Resolve sender DID to get public key
        try:
            doc = await DIDManager.resolve(self.sender_did)
            # Find the Ed25519 public key (verificationMethod)
            pub_multibase = None
            for vm in doc.verification_methods:
                if vm.get("type") in ("Ed25519VerificationKey2020", "Ed25519VerificationKey2018"):
                    pub_multibase = vm.get("publicKeyMultibase")
                    break

            if not pub_multibase:
                logger.error("a2a_no_verification_key", did=self.sender_did)
                return False

            # Convert multibase to joserfc OKPKey
            import base58

            pub_bytes = base58.b58decode(pub_multibase[1:])  # Skip 'z'
            from base64 import urlsafe_b64encode

            x_b64 = urlsafe_b64encode(pub_bytes).rstrip(b"=").decode("utf-8")

            verification_key = OKPKey.import_key({"kty": "OKP", "crv": "Ed25519", "x": x_b64})

            # 3. Verify JWS signature
            member = verify_compact(self.signature, verification_key)
            payload = member.payload

            # 4. Verify payload matches envelope fields
            if payload.get("cmt") != base64.b64encode(self.commitment).decode():
                return False
            if payload.get("root") != base64.b64encode(self.chain_root).decode():
                return False
            return payload.get("iss") == self.sender_did
        except Exception as e:
            logger.error("a2a_verification_error", error=str(e))
            return False


class DiscoveryService:
    """Service for resolving Agent Cards and discovering capabilities."""

    @staticmethod
    async def get_agent_card(did: str) -> dict[str, Any]:
        """Fetch and verify an Agent Card from a DID."""
        doc = await DIDManager.resolve(did)
        # In did:web, the card might be at the service endpoint
        for svc in doc.services:
            if svc.get("type") == "AgentDiscovery":
                # Fetch card from service endpoint...
                pass
        return {}  # Placeholder
