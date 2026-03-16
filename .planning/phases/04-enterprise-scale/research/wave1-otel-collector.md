# Wave 1 Research: OpenTelemetry Collector 2-Tier Architecture

**Task:** T-4.2 (Kubernetes + gVisor/Kata + KEDA) — OTel Collector deployment
**Sources:** OpenTelemetry Collector docs (opentelemetry.io), Tail Sampling Processor (GitHub), Phase 4 research
**Date:** 2026-03-12

---

## 1. Collector Architecture Overview

### Component Model
The OTel Collector is a vendor-agnostic proxy that receives, processes, and exports telemetry data.

```
Receivers → Processors → Exporters
         (pipeline)
```

- **Receivers:** Ingest data (OTLP, Prometheus, Jaeger, etc.)
- **Processors:** Transform data (batch, filter, sample, redact)
- **Exporters:** Send data (OTLP, Prometheus Remote Write, Jaeger, Loki)
- **Extensions:** Health check, pprof, zpages, bearer token auth

### Distributions
- **Core:** Minimal (OTLP receiver/exporter, basic processors)
- **Contrib:** Everything (~200+ components, ~200MB image)
- **Custom (recommended):** Built with `ocb` (OpenTelemetry Collector Builder), only includes needed components (~50MB)

---

## 2. 2-Tier Deployment Pattern

### Architecture
```
┌─────────────────────────────────────────────────────┐
│  Node 1                    Node 2                    │
│  ┌──────────────┐          ┌──────────────┐         │
│  │ Orchestra Pod │          │ Orchestra Pod │         │
│  │  OTLP→:4318  │          │  OTLP→:4318  │         │
│  └──────┬───────┘          └──────┬───────┘         │
│         │                         │                  │
│  ┌──────▼───────┐          ┌──────▼───────┐         │
│  │ Agent Collector│          │ Agent Collector│        │
│  │  (DaemonSet)  │          │  (DaemonSet)  │        │
│  └──────┬───────┘          └──────┬───────┘         │
│         │                         │                  │
│         └────────────┬────────────┘                  │
│                      │                               │
│              ┌───────▼────────┐                      │
│              │ Gateway Collector│                     │
│              │  (Deployment)   │                     │
│              │  2-3 replicas   │                     │
│              └───────┬────────┘                      │
│                      │                               │
│              ┌───────▼────────┐                      │
│              │  Backends       │                     │
│              │  Jaeger/Tempo   │                     │
│              │  Prometheus     │                     │
│              │  Loki           │                     │
│              └────────────────┘                      │
└─────────────────────────────────────────────────────┘
```

### Why 2-Tier?
| Concern | Agent Tier | Gateway Tier |
|---------|-----------|-------------|
| Deployment | DaemonSet (1 per node) | Deployment (2-3 replicas) |
| Purpose | Local collection, batching | Sampling, redaction, export |
| Tail sampling | No (needs full traces) | Yes (all spans routed here) |
| PII redaction | No (Gateway handles) | Yes |
| Resource impact | Lightweight | Heavier (sampling state) |

---

## 3. Agent Tier Configuration

### Kubernetes: DaemonSet
```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: otel-agent
  namespace: orchestra-system
spec:
  selector:
    matchLabels:
      app: otel-agent
  template:
    metadata:
      labels:
        app: otel-agent
    spec:
      containers:
        - name: otel-agent
          image: ghcr.io/orchestra/otel-collector:custom
          args: ["--config=/etc/otel/config.yaml"]
          ports:
            - containerPort: 4317  # OTLP gRPC
              hostPort: 4317
            - containerPort: 4318  # OTLP HTTP
              hostPort: 4318
            - containerPort: 13133 # Health check
          resources:
            requests:
              cpu: 100m
              memory: 256Mi
            limits:
              cpu: 500m
              memory: 512Mi
          volumeMounts:
            - name: config
              mountPath: /etc/otel
      volumes:
        - name: config
          configMap:
            name: otel-agent-config
```

### Agent Collector Config
```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    send_batch_size: 512
    send_batch_max_size: 1024
    timeout: 5s

  memory_limiter:
    check_interval: 1s
    limit_mib: 400
    spike_limit_mib: 100

  resourcedetection:
    detectors: [env, system, gcp, eks]
    timeout: 5s

exporters:
  # Load-balanced export to Gateway (critical for tail sampling)
  loadbalancing:
    protocol:
      otlp:
        endpoint: otel-gateway-headless:4317
        tls:
          insecure: true
    resolver:
      dns:
        hostname: otel-gateway-headless.orchestra-system.svc.cluster.local
        port: 4317
    routing_key: "traceID"  # All spans of same trace → same gateway

extensions:
  health_check:
    endpoint: 0.0.0.0:13133

service:
  extensions: [health_check]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, resourcedetection, batch]
      exporters: [loadbalancing]
    metrics:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [loadbalancing]
    logs:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [loadbalancing]
```

