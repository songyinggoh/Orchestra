# Competitive Research: Agent Orchestration Frameworks

**Research Date:** 2026-03-07
**Phase:** 2 - Differentiation
**Confidence:** HIGH

---

## Framework Comparison Matrix

| Feature | LangGraph | CrewAI | AutoGen/MS Agent Framework | Temporal | **Orchestra (Phase 2)** |
|---------|-----------|--------|---------------------------|----------|------------------------|
| Persistence model | Snapshot (full state dict) | Platform-dependent (AMP) | Snapshot (FileCheckpointStorage) | Event sourcing | **Event sourcing** |
| Auto-persist | No (explicit SqliteSaver) | No | No | Yes (server) | **Yes (.orchestra/runs.db)** |
| SQLite support | Yes (opt-in) | No | Yes (opt-in) | No | **Yes (zero-config default)** |
| HITL interrupt/resume | Yes (API only) | Yes (Flows, rough DX) | Yes (API only) | Yes (signals) | **Yes (API + Rich terminal UI)** |
| Built-in terminal trace | No | No | No | No (web UI) | **Yes (Rich Live tree)** |
| Observability | LangSmith (cloud) | AMP (paid) | OTEL (infra required) | Web UI (server) | **Zero-config terminal** |
| Time-travel debugging | Yes (API: get_state_history) | No | No | Yes (Replay Debugger) | **Yes (CLI interactive)** |
| Agent handoff | State mutation + routing | LLM-decided / A2A | Handoff message type | N/A | **Typed HandoffEvent** |
| Tool ACLs | No | No | No | N/A | **Yes (per-agent)** |
| MCP support | Yes (shipped) | Via A2A | No | N/A | **Yes (stdio + Streamable HTTP)** |
| Local-first | Yes | No (AMP for prod) | Yes | No (requires server) | **Yes** |

---

## LangGraph (LangChain)

### Persistence
- **Snapshot-based checkpointing** — saves full state dict at each "superstep" (node execution boundary)
- Not event-sourced — no record of *what happened*, only *what state resulted*
- SQLite support exists via `SqliteSaver` but is NOT automatic — developer must explicitly pass it to `compile()`
- PostgreSQL via `PostgresSaver`
- Checkpoints are keyed by `(thread_id, checkpoint_id)` with parent pointers for history

### HITL
- `interrupt_before` and `interrupt_after` parameters on nodes — same pattern Orchestra plans
- Resume via `Command(resume=value)` — developer constructs a Command object
- **No built-in terminal UI** — community workaround is building a custom FastAPI layer
- This is a documented pain point: multiple blog posts and GitHub issues about the difficulty of building HITL UX on top of LangGraph's raw API

### Time-Travel
- `get_state_history()` returns checkpoint iterator
- `update_state()` can modify historical state and fork
- **API-only** — no interactive CLI or terminal UI
- State diffs must be computed by the developer

### Observability
- Requires **LangSmith** (cloud product, paid) for production tracing
- Self-hosted alternative requires OTEL infrastructure setup
- No built-in terminal trace rendering

### Handoff
- Handoffs are state mutations + conditional routing (not explicit events)
- No `HandoffEvent` type — the event log (if checkpointing) just shows state changes
- Context preserved via state dict, but the *reason* for handoff is not recorded

### Pain Points (from community)
- DX for HITL requires significant boilerplate (FastAPI wrapper pattern)
- Checkpointing is opt-in and easy to forget
- Debugging requires LangSmith subscription or complex OTEL setup
- Time-travel is powerful but not discoverable (no CLI tooling)

---

## CrewAI

### Persistence
- Platform-dependent — **CrewAI AMP** (Agent Management Platform) handles persistence
- Not local-first — requires AMP infrastructure for production persistence
- No SQLite backend for local development

### HITL
- Human-in-the-loop for Flows launched January 2026
- Community GitHub issues show rough DX and limited documentation
- No built-in terminal UI for state inspection

### Observability
- Requires AMP (paid platform) or third-party integrations
- No built-in terminal trace
- Telemetry focused on agent performance metrics, not execution traces

### Handoff / Delegation
- **Richest delegation story** — supports A2A (Agent-to-Agent) protocol
- Delegation can be LLM-driven (non-deterministic) by default
- A2A protocol enables cross-framework agent communication
- Risk: if A2A standardizes, Orchestra may need compatibility

### Pain Points
- AMP dependency for production features
- HITL documentation gaps
- Non-deterministic delegation makes testing harder

---

## AutoGen / Microsoft Agent Framework

### Persistence
- Evolved into **Microsoft Agent Framework** (October 2025 preview)
- Snapshot-based via `FileCheckpointStorage`
- No event sourcing

### HITL
- Supported at API level (`UserProxyAgent` pattern)
- No terminal UI for interactive state review
- Designed for programmatic integration, not developer debugging

### Observability
- OpenTelemetry integration built in
- BUT requires OTEL collector infrastructure (Jaeger, Grafana, etc.)
- No zero-config local option

### Positioning
- Enterprise-focused (Microsoft ecosystem)
- More complex setup than LangGraph or CrewAI
- Strong multi-agent conversation patterns

---

## Temporal.io

### Persistence
- **Gold standard for event sourcing** — immutable, append-only event log is the source of truth
- Events record every workflow state transition with full detail
- Architectural reference for Orchestra's persistence model

