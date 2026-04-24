import { describe, it, expect } from 'vitest';
import {
  projectState,
  projectNodeStatuses,
  projectMetrics,
} from './projectState';
import type { AnyEvent } from '../types/events';
import fixtureEvents from '../test/fixtures/run-events.json';

const EVENTS = fixtureEvents as unknown as AnyEvent[];

describe('projectState', () => {
  it('returns empty state at sequence -1 (nothing applied yet)', () => {
    expect(projectState(EVENTS, -1)).toEqual({});
  });

  it('applies execution.started initial_state at seq 0', () => {
    expect(projectState(EVENTS, 0)).toEqual({ counter: 0, messages: [] });
  });

  it('applies node.completed.state_update (partial merge) at seq 3', () => {
    expect(projectState(EVENTS, 3)).toEqual({ counter: 1, messages: [] });
  });

  it('applies state.updated via field_updates path at seq 4 (G7 fix)', () => {
    // seq 4 has empty resulting_state and field_updates={messages:["hi"]}
    // Must merge, not replace.
    expect(projectState(EVENTS, 4)).toEqual({ counter: 1, messages: ['hi'] });
  });

  it('applies state.updated via resulting_state (full replace) at seq 7', () => {
    expect(projectState(EVENTS, 7)).toEqual({
      counter: 2,
      messages: ['hi', 'bye'],
    });
  });

  it('full projection (null) matches execution.completed.final_state', () => {
    expect(projectState(EVENTS, null)).toEqual({
      counter: 2,
      messages: ['hi', 'bye'],
    });
  });
});

describe('projectNodeStatuses', () => {
  it('node goes pending → running → completed across sequences', () => {
    expect(projectNodeStatuses(EVENTS, 0).greet).toBeUndefined();
    expect(projectNodeStatuses(EVENTS, 1).greet).toBe('running');
    expect(projectNodeStatuses(EVENTS, 3).greet).toBe('completed');
  });

  it('tracks two nodes independently at seq 5', () => {
    const s = projectNodeStatuses(EVENTS, 5);
    expect(s.greet).toBe('completed');
    expect(s.respond).toBe('running');
  });

  it('all nodes completed at end', () => {
    const s = projectNodeStatuses(EVENTS, null);
    expect(s.greet).toBe('completed');
    expect(s.respond).toBe('completed');
  });
});

describe('projectMetrics', () => {
  it('accumulates tokens and cost across llm.called events', () => {
    const m0 = projectMetrics(EVENTS, 1);
    expect(m0.tokens).toBe(0);
    expect(m0.cost).toBe(0);

    const m2 = projectMetrics(EVENTS, 2);
    expect(m2.tokens).toBe(15); // 10 + 5
    expect(m2.cost).toBeCloseTo(0.0015, 6);

    const m6 = projectMetrics(EVENTS, 6);
    expect(m6.tokens).toBe(43); // 15 + 20 + 8
    expect(m6.cost).toBeCloseTo(0.0043, 6);
  });

  it('reports elapsed duration only after execution.completed', () => {
    expect(projectMetrics(EVENTS, 6).elapsed).toBeNull();
    expect(projectMetrics(EVENTS, 9).elapsed).toBe(9000);
  });

  it('exposes per-node cost accumulation', () => {
    const m = projectMetrics(EVENTS, null);
    expect(m.nodeData.greet.cost).toBeCloseTo(0.0015, 6);
    expect(m.nodeData.respond.cost).toBeCloseTo(0.0028, 6);
  });
});

describe('property: projecting at final sequence equals live reduction', () => {
  // If projectState folds the same reducer as the live store, then
  // projecting at the last sequence must equal folding from start to end.
  it('stable across the fixture', () => {
    const maxSeq = Math.max(...EVENTS.map((e) => e.sequence));
    const projected = projectState(EVENTS, maxSeq);
    const live = projectState(EVENTS, null);
    expect(projected).toEqual(live);
  });
});
