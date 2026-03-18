# Wave 2 Research Topics

**Purpose:** Topics to research before Wave 2 implementation begins.
**Format:** Each topic includes what to look for and why it matters.

---

## Track A: Cost Intelligence (T-4.4 + T-4.5)

### A1. Thompson Sampling for LLM Model Selection
- How Thompson Sampling with Beta priors works for multi-armed bandits
- Cold-start strategy: how many observations before posteriors converge (target: 30-100 per model)
- Contextual bandits vs. vanilla Thompson Sampling — is context (token count, tool count) worth the complexity?
- Look at: `contextualbandits` PyPI library maturity, API surface, latency overhead
- **Key question:** Can we implement Thompson Sampling with just `numpy` Beta sampling, or do we need a library?

### A2. LLM Router Heuristics (Tier 1 — No ML)
- How RouteLLM, Martian, Unify, and LiteLLM implement non-ML routing heuristics
- Token-count thresholds for model tiering (e.g., <500 tokens → small model, >2000 → large)
- Tool-use detection as a routing signal (tool-calling models vs. text-only)
- Complexity estimation without embeddings (keyword density, instruction count)
- **Key question:** What's the simplest heuristic that achieves 20%+ cost reduction on mixed workloads?

### A3. Provider Failover Patterns in Production
- How LiteLLM, Amazon Bedrock, and Azure OpenAI implement failover chains
- Circuit breaker + retry interaction: should retry happen inside or outside the breaker?
- Latency tracking (TTFT — Time to First Token) as a health signal
- Error classification: which provider errors are retryable vs. terminal?
  - Rate limit (retryable, with backoff)
  - Auth failure (terminal)
  - Context window exceeded (terminal, try smaller model)
  - Server error 5xx (retryable)
- **Key question:** Should failover be transparent to the agent (same model name, different provider) or explicit (agent sees model change)?

### A4. Double-Entry Ledger for LLM Cost Tracking
- Double-entry accounting basics: debits, credits, journal entries, trial balance
- How Lago, Metronome, and Orb implement usage-based billing ledgers
- Schema design for a minimal ledger in SQLite (tables, indexes, constraints)
- Idempotent writes: using `event_id` or `idempotency_key` to prevent double-charge
- **Key question:** Is a full double-entry model necessary, or is a simpler "balance + transaction log" sufficient for Orchestra?

### A5. Multi-Tenant Budget Hierarchy
- How AWS Organizations, GCP billing accounts, and Stripe Connect handle nested budgets
- Credit conservation: if parent has $100 and 3 children each have $40, is that $120 or $100?
- Budget alerts and notifications: when to warn vs. block
- LiteLLM's budget implementation: `litellm.BudgetManager` API and storage model
- **Key question:** For Phase 4, do we need full hierarchy (org > team > user) or just flat tenant isolation?

### A6. NativeStrategy vs PromptedStrategy Pattern
- What "Native Schema Enforcement" means for providers that support tool calling natively (Anthropic, OpenAI)
- What "Prompted + Validation" means for providers that don't (Ollama local models, custom HTTP)
- How LangChain and LiteLLM handle transparent strategy switching
- Error recovery when a non-native provider returns malformed tool calls
- **Key question:** Should strategy selection be automatic (probe provider capabilities) or configured per-provider?

---

## Track B: Agent Identity & Authorization (T-4.6 + T-4.7)

### B1. DID Methods: did:peer vs did:web
- `did:peer` numalgo 0 vs numalgo 2: when to use which
- `did:web` resolution: DNS/HTTPS lookup, `.well-known/did.json` hosting, caching
- How `peerdid` 0.5.2 creates and resolves did:peer:2 documents (API walkthrough)
- DID Document structure: `verificationMethod`, `keyAgreement`, `authentication` sections
- **Key question:** Should Orchestra agents default to `did:peer:2` (self-contained, no network) and reserve `did:web` for organizational/external agents only?

### B2. Ed25519 Signing with joserfc
- `joserfc.jws.serialize_compact()` API for Ed25519 (EdDSA) signatures
- Importing Ed25519 keys as `OKPKey` with `crv: "Ed25519"` (vs. X25519 for encryption)
- Verifying JWS signatures: `joserfc.jws.deserialize_compact()` with algorithm allowlist
- Key generation: `cryptography.hazmat.primitives.asymmetric.ed25519.Ed25519PrivateKey.generate()`
- **Key question:** Does `peerdid` embed both X25519 (encryption) AND Ed25519 (signing) keys in did:peer:2, or only one?

### B3. Agent Card Design (A2A / Google ADK Pattern)
- Google's A2A Agent Card specification: required fields, optional fields, extensions
- How `a2a-sdk` 0.3.24 structures AgentCard in Python
- Signed Agent Cards: wrapping card JSON in a JWS envelope
- Discovery protocols: push (gossip/broadcast) vs pull (registry query) vs hybrid
- **Key question:** Should Orchestra's AgentCard be A2A-compatible from the start, or use a simpler internal format and add A2A compatibility in Wave 4 (T-4.11)?

### B4. Gossip Poisoning Defenses
- What gossip poisoning is: attacker injects fake/modified agent cards into discovery
- Signature verification as primary defense: reject cards with invalid signatures
- DID resolution as secondary defense: verify the signing key belongs to the claimed DID
- Agent impersonation vs. identity rotation: how to distinguish legitimate key rotation from attack
- Rate limiting on card publication: prevent flooding the registry
- **Key question:** Is signature verification + DID resolution sufficient, or do we need additional defenses (reputation scores, attestation chains)?

