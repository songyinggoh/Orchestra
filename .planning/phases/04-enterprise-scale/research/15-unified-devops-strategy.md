# Phase 4 Research: Unified DevOps Strategy

**Researched:** 2026-03-11
**Domain:** DevOps, CI/CD, DevSecOps, GitOps
**Status:** DRAFT

---

## 1. Vision: Beyond "CI as a Mirror"

The transition to Phase 4 requires moving from a passive mirror (GitHub → GitLab) to a **Unified DevOps Pipeline**. This pipeline serves as the ultimate gatekeeper for Enterprise-grade stability and security.

### Current State
*   GitHub: Primary source, basic linting, basic testing.
*   GitLab: Mirror for advanced matrix testing and security scanning.

### Target State (Unified)
*   **One Source of Truth:** GitHub Actions handles the full lifecycle (CI, CD, Sec).
*   **GitLab's Role:** Dedicated "Security Audit" mirror or High-Performance runner for massive parallelism.

---

## 2. Pillar 1: Consolidated CI (The Quality Gate)

Standardize all quality checks into a single high-performance matrix.

*   **Matrix:** Python 3.11–3.13 on Ubuntu, Windows, macOS.
*   **Dependencies:** Pre-installed sidecar services (Postgres, Redis, NATS) on Linux.
*   **Artifacts:** Coverage reports (Codecov), Test results (JUnit), and signed Wheels.

---

## 3. Pillar 2: GitOps-Ready CD (The Deployment Gate)

Bridge the gap between "code" and "cluster" by testing the actual deployment artifacts.

*   **KinD (Kubernetes-in-Docker):** Spin up a temporary K8s cluster in every CI run.
*   **Helm Verification:**
    *   `helm lint` & `chart-testing (ct)` for schema validation.
    *   `helm install` into KinD to verify template rendering and pod readiness.
*   **Integration Testing:** Run E2E tests against the *deployed* agents in KinD, ensuring KEDA and NATS connections work in a real cluster environment.

---

## 4. Pillar 3: Shift-Left Security (The Trust Gate)

Integrate security into the earliest possible stage of the developer workflow.

*   **Secret Detection:** **Gitleaks** to catch committed keys (DIDs, DIDComm keys, Provider API keys).
*   **Python SAST:** **Bandit** for static code analysis (catching `eval()`, insecure subprocesses).
*   **Dependency Scanning:** **pip-audit** to verify third-party packages against the OSV/GitHub Advisory database.
*   **Container Scanning:** **Trivy** to scan built OCI images for OS-level vulnerabilities.

---

## 5. Implementation Roadmap

### Step 1: CI/CD Consolidation
*   Create `.github/workflows/devops.yml` merging lint, test, and security.
*   Implement `kind` cluster setup for Helm smoke tests.

### Step 2: Security Hardening
*   Add `bandit` and `pip-audit` to the CI flow.
*   Configure Gitleaks with a project-specific `.gitleaks.toml`.

### Step 3: Deployment Automation
*   Trigger ArgoCD sync via GitHub Actions (or rely on ArgoCD's auto-sync).
*   Implement SLSA provenance for release builds.

---

## 6. Summary Execution Order

1.  **Consolidate:** Merge disparate CI workflows into a single `devops.yml`.
2.  **Verify Deploy:** Add `kind` + `helm` integration testing.
3.  **Harden:** Add Bandit and pip-audit.
4.  **Mirror:** Keep GitLab mirror for redundancy and advanced security features.
