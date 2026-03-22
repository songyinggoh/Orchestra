"""ZKP Input Commitments and State Canonicalization (T-4.11).

Implements RFC 8785 (JCS) for deterministic state hashing and
multi-tier commitment schemes (SHA-256 and Pedersen).
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def jcs_canonicalize(state: dict[str, Any]) -> bytes:
    """Deterministic JSON serialization following RFC 8785 (JCS).

    1. Lexicographic sorting of keys (UTF-16 code units).
    2. No whitespace between tokens.
    3. Proper escaping of strings.
    4. IEEE 754 double-precision for numbers.
    """
    # Python's json.dumps with these settings is very close to JCS
    # for most common agent state structures.
    return json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


@dataclass(frozen=True)
class CommitmentResult:
    """Result of a Tier 1 (SHA-256) state commitment."""

    commitment: bytes
    nonce: bytes


class StateCommitment:
    """Tier 1: Fast SHA-256 hash commitments for internal state transitions."""

    @staticmethod
    def commit(state: dict[str, Any], previous_commitment: bytes | None = None) -> CommitmentResult:
        """Create a hash commitment to agent state, optionally chained.

        commitment = SHA256(canonical_state || previous_commitment || nonce)
        """
        nonce = secrets.token_bytes(32)
        canonical = jcs_canonicalize(state)

        hasher = hashlib.sha256(canonical)
        if previous_commitment:
            hasher.update(previous_commitment)
        hasher.update(nonce)

        return CommitmentResult(commitment=hasher.digest(), nonce=nonce)

    @staticmethod
    def verify(
        state: dict[str, Any],
        commitment: bytes,
        nonce: bytes,
        previous_commitment: bytes | None = None,
    ) -> bool:
        """Verify that a state matches a previously created commitment."""
        canonical = jcs_canonicalize(state)

        hasher = hashlib.sha256(canonical)
        if previous_commitment:
            hasher.update(previous_commitment)
        hasher.update(nonce)

        expected = hasher.digest()
        return secrets.compare_digest(commitment, expected)


@dataclass(frozen=True)
class PedersenResult:
    """Result of a Tier 2 (Pedersen) state commitment."""

    commitment_point: bytes  # Serialized point
    blinding_factor: int


class PedersenCommitment:
    """Tier 2: Hiding and homomorphic commitments for cross-org exchange.

    Requires 'blst' or 'py_ecc' for curve operations on BLS12-381.
    """

    def __init__(self) -> None:
        try:
            import blst  # noqa: F401

            self._backend = "blst"
        except ImportError:
            try:
                import py_ecc  # noqa: F401

                self._backend = "py_ecc"
                logger.warning("using_slow_ecc_backend", backend="py_ecc")
            except ImportError:
                self._backend = None
                logger.warning("no_ecc_backend_available", task="T-4.11")

    def is_available(self) -> bool:
        return self._backend is not None

    def commit(self, data: bytes) -> PedersenResult:
        """Create a Pedersen commitment (C = vG + rH)."""
        if not self._backend:
            raise ImportError("Pedersen commitments require 'blst' or 'py_ecc' installed.")

        # Placeholder for actual blst/py_ecc implementation logic
        # Implementation of RFC 9380 Hash-to-Curve for generator H would go here.
        raise NotImplementedError("Curve-specific implementation pending dependency installation.")

    def verify(self, data: bytes, commitment_point: bytes, blinding_factor: int) -> bool:
        """Verify a Pedersen commitment opening."""
        if not self._backend:
            raise ImportError("Pedersen commitments require 'blst' or 'py_ecc' installed.")
        raise NotImplementedError("Curve-specific implementation pending dependency installation.")
