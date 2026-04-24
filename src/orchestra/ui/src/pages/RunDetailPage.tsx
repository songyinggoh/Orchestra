import { useEffect, useMemo, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import {
  ReactFlow, Background, Controls, MiniMap, type Node,
} from '@xyflow/react';
import { toast } from 'sonner';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel,
  AlertDialogContent, AlertDialogDescription, AlertDialogFooter,
  AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { useUIStore } from '../stores/useUIStore';
import { useRunStore, getRunStore } from '../stores/useRunStore';
import { useSSE } from '../hooks/useSSE';
import { api, UnauthorizedError } from '../hooks/useApi';
import { layoutGraph } from '../hooks/useLayout';
import { NodeCard } from '../components/graph/NodeCard';
import { CostBar } from '../components/cost/CostBar';
import { ScrubberBar } from '../components/scrubber/ScrubberBar';
import { StateViewer } from '../components/state/StateViewer';
import { StateDiff } from '../components/state/StateDiff';
import { RunDetailShell } from '../layout/RunDetailShell';
import { projectState, useProjection } from '../lib/projectState';
import type { AnyEvent } from '../types/events';
import type { GraphInfo, RunStatus } from '../types/api';

const NODE_TYPES = { agent: NodeCard, terminal: NodeCard };

interface RunDetailPageProps {
  securityFilter?: boolean;
  costTab?: boolean;
}

export function RunDetailPage({ securityFilter, costTab }: RunDetailPageProps) {
  const { runId, sequence } = useParams<{ runId: string; sequence?: string }>();
  const navigate = useNavigate();
  const setSelectedSequence = useUIStore((s) => s.setSelectedSequence);
  const selectedSequence = useUIStore((s) => s.selectedSequence);
  const setTimelineFilter = useUIStore((s) => s.setTimelineFilter);
  const setRightPaneTab = useUIStore((s) => s.setRightPaneTab);

  // Seed UIStore from route params
  useEffect(() => {
    setSelectedSequence(sequence !== undefined ? parseInt(sequence, 10) : null);
  }, [sequence, setSelectedSequence]);

  // Update URL when the scrubber pushes a new sequence.
  const handleSequenceChange = useCallback(
    (next: number | null) => {
      if (!runId) return;
      setSelectedSequence(next);
      const path =
        next === null
          ? `/runs/${runId}`
          : `/runs/${runId}/@${next}`;
      navigate(path, { replace: true });
    },
    [runId, navigate, setSelectedSequence],
  );

  useEffect(() => {
    if (securityFilter) { setTimelineFilter({ type: 'security' }); setRightPaneTab('security'); }
    else if (costTab)   { setRightPaneTab('cost'); }
    else                { setTimelineFilter({ type: 'all' }); setRightPaneTab('timeline'); }
  }, [securityFilter, costTab, setTimelineFilter, setRightPaneTab]);

  const { data: runInfo } = useQuery<RunStatus>({
    queryKey: ['runs', runId],
    queryFn: () => api.getRun(runId!),
    enabled: !!runId,
  });

  const { data: graph } = useQuery<GraphInfo>({
    queryKey: ['graphs', runInfo?.workflow_name],
    queryFn: () => api.getGraph(runInfo!.workflow_name),
    enabled: !!runInfo?.workflow_name,
    staleTime: 60_000,
  });

  // Load historical events + state into the run store
  useEffect(() => {
    if (!runId) return;
    let active = true;
    (async () => {
      try {
        const [items, st] = await Promise.all([
          api.getEvents(runId),
          api.getState(runId).catch(() => null),
        ]);
        if (!active) return;
        const events = items.map((item) => ({
          event_type: item.event_type,
          event_id: item.event_id,
          run_id: item.run_id,
          sequence: item.sequence,
          timestamp: item.timestamp,
          schema_version: 1,
          ...item.data,
        } as AnyEvent));
        getRunStore(runId).getState().setInitial(events, st?.state ?? {});
      } catch (e) {
        if (e instanceof UnauthorizedError) toast.error('Missing API key — check Settings');
      }
    })();
    return () => { active = false; };
  }, [runId]);

  // Wire graph topology into store
  useEffect(() => {
    if (runId && graph) getRunStore(runId).getState().setGraph(graph);
  }, [runId, graph]);

  // SSE for live runs
  const onEvent = useCallback((event: AnyEvent) => {
    if (runId) getRunStore(runId).getState().ingestEvent(event);
  }, [runId]);

  const onDone = useCallback(() => {
    if (runId) getRunStore(runId).getState().setSseConnected(false);
  }, [runId]);

  const onSseError = useCallback(() => {
    if (runId) getRunStore(runId).getState().incrementReconnect();
  }, [runId]);

  useSSE({
    runId: runInfo?.status === 'running' ? (runId ?? null) : null,
    onEvent, onDone, onError: onSseError,
  });

  // Live (full-stream) projection from the run store.
  const liveNodeStatuses = useRunStore(runId ?? '', (s) => s.nodeStatuses);
  const liveNodeData = useRunStore(runId ?? '', (s) => s.nodeData);
  const liveMetrics = useRunStore(runId ?? '', (s) => s.metrics);
  const liveState = useRunStore(runId ?? '', (s) => s.currentState);
  const events = useRunStore(runId ?? '', (s) => s.events);

  // Time-travel mode: when the user has scrubbed to a non-live sequence,
  // swap the live store projections for sequence-pinned projections.
  const liveHead = events.length === 0 ? null : events.length - 1;
  const inTimeTravel =
    selectedSequence !== null && liveHead !== null && selectedSequence < liveHead;
  const projection = useProjection(runId ?? '', inTimeTravel ? selectedSequence : null);

  const nodeStatuses = inTimeTravel ? projection.nodeStatuses : liveNodeStatuses;
  const nodeData = inTimeTravel ? projection.nodeData : liveNodeData;
  const metrics = inTimeTravel ? projection.metrics : liveMetrics;
  const currentState = inTimeTravel ? projection.state : liveState;

  // Previous state (for StateDiff left pane). Reuses the same reducer fold
  // at sequence-1 so the pure diff matches what the server would compute.
  const prevState = useMemo(() => {
    if (!inTimeTravel || selectedSequence === null) return {};
    if (selectedSequence <= 0) return {};
    return projectState(events, selectedSequence - 1);
  }, [events, inTimeTravel, selectedSequence]);

  const { nodes: baseNodes, edges } = useMemo(
    () => (graph ? layoutGraph(graph) : { nodes: [], edges: [] }),
    [graph],
  );

  const nodes: Node[] = useMemo(
    () => baseNodes.map((n) => ({
      ...n,
      data: {
        ...n.data,
        status: nodeStatuses[n.id],
        model: nodeData[n.id]?.model ?? null,
        costUsd: nodeData[n.id]?.cost,
        securityCount: nodeData[n.id]?.securityCount ?? 0,
      },
    })),
    [baseNodes, nodeStatuses, nodeData],
  );

  async function handleCancel() {
    if (!runId) return;
    try {
      await api.cancelRun(runId);
      toast.success('Run cancelled');
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  if (!runId) return null;

  const graphCanvas = (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-zinc-800 bg-zinc-900 px-4 py-2">
        <span className="text-sm font-medium text-zinc-300">
          {runInfo?.workflow_name ?? 'workflow'}
        </span>
        <span className="font-mono text-xs text-zinc-600">/ {runId.slice(0, 8)}</span>
        <div className="ml-auto flex items-center gap-2">
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="outline" size="sm" className="h-7 text-xs" disabled={runInfo?.status !== 'running'}>
                Cancel run
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Cancel this run?</AlertDialogTitle>
                <AlertDialogDescription>
                  The run will be stopped. This cannot be undone.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Keep running</AlertDialogCancel>
                <AlertDialogAction onClick={handleCancel}>Cancel run</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
          <Button variant="outline" size="sm" className="h-7 text-xs" disabled>
            Fork from latest — W2
          </Button>
        </div>
      </div>

      <CostBar
        status={metrics.status}
        elapsed={metrics.duration}
        tokens={metrics.totalTokens}
        cost={metrics.totalCost}
        calls={Object.values(nodeData).reduce((s, d) => s + d.toolCount, 0)}
      />

      <ScrubberBar
        events={events}
        selectedSequence={selectedSequence}
        onSequenceChange={handleSequenceChange}
        alwaysVisible={runInfo?.status !== 'running'}
      />

      <div className="flex-1 overflow-hidden">
        {graph ? (
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={NODE_TYPES}
            colorMode="dark"
            fitView
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable={true}
            minZoom={0.3}
            maxZoom={2}
            role="application"
            aria-label="workflow graph"
          >
            <Background gap={20} color="#27272a" />
            <Controls showInteractive={false} />
            <MiniMap
              nodeColor={(n) => {
                const s = (n.data as { status?: string }).status;
                if (s === 'running') return '#f59e0b';
                if (s === 'completed') return '#10b981';
                if (s === 'error') return '#ef4444';
                if (s === 'waiting') return '#8b5cf6';
                return '#3f3f46';
              }}
              maskColor="rgba(9,9,11,0.7)"
            />
          </ReactFlow>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-zinc-600">
            {metrics.status !== 'pending' ? 'Graph topology not available' : 'Loading…'}
          </div>
        )}
      </div>
    </div>
  );

  const stateViewer = inTimeTravel ? (
    <StateDiff
      before={prevState}
      after={currentState}
      beforeLabel={selectedSequence! > 0 ? `@${selectedSequence! - 1}` : 'initial'}
      afterLabel={`@${selectedSequence}`}
    />
  ) : (
    <StateViewer state={currentState} />
  );

  return (
    <RunDetailShell
      runId={runId}
      graphCanvas={graphCanvas}
      stateViewer={stateViewer}
    />
  );
}
