# Phase 4 Research: Cost Routing & Intelligence

**Research date:** 2026-03-11
**Scope:** 8 topics under the "Cost Routing & Intelligence" cluster in Phase 4
**Context:** Orchestra already has `CostAggregator` (EventBus subscriber), `BudgetPolicy` (soft/hard limits), and `ModelCostRegistry` (per-model pricing with 16 models in `_default_prices.json`)

---

## 1. Cost-Aware Routing

### Existing Implementations (2025-2026)

| Project | Type | Approach | Cost Savings |
|---------|------|----------|--------------|
| **RouteLLM** (LMSYS) | OSS framework | Trained classifiers (BERT, MF, causal LLM, SW-ranking) on preference data | Up to 85% cost reduction at 95% GPT-4 quality |
| **LiteLLM** (BerriAI) | OSS proxy | RPM/TPM-based routing, provider budget limits, Redis-backed spend tracking | Configurable per-provider budgets |
| **Martian** | Commercial SaaS | Query analysis + model capability matching | Up to 98% claimed |
| **NotDiamond** | Commercial + OSS | Custom router training on eval data, multi-objective optimization | Up to 10x |
| **Portkey** | Commercial gateway | Semantic caching, load balancing, automatic failover | Variable |

### Task Complexity Classification — Three Tiers

**Tier 1 — Heuristic Rules (no ML, implement immediately):**
Classify by token count, tool count, whether tool calls are expected, and reasoning depth. Route "simple" to Haiku/Flash/GPT-4o-mini, "moderate" to Sonnet/GPT-4o, "complex" to Opus/o1. A hybrid query routing system using this approach reduced LLM usage 37-46% and latency 32-38%, yielding 39% cost reduction.

**Tier 2 — Trained Classifier (RouteLLM-style):**
Train a BERT classifier on preference data (prompt + which model "won"). RouteLLM provides 4 pre-trained routers out of the box via `pip install routellm`. It acts as a drop-in OpenAI client replacement.

**Tier 3 — Contextual Bandits (see Topic 2):**
Online learning that adapts routing based on observed outcomes. No pre-labeled training data needed.

### Integration with Orchestra

The proposed `CostAwareRouter` sits between `Agent.run()` and `LLMProvider.complete()`. It uses the existing `ModelCostRegistry` for pricing lookups and `BudgetPolicy.suggested_model` for budget-driven downgrades. The router should be a `Protocol` so users can plug in custom classifiers (including commercial APIs like NotDiamond).

### Key Libraries
- `routellm` — drop-in RouteLLM framework with pre-trained routers
- `litellm` — unified proxy with budget routing across 100+ providers
- `scikit-learn` — for training custom classifiers
- `sentence-transformers` — for embedding-based similarity routing

---

## 2. Thompson Sampling for Model Selection

### Algorithm

Thompson Sampling maintains Beta distribution posteriors over each model's expected reward. At each decision point: (1) sample theta_m from Beta(alpha_m, beta_m) for each model, (2) select the model with highest cost-adjusted sample: m* = argmax(theta_m / cost_m), (3) observe outcome and update the posterior: alpha += successes, beta += failures. The Beta(1,1) prior (uniform) is standard for cold start.

For continuous rewards (quality scores), use Normal(mu, sigma^2) posteriors updated with Bayesian updates, or discretize into success/failure via a quality threshold.

### Defining Reward Signals from Agent Outcomes

| Signal | Type | How to Measure in Orchestra |
|--------|------|---------------------------|
| Task completion | Binary | Agent returned result without errors |
| Tool call success | Binary | All tool calls executed without validation errors |
| Self-check score | Continuous [0,1] | Existing `SelfCheckScorer` |
| FACTScore | Continuous [0,1] | Existing `FactScoreScorer` |
| Latency within SLA | Binary | Response time < target TTFT |
| Cost efficiency | Continuous | quality_score / cost_usd |

A composite reward function is recommended: `reward = quality_score * latency_penalty * cost_factor`, where latency_penalty=1.0 if within SLA (0.8 otherwise), and cost_factor = 1/(1+cost_usd).