### B5. UCAN Specification and py-ucan Library
- UCAN 0.10 specification: header, payload, signature, delegation proofs (`prf` field)
- `py-ucan` 1.0.0 API: `UcanBuilder`, `Capability`, `ResourcePointer`, `Ability`
- How delegation chains work: parent UCAN referenced in child's `prf` array
- Attenuation: how child capabilities must be a subset of parent capabilities
- TTL enforcement: `exp` claim in JWT, clock skew tolerance
- **Key question:** Does `py-ucan` 1.0.0 support custom resource types (like `orchestra:tools/web_search`), or is the resource format fixed?

### B6. UCAN Refresh Mechanism for Long-Running Workflows
- How to handle UCAN expiry during a 30-minute orchestration workflow
- Refresh patterns: parent re-issues UCAN on request, or agent pre-fetches before expiry
- "Heartbeat refresh" vs "on-demand refresh" tradeoffs
- What happens if the parent agent is unavailable when refresh is needed
- **Key question:** Should refresh be pull-based (sub-agent requests) or push-based (parent proactively extends)?

### B7. SecretProvider Abstraction Patterns
- HashiCorp Vault KV v2 API: `read_secret_version()`, `create_or_update_secret()`
- `hvac` 2.4.0 async support: does it have native async, or do we need `asyncio.to_thread()`?
- Alternative secret backends: AWS Secrets Manager, GCP Secret Manager, Azure Key Vault
- Secret rotation patterns: versioned secrets, lease-based access
- Mapping agent DIDs to Vault paths: `secret/data/agents/{agent_did_hash}/signing_key`
- **Key question:** For Phase 4, should we implement Vault + InMemory only, or also add file-based for local development?

### B8. OTel Baggage for Identity Propagation
- W3C Baggage specification: header format, size limits (8192 bytes)
- OpenTelemetry Python `baggage` API: `set_baggage()`, `get_baggage()`, `get_all()`
- Serializing a delegation chain into Baggage: `orchestra.delegation=did:A,did:B,did:C`
- Baggage propagation across NATS messages (not HTTP — how to carry Baggage in NATS headers)
- Security: Baggage is **not signed** — can it be tampered with? Mitigation strategies.
- **Key question:** Is OTel Baggage the right transport, or should we embed delegation context in the UCAN token itself (which IS signed)?

---

## Cross-Cutting Topics

### C1. ExecutionContext Extensions
- Current `ExecutionContext` fields: `run_id`, `state`, `provider`, `tool_registry`, `config`, `event_bus`
- New fields needed: `identity: AgentIdentity`, `ucan: str`, `tenant_id: str`, `delegation_context: DelegationContext`
- Backward compatibility: all new fields must be `Optional` with `None` defaults
- **Key question:** Should we create sub-contexts (e.g., `SecurityContext`) to avoid bloating `ExecutionContext`, or keep it flat?

### C2. New Error Types
- Current error hierarchy: `OrchestraError` → `BudgetExceededError`, `RateLimitError`, `ProviderUnavailableError`, etc.
- New errors needed:
  - `ModelSelectionError` (no model fits constraints)
  - `AllProvidersUnavailableError` (failover chain exhausted)
  - `InvalidSignatureError` (Agent Card signature verification failed)
  - `UCANVerificationError` (expired, invalid audience, bad signature)
  - `DelegationDepthExceededError` (max delegation depth reached)
  - `CapabilityDeniedError` (UCAN doesn't grant required capability)
- **Key question:** Should these be flat under `OrchestraError`, or organized into sub-hierarchies (`RoutingError`, `IdentityError`, `AuthorizationError`)?

### C3. Library Validation Spikes
- Before committing to a library, write a 20-line spike script to validate:
  - `py-ucan 1.0.0`: Create a UCAN, add custom resource, verify, check expiry
  - `peerdid 0.5.2` + Ed25519: Create did:peer:2 with Ed25519 signing key, extract it, sign a payload
  - `hvac 2.4.0`: Connect to Vault dev server, store/retrieve a secret
  - `numpy` Thompson Sampling: Sample from `Beta(a, b)`, update posteriors, verify convergence
- **Key question:** Do any of these spikes reveal blocking issues?

---

## Research Priority Order

| Priority | Topic | Blocks | Effort |
|----------|-------|--------|--------|
| 1 | B5 (UCAN spec + py-ucan) | T-4.7 implementation | High — most unknowns |
| 2 | B2 (Ed25519 + joserfc signing) | T-4.6 Agent Cards | Medium — verify API |
| 3 | A1 (Thompson Sampling) | T-4.4 router core | Medium — algorithm choice |
| 4 | A4 (Double-entry ledger) | T-4.5 schema design | Medium — over/under-engineering risk |
| 5 | B1 (DID methods) | T-4.6 identity model | Low — mostly confirmed |
| 6 | A3 (Failover patterns) | T-4.4 failover | Low — patterns well-known |
| 7 | B3 (Agent Card design) | T-4.6 discovery | Low — format decision |
| 8 | B8 (OTel Baggage) | T-4.6 propagation | Low — may pivot to UCAN-embedded |
| 9 | C3 (Library spikes) | All tasks | Low — quick validation |
| 10 | A2 (Router heuristics) | T-4.4 Tier 1 | Low — straightforward |
| 11 | A5 (Tenant hierarchy) | T-4.5 hierarchy | Low — flat is fine for Phase 4 |
| 12 | A6 (Strategy pattern) | T-4.4 strategy | Low — configure per-provider |
| 13 | B4 (Gossip poisoning) | T-4.6 security | Low — sig verify is sufficient |
| 14 | B6 (UCAN refresh) | T-4.7 long workflows | Low — pull-based default |
| 15 | B7 (SecretProvider) | T-4.6 key storage | Low — Vault + InMemory |
| 16 | C1 (ExecutionContext) | All tasks | Low — keep flat |
| 17 | C2 (Error types) | All tasks | Low — sub-hierarchies |
