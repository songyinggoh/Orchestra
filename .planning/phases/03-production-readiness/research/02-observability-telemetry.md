# Phase 3: Observability & Telemetry - Research

**Researched:** 2026-03-10
**Domain:** OpenTelemetry SDK, GenAI semantic conventions, Prometheus metrics, structured logging
**Confidence:** HIGH

## Summary

Orchestra already has a well-structured EventBus (18 typed events) and a `RichTraceRenderer` for live console output. The observability phase adds production-grade distributed tracing, metrics, and log correlation using OpenTelemetry as the unified standard.

The key architectural insight is that Orchestra should NOT auto-instrument LLM provider SDKs (OpenLLMetry already does that). Instead, Orchestra should emit its own spans for **workflow execution**, **node execution**, **agent handoffs**, and **parallel fan-out**, enriching them with `gen_ai.*` semantic convention attributes from its existing event data. The EventBus subscriber pattern already used by `RichTraceRenderer` is the correct integration point -- an `OTelTraceSubscriber` follows the same pattern.

**Primary recommendation:** Use OpenTelemetry Python SDK 1.40.x with OTLP/HTTP exporters, implement a single `OTelTraceSubscriber` class that subscribes to EventBus and emits spans following the official `gen_ai.*` semantic conventions, and integrate trace IDs into the existing structlog setup. Defer metrics and collector infrastructure to Phase 4.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `opentelemetry-api` | 1.40.0 | Tracing API | Official OTel Python API, stable |
| `opentelemetry-sdk` | 1.40.0 | TracerProvider | Official SDK implementation |
| `opentelemetry-exporter-otlp-proto-http` | 1.40.x | OTLP/HTTP span export | HTTP is simpler than gRPC, no grpcio dep, firewall-friendly |
| `structlog` | >=24.0 | Structured logging (ALREADY in deps) | Already used by Orchestra |

### Supporting (Deferred to Phase 4)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `opentelemetry-exporter-prometheus` | 0.49b0 | Prometheus /metrics endpoint | Phase 4 metrics |
| `opentelemetry-exporter-otlp-proto-grpc` | 1.40.x | OTLP/gRPC export | High-throughput production |
| `opentelemetry-instrumentation-asyncio` | 0.49b0 | Auto-instrument asyncio tasks | Context propagation in parallel fan-out |
| `opentelemetry-semantic-conventions` | 0.49b0 | `gen_ai.*` attribute constants | Type-safe attribute names |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| OTLP/HTTP | OTLP/gRPC | gRPC is faster for high volume but adds `grpcio` (~50MB) dependency; HTTP works everywhere |
| Console exporter | OTLP metrics exporter | Console/File exporters provide zero-infra observability for Phase 3 |
| Jaeger all-in-one | Grafana Tempo | Jaeger is simpler for dev; Tempo is better for prod. Defer both to Phase 4. |

### Installation

```bash
# Core (add to pyproject.toml [project.optional-dependencies])
pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp-proto-http opentelemetry-semantic-conventions
```

**pyproject.toml optional dependency group:**
```toml
[project.optional-dependencies]
telemetry = [
    "opentelemetry-api>=1.30",
    "opentelemetry-sdk>=1.30",
    "opentelemetry-exporter-otlp-proto-http>=1.30",
    "opentelemetry-semantic-conventions>=0.45b0",
]
```

## Architecture Patterns

### Recommended Project Structure
```
src/orchestra/observability/
    __init__.py          # Public API: setup_telemetry(), get_tracer()
    logging.py           # EXISTING: structlog setup (extend with trace_id)
    console.py           # EXISTING: RichTraceRenderer
    tracing.py           # NEW: OTelTraceSubscriber, TracerProvider setup
    metrics.py           # NEW: OTelMetricsSubscriber, MeterProvider setup
    _otel_setup.py       # NEW: Provider initialization, exporter config
    _span_attributes.py  # NEW: gen_ai.* attribute mapping helpers
```

### Pattern 1: EventBus Subscriber for OTel Spans

**What:** An `OTelTraceSubscriber` class that subscribes to EventBus (same pattern as `RichTraceRenderer`) and translates Orchestra events into OpenTelemetry spans.

**When to use:** Always -- this is the primary integration point.

