# Orchestra Framework — Production Live-Use Code Review

**Date:** 2026-03-16
**Reviewer:** code-reviewer agent
**Scope:** Critical-path files for production container deployment
**Verdict:** CONDITIONAL-GO

---

## Verdict Summary

The framework is well-structured and shows mature engineering judgment in most places. There are no obvious show-stopper crash bugs, but five issues must be fixed before this runs unattended in production. Three of them take under an hour each. The other two require a deliberate decision from the team rather than a code change.

---

## Blockers (must fix before live use)

### B-1 — `serve_wrapper.py` binds to localhost; the container will be unreachable

**File:** `serve_wrapper.py`, lines 4 and 9

```python
config = ServerConfig(host="127.0.0.1", port=8000)
...
uvicorn.run(app, host="127.0.0.1", port=8000)
```

`ServerConfig` already defaults to `host="0.0.0.0"`. The wrapper overrides it to `127.0.0.1`, which means the container accepts zero external connections. The CLI `serve` command and `ServerConfig` are both correct; only this file is wrong.

**Fix:** Delete `serve_wrapper.py` and use `orchestra serve` from the Dockerfile instead, or change both host strings to `"0.0.0.0"` / `${ORCHESTRA_HOST:-0.0.0.0}`.

---

### B-2 — Dockerfile exposes port 8080 but runs on port 8000; health checks never pass

**File:** `Dockerfile`, lines 22–26

```dockerfile
ENV ORCHESTRA_PORT=8080
EXPOSE 8080
ENTRYPOINT ["orchestra"]
CMD ["run"]
```

`ORCHESTRA_PORT` is declared but the CLI `serve` command uses `--port` (an explicit Typer option), not this env var. `ServerConfig.port` defaults to `8000`. The exposed port (8080) and the actual listen port (8000) never match. Kubernetes liveness probes targeting 8080 will fail permanently.

Additionally, `CMD ["run"]` invokes `orchestra run`, which expects a workflow file argument — it is not the HTTP server command. The correct command is `orchestra serve`.

**Fix:**
```dockerfile
ENV ORCHESTRA_PORT=8080
EXPOSE 8080
ENTRYPOINT ["orchestra"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8080"]
```
And either plumb `ORCHESTRA_PORT` into the `ServerConfig`, or keep it explicit as shown above.

---

### B-3 — Dockerfile has no health check; no non-root user

**File:** `Dockerfile`

Two independent sub-issues:

**3a — No HEALTHCHECK.** Kubernetes will mark the pod healthy immediately and route traffic before the app is ready, because the `/healthz` endpoint is never polled at the container level. The `/healthz` and `/readyz` routes exist and are correct; they just are not wired into the image.

```dockerfile
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/healthz || exit 1
```

**3b — Runs as root.** The image has no `USER` directive, so the process runs as root inside the container. This violates Pod Security Standards Baseline and will be rejected by clusters enforcing them.

```dockerfile
RUN useradd --system --create-home --uid 1001 orchestra
USER orchestra
```

---

### B-4 — `ORCHESTRA_ENV` defaults to `"dev"` in production containers; Rich renderer activates on every run

**File:** `src/orchestra/core/compiled.py`, lines 176 and 419

```python
_default_trace = "rich" if os.environ.get("ORCHESTRA_ENV", "dev") == "dev" else "off"
```

Because `ORCHESTRA_ENV` is not set in the Dockerfile, every container run activates the `RichTraceRenderer`. The renderer calls `.start()` (which starts a Live display writing to a terminal), and `event_bus.subscribe()` is called twice — once in `run()` and again in `_run_loop()`. In a headless container this generates noisy terminal output and register two subscribers per run (doubling the event dispatch work). This is a runtime misbehaviour, not a crash, but under load it produces measurable overhead.

**Fix:** Add `ENV ORCHESTRA_ENV=prod` to the Dockerfile. No code change required.

---

### B-5 — `_BroadcastStore` in `lifecycle.py` is missing `create_run` and `update_run_status`; background task will crash silently on every run

**File:** `src/orchestra/server/lifecycle.py`, lines 117–144

`_BroadcastStore` delegates `append`, `get_events`, `get_latest_checkpoint`, `get_checkpoint`, `save_checkpoint`, and `list_runs`. It does not implement `create_run` or `update_run_status`.

`CompiledGraph._run_loop` calls both of those methods (lines 618 and 653 of `compiled.py`):

```python
await event_store.update_run_status(effective_run_id, "failed", completed_at)
...
await event_store.update_run_status(effective_run_id, "completed", completed_at)
```

