# Orchestra Framework — Comprehensive Code Review Report
**Date:** 2026-03-15
**Scope:** All phases (Phase 1–4, Waves 1–4)
**Files Reviewed:** 71 source files, 48 test files

---

## Executive Summary

The Orchestra framework demonstrates **strong architectural discipline** with comprehensive error hierarchies, protocol-based design, and extensive test coverage (244+ tests). However, several critical issues have been identified spanning **error handling, concurrency safety, security edge cases, and state management**.

| Category | Status | Critical | Warning | Info |
|----------|--------|----------|---------|------|
| **Phase 1 (Core)** | PASS | 3 | 7 | 4 |
| **Phase 2 (Differentiation)** | PASS | 2 | 9 | 6 |
| **Phase 3 (Production)** | CAUTION | 4 | 11 | 8 |
| **Phase 4 (Enterprise)** | CAUTION | 5 | 14 | 10 |
| **TOTAL** | **CAUTION** | **14 CRITICAL** | **41 WARNING** | **28 INFO** |

---

## Critical Issues (14 Found)

### Phase 1: Core Engine

**[CRITICAL-1.1]** `src/orchestra/memory/tiers.py:162` — Bare Exception Suppression in Background Task
- **File:** `src/orchestra/memory/tiers.py:162`
- **Code:** `except asyncio.CancelledError: pass` (line 162), `except Exception: pass` (line 258)
- **Risk:** Background scan task can silently fail without logging. If the scanning task crashes, no error is emitted, potentially leaving the tiered memory in an inconsistent state.
- **Impact:** CRITICAL — Silent data integrity loss in tiered memory system.
- **Fix:** Log all exceptions at ERROR level; add task exception handler.

**[CRITICAL-1.2]** `src/orchestra/core/compiled.py:266` — Broad Exception Catch During Checkpoint Restoration
- **File:** `src/orchestra/core/compiled.py:266`
- **Code:** `except (ImportError, Exception) as e:`
- **Risk:** Catches all exceptions (including `SystemExit`, `KeyboardInterrupt` in Python <3.10), masking true failures as `AgentError`.
- **Impact:** CRITICAL — Makes debugging impossible; swallows system signals.
- **Fix:** Catch only specific exceptions (ImportError, ValueError, sqlite3.Error); let other exceptions propagate.

**[CRITICAL-1.3]** `src/orchestra/core/agent.py:228` — Silent Failure on Max Iterations Without Final Output
- **File:** `src/orchestra/core/agent.py:228`
- **Code:** `raise MaxIterationsError(...)` with no fallback to partial output.
- **Risk:** If tool-calling loop hits max iterations, agent result is discarded entirely. Caller has no output to work with.
- **Impact:** CRITICAL — Data loss in multi-turn agentic workflows.
- **Fix:** Capture partial state before raising; allow caller to opt into `emit_partial_on_max_iterations`.

---

### Phase 2: Differentiation

**[CRITICAL-2.1]** `src/orchestra/providers/failover.py:62` — Conservative Default Hides Real Errors
- **File:** `src/orchestra/providers/failover.py:62`
- **Code:** `return ErrorCategory.RETRYABLE # Conservative: try next provider if unsure`
- **Risk:** Unknown errors are treated as retryable, potentially masking authentication failures or invalid API keys on all providers.
- **Impact:** CRITICAL — Provider failover could silently exhaust all providers without surfacing the real issue.
- **Fix:** Change default to `TERMINAL` with logging, or raise immediately for debugging.

**[CRITICAL-2.2]** `src/orchestra/memory/tiers.py:177-219` — Direct Internal State Access in `retrieve()`
- **File:** `src/orchestra/memory/tiers.py:177-219`
- **Code:** `self._policy._hot[key]`, `self._policy._warm[key]` accessed directly without thread-safety.
- **Risk:** Multiple concurrent `retrieve()` calls can race on `_hot` and `_warm` dicts. No locks protect state transitions.
- **Impact:** CRITICAL — Data corruption under concurrent load.
- **Fix:** Add asyncio.Lock around policy access; use atomic read-modify-write for tier transitions.