**Span hierarchy:**
```
Workflow Span (root)                    # ExecutionStarted -> ExecutionCompleted
  +-- Node Span (child)                # NodeStarted -> NodeCompleted
  |     +-- LLM Call Span (child)      # LLMCalled (single event, no start/end)
  |     +-- Tool Call Span (child)     # ToolCalled (single event)
  +-- Node Span (child)
  |     +-- LLM Call Span
  +-- Parallel Fan-Out Span            # ParallelStarted -> ParallelCompleted
        +-- Node Span (child, concurrent)
        +-- Node Span (child, concurrent)
```

**Example:**
```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.semconv.attributes.gen_ai_attributes import (
    GEN_AI_OPERATION_NAME,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_SYSTEM,
    GEN_AI_USAGE_INPUT_TOKENS,
    GEN_AI_USAGE_OUTPUT_TOKENS,
)


class OTelTraceSubscriber:
    """Subscribes to EventBus and emits OpenTelemetry spans."""

    def __init__(self, tracer: trace.Tracer) -> None:
        self._tracer = tracer
        self._workflow_spans: dict[str, trace.Span] = {}   # run_id -> span
        self._node_spans: dict[str, trace.Span] = {}       # node_id -> span
        self._node_contexts: dict[str, trace.Context] = {} # node_id -> context

    def on_event(self, event: "AnyEvent") -> None:
        """Sync EventBus callback -- mirrors RichTraceRenderer.on_event."""
        try:
            self._dispatch(event)
        except Exception:
            pass  # Never crash the workflow

    def _on_execution_started(self, event: "ExecutionStarted") -> None:
        span = self._tracer.start_span(
            name=f"workflow.{event.workflow_name}",
            attributes={
                "orchestra.run_id": event.run_id,
                "orchestra.workflow_name": event.workflow_name,
            },
        )
        ctx = trace.set_span_in_context(span)
        self._workflow_spans[event.run_id] = span
        self._workflow_contexts[event.run_id] = ctx

    def _on_llm_called(self, event: "LLMCalled") -> None:
        parent_ctx = self._node_contexts.get(event.node_id)
        with self._tracer.start_as_current_span(
            name="gen_ai.chat",
            context=parent_ctx,
            attributes={
                GEN_AI_OPERATION_NAME: "chat",
                GEN_AI_REQUEST_MODEL: event.model,
                GEN_AI_SYSTEM: _provider_from_model(event.model),
                GEN_AI_USAGE_INPUT_TOKENS: event.input_tokens,
                GEN_AI_USAGE_OUTPUT_TOKENS: event.output_tokens,
                "gen_ai.usage.cost": event.cost_usd,
                "gen_ai.response.finish_reason": event.finish_reason,
            },
        ) as span:
            span.set_attribute("orchestra.node_id", event.node_id)
            span.set_attribute("orchestra.agent_name", event.agent_name)

    def _on_execution_completed(self, event: "ExecutionCompleted") -> None:
        span = self._workflow_spans.pop(event.run_id, None)
        if span:
            span.set_attribute("orchestra.total_tokens", event.total_tokens)
            span.set_attribute("orchestra.total_cost_usd", event.total_cost_usd)
            span.set_attribute("orchestra.status", event.status)
            if event.status == "failed":
                span.set_status(trace.StatusCode.ERROR)
            span.end()
```

### Pattern 2: Metrics via OTel MeterProvider

**What:** Counters, histograms, and up-down-counters for LLM operations, following `gen_ai.*` metric semantic conventions.

**Example:**
```python
from opentelemetry import metrics

meter = metrics.get_meter("orchestra")

# Following gen_ai semantic conventions
token_usage = meter.create_counter(
    name="gen_ai.client.token.usage",
    description="Number of tokens used in GenAI operations",
    unit="{token}",
)

operation_duration = meter.create_histogram(
    name="gen_ai.client.operation.duration",
    description="GenAI operation duration",
    unit="s",
    # OTel semconv recommended buckets for GenAI
    # [0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64, 1.28, 2.56, 5.12, 10.24, 20.48, 40.96, 81.92]
)

# Orchestra-specific metrics
workflow_counter = meter.create_counter(
    name="orchestra.workflow.count",
    description="Number of workflow executions",
    unit="{workflow}",
)

node_duration = meter.create_histogram(
    name="orchestra.node.duration",
    description="Node execution duration",
    unit="s",
)

error_counter = meter.create_counter(
    name="orchestra.errors",
    description="Number of errors occurred",
    unit="{error}",
)
```

### Pattern 3: Structlog + Trace ID Correlation

**What:** Inject `trace_id` and `span_id` from the active OpenTelemetry context into every structlog log record.

