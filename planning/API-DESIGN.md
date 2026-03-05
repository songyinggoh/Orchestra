# Orchestra: Public API Design

**Document Version:** 1.0
**Date:** 2026-03-05
**Status:** Draft for Review
**Authors:** API Design Agent

---

## Preface: Design Philosophy

Orchestra's API is governed by five principles, in priority order:

1. **Progressive complexity** — The simplest case must be expressible in under 20 lines. The hardest case must be expressible without escape hatches.
2. **Explicit over implicit** — State flows, routing decisions, and agent communication are visible in code, not hidden by magic.
3. **Fail loudly at build time** — Type mismatches between agent outputs, unreachable nodes, and missing reducers are detected at `compile()`, not discovered at 2am in production.
4. **Zero-infrastructure first** — Every feature works locally with `pip install orchestra`. Nothing requires Docker, a database, or a cloud account to run for the first time.
5. **Pythonic throughout** — Decorators, `async/await`, `with` blocks, Pydantic models, and type annotations are the lingua franca. No XML, no proprietary DSL, no magic strings.

### Why This API Shape, Not Another

LangGraph has the best architectural model (explicit state graphs, reducers) but the worst developer experience — it takes 50 lines to do what Swarm does in 5. CrewAI has the best developer experience but the worst architectural model — it hides the graph entirely, making debugging impossible and complex patterns inexpressible.

Orchestra's API thread-the-needle: simple patterns feel as easy as CrewAI, complex patterns feel as powerful as LangGraph, and the same mental model scales from one to the other without a conceptual break.

---

## Section 1: Quick Start API

This is what goes in the README. A developer should reach "it works" in under 5 minutes.

```python
import asyncio
from orchestra import agent, WorkflowGraph, run

# Define agents with the decorator syntax
@agent(model="gpt-4o-mini")
async def researcher(topic: str) -> str:
    """You are a research assistant. Given a topic, find the key facts and
    summarize them clearly in 3-5 bullet points."""

@agent(model="gpt-4o-mini")
async def writer(research: str) -> str:
    """You are a technical writer. Given research notes, write a clear,
    engaging 2-paragraph summary suitable for a general audience."""

# Connect them into a workflow
graph = (
    WorkflowGraph()
    .then(researcher)
    .then(writer)
)

# Run it
result = asyncio.run(run(graph, input={"topic": "quantum computing"}))
print(result.output)
```

That is it. 18 lines, two agents, a sequential workflow.

**What happens under the hood:** Orchestra compiles the graph (validates connectivity, infers state schema from type annotations), creates an in-memory SQLite checkpoint store, runs the agents in sequence using asyncio, and returns a `RunResult` with the final output and the full execution trace.

**The README progression:** The quick start shows this. The next example shows adding tools. The third shows parallel fan-out. Each adds exactly one new concept.

### Comparison

| Framework | Equivalent Quick Start | Lines |
|---|---|---|
| **Orchestra** | Above | 18 |
| **CrewAI** | Agent + Task + Crew + process | ~25 |
| **LangGraph** | Graph + node functions + TypedDict state + compile + invoke | ~45 |
| **Swarm** | Agent + client.run() | ~12 (but no graph, no state, no observability) |

Swarm is shorter, but it cannot scale to any production pattern. Orchestra's quick start is nearly as short while remaining architecturally sound.

---

## Section 2: Agent Definition API

All three styles compile to the same internal `AgentSpec` dataclass. A graph node does not know or care which definition style created the agent it wraps. Style is a developer preference, not an architectural constraint.

### The Internal AgentSpec

```python
# orchestra/core/spec.py — not part of the public API, shown for clarity
from dataclasses import dataclass, field
from typing import Any
from pydantic import BaseModel

@dataclass
class AgentSpec:
    name: str
    system_prompt: str
    model: str
    provider: str                          # "openai", "anthropic", "google", etc.
    tools: list[str] = field(default_factory=list)  # tool registry keys
    output_type: type[BaseModel] | None = None       # Pydantic output schema
    temperature: float = 0.7
    max_tokens: int | None = None
    memory_config: MemoryConfig | None = None
    guardrails: list[GuardrailSpec] = field(default_factory=list)
    capabilities: set[str] = field(default_factory=set)  # IAM capability grants
    retry_policy: RetryPolicy | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### Style 1: Class-Based (Production)

Class-based definition is the recommended style for production code. It is explicit, refactorable, discoverable in IDEs, and supports inheritance for sharing configuration.

```python
from orchestra import Agent, tool
from orchestra.memory import MemoryConfig
from pydantic import BaseModel
from typing import ClassVar


# --- Output schema ---
class ResearchReport(BaseModel):
    summary: str
    key_findings: list[str]
    sources: list[str]
    confidence: float  # 0.0 - 1.0


# --- Tool definition (see Section 5 for full tool API) ---
@tool
async def web_search(query: str, max_results: int = 5) -> list[dict]:
    """Search the web and return results."""
    ...

@tool
async def read_document(url: str) -> str:
    """Fetch and extract text from a URL."""
    ...


# --- Minimal class-based agent ---
class ResearchAgent(Agent):
    # Required
    role: ClassVar[str] = "Senior Research Analyst"
    model: ClassVar[str] = "gpt-4o"

    # System prompt — can be a string or a method
    system_prompt: ClassVar[str] = """
        You are a senior research analyst with expertise in synthesizing
        information from multiple sources. Always cite your sources.
        Output must be structured as a ResearchReport.
    """

    # Tools this agent is allowed to use
    tools: ClassVar[list] = [web_search, read_document]

    # Pydantic model for structured output (validated before passing downstream)
    output_type: ClassVar[type] = ResearchReport


# --- Full class-based agent with all options ---
class AnalyticsAgent(Agent):
    role: ClassVar[str] = "Data Analyst"
    goal: ClassVar[str] = "Identify trends and anomalies in datasets"
    backstory: ClassVar[str] = """
        You have 10 years of experience in quantitative analysis.
        You favor precision over speed and always show your reasoning.
    """

    # Model configuration
    model: ClassVar[str] = "gpt-4o"
    provider: ClassVar[str] = "openai"   # explicit provider (default: inferred from model)
    temperature: ClassVar[float] = 0.2   # lower for analytical tasks
    max_tokens: ClassVar[int] = 4096

    # Output
    output_type: ClassVar[type] = AnalyticsReport

    # Memory (see Section 4)
    memory: ClassVar[MemoryConfig] = MemoryConfig(
        short_term=True,    # remember this session's conversation
        long_term=True,     # persist key facts across sessions
        entity_tracking=True,  # extract and remember entities (people, orgs, etc.)
    )

    # Capabilities (IAM — see Section 6)
    capabilities: ClassVar[set[str]] = {"db:read", "files:read"}

    # Retry policy (see Section 10)
    retry_policy: ClassVar[RetryPolicy] = RetryPolicy(max_attempts=3, backoff="exponential")

    # Dynamic system prompt — override to inject runtime context
    async def build_system_prompt(self, context: ExecutionContext) -> str:
        dataset_name = context.state.get("dataset_name", "unknown dataset")
        return f"{self.backstory}\n\nYou are analyzing: {dataset_name}"

    # Pre-processing hook: modify input before LLM call
    async def before_run(self, input: dict, context: ExecutionContext) -> dict:
        # Example: normalize input field names
        return {"data": input.get("raw_data") or input.get("data")}

    # Post-processing hook: validate or transform output
    async def after_run(self, output: AnalyticsReport, context: ExecutionContext) -> AnalyticsReport:
        if output.confidence < 0.5:
            context.emit_warning("Low confidence analysis — consider human review")
        return output


# --- Inheritance for sharing configuration ---
class BaseProductionAgent(Agent):
    """Base class for all production agents — enforces org-wide defaults."""
    provider: ClassVar[str] = "anthropic"
    model: ClassVar[str] = "claude-opus-4-6"
    retry_policy: ClassVar[RetryPolicy] = RetryPolicy(max_attempts=3)
    guardrails: ClassVar[list] = [PIIGuardrail(), ContentSafetyGuardrail()]

class CustomerSupportAgent(BaseProductionAgent):
    role: ClassVar[str] = "Customer Support Specialist"
    model: ClassVar[str] = "claude-haiku-3"  # override to cheaper model for this role
    tools: ClassVar[list] = [lookup_ticket, update_ticket, send_email]
    output_type: ClassVar[type] = SupportResponse
```

**Design rationale:** `ClassVar` annotations are used for class-level configuration (as opposed to instance attributes) because Python class bodies are executed once, not per-instance. This mirrors how CrewAI does it but with explicit `ClassVar` typing for correctness. The `before_run` / `after_run` hooks give production agents lifecycle control without requiring graph-level middleware. Inheritance allows org-wide policy enforcement.

**LangGraph comparison:** LangGraph uses plain functions as nodes with no class structure. Sharing configuration across nodes requires manual wiring or global state. Orchestra's class model makes agent reuse and org-wide policies natural.

**CrewAI comparison:** CrewAI uses Pydantic fields (not `ClassVar`), which means agent configuration is per-instance. This is less efficient and leads to surprising behavior when agents are shared across crews. Orchestra's `ClassVar` pattern is more correct.

---

### Style 2: Decorator-Based (Rapid Prototyping)

The decorator syntax is optimized for minimal ceremony. The function docstring becomes the system prompt. Type annotations define the input/output contract. Tools are passed as arguments.

```python
from orchestra import agent, tool
from pydantic import BaseModel


