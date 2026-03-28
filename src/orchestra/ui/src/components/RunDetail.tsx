import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
} from '@xyflow/react';
import { api } from '../hooks/useApi';
import { useSSE } from '../hooks/useSSE';
import { useLayout } from '../hooks/useLayout';
import { AgentNode } from './AgentNode';
import { TerminalNode } from './TerminalNode';
import { EventTimeline } from './EventTimeline';
import { CostBar } from './CostBar';
import { StateViewer } from './StateViewer';
import type { GraphInfo } from '../types/api';
import type { AnyEvent } from '../types/events';
import type { AgentNodeData } from './AgentNode';

const nodeTypes = {
  agent: AgentNode,
  terminal: TerminalNode,
};

interface RunDetailProps {
  runId: string;
  onBack: () => void;
}

interface RunMetrics {
  status: string;
  elapsed: number | null;
  tokens: number;
  cost: number;
  calls: number;
  workflowName: string;
}

export function RunDetail({ runId, onBack }: RunDetailProps) {
  const [graph, setGraph] = useState<GraphInfo | null>(null);
  const [events, setEvents] = useState<AnyEvent[]>([]);
  const [state, setState] = useState<Record<string, unknown>>({});
  const [metrics, setMetrics] = useState<RunMetrics>({
    status: 'running',
    elapsed: null,
    tokens: 0,
    cost: 0,
    calls: 0,
    workflowName: '',
  });

  // Node status tracking
  const [nodeStatuses, setNodeStatuses] = useState<Record<string, AgentNodeData['status']>>({});
  const [nodeData, setNodeData] = useState<Record<string, Partial<AgentNodeData>>>({});

  // Load graph info and historical events on mount
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const runInfo = await api.getRun(runId);
        if (!active) return;
        setMetrics((m) => ({ ...m, status: runInfo.status, workflowName: runInfo.workflow_name }));

        // Load graph topology
        if (runInfo.workflow_name) {
          try {
            const g = await api.getGraph(runInfo.workflow_name);
            if (active) setGraph(g);
          } catch { /* graph may not be registered anymore */ }
        }

        // Load historical events
        const items = await api.getEvents(runId);
        if (!active) return;
        const parsed = items.map((item) => ({
          event_type: item.event_type,
          sequence: item.sequence,
          event_id: item.event_id,
          ...item.data,
        } as AnyEvent));
        setEvents(parsed);
        processEvents(parsed);

        // Load state
        try {
          const st = await api.getState(runId);
          if (active) setState(st.state);
        } catch { /* no state yet */ }
      } catch { /* run may not exist */ }
    })();
    return () => { active = false; };
  }, [runId]); // eslint-disable-line react-hooks/exhaustive-deps

  const processEvents = useCallback((evts: AnyEvent[]) => {
    const statuses: Record<string, AgentNodeData['status']> = {};
    const data: Record<string, Partial<AgentNodeData>> = {};
    let tokens = 0;
    let cost = 0;
    let calls = 0;
    let elapsed: number | null = null;
    let status = 'running';
    let workflowName = '';

    for (const e of evts) {
      const rec = e as unknown as Record<string, unknown>;
      switch (e.event_type) {
        case 'execution.started':
          workflowName = (rec.workflow_name as string) || '';
          break;
        case 'execution.completed':
          elapsed = (rec.duration_ms as number) ?? null;
          status = (rec.status as string) || 'completed';
          break;
        case 'node.started':
          statuses[rec.node_id as string] = 'running';
          break;
        case 'node.completed':
          statuses[rec.node_id as string] = 'completed';
          data[rec.node_id as string] = {
            ...data[rec.node_id as string],
            durationMs: rec.duration_ms as number,
          };
          break;
        case 'error.occurred':
          statuses[rec.node_id as string] = 'error';
          break;
        case 'llm.called':
          tokens += ((rec.input_tokens as number) || 0) + ((rec.output_tokens as number) || 0);
          cost += (rec.cost_usd as number) || 0;
          calls++;
          data[rec.node_id as string] = {
            ...data[rec.node_id as string],
            model: rec.model as string,
            costUsd: (data[rec.node_id as string]?.costUsd ?? 0) + ((rec.cost_usd as number) || 0),
            tokens: (data[rec.node_id as string]?.tokens ?? 0) + ((rec.input_tokens as number) || 0) + ((rec.output_tokens as number) || 0),
          };
          break;
        case 'state.updated':
          if (rec.resulting_state) setState(rec.resulting_state as Record<string, unknown>);
          break;
      }
    }

    setNodeStatuses((prev) => ({ ...prev, ...statuses }));
    setNodeData((prev) => {
      const merged = { ...prev };
      for (const [k, v] of Object.entries(data)) {
        merged[k] = { ...merged[k], ...v };
      }
      return merged;
    });
    setMetrics((m) => ({
      ...m,
      tokens: m.tokens + tokens,
      cost: m.cost + cost,
      calls: m.calls + calls,
      elapsed: elapsed ?? m.elapsed,
      status: status !== 'running' ? status : m.status,
      workflowName: workflowName || m.workflowName,
    }));
  }, []);

  // SSE for live events
  const onEvent = useCallback((event: AnyEvent) => {
    setEvents((prev) => [...prev, event]);
    processEvents([event]); // incremental update
  }, [processEvents]);

  const onDone = useCallback(() => {
    setMetrics((m) => ({ ...m, status: m.status === 'running' ? 'completed' : m.status }));
  }, []);

  useSSE({
    runId: metrics.status === 'running' ? runId : null,
    onEvent,
    onDone,
  });

  // Apply node statuses to layouted nodes
  const { nodes: baseNodes, edges: baseEdges } = useLayout(graph);

  const nodes: Node[] = useMemo(
    () =>
      baseNodes.map((n) => ({
        ...n,
        data: {
          ...n.data,
          status: nodeStatuses[n.id],
          ...nodeData[n.id],
        },
      })),
    [baseNodes, nodeStatuses, nodeData],
  );

  const edges: Edge[] = useMemo(
    () =>
      baseEdges.map((e) => ({
        ...e,
        animated: nodeStatuses[e.source] === 'running' || e.animated,
      })),
    [baseEdges, nodeStatuses],
  );

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-zinc-800 bg-zinc-900">
        <button onClick={onBack} className="text-zinc-500 hover:text-zinc-300 text-sm">{'\u2190'} Runs</button>
        <span className="text-sm text-zinc-300 font-medium">
          {metrics.workflowName || 'workflow'}
        </span>
        <span className="text-xs text-zinc-600 font-mono">/ {runId.slice(0, 8)}</span>
      </div>

      {/* Cost/Status bar */}
      <CostBar
        status={metrics.status}
        elapsed={metrics.elapsed}
        tokens={metrics.tokens}
        cost={metrics.cost}
        calls={metrics.calls}
      />

      {/* Main content: graph (left) + timeline (right) */}
      <div className="flex-1 flex min-h-0">
        {/* Graph panel */}
        <div className="flex-1 min-w-0">
          {graph ? (
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
              <MiniMap
                nodeColor={(n) => {
                  const s = (n.data as unknown as AgentNodeData)?.status;
                  if (s === 'running') return '#f59e0b';
                  if (s === 'completed') return '#10b981';
                  if (s === 'error') return '#ef4444';
                  return '#3f3f46';
                }}
                style={{ background: '#0a0a0f' }}
              />
            </ReactFlow>
          ) : (
            <div className="flex items-center justify-center h-full text-zinc-600 text-sm">
              {events.length > 0 ? 'Graph topology not available' : 'Loading...'}
            </div>
          )}
        </div>

        {/* Timeline panel */}
        <div className="w-[380px] border-l border-zinc-800 flex flex-col bg-zinc-900/30">
          <div className="px-3 py-2 border-b border-zinc-800">
            <span className="text-[11px] font-medium text-zinc-400">
              Events ({events.length})
            </span>
          </div>
          <div className="flex-1 min-h-0">
            <EventTimeline events={events} />
          </div>
        </div>
      </div>

      {/* State viewer */}
      <StateViewer state={state} />
    </div>
  );
}