### Python Libraries

| Library | Install | Features |
|---------|---------|----------|
| `contextualbandits` | `pip install contextualbandits` | LinUCB, Thompson Sampling, adaptive greedy; takes sklearn classifiers as oracle |
| `thompson` (erdogant) | `pip install thompson` | Thompson Sampling + UCB; visualization; Beta/Gaussian posteriors |
| `vowpalwabbit` | `pip install vowpalwabbit` | Industrial-strength contextual bandits (Microsoft) |
| `numpy` alone | built-in | 10-line implementation with `np.random.beta()` |

### 2025 Academic Work on Bandits for LLM Routing

- **LinUCB-based LLM selection** (arxiv 2506.17670): Contextual bandit framework for sequential LLM selection with budget-aware extensions. Sublinear regret without future context prediction.
- **Multi-objective routing** (arxiv 2510.07429): Preference-conditioned approach balancing performance and cost. Reported 16.84% accuracy improvement and 50% cost reduction.
- **LLM-augmented bandits** (arxiv 2311.02268): Uses LLMs to generate prior knowledge for cold-start bandit problems.

### Recommendation for Orchestra

Implement `ThompsonModelSelector` as a pluggable strategy within `CostAwareRouter`. Use binary rewards initially (task_completed), graduate to continuous rewards via `SelfCheckScorer`. Store bandit state (alpha/beta per model) in the persistence layer so learning survives restarts. The numpy-only implementation is sufficient; add `contextualbandits` for contextual features (prompt length, tool count, domain).

---

## 3. Model Distillation for Router Training

### Two Distinct Use Cases

**Use Case A — Router Distillation (primary for Orchestra):** Collect (prompt, model, quality_score) tuples from production. Train a small sklearn classifier (GradientBoosting or logistic regression over sentence-transformer embeddings) to predict which model performs best per prompt. This is what RouteLLM does with its BERT and MF routers.

**Use Case B — Model Distillation (secondary, for power users):** Use a large teacher model to generate training data. Fine-tune a smaller student model on that data. Deploy the student for cheaper inference. Tools:

| Platform | Availability | Details |
|----------|-------------|---------|
| **OpenAI Stored Completions** | GA, free | Set `store: true` in Chat Completions API. Captures input-output pairs. Integrated with Evals and fine-tuning. Fine-tune GPT-4o-mini from GPT-4o teacher data. |
| **Anthropic/Bedrock** | GA in us-west-2 | Claude 3 Haiku fine-tuning via Amazon Bedrock only (not Anthropic API directly). Teacher: Sonnet, Student: Haiku. Reported 81.5% to 99.6% accuracy, 85% token reduction. |
| **Distilling Step-by-Step** (Google) | OSS | Train smaller models with rationale-augmented examples. Outperforms larger models with less data. |
| **EasyDistill** (Alibaba, 2025) | OSS | Toolkit for compressing large NLP models. |

Compression ordering research (2025) found that **Pruning -> Distillation -> Quantization (P-KD-Q)** yields the best balance.

### Collection Pipeline for Orchestra

1. `EventBus` emits `LLMCalled` events (already exists in `CostAggregator`)
2. New `RoutingDataCollector` subscriber captures prompt + model + outcome
3. Embed prompts using `sentence-transformers` (offline batch)
4. Store samples in SQLite or Parquet
5. Periodically retrain the router classifier (CLI command or scheduled job)
6. Deploy as `TrainedRouterClassifier` loaded from a pickle/ONNX file

### Key Libraries
- `sentence-transformers>=3.0` (all-MiniLM-L6-v2 for embeddings)
- `scikit-learn>=1.5` (GradientBoostingClassifier or LogisticRegression)
- `surprise` or `implicit` (if using MF approach from RouteLLM)

---

## 4. SLA-Driven Routing

### Key Metrics

