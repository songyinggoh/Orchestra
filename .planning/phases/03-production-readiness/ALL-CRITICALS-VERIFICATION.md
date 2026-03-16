# All-Criticals Verification Report

**Date:** 2026-03-16
**Scope:** 14 critical issues from CODE_REVIEW_REPORT.md / CRITICAL_FIXES.md
**Method:** Direct source file inspection — no SUMMARY trust, no claim trust

---

## Summary Table

| # | Issue | File | Status | Evidence |
|---|-------|------|--------|----------|
| 1 | CRITICAL-4.4 — Dynamic import RCE | `memory/serialization.py` | **FIXED** | Registry at line 25–36; `importlib` not used in deserializer |
| 2 | CRITICAL-4.5 — Mutable allowlist | `core/dynamic.py` | **FIXED** | `DEFAULT_ALLOWED_PREFIXES: tuple[str, ...]` at line 25; instance stored as tuple at line 41–43 |
| 3 | CRITICAL-3.4 — UCAN narrowing not enforced | `security/acl.py` | **FIXED** | `validate_narrowing()` at lines 18–82; `_validate_proof_chain()` called at line 199 in `is_authorized()` |
| 4 | CRITICAL-4.3 — Revocation never checked | `identity/agent_identity.py` | **FIXED** | Revocation gate in `verify_jws()` (line 183), `verify_raw()` (line 221), and `AgentIdentityValidator.validate_with_revocation()` (line 315); also wired into `ToolACL.is_authorized()` at acl.py line 148–151 |
| 5 | CRITICAL-4.2 — No key rotation | `messaging/secure_provider.py` | **FIXED** | `rotate_keys()` method at line 318; `_rotate_keys_if_needed()` called on every `encrypt_for()` at line 238; `_key_history` maintained for backward decryption |
| 6 | CRITICAL-3.3 — Broad UCAN exception | `identity/ucan.py` | **FIXED** | `except JoseError` at line 72 (not bare `except Exception`); JoseError imported from joserfc |
| 7 | CRITICAL-2.2 — TieredMemory race condition | `memory/tiers.py` | **FIXED** | `_policy_lock = asyncio.Lock()` at line 163; all `_policy._hot` / `_policy._warm` accesses wrapped in `async with self._policy_lock` |
| 8 | CRITICAL-3.1 — Context mutation not atomic | `core/context.py` | **FIXED** | `_lock: asyncio.Lock` field at lines 70–75; `mutate()` async context manager at lines 104–120 |
| 9 | CRITICAL-3.2 — Daemon thread not joined | `tools/wasm_runtime.py` | **PARTIAL** | `shutdown()` method with `join()` at line 206–220; `_ticker_stop` Event used; BUT thread is still `daemon=True` (line 232), not `daemon=False` as prescribed — shutdown must be called explicitly, automatic join on process exit is not guaranteed for daemon threads |
| 10 | CRITICAL-1.1 — Exception suppression in background task | `memory/tiers.py` | **FIXED** | `_log_task_exception` done-callback at lines 25–35; attached via `add_done_callback` at line 174; `stop()` catches non-CancelledError at lines 188–193 |
| 11 | CRITICAL-2.1 — Conservative failover default | `providers/failover.py` | **FIXED** | Line 62: `return ErrorCategory.TERMINAL` as default (not RETRYABLE); comment explicitly states "Unknown errors should surface" |
| 12 | CRITICAL-1.2 — Broad except in compiled.py | `core/compiled.py` | **FIXED** | Line 266: `except (ImportError, OSError, sqlite3.Error) as e` — no bare `except Exception`; system-level exceptions propagate |
| 13 | CRITICAL-1.3 — Max iterations loses partial output | `core/agent.py` | **FIXED** | `partial_result` built at lines 245–255; `emit_partial_on_max_iterations` param at line 65; `MaxIterationsError` carries `partial_output=partial_result` at line 269 |
| 14 | CRITICAL-4.1 — WAL+PRAGMA init race | `cost/persistent_budget.py` | **FIXED** | `_init_lock = asyncio.Lock()` at line 72; `initialize()` wraps all init under `async with self._init_lock` at lines 76–79; `_do_initialize()` guarded by checked `_initialized` flag |

**Score: 13/14 FIXED, 1/14 PARTIAL**

---

## Per-Issue Detail

### CRITICAL-4.4 — Dynamic Import RCE via Deserialization

**File:** `src/orchestra/memory/serialization.py`
**Status: FIXED**

The fix is substantive and correct. Lines 21–36 define a static `SERIALIZATION_REGISTRY` dict keyed by fully-qualified class name (`"{module}.{classname}"`). The `_object_hook` decoder at lines 63–101 looks up the class via `SERIALIZATION_REGISTRY.get(lookup_key)` (line 79) and returns the raw dict on a registry miss (line 89) — it never calls `importlib.import_module`. The comment at line 22 explicitly documents the CRITICAL-4.4 fix.

