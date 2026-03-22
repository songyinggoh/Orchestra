"""UCAN (User Controlled Authorization Networks) implementation for Orchestra.

Implements UCAN 0.8.1 tokens directly via joserfc JWT.
Per DD-9: py-ucan is dropped entirely.
Per DD-4: capabilities can only be narrowed, never widened.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Sequence
from typing import Any

import structlog
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import OKPKey

from orchestra.core.errors import UCANVerificationError
from orchestra.identity.types import UCANCapability

logger = structlog.get_logger(__name__)


class UCANManager:
    """Issues and verifies UCAN tokens using joserfc JWT."""

    UCV = "0.8.1"

    def __init__(self, signing_key: OKPKey | None = None, issuer_did: str | None = None) -> None:
        self._signing_key = signing_key
        self._issuer_did = issuer_did

    def issue(
        self,
        audience_did: str,
        capabilities: Sequence[UCANCapability],
        ttl_seconds: int = 3600,
        proofs: list[str] | None = None,
        not_before: int | None = None,
    ) -> str:
        """Issue a signed UCAN token."""
        if not self._signing_key or not self._issuer_did:
            raise RuntimeError(
                "UCANManager must be initialized with signing_key and issuer_did to issue tokens"
            )

        now = int(time.time())
        header = {"alg": "EdDSA", "typ": "JWT"}
        payload = {
            "ucv": self.UCV,
            "iss": self._issuer_did,
            "aud": audience_did,
            "nbf": not_before or (now - 60),
            "exp": now + ttl_seconds,
            "att": [{"with": cap.resource, "can": cap.ability} for cap in capabilities],
            "prf": proofs or [],
            "nnc": secrets.token_hex(8),
        }
        # RFC 9864 / joserfc requirement
        return jwt.encode(header, payload, self._signing_key, algorithms=["EdDSA"])

    @staticmethod
    def verify(
        token_str: str,
        verification_key: OKPKey,
        expected_audience: str | None = None,
    ) -> dict[str, Any]:
        """Verify signature and basic claims (expiry, audience)."""
        try:
            decoded = jwt.decode(token_str, verification_key, algorithms=["EdDSA"])
            payload = decoded.claims
        except JoseError as e:
            raise UCANVerificationError(f"JWT verification failed: {e!s}") from e

        now = int(time.time())

        # 1. Expiry check (DD-4: expired = deny all)
        if payload.get("exp", 0) < now:
            raise UCANVerificationError(f"UCAN expired at {payload.get('exp')}")

        # 2. Not-before check
        if payload.get("nbf", 0) > now + 60:  # 1 min clock skew grace
            raise UCANVerificationError(f"UCAN not yet valid (nbf: {payload.get('nbf')})")

        # 3. Audience check
        if expected_audience and payload.get("aud") != expected_audience:
            raise UCANVerificationError(
                f"Audience mismatch: expected {expected_audience}, got {payload.get('aud')}"
            )

        return payload

    @staticmethod
    def check_capability(
        payload: dict[str, Any],
        required: UCANCapability,
    ) -> bool:
        """Check if the payload grants the required capability.

        DD-4: capabilities can only narrow, never widen.  A granted resource
        matches the required resource only when:
          - exact match:            granted == required
          - explicit wildcard:      granted ends with "/*" and required is
                                    within that namespace
                                    e.g. "orchestra:tools/*" grants
                                         "orchestra:tools/web_search"

        A bare parent scope (e.g. "orchestra:tools") does NOT implicitly
        grant child resources ("orchestra:tools/web_search").
        """
        att = payload.get("att", [])
        for entry in att:
            granted_resource = entry.get("with", "")
            granted_ability = entry.get("can", "")

            # Exact match
            if granted_resource == required.resource:
                resource_match = True
            # Explicit wildcard: "namespace/*" covers "namespace/anything"
            elif granted_resource.endswith("/*"):
                namespace = granted_resource[:-2]  # strip "/*"
                resource_match = required.resource.startswith(namespace + "/")
            else:
                resource_match = False

            # Ability match or wildcard '*'
            ability_match = granted_ability == required.ability or granted_ability == "*"

            if resource_match and ability_match:
                return True

        return False

    def delegate(
        self,
        parent_token: str,
        audience_did: str,
        capabilities: Sequence[UCANCapability],
        ttl_seconds: int = 3600,
    ) -> str:
        """Delegate capabilities from a parent token."""
        # Note: we don't strictly verify the parent token has the caps here,
        # that's done by the final consumer.
        return self.issue(
            audience_did=audience_did,
            capabilities=capabilities,
            ttl_seconds=ttl_seconds,
            proofs=[parent_token],
        )
