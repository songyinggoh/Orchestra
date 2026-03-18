---
phase: 03-production-readiness
scope: Week 2 concurrency critical issues (CRITICAL-2.2, CRITICAL-3.1, CRITICAL-3.2)
verified: 2026-03-15T00:00:00Z
status: passed
score: 3/3 issues fully fixed and tested
overall: GREEN
---

# Week 2 Concurrency Safety — Verification Report

**Verified:** 2026-03-15
**Scope:** CRITICAL-2.2, CRITICAL-3.1, CRITICAL-3.2 from REVIEW_SUMMARY.md action plan
**Overall Status: GREEN — All three issues are fixed, tested, and passing**

---

## Issue Verdicts at a Glance

| Issue | Description | Verdict | Tests Passing |
|-------|-------------|---------|---------------|
| CRITICAL-2.2 | Race condition in tiered memory | PASS | 3/3 concurrent tests |
| CRITICAL-3.1 | Context mutation without atomic guarantees | PASS | 2/2 targeted tests |
| CRITICAL-3.2 | Daemon thread outlives event loop | PASS | 2/2 targeted tests |

---

## CRITICAL-2.2: Race Condition in Tiered Memory

**File:** `src/orchestra/memory/tiers.py`
**Status: PASS**

### Fix Verification

Every access to `_policy._hot` and `_policy._warm` is guarded by `_policy_lock` (`asyncio.Lock`).
No I/O (`await`) occurs while the lock is held — the pattern is: acquire lock, capture value, release, then do I/O.

Confirmed lock coverage at each access site:

| Location | Line(s) | Protected |
|----------|---------|-----------|
| `store()` — `_policy.insert()` call | 199–200 | `async with self._policy_lock` |
| `retrieve()` — HOT tier check and value capture | 219–225 | `async with self._policy_lock` |
| `retrieve()` — WARM tier check and value capture | 234–240 | `async with self._policy_lock` |
| `retrieve()` — warm-backend promote into `_hot` | 252–255 | `async with self._policy_lock` |
| `retrieve()` — cold-backend promote into `_hot` | 264–267 | `async with self._policy_lock` |
| `demote()` — `_policy.remove()` call | 297–298 | `async with self._policy_lock` |
| `stats()` — `len(_hot)` / `len(_warm)` reads | 320–322 | `async with self._policy_lock` |

The `_policy_lock` is initialised in `__init__` at line 163. `SLRUPolicy` methods (`access`, `insert`, `evictions_due`, `remove`) are synchronous pure-Python with no yield points, so no interleaving is possible while the lock is held.

### Test Results

Three concurrent-access tests were added to `tests/unit/test_tiered_memory.py` (lines 217–316):

- `test_concurrent_retrieve_no_corruption` — 50 concurrent `retrieve()` calls on the same key; all must return the correct value without `KeyError`. **PASSED**
- `test_concurrent_store_and_retrieve` — interleaved `store()` and `retrieve()` with small tier limits to maximise eviction churn; no `KeyError` allowed. **PASSED**
- `test_promotion_under_concurrent_load` — 60 concurrent retrieves promoting across WARM→HOT with `hot_max=3` forcing constant HOT→WARM demotions; no exceptions, correct values, tier counts within bounds. **PASSED**

**Full `test_tiered_memory.py` suite: 13/13 passed. `test_memory_tiers_full.py`: 4/4 passed.**

### Evidence (line numbers in `tiers.py`)

```
Line 163:  self._policy_lock = asyncio.Lock()
Line 199:  async with self._policy_lock:
Line 219:  async with self._policy_lock:
Line 234:  async with self._policy_lock:
Line 252:  async with self._policy_lock:
Line 264:  async with self._policy_lock:
Line 297:  async with self._policy_lock:
Line 320:  async with self._policy_lock:
```

Debug resolution doc: `.planning/debug/resolved/critical-2-2-tiered-memory-race.md` — status `resolved`, confirms the same audit findings.

---

## CRITICAL-3.1: Context Mutation Without Atomic Guarantees

**Files:** `src/orchestra/security/attenuation.py`, `src/orchestra/security/guard.py`
**Status: PASS**

### Fix Verification

The fix required that `was_restricted` be captured before any mutation, that `SecurityViolation` be emitted only on the first `False -> True` transition, and that no duplicate events be emitted.

