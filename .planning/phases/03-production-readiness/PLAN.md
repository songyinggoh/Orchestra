# Phase 3: Production Readiness — Implementation Plan

**Phase:** 03-production-readiness
**Goal:** Transform Orchestra from a development-time framework into a production-grade service with HTTP serving, observability, caching, safety guardrails, cost management, and reliability testing.
**Status:** Ready for Execution
**Waves:** 4 (progressive layering — each wave builds on the prior)
**Estimated Tasks:** 8 tasks across 4 waves

---

## Observable Truths (Goal-Backward)

When Phase 3 is complete, all of the following must be demonstrably true:

| # | Truth | Verification |
|---|-------|--------------|
| T1 | A user can start a workflow run via HTTP POST and receive streamed events via SSE | `curl -X POST http://localhost:8000/api/v1/runs` returns 202; `curl http://localhost:8000/api/v1/runs/{id}/stream` yields SSE events |
| T2 | A workflow run produces an OpenTelemetry trace with workflow > node > LLM call span hierarchy visible in Jaeger | `docker compose -f docker-compose.otel.yml up -d && pytest tests/integration/test_otel.py` passes; spans visible at `http://localhost:16686` |
| T3 | Repeated identical LLM calls (temperature=0) are served from cache on second invocation | `pytest tests/unit/test_cached_provider.py` — cache hit returns same response without provider call |
| T4 | An agent with input/output guardrails blocks unsafe content and retries on validation failure | `pytest tests/unit/test_guardrails.py` — PII redaction, length limits, retry-on-fail all pass |
| T5 | Every workflow run reports accurate total_cost_usd in ExecutionCompleted events | `pytest tests/unit/test_cost.py` — CostAggregator accumulates LLMCalled costs correctly |
| T6 | Budget hard limits abort a run before exceeding the dollar cap | `pytest tests/unit/test_cost.py::test_hard_limit_abort` passes |
| T7 | Chaos fault injection (timeouts, errors, malformed responses) does not crash the framework | `pytest tests/chaos/` passes — graceful degradation verified |
| T8 | Load testing confirms the FastAPI server handles 50+ concurrent SSE streams | `locust -f tests/load/locustfile.py --headless -u 50 -r 10 -t 30s` completes without errors |

---

## Wave Structure

```
Wave 1: [T-3.1] FastAPI Server + [T-3.2] OTel Integration
    |
    v
Wave 2: [T-3.3] CachedProvider + [T-3.4] MemoryManager Protocol
    |
    v
Wave 3: [T-3.5] Guardrails + [T-3.6] Cost Management
    |
    v
Wave 4: [T-3.7] Chaos Engineering + [T-3.8] CI/CD Gates + [T-3.9] Integration Verification
```

---

## Wave 1: Serving & Observability (Foundation)

> **Purpose:** Expose agents as HTTP services and instrument them with distributed tracing. Every subsequent wave benefits from having a running server and visible traces.

### Risk Assessment
- **Medium:** SSE streaming edge cases (client disconnect, proxy timeouts, heartbeat). Mitigated by sse-starlette fallback.
- **Low:** OTel SDK is mature. Span lifecycle mismatch with single-event types (LLMCalled) requires backdate pattern.
- **Critical Path:** Yes — all subsequent waves depend on the server and OTel being operational.

---

### T-3.1: FastAPI Server with SSE Streaming