These calls are inside a bare `except Exception: pass` block, so the `AttributeError` is silently swallowed. The run status in the event store never transitions from `"running"`, which means the `/runs` endpoint always shows stale status, and the SSE stream is the only truthful signal of completion. Additionally, `run()` calls `await _sqlite_store.create_run(...)` before any background task is involved — but when the server manages its own `InMemoryEventStore` via `_BroadcastStore`, `create_run` on the inner store is never called, so the store has no record of the run.

**Fix:** Add the two missing delegate methods to `_BroadcastStore`:

```python
async def create_run(self, *args: Any, **kwargs: Any) -> Any:
    return await self._inner.create_run(*args, **kwargs)

async def update_run_status(self, *args: Any, **kwargs: Any) -> Any:
    return await self._inner.update_run_status(*args, **kwargs)
```

---

## Warnings (should fix; will not crash production but degrade reliability)

### W-1 — `setup_logging()` is never called in the server path

**File:** `src/orchestra/observability/logging.py` (function defined); `src/orchestra/server/app.py` and `src/orchestra/cli/main.py` (never called)

`setup_logging(json_output=True)` exists and is correct for container environments. Neither the `lifespan` startup hook in `app.py` nor the `serve` CLI command ever calls it. Structlog is therefore unconfigured: all modules call `structlog.get_logger(__name__)` but output format is controlled by whatever the last caller to `structlog.configure` happened to set (or the built-in default).

In practice the logs probably work because the stdlib `logging.basicConfig` fallback fires, but they will not be JSON, they will not have `trace_id`/`span_id` injection, and the format will vary across workers if uvicorn is started with `--workers > 1`.

**Fix:** In the lifespan startup hook in `app.py`:
```python
from orchestra.observability.logging import setup_logging
setup_logging(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    json_output=os.environ.get("ORCHESTRA_ENV", "dev") != "dev",
)
```

---

### W-2 — `RunManager` never purges completed runs; unbounded memory growth

**File:** `src/orchestra/server/lifecycle.py`, `RunManager._runs`

`_runs` is a plain `dict`. Every completed or failed run stays in memory indefinitely. Under sustained load this is an unbounded memory leak. The shutdown handler in `app.py` cancels in-flight tasks but does not clear `_runs`.

The `event_queue` attached to each `ActiveRun` also grows without bound because `_queue_callback` puts every event for a given `run_id` into the queue but there is no reader after SSE clients disconnect. Once the SSE client disconnects, the queue fills silently.

**Fix (minimal):** Evict finished runs from `_runs` after a configurable TTL (e.g., 5 minutes) using a background cleanup task. Add `maxsize` to the `asyncio.Queue` to bound memory per run (e.g., `asyncio.Queue(maxsize=1000)`), and document that SSE clients that do not drain fast enough will cause events to be dropped.

---

### W-3 — `AsyncCircuitBreaker` has no async lock; concurrent failover calls can corrupt state

**File:** `src/orchestra/security/circuit_breaker.py`

`record_failure()`, `record_success()`, and `allow_request()` all read and write `_failure_count`, `_state`, and `_last_failure_time` without any lock. When `ProviderFailover.complete()` is called concurrently from multiple coroutines (which is the expected production pattern), two coroutines can both read `CLOSED`, both call `record_failure()`, and both independently trip the circuit, causing the `_failure_count` to over-increment. In `HALF_OPEN`, two concurrent requests can both be allowed through simultaneously, defeating the probe-then-recover semantics.

This is a correctness bug, not a crash risk. The circuit still eventually stabilises, but it will trip too aggressively under concurrent load.

**Fix:** Add an `asyncio.Lock` to `AsyncCircuitBreaker` and acquire it inside `allow_request`, `record_success`, and `record_failure`. Since these are synchronous methods, use `threading.Lock` if the breaker is also used from synchronous contexts, or switch to an internal `asyncio.Lock` and make the methods async.

---

### W-4 — `PersistentBudgetStore` reuses a single `:memory:` connection without a per-call lock

**File:** `src/orchestra/cost/persistent_budget.py`, lines 141–146

```python
if self.db_path == Path(":memory:") and self._memory_conn:
    # ...
    yield self._memory_conn
```

The in-memory mode yields the same connection object to every concurrent caller. `aiosqlite` wraps SQLite's C library through a thread executor; concurrent awaits on the same connection object can serialize correctly in CPython, but the connection itself is not designed for concurrent use and will raise if two coroutines issue `BEGIN IMMEDIATE` at the same time. In production this mode is typically used in tests, but if a deployment mistakenly points `db_path` at `:memory:` (e.g., misconfigured env var), it will fail under any concurrency.

**Fix:** Add an `asyncio.Lock` around the `:memory:` connection access, or document that `:memory:` is test-only and enforce that in the constructor.

---

### W-5 — `numpy` imported at call time in `ProviderFailover.get_provider_health()`; missing from server extras

