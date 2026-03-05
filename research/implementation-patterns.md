# Multi-Agent Orchestration Framework: Implementation Patterns Research

**Researched:** 2026-03-05
**Domain:** Multi-agent orchestration framework internals
**Confidence:** MEDIUM (based on training data through early 2025; WebSearch/WebFetch unavailable for live verification)

**Caveat:** This research is derived from training knowledge of framework source code and documentation. Specific API details may have shifted in recent releases. Version numbers and APIs should be verified against current documentation before implementation.

---

## Summary

Multi-agent orchestration frameworks converge on a small set of core patterns, but differ significantly in their philosophy and implementation approach. The five frameworks studied (LangGraph, CrewAI, OpenAI Swarm, AutoGen, and the Anthropic agent patterns) each make different tradeoffs between simplicity, control, and flexibility.

The fundamental architectural choice is between **graph-based orchestration** (LangGraph), **role-based task pipelines** (CrewAI), **lightweight function-routing** (Swarm), and **conversation-centric group chat** (AutoGen). Each approach implies a different state management strategy, communication model, and extension pattern.

**Primary recommendation:** A well-designed orchestration framework should support multiple orchestration patterns (graph, pipeline, dynamic routing) through a unified agent definition model, with pluggable state management and clear inter-agent communication protocols.

---

## 1. Agent Definition Patterns

### 1.1 Class-Based Definition (CrewAI)

**Confidence:** HIGH

CrewAI defines agents as Pydantic model instances with role, goal, backstory, and tool configurations.

```python
# CrewAI Agent Definition Pattern
from crewai import Agent

class Agent(BaseModel):
    """Core fields in CrewAI's Agent class"""
    role: str                          # Agent's role description
    goal: str                          # What the agent aims to achieve
    backstory: str                     # Context for the agent's persona
    llm: Optional[Any] = None         # LLM instance or model name
    tools: List[Any] = []             # Tools the agent can use
    max_iter: int = 25                # Max reasoning iterations
    max_rpm: Optional[int] = None     # Rate limiting
    memory: bool = True               # Whether to use memory
    verbose: bool = False             # Logging verbosity
    allow_delegation: bool = True     # Can delegate to other agents
    step_callback: Optional[Any] = None  # Hook for each step
    cache: bool = True                # Cache tool results

# Usage
researcher = Agent(
    role="Senior Research Analyst",
    goal="Discover groundbreaking insights about AI trends",
    backstory="You are a veteran analyst at a top research firm...",
    tools=[search_tool, scrape_tool],
    llm="gpt-4",
    verbose=True,
)
```

**Strengths:**
- Self-documenting: role/goal/backstory make agent purpose clear
- Validation via Pydantic
- Serializable configuration
- Easy to understand for newcomers

**Weaknesses:**
- Heavy abstraction layer over what is fundamentally a prompt + tools
- Difficult to customize agent reasoning loop
- Role/backstory fields are just prompt engineering with extra steps

---

### 1.2 Function-Based Definition (OpenAI Swarm)

**Confidence:** HIGH

Swarm takes a minimalist approach: an Agent is essentially a named system prompt plus a list of callable functions.

```python
# Swarm Agent Definition Pattern
from dataclasses import dataclass, field
from typing import Callable

@dataclass
class Agent:
    name: str = "Agent"
    model: str = "gpt-4o"
    instructions: Union[str, Callable] = "You are a helpful agent."
    functions: list = field(default_factory=list)
    tool_choice: str = None
    parallel_tool_calls: bool = True

# Usage -- dead simple
triage_agent = Agent(
    name="Triage Agent",
    instructions="Determine which department can help the user.",
    functions=[transfer_to_sales, transfer_to_support],
)

sales_agent = Agent(
    name="Sales Agent",
    instructions="You are a sales agent. Help with purchasing.",
    functions=[check_inventory, place_order],
)

# Dynamic instructions via callable
def instructions_with_context(context_variables):
    user_name = context_variables.get("user_name", "User")
    return f"Help {user_name} with their request. Be concise."

dynamic_agent = Agent(
    name="Personal Agent",
    instructions=instructions_with_context,
)
```

**Strengths:**
- Minimal abstraction -- nearly zero overhead
- Dynamic instructions via callables
- No framework lock-in; easy to understand the full codebase (~300 lines)
- Functions ARE the tools; no separate tool registration

**Weaknesses:**
- No built-in memory, state, or persistence
- No lifecycle hooks beyond function calls
- Not designed for production (explicitly educational)
- No structured output handling

---

### 1.3 Config/Conversation-Based Definition (AutoGen)

**Confidence:** MEDIUM (AutoGen underwent major API changes with v0.4/AG2 fork)

AutoGen defines agents as conversable entities with LLM config and code execution capabilities.

```python
# AutoGen Agent Definition Pattern (v0.2 / pre-AG2 fork)
from autogen import AssistantAgent, UserProxyAgent

# LLM-powered agent
assistant = AssistantAgent(
    name="assistant",
    llm_config={
        "config_list": [
            {"model": "gpt-4", "api_key": "..."},
        ],
        "temperature": 0,
        "cache_seed": 42,        # Deterministic caching
    },
    system_message="You are a helpful AI assistant.",
    max_consecutive_auto_reply=10,
    human_input_mode="NEVER",    # NEVER, ALWAYS, or TERMINATE
)

# Human proxy / code executor
user_proxy = UserProxyAgent(
    name="user_proxy",
    human_input_mode="TERMINATE",
    max_consecutive_auto_reply=5,
    is_termination_msg=lambda x: x.get("content", "").rstrip().endswith("TERMINATE"),
    code_execution_config={
        "work_dir": "coding",
        "use_docker": False,     # or True for sandboxed execution
    },
)

# AutoGen v0.4+ / AG2 uses a different pattern with more explicit agent types
# AgentChat introduces ChatAgent base class
```

**Strengths:**
- Agents are conversation-native; built for multi-turn dialogue
- Code execution built in (Docker sandboxing available)
- Human-in-the-loop is a first-class concept (UserProxyAgent)
- Termination conditions are explicit

**Weaknesses:**
- Agent types proliferated (AssistantAgent, UserProxyAgent, GroupChatManager, etc.)
- Config-heavy; lots of dictionaries
- API instability (major changes between v0.2, v0.4, and AG2 fork)
- Hard to reason about execution flow

---

### 1.4 Decorator-Based Definition

**Confidence:** MEDIUM

Some frameworks and custom implementations use decorators to turn functions into agents.

```python
# Decorator-based agent pattern (composite / representative)
from typing import Any

def agent(name: str, tools: list = None, model: str = "gpt-4"):
    """Decorator that turns a function into an agent definition."""
    def decorator(func):
        func._agent_name = name
        func._agent_tools = tools or []
        func._agent_model = model
        func._agent_instructions = func.__doc__ or ""
        return func
    return decorator

@agent(name="researcher", tools=[web_search])
def research_agent(query: str) -> str:
    """You are a research specialist. Find accurate information
    and cite your sources."""
    pass  # Framework handles execution

@agent(name="writer", tools=[])
def writing_agent(research: str, style: str) -> str:
    """You are a skilled writer. Use the provided research
    to create compelling content."""
    pass  # Framework handles execution

# Anthropic's tool_use pattern is decorator-adjacent:
# Define tools as typed functions, agent uses them via function calling
```

**Strengths:**
- Pythonic and familiar
- Function signature defines input/output contract
- Docstring as system prompt is elegant
- Easy to compose into pipelines

**Weaknesses:**
- Less discoverable than class-based
- Harder to serialize/deserialize
- Limited metadata attachment points
- Testing requires framework awareness

---

### 1.5 DSL-Based Definition

**Confidence:** LOW (less common in mainstream frameworks)

