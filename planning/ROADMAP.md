# Orchestra -- Project Roadmap

**Project:** Orchestra - Python-first Multi-Agent Orchestration Framework
**Created:** 2026-03-05
**Updated:** 2026-03-09
**Timeline:** 26 weeks (4 phases)
**Status:** In Progress (Phase 3)

---

## Phases

- [x] **Phase 1: Core Engine (Weeks 1-6)** - Graph engine, agent protocol, typed state, LLM adapters, testing harness, CLI, and example workflows.
- [x] **Phase 2: Differentiation (Weeks 7-12)** - Event-sourced persistence, HITL, time-travel debugging, handoff protocol, MCP integration, and rich tracing.
- [ ] **Phase 3: Production Readiness (Weeks 13-18)** - FastAPI server, OpenTelemetry, Redis cache, multi-tier memory, advanced test harnesses, guardrails, and cost tracking.
- [ ] **Phase 4: Enterprise & Scale (Weeks 19-26)** - Cost router, agent IAM, Ray executor, NATS messaging, dynamic subgraphs, TypeScript SDK, and Kubernetes deployment.

---

## Strategy: Parallel Wave Execution

Per **RECONCILIATION.md**, Phase 2 was executed in **parallel waves** rather than strictly sequential tasks to maximize development velocity across independent subsystems.

- **Wave 1 (Foundation):** Events, MCP, and Providers (Plans 01, 02, 03) - **DONE**
- **Wave 2 (Infrastructure):** SQLite, Trace Renderer, and Handoff (Plans 04a, 04b) - **DONE**
- **Wave 3 (Control Flow):** HITL and Tool ACLs (Plan 06) - **DONE**
- **Wave 4 (Debugging):** Time-Travel Debugging (Plan 07) - **DONE**
- **Wave 5 (Validation):** Advanced Examples (Plan 08) - **DONE**

---

## Phase 1: Core Engine (COMPLETED)

**Goal:** A developer can define agents, compose them into typed graph workflows, run them against real LLMs, and write deterministic unit tests -- all from a single `pip install orchestra-agents`.

| Task | Description | Status | Evidence |
|:---|:---|:---:|:---|
| 1.1 | Project Scaffolding | [x] | `pyproject.toml`, GitHub Actions CI |
| 1.2 | Agent Protocol & Base Classes | [x] | `core/agent.py`, `core/context.py` |
| 1.3 | Graph Engine (Workflow/Compiled) | [x] | `core/graph.py`, `core/compiled.py` |
| 1.4 | Reducer-Based Typed State | [x] | `core/state.py` (9 built-in reducers) |
| 1.5 | LLM Provider Protocol & Adapters | [x] | `providers/` (Anthropic, OpenAI-compat) |
| 1.6 | Function-Calling Tool Integration | [x] | `tools/base.py`, `@tool` decorator |
| 1.7 | ScriptedLLM Test Harness | [x] | `testing/scripted.py` |
| 1.8 | Basic CLI with Typer | [x] | `cli/main.py` |
| 1.9 | Console Logging (structlog) | [x] | `observability/logging.py` |
| 1.10| Example Workflows | [x] | `examples/` (sequential, parallel, conditional) |
| 1.11| Documentation (Scaffolding) | [x] | `docs/` (mkdocs set up) |

---

## Phase 2: Differentiation (COMPLETED)

**Goal:** Build features that distinguish Orchestra from LangGraph: event-sourced persistence, rich console tracing, MCP integration, and first-class handoff.

### Wave 1: Foundation (COMPLETED)

| Task | Plan | Description | Status | Evidence |
|:---|:---|:---|:---:|:---|
| 2.1 | Plan 01 | **Event-Sourced Infrastructure**: Immutable event hierarchy, EventBus, state projection. | [x] | `storage/events.py`, `storage/store.py` |
| 2.8 | Plan 02 | **MCP Client Integration**: stdio and HTTP transports for MCP 2025-11-25 spec. | [x] | `tools/mcp.py` |
| 2.10| Plan 03 | **Advanced Providers**: Google Gemini and Ollama native adapters. | [x] | `providers/google.py`, `ollama.py` |

### Wave 2: Infrastructure (COMPLETED)

| Task | Plan | Description | Status | Evidence |
|:---|:---|:---|:---:|:---|
| 2.2 | Plan 04a| **SQLite Event Store**: Durable persistence with WAL mode and snapshots. | [x] | `storage/sqlite.py` |
| 2.6 | Plan 04b| **Rich Console Trace Renderer**: Live terminal tree visualization of runs. | [x] | `observability/console.py` |
| 2.7 | Plan 04b| **Handoff Protocol**: Swarm-style handoff with context distillation. | [x] | `core/handoff.py`, `context_distill.py` |
| 2.3 | Plan 05 | **PostgreSQL Backend**: asyncpg-based event store. | [x] | `storage/postgres.py` |

### Wave 3: Control Flow (COMPLETED)

| Task | Plan | Description | Status | Evidence |
|:---|:---|:---|:---:|:---|
| 2.4 | Plan 06 | **HITL (Interrupt/Resume)**: Pause nodes for human approval/edit. | [x] | `CompiledGraph.resume()`, `Checkpoint` model |
| 2.9 | Plan 06 | **Tool Registry ACLs**: Scoped tool access for production environments. | [x] | `security/acl.py`, `BaseAgent.acl` |

### Wave 4 & 5: Debugging & Validation (COMPLETED)

| Task | Plan | Description | Status | Evidence |
|:---|:---|:---|:---:|:---|
| 2.5 | Plan 07 | **Time-Travel Debugging**: Fork/replay from historical checkpoints. | [x] | `timetravel.py`, `CompiledGraph.fork()` |
| 2.11| Plan 08 | **Advanced Examples**: HITL approval, complex handoffs. | [x] | `examples/`, `test_advanced_examples.py` |

---

## Progress Summary

| Phase | Tasks | Status | Completion % |
|-------|-------|--------|:---:|
| 1. Core Engine | 11/11 | **COMPLETED** | 100% |
| 2. Differentiation | 11/11 | **COMPLETED** | 100% |
| 3. Production Readiness | 0/10 | Not started | 0% |
| 4. Enterprise & Scale | 0/9 | Not started | 0% |

**Overall Project Completion:** ~52%

---

## Risk Summary (Active Phase)

| Risk | Status | Mitigation |
|:---|:---:|:---|
| Event Sourcing Complexity | Low | 18+ unit tests for projection/serialization in `test_events.py` |
| MCP Spec Stability | Medium | Tracking MCP 2025-11-25; using official `mcp` SDK |
| Production Load (Postgres) | Medium | **NEXT:** Phase 3 must stress test the PostgresEventStore with concurrent workloads |

---
*Last Verified: 2026-03-09*
*Verifier: Gemini CLI (orchestrator)*