| Metric | Definition | Typical SLO |
|--------|-----------|-------------|
| **TTFT** | Time from request to first token | < 200ms (chat), < 1s (batch) |
| **TPOT** | Inter-token latency during streaming | < 15ms |
| **E2E Latency** | Total request-to-complete time | < 2s (chat), < 30s (analysis) |

Leading systems in 2025-2026 achieve sub-0.5s TTFT and exceed 1,000 TPS. Gemini 2.5 Flash provides sub-200ms TTFT; Claude 3 Opus can be 500-2000ms.

### Measuring TTFT in Orchestra

Orchestra's `LLMProvider.stream()` returns `AsyncIterator[StreamChunk]`. TTFT = time from `stream()` call to first yielded chunk. This should be recorded as:
- OTel span attribute: `gen_ai.ttft_ms`
- OTel Histogram metric: `orchestra.llm.ttft_ms` with `{provider, model}` labels
- Sliding window statistics maintained per provider/model

### SLA Router Algorithm

The `SLARouter` wraps `CostAwareRouter`. Given a `LatencySLA` (max_ttft_ms, max_e2e_ms, priority), it filters candidate models to only those whose p95 TTFT is within budget, then delegates to the cost router for final selection among compliant candidates.

### Fallback Chain Pattern

Define ordered `FallbackChain` steps with per-step timeouts. If step 1 (e.g., Claude Sonnet, 2000ms timeout) fails or times out, try step 2 (GPT-4o, 3000ms), then step 3 (Haiku, 1000ms as fast fallback). SLO-driven scheduling research (SOLA, Tsinghua 2025) formalizes joint TTFT-TBT-throughput optimization.

### Recommendation

Add `LatencySLA` as an optional parameter to `ExecutionContext`. Store latency statistics in a sliding-window buffer (last 100 calls per provider/model) updated via EventBus. The SLARouter filters, then delegates to CostAwareRouter.

---

## 5. Matrix Factorization for Performance Prediction

### Mathematical Foundation

Approximate the sparse (task x model) quality matrix R as R ~ P * Q^T, where P is (n_tasks x k) latent task features, Q is (n_models x k) latent model features, k is latent dimension (typically 8-64). Predicted quality for task i on model j = P[i,:] dot Q[j,:]. Train by minimizing squared error + L2 regularization via ALS or SGD.

### RouteLLM's MF Router (the reference implementation)

Trained on Chatbot Arena preference data. Prompts embedded with sentence-transformers, projected into shared latent space with model vectors. Results:
- 95% GPT-4 quality using only 26% GPT-4 calls (48% cheaper than random)
- With data augmentation: 95% quality with only 14% GPT-4 calls (75% cheaper)
- MF outperforms BERT and causal LLM classifiers on this task

### Python Libraries

| Library | Best For | Notes |
|---------|----------|-------|
| `surprise` (`pip install scikit-surprise`) | Explicit ratings. SVD, SVD++, PMF, NMF. | Clean API, good for prototyping. No implicit feedback support. |
| `implicit` (`pip install implicit`) | Implicit feedback. ALS, BPR, logistic MF. | GPU-accelerated, highly parallelizable. |
| `scipy.sparse.linalg.svds` | Full control. | Direct sparse SVD, no dependencies beyond scipy. |
| `lightfm` | Hybrid with content features. | When you have both task metadata and interaction data. |

### Integration with Cost-Aware Routing

MF predictions serve as a quality estimate in the routing decision: `routing_score(model) = predicted_quality(model) / cost(model)`. This allows the router to pick the model with the best quality-per-dollar ratio for each specific task rather than relying on static tier assignments.

### Recommendation

Use `scipy.sparse` SVD for the core implementation (minimal dependencies). Require at least 100 observations per model before trusting MF predictions; fall back to heuristic routing when data is sparse. Implement as `ModelPerformancePredictor` that plugs into `CostAwareRouter`.

---

## 6. Full Chargeback Billing System

### Tenant Cost Attribution Through Nested Calls