**Example:**
```python
import structlog
from opentelemetry import trace


def add_otel_context(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Structlog processor that injects trace_id and span_id."""
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx.is_valid:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict


# In setup_logging(), add to shared_processors BEFORE the renderer:
shared_processors = [
    structlog.contextvars.merge_contextvars,
    add_otel_context,  # <-- NEW: inject trace_id, span_id
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.UnicodeDecoder(),
]
```

### Pattern 4: TracerProvider + Exporter Setup

**What:** A `setup_telemetry()` function that configures TracerProvider with OTLP exporter, using environment variables for endpoint configuration.

**Example:**
```python
import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME


def setup_telemetry(
    service_name: str = "orchestra",
    endpoint: str | None = None,
    use_console: bool = False,
) -> None:
    """Initialize OpenTelemetry tracing.

    Reads OTEL_EXPORTER_OTLP_ENDPOINT env var if endpoint not provided.
    Default: http://localhost:4318 (OTLP/HTTP).
    """
    resource = Resource.create({SERVICE_NAME: service_name})
    
    tracer_provider = TracerProvider(resource=resource)
    
    if use_console:
        tracer_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    else:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        endpoint = endpoint or os.getenv(
            "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318"
    )
        tracer_provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
        )
    
    trace.set_tracer_provider(tracer_provider)
```

### Pattern 5: Async Context Propagation in Parallel Fan-Out

**What:** When Orchestra uses `asyncio.gather()` for parallel node execution, trace context must propagate correctly to each concurrent task.

**Key insight:** Python 3.11+ `asyncio.Task` copies `contextvars` at task creation time. If tasks are created inside an active span context, child spans are automatically linked. The critical requirement is that `asyncio.create_task()` is called while the parent span context is active.

**Example:**
```python
from opentelemetry import context as otel_context


async def execute_parallel_nodes(nodes: list[Node], parent_ctx: otel_context.Context):
    """Execute nodes in parallel, propagating trace context."""
    # Attach parent context so create_task copies it
    token = otel_context.attach(parent_ctx)
    try:
        tasks = [asyncio.create_task(execute_node(node)) for node in nodes]
        # Each task inherits parent_ctx via contextvars copy
        results = await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        otel_context.detach(token)
    return results
```

### Anti-Patterns to Avoid

- **Creating coroutines outside span context then wrapping in tasks later:** Context is copied at `create_task()` time, not coroutine creation. Always create tasks inside the span context.
- **Using SimpleSpanProcessor in production:** It blocks on export. Always use `BatchSpanProcessor`.
- **Setting span attributes after `span.end()`:** OTel ignores post-end mutations silently. Set all attributes before calling `end()`.
- **Storing spans in module-level globals:** Spans are request-scoped. Use dict keyed by run_id/node_id (as shown in the subscriber pattern).
- **Importing OTel exporter packages unconditionally:** Guard with try/except ImportError so the framework works without telemetry deps installed.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Trace context propagation | Custom context threading | OpenTelemetry Context API + contextvars | W3C tracecontext standard, works with all backends |
| Span batching + export | Custom queue + HTTP sender | BatchSpanProcessor | Handles batching, retry, backpressure, shutdown |
| Prometheus /metrics endpoint | Custom HTTP handler | opentelemetry-exporter-prometheus | Handles all metric types, text format serialization |
| LLM SDK instrumentation | Monkey-patching provider SDKs | OpenLLMetry instrumentors | Maintained by community, covers all providers |
| Trace ID generation | uuid4 for trace IDs | OTel SDK generates W3C-compliant 128-bit trace IDs | Interoperable with all tracing backends |
| Log-trace correlation | Custom log middleware | structlog processor + OTel context | One processor, zero coupling |

**Key insight:** OpenTelemetry is the industry standard for this entire domain. Building custom solutions would create vendor lock-in and miss ecosystem compatibility with Jaeger, Grafana, Datadog, etc.

## Common Pitfalls

### Pitfall 1: Import Errors When Telemetry Not Installed
**What goes wrong:** Framework crashes if OTel packages are not installed.
**Why it happens:** Unconditional imports at module level.
**How to avoid:** Guard all OTel imports with try/except, make telemetry an optional dependency group. Use a `_OTEL_AVAILABLE` flag pattern (same as `_RICH_AVAILABLE` in console.py).
**Warning signs:** ImportError in production when user hasn't installed `[telemetry]` extra.

