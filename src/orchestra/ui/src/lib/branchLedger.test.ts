import { describe, it, expect } from 'vitest';
import { buildBranchLedger, ledgerTotal } from './branchLedger';
import type { AnyEvent } from '../types/events';

function ts(offset = 0) {
  return new Date(1_700_000_000_000 + offset).toISOString();
}

function ev(overrides: Partial<AnyEvent> & { event_type: string }): AnyEvent {
  return {
    event_id: `evt-${Math.random()}`,
    run_id: 'run-1',
    sequence: 0,
    timestamp: ts(),
    ...overrides,
  } as AnyEvent;
}

// Flat 2-branch parallel: node_a and node_b each get 2 LLM calls.
const FLAT_EVENTS: AnyEvent[] = [
  ev({ event_type: 'parallel.started', sequence: 1, source_node: 'dispatch', target_nodes: ['node_a', 'node_b'], timestamp: ts(0) } as AnyEvent),
  ev({ event_type: 'node.started', sequence: 2, node_id: 'node_a', timestamp: ts(1) } as AnyEvent),
  ev({ event_type: 'llm.called', sequence: 3, node_id: 'node_a', cost_usd: 0.01, model: 'gpt-4', agent_name: 'a', input_tokens: 100, output_tokens: 50 } as AnyEvent),
  ev({ event_type: 'node.started', sequence: 4, node_id: 'node_b', timestamp: ts(2) } as AnyEvent),
  ev({ event_type: 'llm.called', sequence: 5, node_id: 'node_b', cost_usd: 0.02, model: 'gpt-4', agent_name: 'b', input_tokens: 200, output_tokens: 100 } as AnyEvent),
  ev({ event_type: 'llm.called', sequence: 6, node_id: 'node_a', cost_usd: 0.005, model: 'gpt-4', agent_name: 'a', input_tokens: 50, output_tokens: 25 } as AnyEvent),
  ev({ event_type: 'llm.called', sequence: 7, node_id: 'node_b', cost_usd: 0.015, model: 'gpt-4', agent_name: 'b', input_tokens: 150, output_tokens: 75 } as AnyEvent),
  ev({ event_type: 'parallel.completed', sequence: 8, source_node: 'dispatch', target_nodes: ['node_a', 'node_b'], timestamp: ts(3) } as AnyEvent),
];

describe('buildBranchLedger — flat 2-branch parallel', () => {
  it('creates one entry per declared branch', () => {
    const ledger = buildBranchLedger(FLAT_EVENTS);
    expect(Object.keys(ledger)).toHaveLength(2);
  });

  it('accumulates cost correctly per branch', () => {
    const ledger = buildBranchLedger(FLAT_EVENTS);
    const branches = Object.values(ledger);
    const byNode = Object.fromEntries(branches.map((b) => [b.nodes[0], b.cost_usd]));
    expect(byNode['node_a']).toBeCloseTo(0.015, 6);
    expect(byNode['node_b']).toBeCloseTo(0.035, 6);
  });

  it('total matches sum across branches', () => {
    const ledger = buildBranchLedger(FLAT_EVENTS);
    expect(ledgerTotal(ledger)).toBeCloseTo(0.05, 6);
  });

  it('marks completed_at when parallel.completed received', () => {
    const ledger = buildBranchLedger(FLAT_EVENTS);
    for (const b of Object.values(ledger)) {
      expect(b.completed_at).toBeDefined();
    }
  });
});