Some systems define agents via YAML/JSON configuration files.

```yaml
# DSL-based agent definition (representative pattern)
agents:
  researcher:
    model: gpt-4
    system_prompt: |
      You are a senior research analyst specializing in
      technology trends. Always cite your sources.
    tools:
      - web_search
      - document_reader
    constraints:
      max_tokens: 4096
      temperature: 0.3
    memory:
      type: vector
      collection: research_memory

  writer:
    model: gpt-4
    system_prompt: |
      You are a professional writer. Transform research
      into clear, engaging content.
    tools:
      - text_editor
    constraints:
      max_tokens: 8192
      temperature: 0.7
    depends_on:
      - researcher

# Workflow definition
workflow:
  type: sequential
  steps:
    - agent: researcher
      task: "Research {topic}"
      output: research_results
    - agent: writer
      task: "Write article using {research_results}"
      output: final_article
```

**Strengths:**
- Non-developers can define agents
- Easy to version control and diff
- Platform-independent
- Can generate UIs automatically from schema

**Weaknesses:**
- Limited expressiveness for complex logic
- Requires a runtime interpreter
- Debugging is harder (indirection layer)
- Custom behaviors need escape hatches back to code

---

### Agent Definition Comparison Matrix

| Pattern | Flexibility | Simplicity | Serializability | Type Safety | Best For |
|---------|-------------|------------|-----------------|-------------|----------|
| Class-based | HIGH | MEDIUM | HIGH | HIGH | Production frameworks |
| Function-based | MEDIUM | HIGH | LOW | MEDIUM | Lightweight/educational |
| Config-based | MEDIUM | LOW | HIGH | LOW | Enterprise/multi-model |
| Decorator-based | MEDIUM | HIGH | LOW | HIGH | Python-native pipelines |
| DSL-based | LOW | HIGH (for users) | HIGH | LOW | No-code/low-code platforms |

---

## 2. Orchestration Engine Patterns

### 2.1 Graph Execution Engine (LangGraph)

**Confidence:** HIGH

LangGraph models orchestration as a directed graph where nodes are processing steps and edges define transitions. This is the most flexible pattern.

```python
# LangGraph StateGraph Pattern
from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated
import operator

# Step 1: Define state schema
class AgentState(TypedDict):
    messages: Annotated[list, operator.add]  # Reducer: append
    next_agent: str
    research_data: str
    draft: str
    iteration_count: int

# Step 2: Define node functions (each is a processing step)
def researcher_node(state: AgentState) -> dict:
    """Node that runs the researcher agent."""
    messages = state["messages"]
    # Call LLM with researcher system prompt
    response = llm.invoke(messages)
    return {
        "messages": [response],          # Appended via reducer
        "research_data": response.content,
        "next_agent": "writer",
    }

def writer_node(state: AgentState) -> dict:
    """Node that runs the writer agent."""
    research = state["research_data"]
    response = llm.invoke([
        SystemMessage("You are a writer..."),
        HumanMessage(f"Write based on: {research}")
    ])
    return {
        "messages": [response],
        "draft": response.content,
        "next_agent": "reviewer",
    }

def reviewer_node(state: AgentState) -> dict:
    """Node that reviews and decides if revision needed."""
    draft = state["draft"]
    response = llm.invoke([
        SystemMessage("Review this draft. Reply APPROVE or REVISE."),
        HumanMessage(draft)
    ])
    approved = "APPROVE" in response.content
    return {
        "messages": [response],
        "next_agent": END if approved else "writer",
        "iteration_count": state["iteration_count"] + 1,
    }

# Step 3: Build the graph
def should_continue(state: AgentState) -> str:
    """Conditional edge: route based on state."""
    if state["iteration_count"] >= 3:
        return END
    return state["next_agent"]

graph = StateGraph(AgentState)

# Add nodes
graph.add_node("researcher", researcher_node)
graph.add_node("writer", writer_node)
graph.add_node("reviewer", reviewer_node)

# Add edges
graph.set_entry_point("researcher")
graph.add_edge("researcher", "writer")         # Always: researcher -> writer
graph.add_conditional_edges(                     # Conditional: reviewer -> ?
    "reviewer",
    should_continue,
    {
        "writer": "writer",                      # Revise
        END: END,                                # Approve
    }
)
graph.add_edge("writer", "reviewer")            # Always: writer -> reviewer

# Step 4: Compile and run
app = graph.compile()
result = app.invoke({
    "messages": [HumanMessage("Write about AI agents")],
    "next_agent": "researcher",
    "research_data": "",
    "draft": "",
    "iteration_count": 0,
})
```

**Key Implementation Details:**

1. **Reducers** control how state updates merge. `Annotated[list, operator.add]` means list fields are appended, not replaced. Without a reducer, the latest value wins.

2. **Conditional edges** use a routing function that returns the name of the next node. This is how dynamic control flow works.

3. **Compile** step validates the graph (checks for unreachable nodes, validates state schema) and returns a `CompiledGraph` that implements the Runnable interface.

4. **Checkpointing** is built into the compiled graph. With a checkpointer (e.g., `SqliteSaver`), every state transition is persisted, enabling:
   - Time travel (replay from any checkpoint)
   - Human-in-the-loop (pause, inspect, resume)
   - Fault tolerance (restart from last checkpoint)

```python
from langgraph.checkpoint.sqlite import SqliteSaver

checkpointer = SqliteSaver.from_conn_string(":memory:")
app = graph.compile(checkpointer=checkpointer)

# Run with thread_id for persistence
config = {"configurable": {"thread_id": "thread-1"}}
result = app.invoke(initial_state, config)

# Later: resume from checkpoint
result = app.invoke(None, config)  # Continues from saved state
```

**Strengths:**
- Maximum flexibility: any topology (DAG, cycles, conditionals)
- State management is explicit and type-safe
- Checkpointing enables persistence, time-travel, HITL
- Streaming support built in
- Can model any other pattern (sequential, hierarchical, etc.)

**Weaknesses:**
- Higher learning curve
- Boilerplate for simple use cases
- Graph definition can become complex
- Debugging graph execution requires tooling

---

### 2.2 Sequential Pipeline (CrewAI Sequential Process)

**Confidence:** HIGH

CrewAI's sequential process executes tasks in order, passing outputs downstream.

```python
# CrewAI Sequential Pipeline Pattern
from crewai import Crew, Task, Agent, Process

# Define agents
researcher = Agent(role="Researcher", goal="...", backstory="...")
writer = Agent(role="Writer", goal="...", backstory="...")
editor = Agent(role="Editor", goal="...", backstory="...")

# Define tasks -- ORDER MATTERS in sequential process
task1 = Task(
    description="Research the topic: {topic}",
    expected_output="Comprehensive research notes with sources",
    agent=researcher,
)

task2 = Task(
    description="Write an article based on the research",
    expected_output="Well-structured article draft",
    agent=writer,
    context=[task1],  # Explicit dependency: gets task1's output
)

task3 = Task(
    description="Edit and polish the article",
    expected_output="Final polished article",
    agent=editor,
    context=[task2],  # Gets task2's output
)

# Orchestrate
crew = Crew(
    agents=[researcher, writer, editor],
    tasks=[task1, task2, task3],
    process=Process.sequential,  # Execute in order
    verbose=True,
)

result = crew.kickoff(inputs={"topic": "AI Agents"})
```

**Internal orchestration loop (simplified):**

```python
# Pseudocode of CrewAI's sequential execution
class Crew:
    def _run_sequential_process(self):
        task_outputs = {}
        for task in self.tasks:
            # Gather context from upstream tasks
            context = ""
            if task.context:
                context = "\n".join(
                    task_outputs[t.id] for t in task.context
                )

            # Build prompt with agent role + task description + context
            prompt = self._build_prompt(task, context)

            # Execute agent (with tool loop)
            result = task.agent.execute_task(
                task=task,
                context=context,
                tools=task.tools or task.agent.tools,
            )

            task_outputs[task.id] = result
            task.output = result

        return task_outputs[self.tasks[-1].id]
```

