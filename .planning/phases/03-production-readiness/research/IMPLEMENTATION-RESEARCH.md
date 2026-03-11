# Phase 3: Implementation Research

**Phase:** 3 - Production Readiness
**Confidence:** HIGH
**Date:** 2026-03-10

---

## 1. FastAPI + SSE Implementation

### Library Choice
- Use `sse-starlette` (not FastAPI native SSE) for heartbeat, disconnect detection, and graceful shutdown
- `@app.on_event("startup")` is **deprecated** — use `lifespan` context manager exclusively
- RunManager must decouple run lifecycle from HTTP request lifecycle via `asyncio.create_task()`

### Run Lifecycle Pattern
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize: graph registry, event stores, LLM clients
    app.state.graph_registry = GraphRegistry()
    app.state.run_manager = RunManager()
    yield
    # Cleanup: cancel pending runs, close connections
    await app.state.run_manager.shutdown()
```

### SSE Streaming
```python
from sse_starlette.sse import EventSourceResponse

async def event_generator(run_id: str, request: Request):
    queue = asyncio.Queue()
    event_bus.subscribe(run_id, queue.put)
    try:
        while True:
            if await request.is_disconnected():
                break
            event = await asyncio.wait_for(queue.get(), timeout=15.0)
            yield {"event": event.type, "data": event.json(), "id": str(event.sequence)}
    except asyncio.TimeoutError:
        yield {"comment": "ping"}  # Heartbeat
```

### Key Implementation Details
- `POST /runs` returns `202 Accepted` with `run_id` — NOT `201 Created`
- Run state machine: `PENDING → RUNNING → (INTERRUPTED | COMPLETED | FAILED)`
- SSE headers: `X-Accel-Buffering: no`, `Cache-Control: no-cache`
- Client reconnection: check `Last-Event-ID` header → replay missed events
- Disconnect detection: `request.is_disconnected()` → checkpoint as INTERRUPTED

---

## 2. OpenTelemetry GenAI Integration

### Current Status
- GenAI semantic conventions remain **experimental** (v0.49b0 with SDK 1.40.0)
- Agent span naming: `invoke_agent {agent_name}` with `SpanKind.INTERNAL`
- Metric histogram buckets are defined in the spec

### Span Hierarchy (4 levels)
```
workflow.run (Root, INTERNAL)
  └─ agent.turn (INTERNAL)
      ├─ llm.chat (CLIENT)
      └─ tool.invocation (CLIENT or INTERNAL)
```

### Implementation as EventBus Subscriber
```python
class OTelSubscriber:
    def __init__(self, tracer_provider):
        self.tracer = tracer_provider.get_tracer("orchestra")

    async def handle_event(self, event: Event):
        match event:
            case ExecutionStarted(): self._start_root_span(event)
            case NodeStarted(): self._start_child_span(event)
            case LLMCalled(): self._record_llm_span(event)
            case ToolCalled(): self._record_tool_span(event)
            case ErrorOccurred(): self._record_error(event)
```

### Defensive Pattern
- Centralize all `gen_ai.*` attribute strings in one module (`src/orchestra/observability/otel_attributes.py`) to absorb future breaking changes in the experimental spec

### asyncio Context Propagation
```python
from opentelemetry import context

def run_with_trace_context(coro):
    ctx = context.get_current()
    async def wrapped():
        token = context.attach(ctx)
        try:
            return await coro
        finally:
            context.detach(token)
    return asyncio.create_task(wrapped())
```

---

## 3. structlog + OTel Correlation

- A single structlog processor (~10 lines) injects `trace_id` and `span_id` from current OTel span into every log record
- No new dependencies needed — structlog is already a core dependency
- Enables bidirectional trace↔log correlation

```python
def inject_otel_context(logger, method_name, event_dict):
    span = trace.get_current_span()
    if span.is_recording():
        ctx = span.get_span_context()
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict
```

---

## 4. Caching Implementation

### CachedProvider Pattern (~50 lines)
```python
class CacheBackend(Protocol):
    async def get(self, key: str) -> Optional[Any]: ...
    async def set(self, key: str, value: Any, ttl: int = 3600) -> None: ...

class InMemoryCacheBackend:
    def __init__(self, maxsize: int = 256, ttl: int = 3600):
        self._cache = cachetools.TTLCache(maxsize=maxsize, ttl=ttl)
```

### Cache Key Strategy
- SHA-256 of `(model, messages, temperature, max_tokens)`
- Only cache `temperature=0` calls by default
- Default TTL: 1 hour

### Phase 4 Upgrade Path
- `CacheBackend` protocol → `RedisCacheBackend` swaps in mechanically (~30 lines)

---

## 5. Budget-Aware Model Routing

### Dual-Layer Pattern (~80 lines custom)
- **Soft limit:** Triggers model downgrade (e.g., gpt-4o → gpt-4o-mini)
- **Hard limit:** Triggers circuit breaker (kill the run)
- No existing library handles this — custom implementation required

### Budget Delegation
- Orchestrator assigns budget to sub-agents
- Unused credits return to central pool after sub-task completion
- Track consumption at node level via EventBus `LLMCalled` events

### Cost Registry
- Vendored LiteLLM pricing JSON preferred over `tokencost` library
- Updatable without code changes (JSON file or env config)

---

## 6. SPRT Testing

### Library Status
- No maintained Python SPRT library exists (`sprt` package: ~60 weekly downloads, inactive)
- Custom implementation is ~50 lines using `math.log`

### Implementation
```python
class SPRTEvaluator:
    def __init__(self, alpha=0.05, beta=0.05, p0=0.9, p1=0.7):
        self.upper = math.log((1 - beta) / alpha)
        self.lower = math.log(beta / (1 - alpha))

    def update(self, success: bool) -> Literal["pass", "fail", "inconclusive"]:
        # Update log-likelihood ratio
        # Return verdict when thresholds crossed
```

### Three-Valued Verdict
- **Pass:** Statistical confidence agent meets reliability threshold
- **Fail:** Statistical confidence agent is below threshold
- **Inconclusive:** Insufficient evidence — need more trials

---

## 7. Locust SSE Testing

- Use `sseclient-py` with `stream=True` on Locust HTTP client
- Pattern: POST to start run → consume SSE stream in same task
- gevent handles concurrency naturally

---

## Conflict Resolutions

| Source | Recommendation | Override | Reason |
|--------|---------------|----------|--------|
| STACK.md | Redis/redisvl for Wave 2 | In-process caching only | Key decision: Redis deferred to Phase 4 |
| STACK.md | Guardrails AI for Wave 3 | Custom build | Key decision: avoid heavy framework deps |
| STACK.md | tokencost library | Vendored LiteLLM pricing JSON | More comprehensive, updatable without dep |
| Server PDF | Python 3.14 subinterpreters | asyncio.TaskGroup (3.11+) | Subinterpreters too bleeding-edge |
