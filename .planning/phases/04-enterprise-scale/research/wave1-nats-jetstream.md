# Wave 1 Research: NATS JetStream (Reliable Event Bus)

**Task:** T-4.1 (NATS JetStream + DIDComm E2EE)
**Sources:** NATS Docs (docs.nats.io), nats-py GitHub README, Phase 4 research (01-infrastructure-scalability.md), Orchestra codebase
**Date:** 2026-03-12

---

## 1. JetStream Overview

### What It Is
JetStream is NATS's built-in persistence layer, adding **at-least-once delivery**, message replay, and durable consumers on top of NATS core's fire-and-forget pub/sub.

### Why for Orchestra
Orchestra currently uses an in-memory `EventBus` (`src/orchestra/storage/store.py`). This means:
- Messages lost on process crash
- No replay capability
- No cross-process/cross-node communication
- No consumer groups for horizontal scaling

JetStream replaces this with persistent, distributed messaging.

### Core Concepts

| Concept | Description |
|---------|-------------|
| **Stream** | Persistent, append-only log of messages on subjects |
| **Subject** | Routing address (e.g., `orchestra.tasks.analyst`) |
| **Consumer** | Stateful view into a stream with cursor tracking |
| **Ack** | Explicit acknowledgment that a message was processed |
| **Sequence** | Monotonically increasing ID per message in a stream |

---

## 2. Streams

### Stream Configuration
```python
import nats
from nats.js.api import StreamConfig, RetentionPolicy, StorageType

js = nc.jetstream()

# Create the main task stream
await js.add_stream(
    StreamConfig(
        name="TASKS",
        subjects=[
            "orchestra.tasks.*",        # orchestra.tasks.{agent_type}
            "orchestra.events.*",       # orchestra.events.{event_type}
            "orchestra.handoffs.*",     # orchestra.handoffs.{workflow_id}
        ],
        retention=RetentionPolicy.LIMITS,  # Keep until limits hit
        max_msgs=1_000_000,               # Max messages in stream
        max_bytes=1 * 1024**3,            # 1GB max storage
        max_age=7 * 24 * 3600,            # 7-day retention (seconds)
        max_msg_size=1 * 1024**2,         # 1MB max message size
        storage=StorageType.FILE,         # File-based (survives restart)
        num_replicas=3,                   # 3-node replication
        duplicate_window=120,             # 2-min dedup window (seconds)
        discard="old",                    # Discard oldest when full
    )
)
```

### Retention Policies

| Policy | Behavior | Use Case |
|--------|----------|----------|
| `LIMITS` | Keep until max_msgs/max_bytes/max_age | Default. Task stream. |
| `INTEREST` | Delete when all consumers have acked | Transient events. |
| `WORK_QUEUE` | Delete after first ack (single consumer) | Exclusive task assignment. |

**Recommendation:** Use `LIMITS` for the main TASKS stream (allows replay). Consider `WORK_QUEUE` for exclusive task assignment if agents should not duplicate work.

### Subject Hierarchy
```
orchestra.
├── tasks.
│   ├── analyst          # Tasks for analyst agents
│   ├── coder            # Tasks for coder agents
│   ├── reviewer         # Tasks for reviewer agents
│   └── >                # Wildcard (all task types)
├── events.
│   ├── workflow.started
│   ├── workflow.completed
│   ├── agent.heartbeat
│   └── >
└── handoffs.
    ├── {workflow_id}    # Per-workflow handoff channel
    └── >
```

### Wildcards
- `*` — matches one token: `orchestra.tasks.*` matches `orchestra.tasks.analyst`
- `>` — matches one or more tokens: `orchestra.>` matches everything under `orchestra`

---

## 3. Consumers

### Consumer Types

| Type | Behavior | Use Case |
|------|----------|----------|
| **Pull** | Client explicitly requests messages | Preferred. Backpressure-aware. KEDA-scalable. |
| **Push** | Server pushes to a delivery subject | Legacy. No backpressure. Avoid. |
| **Ordered** | Ephemeral, ordered delivery | Read-only replay. Monitoring. |

**Recommendation:** Use **pull consumers** exclusively for task processing. They provide:
- Natural backpressure (agent pulls when ready)
- KEDA can monitor consumer lag for autoscaling
- Explicit ack ensures at-least-once delivery