**ID:** T-3.1
**Title:** FastAPI Application with Run Lifecycle, SSE Streaming, and Graph Registry
**Complexity:** L (Large)
**Dependencies:** None (foundational)
**Files to Create:**
- `src/orchestra/server/__init__.py`
- `src/orchestra/server/app.py` — Application factory with lifespan context manager
- `src/orchestra/server/config.py` — Pydantic Settings for server config
- `src/orchestra/server/dependencies.py` — FastAPI dependency injection (get_event_store, get_graph_registry, get_run_manager)
- `src/orchestra/server/middleware.py` — CORS, request ID (asgi-correlation-id)
- `src/orchestra/server/models.py` — Pydantic request/response schemas (RunCreate, RunResponse, RunStatus, StreamEvent, GraphInfo, ErrorResponse)
- `src/orchestra/server/lifecycle.py` — GraphRegistry, RunManager, ActiveRun
- `src/orchestra/server/routes/__init__.py`
- `src/orchestra/server/routes/runs.py` — POST /runs (202 Accepted), GET /runs/{id}, POST /runs/{id}/resume, GET /runs
- `src/orchestra/server/routes/streams.py` — GET /runs/{id}/stream (SSE with heartbeat, reconnection via Last-Event-ID, disconnect detection)
- `src/orchestra/server/routes/graphs.py` — GET /graphs, GET /graphs/{name}
- `src/orchestra/server/routes/health.py` — GET /healthz, GET /readyz
- `tests/integration/test_fastapi_endpoints.py`
- `tests/integration/test_sse_streaming.py`

**Files to Modify:**
- `pyproject.toml` — Add `[project.optional-dependencies] server = [...]`
- `src/orchestra/cli/main.py` — Add `serve` command

**Acceptance Criteria:**
1. `POST /api/v1/runs` with `{"graph_name": "test", "input": {"query": "hello"}}` returns 202 Accepted with `run_id`
2. `GET /api/v1/runs/{id}/stream` returns SSE events with `event:`, `data:`, `id:` fields
3. SSE heartbeat (`: ping\n\n`) sent every 15 seconds; `retry: 5000\n` in initial event
4. `GET /api/v1/runs/{id}/stream` with `Last-Event-ID` header replays missed events from EventStore
5. Client disconnect detection via `request.is_disconnected()` — run continues, status set to INTERRUPTED if applicable
6. Run state machine: PENDING -> RUNNING -> (COMPLETED | FAILED | INTERRUPTED)
7. `GET /healthz` returns 200; `GET /readyz` checks EventStore connectivity
8. `POST /api/v1/runs/{id}/resume` with state_updates resumes HITL-interrupted runs
9. `GET /api/v1/graphs` lists registered graphs; `GET /api/v1/graphs/{name}` returns node/edge details + Mermaid
10. `pytest tests/integration/test_fastapi_endpoints.py tests/integration/test_sse_streaming.py -x` passes

**Key Design Decisions:**
- FastAPI is a thin transport layer; `CompiledGraph.run()` does the work via `asyncio.Task` in RunManager
- Runs decouple from HTTP lifecycle (survive client disconnect) per research findings
- Use `sse-starlette` for heartbeat/disconnect features (FastAPI native SSE lacks these)
- `X-Accel-Buffering: no` and `Cache-Control: no-cache` headers on SSE responses

---

### T-3.2: OpenTelemetry Integration (Tracing + Metrics + Log Correlation)

**ID:** T-3.2
**Title:** OTel 4-Level Span Hierarchy, structlog Trace Correlation, Jaeger Dev Visualization
**Complexity:** L (Large)
**Dependencies:** None (can run parallel with T-3.1, but integrates with server middleware)
**Files to Create:**
- `src/orchestra/observability/tracing.py` — OTelTraceSubscriber (EventBus subscriber emitting spans)
- `src/orchestra/observability/metrics.py` — OTelMetricsSubscriber (in-process counters/histograms for token.usage, operation.duration, errors; Prometheus exporter deferred to Phase 4)
- `src/orchestra/observability/_otel_setup.py` — `setup_telemetry()` function (TracerProvider, MeterProvider, OTLP/HTTP exporters)
- `src/orchestra/observability/_span_attributes.py` — gen_ai.* attribute mapping helpers, PII redaction check
- `docker-compose.otel.yml` — Jaeger all-in-one for local dev
- `tests/unit/test_otel_tracing.py`
- `tests/unit/test_otel_metrics.py`

**Files to Modify:**
- `src/orchestra/observability/__init__.py` — Export setup_telemetry, OTelTraceSubscriber
- `src/orchestra/observability/logging.py` — Add `add_otel_context` structlog processor (injects trace_id/span_id)
- `src/orchestra/core/compiled.py` — Wire OTelTraceSubscriber as optional EventBus subscriber (~5 lines)
- `pyproject.toml` — Add `[project.optional-dependencies] telemetry = [...]`

