# Critical Issues Re-Verification Report

**Date:** 2026-03-15
**Branch:** phase3-production-readiness
**Verifier:** Manual source inspection (no test execution)

---

## Summary Table

| #    | Issue                                        | File(s) Inspected                               | Status      |
|------|----------------------------------------------|-------------------------------------------------|-------------|
| 1.1  | Bare exception suppression in background task| `memory/tiers.py`                               | FIXED       |
| 1.2  | Broad exception catch at checkpoint restore  | `core/compiled.py` ~line 266                    | FIXED       |
| 1.3  | Lost partial output on max iterations        | `core/agent.py`                                 | FIXED       |
| 2.1  | Conservative default hides failover errors   | `providers/failover.py`                         | FIXED       |
| 2.2  | Race condition in tiered memory              | `memory/tiers.py`                               | FIXED       |
| 3.1  | Context mutation without atomic guarantees   | `core/context.py`                               | STILL OPEN  |
| 3.2  | Daemon thread outlives event loop            | `tools/wasm_runtime.py`                         | PARTIAL     |
| 3.3  | Broad exception in UCAN verification         | `identity/ucan.py`                              | FIXED       |
| 3.4  | UCAN capability narrowing not enforced       | `security/acl.py`, `identity/ucan.py`           | FIXED       |
| 4.1  | WAL + PRAGMA race in budget store            | `cost/persistent_budget.py`                     | FIXED       |
| 4.2  | No key rotation in SecureNatsProvider        | `messaging/secure_provider.py`                  | FIXED       |
| 4.3  | Agent card revocation never checked          | `identity/agent_identity.py`, `security/acl.py` | FIXED       |
| 4.4  | Dynamic import RCE via deserialization       | `tools/wasm_runtime.py`, `tools/registry.py`    | FIXED       |
| 4.5  | Mutable allowlist at runtime                 | `security/acl.py`                               | STILL OPEN  |

**Totals: 11 FIXED, 1 PARTIAL, 2 STILL OPEN**

---

## Detailed Findings

---

### CRITICAL-1.1 -- Bare Exception Suppression in Background Task

**File:** `src/orchestra/memory/tiers.py`
**Status: FIXED**

A module-level `_log_task_exception` done-callback (lines 25-35) is registered on the scan task
in `start()` (line 174) via `self._scan_task.add_done_callback(_log_task_exception)`. The callback
logs any unhandled exception via `_stdlib_logger.exception(...)`.

In `stop()` (lines 177-194), `asyncio.CancelledError` is explicitly caught with a comment
explaining it is expected (the caller requested cancellation), and a second `except Exception`
block logs any unexpected exception that escaped `_background_scan`. Both failure surfaces are
now covered.

---

### CRITICAL-1.2 -- Broad Exception Catch During Checkpoint Restoration

**File:** `src/orchestra/core/compiled.py` ~line 266
**Status: FIXED**

The catch is now narrowed to:

    except (ImportError, OSError, sqlite3.Error) as e:
        raise AgentError(f"Failed to auto-initialize event store for resume: {e}")

The original `except (ImportError, Exception)` that swallowed `SystemExit` and `KeyboardInterrupt`
is gone. Only the three expected filesystem/SQLite failure modes are caught.

---

### CRITICAL-1.3 -- Lost Partial Output on Max Iterations

**File:** `src/orchestra/core/agent.py`
**Status: FIXED**

After the iteration loop exhausts (lines 242-271), a `partial_result = AgentResult(..., partial=True)`
is built from all accumulated assistant messages and tool call records. Two code paths both
preserve output:

- `emit_partial_on_max_iterations=True`: returns the partial result directly.
- `emit_partial_on_max_iterations=False` (default): raises `MaxIterationsError` but sets
  `exc.partial_output = partial_result` so callers can inspect accumulated work.

No partial output is discarded in either path.

---

### CRITICAL-2.1 -- Conservative Default Hides Failover Errors

**File:** `src/orchestra/providers/failover.py`
**Status: FIXED**

`classify_error()` (lines 33-62) categorizes errors as TERMINAL, MODEL_MISMATCH, or RETRYABLE.
The final fallback is `return ErrorCategory.TERMINAL` with the comment
"Unknown errors should surface, not be silently swallowed by failover."