# --- Simplest possible decorator agent ---
@agent(model="gpt-4o-mini")
async def summarizer(text: str) -> str:
    """Summarize the given text in 2-3 sentences."""


# --- With structured output ---
class ExtractedData(BaseModel):
    entities: list[str]
    sentiment: str
    key_topics: list[str]

@agent(model="gpt-4o", temperature=0.1)
async def extractor(document: str) -> ExtractedData:
    """
    Extract structured information from the document.
    Identify: named entities, overall sentiment, and key topics.
    Always return valid JSON matching the ExtractedData schema.
    """


# --- With tools ---
@agent(model="gpt-4o", tools=[web_search, read_document])
async def researcher(query: str) -> ResearchReport:
    """
    You are a senior research analyst.
    Search for information about the query and synthesize findings.
    Always cite your sources.
    """


# --- With all options ---
@agent(
    name="code-reviewer",       # explicit name (default: function name)
    model="claude-opus-4-6",
    provider="anthropic",
    temperature=0.3,
    max_tokens=8192,
    tools=[read_file, run_tests],
    memory=MemoryConfig(short_term=True),
    capabilities={"files:read", "tests:run"},
    retry_policy=RetryPolicy(max_attempts=2),
    guardrails=[ContentSafetyGuardrail()],
)
async def code_reviewer(pull_request_diff: str) -> CodeReview:
    """
    You are a senior software engineer reviewing a pull request.
    Assess: correctness, security, performance, and maintainability.
    Provide specific, actionable feedback with line-level comments.
    """


# --- Using decorator agents in a graph ---
graph = (
    WorkflowGraph()
    .then(researcher)
    .then(code_reviewer)
)
```

**Design rationale:** The function body of a `@agent`-decorated function is intentionally empty (or contains only a docstring). The framework never calls the function body directly — it uses the function's name, signature, docstring, and type annotations to construct an `AgentSpec`, then the actual LLM call is made by the executor. This mirrors how `@dataclass` or `@app.get()` work in FastAPI — the decorator transforms the function, not augments it.

An alternative considered was allowing developers to write logic in the function body that would pre/post-process the LLM call. This was rejected because it makes the agent's behavior unclear: is the code in the body calling the LLM? Preprocessing? Postprocessing? The separation between agent definition (decorator) and lifecycle hooks (class `before_run`/`after_run`) is intentionally explicit.

**Edge case — empty return for agents that just produce side effects:**
```python
@agent(model="gpt-4o-mini", tools=[send_email])
async def notifier(message: str) -> None:
    """Send the given message as an email notification. Use the send_email tool."""
```

**Edge case — multiline docstring as prompt template:**
```python
@agent(model="gpt-4o")
async def translator(text: str, target_language: str) -> str:
    """
    Translate the given text to {target_language}.
    Preserve the tone and style of the original.
    If the text contains technical terminology, keep it in the original language.
    """
    # Template variables in the docstring are resolved from the function arguments
    # at runtime. {target_language} becomes the actual value passed to the agent.
```

---

### Style 3: Config-Based (YAML)

YAML definitions are for no-code platforms, ops teams who need to configure agents without touching Python, and template libraries that can be distributed as files.

```yaml
# agents/researcher.yaml
name: researcher
role: Senior Research Analyst
goal: Find accurate, sourced information on any topic
backstory: |
  You have 15 years of experience in investigative research.
  You always verify information across multiple sources before concluding.
  Your outputs are always structured, cited, and ready for publication.

model: gpt-4o
provider: openai
temperature: 0.5
max_tokens: 4096

output_type:
  $ref: schemas/ResearchReport.json   # JSON Schema or Pydantic class path

tools:
  - web_search
  - read_document
  - arxiv_search

memory:
  short_term: true
  long_term: true
  entity_tracking: false

capabilities:
  - web:read
  - files:read

retry_policy:
  max_attempts: 3
  backoff: exponential
  initial_delay_ms: 500

guardrails:
  - type: pii_detection
    action: redact
  - type: content_safety
    action: block

metadata:
  team: research
  owner: alice@example.com
  version: "2.1"
```

```yaml
# workflows/research_pipeline.yaml
name: research-pipeline
description: Multi-stage research and writing workflow

agents:
  - $ref: agents/researcher.yaml
  - $ref: agents/writer.yaml
  - $ref: agents/editor.yaml

graph:
  entry: researcher
  edges:
    - from: researcher
      to: writer
    - from: writer
      to: editor

state:
  schema: schemas/ResearchState.json
  reducers:
    findings:
      strategy: merge_list
    draft:
      strategy: last_write_wins

config:
  max_turns: 20
  timeout_seconds: 300
  checkpoint_store: sqlite
```

**Loading YAML agents in Python:**
```python
from orchestra import load_agent, load_workflow

# Load a single agent
researcher = load_agent("agents/researcher.yaml")

# Load a complete workflow definition
graph = load_workflow("workflows/research_pipeline.yaml")

# Mix YAML and Python agents
graph = (
    WorkflowGraph()
    .then(researcher)               # from YAML
    .then(custom_python_agent)      # from @agent decorator
    .then(EditorAgent)              # from class definition
)
```

**Design rationale:** YAML is the third definition style, not the first, because it is the least powerful. It cannot express dynamic logic, lifecycle hooks, or custom reducers. It is included specifically for the enterprise use case where security/ops teams need to audit and control agent configuration without Python access, and for integrations with workflow automation tools (n8n, Temporal UI, etc.) that speak YAML natively.

**LangGraph comparison:** LangGraph has no YAML support. CrewAI has some YAML support but it is not comprehensive. Orchestra's YAML schema is formally defined and validated with jsonschema on load, so YAML errors are caught immediately with descriptive messages.

---

## Section 3: Graph Construction API

The `WorkflowGraph` is the core of Orchestra. Every orchestration pattern maps to a combination of node types and edge types.

### Node Types

```python
from orchestra.graph import (
    AgentNode,      # Wraps an Agent — makes an LLM call
    FunctionNode,   # Pure Python function — no LLM call
    DynamicNode,    # Generates sub-nodes at runtime
    SubgraphNode,   # Embeds another compiled graph
)
```

### Edge Types

```python
# Sequential: A -> B (always)
# Conditional: A -> B or A -> C (based on state/output)
# Parallel: A -> [B, C, D] (fan-out, run concurrently)
# Join: [B, C, D] -> E (fan-in, wait for all/any)
# Handoff: A -> B (B takes over the conversation context)
# Loop: A -> A (with exit condition)
```

### Pattern 1: Sequential Flow

```python
from orchestra import WorkflowGraph, run

# Fluent builder style (recommended for simple flows)
graph = (
    WorkflowGraph()
    .then(researcher)   # Step 1
    .then(writer)       # Step 2
    .then(editor)       # Step 3
)

# Equivalent explicit style (recommended when steps need names)
graph = WorkflowGraph()
graph.add_node("research", researcher)
graph.add_node("write",    writer)
graph.add_node("edit",     editor)
graph.add_edge("research", "write")
graph.add_edge("write",    "edit")

compiled = graph.compile()
result = await run(compiled, input={"topic": "neural networks"})
```

**State flow in sequential graphs:** Each agent receives the full workflow state as its input context. Its output is merged into the workflow state using the reducer defined for each state field. The next agent receives the updated state. No agent receives only the previous agent's raw output — it receives the full accumulated state, which prevents loss of context.

---

### Pattern 2: Parallel Fan-Out / Fan-In

```python
from orchestra import WorkflowGraph
from orchestra.graph import join

# Three agents run in parallel, then results are merged
graph = (
    WorkflowGraph()
    .then(query_planner)
    .parallel(
        research_agent_1,   # Runs concurrently
        research_agent_2,   # Runs concurrently
        research_agent_3,   # Runs concurrently
    )
    .join(strategy="all")   # Wait for all three, merge state via reducers
    .then(synthesizer)
)

# Fan-out with explicit join strategy
graph = (
    WorkflowGraph()
    .then(query_planner)
    .parallel(
        legal_reviewer,
        technical_reviewer,
        market_analyst,
        join=join.all(timeout_seconds=60),   # Wait for all, timeout after 60s
    )
    .then(final_decision_agent)
)

# Fan-out with partial join (proceed when any N agents complete)
graph = (
    WorkflowGraph()
    .parallel(
        source_a_searcher,
        source_b_searcher,
        source_c_searcher,
        join=join.any(n=2),  # Proceed when 2 of 3 complete
    )
    .then(synthesizer)
)
```

**How reducers handle fan-in:** When multiple parallel agents write to the same state field, the reducer for that field is invoked. Without a reducer, a write conflict raises `StateConflictError` at compile time — Orchestra never silently drops data.

```python
from orchestra.state import WorkflowState, merge_list, last_write_wins
from pydantic import BaseModel
from typing import Annotated

class ResearchState(WorkflowState):
    # Each parallel agent appends to this list — merge_list reducer handles it
    findings: Annotated[list[str], merge_list] = []

    # Only one agent writes this — last_write_wins is appropriate
    final_report: Annotated[str, last_write_wins] = ""

    # Custom reducer for merging dicts from multiple agents
    agent_outputs: Annotated[dict[str, str], merge_dict] = {}
