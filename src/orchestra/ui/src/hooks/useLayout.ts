import { useMemo } from 'react';
import type { Node, Edge } from '@xyflow/react';
import dagre from '@dagrejs/dagre';
import type { GraphInfo } from '../types/api';

const NODE_WIDTH = 200;
const NODE_HEIGHT = 60;

/**
 * Convert Orchestra GraphInfo to layouted React Flow nodes + edges using Dagre.
 */
export function useLayout(graph: GraphInfo | null) {
  return useMemo(() => {
    if (!graph) return { nodes: [], edges: [] };
    return layoutGraph(graph);
  }, [graph]);
}

export function layoutGraph(graph: GraphInfo): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: 'TB', ranksep: 80, nodesep: 60 });

  // Add __start__ and __end__ virtual nodes
  const allNodeIds = ['__start__', ...graph.nodes, '__end__'];
  for (const id of allNodeIds) {
    g.setNode(id, { width: id.startsWith('__') ? 80 : NODE_WIDTH, height: id.startsWith('__') ? 40 : NODE_HEIGHT });
  }

  // Edge from start to entry point
  g.setEdge('__start__', graph.entry_point);

  // Process edges
  const rfEdges: Edge[] = [];
  let edgeIdx = 0;

  for (const edge of graph.edges) {
    const targets = Array.isArray(edge.target) ? edge.target : [edge.target];
    for (const t of targets) {
      const target = t === '__end__' || t === 'END' ? '__end__' : t;
      g.setEdge(edge.source, target);
      const isHandoff = edge.type === 'HandoffEdge';
      const isConditional = edge.type === 'ConditionalEdge';
      // Handoff edges use indigo-400 (--tag-handoff) rather than the
      // accent color. UI-SPEC §4.1 reserves violet-500 exclusively for
      // the 6 documented accent uses (primary CTA, active nav, selected
      // row, focus ring, progress, keyboard badge) — never for edges.
      rfEdges.push({
        id: `e-${edgeIdx++}`,
        source: edge.source,
        target,
        type: 'smoothstep',
        animated: edge.type === 'ParallelEdge',
        style: {
          stroke: isHandoff ? '#818cf8' : isConditional ? 'var(--status-warn)' : 'var(--text-3)',
          strokeDasharray: isHandoff ? '6 4' : undefined,
        },
        label: isHandoff ? 'handoff' : isConditional ? '?' : undefined,
      });
    }
  }

  // Add edge from start
  rfEdges.unshift({
    id: 'e-start',
    source: '__start__',
    target: graph.entry_point,
    type: 'smoothstep',
    style: { stroke: 'var(--text-3)' },
  });

  dagre.layout(g);

  const rfNodes: Node[] = allNodeIds.map((id) => {
    const pos = g.node(id);
    const isVirtual = id.startsWith('__');
    const w = isVirtual ? 80 : NODE_WIDTH;
    const h = isVirtual ? 40 : NODE_HEIGHT;
    return {
      id,
      type: isVirtual ? 'terminal' : 'agent',
      position: { x: pos.x - w / 2, y: pos.y - h / 2 },
      data: {
        label: isVirtual ? (id === '__start__' ? 'Start' : 'End') : id,
        nodeId: id,
      },
    };
  });

  return { nodes: rfNodes, edges: rfEdges };
}
