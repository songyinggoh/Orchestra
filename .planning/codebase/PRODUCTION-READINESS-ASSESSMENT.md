# Production Readiness Assessment

**Analysis Date:** 2026-03-16
**Verdict:** NOT PRODUCTION-READY. Significant gaps in dependency pinning, server hardening, configuration management, and operational infrastructure. The core orchestration engine is well-architected but the deployment story is incomplete.

---

## 1. Dependency Maturity

**File:** `pyproject.toml`

### Version Pinning: FAIL

Every dependency uses floor-version pins (`>=X.Y`) with no upper bounds or lock file. This means `pip install` on two different days can produce completely different dependency trees.

**Core dependencies (unpinned):**
- `pydantic>=2.5` -- could pull 2.5 or 3.x (if/when released)
- `httpx>=0.26` -- could pull any future breaking version
- `structlog>=24.0` -- no ceiling
- `mcp>=1.26,<2` -- only one with an upper bound

**Optional dependencies (unpinned):**
- `wasmtime>=23.0` -- no ceiling
- `redis[hiredis]>=7.0` -- no ceiling
- `nats-py>=2.14` -- no ceiling
- `ray[serve]>=2.10` -- pulls 500MB+ of deps with no ceiling

**Pre-release / alpha dependencies:**
- `opentelemetry-semantic-conventions>=0.45b0` -- explicitly allows beta releases. The `0.45b0` suffix is a beta marker.

**Lock file: MISSING**

No `requirements.txt`, `poetry.lock`, `uv.lock`, or `Pipfile.lock` exists. Builds are non-reproducible.

**Impact:** A deployment today and a deployment next week could have entirely different dependency versions, making bug reproduction impossible and introducing silent regressions.

**Fix approach:**
1. Add `uv.lock` or `pip-compile` output committed to the repo
2. Add upper bound pins (e.g., `pydantic>=2.5,<3`) for all dependencies
3. Pin the OTel semantic conventions to a stable release when available

---

## 2. Entry Points & Server Startup

### CLI Entry Point

**File:** `src/orchestra/cli/main.py`

The `orchestra` CLI is registered in `pyproject.toml` under `[project.scripts]`. The `serve` command starts uvicorn:

```python
uvicorn.run(app_instance, host=host, port=port, reload=reload)
```

**Problems:**
- No worker count configuration (defaults to 1 worker)
- No access log configuration
- No SSL/TLS configuration
- `reload=True` option exposed but not guarded against production use
- No `--workers` flag for multi-process deployment

### Dockerfile

**File:** `Dockerfile`

```dockerfile
ENTRYPOINT ["orchestra"]
CMD ["run"]
```

**Problems:**
- Entry point is `orchestra run`, not `orchestra serve`. The `run` command expects a workflow file argument that is not provided. **The Dockerfile will fail on startup.**
- No health check instruction (`HEALTHCHECK`)
- No non-root user (runs as root)
- `build-essential` left installed (increases attack surface and image size)
- Installs `ray[serve]` which adds ~500MB to the image
- No `.dockerignore` file found to exclude `.git/`, `tests/`, `.planning/`

### serve_wrapper.py

**File:** `serve_wrapper.py`

```python
config = ServerConfig(host="127.0.0.1", port=8000)
app = create_app(config)
```

**Problem:** Hardcodes `127.0.0.1` which means it only listens on localhost -- unreachable from outside a container. The Dockerfile sets `ORCHESTRA_PORT=8080` but `serve_wrapper.py` ignores it and uses `8000`.

### Verdict: Cannot start in production

The Dockerfile entry point is broken. The serve_wrapper binds to localhost only. There is no production-grade ASGI runner configuration (gunicorn + uvicorn workers, process management).

---

## 3. Configuration Management

### Environment Variables

**No centralized env var handling.** Each module reads its own env vars independently:

| Module | Env Var | Default | Problem |
|--------|---------|---------|---------|
| `src/orchestra/providers/http.py` | `OPENAI_API_KEY` | `""` (empty string) | Silently sends requests with no auth |
| `src/orchestra/providers/anthropic.py` | `ANTHROPIC_API_KEY` | `""` (empty string) | Same -- no fail-fast |
| `src/orchestra/providers/google.py` | `GOOGLE_API_KEY` | `""` (empty string) | Same |
| `src/orchestra/core/compiled.py` | `ORCHESTRA_ENV` | `"dev"` | Defaults to dev mode in production |
| `src/orchestra/core/compiled.py` | `ORCHESTRA_TRACE` | derived from ENV | Rich trace renderer enabled by default |
| `src/orchestra/storage/sqlite.py` | `ORCHESTRA_DB_PATH` | `.orchestra/runs.db` | Relative path, may not exist in container |
| `src/orchestra/storage/postgres.py` | `DATABASE_URL` | `None` | No validation |
| `src/orchestra/observability/_otel_setup.py` | `OTEL_EXPORTER_OTLP_ENDPOINT` | `None` | Standard OTel, fine |

