# Phase 3: Production Readiness — Backup and Contingency Plan

**Created:** 2026-03-10
**Phase:** 3 — Production Readiness (Weeks 13-18)
**Baseline:** 244 passing tests, master branch at Phase 2 complete

---

## Ground Rules

1. The 244 existing unit tests are a hard gate. No wave ships if they regress.
2. Every wave lands on a dedicated branch (`phase-3/wave-N`). Master receives only post-gate merges.
3. An annotated git tag is created before and after every wave: `phase3-pre-wave-N` / `phase3-post-wave-N`.
4. Rollback means `git revert` of the wave's merge commit, not `reset --hard`. History is never rewritten on shared branches.

---

## Section 1: Rollback Strategies Per Wave

### Wave 1 — FastAPI Server + OpenTelemetry (Weeks 13-14)

**What is added:**
- `src/orchestra/server/` (new module — additive)
- `src/orchestra/observability/tracing.py` (new file — additive)
- `src/orchestra/observability/logging.py` instrumented with OTel trace IDs (modification to existing file)
- OTel context propagation patch in `core/compiled.py` parallel execution path (3-line addition, guarded by `if otel_enabled`)
- **Simplification**: Defer Docker Compose additions for Jaeger/Tempo.

**Rollback tier: Tier 1 for server module, Tier 2 for compiled.py patch**

If Wave 1 introduces regressions:

1. `git revert <wave-1-merge-commit>` — removes the entire server module and tracing file cleanly.
2. If only `compiled.py` is the problem: revert that file's commit individually. The OTel patch is gated behind `if context.otel_tracer is not None`, so it is inert if the tracer is not injected. Set `otel_tracer=None` (the default) to disable OTel with zero code change.
3. The EventBus subscriber pattern (same as `RichTraceRenderer`) means OTel tracing never touches the execution loop. Removing the subscriber removes OTel entirely without affecting runs.

**Recovery time:** Under 5 minutes. Server module is self-contained.

---

### Wave 2 — Caching Layer + Simple Memory Manager (Week 15)

**What is added:**
- `src/orchestra/cache/` (new module — additive)
- `src/orchestra/memory/` (new module — additive)
- `CachedProvider` wraps `LLMProvider` — the original provider is unchanged and still directly usable
- **Simplification**: Use in-process `TTLCache`. Redis is Phase 4.
- **Simplification**: `MemoryManager` protocol simplified to 2 methods (`store`, `retrieve`).

**Rollback tier: Tier 1 (purely additive)**

If Wave 2 introduces regressions:

1. `git revert <wave-2-merge-commit>` — removes both new modules. No existing module is modified.
2. Since `CachedProvider` is a wrapper and not a modification to `LLMProvider`, tests that use `ScriptedLLM` directly are unaffected. Cache is opt-in: callers pass `CachedProvider(provider, cache)` or just `provider`.
3. `MemoryManager` is a Protocol stub only. It has no runtime behavior to break.

**Recovery time:** Under 2 minutes.

---

### Wave 3 — Guardrails + Cost Tracking (Weeks 16-17)

**What is added:**
- `src/orchestra/security/guardrails.py` (new file — extends existing `security/` module)
- `src/orchestra/observability/cost.py` (new file — additive)
- One surgical modification to `core/compiled.py`: optional `output_validators` hook in `_execute_agent_node`
- Token wiring in `agent.py` to fill the `total_cost_usd` field in `ExecutionCompleted` events (currently always 0)

**Rollback tier: Tier 2 for compiled.py hook, Tier 2 for agent.py token wiring**

If Wave 3 introduces regressions:

1. Revert the `compiled.py` hook commit individually. The hook is guarded: `for v in (self._output_validators or []):` — an empty list means zero behavioral change. Tests that do not inject validators are unaffected.
2. Revert the `agent.py` token wiring commit. The `total_cost_usd` field already exists in the event schema and defaults to 0. Rolling back restores that default — no event schema change required.
3. `guardrails.py` and `cost.py` are new files; reverting their commits deletes them with no downstream effect.