### Pitfall 2: Span Lifecycle Mismatch with Event-Sourced Architecture
**What goes wrong:** Orchestra events are fire-and-forget (no explicit start/end pairing for LLMCalled, ToolCalled). OTel spans need explicit start + end.
**Why it happens:** LLMCalled is a single event emitted after the call completes, carrying duration_ms. It does not have a separate "started" event.
**How to avoid:** For single-event operations (LLMCalled, ToolCalled), create the span and immediately end it, backdating the start time using `start_time` parameter: `tracer.start_span(name=..., start_time=computed_start_ns)` then `span.end(end_time=event.timestamp)`.
**Warning signs:** All LLM spans show 0ms duration.

### Pitfall 3: Context Loss in asyncio.gather
**What goes wrong:** Parallel node spans become root spans instead of children of the workflow span.
**Why it happens:** If `asyncio.create_task()` is called outside the active span context, the task gets a copy of the wrong context.
**How to avoid:** Explicitly `otel_context.attach(parent_ctx)` before creating tasks, detach after.
**Warning signs:** Traces in Jaeger show disconnected spans instead of a tree.

### Pitfall 4: High Cardinality Metric Labels
**What goes wrong:** Prometheus scrape becomes slow or OOM.
**Why it happens:** Using run_id or node_id as metric labels creates unbounded cardinality.
**How to avoid:** Only use bounded labels: `model`, `provider`, `operation`, `status`, `workflow_name`. Never use run_id, trace_id, or node_id as metric labels.
**Warning signs:** Prometheus memory usage grows linearly with request count.

### Pitfall 5: Exporting Sensitive Data in Spans
**What goes wrong:** LLM prompts/completions appear in trace backends.
**Why it happens:** Naively copying all event fields to span attributes.
**How to avoid:** Never set `gen_ai.prompt` or `gen_ai.completion` span attributes by default. Make it opt-in via `ORCHESTRA_TRACE_CONTENT=true` environment variable. Only export structured metadata (tokens, cost, model, duration).
**Warning signs:** PII visible in Jaeger UI.

### Pitfall 6: Prometheus Exporter in Multiprocessing
**What goes wrong:** Metrics are incorrect or missing.
**Why it happens:** The `opentelemetry-exporter-prometheus` does not support multiprocessing.
**How to avoid:** For multiprocess deployments, use OTLP metrics export to an OTel Collector instead of the direct Prometheus exporter.
**Warning signs:** Metrics reset on worker restart, missing data.

## GenAI Semantic Conventions (Detailed Reference)

### Span Attributes (gen_ai.*)

| Attribute | Type | Requirement | Description |
|-----------|------|-------------|-------------|
| `gen_ai.operation.name` | string | Required | Operation: `chat`, `text_completion`, `embeddings` |
| `gen_ai.system` | string | Required | Provider: `openai`, `anthropic`, `google_ai`, `ollama` |
| `gen_ai.request.model` | string | Required | Model name as requested (e.g., `gpt-4o`, `claude-3-opus`) |
| `gen_ai.response.model` | string | Recommended | Model name as returned by provider |
| `gen_ai.usage.input_tokens` | int | Recommended | Input token count (includes cached tokens) |
| `gen_ai.usage.output_tokens` | int | Recommended | Output token count |
| `gen_ai.response.finish_reasons` | string[] | Recommended | Finish reasons array |

**Orchestra-specific attributes (custom namespace):**

| Attribute | Type | Description |
|-----------|------|-------------|
| `orchestra.run_id` | string | Workflow execution ID |
| `orchestra.workflow_name` | string | Name of the workflow graph |
| `orchestra.node_id` | string | Current node being executed |
| `orchestra.agent_name` | string | Agent name within the node |
| `orchestra.node_type` | string | `agent`, `function`, `subgraph` |
| `orchestra.cost_usd` | float | Cost in USD for this operation |

### Metric Instruments (gen_ai.*)

| Metric Name | Type | Unit | Description |
|-------------|------|------|-------------|
| `gen_ai.client.token.usage` | Counter | `{token}` | Total tokens consumed |
| `gen_ai.client.operation.duration` | Histogram | `s` | Duration of GenAI operations |
| `orchestra.workflow.duration` | Histogram | `s` | End-to-end workflow duration |
| `orchestra.workflow.count` | Counter | `{workflow}` | Workflow executions |
| `orchestra.node.duration` | Histogram | `s` | Per-node execution duration |
| `orchestra.errors.count` | Counter | `{error}` | Error occurrences |
| `orchestra.tool.duration` | Histogram | `s` | Tool call duration |
| `orchestra.handoff.count` | Counter | `{handoff}` | Agent-to-agent handoffs |

