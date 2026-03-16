# CRITICAL-3.1 Verification Report — Context Mutation Without Atomic Guarantees

**Verdict: PASS**
**Date:** 2026-03-16
**Issue:** Race condition in `CapabilityAttenuator.process_risk_score()` — check-then-act pattern with no synchronization could emit duplicate security events.

---

## Summary

The fix is complete. The mutation of `context.restricted_mode` is now safe against duplicate event emission. The guard layer (`PromptShieldGuard.pre_execute_scan`) captures state before any mutation and gates event emission on a first-transition check. All three required tests exist and pass.

---

## Fix Analysis

### How the original problem was resolved

The fix uses approach **(a)**: capture state before mutation, gate event emission on the first-transition.

The fix lives in `src/orchestra/security/guard.py` — **not** in `attenuation.py`. The `CapabilityAttenuator.process_risk_score()` itself is still a bare check-then-set (lines 28-31 of `attenuation.py`), but the race condition for duplicate events is neutralised one layer up in `PromptShieldGuard.pre_execute_scan()`.

**`src/orchestra/security/guard.py`, lines 54-79:**

```
54:    was_restricted = context.restricted_mode          # Snapshot BEFORE any mutation
55:
56:    # Score-based attenuation (sync, no await — atomic in asyncio cooperative model).
57:    self._attenuator.process_risk_score(context, detection.model_score)
58:
59:    if detection.injection_detected:
60:        # Rebuff's combined 'injection_detected' is a hard block regardless of score.
61:        logger.warning("injection_blocked_pre_execute", run_id=context.run_id)
62:        context.restricted_mode = True
63:
64:    # Emit an audit event when restricted_mode is *newly* entered so the
65:    # security state transition is visible to the event log and replay.
66:    if not was_restricted and context.restricted_mode and context.event_bus is not None:
67:        from orchestra.storage.events import SecurityViolation
68:        await context.event_bus.emit(
69:            SecurityViolation(
70:                run_id=context.run_id,
71:                node_id=context.node_id,
72:                violation_type="restricted_mode_entered",
73:                details={
74:                    "risk_score": detection.model_score,
75:                    "injection_detected": detection.injection_detected,
76:                    "trigger": "injection_detected" if detection.injection_detected else "risk_score",
77:                },
78:            )
79:        )
```

**Why this is safe:**

- Line 54 captures `was_restricted` as a boolean snapshot before either mutation path runs.
- Line 66 gates the `event_bus.emit` on `not was_restricted and context.restricted_mode` — this is the first-transition predicate. If the context was already restricted on entry, `was_restricted` is `True` and the event is never emitted.
- Within asyncio's cooperative multitasking model, the synchronous read-modify-write sequence (lines 54-62) cannot be interleaved by another coroutine because there is no `await` between the snapshot and the mutations. The comment on line 56 documents this design intent explicitly.
- The `await` only occurs at line 68 (after both mutations have completed and the transition has been determined), so concurrent callers cannot both observe `was_restricted == False` and both emit.

### Remaining note on `attenuation.py`

`CapabilityAttenuator.process_risk_score()` (lines 28-31) does a bare check-then-set without event emission. This is acceptable because:
1. The only event emission path is in `guard.py`, which applies the snapshot guard.
2. `process_risk_score` is a pure state mutation helper — the caller owns the emission decision.

If `process_risk_score` were ever called from a second call site that also emits events without the snapshot guard, the race would re-emerge. There is currently only one call site (`guard.py:57`).

---

## Required Tests — Status

| Test | Location | Status |
|------|----------|--------|
| `test_restricted_mode_entered_emits_security_event` | `tests/unit/test_injection_attenuation.py:102` | PASS |
| `test_restricted_mode_event_not_duplicated` | `tests/unit/test_injection_attenuation.py:129` | PASS |
| `test_no_event_emitted_without_event_bus` | `tests/unit/test_injection_attenuation.py:153` | PASS |

All 7 tests in the file pass:

```
tests/unit/test_injection_attenuation.py::test_guard_safe_input                         PASSED
tests/unit/test_injection_attenuation.py::test_guard_attenuation_on_risk                PASSED
tests/unit/test_injection_attenuation.py::test_guard_post_execute_redaction             PASSED
tests/unit/test_injection_attenuation.py::test_guard_post_execute_no_redaction_normal_mode PASSED
tests/unit/test_injection_attenuation.py::test_restricted_mode_entered_emits_security_event PASSED
tests/unit/test_injection_attenuation.py::test_restricted_mode_event_not_duplicated     PASSED
tests/unit/test_injection_attenuation.py::test_no_event_emitted_without_event_bus       PASSED

7 passed in 0.97s
```

---

## Test Coverage for Each Required Behavior

### 1. Event emitted on first entry (`test_restricted_mode_entered_emits_security_event`)

- Sets up an `EventBus` subscriber that captures `SecurityViolation` events.
- Calls `pre_execute_scan` with `injection_detected=True`, `model_score=0.95`.
- Asserts `len(emitted) == 1` and `emitted[0].violation_type == "restricted_mode_entered"`.
- PASS — confirms the transition event fires exactly once on entry.

### 2. No duplicate event when already restricted (`test_restricted_mode_event_not_duplicated`)

- Sets `context.restricted_mode = True` before calling `pre_execute_scan`.
- Calls with another high-score injection attempt.
- Asserts `len(emitted) == 0`.
- PASS — confirms the `was_restricted` snapshot correctly suppresses a second event.

### 3. No crash without event bus (`test_no_event_emitted_without_event_bus`)

- Uses a bare `ExecutionContext` with no `event_bus` attached (`context.event_bus is None`).
- Calls `pre_execute_scan` with a high-score attack.
- Asserts no exception is raised and `context.restricted_mode is True`.
- PASS — the `context.event_bus is not None` guard at line 66 prevents a `NoneType` `AttributeError`.

---

## Gaps Found

None. The fix addresses both the duplicate-event race and the None-bus crash path. All required tests are present and passing.

---

_Verifier: Claude (gsd-verifier) — 2026-03-16_