**File:** `src/orchestra/providers/failover.py`, line 175

```python
import numpy as np
```

`numpy` is a large dependency (adds ~30 MB to the image). It is imported inside `get_provider_health()`, which is called from monitoring/health endpoints. If `numpy` is not installed, the health endpoint returns an empty dict silently. Confirming whether `numpy` is included in the `server` or `telemetry` extras is worth checking; if it is not, the p50/p95 latency metrics will never appear in production without an explicit install.

**Fix:** Replace `numpy` percentile math with a stdlib equivalent for a 20-sample window, or declare `numpy` in the `server` extras in `pyproject.toml`.

---

## File-by-File Assessment

### `src/orchestra/core/compiled.py`

**Crash risk:** Low. The `_run_loop` wraps the entire execution in a `try/except Exception` that emits `ErrorOccurred` and re-raises. No exception can silently disappear. The `_renderer.stop()` is called in all exit paths (normal, error, interrupt). `MaxIterationsError` is raised cleanly.

**Resource leaks:** The `SQLiteEventStore` opened under `persist=True` is closed in the success path (`_store_owner` guard, line 233). However, if `_run_loop` raises, `close()` is never called on `_sqlite_store` — the `try/except` in `_run_loop` does not have a `finally` that closes the store. This leaks a file handle per failed run when `persist=True`. Fix: move the `_store_owner` close into a `finally` block in `run()`.

**Concurrency safety:** The `RichTraceRenderer` is subscribed inside both `run()` (line 182) and `_run_loop()` (line 425). When `resume()` calls `_run_loop()` directly, it gets one renderer subscription. When `run()` calls `_run_loop()`, it gets two. Under `resume()` this is fine; under `run()` every event is rendered twice. Not a crash but a cosmetic bug.

**Operational gaps:** `ORCHESTRA_ENV` must be set to `"prod"` (see B-4 above).

---

### `src/orchestra/core/agent.py`

**Crash risk:** Low. Tool exceptions are caught and returned as `ToolResult.error` (line 339). `MaxIterationsError` is raised with `partial_output` populated for caller inspection. `ProviderError` is raised immediately when no provider is set rather than NPE-ing later.

**Resource leaks:** None. No file handles or network connections are opened directly.

**Concurrency safety:** The `acl` attribute is mutated via `object.__setattr__` (line 303) which bypasses Pydantic's frozen-model checks. If two coroutines executing the same `BaseAgent` instance both find `self.acl is None` simultaneously, they will both set it (to the same value), which is benign but should be noted. `BaseAgent` instances are typically not shared across concurrent runs, so this is low risk in practice.

**Operational gaps:** `max_iterations=10` is a reasonable default. No timeout is applied to individual `llm.complete()` calls — a hung provider will stall a coroutine indefinitely. This is the most likely single cause of a production run never completing. The failover layer should apply a timeout; see W-3 above.

---

### `src/orchestra/providers/failover.py`

**Crash risk:** Low. `AllProvidersUnavailableError` is raised when all providers fail. `TERMINAL` and `MODEL_MISMATCH` errors are re-raised immediately (lines 138–141), which is correct — there is no sense retrying with a different provider for an auth failure.

**Resource leaks:** None.

**Concurrency safety:** See W-3. The circuit breaker has no lock.

**Operational gaps:** No per-call timeout. A provider that accepts the connection but never responds stalls the failover chain indefinitely. Add `asyncio.wait_for(provider.complete(...), timeout=30.0)` around the call with the timeout sourced from config.

---

### `src/orchestra/memory/tiers.py`

**Crash risk:** Low. `_background_scan` catches all exceptions inside its loop (line 332) and logs them without crashing. The done-callback `_log_task_exception` logs unhandled exceptions from the task itself.

**Resource leaks:** The background scan task is only started if `start()` is called. If callers forget to call `start()`, the scan task never runs and `stop()` is a no-op — no leak. If `start()` is called, `stop()` correctly cancels and awaits the task. The `_initialized = False` at the end of `stop()` means `start()` can be called again safely.

**Concurrency safety:** The `_policy_lock` pattern is sound — I/O is performed outside the lock and policy mutations are batched inside short critical sections. The previous race in `retrieve()` (where the value was read outside the lock) has been fixed. The remaining subtlety: in `retrieve()`, after step 3 (Redis warm hit), the code inserts directly into `_policy._hot` without going through `SLRUPolicy.insert()`, bypassing the `WARM` insert path. This is intentional (the item is already warm-validated), but means a Redis hit skips the "new items start in WARM" invariant. Under high Redis-hit load, `_hot` can fill faster than expected. This is a policy nuance, not a crash.

