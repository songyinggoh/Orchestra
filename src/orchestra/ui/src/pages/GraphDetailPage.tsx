/**
 * GraphDetailPage — wraps the existing ReactFlow canvas from GraphBrowser.
 * Full migration (split from GraphBrowser.tsx) happens in T-6.1.9.
 */
import { useState } from 'react';
import { useParams } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { ReactFlow, Background, Controls, MiniMap } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Button } from '@/components/ui/button';
import { api } from '../hooks/useApi';
import { layoutGraph } from '../hooks/useLayout';
import { NewRunDialog } from '../components/run/NewRunDialog';
import type { GraphInfo } from '../types/api';

export function GraphDetailPage() {
  const { name } = useParams<{ name: string }>();
  const [newRunOpen, setNewRunOpen] = useState(false);
  const { data: graph, isLoading } = useQuery<GraphInfo>({
    queryKey: ['graphs', name],
    queryFn: () => api.getGraph(name!),
    enabled: !!name,
  });

  if (isLoading || !graph) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-zinc-500">Loading graph…</p>
      </div>
    );
  }

  const { nodes, edges } = layoutGraph(graph);

  return (
    <>
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-zinc-800 px-6 py-4">
        <div>
          <h1 className="text-base font-semibold text-zinc-100">{graph.name}</h1>
          <p className="text-xs text-zinc-500">
            {graph.nodes.length} nodes · {graph.edges.length} edges
          </p>
        </div>
        <Button
          size="sm"
          className="bg-violet-500 text-white hover:bg-violet-400"
          onClick={() => setNewRunOpen(true)}
        >
          Run this graph
        </Button>
      </header>
      <div className="flex-1">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          fitView
          colorMode="dark"
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#27272a" />
          <Controls />
          <MiniMap nodeColor="#52525b" maskColor="rgba(9,9,11,0.7)" />
        </ReactFlow>
      </div>
    </div>
    <NewRunDialog
      open={newRunOpen}
      onOpenChange={setNewRunOpen}
      workflowName={graph.name}
    />
    </>
  );
}