**Strengths:**
- Simple mental model: A then B then C
- Output chaining is automatic
- Easy to reason about data flow
- Good for linear workflows

**Weaknesses:**
- No parallelism
- No conditional branching
- Rigid: cannot skip steps or loop
- Context window can overflow with long chains

---

### 2.3 Hierarchical Delegation (CrewAI Hierarchical Process)

**Confidence:** MEDIUM

A manager agent dynamically assigns tasks to worker agents.

```python
# CrewAI Hierarchical Process Pattern
from crewai import Crew, Process

crew = Crew(
    agents=[researcher, writer, editor],
    tasks=[research_task, writing_task, editing_task],
    process=Process.hierarchical,
    manager_llm="gpt-4",       # Manager uses this LLM
    # OR
    manager_agent=Agent(        # Custom manager agent
        role="Project Manager",
        goal="Coordinate the team to produce excellent content",
        backstory="You are an experienced project manager...",
    ),
)

result = crew.kickoff()
```

**Internal delegation loop (simplified):**

```python
# Pseudocode of hierarchical delegation
class HierarchicalProcess:
    def execute(self):
        manager = self.manager_agent
        remaining_tasks = list(self.tasks)

        while remaining_tasks:
            # Manager decides which task to work on next
            # and which agent should handle it
            decision = manager.decide(
                remaining_tasks=remaining_tasks,
                available_agents=self.agents,
                completed_results=self.results,
            )

            # Manager can:
            # 1. Assign task to specific agent
            # 2. Provide additional instructions
            # 3. Request collaboration between agents
            result = decision.assigned_agent.execute_task(
                task=decision.task,
                context=decision.context,
            )

            # Manager reviews result
            approval = manager.review(result, decision.task)
            if approval.accepted:
                self.results.append(result)
                remaining_tasks.remove(decision.task)
            else:
                # Manager can reassign or provide feedback
                decision.task.feedback = approval.feedback
```

**Strengths:**
- Dynamic task assignment based on results
- Manager can re-route based on quality
- More flexible than sequential
- Natural metaphor (team with manager)

**Weaknesses:**
- Manager becomes a bottleneck (every decision goes through it)
- More LLM calls (manager reasoning overhead)
- Harder to predict execution path
- Manager agent quality is critical

---

### 2.4 Dynamic Routing / Handoff (OpenAI Swarm)

**Confidence:** HIGH

Swarm uses function returns to transfer control between agents. An agent "hands off" by returning another agent from a tool call.

```python
# Swarm Handoff Pattern
from swarm import Swarm, Agent

client = Swarm()

# Handoff functions -- returning an Agent transfers control
def transfer_to_sales():
    """Transfer the conversation to the sales department."""
    return sales_agent

def transfer_to_support():
    """Transfer the conversation to tech support."""
    return support_agent

def escalate_to_manager():
    """Escalate to a human manager."""
    return manager_agent

# Define agents with handoff functions as tools
triage_agent = Agent(
    name="Triage",
    instructions="Determine user intent. Route to appropriate department.",
    functions=[transfer_to_sales, transfer_to_support, escalate_to_manager],
)

sales_agent = Agent(
    name="Sales",
    instructions="Help users with purchases and pricing.",
    functions=[check_price, place_order, transfer_to_support],
)

support_agent = Agent(
    name="Support",
    instructions="Help users with technical issues.",
    functions=[lookup_order, create_ticket, escalate_to_manager],
)

# Run -- Swarm handles the routing automatically
response = client.run(
    agent=triage_agent,
    messages=[{"role": "user", "content": "I need help with my order"}],
)
```

**Swarm's core run loop (simplified from source):**

```python
# Pseudocode of Swarm's core execution loop
class Swarm:
    def run(self, agent, messages, context_variables={}, max_turns=float("inf")):
        active_agent = agent
        history = list(messages)
        init_len = len(messages)

        while len(history) - init_len < max_turns:
            # 1. Call the LLM with current agent's config
            completion = self.get_chat_completion(
                agent=active_agent,
                history=history,
                context_variables=context_variables,
                model_override=None,
            )

            message = completion.choices[0].message
            history.append(message)

            # 2. If no tool calls, we are done
            if not message.tool_calls:
                break

            # 3. Process each tool call
            for tool_call in message.tool_calls:
                name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)

                # Inject context_variables if the function accepts it
                if "context_variables" in inspect.signature(func).parameters:
                    args["context_variables"] = context_variables

                result = func(**args)

                # 4. KEY: If result is an Agent, perform handoff
                if isinstance(result, Agent):
                    active_agent = result       # <-- THE HANDOFF
                    result = {"assistant": active_agent.name}

                # 5. If result is a Response object, extract updates
                elif isinstance(result, Response):
                    if result.agent:
                        active_agent = result.agent
                    if result.context_variables:
                        context_variables.update(result.context_variables)
                    result = result.value

                # 6. Add tool response to history
                history.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(result),
                })

        return Response(
            messages=history[init_len:],
            agent=active_agent,
            context_variables=context_variables,
        )
```

**Strengths:**
- Extremely simple: ~300 lines of core code
- Handoffs are just function returns -- no special API
- Context variables enable stateful conversations
- Easy to understand and extend
- No framework dependencies beyond OpenAI SDK

**Weaknesses:**
- No persistence or checkpointing
- No parallel execution
- No built-in memory beyond conversation history
- Single-threaded conversation model
- Explicitly NOT production-ready (educational)

---

### 2.5 Consensus / Debate Pattern

**Confidence:** MEDIUM

Multiple agents independently solve a problem, then a synthesizer combines or adjudicates.

```python
# Multi-Agent Debate / Consensus Pattern
class DebateOrchestrator:
    def __init__(self, agents: list, judge: Agent, rounds: int = 3):
        self.agents = agents
        self.judge = judge
        self.rounds = rounds

    def run(self, problem: str) -> str:
        # Round 1: Independent solutions
        responses = {}
        for agent in self.agents:
            responses[agent.name] = agent.solve(problem)

        # Rounds 2+: Agents see others' responses and can revise
        for round_num in range(1, self.rounds):
            for agent in self.agents:
                other_responses = {
                    name: resp for name, resp in responses.items()
                    if name != agent.name
                }
                responses[agent.name] = agent.revise(
                    problem=problem,
                    own_response=responses[agent.name],
                    other_responses=other_responses,
                    round_num=round_num,
                )

        # Final: Judge synthesizes
        final = self.judge.synthesize(
            problem=problem,
            all_responses=responses,
        )
        return final

# Usage
debater1 = Agent(name="Optimist", instructions="Argue for the approach...")
debater2 = Agent(name="Skeptic", instructions="Find problems with...")
debater3 = Agent(name="Pragmatist", instructions="Focus on practical...")
judge = Agent(name="Judge", instructions="Synthesize the best answer...")

orchestrator = DebateOrchestrator([debater1, debater2, debater3], judge)
result = orchestrator.run("Should we use microservices or monolith?")
```

**Strengths:**
- Better answers through adversarial review
- Reduces individual agent hallucination
- Natural for complex decisions
- Parallelizable (round 1)

**Weaknesses:**
- Expensive: N agents x M rounds of LLM calls
- Slow: sequential rounds required for debate
- Judge quality is critical
- Diminishing returns after 2-3 rounds

---

### Orchestration Pattern Comparison

