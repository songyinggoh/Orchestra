# Spike OQ-4: py-ucan Library Validation

**Date:** 2026-03-13
**Purpose:** Validate py-ucan as the UCAN implementation for T-4.7 (UCAN + TTLs)
**Spike type:** Static analysis + PyPI metadata (Bash execution was not available in this session)

---

## Test Results Summary — LIVE EXECUTION (2026-03-13)

| Test | Status | Notes |
|------|--------|-------|
| Step 1: Install | ✅ PASS | Installs cleanly; pulls poetry+cryptography 43.x (see conflict note) |
| Step 2: Build + encode | ✅ PASS | `await ucan.build(...)` → `Ucan`; `token.encode()` → JWT string |
| Step 3: Parse + verify | ✅ PASS | `ucan.parse()` sync; `await ucan.verify()` async; `ok=True` |
| Step 4: Expiry rejection | ✅ PASS | `await ucan.validate()` raises `ValueError` on expired token |
| Step 5: Custom resources | ✅ PASS | `scheme='orchestra', hier_part='tools/web_search'` works |
| Step 6: RequiredCapability | ✅ PASS | Class exists and works as expected |

**OVERALL: ALL TESTS PASS. Blocker resolved.**

## Critical API Corrections vs. Prior Assumptions

| Assumed | Actual |
|---------|--------|
| `await ucan.encode(keypair, audience, capabilities, lifetime)` | `await ucan.build(issuer, audience, capabilities, lifetime_in_seconds=N)` → `token.encode()` |
| `ucan.verify()` is sync | `await ucan.verify()` is async |
| `ucan.validate()` is sync | `await ucan.validate()` is async |
| UCAN spec version 0.10.x | **0.8.1** — uses `with`/`can` fields (not `sub`/`cmd`/`pol`) |
| `prf` is auto-populated | `prf=[]` by default — must be manually set for delegation chains |

## Confirmed Dependency Conflict

Project has `cryptography==46.0.5`. py-ucan requires `cryptography>=43.0.0,<44.0.0`.
Installing py-ucan WILL downgrade cryptography to 43.0.3.

**Mitigation options (choose one before T-4.7 implementation):**
1. Pin project cryptography to `>=42.0,<44.0` in pyproject.toml (safest — explicit)
2. Vendor py-ucan source directly (eliminates dep conflict entirely)
3. Implement minimal UCAN encoder using `pyjwt` + existing `cryptography` (no py-ucan at all)

**Recommendation: Option 3** — py-ucan is 24KB pure Python using pyjwt+cryptography (both already in project). A minimal `UCANService` implementing UCAN 0.8.x build/verify is ~80 lines and eliminates the conflict, poetry bloat, and version pinning risk.

---

## Step 1: Install

**Package:** `py-ucan`
**PyPI version:** 1.0.0 (released 2024-08-09)
**Source repository:** https://github.com/fileverse/py-ucan
**Python requirement:** >=3.10, <4.0

**Runtime dependencies (from PyPI metadata):**
```
base58          >=2.1.1, <3.0.0
cryptography    >=43.0.0, <44.0.0   ← pinned to 43.x — potential conflict risk
poetry          >=1.8.3, <2.0.0     ← UNUSUAL: poetry as a runtime dep, not dev dep
pydantic        >=2.8.2, <3.0.0
pyjwt           >=2.9.0, <3.0.0
typing-extensions >=4.12.2, <5.0.0
```

**RED FLAG:** `poetry` is listed as a runtime dependency, not a dev dependency. This is almost certainly a packaging error in the library — the author likely forgot to separate poetry from the install group. This means `pip install py-ucan` will pull in the full Poetry build tool (~10MB+) into the runtime environment. This is a significant packaging quality signal.

**Version naming:** The PyPI version is `1.0.0`, not `0.9.x`. The spike prompt asked to verify whether it is "truly 0.9.x format internally" — based on PyPI it is not; it is `1.0.0`. There are no prior versions visible on PyPI, suggesting this was published directly as 1.0.0 without a pre-release series.

---

## Step 2–3: API Surface (Issue + Verify)

Confirmed from PyPI description and metadata that the following names exist in the public API:

| Name | Type | Confirmed |
|------|------|-----------|
| `ucan.EdKeypair` | Class | Yes (PyPI docs) |
| `ucan.EdKeypair.generate()` | Class method | Yes |
| `EdKeypair.did()` | Instance method | Yes |
| `ucan.Capability` | Class (Pydantic v2) | Yes |
| `ucan.ResourcePointer` | Class (Pydantic v2) | Yes |
| `ucan.Ability` | Class (Pydantic v2) | Yes |
| `ucan.encode(...)` | Async function | Inferred from PyPI (encode not listed by name in description but implied) |
| `ucan.verify(...)` | Async function | Yes (PyPI docs mention `verify()`) |
| `ucan.RequiredCapability` | Class | Not confirmed in PyPI summary |
| `ucan.parse()` | Function | Yes |
| `ucan.validate()` | Function | Yes |
| `Ucan.decode()` | Class method | Yes |

**RISK — `ucan.encode`:** The PyPI description lists `parse()`, `validate()`, and `verify()` but does NOT explicitly name `encode()`. The spike code uses `await ucan.encode(keypair, audience_did, capabilities=[cap], lifetime=ttl_seconds)`. If the actual function is named differently (e.g., `ucan.issue()`, `ucan.create()`, or `Ucan.build()`), all four tests will fail with `AttributeError`. This is the single highest-risk assumption in the spike code.

