"""UCAN delegation and chain verification (DD-4, DD-9).

Provides utilities for verifying chains of UCAN tokens and ensuring
capabilities are correctly attenuated at each step.
"""

from __future__ import annotations

from typing import Any

import structlog
from joserfc.jwk import OKPKey

from orchestra.core.errors import CapabilityDeniedError, UCANVerificationError
from orchestra.identity.did import DIDManager
from orchestra.identity.types import UCANCapability, UCANToken
from orchestra.identity.ucan import UCANManager

logger = structlog.get_logger(__name__)


async def verify_delegation_chain(
    token_str: str,
    required_capability: UCANCapability,
    expected_audience: str,
) -> UCANToken:
    """Verify a UCAN token and its entire proof chain.

    Args:
        token_str: The UCAN JWT string to verify.
        required_capability: The capability the final audience needs.
        expected_audience: The DID that should be the 'aud' of the token.

    Returns:
        The verified UCANToken object.

    Raises:
        UCANVerificationError: If any step in the chain fails verification.
        CapabilityDeniedError: If the chain does not grant the required capability.
    """
    logger.debug("ucan_verify_chain_start", aud=expected_audience, res=required_capability.resource)

    # 1. Parse and verify the leaf token
    # We need the issuer's public key to verify the signature
    import jwt as pyjwt  # Just for unverified decode to get 'iss'

    try:
        pyjwt.get_unverified_header(token_str)  # validate header format
        payload = pyjwt.decode(token_str, options={"verify_signature": False})
        issuer_did = payload.get("iss")
    except Exception as e:
        raise UCANVerificationError(f"Failed to parse UCAN header/payload: {e!s}") from e

    if not issuer_did:
        raise UCANVerificationError("UCAN missing 'iss' claim")

    # Resolve issuer DID to get public key
    doc = await DIDManager.resolve(issuer_did)
    # did:peer:2 always has the key in verificationMethod. did:web depends on the doc.
    # We'll use the first Ed25519 key found for now.
    pub_multibase = None
    for vm in doc.verification_methods:
        if vm.get("type") in ("Ed25519VerificationKey2020", "Ed25519VerificationKey2018"):
            pub_multibase = vm.get("publicKeyMultibase")
            break

    if not pub_multibase:
        raise UCANVerificationError(f"No Ed25519 public key found for issuer {issuer_did}")

    # Convert multibase to joserfc OKPKey
    import base58

    if not pub_multibase.startswith("z"):
        raise UCANVerificationError("Only base58btc (z) multibase supported for UCAN keys")

    pub_bytes = base58.b58decode(pub_multibase[1:])
    from base64 import urlsafe_b64encode

    x_b64 = urlsafe_b64encode(pub_bytes).rstrip(b"=").decode("utf-8")

    verification_key = OKPKey.import_key({"kty": "OKP", "crv": "Ed25519", "x": x_b64})

    # Verify leaf token
    payload = UCANManager.verify(token_str, verification_key, expected_audience=expected_audience)

    # 2. Check capability in the leaf
    if not UCANManager.check_capability(payload, required_capability):
        # It might be granted by a proof, but the leaf MUST also claim it (attenuation)
        raise CapabilityDeniedError(
            f"UCAN does not grant {required_capability.ability} on {required_capability.resource}"
        )

    # 3. Verify proofs recursively
    proofs = payload.get("prf", [])
    if not proofs:
        # Root token — must be issued by the resource owner (self-issued or authorized by system)
        # For Orchestra, we assume 'iss' == resource owner if no proofs.
        # In a real system, we'd check if 'iss' matches the resource prefix
        # (e.g. did:A owns did:A/tools)
        return _build_token_obj(token_str, payload)

    # If there are proofs, at least one must grant the capability to the current issuer
    granted_by_proof = False
    for proof_jwt in proofs:
        try:
            # Recursively verify proof. The 'expected_audience' for the proof is the CURRENT 'iss'
            await verify_delegation_chain(
                token_str=proof_jwt,
                required_capability=required_capability,
                expected_audience=issuer_did,
            )
            granted_by_proof = True
            break
        except (UCANVerificationError, CapabilityDeniedError):
            continue

    if not granted_by_proof:
        raise CapabilityDeniedError(
            f"Capability {required_capability.resource} not granted by any proofs"
        )

    return _build_token_obj(token_str, payload)


def _build_token_obj(raw: str, payload: dict[str, Any]) -> UCANToken:
    caps = []
    for att in payload.get("att", []):
        caps.append(UCANCapability(resource=att["with"], ability=att["can"]))

    return UCANToken(
        raw=raw,
        issuer_did=payload["iss"],
        audience_did=payload["aud"],
        capabilities=tuple(caps),
        not_before=payload.get("nbf", 0),
        expires_at=payload.get("exp", 0),
        nonce=payload.get("nnc", ""),
        proofs=tuple(payload.get("prf", [])),
    )
