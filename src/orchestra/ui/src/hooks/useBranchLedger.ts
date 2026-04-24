import { useMemo } from 'react';
import { useRunStore } from '../stores/useRunStore';
import { buildBranchLedger } from '../lib/branchLedger';
import type { BranchLedger } from '../lib/branchLedger';
import type { GraphInfo } from '../types/api';

function joinNodeMap(graph: GraphInfo | null): Record<string, string | null> {
  if (!graph) return {};
  const map: Record<string, string | null> = {};
  for (const edge of graph.edges) {
    if (edge.type === 'ParallelEdge') {
      const jn = (edge as unknown as { join_node?: string | null }).join_node ?? null;
      map[edge.source] = jn;
    }
  }
  return map;
}

export function useBranchLedger(runId: string): BranchLedger {
  const events = useRunStore(runId, (s) => s.events);
  const graph = useRunStore(runId, (s) => s.graph);
  return useMemo(() => buildBranchLedger(events, joinNodeMap(graph)), [events, graph]);
}