**`guard.py` — `pre_execute_scan()` (lines 42–81):**

1. `was_restricted = context.restricted_mode` is captured at line 54 — before any mutation. This is the snapshot that determines whether a transition occurred.
2. `self._attenuator.process_risk_score(context, detection.model_score)` runs at line 57. This is synchronous (no `await`), so it cannot yield to another coroutine — atomic in asyncio's cooperative scheduling model.
3. `context.restricted_mode = True` may be set again at line 62 (if `injection_detected`).
4. Event emission at lines 66–79 is gated on `not was_restricted and context.restricted_mode` — exactly the first-transition check required.
5. `context.event_bus` null-guard at line 66 prevents crash when no bus is attached.

**`attenuation.py` — `process_risk_score()` (lines 26–31):**

The method already applies a second transition guard: `if not context.restricted_mode:` before setting it (line 29). This means even if called repeatedly, `restricted_mode` is only set once and the log message only fires once.

There is no check-then-act race here for asyncio purposes: `process_risk_score` contains no `await`, so it cannot be interleaved with itself between the check at line 29 and the assignment at line 31.

### Test Results

Tests in `tests/unit/test_injection_attenuation.py`:

- `test_restricted_mode_entered_emits_security_event` — verifies that entering restricted mode emits exactly one `SecurityViolation` event with `violation_type == "restricted_mode_entered"` and `injection_detected == True`. **PASSED**
- `test_restricted_mode_event_not_duplicated` — starts with `context.restricted_mode = True` already set; verifies that a subsequent injection detection emits zero events (no duplicate). **PASSED**
- `test_no_event_emitted_without_event_bus` — verifies the guard does not crash when `context.event_bus is None`. **PASSED**

**Full `test_injection_attenuation.py` suite: 7/7 passed.**

### Evidence (line numbers in `guard.py`)

```
Line 54:  was_restricted = context.restricted_mode        # snapshot before mutation
Line 57:  self._attenuator.process_risk_score(...)         # synchronous — no yield point
Line 62:  context.restricted_mode = True                   # may set again (idempotent)
Line 66:  if not was_restricted and context.restricted_mode and context.event_bus is not None:
Line 68:      await context.event_bus.emit(SecurityViolation(...))
```

---

## CRITICAL-3.2: Daemon Thread Outlives Event Loop (WasmToolSandbox)

**File:** `src/orchestra/tools/wasm_runtime.py`
**Status: PASS**

### Fix Verification

`shutdown()` exists at line 206 and implements all required behaviours:

1. `self._ticker_stop.set()` at line 215 — signals the ticker thread to stop on its next `wait()` call.
2. `self._ticker_thread.is_alive()` guard at line 216 — prevents a `join()` on a thread that never started or already exited.
3. `self._ticker_thread.join(timeout=self._epoch_interval * 2 + 1)` at line 217 — waits for the thread with a finite timeout (default: `1.0 * 2 + 1 = 3.0s`).
4. Post-join `is_alive()` check at line 218 with a `log.warning("wasm_epoch_ticker_did_not_stop_cleanly")` — logs if the thread did not stop within the timeout.
5. `log.debug("wasm_epoch_ticker_stopped")` at line 220 — always logged on clean exit.

The ticker thread itself uses `threading.Event.wait(timeout)` at line 228 rather than `time.sleep()`. This means `_ticker_stop.set()` causes the `wait()` to return immediately, so the thread exits at the end of its current iteration without sleeping the full interval. Clean, prompt exit.

The thread is started as `daemon=True` (line 232), which means if `shutdown()` is not called the process exit kills it automatically — no zombie threads.

`shutdown()` is safe to call multiple times: on the second call `_ticker_stop` is already set (no-op), and `_ticker_thread.is_alive()` returns `False` so the `join()` is skipped entirely.

### Test Results

Tests in `tests/unit/test_wasm_sandbox.py`:

- `test_shutdown_stops_ticker_thread` (line 154) — creates a `WasmToolSandbox` with `epoch_interval=0.05`, verifies thread is alive, calls `shutdown()`, asserts `not s._ticker_thread.is_alive()`. **PASSED**
- `test_shutdown_is_idempotent` (line 166) — calls `shutdown()` twice without error. **PASSED**

**Full `test_wasm_sandbox.py` suite: 11/11 passed** (includes epoch timeout, fuel exceeded, memory limit, and other execution tests — no regressions).