**Recovery time:** Under 10 minutes. Two file-level reverts.

---

### Wave 4 — Advanced Testing: Chaos Engineering (Week 18)

**What is added:**
- `src/orchestra/testing/chaos.py` (new file — additive)
- `tests/load/` and `tests/chaos/` (new test directories)
- CI gate additions to `.github/workflows/`
- **Simplification**: Cut SPRT testing framework. Use fixed-sample fault injection decorators.

**Rollback tier: Tier 1 (all additive)**

If Wave 4 introduces regressions:

1. New test directories cannot break existing tests unless they introduce import-time side effects. Verify by running `pytest tests/unit/` in isolation.
2. CI gate changes: revert the workflow YAML commit. The 244 existing tests still run on the original CI job.
3. SPRT and chaos modules are never imported by production code paths — only by test runners.

**Recovery time:** Under 2 minutes.

---

## Section 2: Dependency Risk Mitigation

### FastAPI

**Risk:** FastAPI 0.115+ changed SSE behavior (native `EventSourceResponse` vs. `sse-starlette`). A minor version bump could alter streaming behavior.

**Mitigation:**
- Pin `fastapi>=0.115.0,<0.116.0` in `pyproject.toml` initially. Unpin only after the wave is verified.
- Build an SSE abstraction: `src/orchestra/server/sse.py` with a `StreamAdapter` that wraps whichever SSE library is active. If `sse-starlette` breaks, swap the adapter implementation without touching route handlers.
- Write SSE contract tests that assert event format and ordering against both `httpx.AsyncClient` and a raw SSE parser. These tests catch library regressions immediately.
- Fallback: FastAPI's native `StreamingResponse` with manual SSE formatting (`data: ...\n\n`) is ~30 lines and has no external dependency. Keep it as a commented fallback in `StreamAdapter`.

### OpenTelemetry SDK

**Risk:** OTel GenAI semantic conventions are still in "Development" status. Attribute names changed in v1.38.0 (deprecated `gen_ai.prompt`/`gen_ai.completion` in favor of span events). Another deprecation wave is plausible.

**Mitigation:**
- Never hardcode OTel attribute name strings. Import exclusively from `opentelemetry-semantic-conventions>=0.50`. If the package renames a constant, the import fails at startup — a loud failure, not a silent drift.
- Write a test that asserts every `span.set_attribute()` call in `tracing.py` uses a constant from the semconv package, not a string literal. Use AST inspection or grep in CI.
- If the semconv package breaks or lags behind the SDK: maintain a thin `src/orchestra/observability/_semconv.py` shim that re-exports the constants Orchestra uses. The shim is the only place to update when conventions change.
- OTel is an EventBus subscriber. If OTel fails entirely, wrap the subscriber's `handle()` method in `try/except` and log the error. Execution continues without traces rather than crashing.

### sse-starlette

**Risk:** `sse-starlette` is a small library (200K weekly downloads). If it breaks or is abandoned, the streaming endpoint fails.

**Mitigation:**
- Use FastAPI's native SSE as the primary path (available since 0.115). Treat `sse-starlette` as the fallback for heartbeat features, not the primary dependency.
- The `StreamAdapter` abstraction (described above) makes the swap mechanical.
- If both fail: `StreamingResponse` with a manual async generator is the nuclear fallback. Document this in `server/sse.py` with a clear comment.

### Redis (Wave 2, deferred but designed for)

**Risk:** Redis client (`redis-py` or `coredis`) API changes. Connection timeouts in CI.

**Mitigation:**
- Phase 3 does not require Redis. `CacheBackend` is a Protocol. The default implementation is `TTLCache` (in-process, zero infrastructure). Redis is a Phase 4 addition.
- All cache operations are fail-open: `try/except` around every cache call, with a `cache.miss` metric emitted on failure. LLM calls proceed normally.

