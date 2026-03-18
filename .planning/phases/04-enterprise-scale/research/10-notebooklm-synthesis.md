# Phase 4 Research Synthesis: NotebookLM Reports + Curated Tools

**Date:** 2026-03-11
**Sources:** 12 NotebookLM PDFs + curated tools list + existing research (01-08)

---

## Executive Summary

This document synthesizes NEW insights from 12 NotebookLM research reports and a curated tools list, layered on top of the 8 existing Phase 4 research files. It highlights **only net-new information** not already captured in the existing research.

---

## 1. Infrastructure & Scalability — New Insights

### From: Engineering Specification (Server & API Layer)
- **Lifespan Context Manager**: FastAPI resource init (vector DBs, checkpointers, LLM clients) MUST happen inside `lifespan` to avoid `RuntimeError: Task attached to a different loop`
- **PostgresSaver Lock Bottleneck**: Internal `self.lock` in `_cursor` context manager serializes ALL checkpoint I/O per instance. Mitigation: multiple Uvicorn workers, each with own saver instance
- **Long-Running Task Pattern**: `POST /runs` → 202 Accepted + `run_id` → `GET /runs/{run_id}/status`. State machine: `PENDING → RUNNING → (INTERRUPTED | COMPLETED | FAILED)`
- **SSE Streaming Standards**: 15s heartbeat (`ping`), `retry: 5000`, `HTTP_LAST_EVENT_ID` for state recovery on reconnect. Headers: `X-Accel-Buffering: no`, `Cache-Control: no-cache`
- **`asyncio.TaskGroup` (Python 3.14)**: Structural concurrency for parallel tool execution with fail-fast. Dedicated "Cleanup Task" on `request.is_disconnected()` to prevent orphaned runs
- **Subinterpreter Marshaling**: Immutable builtins shared efficiently; complex objects require pickling. Design for minimal, shareable data structures

### From: Curated Tools
- **MotleyCrew** (github.com/MotleyCrew-AI/MotleyCrew): Reference for running agentic workflows as Ray execution DAGs. Study "Brain-Hands-Engine" pattern

### New Recommendations
1. Add `request.is_disconnected()` monitoring to server implementation
2. Use `HTTP_LAST_EVENT_ID` replay for SSE resilience
3. Study MotleyCrew's Ray DAG patterns before implementing Ray Serve integration

---

## 2. Agent IAM & Security — New Insights

### From: Agentic IAM & Security Governance Report
- **DID Lifecycle (4 phases)**: Spawning/Generation → Credential Attachment → Presentation Construction → Session Presentation
- **OIDC Bridge via SIOP**: Self-Issued OpenID Connect Provider profile translates VC claims into standard OIDC tokens. Credentials become "re-provable" without original issuer involvement
- **Proof of Identifier Control**: Challenge-response mechanism — relying party issues random string, agent signs with private key, bridge validates against DID document public key
- **Progressive Trust Model**: ZKP enables incremental trust building (not binary trusted/untrusted). "Selective Disclosure" proves facts without revealing full credential
- **Delegation Chain Verification**: Resource server validates ENTIRE chain of signatures back to root authority on capability invocation
- **Real-Time Capability Caveats**: Time-bound limits (single session), task-specific limits (read-only, specific tools/DB subsets)

### From: Curated Tools
- **ACA-Py** (hyperledger/aries-cloudagent-python): Full enterprise-grade DID management — preferred over archived DIDKit
- **peerdid-python** (sicpa-dlab/peer-did-python): Lightweight `did:peer` — use for local/ephemeral agent identity
- **zcapld** (digitalbazaar/zcapld): JavaScript-only, but reference for capability delegation patterns. Must build Python equivalent

### Key Delta from Existing Research
Existing `02-agent-iam-security.md` covers libraries but lacks the **4-phase DID lifecycle** and **SIOP bridge mechanism**. The Progressive Trust model via ZKP is a significant architectural pattern not previously captured.

---

## 3. Cost Routing & Intelligence — New Insights

### From: Strategic Analysis (Cost-Aware Routing)
- **CSCR (Cost-Spectrum Contrastive Routing)**: Maps prompts AND models into shared embedding space. Uses FAISS k-NN for microsecond-latency lookup of "cheapest accurate expert"
- **Two Model Descriptors**:
  - *Logit-Footprint Descriptors*: For open-weights models (Llama, Mistral) — samples internal predictive distribution
  - *Perplexity Fingerprints*: For black-box APIs (GPT-4o, Claude) — scores output using auxiliary SLM (e.g., GPT-2)