// Nested parallel: outer has branches [outer_a, outer_b].
// outer_b contains inner parallel with branches [inner_b1, inner_b2].
const NESTED_EVENTS: AnyEvent[] = [
  ev({ event_type: 'parallel.started', sequence: 1, source_node: 'root', target_nodes: ['outer_a', 'outer_b'], timestamp: ts(0) } as AnyEvent),
  ev({ event_type: 'node.started', sequence: 2, node_id: 'outer_a', timestamp: ts(1) } as AnyEvent),
  ev({ event_type: 'llm.called', sequence: 3, node_id: 'outer_a', cost_usd: 0.1, model: 'gpt-4', agent_name: 'a', input_tokens: 0, output_tokens: 0 } as AnyEvent),
  ev({ event_type: 'node.started', sequence: 4, node_id: 'outer_b', timestamp: ts(2) } as AnyEvent),
  // inner parallel inside outer_b
  ev({ event_type: 'parallel.started', sequence: 5, source_node: 'outer_b', target_nodes: ['inner_b1', 'inner_b2'], timestamp: ts(3) } as AnyEvent),
  ev({ event_type: 'node.started', sequence: 6, node_id: 'inner_b1', timestamp: ts(4) } as AnyEvent),
  ev({ event_type: 'llm.called', sequence: 7, node_id: 'inner_b1', cost_usd: 0.05, model: 'gpt-4', agent_name: 'b1', input_tokens: 0, output_tokens: 0 } as AnyEvent),
  ev({ event_type: 'node.started', sequence: 8, node_id: 'inner_b2', timestamp: ts(5) } as AnyEvent),
  ev({ event_type: 'llm.called', sequence: 9, node_id: 'inner_b2', cost_usd: 0.03, model: 'gpt-4', agent_name: 'b2', input_tokens: 0, output_tokens: 0 } as AnyEvent),
  ev({ event_type: 'parallel.completed', sequence: 10, source_node: 'outer_b', target_nodes: ['inner_b1', 'inner_b2'], timestamp: ts(6) } as AnyEvent),
  ev({ event_type: 'parallel.completed', sequence: 11, source_node: 'root', target_nodes: ['outer_a', 'outer_b'], timestamp: ts(7) } as AnyEvent),
];

describe('buildBranchLedger — nested parallel', () => {
  it('creates 4 branch entries total (2 outer + 2 inner)', () => {
    const ledger = buildBranchLedger(NESTED_EVENTS);
    expect(Object.keys(ledger)).toHaveLength(4);
  });

  it('attributes inner costs to inner branches, not outer', () => {
    const ledger = buildBranchLedger(NESTED_EVENTS);
    const outerA = Object.values(ledger).find((b) => b.nodes.includes('outer_a'));
    expect(outerA?.cost_usd).toBeCloseTo(0.1, 6);
    const innerB1 = Object.values(ledger).find((b) => b.nodes.includes('inner_b1'));
    expect(innerB1?.cost_usd).toBeCloseTo(0.05, 6);
    const innerB2 = Object.values(ledger).find((b) => b.nodes.includes('inner_b2'));
    expect(innerB2?.cost_usd).toBeCloseTo(0.03, 6);
  });
});

// In-progress run: parallel.started without parallel.completed yet.
const LIVE_EVENTS: AnyEvent[] = [
  ev({ event_type: 'parallel.started', sequence: 1, source_node: 'fan', target_nodes: ['w1', 'w2'], timestamp: ts(0) } as AnyEvent),
  ev({ event_type: 'node.started', sequence: 2, node_id: 'w1', timestamp: ts(1) } as AnyEvent),
  ev({ event_type: 'llm.called', sequence: 3, node_id: 'w1', cost_usd: 0.007, model: 'gpt-4', agent_name: 'w', input_tokens: 0, output_tokens: 0 } as AnyEvent),
];

describe('buildBranchLedger — live (no parallel.completed)', () => {
  it('branches are present but completed_at is absent', () => {
    const ledger = buildBranchLedger(LIVE_EVENTS);
    expect(Object.keys(ledger)).toHaveLength(2);
    for (const b of Object.values(ledger)) {
      expect(b.completed_at).toBeUndefined();
    }
  });

  it('accumulates cost as events stream in', () => {
    const ledger = buildBranchLedger(LIVE_EVENTS);
    const w1 = Object.values(ledger).find((b) => b.nodes.includes('w1'));
    expect(w1?.cost_usd).toBeCloseTo(0.007, 6);
  });
});

// Fallback: join_node absent in graphInfo — documented limitation.
describe('buildBranchLedger — missing join_node fallback', () => {
  it('still attributes to declared branches list when graphInfo is empty', () => {
    const ledger = buildBranchLedger(FLAT_EVENTS, {});
    expect(Object.keys(ledger)).toHaveLength(2);
    const total = ledgerTotal(ledger);
    expect(total).toBeCloseTo(0.05, 6);
  });
});