### tiktoken

**Risk:** tiktoken covers OpenAI tokenizers only. Using it for Anthropic/Google causes silent token count errors.

**Mitigation:** (per Pitfall 5 in PITFALLS.md)
- Use provider API response `usage` fields as the authoritative count. tiktoken is only used for pre-flight estimation on OpenAI models.
- `CostAggregator` reads from `LLMCalled.input_tokens` and `LLMCalled.output_tokens` fields, which are already populated by each provider adapter from the API response. tiktoken is not in the aggregation path.

---

## Section 3: Scope Reduction Playbook

For each wave, the MVP is the smallest deliverable that provides standalone value and does not block subsequent waves.

### Wave 1 MVP

**Full scope:** FastAPI server with RunManager + SSE streaming + OTel 4-level span hierarchy + structlog correlation + Docker Compose.

**MVP (if time-constrained):** FastAPI server with synchronous run execution (no RunManager background task pattern), returning full results in the HTTP response. No SSE. OTel EventBus subscriber with graph-level span only (no node or LLM child spans). No Docker Compose.

**What you lose:** Long-running HITL runs over HTTP. Real-time streaming. Fine-grained trace waterfall. Jaeger visualization.

**What you keep:** A working API that can execute graphs and return results. OTel context flows through the system. The API contract (`POST /runs`, `GET /runs/{id}`) is stable so Wave 4 E2E tests can be written against it.

**Upgrade path:** Promote synchronous handler to RunManager pattern in a subsequent PR. Add SSE endpoint. Add child spans. None of these changes break the API contract.

---

### Wave 2 MVP

**Full scope:** CachedProvider with TTLCache + diskcache backends + CacheBackend protocol + MemoryManager protocol stub.

**MVP (if time-constrained):** CachedProvider with in-memory `dict` cache (no TTL, no eviction). MemoryManager protocol as a single `Protocol` class with no implementation.

**What you lose:** TTL-based expiration. Persistence across restarts. Formal CacheBackend protocol for Phase 4 Redis swap.

**What you keep:** LLM call deduplication for temperature=0 calls. The MemoryManager protocol exists for Phase 4 to implement against.

**Upgrade path:** Replace the `dict` with `TTLCache`. Add the `CacheBackend` protocol. These are mechanical substitutions with no API change.

---

### Wave 3 MVP

**Full scope:** InputValidator + OutputValidator protocols + GuardrailRunner + PII detection + CostAggregator + dual-layer budget enforcement + model cost registry + loop detection.

**MVP (if time-constrained):** OutputValidator protocol + one concrete `SchemaValidator` (validates output is valid JSON matching an expected schema) + CostAggregator that reads `LLMCalled` events and accumulates totals per run, exposed in the `ExecutionCompleted` event. No input validation. No budget hard limits. No loop detection.

**What you lose:** Input guardrails. PII redaction. Budget enforcement (hard limits). Recursive loop detection.

