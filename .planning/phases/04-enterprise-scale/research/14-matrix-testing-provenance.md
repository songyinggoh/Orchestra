# Phase 4 Research: Matrix Testing & Verifiable Trust (Provenance)

**Researched:** 2026-03-11
**Domain:** CI/CD, Quality Assurance, Supply Chain Security, SLSA, Sigstore
**Status:** DRAFT

---

## 1. Matrix & Integration Testing at Scale

Orchestra's commitment to enterprise-grade stability requires verifying every change against a broad compatibility matrix.

### The Matrix Dimensions
*   **Python Versions:** 3.11, 3.12, 3.13
*   **Operating Systems:** Ubuntu (latest), Windows (latest), macOS (latest)
*   **Backends (Services):**
    *   PostgreSQL 15, 16
    *   Redis 6, 7
    *   NATS JetStream 2.10

### Optimization Strategies
*   **GitHub Actions:** Use `strategy.matrix` with `fail-fast: false`. Utilize `services` for Linux runners. For Windows/macOS, use localized installation or skip service-heavy tests if covered by Linux.
*   **GitLab CI:** Use `parallel:matrix` with sidecar `services`.
*   **Caching:** Implement OS-specific and Python-version-specific caching for `pip` and `mypy` to reduce runtime by 40-60%.
*   **Service Aliases:** Standardize hostnames (e.g., `postgres`, `redis`, `nats`) across all environments to keep test code agnostic.

---

## 2. Verifiable Trust: SLSA & Provenance

For the A2A (Agent-to-Agent) protocol, "Provenance" is a hard requirement. Enterprise partners must be able to verify that an agent is running a legitimate, untampered build of Orchestra.

### The SLSA Framework
We aim for **SLSA Build Level 3** (Build service is trusted; Provenance is non-forgeable).

### Key Technologies
*   **Sigstore / Cosign:** Used to sign OCI images (Docker) and build artifacts (Wheels/Tarballs) using OIDC "keyless" signing.
*   **SLSA GitHub Generator:** Reusable workflows from the SLSA framework that generate non-forgeable `.intoto.jsonl` provenance files.
*   **GitHub Attestations:** Native GitHub feature to store and verify build metadata.

### Implementation Pattern (OCI Images)
1.  **Build:** Create the Docker image in CI.
2.  **Attest:** Use `slsa-github-generator` to create a signed attestation linked to the commit SHA and workflow run.
3.  **Verify:** Partners use `slsa-verifier` or `cosign verify-attestation` before deploying or interacting with the agent.

---

## 3. CI/CD Workflow Evolution

### Current State
*   GitHub Actions: Basic lint/test on `main`.
*   GitLab CI: Matrix testing for Linux.

### Phase 4 Target
*   **Full Compatibility Matrix:** GitHub Actions expanded to Windows/macOS.
*   **Signed Releases:** Automated GitHub Releases with signed `.whl` files and `intoto` provenance.
*   **Secure OCI Registry:** Signed images in GHCR (GitHub Container Registry).
*   **SBOM (Software Bill of Materials):** Generate CycloneDX/SPDX SBOMs for every release to provide transparency into dependencies.

---

## 4. Summary Execution Order

1.  **Expand Matrix:** Update CI workflows to cover all OS/Python/Service combinations.
2.  **Artifact Signing:** Implement `cosign` and SLSA workflows for release artifacts.
3.  **Image Signing:** Enable OIDC-based signing for GHCR images.
4.  **Verification Tooling:** Provide a simple CLI utility (`orchestra verify`) for users to check the provenance of their local installation.
