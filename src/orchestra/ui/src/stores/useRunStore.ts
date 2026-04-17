/**
 * Per-run state store. One instance per open run (keyed by runId).
 * Consumers use `useRunStore(runId)` which returns a stable store reference.
 */

import { createStore, useStore } from 'zustand';
import { subscribeWithSelector } from 'zustand/middleware';
import type { AnyEvent } from '../types/events';
import type { GraphInfo } from '../types/api';
import {
  eventReducer,
  initialReducerState,
  type NodeStatus,
  type NodeData,
  type RunMetrics,
} from './eventReducer';

export interface RunSlice {
  // Data
  graph: GraphInfo | null;
  events: AnyEvent[];
  nodeStatuses: Record<string, NodeStatus>;
  nodeData: Record<string, NodeData>;
  currentState: Record<string, unknown>;
  metrics: RunMetrics;
  // SSE connection state
  sseConnected: boolean;
  reconnectAttempts: number;
  // Actions
  setGraph: (graph: GraphInfo) => void;
  setInitial: (events: AnyEvent[], state: Record<string, unknown>) => void;
  ingestEvent: (event: AnyEvent) => void;
  setSseConnected: (connected: boolean) => void;
  incrementReconnect: () => void;
  reset: () => void;
}

type RunStore = ReturnType<typeof createRunStore>;

function createRunStore() {
  return createStore<RunSlice>()(
    subscribeWithSelector((set, get) => ({
      graph: null,
      events: [],
      nodeStatuses: {},
      nodeData: {},
      currentState: {},
      metrics: { ...initialReducerState.metrics },
      sseConnected: false,
      reconnectAttempts: 0,

      setGraph(graph) {
        set({ graph });
      },

      setInitial(events, state) {
        // Replay all events through the reducer to rebuild derived state.
        let reducerState = { ...initialReducerState, currentState: state };
        for (const ev of events) {
          const patch = eventReducer(reducerState, ev);
          reducerState = { ...reducerState, ...patch };
        }
        set({
          events,
          currentState: reducerState.currentState,
          nodeStatuses: reducerState.nodeStatuses,
          nodeData: reducerState.nodeData,
          metrics: reducerState.metrics,
        });
      },

      ingestEvent(event) {
        const s = get();
        const reducerState = {
          nodeStatuses: s.nodeStatuses,
          nodeData: s.nodeData,
          currentState: s.currentState,
          metrics: s.metrics,
        };
        const patch = eventReducer(reducerState, event);
        set({
          events: [...s.events, event],
          ...patch,
        });
      },

      setSseConnected(connected) {
        set({ sseConnected: connected, ...(connected ? { reconnectAttempts: 0 } : {}) });
      },

      incrementReconnect() {
        set((s) => ({ reconnectAttempts: s.reconnectAttempts + 1 }));
      },

      reset() {
        set({
          graph: null,
          events: [],
          nodeStatuses: {},
          nodeData: {},
          currentState: {},
          metrics: { ...initialReducerState.metrics },
          sseConnected: false,
          reconnectAttempts: 0,
        });
      },
    })),
  );
}

// Registry so each runId gets exactly one store instance.
const registry = new Map<string, RunStore>();

export function getRunStore(runId: string): RunStore {
  if (!registry.has(runId)) {
    registry.set(runId, createRunStore());
  }
  return registry.get(runId)!;
}

export function disposeRunStore(runId: string): void {
  registry.delete(runId);
}

/** React hook: subscribe to a run-scoped store with an optional selector. */
export function useRunStore<T>(
  runId: string,
  selector: (state: RunSlice) => T,
): T {
  const store = getRunStore(runId);
  return useStore(store, selector);
}

/** Access the full slice without a selector (re-renders on every change). */
export function useRunSlice(runId: string): RunSlice {
  return useRunStore(runId, (s) => s);
}