Orchestra's `CostAggregator` tracks by run_id, model, agent_name. For billing, add `tenant_id` propagation using **OTel Baggage** with a `BaggageSpanProcessor`: set `tenant_id` at the API entry point, and it automatically propagates through all child spans including nested agent calls. Alternative: extend `ExecutionContext` with a `BillingContext` dataclass.

### Database Schema

Three tables: `billing_records` (per-LLM-call records with tenant_id, model, tokens, cost_usd, markup_pct, billed_usd, billing_period), `billing_invoices` (monthly summaries per tenant with line items and Stripe reference), and `tenants` (markup_pct, stripe_customer_id, monthly budget).

### Stripe Integration (2025-2026)

Stripe now offers **native LLM token billing** (preview/waitlist as of March 2026):
- **Meters API**: Create a meter for "llm_token_usage", record per-customer meter events after each LLM call. Stripe handles invoicing, markup, and payment.
- **AI Gateway** (preview): Route LLM calls through Stripe's gateway for automatic token metering. Supports Vercel, OpenRouter, custom gateways.
- **AI Profit Center** feature: Configure markup percentage, Stripe tracks provider costs and applies margin automatically.
- Rate limit: 1,000 meter event calls/second in live mode.
- Python SDK: `stripe.billing.MeterEvent.create(event_name="llm_token_usage", payload={"value": str(tokens), "stripe_customer_id": customer_id})`

Other platforms: **TrueFoundry** (unified AI gateway for multi-model spend management), **Kinde** (billing for AI/LLM APIs with dynamic cost management).

### Recommendation

