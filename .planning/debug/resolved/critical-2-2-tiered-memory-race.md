---
status: resolved
trigger: "Investigate, re-assess, reproduce, and fix CRITICAL-2.2 — Direct Internal State Access in retrieve() without thread-safety"
created: 2026-03-15T00:00:00Z
updated: 2026-03-15T00:10:00Z
symptoms_prefilled: true
goal: find_and_fix
---

## Current Focus

hypothesis: The original CRITICAL-2.2 report was filed against unprotected _policy._hot/_warm access. A _policy_lock (asyncio.Lock) is already present in the code. The question is whether it is applied correctly everywhere and whether any genuine async yield-point races remain.
test: Audit every access to _policy._hot, _policy._warm across the codebase; verify lock coverage; write concurrent pytest to exercise race windows.
expecting: Either (a) the lock is correctly applied everywhere — SKIP verdict, or (b) specific gaps remain — FIX with targeted tests.
next_action: Complete re-assessment; write reproduction test; verify; commit.

## Symptoms

expected: All accesses to _policy._hot and _policy._warm are protected by _policy_lock with no async I/O inside the lock.
actual: Original report said these were unprotected. Need to verify whether a previous partial fix is complete or incomplete.
errors: No runtime error yet — risk is silent data corruption / KeyError under concurrent load.
reproduction: 50+ concurrent retrieve() coroutines + background promote/demote task; asyncio.gather.
started: Filing reflects state before any concurrency fix.

## Eliminated

- hypothesis: _policy_lock does not exist at all
  evidence: Line 163 of tiers.py — `self._policy_lock = asyncio.Lock()` is clearly present in __init__
  timestamp: 2026-03-15T00:01:00Z

- hypothesis: retrieve() accesses _policy._hot/_warm without any lock
  evidence: Lines 219-225 and 234-240 both use `async with self._policy_lock:` before accessing _hot/_warm. All four direct accesses in retrieve() are inside the lock.
  timestamp: 2026-03-15T00:02:00Z

- hypothesis: store() is unprotected
  evidence: Lines 199-200 — `async with self._policy_lock: evictions = self._policy.insert(key, entry)` — protected.
  timestamp: 2026-03-15T00:02:00Z

- hypothesis: stats() is unprotected
  evidence: Lines 320-322 — `async with self._policy_lock: hot_count = ...; warm_count = ...` — protected.
  timestamp: 2026-03-15T00:02:00Z

- hypothesis: demote() is unprotected
  evidence: Lines 297-298 — `async with self._policy_lock: self._policy.remove(key)` — protected.
  timestamp: 2026-03-15T00:02:00Z

## Evidence

- timestamp: 2026-03-15T00:01:00Z
  checked: tiers.py full read, lines 1-373
  found: _policy_lock = asyncio.Lock() exists (line 163). Every direct access to _policy._hot or _policy._warm occurs inside `async with self._policy_lock:`. No I/O (await) is performed while the lock is held. Pattern is: acquire lock → read/mutate in-memory state → release → perform I/O outside lock.
  implication: The implementation already satisfies the fix prescribed in CRITICAL-2.2. A previous fix has already been applied correctly.

- timestamp: 2026-03-15T00:02:00Z
  checked: retrieve() lines 209-273 — four lock-guarded blocks
  found:
    Block 1 (HOT check): lines 219-225 — lock held, reads _hot[key].value, calls access().
    Block 2 (WARM check): lines 234-240 — lock held, reads _warm[key].value, calls access().
    Block 3 (warm backend promote): lines 252-255 — lock held, writes _policy._hot[key], calls evictions_due(). I/O (self._warm.get) is OUTSIDE the lock.
    Block 4 (cold backend promote): lines 264-267 — lock held, writes _policy._hot[key], calls evictions_due(). I/O (self._cold.retrieve) is OUTSIDE the lock.
  implication: The retrieve() implementation matches the prescribed fix pattern exactly.

- timestamp: 2026-03-15T00:03:00Z
  checked: SLRUPolicy methods — access(), insert(), evictions_due(), remove() — for internal consistency
  found: All methods are synchronous pure-Python (no awaits). They mutate OrderedDict objects. No async yield points inside. All callers hold _policy_lock before calling these methods.
  implication: Under asyncio cooperative scheduling there are no yield points inside policy mutations, so there is no window for another coroutine to interleave while the policy is in a partial state.

- timestamp: 2026-03-15T00:04:00Z
  checked: GIL relevance
  found: This is asyncio (single-threaded cooperative). The GIL is not relevant here. The relevant protection is ensuring no `await` occurs between a check and a use of policy state. The current code captures the value under the lock (val = self._policy._hot[key].value) before releasing, so there is no check-then-use gap in the async sense.
  implication: No genuine race window exists in the current implementation.

- timestamp: 2026-03-15T00:05:00Z
  checked: test files for concurrent coverage
  found: test_tiered_memory.py and test_memory_tiers_full.py have no concurrent retrieve/store tests. The concurrency tests prescribed in CRITICAL-2.2 Step 5 are missing.
  implication: The fix exists but is unverified by test. Adding the three concurrent tests is the remaining action.

## Resolution

root_cause: CRITICAL-2.2 was a VALID finding at time of filing. However, a correct fix has already been applied: _policy_lock (asyncio.Lock) wraps all policy state accesses; no I/O is performed while the lock is held; the value is captured inside the lock before release. The implementation matches the prescribed fix pattern exactly.

fix: Production code required no changes. Three concurrent tests were added to tests/unit/test_tiered_memory.py to verify the existing lock implementation under load.

verification: All 21 tiered-memory + SLRU tests pass. Full unit suite: 579 passed, 4 skipped, 0 failures.

files_changed:
  - tests/unit/test_tiered_memory.py (appended test_concurrent_retrieve_no_corruption, test_concurrent_store_and_retrieve, test_promotion_under_concurrent_load)