**Critical issue:** `ORCHESTRA_ENV` defaults to `"dev"`, which enables the Rich trace renderer in production. This writes formatted terminal output to stdout on every workflow event and adds overhead.

**No startup validation.** There is no code that checks required env vars at startup and fails fast with a clear message. A misconfigured deployment will accept requests and fail at runtime.

### CORS Configuration

**File:** `src/orchestra/server/config.py`

```python
cors_origins: list[str] = Field(default_factory=lambda: ["*"])
```

CORS defaults to `allow_origins=["*"]` with `allow_credentials=True`. This is a security vulnerability -- it allows any origin to make credentialed requests.

### ServerConfig

**File:** `src/orchestra/server/config.py`

`ServerConfig` is a plain `BaseModel`, not `pydantic-settings.BaseSettings`. It does not read from environment variables. Configuration must be passed programmatically or hardcoded. There is no way to configure the server via env vars without writing custom code.

---

## 4. Error Handling Audit

### `src/orchestra/core/compiled.py` -- CompiledGraph._run_loop

**Adequate.** The main execution loop wraps the entire execution in `try/except Exception` (line 582), emits `ErrorOccurred` and `ExecutionCompleted(status="failed")` events, and re-raises. This is the correct pattern for an orchestration engine.

**Minor issues:**
- Lines 621, 656, 769, 801: Bare `except Exception: pass` blocks that silently swallow errors during `update_run_status()` and guardrail event emission. These should at least log.
- Line 176/419: Trace renderer setup duplicated between `run()` and `_run_loop()`. The `run()` path subscribes a renderer, then `_run_loop()` subscribes a SECOND one, doubling output.

### `src/orchestra/core/agent.py` -- BaseAgent.run

**Adequate.** Tool execution errors are caught and returned as `ToolResult.error` (line 339). `MaxIterationsError` is raised with partial output. No unhandled exception paths.

**Minor issue:** Line 225 -- structured output validation failure is logged as warning and silently returns `None` for `structured_output`. In production, this should be configurable (fail vs. warn).

### `src/orchestra/providers/failover.py` -- ProviderFailover

**Adequate.** Error classification is well-designed with `TERMINAL`, `RETRYABLE`, and `MODEL_MISMATCH` categories. Terminal errors are re-raised immediately. Circuit breakers protect each provider.

**Issue:** Line 175 -- `get_provider_health()` imports `numpy` at call time. If the `routing` optional dependency is not installed, this will raise `ImportError` at runtime when checking health. Should degrade gracefully.

### Broad `except Exception` Usage Across Codebase

Found 60+ instances of `except Exception` across the `src/orchestra/` tree. Most are in optional feature loading (acceptable) or event emission (should log). Key problematic files:

- `src/orchestra/memory/backends.py` -- 5 bare `except Exception as e` blocks in Redis backend operations. All re-raise as custom exceptions, which is acceptable.
- `src/orchestra/observability/console.py` -- 3 bare `except Exception` that silently suppress rendering failures. Fine for observability, but should log.
- `src/orchestra/tools/mcp.py` -- 7 `except Exception` blocks, some silently swallowing MCP connection failures.
- `src/orchestra/identity/agent_identity.py` -- 3 `except Exception` blocks that return `False` on verification failures. This could mask real bugs in signature verification.

---

## 5. Missing Infrastructure

### Signal Handling: ABSENT

No SIGTERM/SIGINT handler anywhere in the codebase. The `uvicorn.run()` call in the CLI relies on uvicorn's default signal handling, which does not:
- Drain in-flight workflow executions
- Flush event stores
- Close NATS/Redis connections

A `docker stop` or Kubernetes pod termination will kill running workflows mid-execution with no checkpoint.

### Graceful Shutdown: PARTIAL

**File:** `src/orchestra/server/app.py`

The lifespan handler cancels running tasks on shutdown:

