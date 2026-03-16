---
status: resolved
trigger: "Investigate, re-assess, reproduce, and fix CRITICAL-3.3 — Generic Exception Handler in UCAN Verification"
created: 2026-03-15T00:00:00Z
updated: 2026-03-15T00:00:00Z
---

## Current Focus

hypothesis: `except Exception as e` on ucan.py:71 wraps joserfc jwt.decode. This genuinely catches programmer errors (AttributeError, TypeError) and converts them to UCANVerificationError, hiding bugs. Also found a second identical pattern in delegation.py:50 wrapping pyjwt unverified decode.
test: narrow the catch to joserfc.errors.JoseError only; verify AttributeError propagates
expecting: programmer errors propagate; JoseError (bad sig, expired, invalid payload) still map to UCANVerificationError
next_action: apply fix to ucan.py:71, then run full test suite

## Symptoms

expected: programmer errors (AttributeError, TypeError) should propagate as-is from UCANManager.verify()
actual: ALL exceptions including AttributeError are caught and re-raised as UCANVerificationError
errors: none (silent mis-classification)
reproduction: pass a None/malformed key → raises UCANVerificationError instead of TypeError
started: since initial implementation

## Eliminated

- hypothesis: broad catch is safe because joserfc only raises JoseError subclasses
  evidence: joserfc jwt.decode can raise ValueError internally if payload JSON is malformed (InvalidPayloadError extends JoseError), but the key object operations before .claims access can raise AttributeError/TypeError on bad inputs
  timestamp: 2026-03-15

- hypothesis: delegation.py:50 is in scope for this fix
  evidence: delegation.py uses PyJWT (not joserfc) for unverified pre-decode; that broad catch is a separate issue outside CRITICAL-3.3 scope. did.py:69 just re-raises, so it is a logging wrapper, not a swallowing pattern. agent_identity.py catches are unrelated to JWT.
  timestamp: 2026-03-15

## Evidence

- timestamp: 2026-03-15
  checked: ucan.py lines 68-72
  found: try block calls jwt.decode(token_str, verification_key, algorithms=["EdDSA"]) then accesses decoded.claims. The except Exception catches everything — including bad key object AttributeErrors before joserfc even runs.
  implication: any programmer error producing AttributeError/TypeError in the decode call becomes UCANVerificationError, hiding the root cause

- timestamp: 2026-03-15
  checked: joserfc exception hierarchy (live introspection)
  found: all joserfc errors are subclasses of joserfc.errors.JoseError. jwt.decode docstring lists BadSignatureError and InvalidPayloadError as documented raises. All other error variants (ExpiredTokenError, MissingClaimError, etc.) also extend JoseError.
  implication: catching joserfc.errors.JoseError is sufficient and correct for all legitimate JWT failures

- timestamp: 2026-03-15
  checked: did.py:69, agent_identity.py:66/129/149, security/circuit_breaker.py:21
  found: did.py re-raises (except Exception as e: logger.error(...); raise) — not swallowing. agent_identity.py catches are not JWT-related. circuit_breaker.py is unrelated.
  implication: only ucan.py:71 needs fixing for CRITICAL-3.3

## Resolution

root_cause: `except Exception as e` on ucan.py line 71 catches all exceptions from joserfc jwt.decode and the .claims attribute access, converting programmer errors (AttributeError, TypeError) to UCANVerificationError and masking real bugs
fix: replace `except Exception as e` with `except JoseError as e` on ucan.py:72; import joserfc.errors.JoseError at top of module
verification: 18/18 tests pass (test_ucan.py x8, test_ucan_acl_integration.py x7, test_ucan_ttls.py x3); reproduction test now correctly expects TypeError to propagate and passes
files_changed:
  - src/orchestra/identity/ucan.py (line 17: new import; line 72: narrowed except clause)
  - tests/unit/test_ucan.py (3 new tests added: legitimate_errors_caught, bad_signature_caught, programmer_errors_propagate)
