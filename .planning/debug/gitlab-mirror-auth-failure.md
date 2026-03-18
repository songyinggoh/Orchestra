---
status: diagnosed
trigger: "GitLab mirror workflow fails with HTTP Basic: Access denied after URL-encoding fix"
created: 2026-03-11T00:00:00Z
updated: 2026-03-11T00:00:00Z
---

## Current Focus

hypothesis: Multiple possible causes ranked by likelihood — see Evidence and Resolution
test: User must verify token configuration against checklist
expecting: One of the identified causes resolves the issue
next_action: User follows diagnostic checklist

## Symptoms

expected: git push to GitLab mirror succeeds
actual: "HTTP Basic: Access denied" — GitLab rejects the credentials
errors: "remote: HTTP Basic: Access denied. If a password was provided for Git authentication, the password was incorrect or you're required to use a token instead of a password."
reproduction: Any push to GitHub triggers the mirror workflow, which fails at git push
started: After fixing URL-encoding issues (errors 1 and 2 resolved, error 3 is current)

## Eliminated

- hypothesis: Newline in PAT breaking URL
  evidence: Fixed with tr -d, error changed from "url contains newline" to new error
  timestamp: prior session

- hypothesis: Special chars in PAT breaking URL parsing
  evidence: Fixed with python3 URL-encoding, error changed from "port number" to auth failure
  timestamp: prior session

- hypothesis: Wrong username for personal access tokens
  evidence: GitLab docs confirm "oauth2" works as username for PATs; any non-blank username works for PATs
  timestamp: current session

- hypothesis: Workflow syntax error
  evidence: YAML is valid, env var passing is correct, git remote add syntax is correct
  timestamp: current session

## Evidence

- timestamp: current session
  checked: GitLab docs on PAT authentication usernames
  found: For personal access tokens, ANY non-blank username works (including "oauth2"). For PROJECT access tokens, the username MUST be "git". The workflow uses "oauth2" which is fine for PATs but WRONG for project access tokens.
  implication: If the secret contains a PROJECT access token (not a personal one), "oauth2" username would cause Access Denied.

- timestamp: current session
  checked: GitLab docs on required token scopes for git push
  found: write_repository scope is REQUIRED for git push. The api scope also grants this implicitly. read_repository alone is NOT sufficient.
  implication: If token was created with only read_repository (or other scopes but not write_repository/api), push will be denied.

- timestamp: current session
  checked: GitLab docs and forums on token expiration
  found: PATs have configurable expiration dates. Expired tokens return "HTTP Basic: Access denied" — the SAME error message, with no indication the token expired.
  implication: Token may have expired since creation.

- timestamp: current session
  checked: URL-encoding behavior of python3 urllib.parse.quote
  found: urllib.parse.quote with safe='' encodes ALL special characters including hyphens, underscores, dots, and tildes. GitLab PATs typically use glpat-XXXX format (alphanumeric + hyphens). Encoding hyphens to %2D should still work, but there is a risk: if the GitHub secret itself was stored already-encoded, the workflow would DOUBLE-encode it.
  implication: Double-encoding is possible if the secret value was pasted with percent-encoded characters.

- timestamp: current session
  checked: GitLab target repository existence requirement
  found: git push to a non-existent GitLab project via HTTPS will also fail with authentication errors (not a 404 as you might expect).
  implication: If the GitLab repo does not exist at the exact path, this error appears.

- timestamp: current session
  checked: GitLab forum threads on the exact error message
  found: The most common causes in order: (1) token expired/revoked, (2) wrong scopes, (3) wrong token type + username combo, (4) repo doesn't exist, (5) 2FA enforcement changes
  implication: Ranked likelihood for investigation

## Resolution

root_cause: Cannot determine single root cause without access to GitLab account — this is a token/account configuration issue, not a code issue. The workflow syntax is correct. The five most likely causes are documented in Evidence with a diagnostic checklist.
fix: User must verify and potentially regenerate their GitLab PAT (see checklist below)
verification: Workflow succeeds on next push
files_changed: []
