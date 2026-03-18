# Phase 4 Competitive Analysis: Enterprise Agent Framework Landscape

**Date:** 2026-03-11
**Scope:** 10 frameworks/platforms analyzed across distributed execution, identity, cost, memory, observability, deployment

---

## Cross-Cutting Feature Matrix

| Feature | LangGraph | CrewAI | AutoGen | ADK | OpenAI SDK | LiteLLM | Portkey | Haystack | Temporal | Langfuse |
|---------|:---------:|:------:|:-------:|:---:|:----------:|:-------:|:-------:|:--------:|:--------:|:--------:|
| Distributed Exec | Pg+Redis | No | gRPC | No | No | N/A | N/A | No | Core | N/A |
| Agent Identity | No | String role | Type sub | Agent Card | No | Virtual keys | No | No | No | No |
| Cost Tracking | LangSmith | Display | No | No | No | **Best** | Yes | No | No | Yes |
| Budget Enforcement | No | No | No | No | No | **Yes** | No | No | No | No |
| Memory Tiers | Store (flat) | 5 tiers | Per-agent | Session | No | N/A | N/A | No | Result persist | N/A |
| Event Sourcing | Checkpoints | No | No | No | No | N/A | N/A | No | **Yes** | Trace logs |
| OTel Integration | No | No | No | Cloud Trace | No | No | No | No | Partial | Yes |
| Guardrails | No | Enterprise | No | No | Yes (LLM) | No | Middleware | No | No | No |
| Multi-Provider | Via LC | Via LiteLLM | Yes | Partial | No | **Core** | Core | Integrations | N/A | N/A |
| HITL | Interrupt | No | No | input-required | No | N/A | N/A | No | Signals | N/A |

---

## Where Orchestra Already Leads

1. **Event-sourced persistence** — Only Temporal is comparable. Orchestra's EventStore with time-travel and branching is unique among agent frameworks.
2. **Multi-provider native adapters** — Native Anthropic, OpenAI, Google, Ollama (not wrappers).
3. **Cost management** — CostAggregator + BudgetPolicy + ModelCostRegistry surpasses every agent framework. Only LiteLLM has comparable budget enforcement.
4. **Handoff protocol with context distillation** — More sophisticated than OpenAI's or AutoGen's.
5. **OTel-native observability** — No other agent framework has OTel as first-class.

---

## Key Patterns to Adopt

### From LangGraph
- **Checkpoint-as-first-class-citizen:** Every node execution produces durable checkpoint.
- **Store API namespacing:** `(namespace, key)` model for multi-tenant memory isolation.
- **Competing consumers:** Multiple executor replicas pulling from shared queue (simpler than Ray).

### From CrewAI
- **Entity memory:** Automatic entity extraction and tracking across tasks.
- **Named process types:** Pre-built orchestration patterns (sequential, hierarchical, consensual).

### From AutoGen/AG2
- **Topic-subscription messaging:** Decoupled agent addressing via topic subscriptions.
- **HeadAndTailChatCompletionContext:** Keep system + first K + last N messages.

### From Google ADK
- **Agent Card at `/.well-known/agent.json`:** REST-native discovery.
- **AgentTool pattern:** Sub-agents invokable as tools (uniform interface).
- **Skill-based routing:** LLM picks sub-agent from skills metadata.

### From OpenAI Agents SDK
- **Handoffs as tools:** Zero additional framework machinery.
- **Guardrail-as-agent:** Lightweight agent with specialized prompt as guardrail.
- **Tripwire pattern:** Binary `tripwire_triggered` with `output_info`.

### From LiteLLM
- **Multi-level budget hierarchy:** Org → Team → User → Key.
- **Cooldown mechanism:** Failed deployments temporarily removed, auto-reintroduced.
- **Rate limit header tracking:** Proactively routing away before hitting limits.

### From Portkey
- **Declarative routing config:** JSON-based, deployable without code changes.
- **Canary routing:** A/B testing across models.

### From Haystack
- **Pipeline serialization to YAML:** `Graph.to_yaml()` / `Graph.from_yaml()`.
- **Component warm-up pattern:** Separate initialization from execution.
- **Hot-loading (Hayhooks):** Deploy new versions without restart.

### From Temporal
- **Per-activity retry policies:** Per-node retry, not global.
- **Signals pattern:** Send input to running workflow without interrupting.
- **Compensation/saga pattern:** Rollback for workflows with side effects.

### From Langfuse
- **Trace-to-dataset pipeline:** Production traces → evaluation datasets.
- **Score annotation model:** `Score(name, value, comment)` for quality tracking alongside cost.

---

## Priority Recommendations for Phase 4

### 1. Distributed Execution: NATS + Competing Consumers (not Ray)
Ray adds massive complexity and 500MB+ dep. No Python agent framework uses Ray successfully in production. Temporal's task queue model maps perfectly to NATS JetStream. LangGraph's simpler Pg+Redis validates that agent systems don't need heavyweight compute.

### 2. Agent Identity: A2A Agent Card + DID
Agent Card at `/.well-known/agent.json`. RemoteAgent for cross-instance delegation. DID-based identity and UCAN capability delegation.

### 3. Memory Tiers: Three tiers, not five
WorkingMemory (in-process, per-run) + SessionMemory (Redis, cross-run) + LongTermMemory (PostgreSQL + pgvector). Namespace scoping from LangGraph. Entity extraction from CrewAI.

### 4. Cost-Aware Routing
CostRouter with strategies: cheapest, quality-first, balanced (Thompson), budget-aware. Declarative config (Portkey). Cooldown + rate limit headers (LiteLLM). Canary routing for A/B.

### 5. K8s Deployment (Helm)
Server (FastAPI, 2+ replicas) + Worker (N replicas, HPA on NATS depth) + NATS (clustered) + PostgreSQL (HA) + Redis (Sentinel) + Jaeger (optional).

### 6. Testing: Trace-to-Dataset + SPRT + Score Annotations
Export EventStore traces as eval datasets. SPRT for behavioral regression. Score events in EventStore.

### 7. Graph Serialization
`Graph.to_yaml()` / `Graph.from_yaml()`. Hot-loading without restart. Version control workflows independently.

---

## License Compatibility

All analyzed frameworks use MIT or Apache-2.0. Orchestra can study their public code for patterns without legal concern.