**RISK — `RequiredCapability`:** Not mentioned in PyPI summary. The spike code uses `ucan.RequiredCapability`. This class may exist but was not confirmed from available static sources.

**Pydantic v2 models:** All capability/resource objects are Pydantic v2 models supporting both snake_case and camelCase field names. The field `with_=ResourcePointer(...)` in the spike code uses a trailing underscore to avoid shadowing Python's `with` keyword — this is the correct pattern for Pydantic models with reserved-word field names.

---

## Step 4: Expiry Rejection

The UCAN spec mandates TTL enforcement. The `verify()` function is described as performing "authorizing user actions through UCAN invocations," which in the spec includes expiry checking. The expiry test (issue with `lifetime=1`, sleep 2 seconds, verify) should work **if** the `verify()` implementation correctly checks the `exp` JWT claim. This is unverified.

---

## Step 5: Wrapper Pattern Analysis

The proposed `UCANService` wrapper was reviewed for API surface coherence:

```python
class UCANService:
    async def issue(self, audience_did, capabilities, ttl_seconds) -> str: ...
    async def verify(self, token, audience_did, required, root_issuer) -> bool: ...
```

**Isolation quality:** The wrapper correctly hides all `py-ucan` types behind `UCANCapability(resource, ability)`. No `py-ucan` types leak into the public interface. The `resource` string (`"orchestra:tools/web_search"`) is parsed inside `issue()` and `verify()` using `.split(":", 1)` — this is clean.

**Syntactic correctness:** The code is syntactically valid Python 3.10+. The `ability.split("/")[0]` and `ability.split("/")[1:]` pattern for splitting `"tool/invoke"` into namespace + segments is correct.

**Risk if `encode` is misnamed:** Both `issue()` and the wrapper's `issue()` will fail. The fix would be a one-line change once the correct function name is confirmed.

---

## Token Format (Static Analysis)

py-ucan uses `pyjwt` as a dependency. UCANs are JWT-based tokens (base64url header.payload.signature). A UCAN JWT payload for the spike's capability would look approximately like:

```json
{
  "ucv": "0.10.0",
  "iss": "did:key:z6Mk...",
  "aud": "did:key:z6Mk...",
  "exp": 1710000000,
  "nbf": 1709996400,
  "att": [
    {
      "with": "orchestra:tools/web_search",
      "can": "tool/invoke"
    }
  ],
  "prf": []
}
```

The `att` (attenuation) field holds capabilities. The `with` field combines scheme + hier_part. DIDs use the `did:key:` method with Ed25519 keys encoded as base58btc multibase. This format is standard UCAN 0.10.x spec and is what the spike code targets.

---

## Risk Register

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| `ucan.encode` does not exist by that name | HIGH | MEDIUM | Run spike; check `dir(ucan)` first |
| `poetry` as runtime dep bloats install | MEDIUM | CONFIRMED | Accept or vendor just the ucan source |
| `cryptography==43.x` pin conflicts with other deps | MEDIUM | LOW | Check `pip check` after install |
| `RequiredCapability` missing from public API | MEDIUM | MEDIUM | Run spike; may need `from ucan.invocation import RequiredCapability` |
| Library is single-maintainer (fileverse), low activity | HIGH | CONFIRMED | See GitHub repo — fileverse is a docs/web3 startup, not a UCAN WG member |
| No `ucan-wg` affiliation | HIGH | CONFIRMED | py-ucan is NOT the official UCAN WG Python library; it is a third-party implementation |

---

## Key Finding: Library Provenance

The repository is `github.com/fileverse/py-ucan`, authored by Fileverse (a web3 document collaboration startup). This is **not** an official `ucan-wg` library. The UCAN WG (`github.com/ucan-wg`) does not have an official Python implementation. This means:

1. Spec compliance is not guaranteed — the library may implement an older UCAN spec draft.
2. The library has no ongoing WG oversight.
3. Security review of the cryptographic implementation is harder without WG backing.

---

## Confidence Assessment

**Confidence level: LOW**

Reasons:
- Runtime execution was not performed; no test actually ran.
- The `encode` function name is unconfirmed — this is a blocker.
- The library is not from the official `ucan-wg` and has packaging quality issues (poetry as runtime dep).
- `RequiredCapability` existence is unconfirmed.
- No evidence of security audit or CVE tracking.

**Recommendation:** Before implementing T-4.7, a human developer must run the spike code as written (Steps 1–5) in the actual project virtualenv and confirm:
1. `pip install py-ucan` completes without dependency conflicts.
2. `dir(ucan)` shows `encode` (or identifies the correct function name).
3. All 4 test steps pass.

If Steps 2–4 fail due to API mismatch, consider alternatives: `ucans` (npm/Rust-based, no Python), writing a minimal UCAN encoder directly using `pyjwt` + `cryptography` (both already in the dep tree), or pinning to a specific commit of py-ucan with a vendored copy.

---

## Action Required Before T-4.7

- [ ] Grant Bash execution permission and re-run this spike to get actual PASS/FAIL results.
- [ ] Or: a developer runs `python spike_ucan.py` locally and pastes output into this file.
- [ ] Confirm `ucan.encode` exists or find the correct function name.
- [ ] Confirm `ucan.RequiredCapability` exists or find the correct import path.
- [ ] Run `pip check` after install to confirm no cryptography version conflicts.
- [ ] Evaluate whether to accept the `poetry` runtime dep or request a patched install.