**What you keep:** Output schema validation (which `ContractRegistry` partially already provides). Per-run cost totals visible in the API response (Phase 3 success criterion #4: "Every run response includes a calculated cost field").

**Upgrade path:** Add InputValidator hook in `compiled.py`. Add budget check in `CostAggregator.on_llm_called()`. Add loop detection counter. All additive.

---

### Wave 4 MVP

**Full scope:** SPRT testing framework + chaos engineering (timeouts, rate limits, partial responses) + CI coverage gates + E2E regression suite against FastAPI endpoints + load tests.

**MVP (if time-constrained):** Chaos fault injection decorators for Provider calls (timeout simulation, 429 simulation) + pytest fixtures that wrap `ScriptedLLM` with these faults + one E2E test against the FastAPI server using `httpx.AsyncClient`. No SPRT. No load tests. No CI coverage gate changes.

**What you lose:** SPRT early-exit framework. Load testing. Coverage gate enforcement.

**What you keep:** Fault injection capability, which is the highest-value item for validating graceful degradation. One E2E test that proves the API surface works end-to-end.

**Upgrade path:** SPRT can be added as a standalone module later. Load tests (`locust` scripts) are external to the pytest suite and can be added independently.

---

## Section 4: Data Safety — Keeping 244 Tests Green

### Test Isolation Strategy

**Rule 1: Unit tests never import server or OTel modules.**
The existing 244 tests are in `tests/unit/`. New Phase 3 tests go in:
- `tests/integration/` — FastAPI endpoint tests using `httpx.AsyncClient` and `TestClient`
- `tests/load/` — locust scripts (not part of the pytest suite)
- `tests/chaos/` — fault injection tests using `ScriptedLLM` with injected failures

`tests/unit/` must remain free of any dependency on `fastapi`, `uvicorn`, `opentelemetry`, or `redis`. Enforce this with an import boundary check in CI:
```
pytest tests/unit/ --import-mode=importlib
```
If a unit test file imports `orchestra.server` or `orchestra.observability.tracing`, the test fails to collect and the problem is visible immediately.

**Rule 2: All Phase 3 modules that touch existing code use conditional injection.**
- OTel tracer: `CompiledGraph` accepts an optional `otel_tracer=None` parameter. Existing tests pass no tracer; the code path is unchanged.
- Output validators: `_execute_agent_node` checks `if self._output_validators:` before running any validator. No validators injected = zero overhead.
- CostAggregator: an EventBus subscriber, not a modification. Tests that don't subscribe to the EventBus are unaffected.

**Rule 3: Run the full 244-test suite as the first step of every wave's CI job.**
The CI pipeline structure is:
```
job: unit-tests (always runs first)
  pytest tests/unit/ -x  # fail fast

job: integration-tests (runs after unit-tests passes)
  pytest tests/integration/

job: wave-gate (runs after integration-tests)
  check coverage thresholds
```
If unit tests fail, the integration job does not start. The merge gate requires all three jobs to pass.

**Rule 4: Pytest fixtures for new infrastructure use autouse=False.**
New fixtures (`fastapi_client`, `otel_tracer`, `cached_provider`) are never `autouse=True`. Existing tests are not affected by fixture additions.

**Rule 5: Database-touching tests use isolated SQLite files.**
Each test that writes to an EventStore uses `tmp_path` (pytest's temporary directory fixture) to create a fresh SQLite file. No shared database state between tests. This is already the convention from Phase 2; maintain it strictly.

---

## Section 5: Performance Degradation Contingency

### OTel Instrumentation Overhead

**Acceptable overhead threshold:** Less than 5% added latency per node execution (measured by comparing `NodeStarted`→`NodeCompleted` duration with and without OTel enabled). OTel span creation is typically sub-millisecond for in-process exporters.

**If OTel overhead exceeds threshold:**

1. First action: Switch from synchronous OTLP export to the async batch exporter (`BatchSpanProcessor`). The default `SimpleSpanProcessor` blocks the event loop until the span is exported. This alone typically eliminates the bottleneck.
2. Second action: Reduce span attribute count. Large message payloads in span attributes (e.g., full prompt text) create serialization overhead. Move prompt/completion content to span events with `add_event()` only when `log_payloads=True` (off by default).
3. Third action: Enable head-based sampling at 10% for non-error traces. OTel SDK suppresses span creation entirely for unsampled traces — zero overhead. Error traces always sample at 100%.
4. Nuclear option: Set `otel_tracer=None` in `CompiledGraph`. OTel is completely disabled. All 244 tests pass. Traces are lost until the performance issue is resolved offline.

**Benchmark to run before shipping Wave 1:**
```
pytest tests/benchmarks/test_otel_overhead.py
```
This test runs a 5-node graph 100 times with and without OTel, asserts median latency increase is under 5%.

---

### Caching Layer Overhead

**Risk:** Cache key computation (SHA-256 of serialized messages) adds CPU overhead on every LLM call, even on cache misses.

**If caching overhead exceeds 2ms per call (negligible vs. LLM latency but measurable in benchmarks):**

1. Switch from SHA-256 to xxHash (faster, non-cryptographic). The cache key does not need cryptographic properties.
2. If the serialization step is slow: pre-serialize messages as part of the provider's request preparation, not inside the cache layer.
3. Worst case: set `cacheable=False` on the provider globally. Caching is entirely bypassed. The `CachedProvider` wrapper becomes a pass-through with two extra function calls.

---

### Guardrail Overhead

**Risk:** Output validators add latency after every LLM call. A schema validator using Pydantic is fast (<1ms). A validator that makes a second LLM call (LLM-as-judge pattern) adds full model latency.

**Policy:** Phase 3 validators must not make LLM calls. Any validator that requires LLM evaluation is deferred to Phase 4. This is a scope rule, not a contingency.

**If validator latency exceeds 10ms:**
1. Run validators concurrently via `asyncio.gather()` when multiple validators are registered for a node.
2. Add a per-validator timeout (default 5 seconds). Timeout raises `ValidatorTimeoutError`, which is treated as a `warn` action (log, emit metric, continue execution). Hard failures never time out silently.

---

### Budget Enforcement Race Conditions (Pitfall 8)

Phase 3 uses in-process cost accumulation (a single `asyncio.Task` per run). Race conditions on budget checks are not possible within a single event loop iteration because `CostAggregator.on_llm_called()` is a coroutine called sequentially by the EventBus. The Pitfall 8 race (Redis `INCRBYFLOAT`) only applies in Phase 4 when multiple Uvicorn workers share a Redis counter.

Document this explicitly in `cost.py` with a `# NOTE: single-process only` comment so it is not silently carried into Phase 4.

---

## Section 6: Phase 4 Dependency Mapping

Phase 4 tasks are listed in `planning/ROADMAP.md` as: Cost Router, Agent IAM, Ray Executor, NATS Messaging, Dynamic Subgraphs, TypeScript SDK, Kubernetes Deployment.

The table below maps Phase 3 outputs to Phase 4 requirements.

| Phase 3 Output | Phase 4 Task That Needs It | Hard Dependency? | If Incomplete |
|---|---|:---:|---|
| FastAPI server (`server/app.py`) with RunManager | TypeScript SDK (needs a stable REST API to call), Kubernetes Deployment (deploys the server) | Yes | Phase 4 TypeScript SDK has no server to call. Kubernetes Deployment has nothing to containerize. Both tasks must wait. |
| OTel instrumentation (`observability/tracing.py`) | Cost Router (uses OTel metrics to route to cheaper models when P95 latency spikes), Kubernetes Deployment (OTel Collector Target Allocator) | Soft | Cost Router can use raw `LLMCalled` event data as a fallback. K8s OTel Collector is additive. |
| `CacheBackend` protocol (`cache/backends.py`) | Redis L2 cache in Phase 4 (requires the protocol to exist before implementing `RedisCacheBackend`) | Yes for clean implementation | Without the protocol, Phase 4 must add it before adding Redis. One extra PR, not a blocker. |
| `MemoryManager` protocol (`memory/manager.py`) | Phase 4 Redis hot tier, vector Cold tier, and embedding retrieval all implement this protocol | Yes | Without the protocol, Phase 4 must define it before building implementations. Same as above — one extra PR. |
| Guardrails (`security/guardrails.py`) with `InputValidator`/`OutputValidator` protocols | Agent IAM (Phase 4 RBAC hooks into the input validation path), PromptShield SLM upgrade | Soft | Agent IAM can enforce permissions via the existing `acl.py` pattern without guardrails. PromptShield is additive. |
| `CostAggregator` + model cost registry | Cost Router (routes based on spend vs. budget), chargeback billing system | Yes | Cost Router cannot function without per-run cost data. If `CostAggregator` is incomplete, Cost Router must be deferred. |
| Advanced testing: fault injection + E2E suite | Ray Executor (needs fault injection to validate distributed failure modes), CI gates | Soft | Ray Executor can add its own fault injection. Existing 244 tests still gate CI. |

### Hard Dependencies Summary

Three Phase 3 outputs are hard dependencies for Phase 4:

1. **FastAPI server with RunManager** — blocks TypeScript SDK and Kubernetes Deployment. These are the highest-visibility Phase 4 deliverables. If Wave 1 is descoped to the MVP (synchronous handler, no RunManager), Phase 4 must promote it to full RunManager before starting those tasks.

2. **CostAggregator with model cost registry** — blocks Cost Router. Cost Router is the first Phase 4 task in the roadmap. If Wave 3 cost tracking is incomplete, Cost Router must be rescheduled to after it is finished.

3. **`CacheBackend` and `MemoryManager` protocols** — not blockers for any single Phase 4 task, but their absence forces Phase 4 to define them mid-stream, which creates scope creep in Phase 4 planning.

### Incomplete Phase 3 Decision Tree

```
Wave 1 incomplete →
  - If synchronous handler only (no RunManager):
      → Phase 4 must complete RunManager before TypeScript SDK or K8s tasks
      → Add "PHASE3-REMAINDER-W1" task to Phase 4 wave planning
  - If no OTel:
      → Phase 4 Cost Router uses LLMCalled events directly (acceptable fallback)
      → Add OTel as Phase 4 Wave 1 task

Wave 2 incomplete →
  - If no CacheBackend protocol:
      → Phase 4 defines it in the same PR as RedisCacheBackend
      → Net: one extra PR, no timeline impact
  - If no MemoryManager protocol:
      → Same as above

Wave 3 incomplete →
  - If no CostAggregator:
      → Phase 4 Cost Router is blocked; must be rescheduled past the CostAggregator completion
      → This is the highest-impact incomplete scenario
  - If no Guardrails protocols:
      → Agent IAM uses acl.py pattern; PromptShield deferred further

Wave 4 incomplete →
  - SPRT/chaos tests are standalone; no Phase 4 feature depends on them
  - E2E suite absence means Phase 4 starts with less regression coverage
      → Mitigate: add E2E tests as Phase 4 Wave 1 task before any feature work
```

---

## Appendix: Git Branch and Tag Discipline

```
master                    (Phase 2 baseline — protected)
  └── phase-3/wave-1      (FastAPI + OTel)
  └── phase-3/wave-2      (Cache + Memory)
  └── phase-3/wave-3      (Guardrails + Cost)
  └── phase-3/wave-4      (Testing)
  └── phase-3/integration (landing branch; wave branches merge here after gate)
```

Tags to create:
- `phase3-pre-wave-1` — before any Wave 1 work begins
- `phase3-post-wave-1` — after Wave 1 merges to integration and gate passes
- `phase3-pre-wave-2`, `phase3-post-wave-2`
- `phase3-pre-wave-3`, `phase3-post-wave-3`
- `phase3-pre-wave-4`, `phase3-post-wave-4`
- `phase3-complete` — after all 4 waves merge to master

Rollback commands (for reference):
```bash
# Revert a wave's merge commit from integration branch
git revert -m 1 <wave-N-merge-commit-sha>

# Hard rollback to pre-wave tag (only for Tier 3 / behavioral changes)
git checkout phase3-pre-wave-N -- src/orchestra/core/compiled.py

# Verify 244 tests still pass after any revert
pytest tests/unit/ -x -q
```

---

*Last updated: 2026-03-10*
*Authored by: backup-planner agent*