```

**LangGraph comparison:** LangGraph's parallel execution is identical conceptually but requires explicit `Send` objects and manual state key management. Orchestra's `.parallel()` and `.join()` builder methods handle the `Send`/fan-in wiring automatically while preserving full control over join strategy.

---

### Pattern 3: Conditional Branching

```python
from orchestra import WorkflowGraph
from orchestra.graph import route

# Route based on state value
def select_next_agent(state: ReviewState) -> str:
    if state.sentiment_score < 0.3:
        return "escalation_agent"
    elif state.needs_human_review:
        return "human_review"
    else:
        return "auto_resolve_agent"

graph = (
    WorkflowGraph()
    .then(sentiment_analyzer)
    .branch(
        select_next_agent,         # routing function
        paths={
            "escalation_agent":   escalation_agent,
            "human_review":       human_review_node,
            "auto_resolve_agent": auto_resolve_agent,
        }
    )
    .merge("resolution")           # named merge point — all paths converge here
    .then(resolution_logger)
)

# Shorthand for binary conditions
graph = (
    WorkflowGraph()
    .then(classifier)
    .if_then(
        condition=lambda state: state.category == "urgent",
        then=urgent_handler,
        otherwise=standard_handler,
    )
    .then(logger)
)

# Router agent — the LLM itself makes the routing decision
graph = (
    WorkflowGraph()
    .then(triage_router)           # agent whose output IS the routing decision
    .route_on_output(              # route based on the agent's structured output
        paths={
            "billing":   billing_agent,
            "technical": technical_agent,
            "general":   general_agent,
        }
    )
)
```

**Design rationale:** Three branching styles for three situations:
- `.branch()` — when routing logic is deterministic Python (most common, most debuggable)
- `.if_then()` — syntactic sugar for the common binary case
- `.route_on_output()` — when the LLM itself should decide routing (Swarm-style)

**LangGraph comparison:** LangGraph's `add_conditional_edges` is powerful but requires the routing function to return a string matching node names. Orchestra's `.branch()` does the same with a more descriptive API. The `.route_on_output()` pattern is unique to Orchestra and handles the common case where an LLM acts as a router agent.

---

### Pattern 4: Loops

```python
from orchestra import WorkflowGraph
from orchestra.graph import loop

# Loop until condition is met (max_iterations is a safety guard)
graph = (
    WorkflowGraph()
    .then(task_generator)
    .loop(
        body=worker_agent,
        exit_condition=lambda state: state.tasks_remaining == 0,
        max_iterations=10,   # required safety guard — compile error if omitted
    )
    .then(result_aggregator)
)

# Loop with multiple agents in the body
graph = (
    WorkflowGraph()
    .then(planner)
    .loop(
        body=(
            WorkflowGraph()
            .then(executor)
            .then(validator)
        ),
        exit_condition=lambda state: state.validation_passed,
        max_iterations=5,
    )
    .then(finalizer)
)

# Explicit loop with named continue/break edges
graph = WorkflowGraph()
graph.add_node("planner",    planner)
graph.add_node("executor",   executor)
graph.add_node("validator",  validator)
graph.add_node("finalizer",  finalizer)
graph.add_edge("planner",    "executor")
graph.add_edge("executor",   "validator")
graph.add_conditional_edge(
    "validator",
    condition=lambda state: "executor" if not state.done else "finalizer"
)

compiled = graph.compile(max_turns=20)  # global safety guard
```

**Edge case — detecting infinite loops:** `compile()` performs cycle detection. Any cycle must have either a `max_iterations` guard on `.loop()` or a `max_turns` argument on `compile()`. A cycle without either raises `GraphCompileError: cycle detected without termination guard`. This catches the most common production failure mode before deployment.

---

### Pattern 5: Handoffs (Swarm-Style)

Handoffs are for conversational routing — a triage agent passes full conversation context to a specialist agent, and the specialist continues the conversation as if they had been there from the start.

```python
from orchestra import WorkflowGraph
from orchestra.graph import handoff

# Simple handoff — triage routes to one of several specialists
graph = (
    WorkflowGraph()
    .then(triage_agent)         # triage decides who handles it
    .handoff(                   # transfer full conversation context
        billing_agent,          # specialist A
        technical_agent,        # specialist B
        hr_agent,               # specialist C
        # Routing: triage agent's output must contain a 'handoff_to' field
        # (or use route_fn for Python-level routing)
    )
)

# Handoff with Python routing function (when you don't want an LLM to route)
graph = (
    WorkflowGraph()
    .then(triage_agent)
    .handoff(
        billing_agent,
        technical_agent,
        route_fn=lambda state: state.department,   # Python routing, not LLM
    )
)

# Multi-hop handoff — specialists can hand off to each other
graph = WorkflowGraph()
graph.add_node("triage",    triage_agent)
graph.add_node("billing",   billing_agent)
graph.add_node("technical", technical_agent)
graph.add_node("escalation", escalation_agent)

# Any agent can hand off to escalation
for agent_name in ["billing", "technical"]:
    graph.add_handoff(
        agent_name,
        "escalation",
        condition=lambda state: state.escalated,
    )

compiled = graph.compile()
```

**What handoff transfers:** The full conversation message history, the current workflow state, and a `HandoffContext` object containing the reason for the handoff and any notes from the handing-off agent. The receiving agent can see the full conversation and pick up seamlessly.

**Swarm comparison:** Swarm implements handoffs as function returns — an agent returns an `Agent` object instead of a string to signal a handoff. Orchestra formalizes this as a first-class graph edge type, adding persistence (the handoff state is checkpointed), observability (handoffs appear in the trace tree), and multi-hop routing.

---

### Pattern 6: Dynamic Subgraphs

DynamicNode is Orchestra's most novel pattern. A planner agent decomposes a task at runtime, creating sub-nodes whose number and configuration are not known at graph-compile time.

```python
from orchestra import WorkflowGraph
from orchestra.graph import DynamicNode, SubgraphSpec

# The planner agent returns a list of tasks
# DynamicNode spawns one agent per task, runs them in parallel, then merges
graph = (
    WorkflowGraph()
    .then(task_planner)          # returns TaskPlan with list of subtasks
    .dynamic(
        # Factory: given the planner's output, return a list of subgraphs to run
        factory=lambda state: [
            SubgraphSpec(
                agent=research_agent,
                input={"query": task.query, "depth": task.depth},
                output_key=f"research_{i}",
            )
            for i, task in enumerate(state.task_plan.subtasks)
        ],
        join=join.all(),         # wait for all dynamic subgraphs to complete
    )
    .then(result_synthesizer)
)

# Explicit DynamicNode for more control
async def build_research_subgraphs(state: ResearchState) -> list[SubgraphSpec]:
    """Given a research plan, create one subgraph per research thread."""
    specs = []
    for i, thread in enumerate(state.plan.threads):
        subgraph = (
            WorkflowGraph()
            .then(web_searcher)
            .then(document_reader)
            .then(fact_extractor)
        )
        specs.append(SubgraphSpec(
            graph=subgraph,
            input={"topic": thread.topic, "sources": thread.preferred_sources},
            output_key=f"thread_{i}",
            max_turns=10,
        ))
    return specs

graph = (
    WorkflowGraph()
    .then(research_planner)
    .add_node("dynamic_research", DynamicNode(factory=build_research_subgraphs))
    .add_edge("research_planner", "dynamic_research")
    .then(synthesizer)
)
```

**LangGraph comparison:** LangGraph graphs are static after `compile()`. Dynamic subgraph generation is not possible without escape hatches (custom node implementations that manually invoke the graph engine). Orchestra's `DynamicNode` is a first-class citizen with full observability, checkpointing, and fan-in support.

---

### Pattern 7: Subgraph Composition

Pre-built subgraphs can be composed into larger workflows, enabling reusable workflow components.

```python
from orchestra import WorkflowGraph, load_graph

# Define a reusable research subgraph
research_subgraph = (
    WorkflowGraph(name="research")
    .then(query_expander)
    .parallel(web_searcher, arxiv_searcher, news_searcher)
    .join(strategy="all")
    .then(source_deduplicator)
    .then(fact_extractor)
)

# Compile it as a reusable component
compiled_research = research_subgraph.compile()

# Compose into a larger workflow
full_pipeline = (
    WorkflowGraph(name="full-research-pipeline")
    .then(topic_analyzer)
    .subgraph(compiled_research)    # embed the entire research subgraph as one node
    .then(report_writer)
    .then(editor)
)

# Load subgraphs from files
research_subgraph = load_graph("subgraphs/research.yaml")
writing_subgraph  = load_graph("subgraphs/writing.yaml")