```
# Line 79 — verified:
cls = SERIALIZATION_REGISTRY.get(lookup_key)
```

No `importlib` call exists in the deserialization path.

---

### CRITICAL-4.5 — Mutable Allowlist at Runtime

**File:** `src/orchestra/core/dynamic.py`
**Status: FIXED**

`DEFAULT_ALLOWED_PREFIXES` is declared as `tuple[str, ...]` at line 25 (not a list, not a `pydantic.*` prefix). The `SubgraphBuilder.__init__` stores the caller-supplied prefixes — or the default — as a tuple using `tuple(allowed_prefixes)` at line 42. There is no `.append()` or `.extend()` method on a tuple. No `pydantic.*` prefix appears in the default.

```python
# Lines 25–29 — verified:
DEFAULT_ALLOWED_PREFIXES: tuple[str, ...] = (
    "orchestra.core.",
    "orchestra.tools.",
    "orchestra.providers.",
)
```

```python
# Lines 41–43 — verified (instance also immutable):
self._allowed_prefixes: tuple[str, ...] = (
    tuple(allowed_prefixes) if allowed_prefixes else DEFAULT_ALLOWED_PREFIXES
)
```

Note: `importlib.import_module` is still used at line 56 in `resolve_ref()`, which is correct and expected — this is the safe side (after allowlist check) for resolving refs from YAML graphs, not deserialization.

---

### CRITICAL-3.4 — UCAN Capability Narrowing Not Enforced

**File:** `src/orchestra/security/acl.py`
**Status: FIXED**

`validate_narrowing()` is implemented at lines 18–82 with proper four-case resource matching (exact, explicit tools wildcard, namespace wildcard, child-of-namespace). `ToolACL.is_authorized()` calls `_validate_proof_chain(ucan)` at line 199 when `ucan.proofs` is non-empty. `_validate_proof_chain()` (lines 203–237) iterates over the full delegation chain and calls `validate_narrowing()` on each adjacent parent–child pair, raising `CapabilityDeniedError` on any widening.

Step 5 of `is_authorized()` also enforces that a bare parent scope (`"orchestra:tools"`) no longer implicitly grants child resources — only `"orchestra:tools/{tool_name}"` (exact) or `"orchestra:tools/*"` (explicit wildcard) are accepted (lines 180–189).

---

### CRITICAL-4.3 — Agent Card Revocation Never Checked

**File:** `src/orchestra/identity/agent_identity.py` and `src/orchestra/security/acl.py`
**Status: FIXED**

Revocation is checked in three places:

1. `AgentCard.verify_jws()` — revocation gate before crypto, line 183.
2. `AgentCard.verify_raw()` — revocation gate before crypto, line 221.
3. `AgentIdentityValidator.validate_with_revocation()` — centralised validator that checks `self._revocation_list.is_revoked()` before calling either verify path, line 315.
4. `ToolACL.is_authorized()` — accepts optional `agent_did` and `revocation_list` params and checks at lines 148–151 before any ACL or UCAN rule, raising `AgentRevokedException` (not returning False) so callers can distinguish denied vs revoked.

The `RevocationList` class (lines 25–64) provides `revoke()`, `unrevoke()`, `is_revoked()` with in-memory `set` storage.

---

### CRITICAL-4.2 — No Key Rotation for DIDComm E2EE

**File:** `src/orchestra/messaging/secure_provider.py`
**Status: FIXED**

Key rotation is implemented with two code paths:

1. **Automatic interval-based:** `_rotate_keys_if_needed()` (lines 372–430) is called on every `encrypt_for()` call (line 238). Uses `time.monotonic()` for elapsed-time comparison. Generates new X25519 keypair + new did:peer:2 DID, increments `version`, archives old key in `_key_history`.
2. **Explicit on-demand:** `rotate_keys()` method (lines 318–366) for callers who want manual control.

Old key material is archived in `self._key_history` so in-flight messages encrypted before the rotation boundary can still be decrypted. The `kid` field in the JWE header (line 254) carries the wall-clock key version for audit purposes.

`AgentKeyMaterial` dataclass (lines 56–87) has `version: int`, `created_at: float`, `rotated_at: float | None`, and `needs_rotation()` method.

---

### CRITICAL-3.3 — Broad Exception in UCAN Verification

**File:** `src/orchestra/identity/ucan.py`
**Status: FIXED**

`UCANManager.verify()` at line 69 now catches `JoseError` (imported at line 17 from `joserfc.errors`) instead of bare `except Exception`. The `from e` chaining at line 73 preserves the exception cause. Standard time/field checks follow outside the try block. No broad exception catch remains in the critical verification path.

