# Phase 4: Testing, Safety & Guardrails — Research Report

**Researched:** 2026-03-11
**Domain:** Statistical testing, behavioral analysis, mutation testing, prompt injection defense

---

## 1. SPRT (Sequential Probability Ratio Test)

### How It Works
SPRT tests hypotheses one observation at a time, making decisions at each step (accept H0, reject H0, or continue). **Optimal:** no other test with same error rates uses fewer samples on average.

**Algorithm:**
1. H0: Agent success rate = p0 (baseline, e.g., 0.92)
2. H1: Agent success rate = p1 (degraded, e.g., 0.85)
3. Boundaries: A = (1-beta)/alpha, B = beta/(1-alpha)
4. Update log-likelihood ratio after each observation
5. Decide when ratio crosses boundary; cap at N_max for truncation

**ConSol (arXiv 2503.17587):** SPRT applied to LLM reasoning consistency, cutting samples by 40-60%.

### Python: Build Custom (~100 lines)
No maintained library exists. Use `scipy.stats.binom.logpmf()` for likelihood. Build `SPRTBinomial` with `update(bool) -> Decision`.

---

## 2. Behavioral Fingerprinting

### Features to Extract
- **Response:** length distribution, token counts, latency (TTFT, total), vocabulary diversity
- **Tool Usage:** call frequency per tool, ordering n-grams, argument patterns, error rates
- **Decision:** handoff frequency, state size growth, retry/fallback rate, reasoning chain length
- **Errors:** type distribution, per-task failure rates, exception clusters

### Drift Detection Methods
| Method | Python | Use For |
|--------|--------|---------|
| **KL Divergence** | `scipy.stats.entropy(pk, qk)` | Categorical data (tool usage, error types) |
| **KS Test** | `scipy.stats.ks_2samp()` | Continuous data (latency, response length) |
| **CUSUM** | `menelaus` library | Online real-time monitoring |
| **PSI** | Custom numpy | Overall stability scoring |
| **JSD** | `scipy.spatial.distance.jensenshannon()` | Symmetric alternative to KL |

**Agent Drift paper (arXiv 2601.04170):** Defines Agent Stability Index (ASI) — composite metric covering semantic drift, coordination drift, and behavioral degradation. Directly applicable.

**Behavioral Fingerprinting paper (arXiv 2509.04504):** Diagnostic Prompt Suite with LLM-as-judge. Core capabilities converge; alignment behaviors vary dramatically.

### Libraries
- `scipy.stats` (already transitive dep) — KS, entropy, statistical tests
- `menelaus >= 0.3` — CUSUM, ADWIN for online detection
- Avoid heavy `evidently` or `alibi-detect`

---

## 3. Agent Mutation Testing

### Tools
| Tool | Stars | Status | Key Feature |
|------|-------|--------|-------------|
| **mutmut** | ~1.2k | Active (3.3.1) | Incremental, mypy filtering, pytest |
| **cosmic-ray** | ~500 | Feb 2026 | Parallel via Celery, pluggable operators |
| **Mutahunter** | ~258 | Oct 2025 | LLM-generated context-aware mutations |

### Agent-Specific Mutation Types

**Tool Call:** injection, deletion, argument corruption, response corruption, timeout injection
**Prompt:** system prompt truncation, instruction injection, few-shot deletion, temperature perturbation
**State:** key deletion, value corruption, rollback, handoff target swap
**Reliability:** provider error injection, partial response, rate limit injection

### LLM-Powered Mutations
- **AdverTest (arXiv 2602.08146):** Two adversarial LLM agents (Test Generator + Mutant Generator) iterate. Outperforms traditional operators.
- **Meta (arXiv 2501.12862):** Mutation testing feedback guides LLM-based test generation in production.

### Implementation
Phase A: `mutmut` on existing 244+ tests → baseline mutation score
Phase B: Custom `AgentMutator` fixtures (ToolCallMutator, PromptMutator, StateMutator, ProviderMutator)
Phase C: Mutahunter for PR-level context-aware mutations

---

## 4. PromptShield SLM

### Available Models

| Model | Size | Accuracy/F1 | License |
|-------|------|-------------|---------|
| **Sentinel** (qualifire) | ~355M | 0.987/0.980 | Open |
| **Llama Prompt Guard 2** | 86M/22M | High | Llama |
| **protectai/deberta-v3-base-v2** | ~184M | High | Apache 2.0 |
| **deepset/deberta-v3-base-injection** | ~184M | Good | Apache 2.0 |

**Sentinel** is current SOTA (arXiv 2506.05446), ModernBERT-large, 8K context.
### Deployment Pattern: Parallel Execution (Zero Added Latency)

```python
async def guarded_agent_call(prompt, agent):
    guard_task = asyncio.create_task(run_injection_guard(prompt))  # ~10-50ms GPU
    llm_task = asyncio.create_task(agent.call_llm(prompt))         # ~500-3000ms
    guard_result = await guard_task
    if guard_result.is_injection:
        llm_task.cancel()
        raise PromptInjectionDetected(guard_result)
    return await llm_task
```

Guard is always faster than LLM → zero latency overhead on happy path.

---

## 4.1 PromptShield Residual Risk — Output Scanning & Attenuation

### Rationale: The 35% Bypass Gap
Prompt injection is the most common attack vector for agent systems. A "shield" like Prompt Guard with a 65% success rate leaves a 35% residual risk — a gap too large for enterprise applications.

### Implementation: Defense-in-Depth

| Technology | Role | Benefit |
|------------|------|---------|
| **Output Scanning** | Post-Execution Check | Scan agent outputs (before they are used by a tool or sent to a user) for malicious tokens or unauthorized commands. |
| **Capability Attenuation** | Contextual Restriction | Dynamically reduce an agent's available tools when a high-risk prompt is detected (e.g., "Network-less" mode). |
| **PII Scrubbing** | Privacy Guard | Scan outputs for PII to prevent data leakage during a successful injection attack. |

### Recommendation for Orchestra
- **P1 Action:** Implement **Output Scanning** as a mandatory second layer for all high-value agent responses.
- **P1 Action:** Neutralize successful injections using **Capability Attenuation**, switching agents to a "Restricted Mode" (no networking/disk) when PromptShield flags a suspicious prompt (even with low confidence).

---

### Rebuff Migration (ARCHIVED May 2025)
| Rebuff Layer | Replacement |
|-------------|-------------|
| Heuristic scanning | Keep (regex patterns) |
| LLM-based detection | SLM classifier (Sentinel) |
| VectorDB scanning | Optional embedding similarity |
| Canary tokens | Keep |

### CPU Optimization
Use ONNX Runtime (`optimum` library) for 2-4x speedup over vanilla PyTorch on CPU.

---

## Custom Components to Build

| Component | Lines (est.) | Description |
|-----------|-------------|-------------|
| `SPRTBinomial` | ~100 | Truncated SPRT for binary pass/fail |
| `BehavioralFingerprint` | ~200 | Feature extraction + baseline + drift scoring |
| `DriftMonitor` | ~150 | Online KS/KL/CUSUM monitoring |
| `AgentMutator` | ~300 | Agent-specific mutation operators |
| `PromptShieldGuard` | ~150 | Async SLM wrapper with parallel execution |

## Dependencies

| Library | Purpose | Priority |
|---------|---------|----------|
| `scipy` | Statistical tests | P0 (already transitive) |
| `transformers` | Load SLM models | P1 |
| `torch` or `onnxruntime` | SLM inference | P1 |
| `mutmut` | Mutation testing | P2 (dev-only) |
| `menelaus` | Online drift detection | P3 |