custom_pipeline = (
    WorkflowGraph()
    .then(planner)
    .subgraph(research_subgraph)
    .subgraph(writing_subgraph)
    .then(publisher)
)
```

---

### Graph Compile Options

```python
compiled = graph.compile(
    state_schema=ResearchState,        # explicit state schema (inferred if omitted)
    max_turns=50,                      # global safety guard (default: 100)
    interrupt_before=["human_review"], # pause before these nodes for HITL
    interrupt_after=["planner"],       # pause after these nodes for HITL
    checkpointer=SqliteCheckpointer("./runs.db"),  # explicit checkpointer
    validate_types=True,               # enforce input/output type compatibility on edges (default: True)
    debug=True,                        # verbose compile logging
)
```

**What `compile()` validates:**
- All referenced nodes exist
- No unreachable nodes
- No cycles without termination guards
- State field types match across edges (input types of agent B match output types of agent A)
- All referenced tools are registered
- All referenced capabilities are defined

---

## Section 4: State API

### Defining Custom State

State is a Pydantic model that extends `WorkflowState`. Every field that parallel agents might write to needs an explicit reducer.

```python
from orchestra.state import WorkflowState, merge_list, last_write_wins, merge_dict, concat_str
from pydantic import BaseModel, Field
from typing import Annotated, Any


# --- Built-in reducers ---
# merge_list    : append new items to existing list (no deduplication)
# merge_set     : union of two sets
# merge_dict    : shallow merge, new keys win
# last_write_wins: new value replaces existing (default for scalar fields)
# concat_str    : concatenate strings with a separator
# sum_numbers   : add numeric values
# keep_first    : ignore updates, keep original value
# max_value     : keep the larger of two numeric values
# min_value     : keep the smaller of two numeric values


class ResearchState(WorkflowState):
    # Scalar fields — last_write_wins is the default (no annotation needed)
    query: str = ""
    status: str = "pending"
    final_report: str = ""

    # List fields — multiple agents append findings
    findings: Annotated[list[str], merge_list] = []
    sources: Annotated[list[str], merge_list] = []
    errors: Annotated[list[str], merge_list] = []

    # Dict fields — multiple agents contribute different keys
    agent_outputs: Annotated[dict[str, str], merge_dict] = {}

    # Numeric accumulation
    total_tokens_used: Annotated[int, sum_numbers] = 0
    total_cost_usd: Annotated[float, sum_numbers] = 0.0

    # Nested Pydantic models
    research_plan: ResearchPlan | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# --- Custom reducer function ---
def merge_reports(existing: list[Report], new: list[Report]) -> list[Report]:
    """Custom reducer: merge reports, deduplicating by source URL."""
    existing_urls = {r.url for r in existing}
    unique_new = [r for r in new if r.url not in existing_urls]
    return existing + unique_new

class AdvancedState(WorkflowState):
    reports: Annotated[list[Report], merge_reports] = []


# --- State with validation ---
from pydantic import field_validator, model_validator

class ValidatedState(WorkflowState):
    confidence: float = 0.0
    findings: Annotated[list[str], merge_list] = []

    @field_validator("confidence")
    @classmethod
    def confidence_in_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"confidence must be between 0 and 1, got {v}")
        return v

    @model_validator(mode="after")
    def findings_required_when_confident(self) -> "ValidatedState":
        if self.confidence > 0.8 and not self.findings:
            raise ValueError("High confidence requires at least one finding")
        return self
```

### Accessing State in Agent Code

Agents access state through the `ExecutionContext` passed to lifecycle hooks. The framework handles state reading and writing — agents do not write to state directly; they return values that the framework merges.

```python
from orchestra import Agent
from orchestra.context import ExecutionContext


class ContextAwareAgent(Agent):
    role: ClassVar[str] = "Context-Aware Agent"
    model: ClassVar[str] = "gpt-4o"

    async def build_system_prompt(self, context: ExecutionContext) -> str:
        # Read current state
        state: ResearchState = context.state
        prior_findings = "\n".join(state.findings)

        return f"""
        You are a research analyst.
        Prior findings so far:
        {prior_findings}

        Build on these findings, do not repeat them.
        """

    async def before_run(self, input: dict, context: ExecutionContext) -> dict:
        # Read state, read metadata, read run config
        state = context.state
        run_id = context.run_id
        turn = context.turn_number

        # Access parent workflow info
        workflow_name = context.workflow.name

        # Access secrets (scoped by capability)
        api_key = context.get_secret("SEARCH_API_KEY")  # raises if not granted

        return input

    async def after_run(self, output: str, context: ExecutionContext) -> str:
        # Emit events for observability
        context.emit_event("research.finding", {"content": output, "agent": self.role})

        # Write to state — use context.update_state for explicit partial updates
        await context.update_state({"status": "research_complete"})

        return output
```

### How Reducers Work for Parallel Fan-In

When multiple parallel agents complete and write to the same state field, Orchestra applies reducers in a deterministic order (by agent name, alphabetically) to ensure reproducibility.

```python
# What happens internally during fan-in:
# 1. Agent A returns: {"findings": ["finding A1", "finding A2"]}
# 2. Agent B returns: {"findings": ["finding B1"]}
# 3. Agent C returns: {"findings": ["finding C1", "finding C2", "finding C3"]}
#
# Fan-in reducer application order (alphabetical by agent name):
# state.findings = merge_list([], ["finding A1", "finding A2"])   -> ["finding A1", "finding A2"]
# state.findings = merge_list(["finding A1", "finding A2"], ["finding B1"])  -> [..., "finding B1"]
# state.findings = merge_list([...], ["finding C1", "finding C2", "finding C3"])  -> [all 6]
#
# Final state.findings = ["finding A1", "finding A2", "finding B1", "finding C1", "finding C2", "finding C3"]
```

**State inspection and time-travel:**
```python
from orchestra import get_run, inspect_state

# Get state at a specific checkpoint
run = await get_run(run_id="run_abc123")
state_after_research = await run.state_at(checkpoint="after:research_agent")
state_after_writing  = await run.state_at(checkpoint="after:writing_agent")

# Compare state at two points
diff = state_after_writing.diff(state_after_research)
print(diff)

# Resume from a checkpoint with modified state
modified_state = state_after_research.copy(update={"findings": ["manually added finding"]})
result = await run.resume_from(
    checkpoint="after:research_agent",
    state_override=modified_state,
)
```

---

## Section 5: Tool API

### @tool Decorator

```python
from orchestra.tools import tool, ToolContext
from pydantic import BaseModel


# --- Simplest tool ---
@tool
async def get_weather(city: str) -> str:
    """Get current weather for a city."""
    # Implementation
    return f"Sunny, 72F in {city}"


# --- Tool with Pydantic input/output schemas ---
class SearchInput(BaseModel):
    query: str
    max_results: int = 10
    date_filter: str | None = None   # e.g., "last_week", "last_month"

class SearchResult(BaseModel):
    url: str
    title: str
    snippet: str
    published_date: str | None

@tool(
    name="web_search",                          # explicit name (default: function name)
    description="Search the web for information. Returns relevant URLs and snippets.",
    category="web",                             # for registry organization
    requires_capability="web:read",             # IAM capability gate
    timeout_seconds=10,
    cache_ttl_seconds=300,                      # cache results for 5 minutes
    rate_limit="10/minute",                     # per-agent rate limit
)
async def web_search(input: SearchInput) -> list[SearchResult]:
    """Search the web and return structured results."""
    results = await _search_api(input.query, input.max_results)
    return [SearchResult(**r) for r in results]


# --- Tool with context access ---
@tool
async def read_user_file(filepath: str, ctx: ToolContext) -> str:
    """Read a file from the user's workspace."""
    # ctx provides access to the calling agent's identity and permissions
    agent_id = ctx.agent_id
    run_id = ctx.run_id

    # Check fine-grained permissions (beyond capability gate)
    if not ctx.can_access_path(filepath):
        raise ToolPermissionError(f"Agent {agent_id} cannot access {filepath}")

    return await _read_file(filepath)


# --- Tool with side effects and audit logging ---
@tool(requires_capability="email:send", audit=True)
async def send_email(to: str, subject: str, body: str, ctx: ToolContext) -> bool:
    """Send an email. This action is audited."""
    # audit=True: every invocation is written to the audit log with
    # agent_id, run_id, timestamp, and full input/output
    result = await _email_service.send(to=to, subject=subject, body=body)
    return result.success


# --- Synchronous tool (automatically wrapped in run_in_executor) ---
@tool(sync=True)
def compute_embedding(text: str) -> list[float]:
    """CPU-bound embedding computation — runs in a thread pool."""
    return embedding_model.encode(text).tolist()
```

### Tool with Pydantic Input/Output Schemas

The `tool` decorator automatically generates the JSON Schema for function-calling from the Pydantic input model or from the function signature (using type annotations). No manual schema writing required.

```python
class CodeExecutionInput(BaseModel):
    code: str
    language: str = "python"
    timeout_seconds: int = 30
    allowed_imports: list[str] = []

