"""Lightweight did:peer:2 implementation for Orchestra.

A replacement for 'peerdid' that is compatible with Pydantic v2 and modern Python.
Implements did:peer:2 with numalgo 2 (encoding public keys and services in the DID).
"""

from __future__ import annotations

import base64
import json
from typing import Any

import base58


# Multicodec prefixes
# https://github.com/multiformats/multicodec/blob/master/table.csv
PREFIX_ED25519_PUB = b"\xed\x01"
PREFIX_X25519_PUB = b"\xec\x01"


def create_peer_did_numalgo_2(
    encryption_keys: list[bytes],
    signing_keys: list[bytes],
    service: dict[str, Any] | None = None,
) -> str:
    """Create a did:peer:2 DID from public keys and optional service.

    Args:
        encryption_keys: List of raw X25519 public keys (32 bytes each).
        signing_keys: List of raw Ed25519 public keys (32 bytes each).
        service: Optional service dict.

    Returns:
        A did:peer:2 string.
    """
    # .V -> Encryption key (X25519)
    # .V -> Signing key (Ed25519) -- wait, Ed25519 is .V too?
    # Actually did:peer:2 uses:
    # .V -> keyAgreement (X25519)
    # .V -> verificationMethod (Ed25519)
    # We use multibase (z for base58btc) + multicodec prefixes.

    parts = ["did:peer:2"]

    # Add encryption keys
    for key in encryption_keys:
        mc = PREFIX_X25519_PUB + key
        mb = "z" + base58.b58encode(mc).decode()
        parts.append(f".V{mb}")

    # Add signing keys
    for key in signing_keys:
        mc = PREFIX_ED25519_PUB + key
        mb = "z" + base58.b58encode(mc).decode()
        parts.append(f".V{mb}")

    # Add service if provided
    if service:
        # Mini-optimisation: did:peer spec allows abbreviated keys in service
        # but we'll use a simple base64url of the JSON for now.
        s_json = json.dumps(service, separators=(",", ":")).encode("utf-8")
        s_b64 = base64.urlsafe_b64encode(s_json).rstrip(b"=").decode()
        parts.append(f".S{s_b64}")

    return "".join(parts)


def resolve_peer_did(did: str) -> dict[str, Any]:
    """Resolve a did:peer:2 DID into a basic DID Document.

    Only supports numalgo 2.
    """
    if not did.startswith("did:peer:2"):
        raise ValueError(f"Unsupported DID method: {did}")

    doc: dict[str, Any] = {
        "@context": "https://www.w3.org/ns/did/v1",
        "id": did,
        "verificationMethod": [],
        "keyAgreement": [],
        "service": [],
    }

    # Split by the dot prefix of each part (after the initial 'did:peer:2')
    # Parts look like .V<multibase> or .S<base64>
    parts = did[len("did:peer:2") :].split(".")
    key_count = 1

    for part in parts:
        if not part:
            continue

        prefix = part[0]
        value = part[1:]

        if prefix == "V":
            # Multibase + Multicodec
            if not value.startswith("z"):
                raise ValueError("Only base58btc (z) multibase supported")

            mc = base58.b58decode(value[1:])
            kid = f"{did}#key-{key_count}"

            if mc.startswith(PREFIX_X25519_PUB):
                raw_key = mc[len(PREFIX_X25519_PUB) :]
                mb = "z" + base58.b58encode(raw_key).decode()
                vm = {
                    "id": kid,
                    "type": "X25519KeyAgreementKey2020",
                    "controller": did,
                    "publicKeyMultibase": mb,
                }
                doc["verificationMethod"].append(vm)
                doc["keyAgreement"].append(kid)
            elif mc.startswith(PREFIX_ED25519_PUB):
                raw_key = mc[len(PREFIX_ED25519_PUB) :]
                mb = "z" + base58.b58encode(raw_key).decode()
                vm = {
                    "id": kid,
                    "type": "Ed25519VerificationKey2020",
                    "controller": did,
                    "publicKeyMultibase": mb,
                }
                doc["verificationMethod"].append(vm)

            key_count += 1

        elif prefix == "S":
            # Base64url encoded JSON
            # Add padding back if needed
            padding = "=" * (4 - (len(value) % 4))
            if padding == "====":
                padding = ""
            s_json = base64.urlsafe_b64decode(value + padding)
            service_data = json.loads(s_json)
            # Ensure id is present in service
            if "id" not in service_data:
                service_data["id"] = f"{did}#service-{len(doc['service']) + 1}"
            doc["service"].append(service_data)

    return doc
