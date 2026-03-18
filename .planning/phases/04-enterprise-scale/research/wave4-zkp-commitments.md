# Wave 4: ZKP Input Commitments - Research

**Researched:** 2026-03-13
**Domain:** Cryptographic commitment schemes for agent state integrity
**Confidence:** MEDIUM (py-ecc API verified; performance data estimated; architectural design is novel)
**Task:** T-4.11 (A2A Protocol + ZKP Input Commitments)

---

## Summary

The PLAN.md specifies `py-ecc>=8.0.0` for "Input Hash Commitments in ZKP circuits" to prevent cross-org state forgery. After thorough investigation, `py-ecc` is the wrong tool for this job as a standalone library. It is a pure-Python elliptic curve library built for the Ethereum ecosystem (BN128/BLS12-381 pairing operations) -- it provides the mathematical primitives for ZKP circuits but does NOT provide a ZKP proving system, circuit compiler, or commitment scheme API. Using py-ecc to build commitments would mean hand-rolling cryptographic protocols on top of raw curve arithmetic.

The actual requirement -- preventing cross-org state forgery by tying proofs to verified state -- does NOT require full ZKP circuits. It requires **cryptographic commitment schemes** that bind agent state to a tamper-evident digest, with optional zero-knowledge opening for privacy. The Python ZKP ecosystem is immature: no production-ready, actively maintained library provides end-to-end ZKP proof generation and verification suitable for this use case.

**Primary recommendation:** Implement a **two-tier commitment scheme**: (1) a fast SHA-256/HMAC-based hash commitment for all state transitions (the 99% path), and (2) Pedersen commitments via **`blst`** for cross-org state exchange. This gives cryptographic state integrity without the performance penalty of pure-Python ECC on every operation.

---

## 1. Cryptographic Library: `blst` (Supranational)

### Why `blst` over `py-ecc` or `Chia BLS`?

| Library | Performance | Status | Suitability |
|---------|-------------|--------|-------------|
| `py-ecc` | POOR (Pure Python) | Active | Only for prototyping; 50-200ms per op. |
| `blst` | **EXTREME** (C/Assembly) | Active | **Selected.** Audited, used in Ethereum/Filecoin. |
| `Chia BLS` | HIGH | **Archived** | Replaced by `chia_rs`; not recommended for new projects. |

**Implementation:** Use `blst` Python bindings for all curve operations on **BLS12-381** ($y^2 = x^3 + 4$). This provides sub-millisecond curve multiplications.

---

## 2. State Canonicalization: RFC 8785 (JCS)

To ensure stable commitments across platforms (Python/TypeScript/Go), we strictly follow **RFC 8785 (JCS)**:

1. **Lexicographic Sorting:** Object keys must be sorted recursively by UTF-16 code units.
2. **Whitespace Removal:** Eliminate all whitespace between JSON tokens.
3. **Primitive Serialization:**
    - **Numbers:** Use IEEE 754 double-precision serialization (ECMAScript style).
    - **Strings:** Standard JSON escaping (RFC 8259).
    - **Literals:** `null`, `true`, `false`.
4. **Encoding:** The final canonical string is encoded as **UTF-8** bytes for the commitment input.

---

## 3. Concrete Commitment Scheme: Pedersen (Wave 4)

### Tier 1: SHA-256 Hash Commitments (Hot Path)
... (logic remains the same, using canonicalize_state from RFC 8785) ...

### Tier 2: Pedersen Commitments (Cold Path -- Cross-Org Verification)
**Scheme:** $C = vG + sH$
- **Curve:** BLS12-381 G1.
- **Generators:** $G$ is the standard generator; $H$ is a 'Nothing-Up-My-Sleeve' (NUMS) point generated via **RFC 9380 (Hash-to-Curve)**.
- **NUMS Seed:** "Orchestra-V01-Pedersen-H".
- **Domain Separation Tag (DST):** `ORCHESTRA-V01-CS01-with-BLS12381G1_XMD:SHA-256_SSWU_RO_`.

---

## 4. Knowledge Gap Reconciliation

| Gap | Status | Resolution |
|:---|:---|:---|
| Pedersen Performance | **RESOLVED** | Shift from `py-ecc` to `blst` (C-bindings). |
| State Canonicalization | **RESOLVED** | Adopt RFC 8785 (JCS) as the formal standard. |
| NUMS Verification | **RESOLVED** | Implement RFC 9380 Hash-to-Curve with versioned DST. |
| Library Selection | **RESOLVED** | Use `blst`; reject archived Chia `bls-signatures`. |

**Overall: ~95% ready for implementation.** Main risks are FFI stability and JCS number serialization edge cases in Python.
