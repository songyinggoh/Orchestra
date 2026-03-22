"""Central DID resolution and management (DD-8).

Integrates did:peer and did:web methods into a single interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from orchestra.identity.did_web import resolve_did_web
from orchestra.messaging.peer_did import resolve_peer_did

logger = structlog.get_logger(__name__)


@dataclass
class DIDDocument:
    """Simplified DID Document structure for Orchestra."""

    id: str
    verification_methods: list[dict[str, Any]] = field(default_factory=list)
    key_agreements: list[str] = field(default_factory=list)
    services: list[dict[str, Any]] = field(default_factory=list)

    def get_public_key_multibase(self, key_id: str) -> str | None:
        """Find the multibase public key for a given key ID."""
        for vm in self.verification_methods:
            if vm.get("id") == key_id or vm.get("id", "").endswith("#" + key_id):
                return vm.get("publicKeyMultibase")
        return None

    def get_encryption_key_id(self) -> str | None:
        """Return the first keyAgreement ID."""
        if self.key_agreements:
            return self.key_agreements[0]
        return None


class DIDManager:
    """Manager for resolving and handling DIDs."""

    @staticmethod
    async def resolve(did: str) -> DIDDocument:
        """Resolve any supported DID method into a DIDDocument."""
        logger.debug("did_resolve_start", did=did)

        try:
            if did.startswith("did:peer:2"):
                doc_dict = resolve_peer_did(did)
                return DIDDocument(
                    id=doc_dict["id"],
                    verification_methods=doc_dict["verificationMethod"],
                    key_agreements=doc_dict["keyAgreement"],
                    services=doc_dict["service"],
                )
            elif did.startswith("did:web:"):
                doc_dict = await resolve_did_web(did)
                return DIDDocument(
                    id=doc_dict["id"],
                    verification_methods=doc_dict.get("verificationMethod", []),
                    key_agreements=doc_dict.get("keyAgreement", []),
                    services=doc_dict.get("service", []),
                )
            else:
                raise ValueError(f"Unsupported DID method: {did}")
        except Exception as e:
            logger.error("did_resolve_failed", did=did, error=str(e))
            raise

    @staticmethod
    def get_method(did: str) -> str:
        """Extract the method name from a DID."""
        parts = did.split(":")
        if len(parts) >= 2:
            return parts[1]
        return "unknown"
