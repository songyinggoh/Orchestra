# Phase 4 GitHub Repository Survey

**Date:** 2026-03-11

---

## Recommended Stack

| Capability | Primary Choice | Stars | Alternative |
|---|---|---|---|
| Distributed compute | **ray-project/ray** | ~40.9k | — |
| Inter-agent messaging | **nats-io/nats.py** | ~1.2k | Redis Streams |
| Agent interop | **a2aproject/a2a-python** | ~1.2k | Custom gRPC |
| DID / identity | **openwallet-foundation/acapy** | — | Custom JWT |
| Capability auth | Build from **ucan-wg/spec** | — | JWT + delegation |
| Prompt injection | **protectai/llm-guard** | ~2.5k | NeMo Guardrails (~5k) |
| Semantic cache | Build using **hnswlib** patterns | ~5k | GPTCache (~7.9k, slowing) |
| Cost routing | **BerriAI/litellm** (reference) | ~37.9k | lm-sys/RouteLLM (~3.5k) |
| Mutation testing | **boxed/mutmut** | ~1.2k | mutahunter (~258, AGPL) |
| K8s operator | **nolar/kopf** | ~2k | — |
| TS client codegen | **openapi-ts/openapi-typescript** | ~7.9k | orval (~5.5k) |
| Vector search | **hnswlib** (cache) / **pgvector** (storage) | ~5k/~20.2k | FAISS (~39.3k) |
| OTel pipeline | **opentelemetry-collector-contrib** | ~4.4k | — |

---

## Key Findings by Topic

### 1. Ray + Agents
- `ray-project/ray`: 40.9k stars, Apache-2.0. Ray Serve wraps FastAPI via `@serve.ingress`. Async actors with `max_concurrency`.
- `langroid/langroid`: 3.9k stars. Actor-model multi-agent framework. Reference architecture.

### 2. NATS Python
- `nats-io/nats.py`: 1.2k stars, v2.14.0 (Feb 2026). Full JetStream support, async-native, pull consumers.
- `orsinium-labs/walnats`: NATS-powered background jobs. Reference for job queues.

### 3. A2A Protocol
- `a2aproject/A2A`: 1k+ stars. Official spec (Linux Foundation).
- `a2aproject/a2a-python`: v0.3.3 (Feb 2026). Official Python SDK.
- `themanojdesai/python-a2a`: Community SDK with MCP integration.

### 4. DID / Verifiable Credentials
- `openwallet-foundation/acapy`: Most mature Python DID/VC toolkit. did:peer, did:webvh, W3C VC, BBS+.
- **`spruceid/didkit`: ARCHIVED July 2025.** Must use ACA-Py or build custom.

### 5. Capability-Based Security
- `w3c-ccg/zcap-spec`: W3C Community Group spec.
- `digitalbazaar/zcap`: Reference implementation — **JavaScript only, no Python**.
- `ucan-wg/spec`: More active than zcap-ld. Go + TS implementations. **No Python lib — must build.**

### 6. Prompt Injection Defense
- `protectai/llm-guard`: 2.5k stars, MIT. Most comprehensive active toolkit.
- `NVIDIA-NeMo/Guardrails`: ~5k stars. Colang 2.0 DSL, parallel flows, OTel integration.
- **`protectai/rebuff`: ARCHIVED May 2025.** Migration required.
- `lakeraai/pint-benchmark`: 4,314-input benchmark dataset.

### 7. Semantic Caching
- `zilliztech/GPTCache`: 7.9k stars, MIT. Modular architecture. **Maintenance slowing** — 83 unreleased commits.
- Recommendation: Build lighter custom cache using hnswlib + embed-then-search pattern.

### 8. Cost Routing
- `BerriAI/litellm`: 37.9k stars. Dominant LLM gateway. Budget limits, fallback chains, routing strategies.
- `lm-sys/RouteLLM`: 3.5k stars. 4 pre-trained routers (SW-ranking, BERT, causal LLM, MF). Up to 70% cost reduction.
- `Portkey-AI/gateway`: 10.8k stars. Sub-1ms overhead, 10B+ tokens/day. TypeScript only.

### 9. Mutation Testing
- `boxed/mutmut`: 1.2k stars, BSD. Incremental, mypy filtering, pytest.
- `sixty-north/cosmic-ray`: ~500 stars. Pluggable operators, Celery-distributed.
- `codeintegrity-ai/mutahunter`: 258 stars, **AGPL**. LLM-generated mutations.

### 10. K8s Operator
- `nolar/kopf`: 2k+ stars, MIT. Decorator-based Python operators. Stable, maintenance mode.

### 11. n8n Custom Nodes
- `n8n-io/n8n-nodes-starter`: Official template. CLI scaffolding.
- `nerding-io/n8n-nodes-mcp`: MCP integration node — reference for protocol nodes.

### 12. OpenAPI TypeScript Codegen
- `openapi-ts/openapi-typescript`: 7.9k stars. Types + openapi-fetch (6kb, zero runtime).
- `hey-api/openapi-ts`: 5k+ stars. Full SDK generation with Zod + TanStack Query.
- `orval-labs/orval`: 5.5k stars. React Query / Vue Query hooks.

### 13. Vector Search
- `facebookresearch/faiss`: 39.3k stars. GPU support, multiple index types.
- `nmslib/hnswlib`: 5k stars. Lightweight CPU-only HNSW. **Best for semantic cache.**
- `qdrant/qdrant`: 29.5k stars. Distributed, async Python client.
- `pgvector/pgvector`: 20.2k stars. PostgreSQL extension, HNSW + IVFFlat.

### 14. OTel Collector
- `open-telemetry/opentelemetry-collector`: 6.6k stars. Core receivers/processors/exporters.
- `open-telemetry/opentelemetry-collector-contrib`: 4.4k stars. Extended components (Prometheus exporter, k8sattributes).
- `open-telemetry/opentelemetry-operator`: K8s operator for Collector management.

---

## Key Risks

1. **No Python zcap-ld or UCAN library** — must build minimal capability auth from spec
2. **DIDKit archived** — ACA-Py is heavy; extracting just DID resolution is non-trivial
3. **GPTCache maintenance declining** — build purpose-built semantic cache
4. **Rebuff archived** — use llm-guard or NeMo Guardrails
5. **kopf in maintenance mode** — acceptable (stable), no new features
6. **Mutahunter is AGPL** — copyleft concern; use as reference only
