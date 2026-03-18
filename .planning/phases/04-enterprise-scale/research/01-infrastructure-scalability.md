# Phase 4 Research: Infrastructure & Scalability Topics

**Date:** 2026-03-11
**Scope:** 10 topics from `planning/PHASE4-TOPICS.md` — Infrastructure & Scalability section
**Context:** Orchestra framework already has graph engine, event-sourced persistence (SQLite/Postgres), FastAPI server, OpenTelemetry instrumentation, in-process caching, and cost tracking. Phase 4 adds distributed/enterprise capabilities.

---

## 1. Ray Core/Serve — Distributed Agent Execution

### Current Version & Status
- **Ray 2.54.0** (latest stable, Feb 2025+)
- Install: `pip install "ray[serve]"`
- License: Apache 2.0
- GitHub: [ray-project/ray](https://github.com/ray-project/ray) — 37k+ stars

### asyncio Integration

Ray natively integrates with asyncio. When an actor class has at least one `async def` method, Ray automatically recognizes it as an `AsyncActor`. All async methods run inside a single Python event loop per actor. Ray integrates with popular async frameworks like aiohttp and aioredis.

```python
import ray

@ray.remote
class AgentWorker:
    def __init__(self, agent_config: dict):
        self.agent = create_agent(agent_config)

    async def execute_step(self, step_input: dict) -> dict:
        """Runs inside Ray's per-actor asyncio event loop."""
        result = await self.agent.process(step_input)
        return result

# Create actor with max 64 concurrent async tasks
worker = AgentWorker.options(max_concurrency=64).remote(config)
result_ref = worker.execute_step.remote({"task": "summarize", "data": payload})
result = await result_ref
```

**Key config — `max_concurrency`:** Controls how many async tasks can be multiplexed on the actor's event loop simultaneously. Default is 1000, but for agent workloads with LLM calls, 32-128 is more practical.

### Ray Serve for Agent Endpoints

Ray Serve provides native FastAPI integration via `@serve.ingress`, allowing Orchestra's existing FastAPI app to be wrapped directly:

```python
from ray import serve
from fastapi import FastAPI

app = FastAPI()

@serve.deployment(num_replicas=2, max_ongoing_requests=100)
@serve.ingress(app)
class OrchestraAgentService:
    def __init__(self):
        self.engine = GraphEngine()

    @app.post("/run")
    async def run_workflow(self, request: dict):
        return await self.engine.execute(request)

serve.run(OrchestraAgentService.bind())
```

Ray Serve also supports **deployment graphs** for composing multiple agents. Multiple deployments can reference each other via `bind()`, enabling a DAG of agent services with independent scaling per deployment.

### Integration Approach for Orchestra

Create a `RayGraphExecutor` implementing the same interface as the in-process executor. Key decisions:

- **Actor-per-agent** (best for stateful agents with conversation history) vs **actor-per-step** (best for stateless transformations)
- **State serialization:** Orchestra's event-sourced persistence already externalizes state, so Ray's serialization requirement is naturally satisfied
- **Error handling:** Use `max_retries` and `retry_exceptions` on remote calls
- **Placement groups:** Co-locate frequently communicating agents to reduce serialization overhead

### Pitfalls
- Object store has 100MB default limit per object — large agent context windows may need chunking
- `asyncio.get_event_loop()` inside Ray actors returns Ray's managed loop — never create new loops
- Ray Serve's autoscaler and Orchestra's own scaling logic may conflict — pick one scaling authority
- Cold start for actors is ~50-200ms — pre-warm critical agent pools

---

## 1.1 Multi-Tenant Isolation — Hard Sandboxing

### Rationale: The "Soft Isolation" Trap
Standard Python process isolation (Subinterpreters/Ray) is vulnerable to side-channel attacks (Spectre/Meltdown) and OS-level escapes. In a multi-tenant enterprise environment, a single data leak between tenants is a terminal event for the platform. "Soft" isolation is insufficient for high-security Ray workers.

### Implementation: Wasm & gVisor/Kata

| Technology | Role | Benefit |
|------------|------|---------|
| **Wasm (WebAssembly)** | Tool Execution | Restricts agent tools to a mathematically proven sandbox with zero access to the host FS/Network unless explicitly granted. |
| **gVisor** | Ray Worker Runtime | User-space kernel (written in Go) that intercepts syscalls, providing a "strong" sandbox for Python processes with low overhead. |
| **Kata Containers** | High-Security Workers | Lightweight VMs (using QEMU/Firecracker) for the most sensitive workloads, providing hardware-level isolation. |

### Recommendation for Orchestra
1. **P0 Action:** Mandate **Wasm (using `wasmtime-py`)** for all third-party or user-provided tool execution.
2. **P0 Action:** Deploy Ray workers inside **gVisor (runsc)** by default in production Kubernetes clusters.

---

## 2. NATS JetStream — Async Agent-to-Agent Messaging

### Current Version & Status
- **nats-py 2.14.0** (latest on PyPI)
- **NATS Server 2.10.x** (JetStream built-in, enabled by default)
- Install: `pip install nats-py`
- License: Apache 2.0
- GitHub: [nats-io/nats.py](https://github.com/nats-io/nats.py)

### Core Concepts
- **Streams:** Append-only message logs, stored on disk or memory, with configurable retention (limits, interest, workqueue)
- **Consumers:** Named subscription points on streams, tracking delivery position per consumer
- **Subjects:** Hierarchical topic names (e.g., `orchestra.agent.*.tasks`)
- **Acknowledgment policies:** `none`, `all`, or `explicit` (per-message ack required)

### Python async Patterns

**Publishing with ack (guarantees storage):**
```python
import nats

async def publish_task(nc, agent_id: str, task: dict):
    js = nc.jetstream()
    await js.add_stream(
        name="agent-tasks",
        subjects=["orchestra.tasks.>"],
        retention="workqueue",   # Each message consumed exactly once
        storage="file",
    )
    ack = await js.publish(
        f"orchestra.tasks.{agent_id}",
        json.dumps(task).encode(),
        headers={"Nats-Msg-Id": task["id"]},  # Idempotent dedup
    )
    return ack.seq
```

**Pull consumer (preferred for agent workers):**
```python
async def agent_worker(nc, agent_id: str):
    js = nc.jetstream()
    psub = await js.pull_subscribe(
        f"orchestra.tasks.{agent_id}",
        durable="worker-1",
        config=nats.js.api.ConsumerConfig(
            ack_policy="explicit",
            max_deliver=3,
            ack_wait=30,
        ),
    )
    while True:
        try:
            msgs = await psub.fetch(batch=10, timeout=5)
            for msg in msgs:
                try:
                    task = json.loads(msg.data)
                    await process_task(task)
                    await msg.ack()
                except Exception:
                    await msg.nak(delay=5)  # Retry after 5s
        except nats.errors.TimeoutError:
            continue
```

**Push consumer (for event fan-out):**
```python
async def event_listener(nc):
    js = nc.jetstream()
    sub = await js.subscribe("orchestra.events.>", durable="monitor")
    async for msg in sub.messages:
        await handle_event(json.loads(msg.data))
        await msg.ack()
```

### Comparison: NATS vs Redis Streams vs Kafka

| Feature | NATS JetStream | Redis Streams | Apache Kafka |
|---------|---------------|---------------|--------------|
| **Latency** | Sub-millisecond | Sub-10ms | 5-50ms (batching) |
| **Throughput** | Millions/sec | High (memory-bound) | Millions/sec |
| **Persistence** | File or memory | AOF/RDB | Log segments |
| **At-least-once** | Yes (explicit ack) | Yes (XACK) | Yes |
| **Exactly-once** | Dedup headers | No native | Idempotent producer |
| **Cluster setup** | Trivial (single binary) | Redis Cluster (complex) | ZooKeeper/KRaft |
| **Ops overhead** | Very low | Medium | High |
| **Python client** | nats-py (async-native) | redis-py/aioredis | confluent-kafka-python |
| **Scale-to-zero (KEDA)** | Yes | Manual | No (brokers always on) |
| **Memory footprint** | ~30MB server | ~50MB+ | 1GB+ JVM heap |

**Recommendation:** NATS JetStream is the clear winner for agent messaging — sub-millisecond latency, native async Python client, minimal ops overhead, built-in clustering with gossip-based server discovery, and KEDA scaler for K8s autoscaling.

### Key Configuration Decisions
- **Retention:** `workqueue` for task distribution (consumed once), `limits` for event streams (bounded replay)
- **Storage:** `file` for production, `memory` for development
- **Max deliver:** 3-5 retries with `nak(delay=N)` exponential backoff
- **Deduplication:** `Nats-Msg-Id` header + stream `duplicate_window`
- **Multi-tenancy:** NATS accounts for tenant isolation — each tenant gets its own subject namespace

### Pitfalls
- Pull consumers must handle `TimeoutError` gracefully
- Message size limit is 1MB default — serialize large payloads as references
- `ack_wait` must be longer than the longest agent task execution time
- NATS clustering requires at least 3 nodes for Raft consensus

---

## 2.1 NATS Persistence Leakage — End-to-End Encryption (E2EE)

### Rationale: The "At-Least-Once" Privacy Risk
NATS JetStream provides "at-least-once" delivery by persisting messages to disk. If the NATS cluster is compromised, all historical agent "chatter" (including PII/secrets) is exposed. Relying solely on TLS (encryption-in-transit) or disk encryption (encryption-at-rest) leaves the data "hot" in the NATS memory/process space.

### Implementation: DIDComm & Ephemeral Keys
Implement **End-to-End Encryption (E2EE)** at the application layer before publishing to NATS.

- **Protocol:** Use **DIDComm v2** (built on JWE/ECDH-ES) for payload encryption.
- **Key Management:** Use ephemeral keys derived from Agent DIDs (see Research Report 02).
- **Orchestra Integration:** The `NatsProvider` must automatically encrypt payloads using the recipient agent's public key (resolved via DID) and sign with the sender's private key.

### Recommendation for Orchestra
- **P0 Action:** Implement a `SecureNatsProvider` wrapper that handles JWE encryption/decryption transparently, ensuring NATS only ever stores opaque ciphertexts.

---

## 3. Kubernetes Operators (kopf)

### Current Version & Status
- **kopf 1.38.0** (released May 2025, latest on PyPI)
- Install: `pip install kopf`
- License: MIT
- GitHub: [nolar/kopf](https://github.com/nolar/kopf)
- Status: Stable, maintenance mode (no major new features, but regular Python/K8s version updates)

### CRD Design for Agent Deployments

```yaml
apiVersion: orchestra.io/v1
kind: OrchestraAgent
metadata:
  name: summarizer-agent
  namespace: production
spec:
  agentType: summarizer
  model: gpt-4o
  maxConcurrency: 10
  replicas: 2
  autoscaling:
    enabled: true
    minReplicas: 1
    maxReplicas: 10
    targetQueueDepth: 50
  resources:
    requests: { cpu: "500m", memory: "512Mi" }
    limits: { cpu: "2", memory: "2Gi" }
  natsSubject: "orchestra.tasks.summarizer"
status:
  phase: Running
  replicas: 2
  activeTaskCount: 7
  lastHeartbeat: "2026-03-11T10:30:00Z"
```

### Kopf Handler Implementation

```python
import kopf

@kopf.on.create('orchestra.io', 'v1', 'orchestraagents')
async def create_agent(spec, name, namespace, logger, **kwargs):
    """Create K8s resources when an OrchestraAgent CR is created."""
    deployment = build_agent_deployment(name, namespace, spec)
    api.create_namespaced_deployment(namespace, deployment)
    if spec.get('autoscaling', {}).get('enabled'):
        create_keda_scaled_object(name, namespace, spec)
    return {"phase": "Running"}

@kopf.on.update('orchestra.io', 'v1', 'orchestraagents')
async def update_agent(spec, name, namespace, diff, logger, **kwargs):
    for op, field, old, new in diff:
        if field == ('spec', 'model'):
            patch_agent_deployment(api, name, namespace, spec)
    return {"phase": "Updating"}

@kopf.on.delete('orchestra.io', 'v1', 'orchestraagents')
async def delete_agent(name, namespace, logger, **kwargs):
    logger.info(f"Cleaning up agent: {name}")

@kopf.timer('orchestra.io', 'v1', 'orchestraagents', interval=30)
async def health_check(spec, name, namespace, status, patch, **kwargs):
    active_tasks = await get_nats_queue_depth(spec['natsSubject'])
    patch.status['activeTaskCount'] = active_tasks
```

### Key Design Decisions
1. **Owner references** on all created resources for automatic K8s garbage collection
2. **Finalizers** via kopf for cleanup of external resources (NATS streams, database state)
3. **Status subresource** for operational state (`kubectl get orchestraagents`)
4. **Async handlers** — kopf natively supports `async def`, fitting Orchestra's async codebase

### Pitfalls
- kopf is in maintenance mode — stable but no major new features expected
- Handlers must be idempotent — `create` may be called multiple times on operator restart
- CRD schema should use OpenAPI v3 validation to catch invalid configurations early

---

## 4. Kubernetes Deployment

### Recommended Stack
- **Infrastructure provisioning:** Terraform (cluster, networking, IAM)
- **Application packaging:** Helm charts (templated K8s manifests)
- **Environment overlays:** Kustomize (dev/staging/prod customization)
- **GitOps delivery:** ArgoCD or FluxCD

### Architecture Pattern: "Terraform for Platform, GitOps for Apps"

Terraform provisions the K8s cluster, VPC, IAM, RDS, and installs operators (KEDA, OTel, cert-manager). ArgoCD/FluxCD continuously deploys application manifests: Orchestra server, agent workers, NATS, KEDA ScaledObjects, OTel Collectors, Ingress, ServiceMonitors, NetworkPolicies.

### Health Checks for Agent Workers

Three probe types are essential:

```yaml
containers:
  - name: orchestra-worker
    livenessProbe:        # Restarts container if agent process is hung
      httpGet: { path: /health/live, port: 8080 }
      initialDelaySeconds: 10
      periodSeconds: 15
    readinessProbe:       # Removes from service if not ready
      httpGet: { path: /health/ready, port: 8080 }
      initialDelaySeconds: 5
      periodSeconds: 10
    startupProbe:         # Allows 150s for model loading/warm-up
      httpGet: { path: /health/startup, port: 8080 }
      failureThreshold: 30
      periodSeconds: 5
```

Liveness checks event loop responsiveness. Readiness checks NATS + DB connections. Startup checks whether initialization (model loading) is complete.

### Helm vs Kustomize

| Aspect | Helm | Kustomize |
|--------|------|-----------|
| **Templating** | Go templates (powerful, complex) | Patch-based (simpler) |
| **Package management** | Yes (chart repos) | No |
| **Rollback** | `helm rollback` built-in | Manual via GitOps |
| **Best for** | Distributable packages | Internal team overlays |

**Recommendation:** Use both. Helm for the base chart (distributable to users), Kustomize overlays for internal environments. ArgoCD natively supports both.

### Key Terraform Resources
Use `terraform-aws-modules/eks/aws` (v20+) for EKS provisioning, plus Helm provider releases for KEDA, OTel Operator, and cert-manager.

### Pitfalls
- Do not manage app-level resources (Deployments, ConfigMaps) in Terraform — use Terraform for infra, GitOps for apps
- Use Sealed Secrets or External Secrets Operator for API keys — never in Helm values or git
- Pod Disruption Budgets for agent workers during node upgrades
- Set resource requests AND limits — LLM calls consume variable memory

---

## 5. Horizontal Pod Autoscaling (HPA) / KEDA

### Current Version & Status
- **KEDA 2.19.0** (released January 2026)
- Next: KEDA 2.20.0 (estimated May 2026)
- Install: Helm chart `kedacore/keda`
- License: Apache 2.0

### Why KEDA Over Standard HPA

Agent workers are I/O-bound (waiting for LLM API responses), so CPU/memory metrics stay low even when overloaded. KEDA extends HPA with external metrics (NATS queue depth). Key advantage: KEDA can scale deployments to **zero replicas** and back up on first event.

### KEDA + NATS JetStream Configuration

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: orchestra-worker-scaler
spec:
  scaleTargetRef:
    name: orchestra-worker
  pollingInterval: 5
  cooldownPeriod: 30
  minReplicaCount: 0
  maxReplicaCount: 20
  fallback:
    failureThreshold: 3
    replicas: 2
  triggers:
    - type: nats-jetstream
      metadata:
        natsServerMonitoringEndpoint: "nats.nats.svc.cluster.local:8222"
        account: "$G"
        stream: "agent-tasks"
        consumer: "worker-1"
        lagThreshold: "10"
        activationLagThreshold: "1"
```

You can combine multiple triggers: NATS queue depth (primary), Prometheus custom metrics (active agent tasks), and cron schedules (pre-scale for peak hours).

### Key Configuration Decisions
- **`pollingInterval`:** 5-10s for responsive scaling; default 30s is too slow for agents
- **`cooldownPeriod`:** 30-60s prevents flapping
- **`lagThreshold`:** Based on agent processing time. If agents process 1 msg/sec, threshold of 10 = "10 seconds behind"
- **`activationLagThreshold`:** Set to 1 for immediate wake-up
- **Fallback replicas:** Always set to prevent outage if NATS monitoring is unreachable

### Pitfalls
- NATS JetStream scaler reads from the monitoring HTTP endpoint (port 8222), not the client port — must be exposed
- `minReplicaCount: 0` means cold starts (10-30s for pod startup) — use `1` for latency-sensitive agents
- KEDA and manual `kubectl scale` conflict — use KEDA as sole scaling authority
- Monitor KEDA operator health — if it dies, scaling stops

---

## 6. OTel Collector Target Allocator

### Current Version & Status
- Managed by the **OpenTelemetry Operator**
- CRD API: `opentelemetry.io/v1beta1`
- GitHub: [open-telemetry/opentelemetry-operator](https://github.com/open-telemetry/opentelemetry-operator)

### How It Works

When multiple Orchestra agent workers emit Prometheus metrics, a single Collector cannot scrape all targets efficiently. The Target Allocator:
1. Discovers scrape targets via ServiceMonitors/PodMonitors or static config
2. Distributes targets evenly across a Collector fleet (StatefulSet)
3. Each Collector queries the TA's HTTP API for its assigned targets
4. The OTel Operator auto-rewrites the Collector's Prometheus receiver config

### Configuration

```yaml
apiVersion: opentelemetry.io/v1beta1
kind: OpenTelemetryCollector
metadata:
  name: orchestra-collector
spec:
  mode: statefulset
  replicas: 3
  targetAllocator:
    enabled: true
    allocationStrategy: consistent-hashing
    replicas: 1
    prometheusCR:
      enabled: true
      serviceMonitorSelector: {}
      podMonitorSelector: {}
  config:
    receivers:
      prometheus:
        config:
          scrape_configs:
            - job_name: 'orchestra-agents'
              scrape_interval: 15s
    processors:
      batch: { send_batch_size: 1024, timeout: 5s }
    exporters:
      otlp: { endpoint: "tempo.monitoring.svc:4317" }
    service:
      pipelines:
        metrics:
          receivers: [prometheus]
          processors: [batch]
          exporters: [otlp]
```

### Allocation Strategies

| Strategy | Behavior | Best For |
|----------|----------|----------|
| **consistent-hashing** (default) | Hash-based, minimal redistribution on scale | Large, stable fleets |
| **least-weighted** | Assigns to collector with fewest targets | Frequently scaling fleets |
| **per-node** | One collector per K8s node | DaemonSet-style |

**Recommendation:** `consistent-hashing` for production — minimizes metric gaps during scaling.

### Integration with Orchestra
Purely infrastructure-level — no code changes needed. Orchestra workers already expose `/metrics` via the Prometheus client. Just deploy ServiceMonitors that match the `app: orchestra-worker` label.

### Pitfalls
- Requires `mode: statefulset` — DaemonSet mode is incompatible
- `serviceMonitorSelector: {}` and `podMonitorSelector: {}` MUST be included even if empty
- `least-weighted` causes excessive redistribution during frequent scaling
- Target Allocator itself defaults to a single replica — set `replicas: 2` for HA

---

## 7. Python Subinterpreters (PEP 734)

### Current State
- **PEP 734** implemented in Python 3.13 (`interpreters` module — provisional)
- **Python 3.14** (Oct 2025) added `concurrent.futures.InterpreterPoolExecutor` and `concurrent.interpreters` (graduated)

### InterpreterPoolExecutor (Python 3.14+)

```python
from concurrent.futures import InterpreterPoolExecutor

def process_agent_result(serialized_input: str) -> str:
    """Runs in an isolated subinterpreter — no shared state."""
    import json
    data = json.loads(serialized_input)
    result = heavy_computation(data)
    return json.dumps(result)

async def parallel_processing(tasks: list[dict]) -> list[dict]:
    loop = asyncio.get_running_loop()
    with InterpreterPoolExecutor(max_workers=4) as executor:
        futures = [
            loop.run_in_executor(executor, process_agent_result, json.dumps(t))
            for t in tasks
        ]
        results = await asyncio.gather(*futures)
        return [json.loads(r) for r in results]
```

### Key Limitations (as of Python 3.14)

1. **No shared objects** — data must be serialized (pickle/JSON). Exception: `memoryview` for buffer-protocol objects (numpy arrays) can be passed zero-copy.
2. **Extension module compatibility** — only modules implementing PEP 489 multi-phase init work. Many C extensions with global state are NOT yet compatible (`sqlite3`, many ML frameworks).
3. **No file handle/socket sharing** between interpreters.
4. **Import overhead** — each subinterpreter independently imports all modules.
5. **Arguments must be pickleable** for `InterpreterPoolExecutor`.

### Performance
- Startup: ~10x faster than processes (~1-5ms vs ~50-100ms)
- Memory: ~5-15MB per interpreter vs ~50-100MB per process
- Scaling: Near-linear CPU scaling for truly CPU-bound work

### Assessment for Orchestra

**Good fit:** CPU-bound reasoning chains, sandboxed user-provided agent code, parallel independent sub-tasks.
**Poor fit:** I/O-bound LLM API calls (asyncio is better), tasks needing shared DB connections, tasks using incompatible C extensions.

**Recommendation:** Defer until Python 3.15+ when extension compatibility improves. Use `ProcessPoolExecutor` for CPU-bound work and `asyncio` for I/O-bound work now. `InterpreterPoolExecutor` is a drop-in replacement when ready.

---

## 8. Dynamic Subgraphs

### Patterns from LangGraph and Similar Frameworks

#### Pattern 1: Send API (Dynamic Fan-Out)
The most common pattern. A node examines runtime state and creates `Send` objects dispatching to other nodes with individual payloads:

```python
from langgraph.constants import Send

class WorkflowState(TypedDict):
    items_to_process: List[str]
    processed_results: Annotated[list, add]

def dispatcher_node(state: WorkflowState) -> list[Send]:
    return [
        Send("process_item", {"item": item})
        for item in state["items_to_process"]
    ]
```

The Send API enables dynamic task creation where the number of parallel tasks is determined at runtime, not design time.

#### Pattern 2: Subgraph Composition
Complete, independently compiled graphs embedded as nodes in a parent graph. Subgraphs encapsulate multi-step logic and can be reused across workflows:

```python
research_subgraph = Graph()
research_subgraph.add_node("search", search_node)
research_subgraph.add_node("summarize", summarize_node)
compiled = research_subgraph.compile()

parent_graph.add_node("research", compiled)  # Subgraph as node
```

#### Pattern 3: Conditional Subgraph Selection
Runtime routing to different subgraphs based on state:

```python
def route(state: dict) -> str:
    if state["task_type"] == "research": return "research_subgraph"
    return "general_subgraph"

graph.add_conditional_edges("router", route, {...})
```

#### Pattern 4: Runtime Graph Mutation
Allow nodes to request structural graph changes during execution (add/remove nodes and edges).

### State Communication
Two patterns: **shared state keys** (simpler, coupled) or **wrapper nodes** (isolated, explicit mapping). Shared state via a `messages` key is the most common pattern in multi-agent systems.

### Integration with Orchestra
Orchestra's existing `GraphEngine` needs:
1. A `Send` primitive in the execution model
2. Support for compiled subgraphs as node types
3. A mutation API gated by permissions
4. Graph mutation persistence in the event store for replay/debugging

### Pitfalls
- Dynamic mutation makes debugging harder — log all mutations
- Infinite fan-out risk — limit `Send` targets (e.g., max 100)
- Runtime mutations can create graph cycles — add cycle detection

---

## 9. Sidecar Pattern

### Istio/Envoy Service Mesh (2025-2026)

Two deployment modes:

**Traditional sidecar mode:** Each pod gets an injected Envoy proxy container intercepting all traffic. Provides mTLS, traffic management, observability, and authorization automatically.

**Ambient mesh mode (Recommended, GA since Istio 1.24):** Eliminates per-pod sidecars:
- **ztunnel** — per-node DaemonSet handling L4 (mTLS, secure tunneling via HBONE)
- **Waypoint proxies** — optional per-namespace L7 Envoy pods for HTTP routing and authorization

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: orchestra
  labels:
    istio.io/dataplane-mode: ambient   # No sidecars needed
```

**Ambient mode performance:** ~70% memory savings, ~50% CPU reduction, faster pod startup, with benchmarks showing over 90% memory reduction in some scenarios.

### IAM Proxy Sidecar for LLM API Calls

A custom sidecar handling credential management for outbound LLM API calls:
- Accepts plaintext HTTP from worker on localhost (no network exposure)
- Fetches/rotates API keys from HashiCorp Vault
- Adds authentication headers to outbound requests
- Logs all API calls for audit
- Enforces rate limits per agent

### Authorization Policies

```yaml
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: orchestra-worker-access
spec:
  selector:
    matchLabels: { app: orchestra-worker }
  rules:
    - from:
        - source:
            principals: ["cluster.local/ns/orchestra/sa/orchestra-server"]
      to:
        - operation:
            methods: ["POST"]
            paths: ["/execute", "/health/*"]
```

### Key Decisions
1. **Ambient vs sidecar:** Use ambient for new deployments (less overhead). Sidecar only if per-pod L7 features needed.
2. **IAM proxy as sidecar vs library:** Sidecar is more secure (worker never sees raw API keys). Library is simpler.
3. **Service mesh vs NATS:** Complementary — NATS for async messaging, mesh for mTLS/auth/observability on sync HTTP.

### Pitfalls
- Sidecar injection adds 100-500ms to pod startup — ambient avoids this
- Default mTLS can break non-mesh services — use `PERMISSIVE` mode during migration
- Each Envoy sidecar uses 50-100MB RAM — significant at scale with hundreds of agent pods

---

## 10. Gossip Protocol

### Python Library Landscape

| Library | GitHub | Status | asyncio | Notes |
|---------|--------|--------|---------|-------|
| **tattle** | kippandrew/tattle | Unmaintained (~2018) | Partial (3.5+) | Most complete Python SWIM impl |
| **scuttlebutt** | geneanet/scuttlebutt | Low activity | Unknown | SWIM-inspired peer list |
| **gossip-python** | thomai/gossip-python | Academic | No | Not production-ready |

**Assessment:** No production-grade, actively-maintained, async-native SWIM library exists in Python as of early 2026.

### Recommended Approach: NATS Built-In Discovery

Since Orchestra is adopting NATS JetStream, leverage NATS's built-in gossip-based cluster discovery. NATS clustering uses a modified SWIM protocol internally — servers gossip membership and automatically form a full mesh.

Agent discovery via NATS request/reply:

```python
async def discover_agents(nc):
    """All agents subscribe to discovery subject."""
    async def handle_discovery(msg):
        await msg.respond(json.dumps({
            "id": agent.id, "type": agent.type,
            "capabilities": agent.capabilities,
        }).encode())
    await nc.subscribe("orchestra.discovery.ping", cb=handle_discovery)
```

### Alternatives
- **HashiCorp Consul** (uses Go `memberlist` with modified SWIM) — for multi-platform discovery outside K8s. Python client: `python-consul2`.
- **Custom SWIM implementation** (~500-1000 lines) using asyncio UDP — feasible but only if cross-org A2A discovery without a broker is required.

### Recommendation
Use NATS service discovery as the primary mechanism. It integrates with NATS JetStream, requires zero additional infrastructure, and NATS's internal gossip handles failure detection and cluster membership. Reserve custom gossip for Phase 5+ cross-organization A2A scenarios.

---

## Integration Map

### How These Technologies Connect

```
                    +-------------------+
                    |   Terraform       |
                    | (Infrastructure)  |
                    +--------+----------+
                             |
                    provisions cluster + installs operators
                             |
              +--------------+------------------+
              |              |                  |
    +---------v----+  +------v-------+  +-------v--------+
    | KEDA Operator|  | OTel Operator|  | kopf Operator  |
    | (Autoscaling)|  | (Telemetry)  |  | (Agent CRDs)   |
    +---------+----+  +------+-------+  +-------+--------+
              |              |                  |
              |    +---------v---------+        |
              |    | Target Allocator  |        |
              |    | (Metric Scraping) |        |
              |    +-------------------+        |
              |                                 |
    +---------v---------------------------------v--------+
    |                  Kubernetes Cluster                  |
    |                                                     |
    |  +-------------+    +-----------+    +------------+ |
    |  | Orchestra   |    | NATS      |    | Agent      | |
    |  | Server      |<-->| JetStream |<-->| Workers    | |
    |  | (FastAPI)   |    | (Messaging)|   | (Ray/Local)| |
    |  +-------------+    +-----------+    +------------+ |
    |                                                     |
    |         Istio Ambient Mesh (mTLS everywhere)        |
    +-----------------------------------------------------+
```

### Integration Decision Matrix

| Component A | Component B | Integration Point |
|-------------|-------------|-------------------|
| Ray Serve | FastAPI | `@serve.ingress` wraps existing FastAPI app |
| Ray Core | NATS | Ray actors consume from NATS queues |
| NATS | KEDA | Monitoring endpoint feeds KEDA scaler |
| KEDA | kopf Operator | Operator creates KEDA ScaledObjects for CRs |
| OTel Collector | Target Allocator | TA distributes scrape targets to Collector fleet |
| Istio | NATS | Transparent mTLS for client connections |
| Istio | OTel | Envoy/ztunnel emits spans and metrics automatically |
| Subinterpreters | Ray | Not needed together — Ray for distribution, subinterpreters for local parallelism |
| Dynamic Subgraphs | Ray | Subgraph nodes dispatch to Ray actors |
| NATS Discovery | Gossip | NATS's internal gossip handles server discovery — no separate layer |

### Recommended Implementation Order

```
Wave 1 (Foundation):    NATS JetStream + K8s Deployment (Helm)
Wave 2 (Scaling):       KEDA + OTel Target Allocator
Wave 3 (Management):    kopf Operator + Istio Ambient
Wave 4 (Distribution):  Ray Core/Serve + Dynamic Subgraphs
Wave 5 (Future):        Python Subinterpreters (when mature)
```

**Rationale:** NATS is the backbone for all inter-agent communication — deploy first. KEDA and OTel TA extend existing K8s infra with minimal code changes. kopf and Istio add operational maturity but are not blocking. Ray is the most complex integration and benefits from stable NATS + K8s. Subinterpreters should wait for Python 3.15+ ecosystem maturity.