### Critical: Load Balancing Exporter
The agent tier **must** use `loadbalancingexporter` (not plain `otlp`) for traces. It routes by trace ID via consistent hashing to a headless gateway Service. This ensures all spans of a trace reach the same gateway instance — **required for tail sampling to work correctly**.

---

## 4. Gateway Tier Configuration

### Kubernetes: Deployment + Headless Service
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: otel-gateway
  namespace: orchestra-system
spec:
  replicas: 2
  selector:
    matchLabels:
      app: otel-gateway
  template:
    metadata:
      labels:
        app: otel-gateway
    spec:
      containers:
        - name: otel-gateway
          image: ghcr.io/orchestra/otel-collector:custom
          args: ["--config=/etc/otel/config.yaml"]
          ports:
            - containerPort: 4317
          resources:
            requests:
              cpu: 500m
              memory: 1Gi
            limits:
              cpu: "2"
              memory: 2Gi
---
apiVersion: v1
kind: Service
metadata:
  name: otel-gateway-headless
  namespace: orchestra-system
spec:
  clusterIP: None  # Headless — required for load balancing exporter DNS resolution
  selector:
    app: otel-gateway
  ports:
    - port: 4317
      targetPort: 4317
```

### Gateway Collector Config
```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317

processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 1500
    spike_limit_mib: 400

  # --- PII Redaction (3-layer defense) ---

  # Layer 1: Redaction processor (whitelist-then-filter)
  redaction:
    allow_all_keys: false
    allowed_keys:
      - "service.name"
      - "service.version"
      - "orchestra.*"
      - "http.method"
      - "http.status_code"
      - "http.route"
      - "rpc.method"
      - "db.system"
      - "gen_ai.system"
      - "gen_ai.request.model"
      - "gen_ai.usage.*"
    blocked_values:
      - '\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b'  # Credit cards
      - '\b\d{3}-\d{2}-\d{4}\b'                       # SSN
      - '\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'  # Email
      - '\b(sk|pk|api)[-_][A-Za-z0-9]{20,}\b'         # API keys

  # Layer 2: Attributes processor (targeted delete/hash)
  attributes/pii:
    actions:
      - key: gen_ai.prompt
        action: delete
      - key: gen_ai.completion
        action: delete
      - key: db.statement
        action: delete
      - key: exception.stacktrace
        action: delete
      - key: enduser.id
        action: hash

  # Layer 3: Transform processor (OTTL surgical redaction)
  transform/pii:
    trace_statements:
      - context: span
        statements:
          - replace_pattern(attributes["http.url"], "password=[^&]*", "password=***")
          - replace_pattern(attributes["http.url"], "token=[^&]*", "token=***")

  # --- Tail Sampling ---
  tail_sampling:
    decision_wait: 15s
    num_traces: 50000
    expected_new_traces_per_sec: 100
    policies:
      # Always keep errors
      - name: keep-errors
        type: status_code
        status_code:
          status_codes: [ERROR]

      # Keep slow traces (>10s)
      - name: keep-slow-traces
        type: latency
        latency:
          threshold_ms: 10000

      # Keep expensive operations
      - name: keep-expensive
        type: ottl_condition
        ottl_condition:
          error_mode: ignore
          span: ['attributes["orchestra.cost_usd"] != nil and Double(attributes["orchestra.cost_usd"]) > 0.10']

      # Keep agent handoffs
      - name: keep-handoffs
        type: string_attribute
        string_attribute:
          key: orchestra.event_type
          values: [handoff, delegation, escalation]

      # Keep security events
      - name: keep-security-events
        type: ottl_condition
        ottl_condition:
          error_mode: ignore
          span: ['attributes["orchestra.security_violation"] != nil']

      # Sample 20% of remaining
      - name: probabilistic-sample
        type: probabilistic
        probabilistic:
          sampling_percentage: 20

      # Rate limit safety net
      - name: rate-limit-safety
        type: rate_limiting
        rate_limiting:
          spans_per_second: 500

  batch:
    send_batch_size: 1024
    timeout: 10s

