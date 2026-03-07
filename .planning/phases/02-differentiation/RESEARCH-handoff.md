# Research: Handoff Protocol Patterns

**Research Date:** 2026-03-07
**Phase:** 2 - Differentiation
**Confidence:** HIGH

---

## 1. OpenAI Swarm / Agents SDK Handoff Pattern

### Swarm (Original)
- Handoff is a **function return** — an agent function returns another agent to transfer control
- `return Agent(name="specialist")` triggers a handoff
- Context (conversation history) is passed entirely to the target agent
- No persistence, no events, no observability — purely in-memory transfer

### OpenAI Agents SDK (Production Evolution)
The Agents SDK evolved Swarm's pattern with a `Handoff` class:

```python
from agents import Agent, Handoff

triage = Agent(
    name="triage",
    handoffs=[
        Handoff(
            agent=billing_agent,
            tool_name_override="transfer_to_billing",
            on_handoff=lambda ctx: update_context(ctx),
            input_filter=lambda input: filter_messages(input, n=10),
            is_enabled=lambda ctx: ctx.context.get("needs_billing"),
        )
    ],
)
```

Key features:
- **`on_handoff` callback** — runs before transfer (e.g., log reason, transform state)
- **`input_filter`** — controls what context the target agent receives (e.g., last N messages, summary)
- **`is_enabled`** — dynamically enable/disable handoff based on state
- **`tool_name_override`** — custom function name presented to the LLM
- Handoffs are exposed to the LLM as callable functions — the LLM decides when to hand off

### Lessons for Orchestra
- The `input_filter` concept is essential for managing context window limits
- `on_handoff` callback maps to event emission (HandoffInitiated)
- Orchestra's graph-edge approach is more deterministic than LLM-decided handoffs (both should be supported)

---

## 2. LangGraph Handoff Pattern

### Command Primitive
LangGraph uses `Command` for handoffs — an atomic operation combining state update + routing:

```python
def triage_node(state):
    if state["category"] == "billing":
        return Command(
            goto="billing_agent",
            update={"handoff_reason": "Billing inquiry detected"},
        )
    return Command(goto="general_agent")
```

### Characteristics
- Handoffs are **state mutations + routing** (not typed events)
- No explicit `HandoffEvent` — the checkpoint just shows state changed
- Context preserved via state dict (full conversation history is in state)
- The *reason* for handoff is not recorded unless developer adds it to state manually
- No built-in context filtering (entire state transfers)

### Lessons for Orchestra
- `Command` combines update + route atomically — Orchestra's `HandoffEdge` should do the same
- Orchestra's typed `HandoffEvent` is a genuine differentiator (auditable, queryable)
- Orchestra should make the handoff reason mandatory or strongly encouraged

---

## 3. CrewAI Delegation Pattern

### Agent Delegation
- CrewAI supports **LLM-decided delegation** — one agent can delegate tasks to another
- The delegating agent includes delegation instructions in its system prompt
- Non-deterministic — the LLM decides if and when to delegate
- Also supports **A2A protocol** for cross-framework agent communication

### A2A Protocol
- Google's Agent-to-Agent protocol for cross-system communication
- HTTPS/JSON-RPC based — designed for networked agents, not in-process
- Each agent has an "Agent Card" describing capabilities
- Task-based communication: one agent creates a task for another

### Lessons for Orchestra
- Orchestra's in-process handoff is faster and more deterministic than A2A
- A2A is complementary (cross-system) not competitive (intra-workflow)
- A2A compatibility could be a future-phase addition

---

## 4. HandoffEdge Design for Orchestra

### As a First-Class Edge Type
`HandoffEdge` joins the existing edge types: `Edge`, `ConditionalEdge`, `ParallelEdge`.

```python
@dataclass(frozen=True)
class HandoffEdge:
    source: str                          # Source agent node
    target: str                          # Target agent node (or condition -> target map)
    condition: EdgeCondition | None      # Optional: dynamic routing
    path_map: dict[str, str] | None      # Optional: condition result -> target node
    context_policy: str = "full"         # "full" | "last_n" | "summary" | "metadata_only"
    context_n: int = 10                  # For "last_n" policy
    preserve_metadata: bool = True       # Transfer metadata dict
    on_handoff: Callable | None = None   # Optional callback
```

### Builder API
```python
# Explicit API
graph.add_handoff("triage", "billing", condition=is_billing)
graph.add_handoff("triage", "general")  # Default/unconditional

# Fluent API
graph.then(triage).handoff_to(billing, condition=is_billing)
graph.then(triage).handoff_to(general)

# With context policy
graph.add_handoff("triage", "specialist",
    context_policy="last_n", context_n=5,
    condition=needs_expert,
)
```

### Conditional Handoffs
```python
# Route to different agents based on state
graph.add_handoff("triage", condition=classify_intent, path_map={
    "billing": "billing_agent",
    "technical": "tech_agent",
    "general": "general_agent",
})
```

This mirrors `ConditionalEdge` but with handoff-specific context transfer semantics.

