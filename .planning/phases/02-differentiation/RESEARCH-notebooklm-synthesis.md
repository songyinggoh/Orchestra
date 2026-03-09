# Phase 2 Research Synthesis: NotebookLM Sources (48 Articles)

**Gathered:** 2026-03-08
**Status:** Research complete

---

## 1. Event Sourcing (10 articles)

### Consensus Patterns
- **Append-only event log** as single source of truth (universal agreement)
- **Aggregate as consistency boundary** with version-based optimistic concurrency
- **CQRS is essential** -- separate read models (projections) required since event stores aren't query-optimized
- **Snapshots for performance** -- periodic state captures reduce replay cost for long-lived aggregates
- **Event store serves dual purpose** -- both persistence (database) and notification (message broker)

### ESAA Pattern (Most Directly Relevant)
From arXiv:2602.23193 -- "Event Sourcing for Autonomous Agents":
- Agents emit **structured intentions** (validated JSON); a deterministic orchestrator validates, persists, and projects
- Clean separation of probabilistic (LLM) from deterministic (orchestrator)
- **Boundary contracts** with JSON Schema at agent/system interface
- Append-only `activity.jsonl` with sequential `event_seq` ordering
- Hash-based replay verification for cryptographic integrity
- Case study: 50 tasks, 86 events, 4 concurrent agents across 8 phases with heterogeneous LLMs

### Python Implementation Patterns
- **Frozen dataclasses** (`@dataclass(frozen=True)`) for event immutability
- **Pydantic** for event validation and serialization
- **SQLAlchemy Core** (not ORM) for optimistic locking row-count checks
- **PostgreSQL NOTIFY/LISTEN** for lightweight event notification
- **Environment-variable persistence config** -- swap backends for testing (in-memory) vs production (PostgreSQL)
- **eventsourcing library** (PyPI) provides mature Application/Aggregate/DomainEvent classes

### Event Store Schema Recommendation
```
events: id, aggregate_id (UUID), aggregate_type, event_type, event_data (JSONB),
        version (int), timestamp, hash, predecessor_hash
aggregates: id (UUID), type, version, snapshot_version, snapshot_data
```

### Agent Domain Events
- `AgentCreated`, `TaskAssigned`, `StepStarted`, `ToolInvoked`, `ToolResultReceived`
- `StepCompleted`, `AgentCompleted`, `AgentFailed`, `AgentSnapshotted`
- `ExecutionStarted`, `NodeEntered`, `NodeCompleted`, `EdgeTraversed`, `ExecutionCompleted`

### Snapshots
- EventSourcingDB treats **snapshots as regular events** (no special storage/API)
- `fromLatestEvent` reads from most recent snapshot-type event
- Create snapshots **asynchronously** to avoid impacting write latency
- Keep snapshot data flat and simple for fast deserialization

### Safety: Replay-Safe External Calls
- **Gateway pattern**: wrap tool/API calls so they don't execute during event replay
- Track replay mode flag; suppress side effects when replaying
- Critical for agents that invoke external tools

---

## 2. Model Context Protocol (12 articles)

### Transport Layer Architecture
| Transport | Use Case | Status |
|-----------|----------|--------|
| **stdio** | Local/testing, IDE plugins | Stable |
| **Streamable HTTP** | Primary production transport | Current standard |
| **SSE** | Legacy networked transport | Deprecated |

### JSON-RPC 2.0 Message Types
1. **Requests** -- `id` + `method` fields, expects response
2. **Responses** -- `id` + `result` fields, paired by matching `id`
3. **Notifications** -- no `id`, fire-and-forget
- **Progress tokens** for long-running operations (`progressToken`, `progress`, `total`)
- **Cancellation** via `requestId` + `reason`
- **Error responses** with JSON-RPC error codes

### Tool Discovery Protocol
- `tools/list` -- discover available tools (names, descriptions, JSON Schema inputs)
- `tools/call` -- invoke a tool with arguments
- **Capability negotiation** during initialization -- client/server exchange supported features
- Tools are "model-controlled" -- exposed for AI model invocation with optional HITL approval

### Three Core Primitives
1. **Resources** -- read-only data exposure from databases
2. **Tools** -- executable functions with side effects
3. **Prompts** -- reusable templates for LLM-server communication