```python
for run_status in await run_manager.list_runs():
    active = run_manager.get_run(run_status.run_id)
    if active and not active.task.done():
        active.task.cancel()
```

This is cancellation, not graceful shutdown. Tasks are killed, not drained. There is no grace period or checkpoint-before-cancel logic.

### Health Checks: PRESENT BUT BASIC

**File:** `src/orchestra/server/routes/health.py`

- `/healthz` -- liveness probe, always returns 200. Correct.
- `/readyz` -- checks event store accessibility. Correct.

**Missing:**
- No deep health check that verifies LLM provider connectivity
- No health check for NATS/Redis connections
- No startup probe for slow-loading models (PromptShield ONNX model)

### Logging Configuration: NOT AUTO-INVOKED

**File:** `src/orchestra/observability/logging.py`

A well-designed `setup_logging()` function exists with JSON output mode, OTel trace correlation, and structlog integration. However, it is never called automatically. Neither the server startup nor the CLI invoke it. The framework uses `structlog.get_logger()` throughout, which works without configuration but produces unstructured output.

Mixed logging approaches:
- Most modules: `structlog.get_logger()` -- good
- `src/orchestra/memory/tiers.py`: `logging.getLogger()` -- stdlib, inconsistent
- `src/orchestra/tools/mcp.py`: `logging.getLogger()` -- stdlib, inconsistent
- `src/orchestra/observability/tracing.py`: `logging.getLogger()` -- stdlib, inconsistent

### Rate Limiting: ABSENT ON SERVER

The `TokenBucket` rate limiter exists in `src/orchestra/security/rate_limit.py` but is not applied to any HTTP endpoint. The server has no request rate limiting, no concurrent run limits, and no input size validation beyond Pydantic schema checking.

### Request Size Limits: ABSENT

No `max_content_length` or request body size limit on the FastAPI app. A malicious client can send arbitrarily large JSON payloads.

### Authentication: ABSENT

The HTTP server has no authentication middleware. Anyone who can reach the endpoint can create and manage workflow runs.

---

## 6. Test Reality

### Unit Test Count

51 test files found in `tests/unit/`. Prior documentation claims 244 tests passing. Tests were difficult to run in the assessment environment (timeout issues), but collection identified the test files.

### Test File Inventory (51 files):

Core engine tests: `test_core.py`, `test_events.py`, `test_handoff.py`, `test_hitl.py`, `test_timetravel.py`
Provider tests: `test_providers.py`, `test_provider_failover.py`
Security tests: `test_acl.py`, `test_rebuff.py`, `test_guardrails.py`, `test_guardrails_integration.py`, `test_circuit_breaker.py`, `test_rate_limiter.py`, `test_wasm_sandbox.py`, `test_e2e_encryption.py`, `test_attenuation.py`, `test_injection_attenuation.py`, `test_promptshield.py`
Identity tests: `test_agent_identity.py`, `test_ucan.py`, `test_ucan_acl_integration.py`, `test_ucan_ttls.py`, `test_signed_discovery.py`, `test_jcs.py`
Memory tests: `test_memory.py`, `test_memory_backends.py`, `test_memory_tiers_full.py`, `test_memory_serialization.py`, `test_tiered_memory.py`, `test_singleflight.py`, `test_invalidation.py`, `test_compression.py`, `test_dedup.py`, `test_cold_tier_backend.py`, `test_redis_memory_backend.py`, `test_slru_policy.py`, `test_vector_store.py`
Cost tests: `test_cost.py`, `test_cost_router.py`, `test_persistent_budget.py`
Observability tests: `test_trace.py`, `test_otel_tracing.py`, `test_otel_metrics.py`
Storage tests: `test_sqlite_store.py`, `test_postgres_store.py`
Other: `test_mcp.py`, `test_cache.py`, `test_context_concurrency.py`, `test_phase2_race_conditions.py`, `test_zkp_commitments.py`

### Integration Tests Requiring External Services

**File:** `tests/integration/test_secure_nats.py`
- **Requires:** NATS server on `localhost:4222`
- Marked with `@pytest.mark.integration`

**File:** `tests/integration/test_redis_tiered_memory.py`
- **Requires:** Redis server on `localhost:6379`
- Uses `pytest.skip` if Redis is unavailable

**Other integration tests:** `test_fastapi_endpoints.py`, `test_sse_streaming.py`, `test_concurrency.py`, `test_full_stack.py` -- these may use mock providers and work without external services.