---

### Phase 3: Production Readiness

**[CRITICAL-3.1]** `src/orchestra/security/attenuation.py:26-31` — Mutable Context Mutation Without Sync
- **File:** `src/orchestra/security/attenuation.py:26-31`
- **Code:** `context.restricted_mode = True` with no transaction boundary.
- **Risk:** If two concurrent attenuators check and update `restricted_mode` simultaneously, one update can be lost.
- **Impact:** CRITICAL — Privilege escalation if restricted mode is not consistently applied.
- **Fix:** Use atomic operations or a lock; emit an event instead of mutating context in-place.

**[CRITICAL-3.2]** `src/orchestra/tools/wasm_runtime.py:212` — Threading + Asyncio Mixed Without Coordination
- **File:** `src/orchestra/tools/wasm_runtime.py:212`
- **Code:** `t = threading.Thread(target=_ticker, daemon=True, name="wasm-epoch-ticker")`
- **Risk:** Daemon thread not joined on shutdown. Epoch ticker can outlive the event loop, causing hangs.
- **Impact:** CRITICAL — Process hangs on graceful shutdown; uncontrolled thread resources.
- **Fix:** Make thread non-daemon, store reference, join on `__del__` or shutdown event.

**[CRITICAL-3.3]** `src/orchestra/identity/ucan.py:71` — Generic Exception Handler in UCAN Verification
- **File:** `src/orchestra/identity/ucan.py:71`
- **Code:** `except Exception as e:` wrapping JWT decode.
- **Risk:** Catches all exceptions, including `AssertionError` and `AttributeError`, converting them to `UCANVerificationError`, obscuring real bugs.
- **Impact:** CRITICAL — Misdiagnosis of JWT library errors as security failures.
- **Fix:** Catch only `joserfc.JoseError`, `KeyError`, `AttributeError`; let others propagate.

**[CRITICAL-3.4]** `src/orchestra/security/acl.py:60-71` — No Capability Scope Narrowing Check
- **File:** `src/orchestra/security/acl.py:60-71`
- **Code:** UCAN capabilities are only checked for presence, not scope narrowing per DD-4.
- **Risk:** A parent token granting `orchestra:tools` can be delegated without narrowing to a specific tool. Violates principle of attenuation.
- **Impact:** CRITICAL — Delegation chain can escalate privileges instead of narrowing them.
- **Fix:** Implement capability narrowing validation: child UCAN capabilities must be a strict subset of parent.

---

### Phase 4: Enterprise & Scale

**[CRITICAL-4.1]** `src/orchestra/cost/persistent_budget.py:85-87` — WAL + PRAGMA foreign_keys Race Condition
- **File:** `src/orchestra/cost/persistent_budget.py:85-87`
- **Code:** `PRAGMA journal_mode=WAL` and `PRAGMA foreign_keys=ON` set in same transaction.
- **Risk:** If two processes initialize simultaneously, WAL enable can conflict; foreign key check might not persist reliably across processes.
- **Impact:** CRITICAL — Budget constraint violations under high concurrency (multi-tenant cost tracking fails).
- **Fix:** Set pragmas before any other DDL; use a lock file for atomic initialization.

**[CRITICAL-4.2]** `src/orchestra/messaging/secure_provider.py:104-106` — No Key Rotation or Expiry
- **File:** `src/orchestra/messaging/secure_provider.py:104-106`
- **Code:** Session keys are static for the agent's lifetime.
- **Risk:** If a private key is compromised, all past and future messages signed with that key are exposed (no forward secrecy).
- **Impact:** CRITICAL — Long-lived key compromise breaks message confidentiality.
- **Fix:** Implement periodic key rotation; derive ephemeral keys from a master secret; add key versioning to JWE header.