### Code Execution Pattern (Anthropic)
- When agents connect to thousands of tools, descriptions alone consume 150K+ tokens
- Solution: agents **write code to call tools** instead of individual tool calls
- Token reduction: 150K -> 2K tokens
- Trade-off: requires secure sandbox execution environment

### Unified Tool Integration (arXiv:2508.02979)
- **ToolRegistry** library: unifies native Python, MCP, OpenAPI, LangChain tools under single interface
- Auto-generates JSON Schema from type hints and docstrings
- Dual-mode sync/async with optimized concurrency
- 60-80% code reduction, up to 3.1x performance improvement

### Dynamic Tool Loading (Strands SDK)
- Auto-discovery from `./tools/` directory with hot-reload
- `load_tool()` for runtime loading from arbitrary paths
- Schema validation before registration
- Meta-tooling: agents can create and load tools at runtime

### MCP Gateways (Production)
- Sit between MCP clients and servers for routing, load balancing, observability
- Top gateways: Bifrost (11us overhead), Cloudflare, Vercel, LiteLLM, Kong AI
- SOC 2 Type II audited options available

### Security Model
- Per-tool ACLs with scoped tokens
- OAuth token management with revocation support
- Input validation on all tool call parameters
- Prompt injection defense through tool responses
- Human-in-the-loop approval gates for sensitive tools
- Full audit trail for compliance

### 54 Agentic Tool Patterns (Arcade.dev)
Categories: Tool, Interface, Discovery, Composition, Execution, Output, Context, Resilience, Security, Compositional. Key principles: Agent Experience (design for LLMs), Security Boundaries, Error-Guided Recovery, Tool Composition.

---

## 3. Multi-Agent Orchestration (14 articles)

### Competitive Landscape

| Player | Strategy | Key Differentiator |
|--------|----------|-------------------|
| **OpenAI** | Minimalist Agents SDK (Agents, Handoffs, Guardrails, Tracing) | Developer ergonomics, low ceremony |
| **Google** | ADK + A2A protocol + Vertex AI | Context compilation, protocol standardization |
| **Microsoft** | Agent Framework (AutoGen+SK) + Foundry | Enterprise integration, dual-language, managed infra |
| **Anthropic** | MCP protocol standard | Tool integration standardization |
| **IBM** | ACP protocol + BeeAI | Lightweight local agent messaging |

### Four Protocol Stack

| Protocol | Creator | Purpose | Format |
|----------|---------|---------|--------|
| **MCP** | Anthropic | Agent-to-tool | JSON-RPC 2.0 |
| **A2A** | Google/Linux Foundation | Agent-to-agent | AgentCard JSON |
| **ACP** | IBM/BeeAI | Local agent messaging | RESTful HTTP |
| **ANP** | Open source | Internet-scale agent networking | JSON-LD + W3C DID |

These are **complementary, not competitive**. Production systems likely need MCP + A2A at minimum.

### Core Orchestration Patterns
1. **Supervisor/Hierarchical** -- central orchestrator decomposes, delegates, monitors
2. **Sequential (Pipes and Filters)** -- deterministic chain, each output feeds next
3. **Parallel (Fan-out/Fan-in)** -- multiple agents process simultaneously
4. **Handoff** -- direct agent-to-agent transfer with full context
5. **Group Chat** -- shared conversation with moderator selecting speakers
6. **Adaptive Network** -- decentralized dynamic discovery and coordination

### OpenAI Swarm/Agents SDK
- Two primitives: **Routines** (system prompt + tools) and **Handoffs** (transfer conversation)
- Stateless `run()` -- no state saved between calls, developer controls persistence
- Handoff via function return: tool returning `Agent` triggers handoff
- Context variables shared across agents without a database
- Production: Guardrails run input validation in parallel with agent execution

### Google ADK: Context as Compiled View
**Most architecturally novel insight across all articles:**
- Context is not a mutable string buffer -- it's a **compiled view** over a richer stateful system
- Four-layer architecture: Working Context / Sessions / Memory / Artifacts
- Each invocation **recompiles** Working Context from underlying state via "compiler passes"
- Hybrid rule/agent context selection (human rules + agent-directed retrieval)
- Transforms context engineering from prompt gymnastics into **systems engineering**

### A2A Agent Cards
- Located at `/.well-known/agent-card.json`
- Fields: `name`, `url`, `version`, `capabilities`, `skills[]`
- Agents are **opaque** -- never expose internal state, only capabilities
- Interaction modes: sync, streaming SSE, async push notifications
- Auto-generation from MCP tool specs possible (TD Commons pipeline)

