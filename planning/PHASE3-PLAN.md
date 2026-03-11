# Phase 3: Production Readiness - Implementation Plan

**Goal:** Transform the core engine into a production-grade service ecosystem with robust serving, observability, caching, and safety mechanisms.
**Timeline:** Weeks 13-18 (6 Weeks)
**Status:** Planned

---

## Strategy: Layered Production Hardening

We will execute Phase 3 in **4 Waves**, focusing first on the serving layer and observability, then moving to performance, governance, and finally reliability.

### Wave 1: Serving & Observability (Weeks 13-14)
**Focus:** Exposing agents as services and seeing what they do.

*   **3.1 FastAPI Server**: Build a production-ready REST API to deploy graphs.
    *   *Endpoints*: `POST /runs`, `GET /runs/{id}`, `POST /runs/{id}/resume`, `GET /runs/{id}/stream`.
    *   *Features*: Async streaming responses (SSE), Pydantic models for inputs/outputs, standard error handling.
*   **3.2 OpenTelemetry (OTel) Integration**: Replace/augment console logging with standard tracing.
    *   *Scope*: Trace context propagation across nodes, span attributes for LLM calls (tokens, latency). 
    *   *Defer*: Prometheus metrics and OTel Collector/Jaeger/Tempo infrastructure (use OTLP with remote backend or local Console exporter).

### Wave 2: Performance & Memory (Week 15)
**Focus:** Speed and state management at scale.

*   **3.3 LLM Response Cache**:
    *   *Implementation*: Implement an in-process `TTLCache` (via `cachetools`) for LLM responses.
    *   *Defer*: Redis integration to Phase 4.
*   **3.4 Simple Memory Manager**:
    *   *Memory Interface*: Define a simplified `MemoryManager` protocol with 2 core methods: `store(key, value)` and `retrieve(key)`.
    *   *Defer*: Multi-tier (hot/cold) logic and vector search to Phase 4.

### Wave 3: Governance & Operations (Weeks 16-17)
**Focus:** Control, safety, and business metrics.

*   **3.5 Guardrails**:
    *   *Input/Output Guards*: Middleware to validate LLM inputs and outputs against safety policies or schema constraints (e.g., PII redaction, topic adherence).
    *   *Fail-safe defaults*: Strategies for handling guardrail violations (retry, fallback, refusal).
*   **3.6 Cost Tracking**:
    *   *Token Counting*: rigorous counting of prompt/completion tokens per step.
    *   *Budgeting*: Soft/hard limits per workflow run or tenant.
    *   *Reporting*: Aggregated cost views.

### Wave 4: Reliability & Testing (Week 18)
**Focus:** Ensuring the system holds up under pressure.

*   **3.7 Advanced Test Harnesses**:
    *   *Concurrency Testing*: Verify thread safety and async correctness under load.
    *   *Chaos Testing*: Simulate LLM timeouts and provider outages via decorators.
    *   *Regression Suite*: Full end-to-end suite running against the FastAPI endpoints.
    *   *Simplification*: Use fixed-sample fault injection instead of complex SPRT (Sequential Probability Ratio Test) framework.

---

## Detailed Task Breakdown

### Wave 1: Serving & Observability

#### 3.1 FastAPI Server
- [ ] **Scaffold Application**: Setup `src/orchestra/server/app.py` with FastAPI.
- [ ] **API Schema Definition**: Define Pydantic models for `RunRequest`, `RunResponse`, `StreamEvent`.
- [ ] **Graph Lifecycle Manager**: Component to load/compile graphs on startup or dynamically.
- [ ] **Run Execution Endpoints**: Implement async route handlers that interact with the `CompiledGraph`.
- [ ] **Streaming Support**: Implement Server-Sent Events (SSE) for real-time token/event streaming.

#### 3.2 OpenTelemetry
- [ ] **Instrumentation Setup**: Configure `opentelemetry-sdk` and `opentelemetry-instrumentation-fastapi`.
- [ ] **Custom Tracers**: Add spans to `Graph.run()`, `Node.execute()`, and `LLMProvider.chat()`.
- [ ] **Context Propagation**: Ensure trace IDs flow through async tasks.
- [ ] **Defer**: Docker Compose setup for Jaeger/Tempo.

### Wave 2: Performance & Memory

#### 3.3 LLM Cache
- [x] **TTLCache Client**: Implementation of `CacheBackend` protocol using `cachetools.TTLCache`.
- [x] **Caching Layer**: Decorator or middleware to cache deterministic LLM calls.

#### 3.4 Simple Memory
- [x] **Memory Interface**: Define `MemoryManager` protocol with `store` and `retrieve` methods.
- [x] **Simple Implementation**: In-memory `dict` or local file-based storage implementation.

### Wave 3: Governance & Operations

#### 3.5 Guardrails
- [ ] **Guardrail Protocol**: Interface for `Validator` components.
- [ ] **Pre-computation Hooks**: Validate user input before it hits the graph.
- [ ] **Post-computation Hooks**: Validate LLM output before it returns to user.

#### 3.6 Cost Tracking
- [ ] **Token Counter**: Integrate `tiktoken` or provider-specific counters.
- [ ] **Cost Model**: Configuration file mapping models to cost-per-token.
- [ ] **Usage Store**: Persist usage stats to the `EventStore` metadata.

### Wave 4: Reliability

#### 3.7 Advanced Testing
- [ ] **Load Test Script**: `locust` script to hammer the API.
- [ ] **Fault Injection**: Decorators to randomly inject errors in Provider calls during test runs.

---

## Success Criteria
1.  **API Live**: Can `curl` a workflow run and receive a streamed response.
2.  **Visible Traces**: Can view trace data (via Console or OTLP exporter).
3.  **Persisted State**: Resuming a workflow after a server restart works seamlessly.
4.  **Cost Awareness**: Every run response includes a calculated cost field.
