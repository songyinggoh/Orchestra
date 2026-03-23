"""did:web manager for long-lived agents."""

from __future__ import annotations

import base64
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class DidWebManager:
    """Manages did:web identities for long-lived agents."""

    def __init__(self, base_url: str) -> None:
        """
        Args:
            base_url: The domain name, e.g., 'orchestra.example.com'
        """
        self.base_url = base_url.strip("/")

    def create_did(self, agent_name: str) -> str:
        """Returns did:web:{base_url}:agents:{agent_name}"""
        safe_name = agent_name.replace("/", ":")
        return f"did:web:{self.base_url}:agents:{safe_name}"

    def build_did_document(
        self, did: str, ed_pub_bytes: bytes, x_pub_bytes: bytes, service_endpoint: str
    ) -> dict[str, Any]:
        """Build the did.json document for HTTP hosting.

        Args:
            did: The did:web identifier.
            ed_pub_bytes: Ed25519 public key bytes (for signing).
            x_pub_bytes: X25519 public key bytes (for encryption).
            service_endpoint: NATS URL or other communication endpoint.
        """

        def base64url_encode(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")

        ed_b64 = base64url_encode(ed_pub_bytes)
        x_b64 = base64url_encode(x_pub_bytes)

        return {
            "@context": [
                "https://www.w3.org/ns/did/v1",
                "https://w3id.org/security/suites/jws-2020/v1",
            ],
            "id": did,
            "verificationMethod": [
                {
                    "id": f"{did}#key-1",
                    "type": "JsonWebKey2020",
                    "controller": did,
                    "publicKeyJwk": {"kty": "OKP", "crv": "Ed25519", "x": ed_b64},
                },
                {
                    "id": f"{did}#key-2",
                    "type": "JsonWebKey2020",
                    "controller": did,
                    "publicKeyJwk": {"kty": "OKP", "crv": "X25519", "x": x_b64},
                },
            ],
            "authentication": [f"{did}#key-1"],
            "assertionMethod": [f"{did}#key-1"],
            "keyAgreement": [f"{did}#key-2"],
            "service": [
                {
                    "id": f"{did}#service-1",
                    "type": "DIDCommMessaging",
                    "serviceEndpoint": service_endpoint,
                }
            ],
        }

    async def resolve(self, did: str) -> dict[str, Any]:
        """Resolve did:web by fetching did.json via HTTPS."""
        return await resolve_did_web(did)


async def resolve_did_web(did: str) -> dict[str, Any]:
    """Resolve did:web by fetching did.json via HTTPS."""
    if not did.startswith("did:web:"):
        raise ValueError(f"Invalid did:web: {did}")

    parts = did.split(":")
    domain = parts[2]
    path = "/".join(parts[3:])

    if not path:
        url = f"https://{domain}/.well-known/did.json"
    else:
        url = f"https://{domain}/{path}/did.json"

    logger.debug("resolving_did_web", did=did, url=url)

    import aiohttp

    async with aiohttp.ClientSession() as session, session.get(url) as response:
        if response.status != 200:
            raise RuntimeError(f"Failed to resolve {did}: HTTP {response.status}")
        return await response.json()