| Pattern | Topology | Dynamic? | Parallelism | Complexity | Best For |
|---------|----------|----------|-------------|------------|----------|
| Graph (LangGraph) | Any | YES | YES | HIGH | Complex workflows with branching |
| Sequential (CrewAI) | Linear | NO | NO | LOW | Simple pipelines |
| Hierarchical | Star | YES | Partial | MEDIUM | Team-style task management |
| Handoff (Swarm) | Dynamic chain | YES | NO | LOW | Conversational routing |
| Consensus/Debate | Parallel + Merge | Partial | YES (round 1) | MEDIUM | Decision quality |

---

## 3. State Management Patterns

### 3.1 Reducer-Based State (LangGraph)

**Confidence:** HIGH

Inspired by Redux, LangGraph uses typed state with reducer functions that control how updates merge.

```python
from typing import TypedDict, Annotated
import operator

# State with reducers
class AgentState(TypedDict):
    # Append-only list (reducer = operator.add)
    messages: Annotated[list, operator.add]

    # Last-write-wins (no reducer annotation)
    current_agent: str

    # Custom reducer for accumulating unique items
    sources: Annotated[set, lambda old, new: old | new]

    # Counter with custom reducer
    step_count: Annotated[int, lambda old, new: old + new]

# How reducers work internally:
class StateManager:
    def apply_update(self, current_state: dict, update: dict) -> dict:
        new_state = dict(current_state)
        for key, value in update.items():
            if key in self.reducers:
                # Apply reducer: merge old and new
                new_state[key] = self.reducers[key](current_state[key], value)
            else:
                # Last-write-wins
                new_state[key] = value
        return new_state

# Example state transitions:
# Initial:  {"messages": [], "current_agent": "", "step_count": 0}
# Update 1: {"messages": [msg1], "current_agent": "researcher", "step_count": 1}
# Result:   {"messages": [msg1], "current_agent": "researcher", "step_count": 1}
# Update 2: {"messages": [msg2], "step_count": 1}
# Result:   {"messages": [msg1, msg2], "current_agent": "researcher", "step_count": 2}
#            ^ appended                 ^ preserved (not in update)     ^ added
```

**Key insight:** Reducers solve the concurrent update problem. When nodes run in parallel (via `add_conditional_edges` fan-out), each returns partial state updates. Reducers define how to merge them without conflicts.

---

### 3.2 Conversation History (AutoGen)

**Confidence:** MEDIUM

AutoGen uses chat history as the primary state mechanism. State IS the conversation.

```python
# AutoGen Conversation-as-State Pattern
class ConversableAgent:
    def __init__(self, name, ...):
        self.name = name
        self._oai_messages = {}  # Dict[Agent, List[Dict]] -- per-peer history

    def send(self, message, recipient, request_reply=True):
        """Send a message to another agent."""
        # Store in sender's history
        self._oai_messages.setdefault(recipient, []).append({
            "role": "assistant",
            "content": message,
        })
        # Recipient stores it too
        recipient.receive(message, self, request_reply)

    def receive(self, message, sender, request_reply=True):
        """Receive a message from another agent."""
        self._oai_messages.setdefault(sender, []).append({
            "role": "user",
            "content": message,
        })
        if request_reply:
            reply = self.generate_reply(
                messages=self._oai_messages[sender],
                sender=sender,
            )
            if reply:
                self.send(reply, sender)

    # State is implicitly the conversation history
    # To access "state", you read the message history
```

**Strengths:**
- Natural for conversational workflows
- History provides context automatically
- No separate state management layer

**Weaknesses:**
- Context window limits become state limits
- No structured data extraction without parsing messages
- Difficult to access specific state values
- History grows linearly; needs summarization strategies

---

### 3.3 Shared Blackboard Pattern

**Confidence:** MEDIUM

A shared mutable data store that all agents can read from and write to.

```python
# Blackboard Pattern Implementation
from threading import Lock
from typing import Any, Dict, List
from dataclasses import dataclass, field
import time

@dataclass
class BlackboardEntry:
    key: str
    value: Any
    author: str        # Which agent wrote this
    timestamp: float
    version: int

class Blackboard:
    def __init__(self):
        self._data: Dict[str, BlackboardEntry] = {}
        self._history: List[BlackboardEntry] = []
        self._lock = Lock()
        self._subscribers: Dict[str, List[callable]] = {}

    def read(self, key: str) -> Any:
        """Read a value from the blackboard."""
        with self._lock:
            entry = self._data.get(key)
            return entry.value if entry else None

    def write(self, key: str, value: Any, author: str):
        """Write a value to the blackboard."""
        with self._lock:
            version = 1
            if key in self._data:
                version = self._data[key].version + 1

            entry = BlackboardEntry(
                key=key,
                value=value,
                author=author,
                timestamp=time.time(),
                version=version,
            )
            self._data[key] = entry
            self._history.append(entry)

        # Notify subscribers
        for callback in self._subscribers.get(key, []):
            callback(entry)

    def subscribe(self, key: str, callback: callable):
        """Subscribe to changes on a key."""
        self._subscribers.setdefault(key, []).append(callback)

    def get_context_for_agent(self, agent_name: str, keys: List[str]) -> dict:
        """Get relevant blackboard state for an agent's prompt."""
        return {
            key: self.read(key)
            for key in keys
            if self.read(key) is not None
        }

# Usage
blackboard = Blackboard()

def researcher_node(state):
    # Write findings to blackboard
    findings = llm.invoke(...)
    blackboard.write("research_findings", findings, author="researcher")
    blackboard.write("sources", sources, author="researcher")
    return state

def writer_node(state):
    # Read from blackboard
    findings = blackboard.read("research_findings")
    sources = blackboard.read("sources")
    draft = llm.invoke(f"Write based on: {findings}")
    blackboard.write("draft", draft, author="writer")
    return state
```

**Strengths:**
- Decoupled: agents do not need to know about each other
- Flexible: any data structure
- Observable: easy to log and debug
- Supports pub/sub for reactive workflows

**Weaknesses:**
- Concurrency challenges (even with locks)
- No schema enforcement by default
- Hard to track data provenance in complex flows
- Can become a "god object"

---

### 3.4 Event Sourcing for Agent State

**Confidence:** LOW (less common, more architectural)

Instead of storing current state, store all events that produced the state.

```python
# Event Sourcing Pattern for Agent State
from dataclasses import dataclass
from enum import Enum
from typing import Any, List
import time

class EventType(Enum):
    AGENT_STARTED = "agent_started"
    TOOL_CALLED = "tool_called"
    TOOL_RESULT = "tool_result"
    LLM_RESPONSE = "llm_response"
    HANDOFF = "handoff"
    STATE_UPDATE = "state_update"
    HUMAN_INPUT = "human_input"
    ERROR = "error"

@dataclass
class AgentEvent:
    type: EventType
    agent_name: str
    timestamp: float
    data: dict
    sequence_number: int

class EventStore:
    def __init__(self):
        self._events: List[AgentEvent] = []
        self._seq = 0

    def append(self, event_type: EventType, agent: str, data: dict):
        self._seq += 1
        event = AgentEvent(
            type=event_type,
            agent_name=agent,
            timestamp=time.time(),
            data=data,
            sequence_number=self._seq,
        )
        self._events.append(event)
        return event

    def replay(self, up_to: int = None) -> dict:
        """Rebuild state by replaying events."""
        state = {}
        events = self._events[:up_to] if up_to else self._events
        for event in events:
            state = self._apply_event(state, event)
        return state

    def _apply_event(self, state: dict, event: AgentEvent) -> dict:
        if event.type == EventType.STATE_UPDATE:
            state.update(event.data)
        elif event.type == EventType.HANDOFF:
            state["active_agent"] = event.data["to_agent"]
        elif event.type == EventType.TOOL_RESULT:
            state.setdefault("tool_results", []).append(event.data)
        return state

    def get_events_for_agent(self, agent_name: str) -> List[AgentEvent]:
        return [e for e in self._events if e.agent_name == agent_name]

    def get_events_since(self, sequence_number: int) -> List[AgentEvent]:
        return [e for e in self._events if e.sequence_number > sequence_number]
```

