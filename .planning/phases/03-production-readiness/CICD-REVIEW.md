# CI/CD & DevOps Workflow Code Review

**Reviewed:** 2026-03-11
**Branch:** phase3-production-readiness
**Reviewer:** code-reviewer agent

---

## Summary

**Overall quality score: 6 / 10**

The pipeline has a genuinely strong security posture for releases (SLSA provenance, Cosign image signing, Gitleaks, Bandit, pip-audit) and good cross-platform matrix coverage. However, it contains several correctness bugs that will cause silent failures in CI, a coverage threshold mismatch between `phase3-gates.yml` and `pyproject.toml`, force-push mirroring with no safeguard, and a service-container misconfiguration that will cause flaky failures on non-Linux matrix legs.

---

## Critical Issues (must fix before merging)

### C-1 — Service containers defined on a matrix job that includes Windows and macOS (ci.yml lines 69–96)

GitHub Actions service containers only run on Linux (`ubuntu-latest`). The `test` job declares `services:` (postgres, redis, nats) at the job level but runs on a 3x3 OS matrix including `windows-latest` and `macos-latest`. On non-Linux runners the service block is silently ignored; the containers are never started. The integration test step is guarded with `if: matrix.os == 'ubuntu-latest'` (line 116), so integration tests are safe — but the unit test step on line 111–113 already has `-m "not integration"`, which means unit tests do not need the services at all.

The problem: the services block wastes runner startup time on every non-Linux leg, and if any unit test accidentally relies on a service being present, it will fail only on Linux while passing on Windows/macOS, creating an invisible cross-platform asymmetry. More dangerously, there is no health-check guard on the NATS container (lines 92–96) — only postgres and redis have `options: --health-cmd`. If NATS is slow to start, integration tests that connect to it on Linux will fail intermittently.

**Fix:** Move service containers inside a separate Linux-only job, or add a NATS health-check option (`--health-cmd "nats-server --help"`).

### C-2 — Coverage gate in phase3-gates.yml (line 25) contradicts pyproject.toml

`phase3-gates.yml` enforces `--cov-fail-under=70`. `pyproject.toml` (line 138) sets `fail_under = 80` under `[tool.coverage.report]`. These are inconsistent: any developer running `pytest --cov` locally enforces 80%, but CI enforces only 70%. The gate should be at least as strict as the local config — preferably higher for a production-readiness phase. Given the project has 244+ tests and is in Phase 3, 80% is the correct floor; 70% is a regression.

**Fix:** Change `--cov-fail-under=70` to `--cov-fail-under=80` to match `pyproject.toml`.

### C-3 — `--cov=src/orchestra` vs `[tool.coverage.run] source = ["orchestra"]` mismatch (phase3-gates.yml line 23, ci.yml line 113)

`phase3-gates.yml` passes `--cov=src/orchestra` (the filesystem path). `ci.yml` passes `--cov=orchestra` (the package name). `pyproject.toml`'s `[tool.coverage.run]` also uses `source = ["orchestra"]` (package name). Using the path form (`src/orchestra`) with pytest-cov works when `src/` is on sys.path, but it produces a different coverage data key than the package form — meaning if the two coverage reports are ever merged (e.g., in Codecov), they will appear as separate, non-overlapping sources, understating actual coverage. Consistency with the installed-package name is the correct approach.

**Fix:** Change `--cov=src/orchestra` to `--cov=orchestra` in `phase3-gates.yml` line 23.

### C-4 — `tests/security/` is excluded from the phase3-gates.yml unit test run

`phase3-gates.yml` runs `pytest tests/unit/ tests/integration/`. `tests/security/` (containing `test_wasm_sandbox.py`, `test_gvisor_interception.py`, `test_nats_e2ee.py`) is never executed in this gate. The main `ci.yml` does run `tests/security/` (line 122) but only on Linux. If `phase3-gates.yml` is the authoritative gate for the phase3 branch, security tests have no coverage gate at all on that branch.

---

## Major Issues (should fix)

### M-1 — Force-push mirroring to GitLab with no branch filter (mirror-to-gitlab.yml lines 19–20)

```
git push gitlab --all --force
git push gitlab --tags --force
```