**Acceptance Criteria:**
1. 4-level span hierarchy: `workflow.run` > `node.{name}` > `gen_ai.chat` > `tool.{name}`
2. All `gen_ai.*` semantic convention attributes populated (gen_ai.system, gen_ai.request.model, gen_ai.usage.input_tokens, gen_ai.usage.output_tokens)
3. LLMCalled spans use backdate pattern (`start_time = event.timestamp - event.duration_ms`)
4. Parallel fan-out nodes appear as concurrent children under a `parallel.*` span
5. PII redaction: `gen_ai.prompt` and `gen_ai.completion` NOT set by default; content capture only via `ORCHESTRA_OTEL_CAPTURE_CONTENT=true`
6. structlog entries include `trace_id` (032x) and `span_id` (016x) when OTel is active
7. 4 Golden Signal metrics exported: `gen_ai.client.operation.duration`, `gen_ai.client.token.usage`, `gen_ai.client.operation.errors`, `orchestra.cost_usd`
8. Bounded metric cardinality: only `model`, `provider`, `operation`, `status`, `workflow_name` as labels (never run_id, node_id)
9. OTel imports guarded with `try/except ImportError` — framework works without telemetry deps
10. `docker compose -f docker-compose.otel.yml up -d` starts Jaeger; traces visible at `http://localhost:16686`
11. `pytest tests/unit/test_otel_tracing.py tests/unit/test_otel_metrics.py -x` passes

**Key Design Decisions:**
- OTelTraceSubscriber follows same EventBus subscriber pattern as RichTraceRenderer (no core engine changes)
- Use OTLP/HTTP (not gRPC) to avoid grpcio 50MB dependency
- Default sample rate 1.0 (LLM calls are expensive and infrequent)
- Asyncio context propagation: `otel_context.attach(parent_ctx)` before `asyncio.create_task()` in parallel execution

---

## Wave 2: Performance & Memory (Optimization)

> **Purpose:** Add caching to reduce LLM costs and latency. Define the memory management protocol for future tiered memory.

### Risk Assessment
- **Low:** CachedProvider is a well-understood wrapper pattern. cachetools is mature.
- **Low:** MemoryManager is a protocol stub — minimal implementation risk.
- **Dependencies:** Wave 1 provides OTel for measuring cache hit rates (nice-to-have, not blocking).

---

### T-3.3: CachedProvider with CacheBackend Protocol

**ID:** T-3.3
**Title:** Cache-Through LLM Provider Wrapper with In-Memory and Disk Backends
**Complexity:** M (Medium)
**Dependencies:** None (can start immediately, but benefits from OTel metrics)
**Files to Create:**
- `src/orchestra/cache/__init__.py` — Exports CacheBackend, InMemoryCacheBackend, DiskCacheBackend, CachedProvider
- `src/orchestra/cache/backends.py` — CacheBackend protocol, InMemoryCacheBackend (cachetools.TTLCache), DiskCacheBackend (diskcache)
- `src/orchestra/providers/cached.py` — CachedProvider wrapper (SHA-256 cache key, temperature gating, tool-call option)
- `tests/unit/test_cached_provider.py`
- `tests/unit/test_cache_backends.py`

**Files to Modify:**
- `pyproject.toml` — Add `cache = ["cachetools>=5.5", "diskcache>=5.6"]` optional dependency

**Acceptance Criteria:**
1. `CachedProvider` wraps any `LLMProvider` transparently — passes through all protocol methods
2. SHA-256 cache key includes: messages (excluding metadata), model, temperature, max_tokens, tools, output_type
3. Only caches calls with `temperature <= max_cacheable_temperature` (default 0.0)
4. `InMemoryCacheBackend` with configurable maxsize (default 1024) and TTL (default 3600s)
5. `DiskCacheBackend` uses `asyncio.to_thread()` for non-blocking I/O
6. Cache hit returns `LLMResponse` without calling underlying provider
7. Cache serialization uses `model_dump_json()` / `model_validate_json()` — excludes `raw_response`
8. `CacheBackend` protocol allows mechanical Redis swap in Phase 4
9. `pytest tests/unit/test_cached_provider.py tests/unit/test_cache_backends.py -x` passes