- **Pareto Frontier Results**: CSCR ~0.79 accuracy (peak, dominant), Thompson Sampling ~0.78, Random ~0.54
- **SLM Distillation Pipeline**: Teacher generates gold-standard data → RFT yields ~66% accuracy gains → 90% cost reduction for specific workflows
- **Model Aliasing**: Call logical descriptors ("high-accuracy") instead of hard-coded model names. Enables fast-fallback without code changes
- **Routing Overhead**: < 100μs via Bifrost/FAISS — negligible latency cost

### From: Multi-Agent Cost Management Report
- **LLMflation**: Model costs dropped from $60/1M tokens (2021) to $0.06/1M tokens (2025) — 1000x reduction
- **Circuit Breaker States**: Closed → Open (5 failures/minute OR dollar cap breach) → Half-Open (30s timeout, single test request)
- **Budget Delegation Conservation Laws**: Sub-agent unused credits return to central pool immediately after each LLM call
- **Mandatory Attribution Tags**: `user_id`, `task_type`, `model_alias`, `department_code`, `budget_duration` (1s|1m|1h|1d|7d|30d)
- **Wasted Spend Categories**: Failed retries with backoff, hallucinations caught by guardrails — report separately for optimization
- **Cost-Saving Heuristics**:
  - Relay Method: Save state to DB, kill agent instance between tasks
  - Model Quantization: W4A16-INT → 3.5x size reduction, 2.4x speedup
  - Batch Processing: Async APIs → 50% discount
  - Prompt Prefix Caching: Cached tokens cost 10% of standard rate
- **GPU Cost Reference**: H100 $3.50-5.50/hr, H200 $4.50-6.50/hr (cloud commitments: up to 80% discount)
- **Recursive Loop Audit**: Max turn counts + semantic similarity for repetition detection + node-level rate limiting + anomaly detection ($0.20→$1.50/turn spike)

### From: Curated Tools
- **RouteLLM** (lm-sys/RouteLLM): Gold standard. Matrix Factorization + Controller for cost-aware selection
- **ParticleThompsonSamplingMAB** (colby-j-wise/ParticleThompsonSamplingMAB): Reference for Thompson Sampling + MF exploration-exploitation

### Key Delta from Existing Research
Existing `03-cost-routing-intelligence.md` has Thompson Sampling and MF but lacks **CSCR shared embedding space**, **Logit-Footprint vs Perplexity Fingerprint** model descriptors, **Model Aliasing** pattern, and the detailed **Conservation Laws** for budget delegation.

---

## 4. Advanced Memory & Data — New Insights

### From: Technical Report (Advanced Memory)
- **"Pancake 2026" Architecture**: Vertical stack that moves vectors directly from Tier 2 Object Stores into GPU VRAM for Tier 0 processing — bypasses CPU bottleneck
- **"Zero-Copy Context" Protocol**: Agents pass pointers to shared-memory segments in L2 backplane (not serialized copies)
- **Multi-Leader Replication**: Redis backplane uses multi-leader model for concurrent writes across geographic clusters (not just Pub/Sub invalidation)
- **Dimensionality Catastrophe**: Vector footprints can exceed 65,535 dimensions — requires engineered HNSW graph structures
- **Product Quantization (PQ)**: Compress reasoning traces into "codebooks" with anisotropic loss function — preserves reasoning "essence" without context limits
- **HNSW Greedy Search**: Start at highest layer (coarse navigation) → proceed to local minimum → descend layers for refinement

### From: Multi-Tier Memory Specification
- **Hybrid Retrieval (Cold Tier)**: 30% BM25 lexical + 70% Dense Embedding = 92% Top-10 Accuracy
- **Composite Scoring**: `Score = (Similarity * w) + (Recency * w) + (Importance * w)`
- **Recency Decay Function**: `Recency = 0.5^(age_days / half_life_days)` — configurable half-life
- **Semantic Dedup Actions (0.85 threshold)**: LLM chooses: Keep | Update | Delete | Insert New
- **MemGPT-Style "Deep Recall"**: Agent autonomously invokes long-term memory search when context window insufficient
- **Redis Flex (Tiered Storage)**: RAM + SSD based on access frequency — relevant for Cold Tier
- **86% cost reduction** from deduplication audit in production environments
- **Sub-10ms response** for Hot Tier, 0.1s improvement → 8-10% conversion lift