### Load Tests

**File:** `load_tests/locustfile.py`
- Exists but assumes `test-graph` is pre-registered on the server
- No automated setup -- manual process

### Test Gaps

- No tests for the `serve` CLI command or server startup
- No tests for the Dockerfile
- No tests for graceful shutdown behavior
- No tests for concurrent request handling at the HTTP layer
- No chaos/failure injection tests
- No test for what happens when env vars are missing

---

## 7. Production Event Store

### InMemoryEventStore in Production Server

**File:** `src/orchestra/server/app.py`, line 38

```python
app.state.event_store = InMemoryEventStore()
```

The server uses `InMemoryEventStore` which is explicitly documented as "Not suitable for production use" (`src/orchestra/storage/store.py`, line 125). All workflow run history is lost on server restart.

The `SQLiteEventStore` is available but not wired into the server. There is no configuration to switch event store backends.

---

## 8. Security Posture

### API Key Handling

Providers silently accept empty API keys and fail at request time:

```python
# src/orchestra/providers/http.py:99
self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
```

No warning, no validation. The provider will happily construct requests with an empty `Authorization` header and fail with a cryptic 401 from OpenAI.

### Secret Storage

**File:** `src/orchestra/security/secrets.py`

- `InMemorySecretProvider` -- for testing only, plaintext in memory
- `VaultSecretProvider` -- prototype, comment says "Not fully implemented in this prototype"
- No production secret provider is available

### CORS Wildcard

As noted above, `cors_origins=["*"]` with `allow_credentials=True` is a security anti-pattern.

---

## 9. Observability in Production

### OTel Integration: GOOD BUT OPTIONAL

OTel tracing and metrics subscribers are set up via optional imports in `CompiledGraph.run()`. If OTel is installed, traces and metrics are automatically emitted. This is well-designed.

**Issue:** The OTel setup happens silently in the graph execution path. There is no way to configure the OTel endpoint from the server config or CLI.

### Metrics: GOOD

**File:** `src/orchestra/observability/metrics.py`

Tracks the 4 Golden Signals (latency, traffic, errors, saturation) for LLM operations. Well-structured.

### Structured Logging: AVAILABLE BUT NOT WIRED

`setup_logging()` exists and is production-ready (JSON mode, OTel correlation) but is never called during server startup.

---

## 10. Summary Scorecard

| Category | Status | Severity |
|----------|--------|----------|
| Dependency pinning | No lock file, floor-only pins | CRITICAL |
| Dockerfile | Broken entry point | CRITICAL |
| CORS configuration | Wildcard with credentials | HIGH |
| Event store in server | InMemory only | HIGH |
| Server authentication | None | HIGH |
| Signal handling | Absent | HIGH |
| Graceful shutdown | Task cancellation only | HIGH |
| Env var validation | No fail-fast | MEDIUM |
| Logging setup | Not auto-invoked | MEDIUM |
| ORCHESTRA_ENV default | Defaults to dev | MEDIUM |
| Rate limiting on server | Absent | MEDIUM |
| Request size limits | Absent | MEDIUM |
| SSL/TLS | Not configurable | MEDIUM |
| Health checks | Basic (no deep checks) | LOW |
| Error handling in engine | Good with minor gaps | LOW |
| OTel integration | Good, optional | LOW |
| Provider retry logic | Well-implemented | OK |
| Circuit breaker | Well-implemented | OK |
| Error hierarchy | Comprehensive | OK |

---

## 11. Minimum Viable Production Fixes

To reach a state where this could handle real traffic:

1. **Fix the Dockerfile** -- Change `CMD ["run"]` to `CMD ["serve", "--host", "0.0.0.0", "--port", "8080"]` and add a non-root user
2. **Add a lock file** -- Run `uv lock` or `pip-compile` and commit the output
3. **Wire SQLiteEventStore into the server** -- Replace `InMemoryEventStore()` with `SQLiteEventStore()` in `app.py`
4. **Set ORCHESTRA_ENV default to "production"** or remove the dev default
5. **Add startup env var validation** -- Fail fast if required API keys are missing
6. **Call setup_logging()** in the server startup lifespan
7. **Fix CORS** -- Default to empty origins list, require explicit configuration
8. **Add server authentication** -- Even a simple API key middleware
9. **Add signal handling** -- Checkpoint running workflows before shutdown
10. **Add request size limits** -- Configure max request body size

---

*Production readiness assessment: 2026-03-16*
