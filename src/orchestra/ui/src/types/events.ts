/** Event types matching Python's EventType enum. */
export type EventType =
  | 'execution.started'
  | 'execution.completed'
  | 'execution.forked'
  | 'node.started'
  | 'node.completed'
  | 'state.updated'
  | 'error.occurred'
  | 'llm.called'
  | 'tool.called'
  | 'edge.traversed'
  | 'parallel.started'
  | 'parallel.completed'
  | 'interrupt.requested'
  | 'interrupt.resumed'
  | 'checkpoint.created'
  | 'security.violation'
  | 'security.restricted_mode_entered'
  | 'input.rejected'
  | 'output.rejected'
  | 'handoff.initiated'
  | 'handoff.completed';

/** Base fields shared by all events. */
export interface WorkflowEvent {
  event_id: string;
  run_id: string;
  timestamp: string;
  sequence: number;
  event_type: EventType;
  schema_version: number;
}

export interface ExecutionStarted extends WorkflowEvent {
  event_type: 'execution.started';
  workflow_name: string;
  initial_state: Record<string, unknown>;
  entry_point: string;
}

export interface ExecutionCompleted extends WorkflowEvent {
  event_type: 'execution.completed';
  final_state: Record<string, unknown>;
  duration_ms: number;
  total_tokens: number;
  total_cost_usd: number;
  status: string;
}

export interface NodeStarted extends WorkflowEvent {
  event_type: 'node.started';
  node_id: string;
  node_type: string;
}

export interface NodeCompleted extends WorkflowEvent {
  event_type: 'node.completed';
  node_id: string;
  node_type: string;
  duration_ms: number;
  state_update: Record<string, unknown> | null;
}

export interface LLMCalled extends WorkflowEvent {
  event_type: 'llm.called';
  node_id: string;
  agent_name: string;
  model: string;
  content: string;
  tool_calls: unknown[];
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  duration_ms: number;
  finish_reason: string;
}

export interface ToolCalled extends WorkflowEvent {
  event_type: 'tool.called';
  node_id: string;
  agent_name: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  result: string;
  error: string | null;
  duration_ms: number;
}

export interface EdgeTraversed extends WorkflowEvent {
  event_type: 'edge.traversed';
  from_node: string;
  to_node: string;
  edge_type: string;
  condition_result: string | null;
}

export interface ParallelStarted extends WorkflowEvent {
  event_type: 'parallel.started';
  source_node: string;
  target_nodes: string[];
}

export interface ParallelCompleted extends WorkflowEvent {
  event_type: 'parallel.completed';
  source_node: string;
  target_nodes: string[];
  duration_ms: number;
}

export interface ErrorOccurred extends WorkflowEvent {
  event_type: 'error.occurred';
  node_id: string;
  error_type: string;
  error_message: string;
}

export interface StateUpdated extends WorkflowEvent {
  event_type: 'state.updated';
  node_id: string;
  field_updates: Record<string, unknown>;
  resulting_state: Record<string, unknown>;
}

export interface InterruptRequested extends WorkflowEvent {
  event_type: 'interrupt.requested';
  node_id: string;
  interrupt_type: string;
}

export interface HandoffInitiated extends WorkflowEvent {
  event_type: 'handoff.initiated';
  from_agent: string;
  to_agent: string;
  reason: string;
}

/** Union of all concrete event types. */
export type AnyEvent =
  | ExecutionStarted
  | ExecutionCompleted
  | NodeStarted
  | NodeCompleted
  | LLMCalled
  | ToolCalled
  | EdgeTraversed
  | ParallelStarted
  | ParallelCompleted
  | ErrorOccurred
  | StateUpdated
  | InterruptRequested
  | HandoffInitiated
  | WorkflowEvent; // fallback for less common types