exporters:
  # Traces → Jaeger/Tempo
  otlp/traces:
    endpoint: tempo.orchestra-system:4317
    tls:
      insecure: true

  # Metrics → Prometheus
  prometheusremotewrite:
    endpoint: http://prometheus.orchestra-system:9090/api/v1/write
    resource_to_telemetry_conversion:
      enabled: true

  # Logs → Loki (optional)
  loki:
    endpoint: http://loki.orchestra-system:3100/loki/api/v1/push

extensions:
  health_check:
    endpoint: 0.0.0.0:13133
  zpages:
    endpoint: 0.0.0.0:55679

service:
  extensions: [health_check, zpages]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, redaction, attributes/pii, transform/pii, tail_sampling, batch]
      exporters: [otlp/traces]
    metrics:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [prometheusremotewrite]
    logs:
      receivers: [otlp]
      processors: [memory_limiter, redaction, attributes/pii, batch]
      exporters: [loki]
```

---

## 5. Tail Sampling Deep Dive

### How It Works
1. Gateway buffers all spans for a trace until `decision_wait` expires
2. Evaluates policies in order (first match wins for AND composite; OR for top-level)
3. If any policy matches → keep entire trace
4. If no policy matches → drop trace

### Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `decision_wait` | 15s | Must be > longest expected trace duration |
| `num_traces` | 50000 | Max concurrent traces in memory |
| `expected_new_traces_per_sec` | 100 | Helps pre-allocate |

### Memory Sizing
- Each buffered trace: ~10-20KB (depends on span count)
- 50,000 traces × 20KB = ~1GB
- Gateway needs 1-2GB memory for tail sampling

### Policy Types Available (17 total)

| Policy | Description |
|--------|-------------|
| `always_sample` | Keep everything (testing only) |
| `latency` | Keep traces exceeding threshold |
| `numeric_attribute` | Filter on numeric span attributes |
| `probabilistic` | Random sampling by percentage |
| `status_code` | Filter by OK/ERROR/UNSET |
| `string_attribute` | Match string span attributes |
| `rate_limiting` | Max spans per second |
| `span_count` | Filter by number of spans in trace |
| `trace_state` | Filter by W3C tracestate |
| `boolean_attribute` | Filter on boolean attributes |
| `ottl_condition` | Custom OTTL expressions |
| `and` | Composite AND of sub-policies |
| `composite` | Weighted composite sampling |

---

## 6. PII Redaction Strategy (3-Layer Defense)

### Layer 1: Redaction Processor (Whitelist — Fail-Secure)
- Only explicitly allowed attribute keys pass through
- Unknown attributes are **dropped** (fail-secure)
- Blocked value patterns mask sensitive data in remaining attributes
- **This is the primary defense** — if misconfigured, data is dropped not leaked

### Layer 2: Attributes Processor (Targeted Delete/Hash)
- Explicitly deletes known-sensitive keys (`gen_ai.prompt`, `db.statement`)
- Hashes PII identifiers (`enduser.id`) — preserves cardinality for metrics
- Defense-in-depth: catches attributes that passed Layer 1 allowlist

### Layer 3: Transform Processor (OTTL Surgical)
- Pattern-based replacement within attribute values
- Catches embedded secrets in URLs, query strings
- Last resort: handles edge cases the other layers miss

### Processing Order
```
Incoming span → Redaction (whitelist) → Attributes (delete/hash) → Transform (pattern) → Tail Sampling → Export
```

**Important:** PII redaction MUST happen before tail sampling. If a span is sampled and exported with PII, it's too late.

---

## 7. Custom Collector Build

### Why Custom?
- Contrib image: ~200MB, ~200+ components, large attack surface
- Custom image: ~50MB, only 8 processors + 4 exporters

### Builder Config (`builder-config.yaml`)
```yaml
dist:
  name: orchestra-otel-collector
  description: Custom OTel Collector for Orchestra
  output_path: ./build
  otelcol_version: 0.115.0

receivers:
  - gomod: go.opentelemetry.io/collector/receiver/otlpreceiver v0.115.0

