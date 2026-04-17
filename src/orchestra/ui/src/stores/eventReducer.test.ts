import { describe, it, expect } from 'vitest';
import { eventReducer, initialReducerState, type ReducerState } from './eventReducer';
import type { AnyEvent } from '../types/events';

function makeEvent<T extends AnyEvent>(overrides: Partial<T> & Pick<T, 'event_type'>): T {
  return {
    event_id: 'evt-1',
    run_id: 'run-1',
    timestamp: new Date().toISOString(),
    sequence: 1,
    schema_version: 1,
    ...overrides,
  } as T;
}

function applyEvents(events: AnyEvent[]): ReducerState {
  let state = initialReducerState;
  for (const ev of events) {
    state = { ...state, ...eventReducer(state, ev) };
  }
  return state;
}

describe('eventReducer', () => {
  it('tracks execution lifecycle: pending → running → completed', () => {
    const events: AnyEvent[] = [
      makeEvent({ event_type: 'execution.started', workflow_name: 'my-flow', initial_state: {}, entry_point: 'a' }),
      makeEvent({ event_type: 'node.started', node_id: 'a', node_type: 'agent' }),
      makeEvent({ event_type: 'llm.called', node_id: 'a', agent_name: 'agent', model: 'claude', content: '', tool_calls: [], input_tokens: 100, output_tokens: 50, cost_usd: 0.001, duration_ms: 200, finish_reason: 'stop' }),
      makeEvent({ event_type: 'node.completed', node_id: 'a', node_type: 'agent', duration_ms: 300, state_update: null }),
      makeEvent({ event_type: 'execution.completed', final_state: {}, duration_ms: 500, total_tokens: 150, total_cost_usd: 0.001, status: 'completed' }),
    ];

    const state = applyEvents(events);

    expect(state.metrics.status).toBe('completed');
    expect(state.metrics.totalTokens).toBe(150);
    expect(state.metrics.totalCost).toBeCloseTo(0.001);
    expect(state.nodeStatuses['a']).toBe('completed');
    expect(state.nodeData['a'].model).toBe('claude');
  });

  it('increments securityCount on security events', () => {
    const events: AnyEvent[] = [
      makeEvent({ event_type: 'security.violation', node_id: 'x', agent_name: 'agent', violation_type: 'injection', details: 'bad' }),
      makeEvent({ event_type: 'input.rejected', node_id: 'x', agent_name: 'agent', guardrail: 'pii', violation_messages: ['fail'] }),
    ];
    const state = applyEvents(events);
    expect(state.nodeData['x'].securityCount).toBe(2);
  });

  it('marks node as waiting on interrupt.requested', () => {
    const state = applyEvents([
      makeEvent({ event_type: 'interrupt.requested', node_id: 'b', interrupt_type: 'human' }),
    ]);
    expect(state.nodeStatuses['b']).toBe('waiting');
  });

  it('marks node as error and sets metrics.status on error.occurred', () => {
    const state = applyEvents([
      makeEvent({ event_type: 'error.occurred', node_id: 'c', error_type: 'RuntimeError', error_message: 'oops' }),
    ]);
    expect(state.nodeStatuses['c']).toBe('error');
    expect(state.metrics.status).toBe('error');
  });
});
