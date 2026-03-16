---
status: resolved
trigger: "Investigate, re-assess, reproduce, and fix CRITICAL-4.2 — No Key Rotation or Expiry in SecureNatsProvider"
created: 2026-03-15T00:00:00Z
updated: 2026-03-15T00:30:00Z
---

## Current Focus

hypothesis: Session keys in SecureNatsProvider are static for the provider lifetime — confirmed.
test: Read source, verified no rotation path exists. Now implementing fix.
expecting: After fix, key material changes after key_rotation_interval elapses; kid in JWE header reflects version.
next_action: Implement _rotate_keys_if_needed() in secure_provider.py; add kid to _PROTECTED_HEADER per-call; write tests.

## Symptoms

expected: Key material should rotate periodically so a compromised key limits the blast radius to one interval.
actual: AgentKeyMaterial is set once in __init__ and never replaced. No TTL, no kid versioning in JWE header.
errors: No runtime error — silent security gap.
reproduction: Create SecureNatsProvider; check `provider._own_keys.keypair` at t=0 and t+1h — identical object.
started: Always — no rotation was ever implemented.

## Eliminated

- hypothesis: Some lazy-init mechanism rotates keys on the second encrypt_for call.
  evidence: __init__ stores own_keys directly; encrypt_for calls _resolve_recipient but never touches _own_keys.
  timestamp: 2026-03-15T00:00:00Z

- hypothesis: kid versioning already present in JWE header.
  evidence: _PROTECTED_HEADER is a module-level constant with no kid field; encrypt_for passes dict(_PROTECTED_HEADER) unchanged.
  timestamp: 2026-03-15T00:00:00Z

## Evidence

- timestamp: 2026-03-15T00:00:00Z
  checked: secure_provider.py lines 68-69, 104-121, 144-150
  found: __init__ takes AgentKeyMaterial and stores it as self._own_keys; create() generates keys once and returns cls(AgentKeyMaterial(...)); no mutation of _own_keys after construction.
  implication: Key lifetime == provider lifetime. No rotation mechanism exists.

- timestamp: 2026-03-15T00:00:00Z
  checked: _PROTECTED_HEADER constant (lines 30-34) and encrypt_for (lines 145-149)
  found: Header dict is static; kid field absent; passed as dict(_PROTECTED_HEADER) copy with no augmentation.
  implication: Recipients cannot distinguish key versions. Forward-secrecy window is unbounded.

- timestamp: 2026-03-15T00:00:00Z
  checked: peer_did.py — create_peer_did_numalgo_2 / resolve_peer_did
  found: DID is fully self-contained (numalgo 2 — key material encoded inline). Rotation requires generating a new DID.
  implication: Key rotation = new (X25519 keypair + did:peer:2 DID). own_did changes on rotation. Callers using own_did as stable address need awareness — but that is acceptable for a session-scoped provider.

- timestamp: 2026-03-15T00:00:00Z
  checked: identity/ directory for duplicate pattern
  found: agent_identity.py holds Ed25519 signing key (identity, not message encryption). No rotation needed there per scope. No other X25519 static key usage found outside secure_provider.py.
  implication: CRITICAL-4.2 is isolated to SecureNatsProvider.

## Resolution

root_cause: SecureNatsProvider stores AgentKeyMaterial once in __init__ and never replaces it. encrypt_for passes a static _PROTECTED_HEADER with no kid field. There is no timer, counter, or trigger for regenerating key material.
fix: |
  1. Add key_rotation_interval: int = 3600 parameter to SecureNatsProvider.__init__.
  2. Store _key_created_at: float = time.monotonic() alongside the initial keys.
  3. Add _rotate_keys_if_needed(): if elapsed > interval, call the same key-generation
     block from create() and replace self._own_keys + self._key_created_at in-place.
     Clear _recipient_cache on rotation (stale own_did no longer valid for inbound).
  4. In encrypt_for(), call _rotate_keys_if_needed() before building the JWM.
     Build a per-call protected header that includes kid=f"key-{int(self._key_created_at)}".
  5. No changes to decrypt() — incoming messages carry the sender's EPK; recipient
     key selection is by own private key, not kid. kid in the header is informational
     for the sender's version.
  6. create() passes key_rotation_interval through so factory callers can configure it.
verification: |
  python -m pytest tests/unit/test_e2e_encryption.py -v → 10/10 passed.
  python -m pytest tests/unit/ → 572 passed, 3 pre-existing race-condition
  failures in test_phase2_race_conditions.py (unrelated to this change).
files_changed:
  - src/orchestra/messaging/secure_provider.py
  - tests/unit/test_e2e_encryption.py
