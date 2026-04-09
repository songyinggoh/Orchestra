# Orchestra Framework — Environment Limitations

An inventory of everything that can break or degrade when running Orchestra
outside a single-machine Linux dev environment with Python 3.12+ and direct
network access.

**Last verified:** 2026-04-09 (re-audited against current codebase)

---

## Categories

The limitations below fall into six groups:

| # | Category | Sections | Fixability |
|---|----------|----------|------------|
| A | **Language Boundary** — no abstraction lets non-Python code define or participate in workflows; only trigger and observe | §1 | Requires design work |
| B | **Broken Deployment Manifests** — config files contradict running code; k8s deployments fail out of the box | §13 | Immediately fixable (wrong values) |
| C | **Environment Assumptions** — hardcoded localhost addresses, relative cwd paths, assumed writable filesystem and internet access | §2, §3, §6, §7 | Fixable with env-var overrides + platformdirs |
| D | **Platform Portability** — no OS detection, no platform-specific code paths; Windows and Alpine containers both affected | §4, §5, §8, §16 | Fixable with platform checks |
| E | **Import Fragility** — optional dependencies crash the entire import chain even when the feature is not used | §12 | Partially fixed; remaining cases need lazy imports |
| F | **Distributed / Multi-Instance State** — in-process state breaks under multiple replicas; no shared state across instances | §14, §15 | Requires design work |

---

## 1. Non-Python Language Support

Non-Python clients can only **trigger pre-registered workflows** via the REST
API — they cannot author workflows, participate as agent nodes, or register for
A2A discovery.

| Capability | Status |
|------------|--------|
| REST API (trigger + observe) | Working — 14 endpoints, any HTTP client |
| TypeScript SDK | Thin read-only HTTP wrapper (`sdk/typescript/src/index.ts` — `startRun`, `streamRunEvents` only) |
| NATS messaging | Language-agnostic pub/sub bus |
| A2A state transfer (JWS) | Working (`interop/a2a.py:25–119`) |
| Declarative workflow spec (JSON/YAML) | Not implemented — no `POST /graphs`, no `WorkflowGraph.from_dict` |
| External agent workers | **Not implemented for non-Python clients** — `TaskConsumer` (`messaging/consumer.py`) exists in Python but requires mandatory DIDComm v2 decryption via `SecureNatsProvider`; non-Python workers receive encrypted ciphertext they cannot process without a DIDComm library |
| A2A discovery (`/.well-known/agent.json`) | Stub only — `DiscoveryService.get_agent_card()` returns `{}` (`interop/a2a.py:125–133`); no route mounted on server |
| TS graph-building DSL | Not implemented |

**Bottom line:** "Python defines, other languages consume" works. "Define
workflows or run agents in TypeScript/Go/Rust" does not. The NATS
`orchestra.tasks.*` subject space is language-agnostic at the transport level
but DIDComm encryption makes it Python-only in practice.

---

## 2. Storage & File System

- **Relative paths everywhere** — SQLite (`.orchestra/runs.db`), disk cache
  (`.orchestra/cache`), MCP config (`.orchestra/mcp.json`) all resolve relative
  to cwd. If the working directory changes (common in containers/k8s), the
  database becomes inaccessible. No XDG or `platformdirs` support.
- **Write permissions assumed** — breaks on read-only filesystems or
  locked-down container security contexts.
- **Disk cache locking** — `diskcache` relies on OS file locks, which can
  deadlock on NFS or SMB network drives.

---

## 3. Networking — Hardcoded Localhost Defaults

Most external services default to `localhost:<port>` with no environment
variable fallback. Exception: OTLP respects the standard `OTEL_EXPORTER_OTLP_ENDPOINT`.

| Service | Default | Source File | Env var? |
|---------|---------|-------------|----------|
| Ollama | `localhost:11434` | `providers/ollama.py:83` | No |
| NATS | `localhost:4222` | `messaging/client.py:27` | No — `ENV NATS_URL` in Dockerfile is vestigial; code never reads it |
| Redis | `localhost:6379` | `memory/backends.py:77` | No |
| Qdrant | `localhost:6333` | `memory/qdrant_backend.py:68` | No |
| OTLP | `localhost:4318` | `observability/_otel_setup.py:61` | **Yes** — reads `OTEL_EXPORTER_OTLP_ENDPOINT` |

Kubernetes, Docker Swarm, or any multi-host deployment requires overriding
every default manually. There is no service discovery.

---

## 4. Native / Compiled Dependencies