**Strengths:**
- Complete audit trail
- Time travel / replay
- Can rebuild state at any point
- Natural fit for debugging and monitoring

**Weaknesses:**
- Storage grows unboundedly
- Replay can be slow for long histories
- More complex to implement correctly
- Snapshot optimization needed for production

---

## 4. Inter-Agent Communication Patterns

### 4.1 Direct Message Passing

**Confidence:** HIGH

Agents send messages directly to each other. The simplest pattern.

```python
# Direct Message Passing Pattern
class MessageBus:
    def __init__(self):
        self._agents: Dict[str, Agent] = {}

    def register(self, agent: Agent):
        self._agents[agent.name] = agent

    def send(self, from_agent: str, to_agent: str, message: dict):
        """Direct point-to-point message."""
        recipient = self._agents[to_agent]
        recipient.receive_message(
            sender=from_agent,
            message=message,
        )

# In LangGraph, this is implicit via state:
# Node A writes to state -> Node B reads from state
# The "message" is the state update
```

### 4.2 Group Chat (AutoGen)

**Confidence:** MEDIUM

Multiple agents participate in a shared conversation, with a manager selecting who speaks next.

```python
# AutoGen GroupChat Pattern
from autogen import GroupChat, GroupChatManager

# Define participating agents
coder = AssistantAgent(name="coder", ...)
reviewer = AssistantAgent(name="reviewer", ...)
tester = AssistantAgent(name="tester", ...)

# Create group chat
group_chat = GroupChat(
    agents=[coder, reviewer, tester],
    messages=[],
    max_round=12,
    speaker_selection_method="auto",  # "auto", "round_robin", "random", or callable
)

# Manager orchestrates the conversation
manager = GroupChatManager(
    groupchat=group_chat,
    llm_config=llm_config,
)

# Internal speaker selection (simplified):
class GroupChat:
    def select_speaker(self, last_speaker, selector):
        if self.speaker_selection_method == "round_robin":
            idx = self.agents.index(last_speaker)
            return self.agents[(idx + 1) % len(self.agents)]

        elif self.speaker_selection_method == "auto":
            # LLM decides who speaks next
            prompt = f"""Given the conversation so far, who should speak next?
            Available agents: {[a.name for a in self.agents]}
            Select one agent name."""
            next_name = selector.generate(prompt)
            return self._agent_by_name(next_name)

        elif callable(self.speaker_selection_method):
            return self.speaker_selection_method(last_speaker, self)

# Start the conversation
user_proxy.initiate_chat(
    manager,
    message="Build a Python web scraper that...",
)
```

**Key insight:** The GroupChatManager maintains a single shared conversation. Each agent sees ALL previous messages when it is their turn. The speaker selection is the critical orchestration decision.

**Strengths:**
- Natural collaboration feel
- All agents have full context
- Flexible speaker selection
- Easy to add/remove agents

**Weaknesses:**
- Context window fills fast (N agents x M rounds)
- Conversation can go off-track without good management
- No private communication channels
- Single-threaded (one speaker at a time)

---

### 4.3 Publish/Subscribe

**Confidence:** MEDIUM

Agents subscribe to topics and receive messages when other agents publish to those topics.

```python
# Pub/Sub Pattern for Agent Communication
from collections import defaultdict
from typing import Callable, Any
import time

class PubSubBroker:
    def __init__(self):
        self._subscriptions: Dict[str, List[Callable]] = defaultdict(list)
        self._message_log: List[dict] = []

    def subscribe(self, topic: str, handler: Callable):
        """Agent subscribes to a topic."""
        self._subscriptions[topic].append(handler)

    def publish(self, topic: str, message: Any, sender: str):
        """Agent publishes to a topic."""
        envelope = {
            "topic": topic,
            "message": message,
            "sender": sender,
            "timestamp": time.time(),
        }
        self._message_log.append(envelope)

        for handler in self._subscriptions[topic]:
            handler(envelope)

    def unsubscribe(self, topic: str, handler: Callable):
        self._subscriptions[topic].remove(handler)

# Usage
broker = PubSubBroker()

# Research agent publishes findings
def researcher_agent(query):
    results = search(query)
    broker.publish("research.findings", results, sender="researcher")
    broker.publish("research.status", "complete", sender="researcher")

# Writer agent subscribes to findings
def on_research_complete(envelope):
    findings = envelope["message"]
    draft = write_article(findings)
    broker.publish("writing.draft", draft, sender="writer")

broker.subscribe("research.findings", on_research_complete)

# Editor subscribes to drafts
def on_draft_ready(envelope):
    draft = envelope["message"]
    edited = edit_article(draft)
    broker.publish("writing.final", edited, sender="editor")

broker.subscribe("writing.draft", on_draft_ready)
```

**Strengths:**
- Highly decoupled
- Easy to add new agents without modifying existing ones
- Supports fan-out (multiple subscribers per topic)
- Natural for event-driven architectures

**Weaknesses:**
- Harder to reason about execution order
- No guaranteed delivery without additional infrastructure
- Debugging pub/sub chains is challenging
- Can create implicit dependencies that are hard to track

---

### 4.4 Tool-Mediated Communication

**Confidence:** HIGH

Agents communicate by writing to and reading from shared resources via tools.

```python
# Tool-Mediated Communication Pattern
# Agents do not talk directly; they share artifacts via tools

def save_research(topic: str, findings: str) -> str:
    """Save research findings for other agents to use."""
    db.save("research", topic, findings)
    return f"Research on '{topic}' saved successfully."

def get_research(topic: str) -> str:
    """Retrieve research findings on a topic."""
    return db.get("research", topic)

def submit_draft(title: str, content: str) -> str:
    """Submit a draft for review."""
    draft_id = db.save("drafts", title, {
        "content": content,
        "status": "pending_review",
    })
    return f"Draft '{title}' submitted with ID {draft_id}."

def get_pending_drafts() -> str:
    """Get all drafts pending review."""
    return json.dumps(db.query("drafts", status="pending_review"))

# Researcher has: [search_web, save_research]
# Writer has:     [get_research, submit_draft]
# Editor has:     [get_pending_drafts, approve_draft, request_revision]

# Communication happens THROUGH the shared data store
# No direct agent-to-agent messages needed
```

**Strengths:**
- Agents are completely independent
- Natural persistence (artifacts are stored)
- Works across sessions/restarts
- Easy to audit (check the data store)

**Weaknesses:**
- Indirect: agents must poll or be triggered
- Latency from storage layer
- Schema must be agreed upon
- No real-time collaboration feel

---

### 4.5 Handoff Protocol (Swarm)

**Confidence:** HIGH

A transfer-of-control pattern where one agent explicitly yields to another.

```python
# Handoff Protocol Pattern (from Swarm)

# Simple handoff: return an Agent to transfer control
def transfer_to_billing():
    """Transfer to billing department."""
    return billing_agent  # Control transfers immediately

# Handoff with context update
from swarm import Response

def transfer_to_specialist(context_variables, issue_type: str):
    """Transfer to a specialist with context."""
    context_variables["issue_type"] = issue_type
    context_variables["escalated"] = True
    return Response(
        value="Transferring you to a specialist...",
        agent=specialist_agent,
        context_variables=context_variables,
    )

# Conditional handoff
def maybe_escalate(context_variables, severity: str):
    """Escalate if severity is high."""
    if severity in ["critical", "high"]:
        return Response(
            value=f"Escalating {severity} issue to manager.",
            agent=manager_agent,
            context_variables={**context_variables, "severity": severity},
        )
    return f"Handling {severity} issue in current department."

# The handoff protocol is elegant because:
# 1. The AGENT decides when to hand off (via function calling)
# 2. The function decides WHERE to hand off (returns target agent)
# 3. Context is preserved across handoffs (context_variables)
# 4. The conversation history carries forward
```

