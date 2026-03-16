# Phase 3: Tree of Thoughts Analysis

**Strategy:** BFS across 5 independent questions, breadth=3, beam=2, depth=3
**Date:** 2026-03-10

---

## Q1: Wave Ordering — Is the proposed order optimal?

### Winner [0.90]: Keep current order (API + OTel together in Wave 1)

**Rationale:** OTel is a third EventBus subscriber — not a structural change. The `RichTraceRenderer` already subscribes to the bus; OTel integration follows the identical pattern. Bundling FastAPI + OTel caps Wave 1's blast radius while delivering the two most visible features together.

**Pruned alternatives:**
- OTel-first, API second [0.55] — defers the primary deliverable, blocks Wave 4 regression suite
- Guardrails-first [0.40] — existing `PromptInjectionAgent`, `SecurityViolation`, Tool ACL provide baseline safety

**Refinement:** Within Wave 3, implement guardrails before cost tracking (guardrails need more design thought; cost tracking is mostly aggregation of existing data).

---

## Q2: Scope Risk — Is Phase 3 too ambitious?

### Winner [0.88]: Manageable with three deferrals

**Defer to Phase 4:**
- Redis pub/sub (no distributed deployment until Phase 4)
- Full multi-tier memory with vector search (simplified to 2-method protocol in Phase 3)
- Prometheus metrics and OTel Collector/Jaeger/Tempo infrastructure

**Keep in Phase 3:**

| Feature | Value | Complexity | Verdict |
|---------|-------|-----------|---------|
| 3.1 FastAPI Server | High (primary deliverable) | Medium | Keep |
| 3.2 OTel | High (production requirement) | Low | Keep (deferred infra) |
| 3.3 LLM Response Cache | Medium | Low (TTLCache) | Keep |
| 3.4 MemoryManager protocol | Medium (interface design) | Low | Keep (2-method) |
| 3.5 Guardrails | High (safety requirement) | Medium | Keep |
| 3.6 Cost Tracking | High (already partially done) | Low | Keep |
| 3.7 Advanced Testing | High | Medium | Keep (cut SPRT) |

**Effective scope:** 5 solid deliverables + 2 thin interfaces. Well within 6-week parallel-wave cadence.

---

## Q3: Integration Complexity — How well does EventBus/EventStore support Phase 3?

### Winner [0.95]: Architecture is well-prepared

**Required changes to CompiledGraph:** Only two, both additive:
1. OTel context propagation in `_execute_parallel` (~3 lines)
2. `output_validators` hook in `_execute_agent_node` (for guardrails)

**Zero changes needed to:**
- EventStore protocol
- Event model (18 types)
- EventBus subscription mechanism
- Storage backends

**Integration paths:**
- **OTel:** EventBus subscriber (same pattern as RichTraceRenderer)
- **Cache:** `CachedProvider` wrapping `LLMProvider.complete()` — no engine changes
- **Cost:** Aggregation of existing `LLMCalled` event data
- **Input guardrails:** Node factory pattern (existing `make_injection_guard_node`)
- **Output guardrails:** Additive hook in `_execute_agent_node`

---

## Q4: Redis Necessity — Essential or premature?

### Winner [0.92]: In-process caching for Phase 3, Redis in Phase 4

**Quantified trade-off:**

| Dimension | Redis (Phase 3) | cachetools/diskcache |
|-----------|-----------------|---------------------|
| Infrastructure added | Redis server, pool, serialization | Zero |
| Development time | 2-3 days | 0.5 days |
| Phase 4 upgrade cost | None | ~30 lines (RedisCacheBackend) |
| Value delivered (single-process) | Same | Same |

**Key insight:** distributed deployment doesn't exist until Phase 4 (Ray executor). Redis adds infrastructure cost with zero incremental value in a single-process model. Design a `CacheBackend` protocol so the swap is mechanical.

---

## Q5: Guardrails — Build custom vs integrate existing?

### Winner [0.88]: Build custom GuardrailMiddleware (~150 lines)

**Why not NeMo Guardrails [0.20]:** colang DSL incompatible with graph-based execution model. Imposes its own conversation model.

**Why not Guardrails AI [0.60]:** Heavy dependencies (OpenAI SDK, litellm, validators). Structured output validation already handled by `LLMProvider.complete(output_type=...)` via Pydantic. Incremental value over custom implementation is low.

**Custom approach:**
- `InputValidator` and `OutputValidator` protocols
- `ValidationResult` with `action: allow | retry | fallback | refuse`
- Reuse existing `SecurityViolation` and `OutputRejected` events
- Extends `src/orchestra/security/` — natural home

---

## Revised Phase 3 Wave Structure

```
Wave 1 — Serving & Observability (Weeks 13–14)
  3.1  FastAPI server: POST /runs, GET /runs/{id}, POST /runs/{id}/resume,
       GET /runs/{id}/stream (SSE)
  3.2  OTel: EventBus subscriber + context propagation fix + Docker Compose Jaeger

Wave 2 — Caching & Interface Stubs (Week 15)
  3.3  CachedProvider with cachetools/diskcache + CacheBackend protocol
  3.4  MemoryManager protocol stub (interface only, no tiering logic)

Wave 3 — Governance & Operations (Weeks 16–17)
  3.5  GuardrailMiddleware: InputValidator + OutputValidator protocols
  3.6  CostAggregator: subscriber + budget limits + API response field

Wave 4 — Reliability & Testing (Week 18)
  3.7  Concurrency tests, fault injection, E2E regression suite,
       chaos scoped to provider timeout simulation only
```