`--force` with `--all` rewrites every branch on the GitLab remote without confirmation. This is intentional for a mirror, but it means a mistake on any branch (e.g., an accidental `git commit --amend` of a shared commit on `master`) will silently destroy GitLab history with no recovery path. Tags are also force-pushed, which can overwrite signed release tags.

This is a deliberate design choice for a mirror, but it needs two safeguards:
1. The workflow triggers on `branches: ["*"]` — this includes forks' PRs if the repo is public with `pull_request_target`. Restrict to `push:` events only from the main repo (already the case, but worth documenting).
2. Consider excluding tags from force-push: `git push gitlab --tags` without `--force` would still create new tags but refuse to overwrite existing ones, protecting release integrity.

### M-2 — `hypothesis` installed ad-hoc outside the extras in phase3-gates.yml (line 50)

```
pip install -e ".[dev,server,storage]" hypothesis
```

`hypothesis` is defined in the `test-advanced` extra in `pyproject.toml` (line 74). Installing it as a bare `pip install hypothesis` bypasses version pinning, meaning CI gets `hypothesis latest` regardless of any version constraint. This is a reproducibility risk — a hypothesis major release could silently break property tests.

**Fix:** Use `pip install -e ".[dev,server,storage,test-advanced]"` to get the pinned version.

### M-3 — No `permissions:` block on ci.yml, cd.yml, or phase3-gates.yml

`release.yml` correctly sets `permissions: contents: read` at the top level. The other three workflow files have no `permissions:` declaration, meaning they inherit the default `GITHUB_TOKEN` permissions for the organization/repo. For public repos the default is read-only for most scopes, but for private repos or organizations with permissive defaults this grants write access to contents and packages. OIDC token injection attacks via compromised third-party actions are more impactful when the token has write permissions.

**Fix:** Add `permissions: contents: read` (or the minimal set needed) at the top of `ci.yml`, `cd.yml`, and `phase3-gates.yml`.

### M-4 — `gitleaks/gitleaks-action@v2` is not pinned to a SHA (ci.yml line 40)

All other actions in the codebase use version tags (`@v4`, `@v5`, etc.). `gitleaks/gitleaks-action@v2` is a floating tag — if the gitleaks repo is compromised or the tag is moved, the security scanning step itself becomes the attack vector. This is a particularly bad place to have an unpinned action because it runs with `GITHUB_TOKEN` in scope and has full checkout access.

**Fix:** Pin to the full commit SHA, e.g., `gitleaks/gitleaks-action@44c470d`, and add a comment with the version it corresponds to.

### M-5 — CD workflow runs on every PR to main, not just merged commits (cd.yml lines 3–7)

```yaml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
```

`cd.yml` runs Helm chart installation tests (`ct install`) on every PR. `ct install` actually deploys charts into a KinD cluster. Running real deployments on PR events means every contributor's PR triggers a Kubernetes cluster creation and chart deployment, which is expensive and potentially unsafe if the PR modifies the Helm charts. Typically `cd.yml` should run on `push` to main (after merge), or the `ct install` step should be limited to `push` while only `ct lint` runs on PRs.

### M-6 — Dockerfile uses `pip install -e` (editable install) in production image (Dockerfile line 17)

```dockerfile
RUN pip install --no-cache-dir -e ".[server,telemetry,cache,storage,postgres,nats,ray,security]"
```

Editable installs (`-e`) create a `.pth` file pointing back to the source directory. In a Docker image this works, but it is not best practice for a production image: it exposes the full source tree under `/app/src/` rather than installing the compiled package into `site-packages`. It also means `pip install --no-cache-dir` does not fully eliminate the source from the image layers because `COPY src/ src/` is a preceding layer. A non-editable install (`pip install .`) would install only the compiled package into `site-packages` and reduce image surface area.

### M-7 — No `concurrency:` group defined in ci.yml or phase3-gates.yml

Without concurrency groups, opening a PR and then immediately pushing another commit launches two concurrent CI runs. Both consume runner minutes but only the later one matters. This is particularly wasteful with the 9-job matrix (3 OS × 3 Python) in ci.yml.

