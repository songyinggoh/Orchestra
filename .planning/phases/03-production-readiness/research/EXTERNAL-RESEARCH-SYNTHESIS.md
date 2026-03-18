# External Research Synthesis — Phase 3 Production Readiness

**Source:** 6 external PDF documents (user-provided research reports)
**Synthesized:** 2026-03-10
**Purpose:** New insights beyond existing research, filtered for Phase 3 relevance

---

## Wave 1: Server & OTel — New Insights

### Server (from Engineering Spec PDF)
- **FastAPI lifespan context manager is MANDATORY** — prevents `RuntimeError: Task attached to a different loop` from module-level initialization of DB clients, vector stores, LLM clients
- **Long-Running Task Pattern:** `POST /runs` returns `202 Accepted` immediately; execution runs as background `asyncio.Task`. Status polled via `GET /runs/{id}/status`
- **Run State Machine:** `PENDING → RUNNING → (INTERRUPTED | COMPLETED | FAILED)` — must be persisted in event store for cross-restart retrieval
- **SSE implementation details:**
  - Heartbeat: `: ping\n\n` every 15 seconds (prevents proxy termination)
  - Client retry: `retry: 5000\n` in initial event
  - Headers: `X-Accel-Buffering: no`, `Cache-Control: no-cache`
  - Reconnection: check `HTTP_LAST_EVENT_ID` header → replay missed events from persistent store
- **Disconnect handling:** Monitor `request.is_disconnected()` → checkpoint state as `INTERRUPTED` (prevents orphaned runs wasting tokens)
- **PostgresSaver bottleneck:** Internal `self.lock` serializes checkpoint R/W per saver instance → need multiple Uvicorn workers for horizontal scaling
- **Pydantic models:** `RunRequest(agent_id, prompt, thread_id, params)`, `EventPayload(type, content, metadata)`, `StateSnapshot(thread_id, checkpoint_id, values, next_node)`
- **asyncio.TaskGroup** (Python 3.11+ structural concurrency) for parallel node execution with fail-fast semantics

### OTel (from Telemetry Spec PDF)
- **Agentic span hierarchy (4 levels):**
  1. `workflow.run` (Root, INTERNAL) — `gen_ai.operation.name = "workflow"`
  2. `agent.turn` (INTERNAL or CLIENT) — `gen_ai.operation.name = "invoke_agent"`
  3. `llm.chat` (CLIENT) — `gen_ai.operation.name = "chat"`
  4. `tool.invocation` (CLIENT or INTERNAL) — `gen_ai.operation.name = "execute_tool"`
- **PII redaction MUST occur BEFORE telemetry reaches economics/token-counting processors** — architectural mandate
- **OTelContextMiddleware** for FastAPI: extract W3C `traceparent`/`tracestate` from request headers, attach to execution scope, inject into response headers, detach on completion
- **asyncio context loss fix:** `run_with_trace_context(coro)` wrapper captures current OTel context and reattaches in background tasks
- **structlog integration:** Processor pipeline injects `trace_id` (032x) and `span_id` (016x) into every log entry for bidirectional trace↔log correlation
- **AI Golden Signals (Prometheus metrics):**
  - `gen_ai.client.operation.duration` (Histogram) — TTFT + E2E latency
  - `gen_ai.client.token.usage` (Counter) — by model, token_type (input/output/cache)
  - `gen_ai.client.operation.errors` (Counter) — by model, error.type (logic vs provider)
  - `gen_ai.usage.cost` (Gauge) — estimated USD cost
- **Cardinality rule:** `tenant_id`, `user_id` MUST NOT be metric labels (crashes Prometheus TSDB) → use span attributes instead
- **OTel Collector config:** redaction processor (allow-list keys, block sensitive values) + memory_limiter (1024 MiB) + batch (1000, 10s)
- **Sampling strategy:** Head-based 5% for healthy traces + tail-based 100% for errors/slow spans