```python
# Lines 69–73 — verified:
try:
    decoded = jwt.decode(token_str, verification_key, algorithms=["EdDSA"])
    payload = decoded.claims
except JoseError as e:
    raise UCANVerificationError(f"JWT verification failed: {str(e)}") from e
```

---

### CRITICAL-2.2 — Race Condition in Tiered Memory

**File:** `src/orchestra/memory/tiers.py`
**Status: FIXED**

`_policy_lock = asyncio.Lock()` is created in `__init__` at line 163. All policy mutations and reads of `_policy._hot` and `_policy._warm` are protected:

- `store()`: acquires lock around `_policy.insert()` at line 199–200.
- `retrieve()`: acquires lock for HOT check (lines 219–225) then separately for WARM check (lines 234–240); value is captured inside the lock, I/O happens outside.
- Cold tier promotions: acquire lock around `_policy._hot[key] = entry` at lines 252–255 and 264–267.
- `demote()` cold path: acquires lock around `_policy.remove(key)` at line 297.
- `stats()`: acquires lock to snapshot counts at lines 320–322.

The sentinel `_MISS` object (line 22) correctly distinguishes "not found" from a stored `None` value, eliminating the check-then-use race.

---

### CRITICAL-3.1 — Context Mutation Without Atomic Guarantees

**File:** `src/orchestra/core/context.py`
**Status: FIXED**

`ExecutionContext` has a `_lock: asyncio.Lock` field (lines 70–75) with `init=False, repr=False, compare=False` so it is invisible to Pydantic / dataclass machinery and requires no caller changes. The `mutate()` async context manager (lines 104–120) acquires the lock and yields, serialising concurrent writes to `state`, `loop_counters`, `node_execution_order`, and `turn_number`.

The docstring at lines 27–41 explicitly documents the thread-safety contract and shows usage.

---

### CRITICAL-3.2 — Daemon Thread Not Joined on Shutdown

**File:** `src/orchestra/tools/wasm_runtime.py`
**Status: PARTIAL**

**What is fixed:**
- `shutdown()` method exists at lines 206–220 with `_ticker_stop.set()` and `_ticker_thread.join(timeout=...)`.
- `_ticker_stop = threading.Event()` is used; the loop condition `while not self._ticker_stop.wait(self._epoch_interval)` at line 228 exits immediately when `_ticker_stop` is set, so the thread terminates promptly.
- Logging if the thread does not stop within the timeout.

**What is still not fully addressed:**
- The thread is still created with `daemon=True` at line 232. The prescribed fix in CRITICAL_FIXES.md required `daemon=False` to prevent the thread from dying silently — a daemon thread is not a substitute for a joined thread since the process will exit without waiting for it.
- There is no `__del__` method or async lifespan hook to guarantee `shutdown()` is called. The docstring at lines 207–213 acknowledges "omitting it is only a concern for long-lived processes," but the original issue required an unconditional join guarantee.

**Evidence:**
```python
# Line 232 — still daemon=True:
self._ticker_thread = threading.Thread(
    target=_ticker, daemon=True, name="wasm-epoch-ticker"
)
```

The `shutdown()` method is correct and callable, but relying on daemon=True means the thread can be abandoned if `shutdown()` is not called explicitly. The fix is PARTIAL: `shutdown()` works when called, but the daemon flag leaves the original risk open for callers who omit it.

---

### CRITICAL-1.1 — Exception Suppression in Background Task

**File:** `src/orchestra/memory/tiers.py`
**Status: FIXED**

Two layers of protection:

1. **Done-callback:** `_log_task_exception()` function at lines 25–35 is attached via `add_done_callback` at line 174 in `start()`. Any unhandled exception from the task is logged at ERROR level using `_stdlib_logger.exception()`.
2. **stop() catch:** Lines 188–193 catch non-CancelledError exceptions during `await self._scan_task` in `stop()` and log them with `_stdlib_logger.exception()`.

The `except asyncio.CancelledError: pass` at line 185 is correctly scoped to expected cancellation only.

---

### CRITICAL-2.1 — Conservative Default Hides Real Failover Errors

**File:** `src/orchestra/providers/failover.py`
**Status: FIXED**

Line 62 returns `ErrorCategory.TERMINAL` (not RETRYABLE) as the default for unknown errors. Comment confirms intent:

```python
# Line 62 — verified:
return ErrorCategory.TERMINAL  # Unknown errors should surface, not be silently swallowed by failover
```

The function structure correctly prioritises: explicit Orchestra error types first, then terminal keywords (auth, 401, 403), then model mismatch keywords, then retryable keywords, and finally defaults to TERMINAL. The `complete()` method raises immediately on TERMINAL (line 139) rather than continuing to the next provider.

---

### CRITICAL-1.2 — Broad Exception Catch in Checkpoint Restoration

**File:** `src/orchestra/core/compiled.py`
**Status: FIXED**