Three dependencies require platform-specific wheels or system libraries.
Import crashes at module level are now guarded with `try/except ImportError`,
but **wheel installation still fails on Alpine/musl** regardless:

| Dependency | Type | Import guard? | Platforms still affected |
|------------|------|---------------|--------------------------|
| `asyncpg` | PostgreSQL C extension | Fixed — guarded in `storage/postgres.py:41–48` | Alpine/musl, 32-bit, unsupported arches (install fails, not import crash) |
| `wasmtime` | Rust compiled binary | Fixed — guarded in `tools/wasm_runtime.py:54,111,168` | Alpine/musl, ARM32, RISC-V, MIPS (install fails) |
| `cryptography` | OpenSSL C bindings | Not directly imported; `joserfc` is used instead, but `joserfc` depends on `cryptography` | Legacy OpenSSL 1.0.2, FIPS-only systems |

Alpine Linux containers (common for minimal Docker images) will fail to
**install** `asyncpg` and `wasmtime` without `build-essential`, even though
the import crashes are now handled gracefully.

---

## 5. CLI Providers (claude / gemini / codex)

- Uses `shutil.which()` to locate CLIs on PATH — works cross-platform in
  theory, but the CLIs themselves may not be installed or may behave
  differently on Windows vs Unix.
- All use `asyncio.create_subprocess_exec()` — functional on Windows but
  subprocess piping edge cases exist.
- **Windows CI matrix exists** (`.github/workflows/ci.yml:74`: `os: [ubuntu-latest, windows-latest, macos-latest]`) but covers unit tests with mocked subprocess — real CLI subprocess behavior on Windows remains untested at integration level.
- `PATHEXT` awareness (`.cmd`, `.exe`, `.ps1` shims) is not explicitly handled.

---

## 6. Air-Gapped / Restricted Networks

- **`model2vec`** downloads 100+ MB embedding models from HuggingFace on first
  use. No offline mode, no bundled fallback. Air-gapped deployments cannot use
  the memory/embedding features.
- **`pgvector`** extension requires superuser to `CREATE EXTENSION` — many
  managed PostgreSQL services (RDS, Cloud SQL) restrict this.

---

## 7. Container & Kubernetes

- Dockerfile is `python:3.12-slim` (Debian) only — no Alpine variant provided.
- Helm chart assumes gVisor/Kata runtime and KEDA operator are pre-installed.
- **NATS stream auto-provisioning: fixed** — `create_nats_client()` in
  `messaging/client.py:90` calls `_ensure_stream()` which idempotently creates
  or updates `ORCHESTRA_TASKS` on first connect.
- **KEDA stream name: partially fixed** — Helm template
  (`deploy/helm/orchestra/templates/keda-scaledobject.yaml:37`) correctly
  references `ORCHESTRA_TASKS`, but the kustomize base manifest
  (`deploy/base/orchestra-agent.yaml:41`) still references the old name
  `"agent-tasks"` — autoscaling fails for kustomize-based deployments.
- GitLab CI hardcodes Docker service names (`postgres`, `redis`, `nats`).
- Relative `.orchestra/` paths break when cwd differs from expectation in
  container entrypoints.

---

## 8. Windows-Specific

- **`os.path.expandvars()` with `$VAR` syntax** — not found in current
  `core/` or `cli/` source; may have been removed or was never present.
  Verify before assuming resolved.
- **`stdin_payload.encode()` uses locale encoding** (`providers/claude_code.py:111`,
  `providers/gemini_cli.py:108`) — on Windows with a non-UTF-8 code page
  (cp1252, cp936), non-ASCII prompt content is mis-encoded. Should use
  `.encode("utf-8")` explicitly.
- No `platform.system()` or `os.name` checks anywhere in the codebase —
  Windows behavior is untested at integration level.
- Terminal color output (`structlog.dev.ConsoleRenderer`) may not render in
  PowerShell without configuration.

---

## 9. Crypto & Identity

- EdDSA signing requires OpenSSL 1.1.1+ — legacy systems or FIPS-only
  configurations may not support it.
- `joserfc` is pure Python but depends on `cryptography` for key operations.
- **`identity/ucan.py:16–18` imports `joserfc` at module level without guard** —
  importing anything that depends on `ucan.py` fails if `joserfc` is not
  installed.
- DIDComm v2 encryption requires `joserfc`, `base58`, and `cryptography` — all
  must be importable at runtime for secure messaging to work.

---

## 10. Observability