---

## Wave 2: Caching & Memory — New Insights

### Memory Architecture (from Multi-Tier Memory Spec PDF)
**Phase 3 scope: protocol stub only. Below informs the protocol design.**
- **Three tiers:** Hot (Redis RAM), Warm (RedisJSON semantic dedup), Cold (Vector DB with HNSW)
- **L1/L2 caching pattern:** L1 = local in-memory, L2 = distributed Redis backplane
- **Semantic deduplication thresholds:**
  - 0.98 cosine similarity = pure vector math dedup (no LLM call)
  - 0.85 similarity = triggers LLM consolidation (keep/update/delete/insert)
- **Composite scoring:** `Score = Similarity*w + Recency*w + Importance*w`
- **Recency decay:** `Recency = 0.5^(age_days / half_life_days)`
- **MemGPT-style "Deep Recall":** agent autonomously searches long-term memory when context insufficient
- **Inter-agent Pub/Sub:** Redis channels for cache invalidation across agents
- **ROI:** 86% cost reduction, 15x speedup from semantic caching

**→ Phase 3 action:** Design `MemoryManager` protocol to accommodate these tiers. Implement only L1 (in-process) tier. Leave L2/Warm/Cold as protocol stubs for Phase 4.

---

## Wave 3: Guardrails & Cost — New Insights

### Guardrails (from Safety Audit PDF)
- **PromptShield SLM:** 65.3% TPR @ 0.1% FPR — far better than PromptGuard (9.4%). Consider as Phase 4 upgrade to existing Rebuff guard
- **Indirect prompt injection via RAG:** Context Anchoring + Signed-Prompt Verification + privilege limitation for retrieved-data agents
- **Token Bucket rate limiting:** O(1) time, ~50 bytes per identity (vs 1KB for Leaky Bucket) — ideal for per-agent rate limiting
- **Circuit breaker triggers:** Status 429 (immediate back-off), Status 503 (service unavailable), P95 latency > 2x baseline
- **Provider failover:** Auto-switch from Native Schema Enforcement (Strategy 1) to Prompted+Validation (Strategy 2) for non-native fallbacks
- **Risk-based guardrail routing:**
  - Low risk (summarization): basic rate limiting + PII scan
  - Moderate risk (external search): context anchoring + NSFW filter
  - High risk (financial ops): HITL + strict schema + RBAC
- **Post-guardrail failure modes to monitor:** Partial Refusals (34%), Hidden Compliance (22%)
- **Zero-Trust for LLM APIs:** Every agent output treated as potentially malformed instruction
- **OWASP AI Agent Security Top 10 (2026)** alignment recommended

### Cost (from Cost Management PDF)
- **Unit economics per agent** — not just total spend
- **Dual-layer budget enforcement:**
  - Hard limits: Circuit breaker (5 failures/min → kill) + dollar caps
  - Soft limits: Budget-aware routing → downgrade to cheaper models (Haiku, SLMs)
- **Budget delegation conservation law:** Orchestrator assigns budget to sub-agents; unused credits return to central pool immediately after sub-task completion
- **Dynamic Model Cost Registry:** Track LLMflation (1000x cost reduction over 4 years). Must be updatable without code changes
- **Recursive Loop Risk Audit:**
  - Max turn counts (hard cap)
  - Semantic similarity thresholds (detect repetitive outputs = reasoning stalls)
  - Node-level rate limiting (catches expensive single requests that gateway limits miss)
  - Anomaly detection: $0.20→$1.50/turn spike triggers investigation
- **Mandatory metadata tags:** user_id, task_type, model_alias, department_code, budget_duration
- **Wasted spend tracking:** Failed retries with exponential backoff + hallucinations caught by guardrails
- **Showback→Chargeback transition** for AI accountability
- **Cost-saving heuristics:** Relay Method (kill instances between tasks), batch processing (50% discount), prompt prefix caching (10% of standard rates)

