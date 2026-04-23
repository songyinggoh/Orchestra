/**
 * Client-side state projection at arbitrary event sequences.
 *
 * Mirrors server's `project_state()` at `src/orchestra/storage/store.py:197`.
 * Consumed by the time-travel scrubber: given a run's event stream and a
 * target sequence, returns the state, node statuses, and metrics as they
 * would have appeared at that moment.
 *
 * Implementation folds the existing `eventReducer` (which already handles
 * all 21 event types) over the sliced event stream — one source of truth
 * for both live reducer and projection.
 */

import { useMemo } from 'react';
import { useRunStore } from '../stores/useRunStore';
import {
  eventReducer,
  initialReducerState,
  type NodeStatus,
  type NodeData,
  type RunMetrics,
  type ReducerState,
} from '../stores/eventReducer';
import type { AnyEvent } from '../types/events';

function sliceUpTo(events: AnyEvent[], upToSequence: number | null): AnyEvent[] {
  if (upToSequence === null) return events;
  return events.filter((e) => e.sequence <= upToSequence);
}

function fold(events: AnyEvent[], upToSequence: number | null): ReducerState {
  let state: ReducerState = { ...initialReducerState };
  for (const ev of sliceUpTo(events, upToSequence)) {
    state = { ...state, ...eventReducer(state, ev) };
  }
  return state;
}

export function projectState(
  events: AnyEvent[],
  upToSequence: number | null,
): Record<string, unknown> {
  return fold(events, upToSequence).currentState;
}

export function projectNodeStatuses(
  events: AnyEvent[],
  upToSequence: number | null,
): Record<string, NodeStatus> {
  return fold(events, upToSequence).nodeStatuses;
}

export interface ProjectedMetrics {
  tokens: number;
  cost: number;
  calls: number;
  elapsed: number | null;
  nodeData: Record<string, NodeData>;
}

export function projectMetrics(
  events: AnyEvent[],
  upToSequence: number | null,
): ProjectedMetrics {
  const s = fold(events, upToSequence);
  const calls = Object.values(s.nodeData).reduce((sum, n) => sum + n.toolCount, 0);
  return {
    tokens: s.metrics.totalTokens,
    cost: s.metrics.totalCost,
    calls,
    elapsed: s.metrics.duration,
    nodeData: s.nodeData,
  };
}

export interface Projection {
  state: Record<string, unknown>;
  nodeStatuses: Record<string, NodeStatus>;
  metrics: RunMetrics;
  nodeData: Record<string, NodeData>;
}

/**
 * React hook: project the run store's events at `sequence`. Memoized on
 * (events reference, sequence) — a single O(N) fold per change. For
 * typical runs (<1000 events) this is <200ms even without bucketed caching.
 */
export function useProjection(runId: string, sequence: number | null): Projection {
  const events = useRunStore(runId, (s) => s.events);
  return useMemo(() => {
    const folded = fold(events, sequence);
    return {
      state: folded.currentState,
      nodeStatuses: folded.nodeStatuses,
      metrics: folded.metrics,
      nodeData: folded.nodeData,
    };
  }, [events, sequence]);
}