TERMINAL and MODEL_MISMATCH are re-raised immediately. Only RETRYABLE errors advance to the
next provider. Unknown errors now surface rather than being hidden.

---

### CRITICAL-2.2 -- Race Condition in Tiered Memory

**File:** `src/orchestra/memory/tiers.py`
**Status: FIXED**

`_policy_lock = asyncio.Lock()` (line 163) is acquired via `async with self._policy_lock:` before
every access to `self._policy._hot` or `self._policy._warm` across `store()`, `retrieve()`,
`demote()`, and `stats()`. I/O operations (Redis/pgvector calls) occur outside the lock. The
pattern is correct: hold lock only for in-memory mutations, release before awaiting I/O.

---

### CRITICAL-3.1 -- Context Mutation Without Atomic Guarantees

**File:** `src/orchestra/core/context.py`
**Status: STILL OPEN**

`ExecutionContext` is a plain `@dataclass` with no lock, no `asyncio.Lock`, no `threading.Lock`,
and no `asyncio.Event`. All fields are mutable. Problematic representative code:

    @dataclass
    class ExecutionContext:
        state: dict[str, Any] = field(default_factory=dict)
        loop_counters: dict[str, int] = field(default_factory=dict)
        node_execution_order: list[str] = field(default_factory=list)
        # ... no synchronization anywhere

Under concurrent access from parallel edges in `CompiledGraph`, mutations to `state`,
`loop_counters`, `node_execution_order`, and `turn_number` are not atomic. No fix has been applied.

---

### CRITICAL-3.2 -- Daemon Thread Outlives Event Loop

**File:** `src/orchestra/tools/wasm_runtime.py`
**Status: PARTIAL**

A `shutdown()` method (lines 206-220) now exists and correctly sets the stop event, then joins
the ticker thread. The ticker loop uses `threading.Event.wait()` so it exits promptly when
`shutdown()` is called.

However, `shutdown()` is not called automatically. There is no `__enter__`/`__exit__` context
manager, no `__del__`, and no lifecycle hook in `CompiledGraph` or elsewhere that ensures
`shutdown()` fires. If callers omit it, the thread lives until process exit. The risk is
mitigated (daemon threads do not block process exit) but clean shutdown is opt-in only.

---

### CRITICAL-3.3 -- Broad Exception in UCAN Verification

**File:** `src/orchestra/identity/ucan.py`
**Status: FIXED**

The import `from joserfc.errors import JoseError` (line 17) and the narrowed catch:

    except JoseError as e:
        raise UCANVerificationError(f"JWT verification failed: {str(e)}") from e

replaces the former `except Exception`. `AttributeError`, `TypeError`, and other programmer
errors now propagate normally instead of being silently hidden as verification failures.

---

### CRITICAL-3.4 -- UCAN Capability Narrowing Not Enforced

**Files:** `src/orchestra/security/acl.py`, `src/orchestra/identity/ucan.py`
**Status: FIXED**

In `acl.py` `is_authorized()` (lines 163-173):

    resource_match = (
        cap.resource == f"orchestra:tools/{tool_name}" or
        cap.resource == "orchestra:tools/*"
    )

A comment documents explicitly: "NOT allowed: bare orchestra:tools (implicit parent-scope passthrough)".

`ucan.py` `check_capability()` applies the same rule. `validate_narrowing()` in `acl.py` and
`_validate_proof_chain()` enforce DD-4 chain narrowing for delegated tokens.

---

### CRITICAL-4.1 -- WAL + PRAGMA Race in Budget Store

**File:** `src/orchestra/cost/persistent_budget.py`
**Status: FIXED**

`self._init_lock = asyncio.Lock()` (line 72) protects `initialize()`:

    async with self._init_lock:
        if self._initialized:
            return
        await self._do_initialize()

All PRAGMA statements and DDL run within a single connection context inside `_do_initialize()`,
and `self._initialized = True` is set only after `db.commit()`. No coroutine can begin a
transaction before the WAL PRAGMA has been committed.

---

### CRITICAL-4.2 -- No Key Rotation in SecureNatsProvider

**File:** `src/orchestra/messaging/secure_provider.py`
**Status: FIXED**