Implement internal billing with SQLite storage first (aligns with Orchestra's existing patterns). Use OTel Baggage for tenant_id propagation. Add Stripe integration as an optional plugin. Provide a CLI command for generating billing reports per tenant per period.

---

## 7. Per-Tenant Persistent Budget Tracking

### Design: Database-Backed Double-Entry Ledger

Borrow from accounting: every budget change creates a debit (cost incurred) and credit (budget allocated). The balance is always the sum of entries. This provides a complete audit trail.

Tables: `budget_ledger` (tenant_id, entry_type credit/debit, amount_usd, description, run_id, balance_after) and `budget_limits` (tenant_id, soft_limit_usd, hard_limit_usd, period monthly/weekly/daily).

### Budget Enforcement Strategies

**Option A — Pessimistic locking (strong consistency):** Row-level lock on latest ledger entry via `SELECT ... FOR UPDATE`. Exact enforcement, no overspend. Cons: serialization bottleneck, higher latency. Best for hard limits.

**Option B — Optimistic caching (eventual consistency, recommended):** Check against a cached balance with TTL (e.g., 1 second). Optimistically deduct from cache. Reconcile periodically with database. Possible small overspend during cache window; mitigate by setting hard limit at 95% of actual budget.

**Option C — Redis-backed distributed budget (LiteLLM pattern):** LiteLLM syncs in-memory cache with Redis every 0.01s. Hierarchical: Org > Team > User > Key > End User. Budget periods: 1d, 7d, 30d, monthly.

### Python Tools

- **Django Ledger** (`pip install django-ledger`): Full double-entry accounting with multi-tenant support, multi-entity management, real-time reporting. Open-source, Django-based.
- **aiosqlite** / **asyncpg**: Async database drivers for the ledger backend.
- **Redis** + **aioredis**: For cross-instance budget sync in distributed deployments.

### Integration with Orchestra

Extend `BudgetPolicy` to `PersistentBudgetPolicy` that reads/writes a ledger database. Override `check()` to query persistent balance. Add `record_spend()` method called by `CostAggregator` after each LLM call. Share the database with the billing system (Topic 6).

---

## 8. Provider Failover with Strategy Switching

### Circuit Breaker Pattern

Three states: CLOSED (normal) -> OPEN (fail-fast after threshold failures) -> HALF-OPEN (test with limited traffic). Real-world reference: Salesforce Agentforce opens the circuit when 40%+ of traffic fails within 60 seconds and routes all traffic to the equivalent model on another provider.

### Python Circuit Breaker Libraries

| Library | Async Support | Install |
|---------|:------------:|---------|
| **aiobreaker** | Native asyncio | `pip install aiobreaker` — recommended for Orchestra |
| **pybreaker** | Sync only | `pip install pybreaker` — most popular, Redis backing |
| **circuitbreaker** | Decorator | `pip install circuitbreaker` — lightweight |
| **purgatory** | Native asyncio | `pip install purgatory` — built for asyncio |

`aiobreaker` is the best fit: native asyncio support (Orchestra is async), configurable `fail_max` (default 5) and `reset_timeout`, optional Redis backing for shared state.

### Detecting Provider Degradation

Three composable detectors:
1. **Error Rate**: Sliding window (last 100 calls), trigger at >= 40% failure rate
2. **Latency Spikes**: Track p95 latency in sliding window, trigger when p95 exceeds threshold (e.g., 5000ms)
3. **Rate Limit**: Count consecutive HTTP 429 responses, trigger at >= 3 consecutive

### Strategy Switching: Native vs Prompted Tool Calling

When failing over from a provider with native function calling (Anthropic, OpenAI, Google) to one without (some Ollama models, open-source endpoints), the tool calling strategy must change:

**Native strategy:** Tools passed as structured schemas in API request, provider returns structured `tool_use` blocks. High reliability, no prompt engineering.

**Prompted + Validation fallback:** Tools described in system prompt as text, LLM outputs JSON, response parsed and validated against schemas, retry loop on validation failures (up to 3 attempts with error feedback). Research (2025) identifies three reliability techniques: better prompting, constrained decoding, and validation with re-prompting. A dual-layer verification system (rule + model verification) reduces deployment overhead.

The `StrategySwitch` component detects whether the target provider supports native function calling and transparently switches strategy. The `ProviderFailover` wraps multiple providers with circuit breakers and iterates through a fallback chain, delegating to `StrategySwitch` for each.

### Recommendation

Use `aiobreaker` for async circuit breaking. Build degradation detectors as composable components attached to the EventBus. Implement fallback chains configurable via YAML alongside provider credentials. The strategy switch is transparent to agents — they always pass tools as schemas; the failover layer handles translation.

---

## Integration Map

```
Agent.run()
  |
  v
ExecutionContext (+ tenant_id, LatencySLA, BudgetPolicy)
  |
  v
CostAwareRouter [Topic 1]
  |-- HeuristicRules (Tier 1)
  |-- ThompsonSampler [Topic 2]
  |-- MFPredictor [Topic 5]
  |-- TrainedClassifier [Topic 3]
  |
  v
SLARouter [Topic 4] — filters by TTFT compliance
  |
  v
ProviderFailover [Topic 8]
  |-- CircuitBreaker (aiobreaker)
  |-- StrategySwitch (native vs prompted tools)
  |-- FallbackChain
  |
  v
LLMProvider.complete()
  |
  v
EventBus emissions
  |-- CostAggregator (existing)
  |-- BillingAggregator [Topic 6] --> Stripe
  |-- PersistentBudgetPolicy [Topic 7] --> SQLite/Redis ledger
  |-- RoutingDataCollector [Topic 3] --> training data
```

## Recommended Implementation Order

**Wave 1 (Foundation):** Cost-Aware Routing (heuristic tier), Persistent Budget Tracking, Provider Failover with circuit breakers. These are independent and everything else depends on them.

**Wave 2 (Intelligence):** Thompson Sampling, SLA-Driven Routing, Matrix Factorization. These plug into the CostAwareRouter from Wave 1.

**Wave 3 (Enterprise):** Chargeback Billing (needs persistent budget + cost tracking), Model Distillation (needs accumulated production routing data).

## New Dependencies

Core (required): `numpy>=1.26`, `scipy>=1.12`, `aiobreaker>=1.2`

Optional extras:
- `routing-ml`: `sentence-transformers>=3.0`, `scikit-learn>=1.5`, `contextualbandits>=0.3`
- `billing`: `stripe>=10.0`, `aiosqlite>=0.20`