---

## Wave 4: Testing — New Insights

### QA Framework (from QA Report PDF)
- **Reliability Surface R(k, ε, λ):**
  - k = consistency (pass@k over repeated trials)
  - ε = robustness (resilience to task perturbations)
  - λ = fault tolerance (state recovery from infra failures)
- **SPRT (Sequential Probability Ratio Test):** Early-exit testing — 78% token cost reduction vs fixed-sample
  - Variance-Calibrated Budgeting: stable agents need 4-7x fewer trials
  - Three-valued verdict: Pass / Fail / Inconclusive (mathematically necessary)
- **Five-dimensional coverage tuple:**
  - C_tool: every tool invoked
  - C_path: Chao1 estimator for hidden reasoning sequence space
  - C_state: variety of internal states/histories reached
  - C_boundary: edge cases in tool parameters
  - C_model: consistency across LLM providers
- **Agent mutation testing:** Four operators (Prompt, Tool, Model, Context) with stochastic kill semantics (95% confidence)
- **Behavioral fingerprinting:** Map traces to low-dimensional manifolds → Hotelling's T² test for multivariate regression detection. Six feature families: tool usage, structural complexity, output characteristics, reasoning patterns, error/recovery, efficiency metrics
- **Trace-first offline analysis:** Run coverage + contract tests on production traces at ZERO token cost
- **CI/CD gates:**
  - Minimum 0.80 coverage across all 5 dimensions
  - No statistically significant degradation at α=0.05
  - SPRT must reach definitive "Pass" — any "Inconclusive" triggers manual review
- **Chaos engineering scenarios:** Transient timeouts, rate limits (429), partial responses, schema drift

---

## Contradictions with Existing Research

1. **Redis timing:** External docs (Memory Spec, Cost PDF) assume Redis is available. Existing research correctly defers Redis to Phase 4. **Resolution: maintain deferral** — design protocols to support Redis but implement in-process only.
2. **sse-starlette vs FastAPI native:** Research agents found FastAPI 0.115+ has native `EventSourceResponse`. Existing research recommends sse-starlette. **Resolution: prefer FastAPI native SSE, keep sse-starlette as fallback for heartbeat/disconnect features.**
3. **Guardrails AI vs custom:** External Safety PDF doesn't mention Guardrails AI framework. Aligns with existing decision to build custom. **No contradiction.**
4. **Python version:** Server Spec PDF mentions Python 3.14 `asyncio.TaskGroup` and subinterpreters. **Resolution: use TaskGroup (available since 3.11), defer subinterpreters to Phase 4.**

---

## Phase 3 vs Phase 4 Triage

### Phase 3 (implement now)
- FastAPI lifespan + Long-Running Task Pattern + run state machine
- SSE with heartbeat, reconnection, disconnect detection
- OTel 4-level span hierarchy as EventBus subscriber
- PII redaction layer before telemetry export
- structlog with OTel trace correlation
- AI Golden Signals (4 Prometheus metrics)
- CachedProvider with in-process TTLCache + CacheBackend protocol
- MemoryManager protocol stub (L1 only)
- Custom InputValidator/OutputValidator extending ContractRegistry
- Token Bucket rate limiter
- CostAggregator EventBus subscriber with dual-layer budgets
- Budget delegation tracking for sub-agents
- Recursive loop detection (max turns + anomaly flags)
- SPRT-based token-efficient testing framework
- Chaos engineering (timeouts, rate limits, partial responses)
- CI/CD coverage gates

### Phase 4 (defer)
- Redis L2 backplane + Pub/Sub cache invalidation
- Warm tier semantic deduplication (0.85/0.98 thresholds)
- Cold tier HNSW vector retrieval
- PromptShield SLM deployment
- Provider failover with strategy switching
- Subinterpreters for CPU-bound parallelism
- Full chargeback billing system
- Kubernetes OTel Collector Target Allocator