**Operational gaps:** `create_tiered_memory()` starts no background task — callers must call `manager.start()` explicitly. This is easy to forget. Consider calling `start()` inside the factory function, or raising if `start()` has not been called before the first `store()`.

---

### `src/orchestra/cost/persistent_budget.py`

**Crash risk:** Low. `BEGIN IMMEDIATE` combined with `rollback` on exception prevents partial writes. `CyclicHierarchyError` is raised on circular parent references. `BudgetExceededError` is raised cleanly.

**Resource leaks:** File-backed `aiosqlite` connections are opened and closed inside a context manager (lines 147–152). No leak for normal use. See W-4 for the `:memory:` edge case.

**Concurrency safety:** `BEGIN IMMEDIATE` acquires a write lock at the SQLite level, which serializes all budget operations correctly for a single process. If multiple processes share the same SQLite file (e.g., multiple uvicorn workers), `BEGIN IMMEDIATE` still serializes at the OS level because SQLite WAL mode is enabled. This is correct.

**Operational gaps:** `check_and_debit` returns `1_000_000.0` (one million USD) when a tenant account does not exist (line 197). This means unknown tenants spend freely. This is likely intentional ("open by default") but deserves a comment and a config option to make it closed by default in production.

---

### `serve_wrapper.py`

See B-1 and B-2 above. This file is a development artifact. It should either be deleted or replaced with a proper production entrypoint. The `orchestra serve` CLI command with explicit host/port arguments is the correct production invocation.

---

### `Dockerfile`

See B-2, B-3, and B-4 above. Additionally:

- The editable install (`pip install ".[...]"`) in the previous review was noted as not best-practice; this is already fixed — the current `RUN pip install --no-cache-dir ".[...]"` installs normally.
- `build-essential` in the base image adds ~170 MB and is only needed at build time. Consider a multi-stage build to keep the final image small:

```dockerfile
FROM python:3.12-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md .
COPY src/ src/
RUN pip install --no-cache-dir ".[server,telemetry,cache,storage,postgres,nats,security,messaging]"

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=builder /usr/local/bin/orchestra /usr/local/bin/orchestra
RUN useradd --system --uid 1001 orchestra
USER orchestra
ENV ORCHESTRA_ENV=prod
ENV ORCHESTRA_PORT=8080
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/healthz || exit 1
ENTRYPOINT ["orchestra"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8080"]
```

- The `ray` extra is included in the current install line but the Phase 4 ToT analysis explicitly chose NATS over Ray and noted Ray adds 500 MB+ to the image. Remove `ray` from the extras list.

---

## Cross-Cutting Concerns

### Logging to stdout

`setup_logging(json_output=True)` emits structured JSON to stdout, which is exactly right for container environments. The problem is that it is never called in the server path (W-1). Once wired in, this is correct.

### Hardcoded credentials / localhost assumptions

No hardcoded API keys or passwords were found in the reviewed files. The one localhost assumption that matters is `serve_wrapper.py` (B-1). The `NATS_URL` default in the Dockerfile (`nats://nats:4222`) is a service name, which is correct for Kubernetes.

### CORS wildcard

`cors_origins` defaults to `["*"]` in `ServerConfig`. This is acceptable for an internal API server but must be restricted if the server is ever exposed to a browser-accessible public URL.

### General exception handler leaks error type names

`app.py` line 87:
```python
content=ErrorResponse(detail=str(exc), error_type=type(exc).__name__).model_dump()
```

`type(exc).__name__` and `str(exc)` can leak internal class names and stack-trace fragments to external callers. Consider returning a generic `"internal_error"` type and logging the real detail server-side.

---

## Priority Fix Order

| Priority | Item | Effort |
|----------|------|--------|
| 1 | B-2: Fix Dockerfile CMD and port mismatch | 15 min |
| 2 | B-1: Fix serve_wrapper.py localhost binding | 5 min |
| 3 | B-3: Add HEALTHCHECK and non-root USER to Dockerfile | 10 min |
| 4 | B-4: Add ENV ORCHESTRA_ENV=prod to Dockerfile | 2 min |
| 5 | B-5: Add create_run / update_run_status to _BroadcastStore | 10 min |
| 6 | W-1: Call setup_logging() in server lifespan | 15 min |
| 7 | W-2: Add run TTL eviction and queue maxsize to RunManager | 1 hour |
| 8 | W-3: Add asyncio.Lock to AsyncCircuitBreaker | 30 min |
| 9 | W-4: Document :memory: as test-only, add lock | 20 min |
| 10 | W-5: Replace numpy with stdlib in get_provider_health | 15 min |

Fixes B-1 through B-5 are prerequisites for a functioning container. W-1 through W-5 are hardening steps that should be completed before the first production load spike.
