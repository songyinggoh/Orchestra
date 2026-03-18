# Phase 4: Curated Tools & Libraries — Detailed Research

**Date:** 2026-03-11
**Scope:** 13 specific tools/libraries recommended for Phase 4 integration

---

## Integration Priority Matrix

| Tool | Priority | Maturity | Async Ready | License | Notes |
|------|----------|----------|-------------|---------|-------|
| **A2A Protocol** | Critical | High (Google/LF) | Native async | Apache 2.0 | Standard for agent interop |
| **Ray Serve** | High | Very High | Native async | Apache 2.0 | Scaling backbone (but heavy — 500MB+) |
| **Neo4j** | High | Very High | Native async | GPL v3 (Community) | Warm-tier graph memory |
| **RouteLLM** | High | Medium | Needs wrapping | Apache 2.0 | Cost-aware routing |
| **Prompt Guard 2 86M** | High | High (Meta) | Needs wrapping | Meta Community | Multilingual injection+jailbreak |
| **Zstandard** | Medium | Very High | Needs wrapping | BSD-3 | Cold-tier compression |
| **DeBERTa Injection v2** | Medium | Medium | Needs wrapping | Apache 2.0 | Fast English injection detection |
| **ConSol SPRT** | Medium | Low (new) | Unknown | Unknown | Token-efficient self-consistency |
| **ACA-Py** | Medium | High | REST API | Apache 2.0 | Enterprise DID mgmt (heavy infra) |
| **MotleyCrew** | Low | Low-Medium | Partial | Apache 2.0 | Learn from patterns, not depend on |
| **peerdid-python** | Low | Low (dormant) | No | Apache 2.0 | Lightweight DIDs; dormant since 2023 |
| **zcapld/zcap** | Low | Medium | N/A (JS only) | BSD-3 | No Python impl; spec-only value |
| **ParticleThompsonSamplingMAB** | Low | Very Low | No | Unknown | Academic reference only |

---

## 1. RouteLLM

- **Repo:** lm-sys/RouteLLM | **Stars:** ~4.3k | **License:** Apache 2.0
- **PyPI:** `routellm` 0.2.0
- **4 built-in routers:** `mf` (Matrix Factorization — recommended), `bert`, `sw_ranking`, `causal_llm`
- **Results:** 85%+ cost reduction on MT-Bench, 45% on MMLU, 35% on GSM8K vs always GPT-4
- Uses LiteLLM under the hood — any OpenAI-compatible endpoint works

```python
from routellm.controller import Controller
client = Controller(routers=["mf"], strong_model="gpt-4o", weak_model="gpt-3.5-turbo")
response = client.chat.completions.create(model="router-mf-0.5", messages=[...])
```

**Integration:** No native async — wrap with `asyncio.to_thread()` or use HTTP server mode. MF router is sub-millisecond inference.

---

## 2. ParticleThompsonSamplingMAB

- **Repo:** colby-j-wise/ParticleThompsonSamplingMAB | **Stars:** ~10-20
- **Status:** Academic project (2018, Columbia COMS6998). Single Jupyter notebook, not packaged.
- **Value:** Algorithmic reference for particle-filter-based Thompson Sampling over factorized reward matrix
- **Integration:** Reimplement the algorithm (~150 lines), don't depend on this repo

---

## 3. Ray Serve

- **Repo:** ray-project/ray | **Stars:** ~36k+ | **License:** Apache 2.0
- **Latest:** Ray 2.54.0 (Feb 2026)
- **Key:** Deployment Graphs for multi-model composition, LLMServer with prefill-decode disaggregation, Direct Transport for GPU-to-GPU
- **"Brain-Hands-Engine" pattern:** Community architectural pattern — Brain (orchestrator), Hands (tools), Engine (Ray Serve scaling)

```python
@serve.deployment
class Agent:
    async def __call__(self, request):
        return await self.process(request)
```

**Integration:** Native async, but ~100MB+ install. Make optional: `pip install orchestra[ray]`. Per competitive analysis, NATS + competing consumers may be sufficient for Phase 4.

---

## 4. MotleyCrew

