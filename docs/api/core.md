# Core API Reference

## Agents

### BaseAgent

::: orchestra.core.agent.BaseAgent
    options:
      show_source: false
      heading_level: 4

### @agent decorator

::: orchestra.core.agent.agent
    options:
      show_source: false
      heading_level: 4

### DecoratedAgent

::: orchestra.core.agent.DecoratedAgent
    options:
      show_source: false
      heading_level: 4

---

## Graph Building

### WorkflowGraph

::: orchestra.core.graph.WorkflowGraph
    options:
      show_source: false
      heading_level: 4
      members:
        - add_node
        - add_edge
        - add_conditional_edge
        - add_parallel
        - set_entry_point
        - then
        - parallel
        - join
        - branch
        - if_then
        - loop
        - compile

---

## Graph Execution

### CompiledGraph

::: orchestra.core.compiled.CompiledGraph
    options:
      show_source: false
      heading_level: 4
      members:
        - run
        - to_mermaid

---

## Runner

### run

::: orchestra.core.runner.run
    options:
      show_source: false
      heading_level: 4

### run_sync

::: orchestra.core.runner.run_sync
    options:
      show_source: false
      heading_level: 4

### RunResult

::: orchestra.core.runner.RunResult
    options:
      show_source: false
      heading_level: 4

---

## State

### WorkflowState

::: orchestra.core.state.WorkflowState
    options:
      show_source: false
      heading_level: 4

### Reducers

::: orchestra.core.state.merge_list
    options:
      show_source: false
      heading_level: 4

::: orchestra.core.state.merge_dict
    options:
      show_source: false
      heading_level: 4

::: orchestra.core.state.sum_numbers
    options:
      show_source: false
      heading_level: 4

::: orchestra.core.state.last_write_wins
    options:
      show_source: false
      heading_level: 4

::: orchestra.core.state.merge_set
    options:
      show_source: false
      heading_level: 4

::: orchestra.core.state.concat_str
    options:
      show_source: false
      heading_level: 4

::: orchestra.core.state.keep_first
    options:
      show_source: false
      heading_level: 4

::: orchestra.core.state.max_value
    options:
      show_source: false
      heading_level: 4

::: orchestra.core.state.min_value
    options:
      show_source: false
      heading_level: 4

### State Functions

::: orchestra.core.state.extract_reducers
    options:
      show_source: false
      heading_level: 4

::: orchestra.core.state.apply_state_update
    options:
      show_source: false
      heading_level: 4

::: orchestra.core.state.merge_parallel_updates
    options:
      show_source: false
      heading_level: 4

---

## Context

### ExecutionContext

::: orchestra.core.context.ExecutionContext
    options:
      show_source: false
      heading_level: 4

---

## Types

### Message

::: orchestra.core.types.Message
    options:
      show_source: false
      heading_level: 4

### MessageRole

::: orchestra.core.types.MessageRole
    options:
      show_source: false
      heading_level: 4

### ToolCall

::: orchestra.core.types.ToolCall
    options:
      show_source: false
      heading_level: 4

### ToolResult

::: orchestra.core.types.ToolResult
    options:
      show_source: false
      heading_level: 4

### AgentResult

::: orchestra.core.types.AgentResult
    options:
      show_source: false
      heading_level: 4

### LLMResponse

::: orchestra.core.types.LLMResponse
    options:
      show_source: false
      heading_level: 4

### TokenUsage

::: orchestra.core.types.TokenUsage
    options:
      show_source: false
      heading_level: 4

### StreamChunk

::: orchestra.core.types.StreamChunk
    options:
      show_source: false
      heading_level: 4

---

## Edges

### Edge

::: orchestra.core.edges.Edge
    options:
      show_source: false
      heading_level: 4

### ConditionalEdge

::: orchestra.core.edges.ConditionalEdge
    options:
      show_source: false
      heading_level: 4

### ParallelEdge

::: orchestra.core.edges.ParallelEdge
    options:
      show_source: false
      heading_level: 4

---

## Nodes

### AgentNode

::: orchestra.core.nodes.AgentNode
    options:
      show_source: false
      heading_level: 4

### FunctionNode

::: orchestra.core.nodes.FunctionNode
    options:
      show_source: false
      heading_level: 4

### SubgraphNode

::: orchestra.core.nodes.SubgraphNode
    options:
      show_source: false
      heading_level: 4

---

## Protocols

### Agent Protocol

::: orchestra.core.protocols.Agent
    options:
      show_source: false
      heading_level: 4

### Tool Protocol

::: orchestra.core.protocols.Tool
    options:
      show_source: false
      heading_level: 4

### LLMProvider Protocol

::: orchestra.core.protocols.LLMProvider
    options:
      show_source: false
      heading_level: 4

---

## Errors

::: orchestra.core.errors
    options:
      show_source: false
      heading_level: 4
      members_order: source