---

### Communication Pattern Comparison

| Pattern | Coupling | Latency | Scalability | Debuggability | Best For |
|---------|----------|---------|-------------|---------------|----------|
| Direct message | HIGH | LOW | LOW | HIGH | Simple 2-agent systems |
| Group chat | MEDIUM | MEDIUM | LOW | MEDIUM | Collaborative problem-solving |
| Pub/Sub | LOW | MEDIUM | HIGH | LOW | Event-driven, many agents |
| Tool-mediated | VERY LOW | HIGH | HIGH | HIGH | Async, persistent workflows |
| Handoff | MEDIUM | LOW | MEDIUM | HIGH | Conversational routing |

---

## 5. Tool Integration Patterns

### 5.1 Function-Calling Based (Most Common)

**Confidence:** HIGH

Tools are Python functions whose signatures are converted to JSON Schema for the LLM.

```python
# Function-Calling Tool Integration Pattern

# Pattern A: Direct function registration (Swarm-style)
def get_weather(location: str, unit: str = "celsius") -> str:
    """Get current weather for a location.

    Args:
        location: City name or coordinates
        unit: Temperature unit (celsius or fahrenheit)
    """
    # Implementation
    return f"72F in {location}"

agent = Agent(
    name="Weather Bot",
    functions=[get_weather],  # Functions ARE the tools
)

# Under the hood, Swarm converts this to OpenAI function schema:
def function_to_json(func) -> dict:
    """Convert a Python function to OpenAI function-calling schema."""
    type_map = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
    }

    sig = inspect.signature(func)
    parameters = {}
    required = []

    for name, param in sig.parameters.items():
        if name == "context_variables":
            continue  # Skip internal params

        param_type = type_map.get(param.annotation, "string")
        parameters[name] = {"type": param_type}

        if param.default is inspect.Parameter.empty:
            required.append(name)

    return {
        "type": "function",
        "function": {
            "name": func.__name__,
            "description": func.__doc__ or "",
            "parameters": {
                "type": "object",
                "properties": parameters,
                "required": required,
            },
        },
    }

# Pattern B: Decorated tool registration (LangChain-style)
from langchain.tools import tool

@tool
def search_database(query: str, limit: int = 10) -> str:
    """Search the internal database for relevant documents."""
    results = db.search(query, limit=limit)
    return json.dumps(results)

# Pattern C: Pydantic-validated tools (CrewAI-style)
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

class SearchInput(BaseModel):
    query: str = Field(..., description="Search query")
    max_results: int = Field(10, description="Maximum results")

class SearchTool(BaseTool):
    name: str = "Search Database"
    description: str = "Search internal database"
    args_schema: type[BaseModel] = SearchInput

    def _run(self, query: str, max_results: int = 10) -> str:
        return json.dumps(db.search(query, max_results))
```

---

### 5.2 MCP (Model Context Protocol) Integration

**Confidence:** MEDIUM

MCP provides a standardized protocol for connecting LLMs to external tools and data sources via a client-server architecture.

```python
# MCP Tool Integration Pattern

# MCP Server exposes tools via JSON-RPC
class MCPToolServer:
    """A server that exposes tools via MCP protocol."""

    def __init__(self):
        self.tools = {}

    def register_tool(self, name: str, handler: Callable, schema: dict):
        self.tools[name] = {
            "handler": handler,
            "schema": schema,
        }

    async def handle_request(self, request: dict) -> dict:
        method = request["method"]

        if method == "tools/list":
            # Return available tools and their schemas
            return {
                "tools": [
                    {
                        "name": name,
                        "description": tool["schema"].get("description", ""),
                        "inputSchema": tool["schema"],
                    }
                    for name, tool in self.tools.items()
                ]
            }

        elif method == "tools/call":
            tool_name = request["params"]["name"]
            arguments = request["params"]["arguments"]
            result = await self.tools[tool_name]["handler"](**arguments)
            return {"content": [{"type": "text", "text": str(result)}]}

# MCP Client integration with agent framework
class MCPToolProvider:
    """Connects to MCP servers and provides tools to agents."""

    def __init__(self, server_configs: list):
        self.servers = []
        for config in server_configs:
            # Connect via stdio, SSE, or HTTP
            self.servers.append(MCPClient(config))

    async def get_tools(self) -> list:
        """Aggregate tools from all connected MCP servers."""
        all_tools = []
        for server in self.servers:
            tools = await server.request("tools/list")
            all_tools.extend(tools["tools"])
        return all_tools

    async def call_tool(self, name: str, arguments: dict) -> str:
        """Route tool call to the appropriate server."""
        for server in self.servers:
            if name in server.available_tools:
                result = await server.request("tools/call", {
                    "name": name,
                    "arguments": arguments,
                })
                return result["content"][0]["text"]
        raise ValueError(f"Tool {name} not found on any server")

# Usage with agent
mcp_provider = MCPToolProvider([
    {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem"]},
    {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]},
])

tools = await mcp_provider.get_tools()
agent = Agent(name="assistant", tools=tools)
```

**Key MCP concepts:**
- **Servers** expose tools, resources (read-only data), and prompts
- **Clients** connect to servers and make tools available to LLMs
- **Transport** can be stdio (local), SSE, or HTTP
- **Resources** provide context (like file contents) without tool execution
- **Sampling** allows servers to request LLM completions (reverse direction)

---

### 5.3 Custom Tool Registry

**Confidence:** MEDIUM

A centralized registry that manages tool discovery, access control, and execution.

```python
# Custom Tool Registry Pattern
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable
from enum import Enum
import asyncio
import time

class ToolPermission(Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    ADMIN = "admin"

@dataclass
class ToolDefinition:
    name: str
    description: str
    handler: Callable
    parameters_schema: dict
    permissions_required: List[ToolPermission] = field(default_factory=list)
    rate_limit: Optional[int] = None  # calls per minute
    timeout: int = 30  # seconds
    tags: List[str] = field(default_factory=list)

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._agent_permissions: Dict[str, List[ToolPermission]] = {}
        self._call_counts: Dict[str, List[float]] = {}

    def register(self, tool: ToolDefinition):
        self._tools[tool.name] = tool

    def grant_access(self, agent_name: str, permissions: List[ToolPermission]):
        self._agent_permissions[agent_name] = permissions

    def get_tools_for_agent(self, agent_name: str) -> List[dict]:
        """Return tool schemas an agent is authorized to use."""
        agent_perms = self._agent_permissions.get(agent_name, [])
        available = []
        for tool in self._tools.values():
            if all(p in agent_perms for p in tool.permissions_required):
                available.append({
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters_schema,
                })
        return available

    async def execute(self, tool_name: str, args: dict, agent_name: str) -> str:
        """Execute a tool with permission and rate limit checks."""
        tool = self._tools.get(tool_name)
        if not tool:
            raise ValueError(f"Unknown tool: {tool_name}")

        # Permission check
        agent_perms = self._agent_permissions.get(agent_name, [])
        if not all(p in agent_perms for p in tool.permissions_required):
            raise PermissionError(
                f"Agent '{agent_name}' lacks permissions for '{tool_name}'"
            )

        # Rate limit check
        if tool.rate_limit:
            now = time.time()
            calls = self._call_counts.get(tool_name, [])
            recent = [t for t in calls if now - t < 60]
            if len(recent) >= tool.rate_limit:
                raise Exception(f"Tool '{tool_name}' rate limited")
            recent.append(now)
            self._call_counts[tool_name] = recent

        # Execute with timeout
        result = await asyncio.wait_for(
            tool.handler(**args),
            timeout=tool.timeout,
        )
        return str(result)
```