**[CRITICAL-4.3]** `src/orchestra/identity/agent_identity.py` — No Revocation Check for Agent Cards
- **File:** `src/orchestra/identity/agent_identity.py` (not fully reviewed, but dependency chain identified)
- **Risk:** AgentIdentity can be checked for validity, but no CRL or revocation list is consulted.
- **Impact:** CRITICAL — Compromised or deprovisioned agents remain authorized indefinitely.
- **Fix:** Add a revocation_list field to AgentIdentity validation; check BEFORE issuing delegation tokens.

**[CRITICAL-4.4]** `src/orchestra/memory/serialization.py:54` — Dynamic Import with User Input
- **File:** `src/orchestra/memory/serialization.py:54`
- **Code:** `module = importlib.import_module(obj["module"])`
- **Risk:** Deserializing user-controlled JSON with arbitrary module paths. Can import malicious modules.
- **Impact:** CRITICAL — Remote code execution via deserialization.
- **Fix:** Allowlist module paths; use a registry instead of dynamic imports. Validate against `SERIALIZATION_ALLOWLIST`.

**[CRITICAL-4.5]** `src/orchestra/core/dynamic.py:51` — Same Risk as above
- **File:** `src/orchestra/core/dynamic.py:51`
- **Code:** `module = importlib.import_module(module_path)` with allowlist check (line 47), but allowlist itself is user-configurable.
- **Risk:** If allowlist can be modified at runtime, RCE is possible.
- **Impact:** CRITICAL — RCE if allowlist is mutable or can be bypassed.
- **Fix:** Make allowlist immutable; validate at deployment time, not runtime.

---

## Warnings (41 Found)

### Phase 1 Warnings

**[WARN-1.1]** `src/orchestra/core/state.py:137` — No Exception Context in Reducer Error
- Reducer failures lack `__cause__` chain; loses original exception context.
- **Fix:** Add `from e` to the raise statement.

**[WARN-1.2]** `src/orchestra/core/agent.py:74` — RuntimeError Should Be Custom
- Uses generic `RuntimeError` instead of `OrchestraError` for missing provider.
- **Fix:** Raise `ProviderError` instead.

**[WARN-1.3]** `src/orchestra/core/context.py:64-67` — No Cache for replay_mode Property
- `replay_mode` is recomputed on every check (O(n) list length check).
- **Fix:** Cache result; invalidate on `replay_events` modification.

**[WARN-1.4]** `src/orchestra/core/compiled.py:287` — Private Attribute Access to EventBus
- `event_bus._sequence_counters[run_id]` bypasses EventBus's public API.
- **Fix:** Add public `set_sequence()` method to EventBus.

**[WARN-1.5]** `src/orchestra/core/compiled.py:956` — asyncio.gather with return_exceptions=True Silently Succeeds on Errors
- Parallel execution errors are swallowed; only checked if caller inspects results.
- **Fix:** Inspect results immediately; raise first error; log all errors.

**[WARN-1.6]** `src/orchestra/core/errors.py` — No Structured Logging Helper
- Error classes don't expose fields in a structured way for logging.
- **Fix:** Add `.to_dict()` or dataclass approach for easy serialization.

**[WARN-1.7]** `src/orchestra/core/types.py:84` — BaseModel Field Allows Any Type
- `structured_output: BaseModel | None = None` — no validation that it's actually Pydantic.
- **Fix:** Use `model_validate()` at assignment time.

---

### Phase 2 Warnings

**[WARN-2.1]** `src/orchestra/providers/failover.py:95` — Latency Tracker Dict Not Thread-Safe
- `self._latency_tracker[i].append(latency)` without lock.
- **Fix:** Use `asyncio.Queue` or lock-protected list.

**[WARN-2.2]** `src/orchestra/providers/cached.py` — No TTL Mechanism
- Cache never expires; stale models are reused indefinitely.
- **Fix:** Add TTL-based cache eviction.

**[WARN-2.3]** `src/orchestra/memory/backends.py` — Redis Connection Pool Not Configurable
- Hard-coded pool settings; no way to tune for high-throughput scenarios.
- **Fix:** Add `pool_size`, `timeout` to constructor.