processors:
  - gomod: go.opentelemetry.io/collector/processor/batchprocessor v0.115.0
  - gomod: go.opentelemetry.io/collector/processor/memorylimiterprocessor v0.115.0
  - gomod: github.com/open-telemetry/opentelemetry-collector-contrib/processor/tailsamplingprocessor v0.115.0
  - gomod: github.com/open-telemetry/opentelemetry-collector-contrib/processor/redactionprocessor v0.115.0
  - gomod: github.com/open-telemetry/opentelemetry-collector-contrib/processor/attributesprocessor v0.115.0
  - gomod: github.com/open-telemetry/opentelemetry-collector-contrib/processor/transformprocessor v0.115.0
  - gomod: github.com/open-telemetry/opentelemetry-collector-contrib/processor/resourcedetectionprocessor v0.115.0
  - gomod: github.com/open-telemetry/opentelemetry-collector-contrib/processor/filterprocessor v0.115.0

exporters:
  - gomod: go.opentelemetry.io/collector/exporter/otlpexporter v0.115.0
  - gomod: github.com/open-telemetry/opentelemetry-collector-contrib/exporter/loadbalancingexporter v0.115.0
  - gomod: github.com/open-telemetry/opentelemetry-collector-contrib/exporter/prometheusremotewriteexporter v0.115.0
  - gomod: github.com/open-telemetry/opentelemetry-collector-contrib/exporter/lokiexporter v0.115.0

extensions:
  - gomod: go.opentelemetry.io/collector/extension/healthcheckextension v0.115.0
  - gomod: go.opentelemetry.io/collector/extension/zpagesextension v0.115.0
  - gomod: go.opentelemetry.io/collector/extension/pprofextension v0.115.0
```

### Build
```bash
# Install ocb
go install go.opentelemetry.io/collector/cmd/builder@v0.115.0

# Build custom collector
builder --config=builder-config.yaml

# Dockerize
docker build -t ghcr.io/orchestra/otel-collector:custom .
```

---

## 8. No Application Code Changes Needed

Orchestra's existing OTLP/HTTP exporter (from Phase 3 OTel integration) sends to `localhost:4318`. The DaemonSet agent exposes this via `hostPort`. The entire 2-tier architecture is **purely infrastructure** — no changes to `src/orchestra/observability/`.

```
Orchestra app → OTLP HTTP → localhost:4318 → Agent DaemonSet → Gateway → Backend
                (existing)    (hostPort)      (new infra)      (new infra)
```

---

## 9. Resource Sizing Guide

| Component | CPU Request | CPU Limit | Memory Request | Memory Limit |
|-----------|-----------|---------|--------------|------------|
| Agent (DaemonSet) | 100m | 500m | 256Mi | 512Mi |
| Gateway (Deployment) | 500m | 2 | 1Gi | 2Gi |

### Scaling Guidelines
- 1 Gateway replica per ~500 spans/sec throughput
- Tail sampling with 50K traces needs ~500MB-1GB
- Add replicas if `otelcol_processor_tail_sampling_sampling_decision_timer_latency` > 1s

### Self-Monitoring Metrics
- `otelcol_receiver_accepted_spans`: Incoming span rate
- `otelcol_processor_tail_sampling_count_traces_sampled`: Sampling hit rate
- `otelcol_exporter_sent_spans`: Outgoing span rate
- `otelcol_processor_batch_timeout_trigger_send`: Batch flush frequency

---

## 10. Resolved Decisions

### Redaction Processor Maturity (Gap 7 — RESOLVED)
- **Decision:** Use attributes + transform processors as primary PII defense; redaction processor as optional enhancement
- Attributes processor (delete/hash) and Transform processor (OTTL patterns) are `stable`
- Redaction processor is `alpha` — enable via Helm value `otel.redaction.enabled: true`
- If redaction processor breaks on upgrade, attributes + transform layers still protect PII
- Gateway pipeline order: `memory_limiter → redaction (optional) → attributes/pii → transform/pii → tail_sampling → batch`

## 11. Remaining Open Questions

1. **Trace ID routing correctness:** Verify loadbalancingexporter consistent hashing works with NATS-originated trace IDs (not HTTP-originated)
2. **Multi-tenant traces:** If Orchestra supports multiple tenants, need tenant-aware sampling policies
3. **Cost:** Gateway replicas + storage backends add infrastructure cost. Need budget estimate.
4. **Existing Phase 3 OTel:** Verify Phase 3's OTLP exporter config is compatible with hostPort DaemonSet pattern

---

## 11. Cross-References

- **K8s DaemonSet/Deployment:** See `wave1-k8s-helm-keda-terraform.md` for Helm integration
- **NATS trace context:** See `wave1-nats-jetstream.md` for trace propagation through JetStream
- **Existing OTel setup:** `src/orchestra/observability/` (Phase 3)
- **Prior research:** `02-observability-telemetry.md` (Phase 3 research)
