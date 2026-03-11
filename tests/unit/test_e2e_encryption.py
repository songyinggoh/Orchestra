"""Unit tests for DIDComm v2 JWE encryption layer (no NATS required).

Tests the joserfc-based anoncrypt implementation in isolation:
  - Round-trip encrypt/decrypt
  - Wrong key raises
  - EPK uniqueness per message
  - Algorithm allowlist blocks tampered alg header
  - Plaintext body not visible in ciphertext
"""

from __future__ import annotations

import json
import uuid

import pytest

joserfc = pytest.importorskip("joserfc", reason="joserfc not installed")

from joserfc import jwe
from joserfc.jwk import OKPKey

# ------------------------------------------------------------------ helpers

_HEADER = {
    "alg": "ECDH-ES+A256KW",
    "enc": "A256GCM",
    "typ": "application/didcomm-encrypted+json",
}


def _make_jwm(body: dict) -> bytes:
    return json.dumps(
        {"id": str(uuid.uuid4()), "type": "task/1.0/request", "body": body}
    ).encode()


def _encrypt(pub_key: OKPKey, body: dict) -> str:
    return jwe.encrypt_compact(dict(_HEADER), _make_jwm(body), pub_key)


def _decrypt(token: str, priv_key: OKPKey) -> dict:
    from joserfc.jwe import JWERegistry

    registry = JWERegistry(algorithms=["ECDH-ES+A256KW", "A256GCM"])
    result = jwe.decrypt_compact(token, priv_key, registry=registry)
    return json.loads(result.plaintext)


# ------------------------------------------------------------------ tests


def test_anoncrypt_round_trip() -> None:
    """encrypt → wire → decrypt recovers original body."""
    keypair = OKPKey.generate_key("X25519")
    pub = OKPKey.import_key(keypair.as_dict(private=False))

    token = _encrypt(pub, {"task_id": "t1", "secret": "s3cr3t"})
    plaintext = _decrypt(token, keypair)

    assert plaintext["body"]["task_id"] == "t1"
    assert plaintext["body"]["secret"] == "s3cr3t"
    assert "id" in plaintext


def test_wrong_key_raises() -> None:
    """Decryption with a different private key must raise — not return garbage."""
    keypair = OKPKey.generate_key("X25519")
    wrong_key = OKPKey.generate_key("X25519")
    pub = OKPKey.import_key(keypair.as_dict(private=False))

    token = _encrypt(pub, {"secret": "value"})

    with pytest.raises(Exception):
        _decrypt(token, wrong_key)


def test_epk_unique_per_message() -> None:
    """Every encrypt_compact call produces a distinct EPK (no reuse)."""
    keypair = OKPKey.generate_key("X25519")
    pub = OKPKey.import_key(keypair.as_dict(private=False))

    # JWE compact = header.key.iv.ciphertext.tag — part[0] contains the EPK
    headers = {
        jwe.encrypt_compact(dict(_HEADER), b"same payload", pub).split(".")[0]
        for _ in range(10)
    }
    assert len(headers) == 10, "EPK must differ on every encrypt call"


def test_plaintext_not_in_ciphertext() -> None:
    """Sensitive payload fields must not appear in the JWE token."""
    keypair = OKPKey.generate_key("X25519")
    pub = OKPKey.import_key(keypair.as_dict(private=False))

    token = _encrypt(pub, {"api_key": "sk-supersecret", "user": "alice"})

    assert "supersecret" not in token
    assert "alice" not in token
    # Compact JWE has exactly 5 parts
    assert token.count(".") == 4


def test_algorithm_allowlist_blocks_wrong_alg() -> None:
    """JWERegistry must reject tokens whose alg is not on the allowlist."""
    from joserfc.jwe import JWERegistry

    keypair = OKPKey.generate_key("X25519")
    pub = OKPKey.import_key(keypair.as_dict(private=False))
    token = _encrypt(pub, {"data": "x"})

    # Allowlist that excludes the correct algorithm
    strict_registry = JWERegistry(algorithms=["RSA-OAEP", "A256GCM"])
    with pytest.raises(Exception):
        jwe.decrypt_compact(token, keypair, registry=strict_registry)


def test_secure_nats_provider_round_trip() -> None:
    """SecureNatsProvider.encrypt_for / decrypt round-trip (no NATS needed)."""
    peerdid = pytest.importorskip("peerdid", reason="peerdid not installed")  # noqa: F841
    base58 = pytest.importorskip("base58", reason="base58 not installed")  # noqa: F841

    from orchestra.messaging.secure_provider import SecureNatsProvider

    alice = SecureNatsProvider.create()
    bob = SecureNatsProvider.create()

    token = alice.encrypt_for({"task": "hello"}, bob.own_did)
    plaintext = bob.decrypt(token)

    assert plaintext["body"]["task"] == "hello"


def test_secure_nats_provider_wrong_recipient_raises() -> None:
    """Provider cannot decrypt a message not addressed to it."""
    peerdid = pytest.importorskip("peerdid", reason="peerdid not installed")  # noqa: F841
    base58 = pytest.importorskip("base58", reason="base58 not installed")  # noqa: F841

    from orchestra.messaging.secure_provider import SecureNatsProvider

    alice = SecureNatsProvider.create()
    bob = SecureNatsProvider.create()
    eve = SecureNatsProvider.create()

    token = alice.encrypt_for({"task": "secret"}, bob.own_did)

    with pytest.raises(Exception):
        eve.decrypt(token)