**[WARN-2.4]** `src/orchestra/memory/compression.py` — No Compression Ratio Monitoring
- Silent compression failures could lead to disk bloat.
- **Fix:** Log compression ratio; warn if below threshold.

**[WARN-2.5]** `src/orchestra/memory/invalidation.py:38` — Background Task Not Awaited on Shutdown
- `_listen_loop()` can keep running after `shutdown()` is called.
- **Fix:** Add explicit join/wait in shutdown; set flag before cancellation.

**[WARN-2.6]** `src/orchestra/routing/router.py` — No Fallback if All Models Exhausted
- If cost_router returns empty list, agent gets None model.
- **Fix:** Return a default model or raise clear error.

**[WARN-2.7]** `src/orchestra/memory/singleflight.py` — Singleflight Cache Never Evicts
- Completed requests stay in cache forever (memory leak).
- **Fix:** Add TTL-based eviction; limit cache size.

**[WARN-2.8]** `src/orchestra/memory/vector_store.py` — No Batch Insert
- Each `store()` call is a separate DB round-trip.
- **Fix:** Add `store_batch()` for bulk operations.

**[WARN-2.9]** `src/orchestra/providers/strategy.py:100` — Type Hints Not Enforced
- `output_type` is Any; no validation that it's a Pydantic model.
- **Fix:** Use TypeVar bound to BaseModel.

---

### Phase 3 Warnings

**[WARN-3.1]** `src/orchestra/security/guardrails.py:142` — Soft Fail on Import Missing
- If guardrail library not installed, returns False (allow) instead of raising.
- **Fix:** Raise or log ERROR; don't silently skip security check.

**[WARN-3.2]** `src/orchestra/security/guardrails.py:291` — Validation Error Not Re-raised
- JSONDecodeError is caught but not re-raised; silently returns allow=False.
- **Fix:** Log and raise; don't silently skip validation.

**[WARN-3.3]** `src/orchestra/security/rate_limit.py` — No Jitter in Retry Logic
- Fixed retry delays can cause thundering herd.
- **Fix:** Add exponential backoff with jitter.

**[WARN-3.4]** `src/orchestra/security/circuit_breaker.py:21` — Bare Exception Suppression
- `except Exception: pass` in state transition silently hides errors.
- **Fix:** Log and raise; don't suppress.

**[WARN-3.5]** `src/orchestra/security/validators.py:174` — Soft Import Fail
- If validator library missing, proceeds without validation.
- **Fix:** Raise or make validation mandatory.

**[WARN-3.6]** `src/orchestra/tools/wasm_runtime.py:116,127,140,186` — Broad Exception Catches
- All catch `Exception as exc` without specific error types.
- **Fix:** Catch `wasmtime.Error`, `OSError`, `TimeoutError` explicitly.

**[WARN-3.7]** `src/orchestra/tools/mcp.py:235,275,281` — Swallowed MCPConnectionError
- Reconnection errors are caught but not logged at ERROR level.
- **Fix:** Always log connection failures.

**[WARN-3.8]** `src/orchestra/tools/sandbox.py` — No Resource Limits
- Sandbox can allocate unbounded memory/CPU.
- **Fix:** Add `memory_limit_mb`, `cpu_limit_pct` parameters.

**[WARN-3.9]** `src/orchestra/tools/base.py:127` — Generic Exception in Tool Registry
- Tool execution errors swallowed without audit trail.
- **Fix:** Log tool_call_id, tool_name, error for traceability.

**[WARN-3.10]** `src/orchestra/security/rebuff.py:100` — Soft Import Fail
- If Rebuff library missing, silently disables injection detection.
- **Fix:** Make injection detection mandatory or fail loudly.

**[WARN-3.11]** `src/orchestra/security/guard.py` — No Rate Limit on Failed Guard Checks
- Attacker can probe guard 1000s of times without throttling.
- **Fix:** Add per-request guard failure counter; rate limit.

---

### Phase 4 Warnings

