/**
 * RunDetailShell — wraps RunDetailPage; provides the horizontal split layout
 * (ReactFlow canvas on left, tabbed RightPane on right).
 */

import { type ReactNode } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useUIStore } from '../stores/useUIStore';
import { EventTimeline } from '../components/events/EventTimeline';
import { CostBreakdownPanel } from '../components/cost/CostBreakdownPanel';

interface RunDetailShellProps {
  runId: string;
  graphCanvas: ReactNode;
  stateViewer: ReactNode;
}

export function RunDetailShell({ runId, graphCanvas, stateViewer }: RunDetailShellProps) {
  const rightPaneTab = useUIStore((s) => s.rightPaneTab);
  const setRightPaneTab = useUIStore((s) => s.setRightPaneTab);
  const setTimelineFilter = useUIStore((s) => s.setTimelineFilter);

  function handleTabChange(tab: string) {
    const t = tab as typeof rightPaneTab;
    setRightPaneTab(t);
    if (t === 'security') setTimelineFilter({ type: 'security' });
    else if (t === 'timeline') setTimelineFilter({ type: 'all' });
  }

  return (
    <div className="flex h-full min-h-0 flex-1">
      {/* Left: ReactFlow canvas */}
      <div className="flex-1 overflow-hidden">{graphCanvas}</div>

      {/* Right pane: tabbed */}
      <div className="flex w-96 flex-col border-l border-zinc-800 bg-zinc-950">
        <Tabs
          value={rightPaneTab}
          onValueChange={handleTabChange}
          className="flex h-full flex-col"
        >
          <TabsList className="flex-shrink-0 rounded-none border-b border-zinc-800 bg-transparent px-3 py-0 h-9">
            <TabsTrigger value="timeline" className="text-xs">Timeline</TabsTrigger>
            <TabsTrigger value="state"    className="text-xs">State</TabsTrigger>
            <TabsTrigger value="cost"     className="text-xs">Cost</TabsTrigger>
            <TabsTrigger value="security" className="text-xs">Security</TabsTrigger>
          </TabsList>

          <TabsContent value="timeline" className="mt-0 flex-1 overflow-hidden">
            <EventTimeline runId={runId} />
          </TabsContent>

          <TabsContent value="state" className="mt-0 flex-1 overflow-auto p-2">
            {stateViewer}
          </TabsContent>

          <TabsContent value="cost" className="mt-0 flex-1 overflow-hidden">
            <CostBreakdownPanel runId={runId} />
          </TabsContent>

          <TabsContent value="security" className="mt-0 flex-1 overflow-hidden">
            <EventTimeline runId={runId} />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