- **Repo:** MotleyAI/motleycrew | **Stars:** ~300-500 | **License:** Apache 2.0
- Mixes agents from LangChain, LlamaIndex, CrewAI, AutoGen as DAGs
- Ray integration: tasks become `@ray.remote` calls
- Knowledge graph via Kuzu embedded DB
- **Integration:** Learn from patterns (especially Ray DAG execution), don't take hard dependency

---

## 5. ACA-Py (Aries Cloud Agent Python)

- **Repo:** openwallet-foundation/acapy (renamed from hyperledger/) | **Stars:** ~400+
- **License:** Apache 2.0 | **PyPI:** `acapy-agent` (renamed from `aries-cloudagent`)
- **Latest:** 1.4.0 with Kanon Storage (separates KMS from data persistence)
- Full DID management, multi-tenant, W3C VC, DIDComm v1/v2
- REST API + webhooks

**Integration:** Heavy infrastructure (Askar wallet + PostgreSQL). Multi-tenant model maps to Orchestra's multi-agent architecture. Use REST API via `httpx.AsyncClient`.

---

## 6. peerdid-python

- **Repo:** sicpa-dlab/peer-did-python | **Stars:** ~15-25 | **License:** Apache 2.0
- **Latest:** 0.5.2 (July 2023 — **dormant**)
- Lightweight `did:peer` creation/resolution without ledger
- No async support, synchronous only

```python
from peerdid.core.peer_did_helper import create_peer_did_numalgo_2
from peerdid.peer_did import resolve_peer_did
did = create_peer_did_numalgo_2(encryption_keys=[...], signing_keys=[...], service=service)
```

**Integration:** Small enough to vendor/fork. Use for ephemeral agent DIDs. Complement with ACA-Py for enterprise.

---

## 7. zcapld / @digitalbazaar/zcap

- **Repo:** digitalbazaar/zcap | **Stars:** ~30-40 | **License:** BSD-3
- **Latest:** @digitalbazaar/zcap v9.0.0 (npm) — **JavaScript ONLY**
- ZCAP-LD spec v0.3 implementation: capability delegation with chain-of-custody, caveats, revocation

**Integration:** NO Python implementation. Options:
1. Build from spec using `pyld` + `PyNaCl` (significant effort)
2. Node.js sidecar (adds complexity)
3. **Recommended:** Simplified capability model inspired by ZCAP-LD using `joserfc` for JWT operations — `delegate()`, `invoke()`, `revoke()` methods

---

## 8. Llama Prompt Guard 2 86M

- **Model:** meta-llama/Llama-Prompt-Guard-2-86M (HuggingFace)
- **License:** Meta Llama Community License
- **Architecture:** Fine-tuned mDeBERTa-v3-base (86M backbone + 192M word embeddings)
- **Multi-label:** benign / injection / jailbreak
- **Multilingual:** EN, FR, DE, HI, IT, PT, ES, TH
- CPU inference: ~5-10ms per input

```python
from transformers import pipeline
classifier = pipeline("text-classification", model="meta-llama/Llama-Prompt-Guard-2-86M")
result = classifier("Ignore previous instructions and...")
# [{'label': 'INJECTION', 'score': 0.98}]
```

**Integration:** Wrap with `asyncio.to_thread()`. Model download ~350MB, cache in deployment. Successor: Llama Guard 4 (Dec 2025, larger).

---

## 9. DeBERTa-v3-small Prompt Injection v2

- **Model:** protectai/deberta-v3-small-prompt-injection-v2 (HuggingFace)
- **License:** Apache 2.0
- **Architecture:** Fine-tuned microsoft/deberta-v3-small (~44M params)
- Binary: benign (0) vs injection (1). English only. Does NOT detect jailbreak.
- Faster than Prompt Guard 86M

**Integration:** Complementary to Prompt Guard — use DeBERTa for fast English injection screening, Prompt Guard for multilingual + jailbreak. Ensemble approach for production.

---

## 10. ConSol (SPRT for LLM Self-Consistency)

- **Repo:** LiuzLab/consol | **Stars:** Small (new)
- **PyPI:** `pip install consol` | **Paper:** arXiv:2503.17587
- **Modes:** `msprt`, `sprt`, `pvalue`, `bayesian_posterior`, `vote40`, `vote1`
- **Results:** 85-88% token reduction while maintaining accuracy vs full self-consistency