---

## 5. Context Preservation Strategies

### Policies
| Policy | Behavior | Use Case |
|--------|----------|----------|
| `full` | Transfer all messages + metadata | Short conversations, full context needed |
| `last_n` | Transfer last N messages + system prompt | Long conversations, context window management |
| `summary` | LLM-generated summary of conversation | Very long conversations, expensive but compact |
| `metadata_only` | Transfer metadata dict only, no messages | Structured handoffs where data is in state fields |
| `custom` | User-provided filter function | Any custom logic |

### Default: `full`
All frameworks default to transferring the full conversation history. Orchestra should do the same, with easy opt-in to filtering.

### Implementation
```python
def _apply_context_policy(
    messages: list[Message],
    policy: str,
    n: int = 10,
    provider: LLMProvider | None = None,
) -> list[Message]:
    if policy == "full":
        return messages
    elif policy == "last_n":
        system = [m for m in messages if m.role == MessageRole.SYSTEM]
        recent = messages[-n:]
        return system + recent
    elif policy == "summary":
        # Use provider to generate summary
        ...
    elif policy == "metadata_only":
        return []  # No messages transferred, just state
```

---

## 6. Handoff Events for Event Store

### Event Types
```python
class HandoffInitiated(WorkflowEvent):
    event_type: Literal["handoff_initiated"] = "handoff_initiated"
    source_agent: str
    target_agent: str
    reason: str | None           # Why the handoff happened
    context_policy: str          # Which context policy was applied
    context_message_count: int   # How many messages were transferred
    condition_result: str | None # What the condition function returned

class HandoffCompleted(WorkflowEvent):
    event_type: Literal["handoff_completed"] = "handoff_completed"
    source_agent: str
    target_agent: str
    duration_ms: float           # Time from initiated to target agent completion
```

### Rich Trace Rendering
```
├── OK triage_agent     0.8s  200 tok  $0.001
│   └── handoff -> billing_agent  (reason: "Billing inquiry")
├── OK billing_agent    2.1s  570 tok  $0.003
```

The handoff appears as a child of the source agent with an arrow indicating the transfer.

---

## 7. Agent-Initiated Handoffs

### Existing Hook: `AgentResult.handoff_to`
The codebase already has `AgentResult.handoff_to: str | None` (types.py line 78). This enables a secondary handoff mechanism where the LLM decides to hand off:

1. Agent's LLM returns a response indicating handoff (via tool call or structured output)
2. Agent sets `result.handoff_to = "specialist"`
3. `CompiledGraph._resolve_next()` checks `result.handoff_to` and routes accordingly

### Validation
- Agent-initiated handoffs should require pre-registration of valid targets at compile time
- `graph.add_handoff("triage", "specialist")` registers "specialist" as a valid handoff target for "triage"
- If `result.handoff_to` returns a name not in the registered targets, raise `GraphCompileError`

---

## 8. Edge Cases

### Handoff from Parallel Branches
- **Recommendation: Forbid.** If a node in a parallel group tries to hand off, raise a clear error
- Parallel branches should complete and merge before handoff decisions
- Error: "Handoff from parallel branch 'analyst_1' is not supported. Complete parallel execution first."

### Handoff Cycles
- A -> B -> A is allowed but needs a cycle guard (max_handoffs or max_turns)
- Track handoff history in `ExecutionContext` for cycle detection
- Default max: 10 handoffs per run (configurable)

### Bidirectional Handoff ("Ask and Return")
- **Recommendation: Don't support directly.** Use `SubgraphNode` for this pattern
- A -> B -> A with return value is better modeled as: A calls a subgraph containing B

---

## 9. Google A2A Protocol Relevance

### What A2A Is
- Cross-system agent communication via HTTPS/JSON-RPC
- Each agent has an "Agent Card" (capabilities manifest)
- Task-based: create task -> monitor progress -> get result
- Designed for networked, cross-framework, cross-organization communication

### Relationship to Orchestra
- **Complementary, not competitive** — A2A handles cross-system; `HandoffEdge` handles intra-workflow in-process
- They could share event types for consistent observability
- A2A compatibility is a future-phase consideration, not Phase 2 scope
- If A2A standardizes broadly, Orchestra should consider an `A2AHandoffEdge` that wraps remote agent calls

---

## 10. Integration Points in Existing Codebase

| File | Integration |
|------|-------------|
| `src/orchestra/core/edges.py` | Add `HandoffEdge` frozen dataclass alongside existing edge types |
| `src/orchestra/core/types.py` | `AgentResult.handoff_to` already exists (line 78) |
| `src/orchestra/core/compiled.py` | `_resolve_next()` handles `HandoffEdge` routing and context transfer |
| `src/orchestra/core/graph.py` | `add_handoff()` explicit method and `.handoff_to()` fluent method |
| `src/orchestra/core/context.py` | Add `handoff_history: list[tuple[str, str]]` for cycle detection |

---

*Research: 2026-03-07*
*Researcher: gsd-phase-researcher agent*