- OTLP exporter silently drops traces if the collector at the configured
  endpoint is unreachable — no error, no warning. (`OTEL_EXPORTER_OTLP_ENDPOINT`
  is respected; the silent-drop behavior applies regardless of which endpoint
  is configured.)
- Prometheus exporter and Collector configuration were deferred (not
  implemented).

---

## 11. Python Version & Asyncio Compatibility

- **`asyncio.TimeoutError` vs `TimeoutError` (Python 3.10)** — CLI providers
  (`claude_code.py:120`, `gemini_cli.py:117`) catch builtin `TimeoutError`.
  On Python 3.10, `asyncio.wait_for` raises `asyncio.TimeoutError` (a subclass
  of `concurrent.futures.TimeoutError`), which does **not** match the builtin
  `TimeoutError`. Timeouts propagate as unhandled exceptions.
- **`asyncio.run()` inside existing event loop** — `run_sync()` in
  `core/runner.py:118` calls `asyncio.run()`, which raises
  `RuntimeError: This event loop is already running` inside Jupyter
  notebooks, pytest-asyncio, FastAPI route handlers, or any async host.
- **`asyncio.ensure_future` deprecated in 3.12** —
  `storage/sqlite.py:455` (`SnapshotManager.on_event`) calls
  `asyncio.ensure_future()` from a sync callback without checking for
  a running loop. Deprecated in 3.12; fails with `RuntimeError` from
  non-event-loop threads.
- **`asyncio.get_event_loop()` deprecated in 3.10+** —
  `reliability/selfcheck.py:230` and `reliability/factscore.py:191` use
  the deprecated form instead of `asyncio.get_running_loop()`.

---

## 12. Import Chain Fragility

Importing the top-level package or its submodules may crash if optional
dependencies are missing.

| Import | Crashes Without | Root Cause | Status |
|--------|----------------|------------|--------|
| `import orchestra` | `rebuff` | `__init__.py:35` unconditionally re-exports `InjectionAuditorAgent` from `orchestra.security`; `security/__init__.py:63–74` guards the import with `try/except ImportError: pass` but the re-export from the top-level fails when the name is absent from the namespace | **Partial fix** — guard in `security/__init__.py` but top-level re-export still crashes |
| `import orchestra.memory` | `numpy` | `memory/__init__.py:3` eagerly imports `EmbeddingProvider` from `embeddings.py:8` which does `import numpy as np` at module level | Not fixed |
| `from orchestra.routing import CostAwareRouter` | `numpy` | `routing/router.py:13` does `import numpy as np` at module level | Not fixed |
| `from orchestra.providers.failover import ...` | `numpy` | `failover.py:186` imports `numpy` inside `get_provider_health()` without guard | Not fixed |
| `from orchestra.security.guard import ...` | `joserfc` | `guard.py` → `attenuation.py` → `identity/ucan.py:16–18` imports `joserfc` at module level | Not fixed |
| `from orchestra.storage.postgres import ...` | `asyncpg` | Previously module-level; now guarded with `try/except ImportError` in `storage/postgres.py:41–48` | **Fixed** |
| Hot-reload modules | `watchfiles` | `core/hotreload.py:59`, `discovery/hotreload.py:105` import at module level; not declared in `pyproject.toml` (relies on transitive dep from `uvicorn[standard]`) | Not fixed |

**Bottom line:** Several optional imports still crash the import chain. Every
optional import must be lazy-loaded behind `try/except ImportError`.

---

## 13. Deployment Manifest Mismatches

| Mismatch | Manifest Value | Code Value | Impact | Status |
|----------|---------------|------------|--------|--------|
| Health probe paths | `deploy/helm/orchestra/values.yaml:48,52` → `/health`, `/ready` | `server/routes/health.py:12,18` → `/healthz`, `/readyz` | Pods CrashLoopBackOff — probes always fail | **Still broken** |
| Container port | `deploy/helm/orchestra/templates/deployment.yaml:34` → `containerPort: 8000` | Dockerfile `EXPOSE 8080`; `CMD [..., "--port", "8080"]` | Service unreachable in any Helm deployment | **Still broken** |
| KEDA stream name (Helm) | `deploy/helm/orchestra/templates/keda-scaledobject.yaml:37` → `ORCHESTRA_TASKS` | Code creates `ORCHESTRA_TASKS` | Match — autoscaling works for Helm deployments | **Fixed** |
| KEDA stream name (kustomize base) | `deploy/base/orchestra-agent.yaml:41` → `agent-tasks` | Code creates `ORCHESTRA_TASKS` | Autoscaling never triggers for kustomize-based deployments | **Still broken** |