### Market Data
- Autonomous AI agent market: **$8.5B by 2026**, **$35B by 2030** (Deloitte)
- **40% of enterprise apps** will integrate AI agents by 2026 (Gartner)
- **1,445% surge** in multi-agent system inquiries Q1 2024 -> Q2 2025
- Organizations with multi-agent architectures: **45% faster resolution**, **60% more accurate outcomes**

### Key Insight: Graph-Based Orchestration is Table Stakes
Every major framework is converging on directed graphs with branching, cycles, and checkpointing. LangGraph pioneered; others following.

---

## 4. HITL, Time-Travel, Observability & Infrastructure (12 articles)

### HITL Interrupt Types

**Static interrupts:**
- `interrupt_before=True` / `interrupt_after=True` on node definitions
- Simpler but less flexible

**Dynamic interrupts (`interrupt()`):**
- Called inside node function; pauses based on runtime conditions
- Raises internal exception caught by runtime
- **Entire node re-executes on resume** (not from interrupt line)
- Place `interrupt()` at start of node to avoid duplicate side effects

### Resume Mechanism
- `Command(resume=value)` passed to `graph.invoke()`
- Resume value becomes return value of `interrupt()` call
- Thread ID in config identifies which checkpoint to resume from
- Multiple parallel interrupts: each interrupt ID maps to its resume value

### LangGraph Gap: No Direct State Editing
- State modification is **indirect** via resume values
- `update_state()` exists but only for time-travel scenarios
- **Orchestra opportunity**: provide direct state field editing during pause

### Seven HITL Design Patterns
1. Approve/Reject
2. Edit Graph State
3. Review Tool Calls
4. Validate Human Input
5. Multi-Turn Conversations
6. Escalation
7. Audit Trail

### Time-Travel: Three Core Capabilities
1. **Understand reasoning** -- replay to see inputs/state leading to each decision
2. **Debug mistakes** -- rewind to before error, step forward to find failure
3. **Explore alternatives** -- branch from checkpoint with modified state ("what-if")

### Time-Travel Implementation
- `get_state_history(config)` -- retrieve execution history
- `get_state(config, checkpoint_id)` -- load state at checkpoint
- `update_state(config, updates, checkpoint_id)` -- modify historical state, creating fork
- **Replay** = re-execute with same state; **Fork** = re-execute with modified state
- Original timeline preserved; forks are independent
- Event log IS the time-travel data -- no separate storage needed

### OpenTelemetry for Agent Tracing
Industry converging on OTel semantic conventions for AI agents:

```
Root Span: invoke_agent {gen_ai.agent.name}
  |-- gen_ai.chat (LLM call)
  |     gen_ai.request.model, gen_ai.usage.input_tokens, gen_ai.usage.output_tokens
  |-- tool.invoke {tool.name}
  |-- gen_ai.chat (follow-up)
```