### Evidence (line numbers in `wasm_runtime.py`)

```
Line 64:   self._ticker_stop = threading.Event()
Line 206:  def shutdown(self) -> None:
Line 215:      self._ticker_stop.set()
Line 216:      if self._ticker_thread is not None and self._ticker_thread.is_alive():
Line 217:          self._ticker_thread.join(timeout=self._epoch_interval * 2 + 1)
Line 218:          if self._ticker_thread.is_alive():
Line 219:              log.warning("wasm_epoch_ticker_did_not_stop_cleanly")
Line 220:  log.debug("wasm_epoch_ticker_stopped")
Line 228:      while not self._ticker_stop.wait(self._epoch_interval):
```

---

## Full Test Run Summary

```
Command: pytest tests/unit/test_tiered_memory.py tests/unit/test_memory_tiers_full.py
         tests/unit/test_injection_attenuation.py tests/unit/test_wasm_sandbox.py -v

Result:  35 passed in 1.79s
```

No failures. No skips. No warnings. Zero regressions across all 35 tests spanning the three affected modules.

---

## Targeted Test Run (Issue-Specific)

| Test | Issue | Result |
|------|-------|--------|
| `test_concurrent_retrieve_no_corruption` | CRITICAL-2.2 | PASSED |
| `test_concurrent_store_and_retrieve` | CRITICAL-2.2 | PASSED |
| `test_promotion_under_concurrent_load` | CRITICAL-2.2 | PASSED |
| `test_restricted_mode_entered_emits_security_event` | CRITICAL-3.1 | PASSED |
| `test_restricted_mode_event_not_duplicated` | CRITICAL-3.1 | PASSED |
| `test_shutdown_stops_ticker_thread` | CRITICAL-3.2 | PASSED |
| `test_shutdown_is_idempotent` | CRITICAL-3.2 | PASSED |

**7/7 targeted tests passing.**

---

## Gaps and Remaining Concerns

### No Gaps — All Three Issues Fully Resolved

**CRITICAL-2.2:** Implementation is correct and comprehensively tested. The debug resolution doc at `.planning/debug/resolved/critical-2-2-tiered-memory-race.md` is accurate and matches the code.

**CRITICAL-3.1:** The `was_restricted` snapshot pattern and single-transition event guard are correctly implemented. No separate debug resolution doc exists for this issue, but the fix is present and tested in `guard.py`.

**CRITICAL-3.2:** `shutdown()` is fully implemented with signal, join, timeout, and warning log. No separate debug resolution doc exists for this issue, but the fix is present and tested.

### Minor Observation (Not a Blocker)

The `_policy_lock` in `TieredMemoryManager` is an `asyncio.Lock`, which means it is not safe for use from OS threads. This is correct and intentional — all callers are `async def` coroutines running in the asyncio event loop. However, if the `_background_scan` task were ever replaced with a thread-based scanner, this would need to change. This is a documentation note, not a current defect.

### Debug Docs Not Present for CRITICAL-3.1 and CRITICAL-3.2

The `.planning/debug/resolved/` directory contains a resolution doc for CRITICAL-2.2 but not for CRITICAL-3.1 or CRITICAL-3.2. This is a documentation gap only — the fixes are present in code and verified by tests. Consider adding resolution docs for completeness if the debug trail needs to be complete.

---

## Conclusion

**Overall Status: GREEN**

All three Week 2 concurrency critical issues are fixed in the production codebase and covered by passing tests:

- CRITICAL-2.2: `asyncio.Lock` correctly guards all `_policy._hot`/`_policy._warm` accesses; 3 concurrent stress tests confirm no race under load.
- CRITICAL-3.1: `was_restricted` snapshot + single-transition guard prevents duplicate `SecurityViolation` events; 2 targeted tests confirm the first-transition-only behaviour.
- CRITICAL-3.2: `shutdown()` correctly signals the ticker event, joins with timeout, and logs if the thread fails to stop; 2 targeted tests confirm clean shutdown and idempotency.

The codebase is safe to proceed with Week 3 (error handling and data integrity) remediation.

---

_Verified: 2026-03-15_
_Verifier: Claude (gsd-verifier)_
_Test environment: Python 3.13.5 / pytest 9.0.2 / Windows 11_