### Pull Consumer Configuration
```python
from nats.js.api import ConsumerConfig, AckPolicy, DeliverPolicy, ReplayPolicy

# Durable pull consumer for agent workers
await js.add_consumer(
    stream="TASKS",
    config=ConsumerConfig(
        durable_name="orchestra-workers",
        filter_subject="orchestra.tasks.*",
        ack_policy=AckPolicy.EXPLICIT,       # Must ack each message
        ack_wait=30,                          # 30s to ack before redeliver
        max_deliver=5,                        # Max redelivery attempts
        max_ack_pending=1000,                 # Max unacked messages
        deliver_policy=DeliverPolicy.ALL,     # Start from beginning
        replay_policy=ReplayPolicy.INSTANT,   # Replay as fast as possible
    )
)
```

### Pull Subscribe Pattern
```python
# Pull-based consumption with explicit ack
sub = await js.pull_subscribe(
    subject="orchestra.tasks.*",
    durable="orchestra-workers",
    stream="TASKS"
)

while True:
    try:
        msgs = await sub.fetch(batch=10, timeout=5)
        for msg in msgs:
            try:
                task = json.loads(msg.data)
                await process_task(task)
                await msg.ack()  # Explicit ack on success
            except Exception as e:
                await msg.nak(delay=5)  # Negative ack → redeliver after 5s
    except nats.errors.TimeoutError:
        continue  # No messages available, loop back
```

### Ack Patterns

| Method | Behavior | When to Use |
|--------|----------|-------------|
| `msg.ack()` | Message processed successfully | Happy path |
| `msg.nak(delay=N)` | Negative ack, redeliver after N seconds | Transient failure |
| `msg.in_progress()` | Reset ack timer (still processing) | Long-running tasks |
| `msg.term()` | Terminate, don't redeliver | Poison messages |

### Long-Running Task Pattern
```python
async def process_long_task(msg):
    """For tasks that take > ack_wait (30s)."""
    # Start heartbeat to prevent redelivery
    async def heartbeat():
        while True:
            await asyncio.sleep(10)
            await msg.in_progress()  # Reset ack timer

    hb_task = asyncio.create_task(heartbeat())
    try:
        result = await execute_agent_task(msg.data)
        await msg.ack()
    except Exception:
        await msg.nak(delay=10)
    finally:
        hb_task.cancel()
```

---

## 4. Consumer Groups (Horizontal Scaling)

### Queue Groups with JetStream
Multiple instances of the same consumer (same `durable_name`) automatically form a consumer group. NATS distributes messages across instances.

```python
# Instance 1 (same durable name)
sub1 = await js.pull_subscribe("orchestra.tasks.*", durable="orchestra-workers")

# Instance 2 (same durable name, different process/pod)
sub2 = await js.pull_subscribe("orchestra.tasks.*", durable="orchestra-workers")

# NATS distributes messages between sub1 and sub2
# Each message delivered to exactly one consumer in the group
```

### KEDA Integration
KEDA monitors consumer lag (pending messages) to scale pods:
```
Consumer lag = stream last sequence - consumer ack floor
```
When lag > `lagThreshold`, KEDA adds pods. Each new pod pulls from the same durable consumer, automatically joining the group.

---

## 5. Message Publishing

### Basic Publish with Ack
```python
js = nc.jetstream()

# Publish returns an ack with stream sequence number
ack = await js.publish(
    subject="orchestra.tasks.analyst",
    payload=json.dumps({
        "task_id": "t-001",
        "workflow_id": "wf-abc",
        "type": "analyze",
        "payload": {...}
    }).encode(),
    headers={
        "Nats-Msg-Id": "t-001",  # Deduplication key
        "Orchestra-Workflow": "wf-abc",
    }
)

print(f"Published to stream={ack.stream}, seq={ack.seq}")
```

### Deduplication
NATS uses `Nats-Msg-Id` header for deduplication within the `duplicate_window` (120s). Publishing the same message ID twice within the window → second publish is a no-op.

```python
# Safe retry — same Nats-Msg-Id won't duplicate
for attempt in range(3):
    try:
        ack = await js.publish(
            "orchestra.tasks.analyst",
            payload=data,
            headers={"Nats-Msg-Id": task_id}
        )
        break
    except Exception:
        await asyncio.sleep(1)
```

### Publish with Trace Context
```python
# Propagate OpenTelemetry trace context via NATS headers
from opentelemetry import trace, context
from opentelemetry.propagators import inject

headers = {"Nats-Msg-Id": task_id}
inject(headers)  # Adds traceparent, tracestate headers

ack = await js.publish(subject, payload, headers=headers)
```

---

## 6. Replay from Sequence Number

### Replay Scenarios
- **Crash recovery:** Resume from last acked sequence
- **Debugging:** Replay specific time range
- **New consumer:** Process historical messages

### Deliver Policies

