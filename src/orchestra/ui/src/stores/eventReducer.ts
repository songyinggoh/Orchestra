/**
 * Pure reducer: given the current RunSlice state and an incoming event,
 * returns the fields that need updating. Handles all 21 event types.
 * No React or Zustand imports — fully unit-testable.
 */

import type {
  AnyEvent,
  LLMCalled,
  SecurityViolation,
  RestrictedModeEntered,
  InputRejected,
  OutputRejected,
} from '../types/events';

export type NodeStatus = 'pending' | 'running' | 'completed' | 'error' | 'waiting';

export interface NodeData {
  /** Cumulative LLM cost in USD for this node */
  cost: number;
  /** Last model used by this node */
  model: string | null;
  /** Number of tool calls made by this node */
  toolCount: number;
  /** Number of security events originating from this node */
  securityCount: number;
}

export interface RunMetrics {
  status: 'pending' | 'running' | 'completed' | 'error';
  totalCost: number;
  totalTokens: number;
  /** ISO timestamp of execution.started */
  startTime: string | null;
  /** Duration in ms (set on execution.completed) */
  duration: number | null;
  workflowName: string | null;
}

export interface ReducerState {
  nodeStatuses: Record<string, NodeStatus>;
  nodeData: Record<string, NodeData>;
  currentState: Record<string, unknown>;
  metrics: RunMetrics;
}

export const initialReducerState: ReducerState = {
  nodeStatuses: {},
  nodeData: {},
  currentState: {},
  metrics: {
    status: 'pending',
    totalCost: 0,
    totalTokens: 0,
    startTime: null,
    duration: null,
    workflowName: null,
  },
};

function nodeDataFor(state: ReducerState, nodeId: string): NodeData {
  return state.nodeData[nodeId] ?? { cost: 0, model: null, toolCount: 0, securityCount: 0 };
}

function markSecure(state: ReducerState, nodeId: string): Partial<ReducerState> {
  const existing = nodeDataFor(state, nodeId);
  return {
    nodeData: {
      ...state.nodeData,
      [nodeId]: { ...existing, securityCount: existing.securityCount + 1 },
    },
  };
}

/** Returns a partial state update to merge. */
export function eventReducer(state: ReducerState, event: AnyEvent): Partial<ReducerState> {
  switch (event.event_type) {
    case 'execution.started':
      return {
        metrics: {
          ...state.metrics,
          status: 'running',
          startTime: event.timestamp,
          workflowName: event.workflow_name,
        },
        currentState: event.initial_state,
      };

    case 'execution.completed':
      return {
        metrics: {
          ...state.metrics,
          status: (event.status === 'error' ? 'error' : 'completed') as RunMetrics['status'],
          totalCost: event.total_cost_usd,
          totalTokens: event.total_tokens,
          duration: event.duration_ms,
        },
        currentState: event.final_state,
      };

    case 'execution.forked':
      // No node-status change; the fork badge is handled in the UI layer.
      return {};

    case 'node.started':
      return {
        nodeStatuses: { ...state.nodeStatuses, [event.node_id]: 'running' },
      };

    case 'node.completed':
      return {
        nodeStatuses: { ...state.nodeStatuses, [event.node_id]: 'completed' },
        currentState: event.state_update
          ? { ...state.currentState, ...event.state_update }
          : state.currentState,
      };

    case 'error.occurred':
      return {
        nodeStatuses: { ...state.nodeStatuses, [event.node_id]: 'error' },
        metrics: { ...state.metrics, status: 'error' },
      };

    case 'state.updated':
      return {
        currentState: event.resulting_state,
      };

    case 'llm.called': {
      const llm = event as LLMCalled;
      const existing = nodeDataFor(state, llm.node_id);
      return {
        nodeData: {
          ...state.nodeData,
          [llm.node_id]: {
            ...existing,
            cost: existing.cost + llm.cost_usd,
            model: llm.model,
          },
        },
        metrics: {
          ...state.metrics,
          totalCost: state.metrics.totalCost + llm.cost_usd,
          totalTokens:
            state.metrics.totalTokens + llm.input_tokens + llm.output_tokens,
        },
      };
    }

    case 'tool.called': {
      const existing = nodeDataFor(state, event.node_id);
      return {
        nodeData: {
          ...state.nodeData,
          [event.node_id]: { ...existing, toolCount: existing.toolCount + 1 },
        },
      };
    }

    case 'edge.traversed':
      // Edge highlight is transient (400ms pulse) — handled in UI layer, not state.
      return {};

    case 'parallel.started':
      return {
        nodeStatuses: {
          ...state.nodeStatuses,
          ...Object.fromEntries(event.target_nodes.map((n) => [n, 'running' as NodeStatus])),
        },
      };

    case 'parallel.completed':
      return {
        nodeStatuses: {
          ...state.nodeStatuses,
          ...Object.fromEntries(event.target_nodes.map((n) => [n, 'completed' as NodeStatus])),
        },
      };

    case 'interrupt.requested':
      return {
        nodeStatuses: { ...state.nodeStatuses, [event.node_id]: 'waiting' },
      };

    case 'interrupt.resumed':
      return {
        nodeStatuses: { ...state.nodeStatuses, [event.node_id]: 'running' },
        currentState: { ...state.currentState, ...event.state_modifications },
      };

    case 'checkpoint.created':
      // Scrubber diamond tick is handled in W2; no state mutation here.
      return {};

    case 'security.violation':
      return markSecure(state, (event as SecurityViolation).node_id);

    case 'security.restricted_mode_entered':
      return markSecure(state, (event as RestrictedModeEntered).node_id);

    case 'input.rejected':
      return markSecure(state, (event as InputRejected).node_id);

    case 'output.rejected':
      return markSecure(state, (event as OutputRejected).node_id);

    case 'handoff.initiated':
      // Handoff edge rendering handled by graph layer.
      return {};

    case 'handoff.completed':
      // Edge solidification handled by graph layer.
      return {};

    default: {
      // Exhaustiveness guard: TypeScript will error here if a new EventType
      // is added to the union but not handled above.
      const _: never = event;
      void _;
      return {};
    }
  }
}
