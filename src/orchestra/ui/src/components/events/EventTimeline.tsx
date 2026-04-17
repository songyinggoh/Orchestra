/**
 * Virtualized event timeline — renders EventRow for each event in the store.
 * Respects useUIStore.timelineFilter.
 */

import { useMemo, useEffect, useRef } from 'react';
import { useUIStore } from '../../stores/useUIStore';
import { useRunStore } from '../../stores/useRunStore';
import { EventRow } from './EventRow';
import type { AnyEvent } from '../../types/events';

interface EventTimelineProps {
  runId: string;
}

function getNodeId(event: AnyEvent): string | null {
  if ('node_id' in event && typeof event.node_id === 'string') return event.node_id;
  return null;
}

export function EventTimeline({ runId }: EventTimelineProps) {
  const events = useRunStore(runId, (s) => s.events);
  const nodeData = useRunStore(runId, (s) => s.nodeData);
  const timelineFilter = useUIStore((s) => s.timelineFilter);
  const setTimelineFilter = useUIStore((s) => s.setTimelineFilter);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Build set of nodeIds that have at least one security event.
  const securityNodeIds = useMemo(() => {
    const ids = new Set<string>();
    for (const [nodeId, data] of Object.entries(nodeData)) {
      if (data.securityCount > 0) ids.add(nodeId);
    }
    return ids;
  }, [nodeData]);

  const SECURITY_TYPES = new Set<AnyEvent['event_type']>([
    'security.violation',
    'security.restricted_mode_entered',
    'input.rejected',
    'output.rejected',
  ]);

  const filtered = useMemo(() => {
    if (timelineFilter.type === 'all') return events;
    if (timelineFilter.type === 'security') {
      return events.filter((e) => SECURITY_TYPES.has(e.event_type));
    }
    if (timelineFilter.type === 'node') {
      return events.filter((e) => getNodeId(e) === timelineFilter.nodeId);
    }
    return events;
  }, [events, timelineFilter]);

  // Auto-scroll to bottom when new events arrive (only when filter is 'all').
  useEffect(() => {
    if (timelineFilter.type === 'all') {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [events.length, timelineFilter.type]);

  if (events.length === 0) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-zinc-600">No events yet</p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Filter bar */}
      {timelineFilter.type !== 'all' && (
        <div className="flex items-center gap-2 border-b border-zinc-800 px-3 py-1.5 text-xs">
          <span className="text-zinc-500">
            {timelineFilter.type === 'security'
              ? 'Security events only'
              : `Node: ${timelineFilter.nodeId}`}
          </span>
          <button
            className="ml-auto text-violet-400 hover:underline"
            onClick={() => setTimelineFilter({ type: 'all' })}
          >
            Clear filter
          </button>
        </div>
      )}

      <div
        className="flex-1 overflow-y-auto"
        role="feed"
        aria-label="Event timeline"
        aria-busy={false}
      >
        {filtered.map((event) => (
          <EventRow
            key={event.event_id}
            event={event}
            securityNodeIds={securityNodeIds}
          />
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="border-t border-zinc-800 px-3 py-1 text-xs text-zinc-600">
        {filtered.length} event{filtered.length !== 1 ? 's' : ''}
        {timelineFilter.type !== 'all' && ` (filtered from ${events.length})`}
      </div>
    </div>
  );
}