### From: Curated Tools
- **Neo4j**: Graph database for Warm/Graph memory tier — enables relationship-based retrieval (not just vector similarity)
- **Zstandard (zstd)**: Cold/event-store compression (aligns with existing PEP 784 recommendation)

### Key Delta from Existing Research
Existing `04-memory-data-caching.md` covers SLRU/Redis/HNSW but lacks **Hybrid Retrieval (BM25+Dense)**, **Composite Scoring with decay**, **MemGPT-style Deep Recall**, **Neo4j graph memory**, and the **4-action semantic dedup workflow** (Keep/Update/Delete/Insert).

---

## 5. Testing & Quality — New Insights

### From: Comprehensive Quality Assurance Report
- **Reliability Surface Model**: `R(k, ε, λ)` — Consistency (k), Robustness (ε), Fault Tolerance (λ)
- **Three-Valued Verdict**: Pass, Fail, **Inconclusive** — mathematically necessary for stochastic agents
- **Variance-Calibrated Budgeting**: Stable agents → 4-7x trial reduction; Moderate/Volatile → higher samples. SPRT achieves **78% token cost reduction** vs fixed-sample
- **Five-Dimensional Coverage Tuple**: `C = (C_tool, C_path, C_state, C_boundary, C_model)`
  - C_tool: Every tool invoked
  - C_path: **Chao1 estimator** for hidden reasoning path space
  - C_state: Variety of internal states/conversation histories
  - C_boundary: Edge cases in tool parameters
  - C_model: Cross-provider consistency (GPT-4o vs Claude vs Llama)
- **Stochastic Kill Semantics**: Mutant "killed" only if pass rate drop is statistically significant at 95% confidence (α=0.05)
- **Hotelling's T² Test**: Multivariate regression detection on behavioral fingerprint manifolds — higher power than simple pass-rate testing
- **6 Behavioral Fingerprint Feature Families**:
  1. Tool Usage (distribution & frequency)
  2. Structural Complexity (trace length & nesting depth)
  3. Output Characteristics (token counts & complexity scores)
  4. Reasoning Patterns (action type distributions: reason, call_tool, respond)
  5. Error/Recovery (error frequency & recovery success rate)
  6. Efficiency Metrics (token cost & latency per step)
- **Trace-First Offline Analysis**: Zero additional token cost — calculate coverage and verify metamorphic relations from production traces
- **Deterministic Replay**: Use execution traces to recreate specific reasoning paths (via Cagent)
- **Contract Testing**: AgentAssert or JSON schemas for agent-to-agent protocol validation
- **Chaos Engineering Framework**: Transient timeouts, rate limits, partial responses, schema drift injection
- **Top Emergent Behavior Risks**: Reasoning loops, cascading failures from agent chain dependencies

### From: Curated Tools
- **ConSol** (LiuzLab/consol): SPRT for LLM self-consistency — "stop sampling" reasoning paths once statistically dominant answer found. **Up to 70% token savings**
- **Certified Self-Consistency** (arXiv 2410.05268): Martingale-based certificates for mathematical guarantees on agent outputs

### Key Delta from Existing Research
Existing `05-testing-safety-guardrails.md` has SPRT/behavioral fingerprinting basics but lacks **Reliability Surface model**, **5D Coverage Tuple**, **Chao1 estimator**, **Stochastic Kill Semantics**, **Hotelling's T²**, **6 feature families**, **Trace-First Offline Analysis**, and **Chaos Engineering** scenarios.

---

## 6. Safety & Guardrails — New Insights

### From: Safety, Guardrails & Reliability Audit
- **PromptShield Comparative Data**: 65.3% TPR @ 0.1% FPR vs PromptGuard 9.4% TPR @ same FPR — PromptShield is 7x better
- **RAG Indirect Injection Mitigation (4-step)**:
  1. Isolation: XML/JSON delimiters for System/User/Third-party content
  2. Context Anchoring: Bind instructions to system prompt, treat bracketed data as informational only
  3. Signed-Prompt Verification: Cryptographic signatures on retrieved document chunks
  4. Privilege Limitation: Restricted tool-calling scopes for agents operating on retrieved data