| Policy | Start From | Use Case |
|--------|-----------|----------|
| `ALL` | First message in stream | New consumer, full replay |
| `LAST` | Last message per subject | Latest state only |
| `NEW` | Only new messages | Real-time only |
| `BY_START_SEQUENCE` | Specific sequence number | Crash recovery |
| `BY_START_TIME` | Specific timestamp | Time-range replay |

### Crash Recovery Pattern
```python
# Store last processed sequence in Orchestra's EventStore
last_seq = await event_store.get_checkpoint("orchestra-workers")

# Create consumer starting from last checkpoint
await js.add_consumer(
    stream="TASKS",
    config=ConsumerConfig(
        durable_name="orchestra-workers",
        deliver_policy=DeliverPolicy.BY_START_SEQUENCE,
        opt_start_seq=last_seq + 1,
        ack_policy=AckPolicy.EXPLICIT,
    )
)

# After processing each message, checkpoint
async def process_and_checkpoint(msg):
    await process_task(msg.data)
    await msg.ack()
    await event_store.set_checkpoint("orchestra-workers", msg.seq)
```

---

## 7. Graceful Fallback to In-Memory

### Design: NatsEventBus with Fallback
```python
from src.orchestra.storage.store import EventBus

class NatsEventBus(EventBus):
    """JetStream-backed event bus with in-memory fallback."""

    def __init__(self, nats_url: str | None = None):
        self._nats_url = nats_url
        self._nc = None
        self._js = None
        self._fallback = InMemoryEventBus()  # Existing implementation

    async def connect(self):
        if not self._nats_url:
            logger.info("No NATS URL configured, using in-memory bus")
            return

        try:
            self._nc = await nats.connect(self._nats_url)
            self._js = self._nc.jetstream()
            await self._ensure_streams()
            logger.info(f"Connected to NATS JetStream at {self._nats_url}")
        except Exception as e:
            logger.warning(f"NATS unavailable ({e}), falling back to in-memory")
            self._nc = None
            self._js = None

    async def publish(self, subject: str, data: dict):
        if self._js:
            await self._js.publish(subject, json.dumps(data).encode())
        else:
            await self._fallback.publish(subject, data)

    async def subscribe(self, subject: str, handler):
        if self._js:
            sub = await self._js.pull_subscribe(subject)
            # ... pull loop with handler
        else:
            await self._fallback.subscribe(subject, handler)
```

---

## 8. NATS Cluster Configuration

### Helm Values for 3-Node JetStream Cluster
```yaml
# deploy/nats-values.yaml
nats:
  image:
    tag: "2.10-alpine"
  jetstream:
    enabled: true
    fileStore:
      pvc:
        size: 10Gi
        storageClassName: gp3  # AWS EBS gp3
    memoryStore:
      maxSize: 1Gi
  cluster:
    enabled: true
    replicas: 3
  monitoring:
    enabled: true
    port: 8222  # KEDA scrapes this
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: "2"
      memory: 2Gi
```

### Cluster Sizing

| Workload | Nodes | File Storage | Memory Store |
|----------|-------|-------------|-------------|
| Dev/Test | 1 | 1Gi | 256Mi |
| Staging | 3 | 5Gi | 512Mi |
| Production | 3-5 | 10-50Gi | 1-4Gi |

---

## 9. Mapping to Orchestra's Current EventBus

### Current Interface (`src/orchestra/storage/store.py`)
The existing `EventBus` provides:
- `publish(event: WorkflowEvent)` — fire and forget
- `subscribe(event_type, handler)` — callback-based

### Migration Path
1. Create `NatsEventBus` implementing same `EventBus` interface
2. Add NATS connection config to Orchestra settings
3. Swap `InMemoryEventBus` → `NatsEventBus` in DI container
4. Existing code continues to work (same interface)
5. Add JetStream-specific features (replay, ack) via extended interface

### Subject Mapping
```python
# Current: event.type → NATS subject
EVENT_TO_SUBJECT = {
    "workflow.started":    "orchestra.events.workflow.started",
    "workflow.completed":  "orchestra.events.workflow.completed",
    "task.assigned":       "orchestra.tasks.{agent_type}",
    "task.completed":      "orchestra.events.task.completed",
    "handoff":             "orchestra.handoffs.{workflow_id}",
    "agent.heartbeat":     "orchestra.events.agent.heartbeat",
}
```

---

## 10. Connection Management

### Async Connection with Reconnect
```python
import nats

async def connect_nats(url: str = "nats://localhost:4222"):
    nc = await nats.connect(
        servers=[url],
        reconnect_time_wait=2,        # Wait 2s between reconnect attempts
        max_reconnect_attempts=60,     # Try for ~2 minutes
        ping_interval=20,              # Ping every 20s
        max_outstanding_pings=3,       # Disconnect after 3 missed pings
        error_cb=on_error,
        disconnected_cb=on_disconnect,
        reconnected_cb=on_reconnect,
        closed_cb=on_close,
    )
    return nc

async def on_disconnect():
    logger.warning("NATS disconnected, attempting reconnect...")

async def on_reconnect():
    logger.info("NATS reconnected")

async def on_error(e):
    logger.error(f"NATS error: {e}")
```