Line 266 (in the `resume()` method):
```python
except (ImportError, OSError, sqlite3.Error) as e:
    raise AgentError(f"Failed to auto-initialize event store for resume: {e}")
```

Only specific, expected exception types are caught. `SystemExit`, `KeyboardInterrupt`, `RuntimeError`, `AttributeError`, and other non-infrastructure errors propagate freely. The `from e` chain was dropped here (the raise wraps to AgentError without it), but that is a minor style point — the critical fix (no bare `except Exception`) is in place.

---

### CRITICAL-1.3 — Max Iterations Loses Partial Output

**File:** `src/orchestra/core/agent.py`
**Status: FIXED**

`BaseAgent.run()` now accepts an `emit_partial_on_max_iterations: bool = False` keyword argument (line 65). After the iteration loop:

- Lines 245–255: builds `partial_result = AgentResult(..., partial=True)` from all accumulated assistant messages and tool call records.
- Lines 257–264: if `emit_partial_on_max_iterations=True`, logs a warning and returns the partial result.
- Lines 266–271: otherwise raises `MaxIterationsError(..., partial_output=partial_result)` so callers who catch the exception can still access accumulated work.

Both paths preserve partial output — the original issue (raising with no output available) is fully resolved.

---

### CRITICAL-4.1 — WAL+PRAGMA Race Condition in Budget Store

**File:** `src/orchestra/cost/persistent_budget.py`
**Status: FIXED**

`PersistentBudgetStore.__init__` creates `self._init_lock = asyncio.Lock()` at line 72. `initialize()` at lines 75–79 acquires the lock before any database work and re-checks `_initialized` inside the lock (double-checked locking pattern). The actual setup is delegated to `_do_initialize()` which runs entirely under the lock. `_initialized = True` is set at line 130 only after all PRAGMAs and table creation have been committed.

```python
# Lines 75–79 — verified:
async def initialize(self) -> None:
    async with self._init_lock:
        if self._initialized:
            return
        await self._do_initialize()
```

The CRITICAL_FIXES.md noted that the load test confirmed the bug still existed. After reviewing the code, the `asyncio.Lock()` guarding is correctly in place in the current source. The load test file (`load_tests/locustfile.py`) is a generic Locust HTTP test for the API server and does not directly exercise concurrent `PersistentBudgetStore.initialize()` — it does not confirm or deny the code fix.

---

## Overall Verdict

**13 of 14 critical issues are FIXED.**

### Remaining NOT FIXED / PARTIAL

| Issue | Status | What Remains |
|-------|--------|--------------|
| CRITICAL-3.2 | PARTIAL | Thread is still `daemon=True` (wasm_runtime.py:232). `shutdown()` exists and works when called, but the daemon flag means the thread can be abandoned silently if the caller omits `shutdown()`. Fix requires either changing to `daemon=False` or adding a `__del__`/atexit guarantee. |

### Confirmed FIXED (all 13)

- CRITICAL-4.4: Class registry, no importlib in deserializer
- CRITICAL-4.5: Immutable tuple allowlist, no pydantic prefix
- CRITICAL-3.4: `validate_narrowing()` + `_validate_proof_chain()` in `is_authorized()`
- CRITICAL-4.3: Revocation gate in verify_jws, verify_raw, AgentIdentityValidator, ToolACL
- CRITICAL-4.2: `rotate_keys()` + `_rotate_keys_if_needed()` + `_key_history`
- CRITICAL-3.3: `except JoseError` (not bare Exception), with cause chaining
- CRITICAL-2.2: `_policy_lock` around all `_policy._hot`/`_policy._warm` accesses
- CRITICAL-3.1: `_lock: asyncio.Lock` + `mutate()` context manager on ExecutionContext
- CRITICAL-1.1: `_log_task_exception` done-callback + `stop()` non-CancelledError catch
- CRITICAL-2.1: `return ErrorCategory.TERMINAL` as unknown-error default
- CRITICAL-1.2: `except (ImportError, OSError, sqlite3.Error)` — no bare except
- CRITICAL-1.3: `partial_result` built after loop; `emit_partial_on_max_iterations` param; `MaxIterationsError.partial_output`
- CRITICAL-4.1: `_init_lock = asyncio.Lock()` + double-checked `_initialized` flag

---

## Recommendation

**Merge-ready** for 13/14 issues. One remaining action:

1. **CRITICAL-3.2 (wasm_runtime.py line 232):** Change `daemon=True` to `daemon=False` and add a `__del__` or atexit handler calling `shutdown()`. This is a 5-line change. Until then, any process that creates a `WasmToolSandbox` without calling `shutdown()` may leave the epoch-ticker thread running past event-loop teardown.

---

_Verified: 2026-03-16_
_Verifier: Claude (gsd-verifier)_