---

## 14. Multi-Instance / HA Deployment State

All in-process state is lost when running multiple instances behind a load
balancer or across Kubernetes replicas:

- **Rate limiter** (`security/rate_limit.py:54`) — `TokenBucket` stores state in
  a per-process dict. With N replicas, effective rate limit is N × configured
  limit.
- **Circuit breaker** (`security/circuit_breaker.py:76–79`) — Each replica trips
  independently. N replicas means N simultaneous HALF_OPEN probes hitting the
  failing provider instead of one.
- **Revocation list** (`identity/`) — In-memory only, no persistence or
  cross-replica replication. Revoking a UCAN on one instance has no effect on
  others.
- **Tool ACL** (`core/agent.py:308`) — Lazy-initialized via
  `object.__setattr__()` bypass of Pydantic's frozen model. Not async-safe:
  two concurrent `_execute_tool` calls can race on `self.acl`.

---

## 15. Cross-Module Integration Issues

- **Provider error type erasure** — `compiled.py:696–711` wraps all provider
  exceptions in `AgentError`, erasing the original type.
  `ProviderFailover.classify_error()` uses `isinstance()` checks that fail
  because the original `RateLimitError` / `ProviderUnavailableError` is gone.
  Retryable timeouts are treated as terminal failures.
- **CLI subprocess orphaning** — When `asyncio.wait_for` fires or a parallel
  branch is cancelled, the child `claude`/`gemini`/`codex` process is
  abandoned. No `proc.kill()` or `await proc.wait()`. Server processes
  accumulate zombies until `Too many open files`.
- **DIDComm key rotation breaks consumers** — `SecureNatsProvider._rotate_keys_if_needed()`
  (`secure_provider.py:392–453`) replaces `own_did` and clears the recipient
  cache. Consumers that cached the old publisher DID cannot encrypt replies to
  the new DID. No announcement mechanism exists. Replies fail with
  `ValueError`.
- **`state.model_dump()` without JSON mode** — `compiled.py` lines 500, 533,
  572, 634 call `model_dump()` (not `model_dump(mode="json")`). If state
  contains `datetime`, `set`, `bytes`, or custom objects, `json.dumps()` in
  the SQLite store raises `TypeError`. The error is caught by a bare
  `except Exception: pass` at line 663, leaving run status stuck as
  "running" forever.
- **`ORCHESTRA_API_KEY` dual meaning** — `server/app.py:58` reads it as the
  server authentication key. `providers/__init__.py:32` reads it as the LLM
  endpoint API key. When `auto_provider()` runs inside the server, it
  selects `HttpProvider` instead of the intended CLI provider.
- **Redis warm tier silent data loss** — `RedisMemoryBackend` methods catch
  `except Exception` and return `None` / swallow errors. Data that should
  persist in the warm tier is silently dropped. No warning emitted.
- **NATS requires full crypto stack** — `SecureNatsProvider.create()` requires
  `joserfc`, `cryptography`, `base58`, and `peerdid`. No plaintext mode
  exists for development or trusted environments.
- **Memory type degradation** — `memory/serialization.py` msgpack hooks
  silently return raw dicts instead of Pydantic model instances when the type
  is not in the static `SERIALIZATION_REGISTRY`.
- **`auto_provider()` blocks event loop** — `providers/__init__.py:66–74`
  does a synchronous `socket.create_connection()` to probe Ollama. Blocks
  the event loop for up to 1 second in server contexts.

---

## 16. Additional CLI / Server Issues

- **`stdin_payload.encode()` uses locale encoding** (`claude_code.py:111`,
  `gemini_cli.py:108`) — On Windows with a non-UTF-8 code page (cp1252,
  cp936), non-ASCII prompt content is mis-encoded. Should use
  `.encode("utf-8")` explicitly.
- **`CodexCliProvider` passes prompt as CLI argument** (`codex_cli.py:95–103`)
  — Unlike the other two providers which use stdin, Codex passes `full_prompt`
  as a positional argv. Linux `ARG_MAX` is 2 MB, macOS 256 KB, Windows
  32,767 chars. Long prompts raise `OSError: Argument list too long`.
- **`cors_origins=[]` silently disables CORS** (`server/config.py:20`) — When
  `CORSMiddleware` receives `allow_origins=[]`, no CORS headers are emitted.
  Browser clients (including the built-in React UI) fail silently.