### Graceful Shutdown
```python
async def shutdown():
    # 1. Stop pulling new messages
    await subscription.unsubscribe()
    # 2. Wait for in-flight tasks to complete
    await asyncio.gather(*in_flight_tasks)
    # 3. Drain connection (flush + close)
    await nc.drain()
```

---

## 11. Performance Characteristics

| Metric | Value | Notes |
|--------|-------|-------|
| Publish throughput | ~10M msgs/sec (core NATS) | JetStream: ~1-3M with ack |
| Latency (publish+ack) | ~0.5-2ms | Single node, local |
| Message size limit | 1MB default | Configurable via `max_payload` |
| Consumer lag query | <1ms | Via monitoring API |

### Benchmarking for T-4.1 Done Criterion
"Publish 100 tasks → 100 acks; NATS store contains only opaque ciphertexts; decryption verified."

```python
async def benchmark_100_tasks():
    published = 0
    for i in range(100):
        ack = await js.publish(
            f"orchestra.tasks.analyst",
            encrypted_payload,  # DIDComm JWE
            headers={"Nats-Msg-Id": f"bench-{i}"}
        )
        assert ack.stream == "TASKS"
        published += 1

    # Verify all 100 stored
    info = await js.stream_info("TASKS")
    assert info.state.messages >= 100

    # Verify opaque (no plaintext in store)
    # Read raw via ordered consumer
    sub = await js.subscribe("orchestra.tasks.*", ordered_consumer=True)
    for _ in range(100):
        msg = await sub.next_msg(timeout=5)
        # Should be JWE JSON, not plaintext
        parsed = json.loads(msg.data)
        assert "ciphertext" in parsed  # JWE envelope
        assert "task_id" not in parsed  # No plaintext leakage
```

---

## 12. Security Considerations

| Concern | Mitigation |
|---------|------------|
| Messages at rest | DIDComm E2EE — JetStream stores only JWE ciphertexts |
| Messages in transit | TLS between NATS nodes and clients |
| Unauthorized publish | NATS auth (token/NKey/JWT) + subject-level permissions |
| Consumer impersonation | Durable consumers bound to authenticated clients |
| Replay attacks | `Nats-Msg-Id` deduplication + sequence tracking |
| Message tampering | DIDComm authcrypt includes sender authentication |

### NATS Authorization (Subject Permissions)
```
# nats-server.conf
authorization {
  users = [
    {
      user: "orchestrator"
      permissions: {
        publish: ["orchestra.tasks.*", "orchestra.handoffs.*"]
        subscribe: ["orchestra.events.>"]
      }
    },
    {
      user: "agent-worker"
      permissions: {
        publish: ["orchestra.events.*"]
        subscribe: ["orchestra.tasks.*"]
      }
    }
  ]
}
```

---

## 13. Open Questions

1. **Stream topology:** One stream (TASKS) for everything, or separate streams per concern (TASKS, EVENTS, HANDOFFS)? Separate streams = independent retention/scaling. One stream = simpler management.
2. **Exactly-once vs at-least-once:** JetStream provides at-least-once. For exactly-once, need idempotent consumers (check `Nats-Msg-Id` before processing). Is this worth the complexity?
3. **Message ordering:** Within a subject, messages are ordered. Across subjects, no ordering guarantee. Does Orchestra need cross-subject ordering for workflows?
4. **NATS vs Redis Streams:** Phase 4 also adds Redis (T-4.8). Should Redis Streams be considered as an alternative to NATS? (Answer: No — NATS is purpose-built for messaging; Redis L2 is for caching/memory.)
5. **Monitoring endpoint access:** KEDA needs access to NATS monitoring (:8222). Ensure network policy allows this.

---

## 14. Cross-References

- **DIDComm E2EE integration:** See `wave1-didcomm-e2ee.md` for SecureNatsProvider wrapping publish/consume with encryption
- **KEDA scaling on consumer lag:** See `wave1-k8s-helm-keda-terraform.md` Section 3
- **Trace context propagation:** See `wave1-otel-collector.md` for OTel trace headers in NATS messages
- **Existing research:** `01-infrastructure-scalability.md` (NATS vs alternatives comparison)
- **Current EventBus:** `src/orchestra/storage/store.py`, `src/orchestra/storage/events.py`