- **Token Bucket vs Leaky Bucket**: Token Bucket is superior — O(1) latency, ~50 bytes/identity (vs ~1KB/identity for Leaky), supports millions of agent identities
- **Zero-Trust Gateway**: 99% reduction in common security threats with real-time validation
- **AbstractCore Strategy Failover**: Strategy 1 (Native Schema Enforcement) → Strategy 2 (Prompted+Validation) when failing over to non-native providers
- **Circuit Breaker Triggers**: Status 429 (rate limit), Status 503 (unavailable), P95 latency > 2x baseline

### From: Curated Tools
- **Meta Prompt Guard 86M** (meta-llama/Prompt-Guard-86M): 86M parameter prompt injection/jailbreak classifier — high-speed, local
- **DeBERTa-v3-small** (protectai/deberta-v3-small-prompt-injection-v2): Smaller injection classifier — even faster inference

### Key Delta from Existing Research
Existing `05-testing-safety-guardrails.md` has PromptShield/Sentinel but lacks **RAG indirect injection 4-step mitigation**, **Token Bucket algorithm**, **Zero-Trust gateway**, and **AbstractCore strategy failover**.

---

## 7. Interoperability (A2A) — New Insights

### From: Reliability & Interoperability Report
- **Agent Card REQUIRED Fields (A2A §4.4)**:
  - Identity: name, description, version, provider
  - Interfaces: supportedInterfaces (URLs, protocol bindings, versions)
  - Capabilities: streaming, pushNotifications, extendedAgentCard flags
  - Security: securitySchemes (OAuth2, Mutual TLS), securityRequirements
  - Operational Modes: defaultInputModes/outputModes (MIME types)
  - Skills: AgentSkill objects with example prompts
  - **Extensions**: Cost-Profiles as non-normative metadata (§4.4.4)
- **A2A vs OpenAPI**: A2A captures asynchronous reasoning and long-running task lifecycles (Input Required, Auth Required states). OpenAPI cannot model stateful task transitions
- **Protocol Stack (3 layers)**:
  - Layer 3: Protocol Bindings (JSON-RPC 2.0/SSE, gRPC, HTTP+JSON/REST)
  - Layer 2: Abstract Operations (Send Message, Stream Message, Get Task, Subscribe)
  - Layer 1: Canonical Data Model (Task, Message, AgentCard, Artifact, Part)
- **Mandatory Protocol Requirements**: Event ordering (in-order), idempotency via messageId, broadcasting (same events to all streams)
- **Ethical Arbitration Engine (EAE)**: Causal Graph Extractor → influence diagrams → Simulative Redress Module (SRM) for forking simulation → Justification Ledger (JL) for audit trail

### Key Delta from Existing Research
Existing `06-a2a-sdk-ecosystem-otel.md` has A2A basics but lacks **required field specifications**, **3-layer protocol stack**, **A2A vs OpenAPI distinction**, and **EAE arbitration architecture**.

---

## 8. OTel & Observability — New Insights

### From: Production Telemetry & Tracing Specification
- **Agentic Span Hierarchy**:
  - `workflow.run` (Root, INTERNAL) → `agent.turn` (INTERNAL/CLIENT) → `llm.chat` (CLIENT) → `tool.invocation` (CLIENT/INTERNAL)
  - Attributes: `gen_ai.operation.name` = workflow | invoke_agent | chat | execute_tool
- **PII Redaction BEFORE Token Counting**: Redaction layer MUST execute before data reaches economics/cost processors
- **Asyncio Context Wrapper** (`run_with_trace_context`):
  ```python
  def run_with_trace_context(coro):
      ctx = context.get_current()
      async def wrapped_coro():
          token = context.attach(ctx)
          try: return await coro
          finally: context.detach(token)
      return asyncio.create_task(wrapped_coro())
  ```
- **structlog Integration**: `inject_otel_context` processor adds `trace_id` (032x) and `span_id` (016x) to every log entry
- **High-Cardinality Warning**: `tenant_id`/`user_id` MUST NOT be metric labels (crashes Prometheus TSDB). Use Span Attributes instead
- **OTel Baggage**: Propagate `session_id` and `tenant_id` across service boundaries
- **Load-Balancing Exporter**: Route all spans with same trace_id to same gateway — required for consistent tail sampling
- **Collector YAML with Redaction Processor**:
  ```yaml
  processors:
    redaction:
      allow_all_keys: false
      allowed_keys: ["gen_ai.request.model", "trace_id", "span_id"]
      blocked_values: ["api_key_*", "Bearer *"]
  ```