**Recommended histogram buckets for GenAI operations:**
`[0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64, 1.28, 2.56, 5.12, 10.24, 20.48, 40.96, 81.92]`

**Metric label dimensions (bounded cardinality):**
`gen_ai.operation.name`, `gen_ai.system`, `gen_ai.request.model`, `orchestra.workflow_name`, `orchestra.node_type`

## Trace Sampling Strategy

### Recommendation: Custom Composite Sampler

LLM workloads are expensive and relatively low-volume compared to web request tracing. The default should be to sample everything (100%), with opt-in reduction.

```python
from opentelemetry.sdk.trace.sampling import (
    ParentBasedTraceIdRatio,
    ALWAYS_ON,
    TraceIdRatioBased,
)


def create_sampler(sample_rate: float = 1.0) -> "Sampler":
    """Create a sampler for Orchestra.

    For LLM workloads:
    - Default 1.0 (100%) because LLM calls are expensive and infrequent
    - Errors are ALWAYS sampled (via parent-based propagation)
    - Use 0.1 (10%) only for very high-throughput batch processing
    """
    if sample_rate >= 1.0:
        return ALWAYS_ON
    return ParentBasedTraceIdRatio(sample_rate)
```

**Head-based vs tail-based:**
- **Head-based** (SDK-side): Use `ParentBasedTraceIdRatio`. Simple, no infrastructure needed. Good default.
- **Tail-based** (Collector-side): Requires an OTel Collector with `tail_sampling` processor. Useful for "always keep errors" and "always keep slow traces" policies. Recommend as an advanced/optional configuration, not default.

**Recommendation for Orchestra:** Default to `ALWAYS_ON` (sample rate 1.0). LLM calls cost real money; you always want to see them. Let users override via `OTEL_TRACES_SAMPLER=parentbased_traceidratio` and `OTEL_TRACES_SAMPLER_ARG=0.1` environment variables.

## Docker Compose Setup (Local Dev)

**DEFERRED TO PHASE 4**: Infrastructure for Jaeger, Tempo, Prometheus, and Grafana is deferred to Phase 4. For Phase 3, use the `ConsoleSpanExporter` or a remote OTLP target (e.g., Honeycomb/Datadog/Langfuse).

## EventBus to OTel Mapping (Complete)

| Orchestra Event | OTel Span Name | Span Kind | Key Attributes |
|----------------|----------------|-----------|----------------|
| `ExecutionStarted` | `workflow.{name}` | INTERNAL | `orchestra.run_id`, `orchestra.workflow_name` |
| `NodeStarted` / `NodeCompleted` | `node.{node_id}` | INTERNAL | `orchestra.node_id`, `orchestra.node_type` |
| `LLMCalled` | `gen_ai.chat` | CLIENT | All `gen_ai.*` attributes |
| `ToolCalled` | `tool.{tool_name}` | INTERNAL | `orchestra.tool_name`, args (truncated) |
| `EdgeTraversed` | (span event on parent) | -- | `from_node`, `to_node`, `edge_type` |
| `ParallelStarted` / `ParallelCompleted` | `parallel.{source_node}` | INTERNAL | `target_nodes` |
| `HandoffInitiated` / `HandoffCompleted` | `handoff.{from}->{to}` | INTERNAL | `from_agent`, `to_agent`, `reason` |
| `ErrorOccurred` | (status + event on current span) | -- | `error_type`, `error_message` |
| `SecurityViolation` | (span event, sets ERROR status) | -- | `violation_type`, `details` |

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `gen_ai.prompt` / `gen_ai.completion` | `gen_ai.input.messages` / `gen_ai.output.messages` (as events) | OTel semconv v1.38.0, 2025 | Old attributes deprecated; use span events for message content |
| Jaeger-specific Thrift protocol | OTLP native (Jaeger 1.35+) | 2023 | No need for Jaeger-specific exporters; OTLP works directly |
| Custom LLM tracing (Langfuse, W&B) | OTel GenAI semantic conventions | 2024-2025 | Standardized; all major platforms now accept OTel GenAI spans |
| Individual provider instrumentation | OpenLLMetry + OTel semconv | 2024-2025 | Community-maintained, covers OpenAI/Anthropic/Google/Ollama |

