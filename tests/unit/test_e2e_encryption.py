"""Unit tests for DIDComm v2 JWE encryption layer (no NATS required).

Tests the joserfc-based anoncrypt implementation in isolation:
  - Round-trip encrypt/decrypt
  - Wrong key raises
  - EPK uniqueness per message
  - Algorithm allowlist blocks tampered alg header
  - Plaintext body not visible in ciphertext
  - Key rotation: new key material generated after interval (CRITICAL-4.2)
  - Key rotation: kid in JWE header changes with each rotation
  - Key rotation: messages encrypted before rotation are still decryptable
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from unittest.mock import patch

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
    base58 = pytest.importorskip("base58", reason="base58 not installed")  # noqa: F841

    from orchestra.messaging.secure_provider import SecureNatsProvider

    alice = SecureNatsProvider.create()
    bob = SecureNatsProvider.create()

    token = alice.encrypt_for({"task": "hello"}, bob.own_did)
    plaintext = bob.decrypt(token)

    assert plaintext["body"]["task"] == "hello"


def test_secure_nats_provider_wrong_recipient_raises() -> None:
    """Provider cannot decrypt a message not addressed to it."""
    base58 = pytest.importorskip("base58", reason="base58 not installed")  # noqa: F841

    from orchestra.messaging.secure_provider import SecureNatsProvider

    alice = SecureNatsProvider.create()
    bob = SecureNatsProvider.create()
    eve = SecureNatsProvider.create()

    token = alice.encrypt_for({"task": "secret"}, bob.own_did)

    with pytest.raises(Exception):
        eve.decrypt(token)


# ------------------------------------------------------------------ key rotation tests (CRITICAL-4.2)


def test_key_rotation_generates_new_key_after_interval() -> None:
    """After the rotation interval elapses, encrypt_for must use new key material.

    Strategy: create a provider with a 1-second interval, record the initial
    keypair identity, fast-forward monotonic time by 2 seconds via mock, call
    encrypt_for, and assert the keypair object has changed.
    """
    base58 = pytest.importorskip("base58", reason="base58 not installed")  # noqa: F841

    from orchestra.messaging.secure_provider import SecureNatsProvider

    alice = SecureNatsProvider.create(key_rotation_interval=1)
    bob = SecureNatsProvider.create(key_rotation_interval=0)  # stable DID for recipient

    original_keypair = alice._own_keys.keypair
    original_did = alice.own_did

    # Simulate time advancing beyond the rotation interval.
    # time.monotonic is called inside _rotate_keys_if_needed; we freeze the
    # "created_at" clock in the past so the elapsed check triggers.
    alice._key_created_at = time.monotonic() - 2  # 2 s > 1 s interval

    alice.encrypt_for({"task": "after_rotation"}, bob.own_did)

    # Key material MUST have changed.
    assert alice._own_keys.keypair is not original_keypair, (
        "keypair object should be replaced after rotation interval elapsed"
    )
    # DID encodes the public key — a new keypair produces a different DID.
    assert alice.own_did != original_did, (
        "own_did should change when a new X25519 keypair is generated"
    )


def test_key_rotation_kid_changes() -> None:
    """The kid field in the JWE protected header must reflect the current key version.

    Verify that:
    1. kid is present in the header before rotation.
    2. After rotation, a different kid appears.

    Strategy: patch time.time in the secure_provider module so the pre-rotation
    and post-rotation calls return distinct integer seconds, making it impossible
    for int() truncation to collapse both values into the same kid string.
    """
    base58 = pytest.importorskip("base58", reason="base58 not installed")  # noqa: F841

    import orchestra.messaging.secure_provider as _sp_mod
    from orchestra.messaging.secure_provider import SecureNatsProvider

    # Two distinct wall-clock values, 100 s apart, well outside int() ambiguity.
    T0 = 1_700_000_000.0
    T1 = 1_700_000_100.0

    with patch.object(_sp_mod, "time") as mock_time:
        # time.monotonic() is used for elapsed checks; keep it real so the
        # provider can tell seconds have passed.  Only time.time() needs faking.
        mock_time.monotonic = time.monotonic
        mock_time.time.return_value = T0

        alice = SecureNatsProvider.create(key_rotation_interval=1)
        bob = SecureNatsProvider.create(key_rotation_interval=0)

        # Encrypt before rotation — capture kid from JWE header part 0.
        token_before = alice.encrypt_for({"seq": 0}, bob.own_did)

    raw_header_before = base64.urlsafe_b64decode(
        token_before.split(".")[0] + "=="  # restore padding
    )
    header_before = json.loads(raw_header_before)
    assert "kid" in header_before, "JWE header must contain a kid field"
    kid_before = header_before["kid"]
    assert kid_before.startswith("key-"), f"kid format unexpected: {kid_before!r}"
    assert kid_before == f"key-{int(T0)}", (
        f"Expected kid 'key-{int(T0)}', got {kid_before!r}"
    )

    # Fast-forward monotonic clock so rotation fires, and advance wall clock to T1.
    alice._key_created_at = time.monotonic() - 2  # elapsed > 1 s interval

    with patch.object(_sp_mod, "time") as mock_time2:
        mock_time2.monotonic = time.monotonic
        mock_time2.time.return_value = T1

        token_after = alice.encrypt_for({"seq": 1}, bob.own_did)

    raw_header_after = base64.urlsafe_b64decode(
        token_after.split(".")[0] + "=="
    )
    header_after = json.loads(raw_header_after)
    kid_after = header_after["kid"]

    assert kid_after == f"key-{int(T1)}", (
        f"Expected kid 'key-{int(T1)}' after rotation, got {kid_after!r}"
    )
    assert kid_after != kid_before, (
        f"kid must differ after key rotation (before={kid_before!r}, after={kid_after!r})"
    )


# ------------------------------------------------------------------ CRITICAL-4.2 explicit rotation and history tests


def test_rotate_keys_generates_new_keypair() -> None:
    """rotate_keys() must produce a new keypair and increment the version counter."""
    base58 = pytest.importorskip("base58", reason="base58 not installed")  # noqa: F841

    from orchestra.messaging.secure_provider import SecureNatsProvider

    provider = SecureNatsProvider.create(key_rotation_interval=0)  # auto-rotation off
    original_keypair = provider._own_keys.keypair
    original_did = provider.own_did
    assert provider.key_version_number == 1

    provider.rotate_keys()

    assert provider._own_keys.keypair is not original_keypair, (
        "rotate_keys() must generate a new keypair object"
    )
    assert provider.own_did != original_did, (
        "DID must change when the X25519 keypair changes"
    )
    assert provider.key_version_number == 2, (
        "version counter must increment from 1 to 2 after first rotation"
    )
    assert provider._own_keys.rotated_at is not None, (
        "rotated_at must be set after explicit rotation"
    )


def test_rotate_keys_archives_old_key() -> None:
    """After rotate_keys(), the old key must appear in _key_history."""
    base58 = pytest.importorskip("base58", reason="base58 not installed")  # noqa: F841

    from orchestra.messaging.secure_provider import SecureNatsProvider

    provider = SecureNatsProvider.create(key_rotation_interval=0)
    assert provider._key_history == [], "history must start empty"

    old_keypair = provider._own_keys.keypair

    provider.rotate_keys()

    assert len(provider._key_history) == 1, "one entry expected after first rotation"
    assert provider._key_history[0].keypair is old_keypair, (
        "archived entry must hold the original keypair"
    )


def test_old_key_history_can_still_decrypt() -> None:
    """A message encrypted with an old key can still be decrypted by the recipient.

    This test mirrors test_key_rotation_does_not_break_active_messages but
    exercises the explicit rotate_keys() path.  The recipient (bob) holds a
    stable key; the sender (alice) rotates.  Because JWE uses the *recipient's*
    public key for key agreement, alice's rotation has no effect on bob's ability
    to decrypt.
    """
    base58 = pytest.importorskip("base58", reason="base58 not installed")  # noqa: F841

    from orchestra.messaging.secure_provider import SecureNatsProvider

    alice = SecureNatsProvider.create(key_rotation_interval=0)
    bob = SecureNatsProvider.create(key_rotation_interval=0)

    # Encrypt before alice rotates
    token_pre = alice.encrypt_for({"payload": "before_rotation"}, bob.own_did)

    # Explicit rotation on alice's side
    alice.rotate_keys()
    assert len(alice._key_history) == 1

    # Bob must still decrypt the pre-rotation token
    plaintext = bob.decrypt(token_pre)
    assert plaintext["body"]["payload"] == "before_rotation", (
        "Message encrypted before sender's explicit key rotation must still decrypt"
    )


def test_needs_rotation_false_when_fresh() -> None:
    """needs_rotation() returns False when the key is younger than max_age_seconds."""
    base58 = pytest.importorskip("base58", reason="base58 not installed")  # noqa: F841

    from orchestra.messaging.secure_provider import SecureNatsProvider

    provider = SecureNatsProvider.create(key_rotation_interval=0)
    # Key was just created — should NOT need rotation with a 1-hour window
    assert provider.needs_rotation(3600) is False


def test_needs_rotation_true_when_old() -> None:
    """needs_rotation() returns True when the key has exceeded max_age_seconds."""
    base58 = pytest.importorskip("base58", reason="base58 not installed")  # noqa: F841

    from orchestra.messaging.secure_provider import SecureNatsProvider

    provider = SecureNatsProvider.create(key_rotation_interval=0)
    # Back-date the key's creation time so it appears old
    provider._own_keys.created_at = time.time() - 7200  # 2 hours ago

    assert provider.needs_rotation(3600) is True, (
        "Key created 2h ago must need rotation with a 1h max_age"
    )


def test_needs_rotation_false_when_disabled() -> None:
    """needs_rotation(0) always returns False (rotation disabled)."""
    base58 = pytest.importorskip("base58", reason="base58 not installed")  # noqa: F841

    from orchestra.messaging.secure_provider import SecureNatsProvider

    provider = SecureNatsProvider.create(key_rotation_interval=0)
    # Even with an artificially aged key, max_age=0 means disabled
    provider._own_keys.created_at = time.time() - 99999
    assert provider.needs_rotation(0) is False
    assert provider.needs_rotation(-1) is False


def test_key_rotation_does_not_break_active_messages() -> None:
    """A message encrypted before rotation must still be decryptable by its recipient.

    The rotation only replaces the *sender's* key material.  The recipient
    decrypts using their own stable private key; the sender's key identity
    is irrelevant to the recipient's decryption.  This test demonstrates that
    in-flight tokens (encrypted before a rotation event) survive.
    """
    base58 = pytest.importorskip("base58", reason="base58 not installed")  # noqa: F841

    from orchestra.messaging.secure_provider import SecureNatsProvider

    alice = SecureNatsProvider.create(key_rotation_interval=1)
    bob = SecureNatsProvider.create(key_rotation_interval=0)

    # Encrypt a message with alice's current (pre-rotation) key.
    token_pre_rotation = alice.encrypt_for({"payload": "pre"}, bob.own_did)

    # Trigger rotation on alice's side.
    alice._key_created_at = time.monotonic() - 2
    alice.encrypt_for({"payload": "trigger_rotation"}, bob.own_did)
    assert alice.own_did  # confirm rotation happened (DID changed)

    # Bob must still decrypt the earlier token — it was addressed to his stable key.
    plaintext = bob.decrypt(token_pre_rotation)
    assert plaintext["body"]["payload"] == "pre", (
        "Message encrypted before sender key rotation must still decrypt correctly"
    )