Full key rotation is implemented:

- `_rotate_keys_if_needed()` (lines 372-430): automatic interval-based rotation, called on every
  `encrypt_for()` invocation.
- `rotate_keys()` (lines 318-366): explicit unconditional rotation API.
- `AgentKeyMaterial` tracks `version` (incremented on rotation), `rotated_at` (wall-clock), and `kid`.
- Every JWE protected header includes `"kid": f"key-{int(self._key_wall_time)}"`.
- Old key material archived in `self._key_history` so in-flight messages remain decryptable.
- `key_rotation_interval=0` disables rotation for stable-DID test scenarios.

---

### CRITICAL-4.3 -- Agent Card Revocation Never Checked

**Files:** `src/orchestra/identity/agent_identity.py`, `src/orchestra/security/acl.py`
**Status: FIXED**

All three missing pieces are now present:

1. `RevocationList` class in `agent_identity.py` (lines 25-64): in-memory set with `revoke()`,
   `unrevoke()`, `is_revoked()`, `__contains__`.

2. `AgentRevokedException` in `errors.py` (lines 219-234): exception with `did` attribute.

3. `AgentCard.verify_jws()` and `verify_raw()` both accept `revocation_list` and raise
   `AgentRevokedException` before any crypto work.

4. `ToolACL.is_authorized()` Step 0 (lines 131-135):

       if agent_did is not None and revocation_list is not None:
           if revocation_list.is_revoked(agent_did):
               raise AgentRevokedException(agent_did)

5. `AgentIdentityValidator` centralizes the two-step pattern (revocation then crypto).

---

### CRITICAL-4.4 -- Dynamic Import RCE via Deserialization

**Files:** `src/orchestra/tools/wasm_runtime.py`, `src/orchestra/tools/registry.py`
**Status: FIXED**

`WasmToolSandbox.execute()` accepts `wasm_bytes: bytes` (compiled binary only). Bytes are
passed to `wasmtime.Module(self._engine, wasm_bytes)` inside the Wasmtime sandboxed runtime.
No user-supplied string is ever passed to `importlib.import_module` or `__import__`.

`ToolRegistry` is a dictionary keyed by tool name; all registrations occur via
`registry.register(tool_instance)` at startup by trusted code. There is no path from
deserialized data to a dynamic import.

---

### CRITICAL-4.5 -- Mutable Allowlist at Runtime

**File:** `src/orchestra/security/acl.py`
**Status: STILL OPEN**

`ToolACL` is `@dataclass(frozen=True)`, which prevents attribute reassignment. However,
`frozen=True` does NOT make contained collections immutable. The fields remain:

    allowed_tools: set[str] = field(default_factory=set)
    denied_tools: set[str] = field(default_factory=set)
    allow_patterns: list[str] = field(default_factory=list)
    deny_patterns: list[str] = field(default_factory=list)

These collections can still be mutated at runtime:

    acl = ToolACL.allow_list(["search"])
    acl.allowed_tools.add("exec")       # Works -- set is mutable
    acl.allow_patterns.append("*")      # Works -- list is mutable

The fix requires changing the field types to `frozenset[str]` and `tuple[str, ...]` with
matching `default_factory=frozenset` and `default_factory=tuple`. This change has NOT been
applied. The `set[str]` and `list[str]` types with mutable default factories remain unchanged.

---

## Remaining Work

### Security Priority

**CRITICAL-4.5:** Change `allowed_tools` and `denied_tools` to `frozenset[str]`, and
`allow_patterns` and `deny_patterns` to `tuple[str, ...]`. Update `allow_list()`, `deny_list()`,
and `open()` factory methods to construct with immutable types.

**CRITICAL-3.1:** Add an `asyncio.Lock` to `ExecutionContext` (or equivalent) and acquire it
before any write to `state`, `loop_counters`, `node_execution_order`, or `turn_number` in
`CompiledGraph`'s parallel execution paths.

### Operational Quality

**CRITICAL-3.2:** Add `__enter__`/`__exit__` to `WasmToolSandbox` so `shutdown()` is called
automatically when used as a context manager.

---

*Report generated: 2026-03-15*
*Verifier: Claude (manual source inspection)*