---

### T-3.4: MemoryManager Protocol Stub

**ID:** T-3.4
**Title:** Minimal Memory Protocol for Phase 4 Readiness
**Complexity:** S (Small)
**Dependencies:** None
**Files to Create:**
- `src/orchestra/memory/__init__.py` — Exports MemoryManager, InMemoryMemoryManager
- `src/orchestra/memory/manager.py` — MemoryManager protocol (store, retrieve) + InMemoryMemoryManager
- `tests/unit/test_memory_manager.py`

**Acceptance Criteria:**
1. `MemoryManager` protocol defines: `store(key, value, metadata, ttl)`, `retrieve(key)`, `search(query, limit)`
2. `InMemoryMemoryManager`: dict-backed, simple substring search
3. Protocol is `@runtime_checkable` for isinstance checks
4. `pytest tests/unit/test_memory_manager.py -x` passes

**Note:** `promote`/`demote` and tier semantics deferred to Phase 4 when multiple storage backends exist. Per Tree of Thoughts analysis: designing tier-management for a one-tier stub is speculative contract design.

---

## Wave 3: Governance & Operations (Safety + Economics)

> **Purpose:** Add input/output guardrails for safety and cost tracking/budget enforcement for economics. Both integrate with EventBus.

### Risk Assessment
- **Medium:** Guardrail ordering matters (PII before telemetry). Must follow canonical ordering documented in research.
- **Low:** CostAggregator is a pure EventBus subscriber — same proven pattern.
- **Medium:** Budget check race condition in parallel execution — accepted limitation, documented.
- **Dependencies:** T-3.2 OTel for cost metrics export (optional enhancement).

---

### T-3.5: Custom Guardrails Framework

**ID:** T-3.5
**Title:** Composable GuardrailChain with InputValidator/OutputValidator, Token Bucket Rate Limiter, Risk-Based Routing
**Complexity:** L (Large)
**Dependencies:** None (extends existing security module)
**Files to Create:**
- `src/orchestra/security/guardrails.py` — OnFail enum, GuardrailResult, Guardrail protocol, GuardrailChain, GuardrailViolation, RetryRequested, GuardedAgent (BaseAgent subclass)
- `src/orchestra/security/validators.py` — Built-in validators: MaxLengthGuardrail, RegexGuardrail, PIIRedactionGuardrail (optional Presidio wrapper)
- `src/orchestra/security/rate_limit.py` — TokenBucket rate limiter (O(1), ~50 bytes per identity), per-agent/per-user/per-run scoping
- `src/orchestra/security/circuit_breaker.py` — AsyncCircuitBreaker (CLOSED/OPEN/HALF_OPEN states)
- `tests/unit/test_guardrails.py`
- `tests/unit/test_rate_limiter.py`
- `tests/unit/test_circuit_breaker.py`

**Files to Modify:**
- `src/orchestra/security/__init__.py` — Export new components