---

### 5.4 Sandboxed Execution

**Confidence:** MEDIUM

Running agent-generated code in isolated environments.

```python
# Sandboxed Code Execution Patterns

# Pattern A: Docker-based (AutoGen style)
import docker
import subprocess

class DockerCodeExecutor:
    def __init__(self, image="python:3.11-slim", timeout=60):
        self.image = image
        self.timeout = timeout
        self.client = docker.from_env()

    def execute(self, code: str, language: str = "python") -> dict:
        """Execute code in a Docker container."""
        container = self.client.containers.run(
            self.image,
            command=f"python -c '{code}'",
            detach=True,
            mem_limit="256m",
            cpu_period=100000,
            cpu_quota=50000,       # 50% CPU
            network_disabled=True,  # No network access
            read_only=True,         # Read-only filesystem
        )
        try:
            result = container.wait(timeout=self.timeout)
            logs = container.logs()
            return {
                "exit_code": result["StatusCode"],
                "output": logs.decode(),
            }
        finally:
            container.remove(force=True)

# Pattern B: Subprocess with restrictions
class SubprocessExecutor:
    def __init__(self, timeout=30, allowed_modules=None):
        self.timeout = timeout
        self.allowed_modules = allowed_modules or ["math", "json", "datetime"]

    def execute(self, code: str) -> dict:
        """Execute code in a restricted subprocess."""
        # Validate: no dangerous imports
        for line in code.split("\n"):
            if "import" in line:
                module = line.split("import")[-1].strip().split(".")[0]
                if module not in self.allowed_modules:
                    return {"error": f"Module '{module}' not allowed"}

        result = subprocess.run(
            ["python", "-c", code],
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
        }

# Pattern C: E2B (cloud sandboxes) -- used by some agent frameworks
# Spins up a full cloud VM per execution
```

---

### Tool Integration Comparison

| Pattern | Setup Cost | Security | Flexibility | Ecosystem | Best For |
|---------|-----------|----------|-------------|-----------|----------|
| Function-calling | LOW | LOW | HIGH | Universal | Most use cases |
| MCP | MEDIUM | MEDIUM | HIGH | Growing | Standardized tool sharing |
| Custom registry | HIGH | HIGH | HIGH | Custom | Enterprise, multi-tenant |
| Sandboxed exec | HIGH | HIGH | MEDIUM | Varies | Code generation agents |

---

## 6. Human-in-the-Loop Patterns

### 6.1 Approval Gates

**Confidence:** HIGH

Pause execution at defined points and wait for human approval.

```python
# Approval Gate Pattern

# LangGraph approach: interrupt_before / interrupt_after
from langgraph.graph import StateGraph, END

graph = StateGraph(AgentState)
graph.add_node("plan", plan_node)
graph.add_node("execute", execute_node)
graph.add_node("report", report_node)

graph.add_edge("plan", "execute")
graph.add_edge("execute", "report")
graph.set_entry_point("plan")

# Compile with interrupt BEFORE the execute node
app = graph.compile(
    checkpointer=checkpointer,
    interrupt_before=["execute"],  # Pause here for approval
)

# First run: executes up to "execute" node, then pauses
config = {"configurable": {"thread_id": "approval-1"}}
result = app.invoke(initial_state, config)
# result contains the plan but execution is paused

# Human reviews the plan...
print(result["plan"])  # Show the plan to human

# Human approves: resume execution
result = app.invoke(None, config)  # Continues from checkpoint

# Human rejects: modify state and resume
app.update_state(config, {"plan": "revised plan..."})
result = app.invoke(None, config)  # Continues with modified state

# Generic approval gate pattern:
class ApprovalGate:
    def __init__(self, approval_handler: Callable):
        self.handler = approval_handler  # Could be CLI, web UI, Slack, etc.

    async def check(self, action: str, context: dict) -> bool:
        """Request human approval for an action."""
        approval = await self.handler(
            action=action,
            context=context,
            options=["approve", "reject", "modify"],
        )
        if approval.decision == "approve":
            return True
        elif approval.decision == "modify":
            return approval.modified_action
        else:
            raise Exception(f"Rejected: {approval.reason}")

# Usage in agent loop
gate = ApprovalGate(cli_approval_handler)

async def execute_with_approval(agent, task):
    plan = agent.plan(task)

    approved = await gate.check(
        action=f"Execute plan: {plan.summary}",
        context={"plan": plan, "tools_used": plan.tools},
    )

    if approved:
        return agent.execute(plan)
```

---

### 6.2 Interactive Debugging

**Confidence:** MEDIUM

Allow humans to inspect and modify agent state during execution.

```python
# Interactive Debugging Pattern
import json

class AgentDebugger:
    def __init__(self, agent_runtime):
        self.runtime = agent_runtime
        self.breakpoints = set()
        self.watches = {}

    def set_breakpoint(self, node_name: str, condition: Callable = None):
        """Break before a specific node, optionally with condition."""
        self.breakpoints.add((node_name, condition))

    def watch(self, state_key: str, label: str = None):
        """Watch a state variable."""
        self.watches[state_key] = label or state_key

    def should_break(self, node_name: str, state: dict) -> bool:
        for bp_node, condition in self.breakpoints:
            if bp_node == node_name:
                if condition is None or condition(state):
                    return True
        return False

    def debug_prompt(self, node_name: str, state: dict) -> dict:
        """Interactive debug console."""
        print(f"\n=== BREAKPOINT: {node_name} ===")

        # Show watched variables
        for key, label in self.watches.items():
            value = state.get(key, "<not set>")
            print(f"  {label}: {value}")

        while True:
            cmd = input("\n(c)ontinue, (s)tate, (m)odify, (a)bort > ")
            if cmd == "c":
                return state
            elif cmd == "s":
                print(json.dumps(state, indent=2, default=str))
            elif cmd == "m":
                key = input("  Key: ")
                value = input("  Value: ")
                state[key] = value
                print(f"  Set {key} = {value}")
            elif cmd == "a":
                raise Exception("Debugging aborted by user")

# LangGraph's built-in approach uses get_state / update_state:
# state = app.get_state(config)
# app.update_state(config, {"key": "new_value"})
```

---

### 6.3 Feedback Loops

**Confidence:** MEDIUM

Human provides feedback that agents incorporate into subsequent iterations.

```python
# Feedback Loop Pattern
class FeedbackLoop:
    def __init__(self, agent, max_iterations: int = 5):
        self.agent = agent
        self.max_iterations = max_iterations
        self.feedback_history = []

    async def run(self, task: str) -> str:
        result = await self.agent.execute(task)

        for iteration in range(self.max_iterations):
            # Present result to human
            print(f"\n--- Iteration {iteration + 1} ---")
            print(result)

            # Get feedback
            feedback = input("\nFeedback (or 'approve' to accept): ")
            if feedback.lower() == "approve":
                return result

            # Store feedback history
            self.feedback_history.append({
                "iteration": iteration,
                "result": result,
                "feedback": feedback,
            })

            # Agent revises based on feedback
            result = await self.agent.revise(
                original_task=task,
                current_result=result,
                feedback=feedback,
                feedback_history=self.feedback_history,
            )

        return result  # Return last result after max iterations
```

---

### 6.4 Escalation Protocols

**Confidence:** MEDIUM

Agents detect when they need human help and escalate appropriately.

