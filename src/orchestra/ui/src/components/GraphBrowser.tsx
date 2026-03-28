import { useEffect, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
} from '@xyflow/react';
import { api } from '../hooks/useApi';
import { useLayout } from '../hooks/useLayout';
import { AgentNode } from './AgentNode';
import { TerminalNode } from './TerminalNode';
import type { GraphInfo } from '../types/api';

const nodeTypes = {
  agent: AgentNode,
  terminal: TerminalNode,
};

interface GraphBrowserProps {
  onBack: () => void;
}

export function GraphBrowser({ onBack }: GraphBrowserProps) {
  const [graphs, setGraphs] = useState<GraphInfo[]>([]);
  const [selected, setSelected] = useState<GraphInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listGraphs()
      .then(setGraphs)
      .catch((e) => setError((e as Error).message));
  }, []);

  const { nodes, edges } = useLayout(selected);

  return (
    <div className="flex h-full">
      {/* Sidebar */}
      <div className="w-48 border-r border-zinc-800 flex flex-col bg-zinc-900/50">
        <div className="px-3 py-2 border-b border-zinc-800 flex items-center gap-2">
          <button onClick={onBack} className="text-zinc-500 hover:text-zinc-300 text-sm">{'\u2190'}</button>
          <span className="text-[11px] font-medium text-zinc-400">Graphs</span>
        </div>
        <div className="flex-1 overflow-y-auto scroll-thin p-2">
          {graphs.map((g) => (
            <button
              key={g.name}
              onClick={() => setSelected(g)}
              className={`w-full text-left px-2 py-1.5 rounded text-xs transition-colors ${
                selected?.name === g.name ? 'bg-zinc-700/50 text-zinc-200' : 'text-zinc-400 hover:bg-zinc-800/50'
              }`}
            >
              {g.name}
            </button>
          ))}
          {graphs.length === 0 && !error && (
            <div className="text-zinc-600 text-xs text-center py-4">No graphs registered</div>
          )}
          {error && (
            <div className="text-red-400 text-xs p-2">{error}</div>
          )}
        </div>
      </div>

      {/* Graph view */}
      <div className="flex-1 flex flex-col">
        {selected ? (
          <>
            <div className="px-4 py-2 border-b border-zinc-800 bg-zinc-900 flex items-center gap-4">
              <span className="text-sm text-zinc-300 font-medium">{selected.name}</span>
              <span className="text-[10px] text-zinc-600 font-mono">
                {selected.nodes.length} nodes \u00B7 {selected.edges.length} edges \u00B7 entry: {selected.entry_point}
              </span>
            </div>
            <div className="flex-1">
              <ReactFlow
                nodes={nodes}
                edges={edges}
                nodeTypes={nodeTypes}
                colorMode="dark"
                fitView
                nodesDraggable={false}
                nodesConnectable={false}
                elementsSelectable={false}
                minZoom={0.3}
                maxZoom={2}
              >
                <Background gap={20} color="#1a1a2e" />
                <Controls showInteractive={false} />
                <MiniMap style={{ background: '#0a0a0f' }} />
              </ReactFlow>
            </div>
          </>
        ) : (
          <div className="flex items-center justify-center h-full text-zinc-600 text-sm">
            Select a graph to view its topology
          </div>
        )}
      </div>
    </div>
  );
}