**Acceptance Criteria:**
1. `GuardrailChain` runs validators sequentially with OnFail actions: BLOCK, FIX, LOG, RETRY, EXCEPTION
2. `GuardedAgent` runs input guardrails before LLM call, output guardrails after, with configurable max_retries (default 2)
3. `PIIRedactionGuardrail` with `on_fail=FIX` detects and redacts PII (Presidio optional dep, guarded import)
4. `MaxLengthGuardrail` blocks or truncates text exceeding limit
5. `RegexGuardrail` validates text matches (or doesn't match) a pattern
6. `TokenBucket` rate limiter: configurable max_tokens, window_seconds, raises `BudgetExceededError` on overspend
7. `AsyncCircuitBreaker`: CLOSED->OPEN after N failures, HALF_OPEN after reset_timeout, re-closes on success
8. Risk-based routing concept: guardrail chain composition varies by risk level (low/moderate/high) — documented in code
9. Follows Orchestra's triple-surface pattern: BaseAgent subclass + graph node factory + tool
10. All guardrail LLM calls tagged with `purpose: "guardrail"` metadata for separate cost tracking
11. `pytest tests/unit/test_guardrails.py tests/unit/test_rate_limiter.py tests/unit/test_circuit_breaker.py -x` passes

---

### T-3.6: Cost Management (CostAggregator + BudgetPolicy + ModelCostRegistry)

**ID:** T-3.6
**Title:** EventBus-Based Cost Aggregation with Dual-Layer Budgets and Centralized Pricing
**Complexity:** M (Medium)
**Dependencies:** None (EventBus pattern already proven)
**Files to Create:**
- `src/orchestra/cost/__init__.py` — Exports CostAggregator, BudgetPolicy, ModelCostRegistry
- `src/orchestra/cost/registry.py` — ModelCostRegistry (loads from bundled JSON, prefix matching, runtime overrides)
- `src/orchestra/cost/aggregator.py` — CostAggregator (EventBus subscriber: LLMCalled -> RunCostSummary with cost_by_model, cost_by_agent)
- `src/orchestra/cost/budget.py` — BudgetPolicy (soft/hard limits for USD and tokens), BudgetExceededError, BudgetCheckResult, model downgrade support
- `src/orchestra/cost/_default_prices.json` — Bundled pricing data (LiteLLM format subset for OpenAI, Anthropic, Google, Ollama models)
- `tests/unit/test_cost.py` — Registry, aggregator, budget enforcement, parallel attribution, unknown model handling

**Files to Modify:**
- `src/orchestra/core/compiled.py` — Wire CostAggregator as EventBus subscriber; populate `ExecutionCompleted.total_cost_usd` and `total_tokens` (~10 lines)
- `src/orchestra/core/agent.py` — Add optional pre-call budget check (~5 lines)

**Acceptance Criteria:**
1. `ModelCostRegistry` loads `_default_prices.json` and resolves pricing by exact match or prefix match
2. `ModelCostRegistry.calculate_cost(model, input_tokens, output_tokens)` returns USD float
3. `CostAggregator.on_event(LLMCalled)` accumulates per-run totals with breakdowns by model and agent
4. `ExecutionCompleted` events now have populated `total_tokens` and `total_cost_usd` (were 0)
5. `BudgetPolicy` soft limit triggers structlog warning or model downgrade
6. `BudgetPolicy` hard limit raises `BudgetExceededError` before LLM call
7. Unknown model returns zero cost with structlog warning (not crash)
8. Parallel execution cost attribution is correct (tested with concurrent LLMCalled events)
9. Budget delegation tracking: orchestrator assigns budget to sub-agents
10. Loop detection: max turn count hard cap + anomaly flag for cost spikes
11. `pytest tests/unit/test_cost.py -x` passes

---

## Wave 4: Reliability & Testing (Validation)

> **Purpose:** Validate everything built in Waves 1-3 through advanced testing: statistical testing, chaos engineering, and CI/CD quality gates.

### Risk Assessment
- **Low:** Testing infrastructure uses mature libraries (Locust, Hypothesis, pytest).
- **Dependencies:** All prior waves must be complete for end-to-end testing.

**Note:** SPRT statistical testing framework, five-dimensional coverage tuples, behavioral fingerprinting, and agent mutation testing were evaluated by Tree of Thoughts analysis and **deferred to Phase 4+**. These are research infrastructure with no user-visible payoff in Phase 3. Standard pytest + fault injection + E2E regression covers all Phase 3 validation needs. A simple `@run_n_times(5)` majority-vote decorator can be added to `src/orchestra/testing/` if non-determinism testing is needed.

---

### T-3.7: Chaos Engineering Framework

**ID:** T-3.7
**Title:** Fault Injection for Provider Timeouts, Rate Limits, Partial Responses, and Schema Drift
**Complexity:** M (Medium)
**Dependencies:** T-3.1 (server endpoints to test against)
**Files to Create:**
- `tests/chaos/__init__.py`
- `tests/chaos/fault_injectors.py` — FaultInjector (wraps provider: configurable timeout_rate, error_rate, malformed_rate, latency_ms)
- `tests/chaos/test_provider_faults.py` — Timeout recovery, rate limit (429) handling, malformed response handling, partial response handling
- `tests/chaos/test_storage_faults.py` — EventStore connection failure recovery
- `tests/chaos/test_server_chaos.py` — Server-level chaos: concurrent disconnect, rapid reconnect, SSE stream interruption

**Acceptance Criteria:**
1. `FaultInjector` wraps any LLMProvider with configurable failure rates
2. Framework handles provider timeouts gracefully (no unhandled exceptions)
3. Rate limit (429-style) errors trigger appropriate backoff
4. Malformed/empty responses do not crash the workflow engine
5. EventStore connection failures during append are recoverable
6. SSE client disconnect + reconnect replays missed events correctly
7. `pytest tests/chaos/ -x` passes

---

### T-3.8: CI/CD Coverage Gates and Load Testing

**ID:** T-3.8
**Title:** Coverage Gates, Load Test Scripts, and CI Pipeline Configuration
**Complexity:** M (Medium)
**Dependencies:** T-3.1 (server), T-3.7 (chaos)
**Files to Create:**
- `tests/load/locustfile.py` — Locust load test (create_run, stream_run, get_run_status tasks)
- `tests/load/conftest.py` — Locust environment config
- `tests/property/test_graph_topologies.py` — Hypothesis property-based graph topology testing
- `.github/workflows/phase3-gates.yml` — CI workflow with coverage gates

**Files to Modify:**
- `pyproject.toml` — Add `test-advanced = [...]` optional dependency group

**Acceptance Criteria:**
1. Locust load test can run headless against the server: `locust -f tests/load/locustfile.py --headless -u 50 -r 10 -t 30s`
2. SSE stream load testing verifies concurrent stream handling
3. Hypothesis generates random DAG topologies and verifies all compile without cycles
4. CI/CD gate: minimum 80% code coverage on `src/orchestra/` (excluding test files)
5. CI/CD gate: all chaos tests pass (no unhandled exceptions under fault injection)
6. `pytest tests/load/ tests/property/ --co` collects tests without errors

---

### T-3.9: End-to-End Integration Verification

**ID:** T-3.9
**Title:** Full Stack Integration Test — Server + OTel + Cache + Guardrails + Cost
**Complexity:** S (Small)
**Dependencies:** All prior tasks (T-3.1 through T-3.8)
**Files to Create:**
- `tests/integration/test_full_stack.py` — End-to-end test: start server, submit run, stream events, verify OTel spans, verify cost tracking, verify guardrails applied
- `tests/integration/conftest.py` — Shared fixtures for integration tests (app factory, async client, ScriptedLLM-backed graphs)

**Acceptance Criteria:**
1. Single test that: creates a graph with guardrails -> starts a run via API -> streams events via SSE -> verifies cost in final event -> confirms OTel span hierarchy
2. Server + OTel + CachedProvider + GuardedAgent + CostAggregator all wired together
3. Second identical run hits cache (verified by 0 LLM calls in events)
4. `pytest tests/integration/test_full_stack.py -x` passes

---

## Dependency Graph

```
T-3.1 (Server) ----+
                    |---> T-3.3 (Cache) ----+
T-3.2 (OTel)   ----+                        |
                    |---> T-3.4 (Memory) ----+---> T-3.7 (Chaos) ---+
                    |                        |                       |
                    +---> T-3.5 (Guardrails)-+---> T-3.8 (CI/CD) ---+---> T-3.9 (E2E)
                    |                        |
                    +---> T-3.6 (Cost) ------+

Wave 1: T-3.1, T-3.2           (parallel)
Wave 2: T-3.3, T-3.4           (parallel, after Wave 1)
Wave 3: T-3.5, T-3.6           (parallel, after Wave 1)
Wave 4: T-3.7, T-3.8, T-3.9   (after Waves 2+3)
```

**Note:** Waves 2 and 3 can execute in parallel since they have no inter-dependencies. Both depend only on Wave 1.

---

## Critical Path

```
T-3.1 (Server) -> T-3.7 (Chaos) -> T-3.9 (E2E Verification)
```

The server (T-3.1) is the longest single task and blocks the most downstream work. If it slips, everything slips. T-3.2 (OTel) is the second critical item — it provides the observability needed to debug issues in all subsequent waves.

---

## File Ownership Matrix

| Module | Files | Owner Task |
|--------|-------|------------|
| `src/orchestra/server/` | All new | T-3.1 |
| `src/orchestra/observability/tracing.py` | New | T-3.2 |
| `src/orchestra/observability/metrics.py` | New | T-3.2 |
| `src/orchestra/observability/_otel_setup.py` | New | T-3.2 |
| `src/orchestra/cache/` | All new | T-3.3 |
| `src/orchestra/providers/cached.py` | New | T-3.3 |
| `src/orchestra/memory/` | All new | T-3.4 |
| `src/orchestra/security/guardrails.py` | New | T-3.5 |
| `src/orchestra/security/validators.py` | New | T-3.5 |
| `src/orchestra/security/rate_limit.py` | New | T-3.5 |
| `src/orchestra/security/circuit_breaker.py` | New | T-3.5 |
| `src/orchestra/cost/` | All new | T-3.6 |
| `tests/chaos/` | All new | T-3.7 |
| `tests/load/` | All new | T-3.8 |
| `tests/property/` | All new | T-3.8 |
| `tests/integration/test_full_stack.py` | New | T-3.9 |

**Shared files (sequential access only):**
- `pyproject.toml` — Modified by T-3.1, T-3.2, T-3.3, T-3.9 (add dependencies in sequence)
- `src/orchestra/core/compiled.py` — Modified by T-3.2 (OTel wiring) and T-3.6 (cost wiring)
- `src/orchestra/core/agent.py` — Modified by T-3.6 (budget pre-check)

---

## New Dependencies Summary

| Group | Packages | Tasks |
|-------|----------|-------|
| `server` | `fastapi>=0.115`, `uvicorn[standard]>=0.30`, `sse-starlette>=2.1`, `asgi-correlation-id>=4.3` | T-3.1 |
| `telemetry` | `opentelemetry-api>=1.20`, `opentelemetry-sdk>=1.20`, `opentelemetry-exporter-otlp-proto-http>=1.20`, `opentelemetry-semantic-conventions>=0.45b0` | T-3.2 |
| `cache` | `cachetools>=5.5`, `diskcache>=5.6` | T-3.3 |
| `pii` (optional) | `presidio-analyzer>=2.2`, `presidio-anonymizer>=2.2` | T-3.5 |
| `test-advanced` | `locust>=2.31`, `hypothesis>=6.120`, `syrupy>=4.8`, `pytest-repeat>=0.9`, `asgi-lifespan>=2.1` | T-3.9 |

---

## Success Criteria (Phase Complete When)

- [ ] All 9 tasks complete with passing acceptance criteria
- [ ] `pytest tests/ -x --cov=orchestra` shows >= 80% coverage on new modules
- [ ] `curl -X POST http://localhost:8000/api/v1/runs` starts a streamed workflow
- [ ] Jaeger shows 4-level trace hierarchy for a workflow run
- [ ] Second identical run hits cache (0 provider calls)
- [ ] Budget-limited run aborts at dollar cap
- [ ] Chaos tests pass without unhandled exceptions
- [ ] Load test handles 50+ concurrent SSE streams
- [ ] All 244 existing tests still pass (no regressions)

---

## Phase 4 Deferred Items (Explicitly NOT in Phase 3)

- SPRT statistical testing framework, behavioral fingerprinting, agent mutation testing (per ToT analysis)
- MemoryManager promote/demote tier semantics (pending multiple storage backends)
- OTel Collector pipeline config, Prometheus exporter/scrape endpoint, sampling strategy
- Redis L2 backplane + Pub/Sub cache invalidation
- Warm tier semantic deduplication (0.85/0.98 thresholds)
- Cold tier HNSW vector retrieval
- PromptShield SLM deployment
- Provider failover with strategy switching
- Python subinterpreters for CPU-bound parallelism
- Full chargeback billing system
- Kubernetes OTel Collector Target Allocator
- Per-tenant persistent budget tracking
- Cost-aware routing (dynamic model selection by task complexity)