**Fix:** Add at the workflow level:
```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

---

## Minor Issues / Suggestions

### m-1 — Python version inconsistency between files

- `ci.yml` matrix: `["3.11", "3.12", "3.13"]`
- `phase3-gates.yml`: hardcoded `"3.13"` for all three jobs
- `cd.yml`: hardcoded `"3.12"`
- `Dockerfile`: `python:3.12-slim`
- `pyproject.toml` mypy: `python_version = "3.11"`

There is no single authoritative version. The Dockerfile should match the version used in production; if that is 3.12, then `phase3-gates.yml` using 3.13 exclusively means the gates are validated against a version that does not match the deployment image.

### m-2 — `ray` included in ci.yml install but `ray[serve]` is 500MB+ (ci.yml line 109)

The MEMORY.md notes that Ray was chosen over NATS for a different reason, but `ray[serve]>=2.10` in the install command for every matrix leg (including Windows and macOS) will substantially increase install times. Ray's Windows support is also limited. Consider excluding `ray` from the test dependency install and using a separate optional Ray test job.

### m-3 — No artifact upload for test results or coverage report in ci.yml

`ci.yml` uploads coverage to Codecov (line 124) but does not upload the `coverage.xml` or JUnit XML report as a GitHub Actions artifact. If Codecov is unavailable or the token is missing, there is no fallback record of the coverage run.

### m-4 — `fetch-depth: 0` in cd.yml may be unnecessary

`cd.yml` does `fetch-depth: 0` (full history) for the checkout. Chart testing (`ct lint`/`ct install`) does not need full git history — it uses it to detect changed charts, which is useful. This is acceptable but worth documenting the reason in a comment.

### m-5 — `release.yml` `image` job has no dependency on `provenance` or `release`

The `image` job builds and pushes the Docker image to GHCR independently of the `release` and `provenance` jobs. This means a Docker image could be published to GHCR before the GitHub Release is created and before SLSA provenance is attached. While the image is independently signed via Cosign, the ordering implies the image could be publicly available before the release is considered complete. Add `needs: [release]` to the `image` job.

### m-6 — `softprops/action-gh-release@v2` in release.yml is a floating minor tag

Like the gitleaks action, this is a tag not a SHA. For a release workflow that writes to the GitHub Release page, pinning to a SHA is preferable.

### m-7 — `POSTGRES_PASSWORD: password` in ci.yml (line 75) is a hardcoded credential

This is a test-only credential used only inside the ephemeral CI container network, so it is not a real secret exposure. However, Gitleaks may flag it. Adding a `# gitleaks:allow` comment or moving to a GitHub secret (`${{ secrets.CI_POSTGRES_PASSWORD }}`) prevents false-positive secret scanner alerts.

### m-8 — `phase3-gates.yml` has no job dependency (`needs:`) between the three jobs

`unit-tests`, `chaos-tests`, and `property-tests` run fully in parallel. If `chaos-tests` depends on the codebase being installable (which `unit-tests` already validates), a failure in the install step of `unit-tests` will not short-circuit the other two jobs. This is a minor efficiency issue rather than a correctness issue.

---

## Positives

1. **SLSA Level 3 provenance** for both the Python package and Docker image in `release.yml` is exemplary supply-chain security — most projects at this stage do not have this.
2. **Cosign image signing** in `release.yml` with keyless signing via OIDC is the current best practice.
3. **SHA-pinned commit checkout** (`actions/checkout@v5`, `actions/setup-python@v5`) for all first-party actions.
4. **Three-layer security scanning**: Gitleaks (secrets), Bandit (SAST), pip-audit (SCA) in `ci.yml`.
5. **`fail-fast: false`** on the matrix in `ci.yml` ensures one failing OS does not hide results from the others.
6. **GitLab PAT URL-encoding** in `mirror-to-gitlab.yml` is correctly implemented using Python's `urllib.parse.quote` with `safe=''` and the `tr -d '\n\r '` pre-clean — this was the bug fixed in recent commits and the current approach is correct.
7. **Built-in pip caching** (`cache: 'pip'` in `actions/setup-python`) on the matrix job reduces install time.
8. **NATS health-check port** (8222 monitoring) is exposed in the service container, which is useful for debugging.
9. **`generate_release_notes: true`** in the release workflow provides automatic changelogs from PR titles.
10. **Minimal `permissions`** on the release workflow's top-level scope (`contents: read`) with job-level escalation only where needed — correct least-privilege pattern.