- **`watchfiles.awatch` fails silently in gVisor/rootless Podman**
  (`core/hotreload.py:59`, `discovery/hotreload.py:105`) — gVisor's `runsc`
  kernel does not implement `inotify`. Hot-reload stops without crashing.
- **`/readyz` returns 200 with zero workflows** — No workflow registration
  check in the readiness probe.
- **PromptShield downloads 500 MB model on first request**
  (`security/guardrails.py:133–143`) — Blocks for 30–120s. Read-only
  container filesystems raise `OSError`. Air-gapped environments get a
  single-string mock detector silently.
- **VectorStore hardcodes `VECTOR(256)` dimension** — Embedding models with
  different dimensions require DDL changes.
- **Wasm ticker thread uses `daemon=False`** — Prevents clean process exit
  when the sandbox is not explicitly stopped.
- **MCP requires Node.js at runtime** — MCP stdio transport spawns `npx` or
  `node` commands. No check for Node.js availability. Failure message is
  opaque.
- **`structlog` `colors=True` hardcoded** — Garbled ANSI escape sequences
  in non-TTY environments (CI logs, piped output, Windows CMD).
- **No state size limit in parallel fan-out** — `compiled.py:954–986` creates
  N shallow copies of the full state dict. With 10 MB state and 10 branches,
  memory consumption is O(N × state_size × 2).
- **Double trace renderer registration** — `compiled.py` creates
  `RichTraceRenderer` at lines 176–179 and again at 422–426. Each event
  is rendered twice to the console.

---

## Summary Table