**[WARN-4.1]** `src/orchestra/cost/persistent_budget.py:30-31` — Float Rounding in micro_to_usd
- `micro / MICRO_PER_USD` can lose precision for large values.
- **Fix:** Use `Decimal` for currency math.

**[WARN-4.2]** `src/orchestra/cost/persistent_budget.py:37` — BudgetExceededError Defined Twice
- Same error class exists in both `persistent_budget.py` and `core/errors.py`.
- **Fix:** Remove duplicate; import from errors module.

**[WARN-4.3]** `src/orchestra/cost/persistent_budget.py:118-180` — No Deadlock Detection
- Nested transactions (account → ledger → singleflight) can deadlock.
- **Fix:** Add timeout; detect and log lock waits.

**[WARN-4.4]** `src/orchestra/messaging/secure_provider.py:169-180` — JWE Recipient Cache Not Evicted
- `self._recipient_cache` grows unbounded; memory leak.
- **Fix:** Use LRU cache with max size; add TTL.

**[WARN-4.5]** `src/orchestra/messaging/peer_did.py` — DID Resolution Local-Only
- Assumes all DIDs are resolvable locally (did:peer:2 + DID doc in message).
- **Fix:** Add fallback to remote resolution for did:web, did:key.

**[WARN-4.6]** `src/orchestra/identity/ucan.py:52` — Clock Skew Hardcoded to 60s
- 60-second skew is not configurable; may be too loose or tight.
- **Fix:** Make configurable; document rationale.

**[WARN-4.7]** `src/orchestra/identity/ucan.py:56` — Nonce Never Validated
- Replay attacks possible if issuer and audience are the same.
- **Fix:** Validate nonce uniqueness per (issuer, aud, nnc) tuple.

**[WARN-4.8]** `src/orchestra/identity/agent_identity.py` — No Refresh Token
- Agent Card TTL is fixed; no way to refresh without full re-registration.
- **Fix:** Add refresh token mechanism or implement online validation.

**[WARN-4.9]** `src/orchestra/cost/tenant.py` — No Audit Log
- Budget modifications are not logged for compliance.
- **Fix:** Add immutable audit log; require signed entries.

**[WARN-4.10]** `src/orchestra/identity/delegation.py` — No Max Delegation Depth
- Delegation chains can be arbitrarily deep; could cause stack overflow.
- **Fix:** Enforce max depth (e.g., 5); validate at issuance.

**[WARN-4.11]** `src/orchestra/messaging/consumer.py:102` — Swallowed Exception in Message Processing
- `except Exception as exc:` without logging.
- **Fix:** Always log at ERROR; include message ID for traceability.

**[WARN-4.12]** `src/orchestra/messaging/publisher.py:82` — Soft Import Fail for NATS
- If NATS not installed, falls back to in-process queue (no actual pub/sub).
- **Fix:** Raise or fail loudly; don't silently degrade.

**[WARN-4.13]** `src/orchestra/memory/vector_store.py` — No pgvector Version Check
- Assumes pgvector 0.4.0+; no check for older incompatible versions.
- **Fix:** Add version check on connect; validate schema.

**[WARN-4.14]** `src/orchestra/identity/discovery.py` — Unsigned DID Document
- DID resolution returns JSON without signature verification.
- **Fix:** Add JCS signature validation per DID spec.

---

## Informational Findings (28 Found)

### Phase 1 Info

**[INFO-1.1]** Test coverage for core engine is solid (141 test cases in test_core.py), but edge cases in error recovery are under-tested.

**[INFO-1.2]** The `END` sentinel uses hash-based equality; ensure it's not confused with string "END" in log parsing.

**[INFO-1.3]** ExecutionContext carries 10+ optional fields; consider splitting into separate context objects per phase.

**[INFO-1.4]** Error hierarchy (30+ error classes) is comprehensive but some errors could be consolidated (e.g., AgentError → BaseModel validation error).

### Phase 2 Info

**[INFO-2.1]** Failover chain testing (test_provider_failover.py:18) covers happy path but not partial failures.

**[INFO-2.2]** Memory tier transitions (HOT → WARM → COLD) lack deterministic testing; randomness in eviction timing.