Standard attributes: `gen_ai.agent.name`, `gen_ai.agent.id`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.response.finish_reason`

Cost = `input_tokens * input_price + output_tokens * output_price`

### Context Management Strategies
1. **Context Trimming** -- drop older turns, keep last N (deterministic, zero latency)
2. **Context Compression** -- summarize prior messages (better preservation, adds latency)
- Focused context improves tool selection, reduces retries
- "Clean room" effect: summaries correct accumulated errors

### asyncpg (PostgreSQL Driver)
- **5x faster than psycopg3** -- native binary protocol implementation
- Connection pool: `asyncpg.create_pool(dsn, min_size=4, max_size=20)`
- Transactions: `async with conn.transaction():`
- Custom JSONB codecs via `set_type_codec()`
- LISTEN/NOTIFY requires dedicated connection (listener must remain idle)
- From MagicStack (same team as uvloop)

### Temporal for Durable Execution
- **Signals** -- fire-and-forget inter-agent messages (strongly ordered, durable)
- **Queries** -- synchronous reads between agents (non-mutating)
- **Schedules** -- durable cron triggers for ambient agents
- State captured at every step via Event History
- On failure: replay from Event History to reconstruct state
- Activities (LLM calls, tool execution) have automatic retry with exponential backoff

### Docker Sandboxing
- Dedicated **microVM** per sandbox (hypervisor-level isolation)
- Private Docker daemon per VM -- agents can build/run containers safely
- HTTP/HTTPS filtering proxy with domain allow/deny lists
- Supports Claude Code, Codex CLI, Copilot CLI, Gemini CLI

---

## Cross-Cutting Recommendations for Orchestra Phase 2

### Architecture Decisions Validated by Research

| Decision | Validation |
|----------|------------|
| Event sourcing with snapshots | Universal consensus; ESAA paper validates for agent orchestration |
| SQLite default, PostgreSQL production | Pragmatic; asyncpg is 5x faster than alternatives |
| HITL via interrupt_before/after | Industry standard (LangGraph); add direct state editing as differentiator |
| Rich console trace | OTel conventions provide standard attributes; Rich renderer complements |
| MCP client integration | stdio + Streamable HTTP transports; support `tools/list` + `tools/call` |

### Novel Differentiators to Pursue

1. **Direct state editing during HITL pause** (LangGraph gap)
2. **Context compilation** a la Google ADK (context as compiled view, not append-only buffer)
3. **ESAA-style boundary contracts** (JSON Schema at agent/orchestrator boundary)
4. **Replay-safe tool gateways** (suppress side effects during time-travel replay)
5. **Hash-chain event integrity** (cryptographic verification of event log)
6. **Auto-generated A2A Agent Cards** from MCP tool definitions
7. **Code execution mode** for tool-heavy agents (Anthropic pattern: 150K -> 2K tokens)

### Production Safety Stack
1. Tool execution isolation (Docker microVM sandbox)
2. Network policies (allow/deny per agent/workflow)
3. Durable execution (Temporal-style retry + state recovery)
4. Human gates (HITL interrupts before critical actions)
5. Observability (OTel traces + Rich terminal + cost tracking)

### Event-Driven Architecture
```
EventBus (in-process, synchronous dispatch)
  |-- EventStore subscriber (persist to DB via asyncpg/aiosqlite)
  |-- TraceRenderer subscriber (Rich terminal display)
  |-- OTelExporter subscriber (emit gen_ai.* spans)
  |-- WebhookNotifier subscriber (optional external notifications)