| Component | Issue | Severity | Environments Affected | Status |
|-----------|-------|----------|-----------------------|--------|
| `import orchestra` | Crashes without `rebuff` (top-level re-export unguarded) | **CRITICAL** | Any env without `rebuff` | Partial fix |
| `import orchestra.memory` | Crashes without `numpy` installed | **CRITICAL** | Any env without `numpy` | Not fixed |
| Helm probes | `/health` vs `/healthz` path mismatch → CrashLoopBackOff | **CRITICAL** | All Helm/k8s deployments | Not fixed |
| Helm port | `containerPort: 8000` vs code runs on `8080` → service unreachable | **CRITICAL** | All Helm deployments | Not fixed |
| KEDA stream (Helm) | `ORCHESTRA_TASKS` now matches code | — | Helm deployments | **Fixed** |
| KEDA stream (kustomize base) | `agent-tasks` vs `ORCHESTRA_TASKS` → no autoscale | **CRITICAL** | kustomize-based k8s | Not fixed |
| CLI Providers | `TimeoutError` catch misses `asyncio.TimeoutError` on 3.10 | HIGH | Python 3.10 |Not fixed |
| CLI Providers | Subprocess orphaned on timeout — no `proc.kill()` | HIGH | Long-running server processes | Not fixed |
| CLI Providers | CodexCli passes prompt as argv — hits ARG_MAX | HIGH | Long prompts on macOS/Windows | Not fixed |
| CLI Providers | Windows CI unit matrix exists; integration behavior untested | MEDIUM | Windows subprocess edge cases | Partial |
| `ORCHESTRA_API_KEY` | Dual meaning: server auth key AND provider API key | HIGH | Server with `auto_provider()` | Not fixed |
| `state.model_dump()` | No `mode="json"` → persistence crash → run stuck "running" | HIGH | Any state with datetime/set/bytes | Not fixed |
| Provider failover | Error type erasure: `AgentError` wrapping loses classify info | HIGH | Multi-provider failover setups | Not fixed |
| DIDComm key rotation | Consumer DID cache invalidated → replies fail | HIGH | Long-running NATS deployments | Not fixed |
| External agent workers | Non-Python workers blocked by mandatory DIDComm decryption | HIGH | Non-Python clients | Not fixed |
| Rate limiter | Per-process dict; N replicas = N × limit | HIGH | Multi-instance / k8s | Not fixed |
| Circuit breaker | Per-process state; N replicas = N HALF_OPEN probes | HIGH | Multi-instance / k8s | Not fixed |
| `asyncio.run()` | Fails inside existing event loop (Jupyter, pytest-asyncio) | HIGH | Notebooks, async hosts | Not fixed |
| SQLite / DiskCache | Relative `.orchestra/` path breaks on cwd change | HIGH | Containers, k8s | Not fixed |
| asyncpg | C extension; needs build tools on Alpine (import crash fixed) | HIGH | Alpine, musl, 32-bit | Partial fix |
| asyncpg import | Module-level import crash: now guarded | — | Minimal installs | **Fixed** |
| wasmtime | Native binary; no musl wheels (import crash fixed) | HIGH | Alpine, ARM32 | Partial fix |
| wasmtime import | Module-level import crash: now guarded | — | Minimal installs | **Fixed** |
| Localhost hardcoding | Ollama/NATS/Redis/Qdrant unreachable in multi-host | HIGH | k8s, Docker Swarm, cloud | Not fixed |
| NATS_URL in Dockerfile | `ENV NATS_URL` set but never read by `NATSClientConfig` | HIGH | Any containerised deployment | Not fixed |
| NATS auto-provisioning | `_ensure_stream()` auto-creates on connect | — | k8s, first-run | **Fixed** |
| NATS / Redis / Qdrant | Hardcoded ports, no service discovery | HIGH | Multi-host deployments | Not fixed |
| NATS messaging | Requires full crypto stack; no plaintext dev mode | MEDIUM | Dev/test environments | Not fixed |
| Redis memory tier | Silent data loss when Redis unreachable | MEDIUM | Intermittent connectivity | Not fixed |
| Memory serialization | Custom Pydantic models silently returned as raw dicts | MEDIUM | Redis-backed memory | Not fixed |
| `routing/router.py` | Module-level `import numpy` with no guard | MEDIUM | Minimal installs | Not fixed |
| `security/guard.py` | Import chain requires `joserfc` via `ucan.py:16–18` | MEDIUM | Installs without crypto extras | Not fixed |
| Revocation list | In-memory only; no persistence or replication | MEDIUM | Multi-instance / restarts | Not fixed |
| Tool ACL | Lazy `object.__setattr__` not async-safe; race condition | MEDIUM | Concurrent agent usage | Not fixed |
| CORS config | `cors_origins=[]` silently disables CORS — no warning | MEDIUM | Browser clients, React UI | Not fixed |
| PromptShield | Downloads 500 MB model on first request | MEDIUM | Air-gapped, read-only containers | Not fixed |
| VectorStore DDL | Hardcodes `VECTOR(256)` dimension | MEDIUM | Different embedding models | Not fixed |
| `watchfiles` | Required at import time; not in `pyproject.toml`; fails silently in gVisor | MEDIUM | gVisor, rootless Podman | Not fixed |
| MCP runtime | Requires Node.js (`npx`/`node`) at runtime; opaque errors | MEDIUM | Non-Node.js environments | Not fixed |
| pgvector | Needs superuser, unavailable on managed DBs | MEDIUM | RDS, Cloud SQL | Not fixed |
| Model downloads | HuggingFace, 100+ MB, no offline mode | MEDIUM | Air-gapped networks | Not fixed |
| File permissions | Assumes writable `.orchestra/` and `~/.cache/` | MEDIUM | Read-only FS, strict containers | Not fixed |
| Helm / k8s manifests | gVisor runtime, KEDA dependency | MEDIUM | Clusters without gVisor | Not fixed |
| EdDSA crypto | Requires OpenSSL 1.1.1+ via `joserfc` + `cryptography` | MEDIUM | Legacy / FIPS-only systems | Not fixed |
| Parallel fan-out | No state size limit; O(N × size) memory copies | MEDIUM | Large state + many branches | Not fixed |
| `stdin_payload.encode()` | Uses locale encoding, not UTF-8 | MEDIUM | Windows non-UTF-8 code pages | Not fixed |
| `auto_provider()` | Sync socket probe blocks event loop for 1s | LOW | Server contexts | Not fixed |
| `asyncio.ensure_future` | Deprecated in 3.12; no loop check in sync callback | LOW | Python 3.12+ | Not fixed |
| `asyncio.get_event_loop()` | Deprecated in 3.10+ | LOW | Python 3.10+ | Not fixed |
| `/readyz` probe | Returns 200 with zero workflows registered | LOW | k8s readiness checks | Not fixed |
| Trace renderer | Double registration → duplicate console output | LOW | `ORCHESTRA_TRACE=1` | Not fixed |
| `structlog` colors | Hardcoded `colors=True` — garbled in non-TTY | LOW | CI/CD, piped output | Not fixed |
| Wasm ticker thread | `daemon=False` prevents clean process exit | LOW | Sandbox without explicit stop | Not fixed |
| Terminal colors | May not render on Windows or non-TTY | LOW | CI/CD, PowerShell | Not fixed |
| Disk cache locking | Deadlock risk on network drives | LOW | NFS, SMB mounts | Not fixed |