class CodeExecutionOutput(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: float

@tool(
    requires_capability="code:execute",
    sandbox=True,       # run in Docker container
    audit=True,
    timeout_seconds=60,
)
async def execute_code(input: CodeExecutionInput) -> CodeExecutionOutput:
    """Execute code in a sandboxed environment. Returns stdout, stderr, and exit code."""
    result = await _sandbox.run(
        code=input.code,
        language=input.language,
        timeout=input.timeout_seconds,
    )
    return CodeExecutionOutput(
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.exit_code,
        duration_ms=result.duration_ms,
    )
```

### MCP Tool Integration

```python
from orchestra.tools.mcp import MCPServer, MCPClient

# Connect to an MCP server and auto-discover its tools
mcp_server = MCPServer(
    name="filesystem-tools",
    url="http://localhost:3000",   # MCP server URL
    # or: command=["npx", "@modelcontextprotocol/server-filesystem", "/workspace"]
)

# Tools from the MCP server are automatically available in the tool registry
# and can be referenced by name in agent definitions
await mcp_server.connect()
available_tools = await mcp_server.list_tools()
# -> ["read_file", "write_file", "list_directory", "search_files"]

# Use MCP tools in an agent
@agent(
    model="claude-opus-4-6",
    tools=["filesystem-tools/read_file", "filesystem-tools/write_file"],  # namespace:tool_name
)
async def file_editor(task: str) -> str:
    """Edit files to complete the given task."""

# Or mount all tools from an MCP server
@agent(
    model="gpt-4o",
    mcp_servers=[mcp_server],   # auto-mount all tools from this server
)
async def filesystem_agent(task: str) -> str:
    """Complete filesystem tasks."""


# Multiple MCP servers
class DataAgent(Agent):
    role: ClassVar[str] = "Data Engineer"
    model: ClassVar[str] = "gpt-4o"
    mcp_servers: ClassVar[list] = [
        MCPServer("postgres-tools", url="http://localhost:3001"),
        MCPServer("s3-tools",       url="http://localhost:3002"),
    ]
```

### Tool Registry

```python
from orchestra.tools import ToolRegistry, ToolPermission

# The global registry (auto-populated by @tool decorator)
registry = ToolRegistry.default()

# List all registered tools
for tool_name, tool_spec in registry.list():
    print(f"{tool_name}: {tool_spec.description}")

# Register a tool manually (without decorator)
registry.register(
    name="custom_tool",
    fn=my_async_function,
    description="Does something custom",
    requires_capability="custom:use",
)

# Tool permissions
permission = ToolPermission(
    tool_name="web_search",
    max_calls_per_run=50,
    allowed_domains=["*.wikipedia.org", "*.arxiv.org"],
    denied_domains=["*.competitor.com"],
)

# Apply permissions to a specific agent in a workflow
compiled = graph.compile()
compiled.grant_tool_permission(agent="researcher", permission=permission)
```

---

## Section 6: LLM Provider API

### Provider Abstraction

Every LLM provider implements the `LLMProvider` Protocol. Users never interact with providers directly — the framework routes calls through the appropriate provider based on the agent's `model` and `provider` fields.

```python
from typing import Protocol, AsyncIterator, runtime_checkable
from orchestra.providers import ChatMessage, ChatCompletion, StreamChunk

@runtime_checkable
class LLMProvider(Protocol):
    """Protocol all LLM providers must implement."""

    async def complete(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float,
        max_tokens: int | None,
        tools: list[dict] | None,
        **kwargs,
    ) -> ChatCompletion: ...

    async def stream(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float,
        max_tokens: int | None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]: ...

    async def embed(self, texts: list[str], model: str) -> list[list[float]]: ...
```

### Configuring Providers

```python
from orchestra.providers import configure_providers, OpenAIProvider, AnthropicProvider

# Global provider configuration (at application startup)
configure_providers(
    openai=OpenAIProvider(
        api_key=os.environ["OPENAI_API_KEY"],
        default_model="gpt-4o-mini",
        organization_id=os.environ.get("OPENAI_ORG_ID"),
        base_url=None,   # override for Azure OpenAI or local proxies
        timeout=30,
        max_retries=3,
    ),
    anthropic=AnthropicProvider(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        default_model="claude-haiku-3",
    ),
    google=GoogleProvider(
        api_key=os.environ["GOOGLE_API_KEY"],
        project_id=os.environ.get("GOOGLE_PROJECT_ID"),
    ),
    # Local models via Ollama
    ollama=OllamaProvider(
        base_url="http://localhost:11434",
        default_model="llama3.2",
    ),
)

# Or use environment-based auto-configuration
from orchestra.providers import auto_configure
auto_configure()   # reads OPENAI_API_KEY, ANTHROPIC_API_KEY, etc. from environment
```

### Switching Models Per Agent

```python
# Per-agent model specification
class FastAgent(Agent):
    model: ClassVar[str] = "gpt-4o-mini"        # cheap, fast

class DeepAgent(Agent):
    model: ClassVar[str] = "claude-opus-4-6"    # expensive, capable

# Or with full provider qualification
class HybridAgent(Agent):
    model: ClassVar[str] = "openai/gpt-4o"      # explicit provider prefix

# Decorator style
@agent(model="anthropic/claude-haiku-3", temperature=0.1)
async def fast_classifier(text: str) -> str:
    """Classify the sentiment quickly."""

# Override model at runtime (for A/B testing or cost experiments)
result = await run(
    compiled,
    input={"query": "..."},
    model_overrides={"researcher": "gpt-4o-mini"},  # override specific agents
)
```

### Intelligent Cost Router

The cost router automatically selects the cheapest model that can handle the task's complexity. Users opt in per-agent or globally.

```python
from orchestra.providers import CostRouter, ModelTier

# Global cost routing
configure_providers(
    cost_router=CostRouter(
        budget_per_run_usd=1.00,        # hard limit per workflow run
        budget_per_agent_usd=0.25,      # hard limit per agent call
        routing_strategy="complexity",  # "complexity" | "speed" | "quality"
        tiers=[
            ModelTier(
                name="fast",
                models=["gpt-4o-mini", "claude-haiku-3"],
                max_complexity=0.4,     # 0.0-1.0 complexity score
            ),
            ModelTier(
                name="standard",
                models=["gpt-4o", "claude-sonnet-4-6"],
                max_complexity=0.75,
            ),
            ModelTier(
                name="premium",
                models=["gpt-4o", "claude-opus-4-6"],
                max_complexity=1.0,
            ),
        ],
    )
)

# Per-agent cost routing opt-in
class SmartAgent(Agent):
    model: ClassVar[str] = "auto"   # "auto" signals cost router to choose
    cost_router: ClassVar[CostRouter] = CostRouter(
        budget_per_run_usd=0.10,
        routing_strategy="complexity",
    )
```

### Streaming API

```python
from orchestra import stream_run

# Stream execution events
async for event in stream_run(compiled, input={"query": "..."}):
    if event.type == "agent.token":
        print(event.token, end="", flush=True)
    elif event.type == "agent.complete":
        print(f"\n[{event.agent_name} completed in {event.duration_ms}ms]")
    elif event.type == "tool.call":
        print(f"[Calling tool: {event.tool_name}]")
    elif event.type == "workflow.complete":
        final_result = event.result
        break

# Stream with type filtering
async for token in stream_run(compiled, input={"query": "..."}, filter="tokens"):
    print(token, end="", flush=True)
```

### Cost Tracking

```python
from orchestra import get_run

run = await get_run(run_id)

# Cost summary
cost = run.cost
print(f"Total cost: ${cost.total_usd:.4f}")
print(f"Input tokens: {cost.total_input_tokens}")
print(f"Output tokens: {cost.total_output_tokens}")

# Per-agent breakdown
for agent_name, agent_cost in cost.by_agent.items():
    print(f"  {agent_name}: ${agent_cost.total_usd:.4f} "
          f"({agent_cost.input_tokens}in / {agent_cost.output_tokens}out)")

# Per-model breakdown
for model, model_cost in cost.by_model.items():
    print(f"  {model}: ${model_cost.total_usd:.4f}")
```

---

## Section 7: Execution API

### Synchronous Execution

```python
from orchestra import run_sync

# Synchronous wrapper for use in non-async contexts (scripts, Jupyter notebooks)
result = run_sync(compiled, input={"query": "quantum computing"})
print(result.output)
print(result.cost.total_usd)
```

### Async Execution

```python
from orchestra import run
import asyncio

async def main():
    result = await run(
        compiled,
        input={"query": "quantum computing"},
        run_id="my-custom-run-id",     # optional — auto-generated if omitted
        config={
            "max_turns": 30,
            "timeout_seconds": 120,
            "tags": ["production", "user:alice"],
        },
    )

    print(result.output)          # final agent output
    print(result.state)           # full final state
    print(result.trace)           # execution trace (all spans)
    print(result.cost)            # cost breakdown
    print(result.run_id)          # run identifier for retrieval
    print(result.duration_ms)     # total wall-clock time

asyncio.run(main())
```

### Streaming Execution (SSE)

```python
from orchestra import stream_run

async def stream_workflow(query: str):
    async for event in stream_run(compiled, input={"query": query}):
        match event.type:
            case "workflow.start":
                yield f"data: {{'type': 'start', 'run_id': '{event.run_id}'}}\n\n"
            case "agent.start":
                yield f"data: {{'type': 'agent_start', 'agent': '{event.agent_name}'}}\n\n"
            case "agent.token":
                yield f"data: {{'type': 'token', 'content': '{event.token}'}}\n\n"
            case "agent.complete":
                yield f"data: {{'type': 'agent_done', 'agent': '{event.agent_name}'}}\n\n"
            case "tool.call":
                yield f"data: {{'type': 'tool_call', 'tool': '{event.tool_name}'}}\n\n"
            case "workflow.complete":
                yield f"data: {{'type': 'done', 'result': {event.result.model_dump_json()}}}\n\n"

# In a FastAPI route:
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()

@app.post("/run")
async def run_workflow(request: RunRequest):
    return StreamingResponse(
        stream_workflow(request.query),
        media_type="text/event-stream",
    )
```

### Human-in-the-Loop (Interrupt / Resume)

```python
from orchestra import WorkflowGraph, run, resume
from orchestra.graph import HumanReviewNode

# Method 1: Interrupt before a specific node
compiled = graph.compile(
    interrupt_before=["final_decision"],   # pause before this node runs
)

# Run until the interrupt
result = await run(compiled, input={"proposal": "..."})
# result.status == "interrupted"
# result.interrupt_point == "final_decision"

# Human inspects the state
print(result.state.draft_decision)  # see what the AI decided

# Resume with or without modification
final = await resume(
    run_id=result.run_id,
    state_override={"human_approved": True, "reviewer_notes": "Looks good"},
)

# Method 2: HumanReviewNode — explicitly placed in the graph
graph = (
    WorkflowGraph()
    .then(proposal_agent)
    .add_node("review", HumanReviewNode(
        prompt="Please review the proposal and approve or reject it.",
        input_display=lambda state: state.proposal,
        timeout_hours=24,            # auto-escalate after 24 hours
        escalate_to="manager_review", # escalation node on timeout
    ))
    .add_edge("proposal_agent", "review")
    .if_then(
        condition=lambda state: state.human_decision == "approved",
        then=execution_agent,
        otherwise=revision_agent,
    )
)

# Method 3: Programmatic interrupt from within an agent
class ReviewAgent(Agent):
    async def after_run(self, output, context: ExecutionContext):
        if output.confidence < 0.7:
            # Request human input before proceeding
            await context.request_human_input(
                message=f"Low confidence ({output.confidence:.0%}). Please verify.",
                data={"draft": output.content},
            )
        return output
```

### Batch Execution

```python
from orchestra import batch_run

# Run the same workflow with multiple inputs in parallel
inputs = [
    {"query": "topic A"},
    {"query": "topic B"},
    {"query": "topic C"},
]

results = await batch_run(
    compiled,
    inputs=inputs,
    max_concurrency=3,    # run up to 3 at a time
    fail_fast=False,      # continue even if some fail
)

for i, result in enumerate(results):
    if result.success:
        print(f"Input {i}: {result.output}")
    else:
        print(f"Input {i} failed: {result.error}")

# Batch with progress tracking
async for progress in batch_run(compiled, inputs=inputs, stream_progress=True):
    print(f"Completed {progress.completed}/{progress.total}")
```

---

## Section 8: Testing API

Orchestra's testing API is the most differentiated feature in the ecosystem. The goal is: agent workflows should be as testable as regular Python code.

### ScriptedLLM — Deterministic Unit Tests

`ScriptedLLM` returns pre-defined responses in sequence. No network calls. Fully deterministic. Runs in milliseconds.

```python
import pytest
from orchestra.testing import ScriptedLLM, script

# Define a script: a list of (input_contains, response) pairs
research_script = script([
    # (match condition, response to return)
    ("research", "Key finding: quantum computers use qubits instead of bits."),
    ("summarize", "Summary: Quantum computing leverages quantum mechanics for computation."),
    # Fallback for unmatched inputs
    script.fallback("I don't know about that."),
])

@pytest.mark.asyncio
async def test_research_workflow():
    compiled = research_graph.compile()

    with ScriptedLLM(script=research_script):
        result = await run(compiled, input={"query": "quantum computing"})

    assert result.success
    assert "qubit" in result.state.findings[0]
    assert result.cost.total_usd == 0.0   # ScriptedLLM has zero cost


# Script by agent name (when different agents need different scripts)
multi_agent_script = script({
    "researcher": [
        ("*", "Research finding: ..."),  # * matches any input
    ],
    "writer": [
        ("*", "Draft report: ..."),
    ],
    "editor": [
        ("*", "Final report: ..."),
    ],
})

@pytest.mark.asyncio
async def test_full_pipeline():
    with ScriptedLLM(script=multi_agent_script):
        result = await run(compiled_pipeline, input={"topic": "AI"})

    assert result.state.final_report != ""


# Script with tool call simulation
tool_script = script([
    script.tool_call(
        trigger="search",              # response that triggers a tool call
        tool="web_search",
        tool_input={"query": "quantum computing"},
        tool_output=[{"url": "https://example.com", "snippet": "Quantum computing is..."}],
        after_tool="Based on my research: ...",  # response after tool result
    ),
])

@pytest.mark.asyncio
async def test_agent_uses_search_tool():
    with ScriptedLLM(script=tool_script) as llm:
        result = await run(compiled, input={"query": "..."})

    assert llm.tool_calls[0].tool_name == "web_search"
    assert "quantum" in llm.tool_calls[0].input["query"]
```

### FlakyLLM — Chaos Testing

```python
from orchestra.testing import FlakyLLM, Failure

@pytest.mark.asyncio
async def test_workflow_retries_on_timeout():
    """Verify the workflow retries when the LLM times out."""
    with FlakyLLM(
        failures=[
            Failure.timeout(on_call=1),             # first call times out
            Failure.timeout(on_call=2),             # second call times out
            # third call succeeds (real script kicks in)
        ],
        fallback_script=research_script,
    ) as llm:
        result = await run(compiled, input={"query": "..."})

    assert result.success
    assert llm.call_count == 3   # failed twice, succeeded on third

@pytest.mark.asyncio
async def test_workflow_handles_provider_error():
    """Verify graceful degradation when provider returns 500."""
    with FlakyLLM(failures=[Failure.provider_error(on_call=1, status=500)]):
        with pytest.raises(ProviderError) as exc_info:
            await run(compiled_no_retry, input={"query": "..."})

    assert exc_info.value.status_code == 500

@pytest.mark.asyncio
async def test_workflow_handles_partial_response():
    """Verify the workflow handles truncated LLM responses."""
    with FlakyLLM(failures=[Failure.truncated_response(on_call=1, truncate_at=50)]):
        result = await run(compiled, input={"query": "..."})
    # Workflow should handle the truncated response gracefully
    assert result.success or result.error_type == "OutputValidationError"
```

### SimulatedLLM — Cheap Integration Tests

`SimulatedLLM` routes to a real but cheap model with seed and temperature=0 for reproducibility. Suitable for CI pipeline integration tests.

```python
from orchestra.testing import SimulatedLLM

@pytest.mark.asyncio
@pytest.mark.integration   # mark as integration test — skip in fast CI
async def test_research_quality():
    """Test that the research workflow produces coherent output."""
    with SimulatedLLM(
        model="gpt-4o-mini",     # cheap model
        seed=42,                 # reproducible
        temperature=0.0,         # deterministic
    ):
        result = await run(compiled, input={"query": "Python programming"})

    assert result.success
    assert len(result.state.findings) >= 3
    assert result.state.final_report.strip() != ""
    assert result.cost.total_usd < 0.05  # budget guard
```

### Workflow Assertions

```python
from orchestra.testing import WorkflowAssertion, assert_workflow

@pytest.mark.asyncio
async def test_workflow_structure():
    with ScriptedLLM(script=research_script):
        result = await run(compiled, input={"query": "AI"})

    assertions = WorkflowAssertion(result)

    # Assert on final output
    assertions.output_contains("finding")
    assertions.output_matches_schema(ResearchReport)

    # Assert on state at specific checkpoints
    assertions.state_at("after:researcher").has_field("findings").is_non_empty()
    assertions.state_at("after:writer").has_field("draft").contains("quantum")

    # Assert on execution path
    assertions.agents_ran_in_order("researcher", "writer", "editor")
    assertions.agent_ran("web_search_tool")
    assertions.agent_did_not_run("escalation_agent")  # verify happy path

    # Assert on cost
    assertions.cost_below_usd(0.50)
    assertions.no_cost()  # when using ScriptedLLM

    # Assert on tool calls
    assertions.tool_called("web_search", times=1)
    assertions.tool_called_with("web_search", query_contains="quantum")

    # Assert on timing
    assertions.completed_within_seconds(5)

    assertions.assert_all()   # raises AssertionError with all failures collected


# Fluent shorthand
@pytest.mark.asyncio
async def test_simple():
    with ScriptedLLM(script=research_script):
        await (
            assert_workflow(compiled, input={"query": "AI"})
            .output_matches_schema(ResearchReport)
            .agents_ran_in_order("researcher", "writer")
            .cost_below_usd(0.10)
            .run()
        )
```

### State Inspection at Checkpoints

```python
from orchestra.testing import CheckpointInspector

@pytest.mark.asyncio
async def test_state_evolution():
    with ScriptedLLM(script=research_script) as llm:
        result = await run(compiled, input={"query": "AI"})

    inspector = CheckpointInspector(result)

    # Get state at each checkpoint
    initial_state    = inspector.state_at("initial")
    post_research    = inspector.state_at("after:researcher")
    post_writing     = inspector.state_at("after:writer")
    final_state      = inspector.state_at("final")

    # Verify state evolution
    assert len(initial_state.findings) == 0
    assert len(post_research.findings) > 0
    assert post_writing.draft != ""
    assert final_state.final_report != ""

    # Verify reducers worked correctly in parallel execution
    assert len(final_state.findings) >= 3  # all parallel agents contributed

    # Inspect message history at each point
    assert len(post_research.messages) > len(initial_state.messages)

    # Replay from a checkpoint (for debugging test failures)
    replay_result = await inspector.replay_from("after:researcher")
    assert replay_result.final_report == final_state.final_report  # deterministic
```

### pytest Fixtures

```python
# conftest.py
import pytest
from orchestra.testing import ScriptedLLM, script, WorkflowTestClient

@pytest.fixture
def research_llm():
    """Fixture providing a scripted LLM for research workflow tests."""
    with ScriptedLLM(script=script([
        ("research", "Finding: quantum computing uses qubits."),
        ("write",    "Draft: Quantum computing is a paradigm shift..."),
        ("edit",     "Final: Quantum computing represents..."),
    ])) as llm:
        yield llm

@pytest.fixture
async def test_client():
    """Fixture for testing the Orchestra HTTP API."""
    async with WorkflowTestClient(compiled) as client:
        yield client

# Usage
async def test_with_fixture(research_llm):
    result = await run(compiled, input={"query": "quantum"})
    assert research_llm.call_count == 3
```

---

## Section 9: Observability API

### Enabling Tracing

```python
import orchestra
from orchestra.observability import configure_tracing, TraceConfig

# Development: Rich console renderer (default, zero config)
orchestra.configure(
    tracing=TraceConfig(
        backend="console",       # beautiful Rich terminal output
        level="verbose",         # "minimal" | "standard" | "verbose" | "debug"
        show_state_diffs=True,   # show what changed in state after each agent
        show_token_counts=True,  # show input/output tokens per agent
        show_costs=True,         # show cost per agent turn
    )
)

# Production: OpenTelemetry export
orchestra.configure(
    tracing=TraceConfig(
        backend="otlp",
        endpoint="http://jaeger:4318/v1/traces",
        service_name="my-agent-service",
        service_version="1.2.3",
        deployment_environment="production",
        # Optional: also export to LangSmith
        langsmith_api_key=os.environ.get("LANGSMITH_API_KEY"),
    )
)

# Honeycomb
orchestra.configure(
    tracing=TraceConfig(
        backend="otlp",
        endpoint="https://api.honeycomb.io",
        headers={"x-honeycomb-team": os.environ["HONEYCOMB_API_KEY"]},
    )
)

# Datadog
orchestra.configure(
    tracing=TraceConfig(
        backend="otlp",
        endpoint="http://datadog-agent:4318",
    )
)
```

### Console Trace Output Format

The Rich console renderer produces output like this during development:

```
Orchestra Run: run_abc123
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  workflow.run [gpt-4o]                          2.4s  $0.0142
  ├─ agent.turn: query_planner                  0.3s  $0.0021
  │     llm.complete [gpt-4o-mini]              0.2s  524→87 tokens
  │     State: query → "quantum computing advances"
  │
  ├─ [PARALLEL] research fan-out                1.8s  $0.0098
  │   ├─ agent.turn: researcher_1               1.8s  $0.0033
  │   │     tool.call: web_search               0.4s  ✓
  │   │     tool.call: read_document            0.6s  ✓
  │   │     llm.complete [gpt-4o]               0.7s  2104→312 tokens
  │   │     State: findings += [3 items]
  │   │
  │   ├─ agent.turn: researcher_2               1.6s  $0.0031
  │   │     tool.call: arxiv_search             0.5s  ✓
  │   │     llm.complete [gpt-4o]               1.0s  1876→287 tokens
  │   │     State: findings += [2 items]
  │   │
  │   └─ agent.turn: researcher_3               1.2s  $0.0034
  │         tool.call: web_search               0.3s  ✓
  │         llm.complete [gpt-4o]               0.8s  1943→301 tokens
  │         State: findings += [4 items]
  │
  └─ agent.turn: synthesizer                    0.3s  $0.0023
        llm.complete [gpt-4o]                   0.2s  3102→445 tokens
        State: final_report ← "Quantum computing..."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total: 2.4s | 5 agents | 3 tool calls | $0.0142 | 9,549 tokens
```

### Programmatic Trace Access

```python
from orchestra import get_run

run = await get_run("run_abc123")

# Full trace tree
trace = run.trace
for span in trace.spans:
    print(f"{span.name}: {span.duration_ms}ms")

# Specific agent span
researcher_span = trace.get_span("agent.turn:researcher")
print(researcher_span.attributes["gen_ai.usage.input_tokens"])

# Export trace
trace.export_json("trace.json")           # OpenTelemetry JSON format
trace.export_html("trace.html")           # interactive HTML visualization
trace.export_jaeger("trace.jaeger.json")  # Jaeger import format

# Time-travel: replay to a specific point
await run.replay_to("after:researcher_agent")
state_at_that_point = run.current_state
```

### Custom Span Attributes

```python
from orchestra.observability import span_attribute, emit_event

class AnalyticsAgent(Agent):
    async def after_run(self, output, context: ExecutionContext):
        # Add custom attributes to the current span
        context.span.set_attribute("analysis.confidence", output.confidence)
        context.span.set_attribute("analysis.data_points", len(output.data_points))

        # Emit a custom event within the span
        context.emit_event("analysis.complete", {
            "confidence": output.confidence,
            "model": self.model,
        })

        return output
```

### Cost Dashboard

```python
from orchestra.observability import CostDashboard

# Get cost breakdown across all runs in a time range
dashboard = CostDashboard()

summary = await dashboard.summary(
    from_date="2026-03-01",
    to_date="2026-03-05",
    group_by=["workflow", "agent", "model"],
)

print(f"Total spend: ${summary.total_usd:.2f}")
print(f"Average per run: ${summary.avg_per_run:.4f}")
print(f"Most expensive workflow: {summary.top_workflow.name}")
print(f"Most expensive model: {summary.top_model.name}")

# Budget alerts
from orchestra.observability import BudgetAlert

BudgetAlert.configure(
    daily_budget_usd=10.00,
    alert_at_pct=80,               # alert at 80% of budget
    on_alert=lambda pct, used: send_slack_alert(f"LLM budget at {pct}%: ${used:.2f}"),
    on_exceeded=lambda: disable_expensive_models(),
)
```

---

## Section 10: Error Handling API

### Error Hierarchy

```python
# orchestra/exceptions.py

class OrchestraError(Exception):
    """Base exception for all Orchestra errors."""
    run_id: str | None = None
    agent_name: str | None = None
    recoverable: bool = False


# Graph construction errors
class GraphError(OrchestraError):
    """Raised during graph.compile() for structural problems."""

class GraphCompileError(GraphError):
    """Unreachable nodes, missing reducers, type mismatches."""
    issues: list[str]  # all issues found, not just the first

class CycleWithoutGuardError(GraphCompileError):
    """Cycle detected with no max_turns/max_iterations guard."""
    cycle_path: list[str]  # the nodes in the cycle


# Agent execution errors
class AgentError(OrchestraError):
    """Raised when an agent fails during execution."""
    recoverable: bool = True  # most agent errors can be retried

class AgentTimeoutError(AgentError):
    """Agent exceeded its time limit."""
    timeout_seconds: float

class OutputValidationError(AgentError):
    """Agent output failed Pydantic validation."""
    raw_output: str
    validation_errors: list[str]
    recoverable: bool = True   # can retry with a corrective prompt


# Tool errors
class ToolError(OrchestraError):
    """Raised when a tool fails."""
    tool_name: str

class ToolPermissionError(ToolError):
    """Agent attempted to call a tool it is not authorized for."""
    agent_name: str
    required_capability: str
    recoverable: bool = False  # permission errors should not be retried

class ToolTimeoutError(ToolError):
    """Tool exceeded its time limit."""
    recoverable: bool = True

class ToolRateLimitError(ToolError):
    """Tool rate limit exceeded."""
    retry_after_seconds: float
    recoverable: bool = True


# Provider errors
class ProviderError(OrchestraError):
    """Raised when an LLM provider returns an error."""
    provider: str
    model: str
    status_code: int | None

class RateLimitError(ProviderError):
    """Provider rate limit exceeded."""
    retry_after_seconds: float
    recoverable: bool = True

class ContextWindowError(ProviderError):
    """Input exceeds the model's context window."""
    context_length: int
    max_context_length: int
    recoverable: bool = False  # requires prompt truncation, not a simple retry


# State errors
class StateError(OrchestraError):
    """Raised when state management fails."""

class StateConflictError(StateError):
    """Parallel agents wrote to the same field without a reducer."""
    field_name: str
    conflicting_agents: list[str]
    recoverable: bool = False  # requires developer intervention

class CheckpointError(StateError):
    """Checkpoint read/write failed."""
    recoverable: bool = True
```

### Retry Policies

```python
from orchestra.retry import RetryPolicy, RetryCondition

# Simple fixed retry
retry = RetryPolicy(max_attempts=3)

# Exponential backoff with jitter
retry = RetryPolicy(
    max_attempts=5,
    backoff="exponential",
    initial_delay_ms=500,
    max_delay_ms=30_000,
    jitter=True,          # add random jitter to prevent thundering herd
)

# Conditional retry (only retry specific error types)
retry = RetryPolicy(
    max_attempts=3,
    retry_on=[RateLimitError, ToolTimeoutError, AgentTimeoutError],
    do_not_retry_on=[ToolPermissionError, ContextWindowError, GraphError],
)

# Custom retry condition
retry = RetryPolicy(
    max_attempts=3,
    condition=RetryCondition(
        fn=lambda error, attempt: (
            isinstance(error, ProviderError) and
            error.status_code in [429, 500, 502, 503] and
            attempt < 3
        )
    ),
)

# With corrective prompt on OutputValidationError
retry = RetryPolicy(
    max_attempts=3,
    on_output_validation_error=RetryWithCorrectionPrompt(
        prompt="Your previous response did not match the required format. "
               "Please try again. Error: {error}. "
               "Required schema: {schema}"
    ),
)

# Apply to agent class
class RobustAgent(Agent):
    retry_policy: ClassVar[RetryPolicy] = RetryPolicy(
        max_attempts=3,
        backoff="exponential",
        retry_on=[RateLimitError, AgentTimeoutError],
    )

# Apply globally in graph compile
compiled = graph.compile(
    default_retry_policy=RetryPolicy(max_attempts=2, backoff="linear"),
)

# Apply to a specific node in the graph
graph.add_node("fragile_agent", fragile_agent, retry_policy=RetryPolicy(max_attempts=5))
```

### Fallback Agents

```python
from orchestra.graph import fallback

# If the primary agent fails, fall back to a simpler agent
graph = (
    WorkflowGraph()
    .then(
        complex_reasoning_agent,
        fallback=simple_agent,          # runs if complex_agent raises an unrecoverable error
    )
    .then(writer)
)

# Fallback chain
graph = (
    WorkflowGraph()
    .then(
        premium_agent,                          # try first
        fallback=standard_agent,               # fall back to this
        fallback_of_fallback=basic_agent,      # last resort
    )
    .then(writer)
)

# Fallback with state annotation
async def mark_as_degraded(state: WorkflowState) -> WorkflowState:
    return state.copy(update={"degraded_mode": True})

graph = (
    WorkflowGraph()
    .then(
        premium_agent,
        fallback=basic_agent,
        on_fallback=mark_as_degraded,   # modify state when falling back
    )
)

# Explicit fallback node in graph
graph = WorkflowGraph()
graph.add_node("premium",     premium_agent)
graph.add_node("basic",       basic_agent)
graph.add_node("synthesizer", synthesizer)
graph.add_edge("premium",    "synthesizer")
graph.add_edge("basic",      "synthesizer")
graph.set_fallback("premium", "basic")   # if "premium" fails, run "basic" instead
```

### Graceful Degradation

```python
from orchestra import WorkflowGraph
from orchestra.error import on_error, ErrorPolicy

# Global error policy for the workflow
compiled = graph.compile(
    error_policy=ErrorPolicy(
        on_agent_error="continue",          # "continue" | "abort" | "fallback"
        on_tool_error="retry",              # "retry" | "skip" | "abort"
        on_provider_rate_limit="wait",      # "wait" | "fallback_model" | "abort"
        on_provider_error="fallback_model", # try the next model in the tier
        max_degradation_depth=2,            # how many fallbacks deep we'll go
    )
)

# Per-node error handling
graph.add_node(
    "optional_enrichment",
    enrichment_agent,
    on_error=ErrorPolicy(
        strategy="skip",                    # if enrichment fails, skip it
        emit_warning=True,                  # log a warning
        state_patch={"enrichment_failed": True},  # mark in state
    )
)

# Error callbacks
compiled = graph.compile(
    on_error=lambda error, context: alert_ops_team(error),
    on_warning=lambda warning, context: log_warning(warning),
)

# Catch errors in run()
from orchestra import run
from orchestra.exceptions import OrchestraError, AgentError

try:
    result = await run(compiled, input={"query": "..."})
except AgentError as e:
    print(f"Agent {e.agent_name} failed in run {e.run_id}: {e}")
    if e.recoverable:
        # Resume from last checkpoint
        result = await resume(e.run_id, state_override={"retry_count": 1})
except OrchestraError as e:
    print(f"Unrecoverable error: {e}")
    # Inspect partial state
    partial_run = await get_run(e.run_id)
    print(partial_run.state)
```

---

## Appendix A: Complete API Surface Reference

### Top-Level Imports

```python
# Core
from orchestra import (
    Agent,           # Base class for class-based agents
    agent,           # Decorator for decorator-based agents
    WorkflowGraph,   # Graph builder
    run,             # Async run
    run_sync,        # Sync run
    stream_run,      # Streaming run
    resume,          # Resume an interrupted run
    batch_run,       # Batch execution
    get_run,         # Retrieve a run by ID
    load_agent,      # Load agent from YAML
    load_workflow,   # Load workflow from YAML
)

# Graph patterns
from orchestra.graph import (
    AgentNode,
    FunctionNode,
    DynamicNode,
    SubgraphNode,
    HumanReviewNode,
    join,
    handoff,
    fallback,
)

# State
from orchestra.state import (
    WorkflowState,
    merge_list,
    merge_set,
    merge_dict,
    last_write_wins,
    concat_str,
    sum_numbers,
    keep_first,
    max_value,
    min_value,
)

# Tools
from orchestra.tools import (
    tool,
    ToolContext,
    ToolRegistry,
    ToolPermission,
)

from orchestra.tools.mcp import (
    MCPServer,
    MCPClient,
)

# Providers
from orchestra.providers import (
    configure_providers,
    auto_configure,
    OpenAIProvider,
    AnthropicProvider,
    GoogleProvider,
    OllamaProvider,
    CostRouter,
    ModelTier,
)

# Testing
from orchestra.testing import (
    ScriptedLLM,
    FlakyLLM,
    SimulatedLLM,
    script,
    Failure,
    WorkflowAssertion,
    assert_workflow,
    CheckpointInspector,
)

# Observability
from orchestra.observability import (
    configure_tracing,
    TraceConfig,
    CostDashboard,
    BudgetAlert,
)

# Exceptions
from orchestra.exceptions import (
    OrchestraError,
    GraphError,
    GraphCompileError,
    CycleWithoutGuardError,
    AgentError,
    AgentTimeoutError,
    OutputValidationError,
    ToolError,
    ToolPermissionError,
    ToolTimeoutError,
    ToolRateLimitError,
    ProviderError,
    RateLimitError,
    ContextWindowError,
    StateError,
    StateConflictError,
    CheckpointError,
)

# Retry
from orchestra.retry import RetryPolicy, RetryCondition, RetryWithCorrectionPrompt

# Memory
from orchestra.memory import MemoryConfig

# Context
from orchestra.context import ExecutionContext

# Guardrails
from orchestra.guardrails import PIIGuardrail, ContentSafetyGuardrail, CostLimitGuardrail
```

---

## Appendix B: Design Decision Log

| Decision | Chosen Approach | Rejected Alternatives | Rationale |
|---|---|---|---|
| Agent definition | Three styles (class/decorator/YAML) | Single style | Supports prototyping → production progression without rewrite |
| State model | Pydantic + `Annotated` reducers | TypedDict (LangGraph) | Better IDE support, runtime validation, serialization |
| Parallel fan-in ordering | Alphabetical by agent name | Non-deterministic / timestamp | Reproducible state for debugging and testing |
| Tool schema generation | Auto-generated from type annotations | Manual JSON Schema | DRY — annotations are the single source of truth |
| Loop safety guard | Required `max_iterations` | Optional | Silent infinite loops are a production failure mode; making the guard required prevents it at compile time |
| HITL mechanism | `interrupt_before/after` + `HumanReviewNode` | Out-of-band webhook | Keeps HITL in the graph definition, visible to all operators |
| Error recovery | `RetryPolicy` + `fallback` node + `ErrorPolicy` | Single retry count | Different errors require different strategies; one parameter is not expressive enough |
| Testing | `ScriptedLLM` / `FlakyLLM` / `SimulatedLLM` | pytest-mock | LLM-specific mocking semantics (scripts, tool call simulation) require purpose-built mocks |
| Trace storage | SQLite (dev) / PostgreSQL (prod) | External trace service only | Zero-infrastructure requirement; can export to OTel backends at any time |
| Dynamic graphs | `DynamicNode` as first-class node type | User-implemented workaround | Runtime graph mutation is a common pattern (plan-and-execute); it should be a first-class primitive |
| Routing | Three mechanisms (Python fn, `route_on_output`, `handoff`) | One mechanism | Each serves a different use case; forcing one mechanism means one will always be awkward |

---

## Appendix C: API Stability Guarantees

| API Layer | Stability | Notes |
|---|---|---|
| `WorkflowGraph` builder methods | Stable | No breaking changes without major version bump |
| `Agent` base class fields | Stable | New `ClassVar` fields may be added (backward compatible) |
| `@agent` decorator signature | Stable | New optional kwargs may be added |
| `WorkflowState` + reducers | Stable | New built-in reducers may be added |
| `@tool` decorator | Stable | |
| `run` / `run_sync` / `stream_run` signatures | Stable | |
| `ScriptedLLM` / `FlakyLLM` / `SimulatedLLM` | Stable | |
| `LLMProvider` Protocol | Stable | Adding methods requires a deprecation cycle |
| `AgentSpec` (internal) | Unstable | Not part of public API; subject to change |
| `ExecutionContext` fields | Semi-stable | Fields may be added; existing fields stable |
| Error hierarchy | Stable | New error subclasses may be added |
| YAML schema | Stable after 1.0 | |
| `DynamicNode` / `SubgraphSpec` | Beta | May change before 1.0 |
