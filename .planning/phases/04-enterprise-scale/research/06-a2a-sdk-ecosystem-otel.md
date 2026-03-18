# Phase 4 Research: Interoperability, SDK, Ecosystem & Observability

**Date:** 2026-03-11
**Scope:** A2A protocol, agent registries, manifests, arbitration, TypeScript SDK, visual builders, marketplace, certification, OTel Collector, Prometheus, sampling.

---

## 1. A2A Protocol (Agent-to-Agent)

### Overview
Google's open standard for cross-framework agent communication. Launched April 2025, 150+ supporting orgs by v0.3. **Complementary to MCP** — MCP is vertical (agent-to-tool), A2A is horizontal (agent-to-agent).

### Protocol
- Transport: HTTPS (required), gRPC (v0.3+)
- Wire format: JSON-RPC 2.0
- Streaming: Server-Sent Events
- Task lifecycle: `submitted → working → [input-required] → completed | failed`

### Python SDK: `a2a-sdk >= 0.3.24`
- GitHub: `a2aproject/a2a-python`
- Built on Starlette/ASGI
- Key classes: `AgentCard`, `AgentSkill`, `RequestHandler`, `A2AStarletteApplication`, `AgentExecutor`
- Alternative: `fasta2a` (Pydantic) — v0.2.5 only, less maintained

### Integration
1. Define `AgentSkill` from Orchestra graph definitions
2. Build `AgentCard` from registered graphs
3. Serve at `/.well-known/agent-card.json` on FastAPI
4. Implement `AgentExecutor` translating A2A tasks to graph runs
5. Mount `A2AStarletteApplication` as sub-app

---

## 2. A2A Agent Card Registry

### Discovery Mechanisms
1. **Well-Known URL**: `/.well-known/agent-card.json`
2. **Central Registry**: Enterprise curated registry server
3. **Standards in progress**: AGNTCY ADS (IETF draft), GoDaddy ANS

### Implementation
Dynamic card generation from `GraphRegistry` — new graphs auto-appear as skills.

---

## 3. Agent Manifest (RFC)

### Competing Standards
| Standard | Format | Status |
|----------|--------|--------|
| A2A Agent Card | JSON | Production (v0.3) |
| OASF (Cisco/Agntcy) | JSON Schema | Released 2025 |
| JSON Agents (PAM) | JSON | Draft spec, 7 capabilities |
| AGENTS.md | Markdown | 60k+ repos |

### Recommendation
A2A Agent Card as primary discovery format. Layer cost/SLA/pricing as extensions. JSON Agents PAM as schema inspiration.

---

## 4. Arbitration Nodes

### Strategies
| Strategy | Best For | Research |
|----------|----------|----------|
| **Priority-Based** | Resource allocation, tenant tiers | Simplest |
| **Voting** | Reasoning tasks (+13.2% accuracy, ACL 2025) | Good default |
| **Weighted Voting** | Domain expertise decisions | Most flexible |
| **Consensus** | Knowledge tasks (+2.8%), safety-critical | Highest overhead |

### Recommendation
Start with priority-based (maps to tenant tiers). Add weighted voting for multi-agent recommendation conflicts. Defer full consensus.

---

## 5. TypeScript Client SDK

### Recommended: openapi-typescript + openapi-fetch
- Zero runtime cost (6kb), type-safe, works everywhere
- FastAPI auto-generates OpenAPI spec → `npx openapi-typescript` → type-safe client
- SSE streaming via async generator over response body

### Alternative: Orval
For React projects — generates React Query hooks with MSW mocks.

---

## 6. Visual Builder Partnerships

### n8n
- Custom node scaffolding: `npm create @n8n/node`
- Declarative style maps to Orchestra REST endpoints
- Publish as `n8n-nodes-orchestra` to npm

### Flowise
- OpenAPI Toolkit: auto-parses Orchestra endpoints into tools
- MCP Integration: Flowise natively supports MCP
- Zero-effort integration from Orchestra's side

---

## 7. Agent Marketplace

### Trust Layers
1. Namespace verification (verified publishers)
2. Automated scanning (dependency vulnerabilities)
3. Community signals (downloads, ratings)
4. Provenance attestation (Sigstore)
5. Sandbox testing (isolated test runs)

### Package Format
```
orchestra-agent-{name}-v{version}/
  manifest.json, graph.yaml, tools/, prompts/, tests/,
  CHANGELOG.md, LICENSE, signatures/
```

---

## 8. Certification Program

### Design (modeled on CKA)
- **Tier 1 — Orchestra Certified Developer (OCD):** 90 min, performance-based, 70% pass. Domains: graph composition (25%), tool/MCP integration (20%), observability (20%), reliability (20%), deployment (15%).
- **Tier 2 — Orchestra Certified Architect (OCA):** 120 min, 74% pass. Requires OCD.
- Defer to late Phase 4 or Phase 5.

---

## 9. OTel Collector Pipeline Config

### Deployment: 2-Tier (Agent + Gateway)
- Agent collectors alongside app pods (batch, compress)
- Gateway collectors centralized (tail sampling, PII scrub)
- Latest: `opentelemetry-collector-contrib:0.147.0`

### Key Processors
`memory_limiter` (always first) → `filter` (drop health checks) → `resource` (add env/service) → `attributes` (enrich) → `batch` (efficient export)

---

## 10. Prometheus Exporter

### Recommended: OTel Prometheus Exporter
```python
from opentelemetry.exporter.prometheus import PrometheusMetricReader
reader = PrometheusMetricReader()
provider = MeterProvider(metric_readers=[reader])
```
Metrics at `http://localhost:9464/metrics`.

### LLM-Optimized Histogram Buckets (ms)
`[100, 250, 500, 1000, 2500, 5000, 10000, 30000, 60000, 120000]`

Apply via OTel SDK Views on `gen_ai.client.operation.duration`.

### AI Golden Signals
| Metric | Type | Labels |
|--------|------|--------|
| `gen_ai.client.operation.duration` | Histogram | system, model, operation |
| `gen_ai.client.token.usage` | Counter | system, model, token_type |
| `gen_ai.client.operation.errors` | Counter | error_type |
| `orchestra.cost_usd` | Counter | system, model |

---

## 11. Sampling Strategy

### Head Sampling (SDK-level)
```python
sampler = ParentBasedTraceIdRatio(rate=0.5)  # 50% base
```

### Tail Sampling (Gateway Collector)
```yaml
policies:
  - name: errors       # ALWAYS keep errors
    type: status_code
    status_code: { status_codes: [ERROR] }
  - name: slow-traces  # ALWAYS keep slow (>10s)
    type: latency
    latency: { threshold_ms: 10000 }
  - name: high-cost    # ALWAYS keep expensive
    type: string_attribute
    string_attribute: { key: orchestra.cost_tier, values: [high, critical] }
  - name: normal       # Sample 10% of normal
    type: probabilistic
    probabilistic: { sampling_percentage: 10 }
```

**Critical:** Do NOT batch before tail sampling. Correct order: `[memory_limiter, tail_sampling, batch]`

**Volume reduction:** ~85-90% with 100% error/slow retention.

---

## Implementation Priority

1. **Wave 1:** OTel Collector + Prometheus + Sampling (deferred from Phase 3)
2. **Wave 2:** A2A protocol + Agent Card + Manifest
3. **Wave 3:** TypeScript SDK
4. **Wave 4:** Visual Builders + Marketplace
5. **Wave 5:** Arbitration + Certification