**Deprecated/outdated:**
- `gen_ai.prompt` and `gen_ai.completion` span attributes: removed in semconv v1.38.0. Use `gen_ai.input.messages` / `gen_ai.output.messages` span events instead.
- `opentelemetry-exporter-jaeger`: Deprecated. Use `opentelemetry-exporter-otlp-proto-http` -- Jaeger accepts OTLP natively.
- Zipkin exporter: Still works but OTLP is preferred for new integrations.

## Open Questions

1. **Content capture opt-in granularity**
   - What we know: `gen_ai.prompt`/`gen_ai.completion` are deprecated; content goes in span events now.
   - What's unclear: What level of content capture Orchestra users will want (none / metadata-only / full prompts+responses).
   - Recommendation: Default to no content capture. Add `ORCHESTRA_OTEL_CAPTURE_CONTENT=true` env var for full capture using span events.

2. **Cost tracking in metrics vs spans**
   - What we know: `gen_ai.usage.cost` is not in the official semconv (only tokens are). Orchestra tracks `cost_usd` on events.
   - What's unclear: Whether to add cost as a custom metric or wait for semconv to standardize it.
   - Recommendation: Add `orchestra.cost_usd` as a custom span attribute and a separate `orchestra.cost` counter metric. Prefix with `orchestra.` to avoid semconv conflicts.

3. **Multi-exporter support**
   - What we know: TracerProvider supports multiple SpanProcessors, each with its own exporter.
   - What's unclear: Whether users need simultaneous export to multiple backends.
   - Recommendation: Support via standard OTel Collector configuration. Don't build multi-exporter config into Orchestra; let users run an OTel Collector if they need fan-out.

## Sources

### Primary (HIGH confidence)
- [OpenTelemetry GenAI Semantic Conventions - Spans](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/) - Full attribute reference
- [OpenTelemetry GenAI Semantic Conventions - Metrics](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-metrics/) - Metric instruments and buckets
- [OpenTelemetry GenAI Agent Spans](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/) - Agent/framework span conventions
- [OpenTelemetry Python Exporters](https://opentelemetry.io/docs/languages/python/exporters/) - Package names, setup patterns
- [OpenTelemetry Python SDK - trace](https://opentelemetry-python.readthedocs.io/en/latest/sdk/trace.html) - TracerProvider, BatchSpanProcessor API
- [OTLP Exporter Configuration](https://opentelemetry.io/docs/languages/sdk-configuration/otlp-exporter/) - Environment variables
- [opentelemetry-sdk 1.40.0 on PyPI](https://pypi.org/project/opentelemetry-sdk/) - Latest version
- [opentelemetry-exporter-prometheus on PyPI](https://pypi.org/project/opentelemetry-exporter-prometheus/) - Prometheus exporter

### Secondary (MEDIUM confidence)
- [OpenLLMetry GitHub](https://github.com/traceloop/openllmetry) - LLM instrumentation packages
- [OpenTelemetry for GenAI blog post](https://opentelemetry.io/blog/2024/otel-generative-ai/) - GenAI SIG overview
- [Deprecated gen_ai.prompt issue](https://github.com/traceloop/openllmetry/issues/3515) - Attribute deprecation details
- [structlog frameworks docs](https://www.structlog.org/en/stable/frameworks.html) - OTel integration patterns
- [Grafana Tempo Docker setup](https://grafana.com/docs/tempo/latest/set-up-for-tracing/setup-tempo/deploy/locally/docker-compose/) - Local dev compose
- [Fix asyncio context loss](https://oneuptime.com/blog/post/2026-02-06-fix-python-asyncio-context-loss/view) - Context propagation fix

### Tertiary (LOW confidence)
- [Datadog OTel GenAI support](https://www.datadoghq.com/blog/llm-otel-semantic-convention/) - Vendor adoption signal
- [Langfuse OTel integration](https://langfuse.com/integrations/native/opentelemetry) - Alternative platform compatibility

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - OpenTelemetry Python SDK is stable (1.40.0), packages verified on PyPI
- Architecture: HIGH - EventBus subscriber pattern proven by existing RichTraceRenderer; gen_ai semconv is official OTel spec
- GenAI semantic conventions: MEDIUM - Spec is marked "Development" stability; attribute names may evolve but core structure is stable
- Pitfalls: HIGH - Well-documented in OTel community, verified across multiple sources
- Docker setup: HIGH - Jaeger all-in-one is standard dev setup, OTLP ports are stable

**Research date:** 2026-03-10
**Valid until:** 2026-04-10 (30 days -- OTel SDK is stable; semconv may get minor updates)