```python
from consol import ConSol
solver = ConSol(models=["gpt-4o-mini"], confidence_models=["msprt", "sprt"])
result = solver.solve(prompt="...")
```

**Integration:** Directly applicable to Orchestra's reliability module. `msprt` is calibrated for LLM output distributions. Very new (March 2025) — API may change. **Note:** Previously CUT from Phase 3 per ToT analysis.

---

## 11. A2A Protocol (Agent-to-Agent)

- **Spec:** a2aproject/A2A (~5k+ stars) | **SDK:** a2aproject/a2a-python
- **License:** Apache 2.0 (Google/Linux Foundation)
- **SDK version:** `a2a-sdk` 0.3.24 (Feb 20, 2026) | **Spec:** v0.3.0
- Agent Card at `.well-known/agent-card.json` (canonicalized per RFC 8785)
- Transports: JSON-RPC 2.0 over HTTP(S), gRPC (v0.3+)
- Built-in OTel tracing, FastAPI/Starlette integration

```python
from a2a.server import A2AServer
from a2a.types import AgentCard, AgentSkill
card = AgentCard(name="Orchestra Agent", skills=[...], capabilities={"streaming": True})
server = A2AServer(agent_card=card, handler=my_handler)
```

**Integration:** Async-first SDK, perfect FastAPI alignment, Google backing + LF governance = strong longevity.

---

## 12. Neo4j (Graph Memory)

- **Driver:** neo4j/neo4j-python-driver | **Stars:** ~900+ | **License:** Apache 2.0 (driver)
- **Driver version:** 6.1.0 (Jan 2026) | **Server:** Neo4j Community (GPL v3) or Enterprise (commercial)
- Full `asyncio` support: `AsyncGraphDatabase.driver()`, `AsyncSession`
- **neo4j-labs/agent-memory:** Purpose-built graph memory (Short-Term, Long-Term, Reasoning)
- **Graphiti (Zep):** Knowledge graph memory on Neo4j for dynamic agents

```python
from neo4j import AsyncGraphDatabase
async with AsyncGraphDatabase.driver(URI, auth=AUTH) as driver:
    async with driver.session() as session:
        records = await session.execute_read(
            lambda tx: tx.run("MATCH (a:Agent)-[:KNOWS]->(f:Fact) RETURN f").values()
        )
```

**Integration:** Mature async driver. GPL v3 Community Edition is copyleft concern — Enterprise requires commercial license. Consider Kuzu or Memgraph as lighter embedded alternatives.

---

## 13. Zstandard (zstd)

- **Lib:** indygreg/python-zstandard | **Stars:** ~600+ | **License:** BSD-3
- **Latest:** python-zstandard 0.25.0 | **Alt:** `compression.zstd` in Python 3.14+ stdlib (PEP 784)
- Dictionary-based compression (train on similar data for 5-10x better ratios)
- Streaming compress/decompress, seekable file format
- Levels 1-22 (default 3)

```python
import zstandard as zstd
cctx = zstd.ZstdCompressor(level=3)
compressed = cctx.compress(data)

# Dictionary training for agent traces
dict_data = zstd.train_dictionary(131072, [sample1, sample2, ...])
cctx = zstd.ZstdCompressor(dict_data=dict_data)
```

**Integration:** Dictionary training on agent message patterns is key win. CPU-bound — use `asyncio.to_thread()` for large data. BSD-3 is maximally permissive.

---

## Key Async Integration Patterns

Most tools need async wrapping for Orchestra's async-first architecture:

```python
# Pattern 1: Thread pool for sync libraries
result = await asyncio.to_thread(sync_function, *args)

# Pattern 2: HTTP client for REST APIs (ACA-Py, A2A)
async with httpx.AsyncClient() as client:
    response = await client.post(url, json=payload)

# Pattern 3: Native async (Neo4j, redis-py, nats-py, a2a-sdk)
async with AsyncGraphDatabase.driver(uri) as driver:
    async with driver.session() as session:
        await session.execute_read(query)
```