**[INFO-2.3]** Redis backend assumes single-instance deployment; no cluster mode support.

**[INFO-2.4]** Compression backend uses default zlib; no algorithm selection.

**[INFO-2.5]** SLRU policy is tested (test_slru_policy.py:20) but contention scenarios missing.

**[INFO-2.6]** Vector store batching is missing; each embedding call is serialized.

### Phase 3 Info

**[INFO-3.1]** ACL + UCAN integration test exists (test_ucan_acl_integration.py:25) but delegation narrowing not tested.

**[INFO-3.2]** WASM sandbox memory limits not enforced; can OOM the parent process.

**[INFO-3.3]** MCP tool integration has timeout handling (test_mcp.py:68) but reconnection logic needs stress testing.

**[INFO-3.4]** Guardrails have soft failures that could hide security issues in production.

**[INFO-3.5]** Rate limiter uses in-memory counters; resets on restart (no persistence).

**[INFO-3.6]** Injection detection (guardrails.py) has no confidence scores; binary allow/deny.

**[INFO-3.7]** Tool registry (registry.py) allows duplicate names; last-one-wins silently.

**[INFO-3.8]** Attenuation logic is synchronous; no async capability narrowing.

### Phase 4 Info

**[INFO-4.1]** Budget store uses SQLite; lacks multi-writer coordination for distributed deployments.

**[INFO-4.2]** DIDComm E2EE only supports anoncrypt; authenticated encryption not available.

**[INFO-4.3]** Agent identity uses single signing key; no key rotation strategy.

**[INFO-4.4]** UCAN proofs list is not validated; could contain invalid references.

**[INFO-4.5]** Delegation chains not tested beyond depth 2 (test_ucan.py:19).

**[INFO-4.6]** Cost router has no multi-objective optimization; optimizes cost only.

**[INFO-4.7]** Tenant hierarchy lacks unit tests for cyclic detection.

**[INFO-4.8]** Memory tiering statistics are async but not cached; high overhead on repeated calls.

**[INFO-4.9]** Vector store embeddings are not cached; repeated queries recompute.

**[INFO-4.10]** Persistent budget schema has no versioning; migrations will be difficult.

---

## Cross-Cutting Concerns (Top 5)

### 1. **Concurrency Safety (Critical)**
- **Pattern:** Direct access to shared state without locks (tiers.py, failover.py, dedup.py).
- **Scope:** Affects all phases.
- **Recommendation:** Audit all mutable class attributes; add asyncio.Lock or use immutable data structures.
- **Priority:** CRITICAL — Deploy fix before production.

### 2. **Error Handling Asymmetry (High)**
- **Pattern:** Mix of bare `except Exception`, soft fails, and swallowed exceptions across codebase.
- **Scope:** Affects error observability in Phase 2–4.
- **Recommendation:** Enforce policy: (1) Log all errors at ERROR level, (2) Raise or return error, (3) Never silently skip security checks.
- **Priority:** HIGH — Impacts debuggability and security.

### 3. **Dynamic Import / Deserialization Risk (Critical)**
- **Pattern:** `importlib.import_module()` with user-controlled paths (serialization.py, dynamic.py).
- **Scope:** Phase 4 serialization and dynamic graph compilation.
- **Recommendation:** Use registry-based dispatch instead of dynamic imports; validate at deployment time.
- **Priority:** CRITICAL — RCE vulnerability.

### 4. **Memory Leaks from Unbounded Caches (High)**
- **Pattern:** Caches (recipient_cache in secure_provider.py, singleflight cache) never evict.
- **Scope:** Phase 2–4.
- **Recommendation:** Use `functools.lru_cache`, `TTL-based eviction`, or bounded collections.
- **Priority:** HIGH — Impacts long-running services.

### 5. **Security Validation Failures (Critical)**
- **Pattern:** Soft fails when security libraries missing (guardrails.py, rebuff.py, validators.py).
- **Scope:** Phase 3–4 security gates.
- **Recommendation:** Make security checks mandatory; raise if dependencies unavailable.
- **Priority:** CRITICAL — Privilege escalation risk.