- **AI Golden Signals (Prometheus)**:
  | Metric | Type | Labels |
  |--------|------|--------|
  | `gen_ai.client.operation.duration` | Histogram | model, provider, operation_type |
  | `gen_ai.client.token.usage` | Counter | model, token_type (input/output/cache) |
  | `gen_ai.client.operation.errors` | Counter | model, error.type (logic vs provider) |
  | `gen_ai.usage.cost` | Gauge | model, service_name |

### From: Platform Maturity & Observability Report
- **"Interface Hallucinations"**: Agents failing to interact correctly with APIs due to ambiguous data structures — Type-Safe SDKs are first defense
- **Reasoning-to-Token Ratio**: Critical metric for detecting agents "thinking in circles"
- **Agent-Handoff-Latency**: Track state transfer time between agents
- **10TB+ daily telemetry**: At scale, 100% capture is financially unviable — tail sampling mandatory
- **DaemonSet Collector Strategy**: Agent Collectors as DaemonSets on all K8s nodes for local burst handling

### Key Delta from Existing Research
Existing `06-a2a-sdk-ecosystem-otel.md` has collector/prometheus basics but lacks **span hierarchy**, **asyncio context wrapper**, **PII redaction ordering**, **structlog integration**, **high-cardinality warning**, **load-balancing exporter**, and **Reasoning-to-Token Ratio** metric.

---

## 9. SDK & Ecosystem — New Insights

### From: Platform Maturity Report
- **10-25% Marketplace Commission Model**: Revenue stream for platform + incentive for developers
- **Usage-Based Pricing / Subscription Tiers** for marketplace agents
- **"Certified Agent Architect" (4 competencies)**: Prompt Engineering, State Management, Security, Context Anchoring
- **Visual Builder Supervisor-Agent Pattern**: Central orchestrator manages fleet of specialized workers in n8n/Flowise
- **Webhook Tools**: Visual builders handle async external events (Gmail, Discord) via webhook tools

### From: Foundations Report
- **Agent Taxonomy**: Worker Agents (domain tasks), Service Agents (utilities/compliance/healing), Support Agents (meta-oversight/monitoring)
- **Orchestration Layer (4 units)**: Planning & Policy, Execution & Control, State & Knowledge, Quality & Operations
- **Murakkab Framework**: Declarative abstractions → 2.8x GPU reduction, 3.7x energy reduction, 4.3x cost reduction
- **MCP vs A2A Positioning**: MCP = vertical (agent-to-tool/data), A2A = horizontal (agent-to-agent) with cryptographic signing

---

## 10. Curated Tools Integration Map

### Already in Existing Research (Confirmed)
| Tool | Existing File | Status |
|------|--------------|--------|
| Ray Serve | 01-infrastructure | Covered (v2.54.0) |
| ACA-Py | 02-agent-iam | Covered (noted DIDKit archived) |
| peerdid-python | 02-agent-iam | Covered (v0.5.2) |
| RouteLLM | 03-cost-routing | Covered (MF + Controller) |
| A2A Protocol | 06-a2a-sdk | Covered (v0.3.24) |
| zstd | 04-memory-data | Covered (PEP 784) |

### NEW Tools to Add
| Tool | Relevance | Integration Point |
|------|-----------|------------------|
| **MotleyCrew** | Ray DAG reference | Study for Ray Serve patterns |
| **ParticleThompsonSamplingMAB** | Thompson Sampling reference | Port to CostAwareRouter |
| **ConSol (SPRT)** | Stop-early testing | SPRTBinomial implementation |
| **Neo4j** | Graph memory warm tier | Alternative/complement to Redis for relationship queries |
| **Prompt Guard 86M** | Injection detection | PromptShield SLM (lighter than Sentinel 355M) |
| **DeBERTa-v3-small injection** | Small classifier | Fastest inference option for injection detection |
| **zcapld (JS reference)** | Capability delegation patterns | Build Python equivalent from spec |
| **Certified Self-Consistency** | Mathematical guarantees | Layer on top of SPRT for formal verification |

---

## 11. Cross-Cutting Architectural Patterns (New)

### Pattern: "Relay Method" (Cost Management)
Save state to DB and kill agent instances between tasks. Prevents "Cloud Mega-Bills" from idle agent processes.