### Time-Travel
- **Workflow Replay Debugger** — IDE-level step-through of production execution history
- Can replay any workflow from its event history
- The benchmark for what time-travel debugging should feel like

### Limitations for Orchestra's Use Case
- Requires a **Temporal server cluster** — not local-first
- Not an agent framework — no LLM integration, tool calling, etc.
- Patterns are transferable but implementation is not reusable

---

## Orchestra's Six Genuine Differentiators

### 1. Event Sourcing as the Persistence Model
No other Python agent framework uses event sourcing. All competitors use snapshot-based checkpointing. Events record *what happened* (NodeStarted, ToolCalled, LLMCalled), not just *what state resulted*. This enables richer debugging, auditing, and replay.

### 2. Zero-Config Rich Terminal Trace
No competitor provides production-quality observability without a cloud service (LangSmith), paid platform (AMP), or self-hosted infrastructure (OTEL collectors). This is the biggest DX gap in the market. Orchestra shows a live-updating Rich tree in the terminal with zero setup.

### 3. Batteries-Included Local Persistence
Competitors require explicit configuration to enable persistence. Orchestra auto-persists every run to `.orchestra/runs.db` by default. Opt-out with `persist=False`, not opt-in.

### 4. HITL with Built-In Terminal Review UI
LangGraph HITL requires building a custom FastAPI layer to present state to humans — this is a documented community pain point with multiple blog posts about the workaround. Orchestra ships the review experience as a Rich panel in the terminal.

### 5. Typed, Auditable Handoff Events
LangGraph handoffs are state mutations + graph routing (not recorded as distinct events). CrewAI handoffs are LLM-decided or A2A network-level. Orchestra handoffs produce explicit `HandoffEvent` records with source agent, target agent, reason, and context — fully queryable in the event log.

### 6. Per-Agent Tool ACLs
No competitor enforces tool access control at the framework level. Orchestra's `ToolRegistry` with ACLs ensures agents can only invoke tools they're explicitly granted access to.

---

## Risks to Watch

1. **LangGraph time-travel exists** (API-only, state-diff focused) — Orchestra's CLI-driven version must be meaningfully better UX, not just a different interface
2. **MCP is now table stakes** — LangGraph already ships MCP support. The integration DX (not the feature itself) is what differentiates
3. **CrewAI's A2A protocol** — if cross-framework agent delegation standardizes around A2A, Orchestra will need to evaluate compatibility
4. **LangGraph's ecosystem momentum** — largest community, most tutorials, most integrations. Orchestra must be clearly better at specific things, not slightly better at everything

---

## Sources

- [LangGraph Persistence Docs](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph Checkpointing Architecture (DeepWiki)](https://deepwiki.com/langchain-ai/langgraph/4.1-checkpointing-architecture)
- [LangGraph HITL Interrupts Docs](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [LangGraph Time Travel Docs](https://langchain-ai.github.io/langgraph/concepts/time-travel/)
- [LangGraph Handoffs Docs](https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs)
- [LangSmith Observability](https://www.langchain.com/langsmith/observability)
- [Persistence in LangGraph -- Deep Practical Guide (Jan 2026)](https://pub.towardsai.net/persistence-in-langgraph-deep-practical-guide-36dc4c452c3b)
- [LangGraph HITL with FastAPI (Medium)](https://shaveen12.medium.com/langgraph-human-in-the-loop-hitl-deployment-with-fastapi-be4a9efcd8c0)
- [LangGraph DX Pain Points (Latenode Community)](https://community.latenode.com/t/current-limitations-of-langchain-and-langgraph-frameworks-in-2025/30994)
- [CrewAI Changelog](https://docs.crewai.com/en/changelog)
- [CrewAI A2A Delegation Docs](https://docs.crewai.com/en/learn/a2a-agent-delegation)
- [CrewAI Human-in-the-Loop Community Issue](https://github.com/crewAIInc/crewAI/issues/2051)
- [AutoGen to Microsoft Agent Framework Migration Guide](https://learn.microsoft.com/en-us/agent-framework/migration-guide/from-autogen/)
- [AutoGen HITL Docs](https://microsoft.github.io/autogen/stable//user-guide/agentchat-user-guide/tutorial/human-in-the-loop.html)
- [Temporal Event History Docs](https://docs.temporal.io/encyclopedia/event-history)
- [Temporal Time-Travel Debugging](https://temporal.io/blog/time-travel-debugging-production-code)
- [Temporal + AI Agents (DEV Community)](https://dev.to/akki907/temporal-workflow-orchestration-building-reliable-agentic-ai-systems-3bpm)
- [Temporal vs LangGraph Production Comparison](https://temporal.io/blog/prototype-to-prod-ready-agentic-ai-grid-dynamics)
- [Open Source AI Agent Frameworks Compared 2026](https://medium.com/@openagents/open-source-ai-agent-frameworks-compared-crewai-vs-langgraph-vs-autogen-vs-openagents-2026-36a036b4801d)
- [15 Best AI Agent Frameworks for Enterprise 2026](https://blog.premai.io/15-best-ai-agent-frameworks-for-enterprise-open-source-to-managed-2026/)

---

*Competitive research: 2026-03-07*
*Researcher: competitor-researcher agent*