```python
# Escalation Protocol Pattern
from enum import Enum
from typing import Optional, Callable

class EscalationLevel(Enum):
    INFO = "info"           # FYI, no action needed
    REVIEW = "review"       # Human should review
    APPROVAL = "approval"   # Cannot proceed without approval
    TAKEOVER = "takeover"   # Human must take over entirely

class EscalationPolicy:
    def __init__(self):
        self.rules = []

    def add_rule(self, condition: Callable, level: EscalationLevel, message: str):
        self.rules.append((condition, level, message))

    def evaluate(self, state: dict) -> Optional[tuple]:
        for condition, level, message in self.rules:
            if condition(state):
                return (level, message)
        return None

# Define escalation policies
policy = EscalationPolicy()

# Escalate if confidence is low
policy.add_rule(
    condition=lambda s: s.get("confidence", 1.0) < 0.5,
    level=EscalationLevel.REVIEW,
    message="Agent confidence is below 50%. Please review output.",
)

# Escalate if touching sensitive data
policy.add_rule(
    condition=lambda s: s.get("involves_pii", False),
    level=EscalationLevel.APPROVAL,
    message="Operation involves PII. Human approval required.",
)

# Escalate if too many retries
policy.add_rule(
    condition=lambda s: s.get("retry_count", 0) >= 3,
    level=EscalationLevel.TAKEOVER,
    message="Agent failed 3 times. Human takeover recommended.",
)

# Escalate if cost threshold exceeded
policy.add_rule(
    condition=lambda s: s.get("total_cost", 0) > 10.0,
    level=EscalationLevel.APPROVAL,
    message="Cost exceeds $10. Approve to continue.",
)

# Integration with agent execution
class EscalationAwareAgent:
    def __init__(self, agent, policy: EscalationPolicy, handler: Callable):
        self.agent = agent
        self.policy = policy
        self.handler = handler  # Human notification system

    async def execute(self, task, state):
        # Check before execution
        escalation = self.policy.evaluate(state)
        if escalation:
            level, message = escalation
            decision = await self.handler(level, message, state)
            if decision == "abort":
                return None
            elif decision == "takeover":
                return await self.handler.human_execute(task, state)

        result = await self.agent.execute(task)

        # Check after execution
        state.update(result)
        escalation = self.policy.evaluate(state)
        if escalation:
            level, message = escalation
            await self.handler(level, message, state)

        return result
```

---

### HITL Pattern Comparison

| Pattern | Latency Impact | User Effort | Automation | Best For |
|---------|---------------|-------------|------------|----------|
| Approval gates | HIGH (blocks) | LOW (yes/no) | HIGH | Safety-critical actions |
| Interactive debug | VERY HIGH | HIGH | LOW | Development/troubleshooting |
| Feedback loops | HIGH | MEDIUM | MEDIUM | Creative/subjective tasks |
| Escalation | LOW (async ok) | VARIES | HIGH | Production monitoring |

---

## 7. Synthesis: Architectural Recommendations

### Recommended Composite Architecture

Based on analyzing all five frameworks, here is a recommended architecture for a new multi-agent orchestration framework:

```
+--------------------------------------------------+
|              Agent Definition Layer               |
|  (Class-based with builder pattern + decorator)   |
+--------------------------------------------------+
           |                    |
+---------------------+  +---------------------+
|   Tool Integration  |  |   State Management  |
|  (Function-calling  |  |  (Reducer-based     |
|   + MCP support     |  |   + event sourcing  |
|   + registry)       |  |   for audit trail)  |
+---------------------+  +---------------------+
           |                    |
+--------------------------------------------------+
|            Orchestration Engine                    |
|  (Graph-based core that can express any pattern:  |
|   sequential, hierarchical, handoff, consensus)   |
+--------------------------------------------------+
           |                    |
+---------------------+  +---------------------+
|   Communication     |  |   Human-in-Loop     |
|  (State-mediated    |  |  (Checkpoint-based  |
|   + pub/sub for     |  |   interrupt/resume  |
|   async workflows)  |  |   + escalation)     |
+---------------------+  +---------------------+
           |
+--------------------------------------------------+
|              Persistence / Checkpointing          |
|  (Pluggable: in-memory, SQLite, Redis, Postgres)  |
+--------------------------------------------------+
```

### Key Design Decisions

| Decision | Recommendation | Rationale |
|----------|---------------|-----------|
| Agent definition | Class-based (Pydantic) | Type safety, serialization, validation |
| Orchestration | Graph engine (like LangGraph) | Most flexible; can express all other patterns |
| State | Typed state with reducers | Explicit, predictable, supports parallel nodes |
| Communication | State-mediated (primary) + pub/sub (async) | Simple default with escape hatch for complex flows |
| Tools | Function-calling + MCP adapter | Standard approach + future-proof protocol |
| HITL | Checkpoint-based interrupt/resume | Clean separation of concerns |
| Persistence | Pluggable store interface | Different needs for dev vs production |

### Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Function-to-JSON schema | Custom parser | `inspect` + existing converters | Edge cases in type handling |
| LLM retries/fallbacks | Custom retry logic | LiteLLM or tenacity | Rate limits, model fallbacks, caching |
| Token counting | Character estimation | tiktoken | Accuracy matters for context management |
| Conversation memory | String concatenation | Structured message lists | Roles, tool calls, multi-modal content |
| Code sandboxing | os.system with restrictions | Docker / E2B / modal | Security is extremely hard to get right |
| Graph visualization | Custom renderer | Mermaid or graphviz export | Standard tooling, wide support |

### Common Pitfalls

| Pitfall | Description | Prevention |
|---------|-------------|------------|
| Context window overflow | Multi-agent conversations fill context fast | Implement summarization, sliding windows, or RAG |
| Infinite loops | Agents keep delegating to each other | Max iteration limits on all loops |
| Cost explosion | N agents x M rounds x long prompts | Token budgets, cost tracking, escalation |
| Hallucinated tool calls | Agent invents tools that do not exist | Strict schema validation, error handling |
| State corruption | Parallel nodes write conflicting state | Reducer pattern, immutable state updates |
| Over-engineering | Building all patterns before needing them | Start with sequential, add complexity as needed |
| Agent identity bleed | Agent forgets its role in long conversations | Reinforce system prompt, use structured state |
| Silent failures | Tool errors swallowed, agent confabulates | Always surface errors to agent, log all tool calls |

---

## Sources

### Primary (HIGH confidence)
- OpenAI Swarm source code (github.com/openai/swarm) -- ~300 lines, fully studied in training data
- LangGraph documentation and StateGraph API -- core patterns well-documented
- CrewAI documentation and source code -- Agent, Task, Crew, Process classes

### Secondary (MEDIUM confidence)
- AutoGen documentation (pre-v0.4 and AG2 fork) -- API instability noted
- MCP specification (modelcontextprotocol.io) -- protocol is well-specified but ecosystem is young
- General multi-agent patterns from academic and industry sources

### Tertiary (LOW confidence)
- DSL-based agent definitions -- composite from multiple smaller frameworks
- Event sourcing for agent state -- architectural pattern, not widely implemented in agent frameworks
- Consensus/debate orchestration -- academic papers, limited production implementations

**Note:** WebSearch and WebFetch tools were unavailable during this research. All findings are based on training knowledge through early 2025. Verify current APIs before implementation.

## Metadata

**Confidence breakdown:**
- Agent definition patterns: HIGH -- based on direct study of framework source code
- Orchestration engines: HIGH -- well-documented in major frameworks
- State management: MEDIUM-HIGH -- reducer pattern is well-documented; event sourcing is architectural
- Communication patterns: MEDIUM -- some patterns are well-implemented, others are conceptual
- Tool integration: HIGH for function-calling, MEDIUM for MCP
- Human-in-the-loop: MEDIUM -- patterns exist but implementations vary significantly

**Research date:** 2026-03-05
**Valid until:** 2026-04-05 (30 days -- this is a fast-moving space; verify APIs against current docs)