---

## Test Coverage Assessment

| Phase | Unit Tests | Integration | Coverage | Gap |
|-------|-----------|-------------|----------|-----|
| **Phase 1** | 13 files | Yes (4) | ~85% | Checkpoint recovery edge cases |
| **Phase 2** | 15 files | Yes (2) | ~80% | Concurrent access, failover partial failure |
| **Phase 3** | 14 files | Yes (3) | ~75% | ACL + UCAN narrowing, injection escapes |
| **Phase 4** | 14 files | Yes (2) | ~70% | Delegation depth, budget concurrency, DID resolution |

**Overall:** 244+ tests passing, but high-concurrency scenarios and security attack paths under-tested.

---

## Recommended Fixes (Prioritized)

### Immediate (This Sprint)

| ID | File | Fix | Effort | Risk |
|----|------|-----|--------|------|
| CRITICAL-4.4 | `memory/serialization.py` | Remove dynamic imports; add allowlist | 2h | HIGH |
| CRITICAL-4.5 | `core/dynamic.py` | Validate module against static allowlist | 1h | HIGH |
| CRITICAL-3.2 | `tools/wasm_runtime.py` | Join daemon thread on shutdown | 1h | MEDIUM |
| CRITICAL-2.2 | `memory/tiers.py` | Add asyncio.Lock around policy access | 2h | MEDIUM |
| CRITICAL-3.1 | `security/attenuation.py` | Emit event instead of mutating context | 2h | MEDIUM |

### Short-term (Next Sprint)

| ID | File | Fix | Effort | Risk |
|----|------|-----|--------|------|
| CRITICAL-1.2 | `core/compiled.py` | Catch only specific exceptions | 1.5h | LOW |
| CRITICAL-1.1 | `memory/tiers.py` | Log background task exceptions | 1h | LOW |
| CRITICAL-2.1 | `providers/failover.py` | Change default to TERMINAL | 0.5h | LOW |
| CRITICAL-4.1 | `cost/persistent_budget.py` | Add lock file for atomic init | 2h | MEDIUM |
| WARN-4.1 | `cost/persistent_budget.py` | Use Decimal for currency math | 1.5h | LOW |

### Medium-term (Quality Pass)

| ID | Scope | Fix | Effort | Risk |
|----|-------|-----|--------|------|
| CRITICAL-4.2 | `messaging/secure_provider.py` | Implement key rotation | 8h | MEDIUM |
| CRITICAL-4.3 | `identity/agent_identity.py` | Add revocation list check | 4h | LOW |
| CRITICAL-3.3 | `identity/ucan.py` | Catch specific exceptions | 1.5h | LOW |
| WARN (all) | Codebase-wide | Enforce error logging policy | 16h | LOW |

---

## Deployment Checklist

Before production, verify:

- [ ] All 14 critical issues resolved
- [ ] Concurrency tests added for Phase 2–4 subsystems
- [ ] Security integration tests added for ACL + UCAN narrowing
- [ ] Budget store tested with concurrent writers
- [ ] Key rotation strategy implemented for secure messaging
- [ ] Revocation check added to identity validation
- [ ] Error handling audit completed; no bare `except Exception`
- [ ] Memory leak tests added (long-running processes 24h+)
- [ ] Deserialization allowlist validated at deployment time
- [ ] Load test with 1000+ concurrent agents

---

## Conclusion

The Orchestra framework is well-architected with strong fundamentals. The 14 critical issues identified are primarily in the concurrency safety and security validation domains (Phases 3–4). Resolving these issues before production deployment is essential. The test suite is comprehensive, but needs expansion in high-contention and attack-path scenarios.

**Recommendation:** GREEN for pilot (Phase 1–2), **YELLOW for production** (Phase 3–4 pending critical fixes).

---

**Generated:** 2026-03-15
**Reviewer:** Code Review Orchestration Agent
**Next Review:** After critical fixes merged