```

---

## Sources

### Event Sourcing
- [Event Sourcing & CQRS with FastAPI and Celery - DEV Community](https://dev.to/markoulis/how-i-learned-to-stop-worrying-and-love-raw-events-event-sourcing-cqrs-with-fastapi-and-celery-477e)
- [ESAA: Event Sourcing for Autonomous Agents - arXiv](https://arxiv.org/abs/2602.23193)
- [Implementing event sourcing using a relational database - SoftwareMill](https://softwaremill.com/implementing-event-sourcing-using-a-relational-database/)
- [Event Sourcing: The Backbone of Agentic AI - Akka](https://akka.io/blog/event-sourcing-the-backbone-of-agentic-ai)
- [Pattern: Event sourcing - Microservices.io](https://microservices.io/patterns/data/event-sourcing.html)
- [EventSourcingDB - the native web](https://www.thenativeweb.io/products/eventsourcingdb)
- [Snapshots - EventSourcingDB](https://docs.eventsourcingdb.io/fundamentals/snapshots/)
- [Implementing Event Sourcing in Python - breadcrumbs collector.tech](https://breadcrumbscollector.tech/implementing-event-sourcing-in-python-part-1-aggregates/)
- [Domain models - eventsourcing 9.5.3 - Read the Docs](https://eventsourcing.readthedocs.io/en/stable/topics/domain.html)
- [Event sourcing pattern - AWS Prescriptive Guidance](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/event-sourcing.html)

### MCP
- [What is MCP AI - K2view](https://www.k2view.com/what-is-mcp-ai/)
- [MCP-SSE-Server-Sample Deep Dive - Skywork](https://skywork.ai/skypage/en/MCP-SSE-Server-Sample-A-Deep-Dive-for-AI-Engineers/1972560383681687552)
- [MCP Message Types JSON-RPC Reference - Portkey](https://portkey.ai/blog/mcp-message-types-complete-json-rpc-reference-guide/)
- [MCP Official Specification (2025-11-25)](https://modelcontextprotocol.io/specification/2025-11-25)
- [Unified Tool Integration for LLMs - arXiv](https://arxiv.org/abs/2508.02979)
- [MCP Explained - CodiLime](https://codilime.com/blog/model-context-protocol-explained/)
- [What Is MCP - Descope](https://www.descope.com/learn/post/mcp)
- [Code Execution with MCP - Anthropic](https://www.anthropic.com/engineering/code-execution-with-mcp)
- [Playwright CLI and MCP - TestDino](https://testdino.com/blog/playwright-cli-vs-mcp/)
- [Top 5 MCP Gateways 2026 - Maxim](https://www.getmaxim.ai/articles/top-5-mcp-gateways-in-2026-3/)
- [Patterns for Agentic Tools - Arcade.dev](https://www.arcade.dev/patterns/)
- [Dynamic Tool Loading - Strands SDK](https://builder.aws.com/content/2zeKrP0DJJLqC0Q9jp842IPxLMm/)

### Multi-Agent Orchestration
- [OpenAI Swarm Explained - Level Up Coding](https://levelup.gitconnected.com/openais-swarm-the-future-of-multi-agent-ai-systems-explained-7983ab1f15c5)
- [Taxonomy of Hierarchical Multi-Agent Systems - arXiv](https://arxiv.org/abs/2508.12683)
- [AI Agent Orchestration - Deloitte](https://www.deloitte.com/us/en/insights/industry/technology/technology-media-and-telecom-predictions/2026/ai-agent-orchestration.html)
- [Top AI Agent Orchestration Platforms 2026 - Redis](https://redis.io/blog/ai-agent-orchestration-platforms/)
- [AI Agent Protocols 2026 - ruh.ai](https://www.ruh.ai/blogs/ai-agent-protocols-2026-complete-guide)
- [Advanced Multi-Agent Orchestration Patterns - onabout.ai](https://www.onabout.ai/p/mastering-multi-agent-orchestration-architectures-patterns-roi-benchmarks-for-2025-2026)
- [Multi-Agent Orchestration Guide - Codebridge](https://www.codebridge.tech/articles/mastering-multi-agent-orchestration-coordination-is-the-new-scale-frontier)
- [A2A Agent Card via MCP - TD Commons](https://www.tdcommons.org/dpubs_series/9366/)
- [Agent Discovery Protocol - ANP](https://agentnetworkprotocol.com/en/specs/08-anp-agent-discovery-protocol-specification/)
- [AgentCard - A2A Protocol Community](https://agent2agent.info/docs/concepts/agentcard/)
- [Microsoft Agent Framework](https://learn.microsoft.com/en-us/agent-framework/overview/)
- [Agent-Orchestrator - LobeHub](https://lobehub.com/skills/openclaw-skills-agent-orchestrator)
- [What's new in Microsoft Foundry - Dec 2025/Jan 2026](https://devblogs.microsoft.com/foundry/whats-new-in-microsoft-foundry-dec-2025-jan-2026/)
- [Context-Aware Multi-Agent Framework - Google Developers](https://developers.googleblog.com/architecting-efficient-context-aware-multi-agent-framework-for-production/)

### HITL, Time-Travel, Observability & Infrastructure
- [LangGraph HITL Strategies - Sparkco](https://sparkco.ai/blog/deep-dive-into-langgraph-hitl-integration-strategies)
- [Time Travel in Agentic AI - Towards AI](https://pub.towardsai.net/time-travel-in-agentic-ai-3063c20e5fe2)
- [Interrupts - LangChain Docs](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [Configure tracing for AI agents - Microsoft Foundry](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-framework)
- [Context Engineering Sessions - OpenAI Cookbook](https://cookbook.openai.com/examples/agents_sdk/session_memory)
- [Hierarchical Code Summarization - arXiv](https://arxiv.org/abs/2504.08975)
- [Docker Sandboxes - Docker Blog](https://www.docker.com/blog/docker-sandboxes-run-claude-code-and-other-coding-agents-unsupervised-but-safely/)
- [Orchestrating Ambient Agents - Temporal](https://temporal.io/blog/orchestrating-ambient-agents-with-temporal)
- [10 Best Agentic Browsers 2026 - Bright Data](https://brightdata.com/blog/ai/best-agent-browsers)
- [Python Asyncio Database Drivers - Super Fast Python](https://superfastpython.com/asyncio-database-drivers/)
- [asyncpg - GitHub](https://github.com/MagicStack/asyncpg)
- [asyncpg Usage Documentation](https://magicstack.github.io/asyncpg/current/usage.html)