### Pattern: "Context Anchoring" (Safety + Observability)
Use OTel Baggage to propagate `tenant_id` through all processing. Ensures agents stay grounded in correct enterprise data. Prevents hallucinations from cross-tenant context pollution.

### Pattern: "Model Aliasing" (Cost Routing)
Application calls logical descriptors ("high-accuracy", "fast-cheap") instead of model IDs. Gateway resolves to current best model. Enables provider failover without code changes.

### Pattern: "Zero-Trust Gateway" (Safety)
Every LLM API call validated in real-time. Schema enforcement (Pydantic) → Content filtering → PII redaction → Budget check. 99% reduction in common security threats.

### Pattern: "Trace-First Offline Analysis" (Testing)
Run coverage and contract tests against production traces at ZERO token cost. Use LLM-as-Judge only for semantic drift verification after prompt updates.

### Performance Benchmarks (Server & API)
| Framework | Latency | Token Cost/Run | Consistency (StdDev) |
|-----------|---------|----------------|---------------------|
| MS Agent Framework | 93s | 7,006 | 0.10 |
| CrewAI | 246s | 27,684 | 0.30 |
| LangGraph | 506s | 8,823 | 0.32 |

---

## 12. Updated Implementation Priority

Based on synthesis of all sources, refined wave ordering:

### Wave 1: Foundation (Critical Path)
1. **Server & API Layer** — Long-running task pattern, SSE streaming, lifespan management
2. **OTel Span Hierarchy** — workflow.run → agent.turn → llm.chat → tool.invocation
3. **Redis L2 Backplane** — Multi-leader replication, Pub/Sub invalidation

### Wave 2: Intelligence Layer
4. **Cost-Aware Routing** — CSCR + Thompson Sampling + Model Aliasing + Budget Conservation Laws
5. **Agent IAM** — DID lifecycle + SIOP Bridge + zcap-ld capabilities
6. **PromptShield** — Parallel execution pattern + RAG indirect injection defense

### Wave 3: Data & Memory
7. **HSM 4-Tier** — Hot/Warm/Cold/Archive with Composite Scoring + Recency Decay
8. **Hybrid Retrieval** — 30% BM25 + 70% Dense Embedding
9. **Semantic Caching** — 0.85 threshold + FAISS/hnswlib index
10. **State Compression** — zstd + Product Quantization for reasoning traces

### Wave 4: Scale & Ecosystem
11. **NATS JetStream** — Competing consumers + KEDA HPA
12. **A2A Protocol** — Agent Card (full spec) + 3-layer protocol stack
13. **TypeScript SDK** — openapi-typescript + openapi-fetch

### Wave 5: Quality & Maturity
14. **SPRT + ConSol** — Variance-Calibrated Budgeting + 3-valued verdicts
15. **Behavioral Fingerprinting** — 6 feature families + Hotelling's T²
16. **Agent Mutation Testing** — Stochastic Kill Semantics + 5D Coverage Tuple
17. **Marketplace + Certification** — 10-25% commission + 4-competency certification

---

## Appendix: Source PDF Index

| # | PDF Title | Pages | Key Domain |
|---|-----------|-------|------------|
| 1 | Platform Maturity & Observability | 5 | SDK, OTel, Marketplace |
| 2 | Agentic Reliability & Interoperability | 4 | SPRT, A2A, Guardrails |
| 3 | Advanced Memory & Data Infrastructure | 4 | HSM, HNSW, Compression |
| 4 | Cost-Aware Routing & Intelligence | 4 | CSCR, Thompson, Distillation |
| 5 | Agentic IAM & Security Governance | 6 | DID, OIDC, zcap-ld, ZKP |
| 6 | Foundations of AI Agent Ecosystems | 4 | Architecture, Taxonomy |
| 7 | Quality Assurance Report | 4 | Reliability Surface, Coverage |
| 8 | Production Telemetry & Tracing | 6 | Spans, Structlog, Collector |
| 9 | Safety, Guardrails & Reliability | 4 | PromptShield, Rate Limiting |
| 10 | Server & API Layer Specification | 3 | FastAPI, SSE, Concurrency |
| 11 | Cost Management & Attribution | 3 | Budget, Chargeback, Loop Audit |
| 12 | Multi-Tier Memory Specification | 4 | Hot/Warm/Cold, Dedup, Scoring |
